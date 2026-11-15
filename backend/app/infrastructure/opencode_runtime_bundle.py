"""Read-only inventory check for an independently prepared OC20-CONFIG-1 bundle."""

import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic

from backend.app.shared.validation import strict_integer, strict_json_object

from .content_paths import ContentPathIndex
from .windows_config_source import LockedFileSource
from .windows_local_paths import LocalPathGuard, local_absolute_path

REF_PREFIX = 'opencode-bundle:sha256:'

MAX_FILES = 20_000
MAX_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_CONTROL_BYTES = 8 * 1024 * 1024
CONFIG = 'opencode.json'
PLUGIN_NAME = '@opencode-ai/plugin'
PLUGIN_VERSION = '1.19.5'
PLUGIN_ROOT = 'node_modules/' + PLUGIN_NAME
PLUGIN_MANIFEST = PLUGIN_ROOT + '/package.json'
CONTROLS = frozenset((CONFIG, 'package.json', 'package-lock.json', PLUGIN_MANIFEST))
REQUIRED = CONTROLS | {'.gitignore'}
DEPENDENCY_GROUPS = ('dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies')
ISOLATION_SETTINGS = {
    '$schema': 'https://opencode.ai/config.json',
    'plugin': [],
    'mcp': {},
    'lsp': False,
    'formatter': False,
    'share': 'disabled',
    'autoupdate': False,
}


def is_opencode_runtime_bundle_ref(value):
    return type(value) is str and re.fullmatch(REF_PREFIX + '[0-9a-f]{64}', value) is not None


class OpenCodeRuntimeBundleError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenCodeRuntimeBundle:
    manifest: Path = field(repr=False)
    root: Path = field(repr=False)

    def __post_init__(self):
        manifest = local_absolute_path(self.manifest)
        root = local_absolute_path(self.root)
        if manifest.is_relative_to(root):
            raise OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_MANIFEST_MUST_BE_OUTSIDE_TREE')
        object.__setattr__(self, 'manifest', manifest)
        object.__setattr__(self, 'root', root)


@dataclass(frozen=True)
class TaskRuntimeBundleDeployment:
    source: OpenCodeRuntimeBundle
    reference: str

    def __post_init__(self):
        if type(self.source) is not OpenCodeRuntimeBundle or not is_opencode_runtime_bundle_ref(
            self.reference
        ):
            raise OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_DEPLOYMENT_REQUIRED')


def _inventory(raw, root, checkpoint):
    data = strict_json_object(raw)
    if (
        set(data) != {'schema_version', 'configuration_policy', 'members'}
        or strict_integer(data['schema_version'], 'schema_version') != 1
        or data['configuration_policy'] != 'OC20-CONFIG-1'
        or type(data['members']) is not list
        or not 1 <= len(data['members']) <= MAX_FILES
    ):
        raise OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_MANIFEST_INVALID')
    namespace = ContentPathIndex(materialization_root=root)
    files, directories = {}, set()
    total = 0
    for row in data['members']:
        checkpoint()
        if type(row) is not dict or set(row) != {'path', 'byte_count', 'sha256'}:
            raise OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_MEMBER_INVALID')
        path = namespace.add_file(row['path'], '100644').path
        size = strict_integer(row['byte_count'], 'byte_count', minimum=0)
        total += size
        digest = row['sha256']
        if (
            type(digest) is not str
            or re.fullmatch('[0-9a-f]{64}', digest) is None
            or total > MAX_BYTES
            or (path in CONTROLS and size > MAX_CONTROL_BYTES)
        ):
            raise OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_MEMBER_INVALID')
        files[path] = (size, digest)
        parts = path.split('/')
        directories.update('/'.join(parts[:count]) for count in range(1, len(parts)))
    if not REQUIRED <= files.keys():
        raise OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_REQUIRED_FILES_MISSING')
    return files, directories


def _verify_tree(root, identity, files, directories, checkpoint, *, original=None, consume=None):
    remaining = set(files)
    directories = set(directories)
    members = {}
    pending = [('', root, identity)]
    controls = {}
    while pending:
        prefix, path, expected = pending.pop()
        with LocalPathGuard(path, directory=True) as current, os.scandir(path) as listing:
            if current.verify() != expected:
                raise OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_DIRECTORY_CHANGED')
            for child in listing:
                checkpoint()
                name = prefix + child.name
                target = path / child.name
                if name in directories:
                    with LocalPathGuard(target, directory=True) as directory:
                        member = directory.verify()
                        if original is not None and original[name] != member:
                            raise OpenCodeRuntimeBundleError(
                                'OPENCODE_RUNTIME_MEMBER_IDENTITY_DIFFERS'
                            )
                        members[name] = member
                        pending.append((name + '/', target, member))
                        if consume is not None:
                            consume(name, member, None)
                    directories.remove(name)
                    continue
                if name not in remaining:
                    raise OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_TREE_DIFFERS')
                size, digest = files[name]
                expected_file = None if original is None else original[name]
                with LockedFileSource(
                    target,
                    max_file_bytes=max(size, 1),
                    expected_file=expected_file,
                    capture_raw=name in CONTROLS or consume is not None,
                    checkpoint=checkpoint,
                ) as lease:
                    blob = lease.snapshot
                    if (blob.byte_count, blob.sha256) != (size, digest):
                        raise OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_MEMBER_DIFFERS')
                    members[name] = blob.file
                    if name in CONTROLS:
                        controls[name] = strict_json_object(blob.raw)
                    if consume is not None:
                        consume(name, blob.file, blob.raw)
                remaining.remove(name)
    if remaining or directories:
        raise OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_TREE_DIFFERS')
    return controls, members


