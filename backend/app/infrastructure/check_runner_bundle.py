"""Read an immutable CHECK20 runner manifest and its protected Windows closure."""

import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import monotonic

from backend.app.shared.validation import strict_integer, strict_json_object

from .content_paths import ContentPathIndex
from .windows_config_source import LockedFileSource
from .windows_local_paths import FileIdentity
from .windows_private_package import PrivatePackageGuard
from .windows_task_workspace_tree import _scan_task_workspace_tree, workspace_tree_sha256

CHECK_PROTOCOL = 'CHECK20-CONTROL-1'
CHECK_CAPABILITIES = frozenset({'CONTENT_INTEGRITY', 'CLI', 'HTTP', 'BROWSER'})
_MANIFEST = 'manifest.json'
_MAX_MANIFEST_BYTES = 1024**2
_MAX_ENTRIES = 16384
_MAX_BYTES = 2 * 1024**3
_REFERENCE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}')
_SHA256 = re.compile('[a-f0-9]{64}')


class CheckResourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class RunnerFile:
    path: str
    sha256: str
    byte_count: int


@dataclass(frozen=True)
class RunnerManifest:
    bundle_id: str
    version: str
    entry_ref: str
    runtime_refs: tuple[str, ...]
    file_entries: tuple[RunnerFile, ...]
    capabilities: tuple[str, ...]
    platform_refs: tuple[str, ...]
    admission_evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class RegisteredCheckRunner:
    """Only installation code supplies the original directory and digest."""

    directory: FileIdentity = field(repr=False)
    manifest_sha256: str
    bundle_id: str
    version: str

    def __post_init__(self):
        if (
            type(self.directory) is not FileIdentity
            or not self.directory.is_directory
            or self.directory.filesystem != 'NTFS'
            or not valid_sha256(self.manifest_sha256)
        ):
            raise CheckResourceError('ORIGINAL_CHECK_RUNNER_SOURCE_REQUIRED')
        reference(self.bundle_id)
        reference(self.version)


def valid_sha256(value):
    return type(value) is str and _SHA256.fullmatch(value) is not None


def reference(value):
    if type(value) is not str or _REFERENCE.fullmatch(value) is None:
        raise CheckResourceError('CHECK_RESOURCE_REFERENCE_INVALID')
    return value