def _declared_dependencies(package):
    declared = {}
    for group in DEPENDENCY_GROUPS:
        values = package.get(group, {})
        if type(values) is not dict or any(type(value) is not str for value in values.values()):
            raise OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_DEPENDENCIES_INVALID')
        if values:
            declared[group] = values
    return declared


def _verify_control_files(controls, files):
    config = controls[CONFIG]
    for name, expected in ISOLATION_SETTINGS.items():
        value = config.get(name)
        if type(value) is not type(expected) or value != expected:
            raise OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_CONFIGURATION_DIFFERS')
    if config.get('instructions', []) != [] or config.get('experimental', {}) != {}:
        raise OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_CONFIGURATION_DIFFERS')
    lock = controls['package-lock.json'].get('packages')
    locked_root = lock.get('') if type(lock) is dict else None
    declared = _declared_dependencies(controls['package.json'])
    if type(locked_root) is not dict or declared != _declared_dependencies(locked_root):
        raise OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_DEPENDENCY_LOCK_DIFFERS')
    plugin = controls[PLUGIN_MANIFEST]
    locked_plugin = lock.get(PLUGIN_ROOT)
    if (
        declared.get('dependencies', {}).get(PLUGIN_NAME) != PLUGIN_VERSION
        or type(locked_plugin) is not dict
        or locked_plugin.get('version') != PLUGIN_VERSION
        or plugin.get('name') != PLUGIN_NAME
        or plugin.get('version') != PLUGIN_VERSION
    ):
        raise OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_REQUIRED_PLUGIN_DIFFERS')
    for path, entry in lock.items():
        if path == '':
            continue
        if (
            not path.startswith('node_modules/')
            or type(entry) is not dict
            or entry.get('link', False) is not False
            or (entry.get('optional', False) is not True and path + '/package.json' not in files)
        ):
            raise OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_LOCKED_PACKAGE_MISSING')


class _HeldRuntimeBundle:
    def __init__(self, source, manifest, root, files, directories, members, checkpoint):
        self.source = source
        self._manifest, self._root = manifest, root
        self.files, self.directories = files, directories
        self._members, self._checkpoint = members, checkpoint
        self.identity = root.verify()

    def visit(self, consume):
        self._checkpoint()
        self._manifest.verify()
        if self._root.verify() != self.identity:
            raise OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_DIRECTORY_CHANGED')
        controls, _ = _verify_tree(
            self.source.root,
            self.identity,
            self.files,
            self.directories,
            self._checkpoint,
            original=self._members,
            consume=consume,
        )
        _verify_control_files(controls, self.files)
        self._manifest.verify()
        self._root.verify()
        self._checkpoint()


@contextmanager
def hold_opencode_runtime_bundle(source, runtime_bundle_ref, *, deadline, cancelled):
    """Hold the original manifest and root and revisit only original member identities."""

    def checkpoint():
        if cancelled() or monotonic() >= deadline:
            raise OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_CHECK_INTERRUPTED')

    checkpoint()
    with LockedFileSource(source.manifest, max_file_bytes=MAX_MANIFEST_BYTES) as manifest:
        snapshot = manifest.snapshot
        if runtime_bundle_ref != REF_PREFIX + snapshot.sha256:
            raise OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_MANIFEST_DIGEST_DIFFERS')
        files, directories = _inventory(snapshot.raw, source.root, checkpoint)
        with LocalPathGuard(source.root, directory=True) as root:
            identity = root.verify()
            controls, members = _verify_tree(source.root, identity, files, directories, checkpoint)
            _verify_control_files(controls, files)
            if root.verify() != identity:
                raise OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_DIRECTORY_CHANGED')
            checkpoint()
            yield _HeldRuntimeBundle(
                source, manifest, root, files, directories, members, checkpoint
            )


def verify_opencode_runtime_bundle(source, runtime_bundle_ref, *, deadline, cancelled):
    """Verify a snapshot of the fixed inventory; a launch must recheck OS access."""
    with hold_opencode_runtime_bundle(
        source, runtime_bundle_ref, deadline=deadline, cancelled=cancelled
    ) as original:
        return len(original.files)