def exact_record(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise CheckResourceError('CHECK_RESOURCE_FIELDS_INVALID')
    return value


def references(values, *, nonempty=False):
    if type(values) is not list or len(values) > 256 or nonempty and not values:
        raise CheckResourceError('CHECK_RESOURCE_REFERENCES_INVALID')
    refs = tuple(reference(value) for value in values)
    if len(set(refs)) != len(refs):
        raise CheckResourceError('CHECK_RESOURCE_REFERENCES_INVALID')
    return refs


def decode_runner_manifest(raw, *, checkpoint=lambda: None):
    if type(raw) is not bytes or not 0 < len(raw) <= _MAX_MANIFEST_BYTES:
        raise CheckResourceError('CHECK_RUNNER_MANIFEST_SIZE_INVALID')
    value = exact_record(
        strict_json_object(raw),
        ('schema_version', 'protocol_version', *RunnerManifest.__dataclass_fields__),
    )
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise CheckResourceError('CHECK_RUNNER_MANIFEST_SCHEMA_INVALID')
    if value['protocol_version'] != CHECK_PROTOCOL:
        raise CheckResourceError('CHECK_RUNNER_PROTOCOL_INVALID')
    capabilities = references(value['capabilities'], nonempty=True)
    if not set(capabilities).issubset(CHECK_CAPABILITIES):
        raise CheckResourceError('CHECK_RUNNER_CAPABILITY_INVALID')
    rows = value['file_entries']
    if type(rows) is not list or not 1 <= len(rows) < _MAX_ENTRIES:
        raise CheckResourceError('CHECK_RUNNER_FILE_COUNT_INVALID')
    namespace = ContentPathIndex()
    namespace.add_file(_MANIFEST, '100644')
    files = []
    total = len(raw)
    for source in rows:
        checkpoint()
        row = exact_record(source, ('path', 'sha256', 'byte_count'))
        path = namespace.add_file(row['path'], '100644').path
        count = strict_integer(row['byte_count'], 'byte_count', minimum=0, maximum=_MAX_BYTES)
        total += count
        if not valid_sha256(row['sha256']) or total > _MAX_BYTES:
            raise CheckResourceError('CHECK_RUNNER_FILE_INVALID')
        files.append(RunnerFile(path, row['sha256'], count))
    entry = value['entry_ref']
    if type(entry) is not str or entry not in {member.path for member in files}:
        raise CheckResourceError('CHECK_RUNNER_ENTRY_NOT_IN_BUNDLE')
    return RunnerManifest(
        reference(value['bundle_id']),
        reference(value['version']),
        entry,
        references(value['runtime_refs']),
        tuple(files),
        capabilities,
        references(value['platform_refs'], nonempty=True),
        references(value['admission_evidence_refs'], nonempty=True),
    )


@dataclass(frozen=True)
class CheckRunnerClosure:
    registration: RegisteredCheckRunner
    manifest: RunnerManifest
    entry: FileIdentity = field(repr=False)
    tree_identity_sha256: str
    members: tuple[tuple[str, FileIdentity], ...] = field(repr=False)


def _closure(package, registration, manifest, source, checkpoint):
    directory = package.verify()
    if directory != registration.directory:
        raise CheckResourceError('ORIGINAL_CHECK_RUNNER_DIRECTORY_DIFFERS')
    files, directories, _, _ = _scan_task_workspace_tree(package.path, directory, checkpoint)
    expected = {row.path: (row.byte_count, row.sha256) for row in manifest.file_entries}
    original_manifest = source.verify()
    expected[_MANIFEST] = original_manifest.byte_count, original_manifest.sha256
    parents = {
        path[:position]
        for path in expected
        for position, character in enumerate(path)
        if character == '/'
    }
    if (
        {name: (count, digest) for name, (_, count, digest) in files.items()} != expected
        or set(directories) != parents
        or files[_MANIFEST][0] != original_manifest.file
    ):
        raise CheckResourceError('ORIGINAL_CHECK_RUNNER_TREE_DIFFERS')
    for name, identity in directories.items():
        checkpoint()
        if package.verify_member(name, directory=True) != identity:
            raise CheckResourceError('ORIGINAL_CHECK_RUNNER_MEMBER_DIFFERS')
    for name, (identity, _, _) in files.items():
        checkpoint()
        if package.verify_member(name, directory=False) != identity:
            raise CheckResourceError('ORIGINAL_CHECK_RUNNER_MEMBER_DIFFERS')
    return CheckRunnerClosure(
        registration,
        manifest,
        files[manifest.entry_ref][0],
        workspace_tree_sha256(files, directories),
        tuple((name, files[name][0]) for name in sorted(files)),
    )


@contextmanager
def hold_check_runner_bundle(registration, *, deadline, cancelled):
    """Verify fixed bytes before use and compare native identities again on return.

    This proves the resource closure. Platform admission and permission to run
    the runner require their own deployment evidence.
    """
    if type(registration) is not RegisteredCheckRunner or not callable(cancelled):
        raise CheckResourceError('ORIGINAL_CHECK_RUNNER_SOURCE_REQUIRED')

    def checkpoint():
        if cancelled() or monotonic() >= deadline:
            raise CheckResourceError('CHECK_RUNNER_INSPECTION_INTERRUPTED')

    checkpoint()
    with PrivatePackageGuard(registration.directory.canonical_path) as package:
        if package.verify() != registration.directory:
            raise CheckResourceError('ORIGINAL_CHECK_RUNNER_DIRECTORY_DIFFERS')
        identity = package.verify_member(_MANIFEST, directory=False)
        with LockedFileSource(
            package.path / _MANIFEST,
            max_file_bytes=_MAX_MANIFEST_BYTES,
            expected_file=identity,
            checkpoint=checkpoint,
        ) as source:
            if source.snapshot.sha256 != registration.manifest_sha256:
                raise CheckResourceError('ORIGINAL_CHECK_RUNNER_MANIFEST_DIFFERS')
            manifest = decode_runner_manifest(source.snapshot.raw, checkpoint=checkpoint)
            if (manifest.bundle_id, manifest.version) != (
                registration.bundle_id,
                registration.version,
            ):
                raise CheckResourceError('ORIGINAL_CHECK_RUNNER_IDENTITY_DIFFERS')
            closure = _closure(package, registration, manifest, source, checkpoint)
            checkpoint()
            yield closure
            if _closure(package, registration, manifest, source, checkpoint) != closure:
                raise CheckResourceError('ORIGINAL_CHECK_RUNNER_TREE_CHANGED')
