"""Fixed CONTROL_GIT command intents for one private staged candidate repository."""

import re
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass
from hashlib import sha256

from backend.app.shared.validation import MAX_SAFE_INTEGER

from .content_manifest import git_oid, object_format
from .git_config_command import private_git_environment
from .runtime_launch_journal import LaunchOutcomeUnknown
from .windows_attribute_handles import GuardAttributeHandles
from .windows_config_source import LockedConfigSource
from .windows_empty_directory import ReadOnlyEmptyDirectory
from .windows_local_paths import FileIdentity, LocalPathGuard, local_absolute_path
from .windows_private_package import PrivatePackageGuard
from .windows_stdio import _handle, _handle_text

CONTENT_COMMAND_REF = 'GIT20-CONTENT-PACKAGE-1'
CONTENT_REF = 'refs/walle/content'
CONTENT_STORE_DIRECTORY = 'candidate-store'
CONTENT_GIT_FLAGS = (
    '--no-replace-objects',
    '-c',
    'core.fsync=all',
    '-c',
    'core.fsyncMethod=fsync',
    '-c',
    'gc.auto=0',
    '-c',
    'maintenance.auto=false',
)
_BODY_KINDS = ('WRITE_BLOB', 'WRITE_TREE')
_READ_KINDS = ('READ_TREE', 'READ_BLOB')
_KINDS = ('INIT', *_BODY_KINDS, 'CREATE_REF', 'READ_REF', *_READ_KINDS)
_EMPTY_SHA256 = sha256(b'').hexdigest()


class ContentGitCommandError(LaunchOutcomeUnknown):
    def __init__(self, code, native_error=None):
        self.native_error = native_error
        super().__init__(code)


def _hex(value, length):
    return type(value) is str and re.fullmatch('[a-f0-9]{' + str(length) + '}', value) is not None


@dataclass(frozen=True)
class ContentGitIntent:
    content_store_key: str
    object_format: str
    kind: str
    object_id: str | None
    input_bytes: int
    input_sha256: str

    def __post_init__(self):
        object_format(self.object_format)
        if (
            not _hex(self.content_store_key, 32)
            or type(self.kind) is not str
            or self.kind not in _KINDS
            or type(self.input_bytes) is not int
            or not 0 <= self.input_bytes <= MAX_SAFE_INTEGER
            or not _hex(self.input_sha256, 64)
            or (self.kind not in _BODY_KINDS and self.input_bytes != 0)
            or (self.input_bytes == 0 and self.input_sha256 != _EMPTY_SHA256)
        ):
            raise ContentGitCommandError('CONTENT_GIT_INTENT_INVALID')
        if self.kind in ('CREATE_REF', *_READ_KINDS):
            git_oid(self.object_id, self.object_format)
            if not self.object_id.strip('0'):
                raise ContentGitCommandError('CONTENT_GIT_OBJECT_INVALID')
        elif self.object_id is not None:
            raise ContentGitCommandError('CONTENT_GIT_UNEXPECTED_OBJECT')

    def verify_input(self, raw):
        if (
            type(raw) is not bytes
            or len(raw) != self.input_bytes
            or sha256(raw).hexdigest() != self.input_sha256
        ):
            raise ContentGitCommandError('CONTENT_GIT_INPUT_DIFFERS')

    def paths(self, parent):
        root = local_absolute_path(parent)
        store = root / CONTENT_STORE_DIRECTORY
        stage = store / ('.capture-' + self.content_store_key)
        return {'parent': root, 'store': store, 'stage': stage, 'repository': stage / 'repo.git'}

    def command(self, repo):
        if self.kind == 'INIT':
            return (
                'init',
                '--bare',
                '--template=',
                '--initial-branch=walle-content',
                '--ref-format=files',
                '--object-format=' + self.object_format,
                str(repo),
            )
        if self.kind == 'WRITE_BLOB':
            return ('hash-object', '-w', '--stdin', '--no-filters')
        if self.kind == 'WRITE_TREE':
            return ('mktree', '-z')
        if self.kind == 'CREATE_REF':
            return (
                'update-ref',
                '--no-deref',
                CONTENT_REF,
                self.object_id,
                '0' * len(self.object_id),
            )
        if self.kind == 'READ_REF':
            return ('for-each-ref', '--format=%(refname)%00%(objectname)%00%(symref)%00')
        return ('cat-file', 'tree' if self.kind == 'READ_TREE' else 'blob', self.object_id)


def content_git_arguments(intent, repo, *, hooks=None):
    prefix = CONTENT_GIT_FLAGS
    if hooks is not None:
        prefix += ('-c', 'core.hooksPath=' + str(hooks))
    if intent.kind != 'INIT':
        prefix += ('--git-dir=' + str(repo),)
    return prefix + intent.command(repo)


def decode_content_git_source(value, *, expected_parent):
    if (
        type(value) is not dict
        or set(value) != {'intent', 'directories'}
        or type(value['intent']) is not dict
        or set(value['intent']) != set(ContentGitIntent.__dataclass_fields__)
        or type(value['directories']) is not dict
        or type(expected_parent) is not FileIdentity
        or not expected_parent.is_directory
        or expected_parent.filesystem != 'NTFS'
    ):
        raise ContentGitCommandError('ORIGINAL_CONTENT_GIT_SOURCE_REQUIRED')
    intent = ContentGitIntent(**value['intent'])
    roles = (
        ('parent', 'store', 'stage')
        if intent.kind == 'INIT'
        else ('parent', 'store', 'stage', 'repository')
    )
    if set(value['directories']) != set(roles):
        raise ContentGitCommandError('ORIGINAL_CONTENT_GIT_DIRECTORY_COHORT_DIFFERS')
    paths = intent.paths(expected_parent.canonical_path)
    directories = {}
    identities = set()
    for role in roles:
        row = value['directories'][role]
        if (
            type(row) is not dict
            or set(row) != {'volume_serial', 'file_id', 'handle'}
            or row['volume_serial'] != expected_parent.volume_serial
            or not _hex(row['file_id'], 32)
            or row['file_id'] in identities
        ):
            raise ContentGitCommandError('ORIGINAL_CONTENT_GIT_DIRECTORY_DIFFERS')
        identities.add(row['file_id'])
        _handle(row['handle'])
        identity = FileIdentity(
            str(paths[role]), row['volume_serial'], row['file_id'], True, 'NTFS'
        )
        directories[role] = (identity, row['handle'])
    if directories['parent'][0] != expected_parent:
        raise ContentGitCommandError('ORIGINAL_CONTENT_GIT_PARENT_DIFFERS')
    return intent, directories


def encode_content_git_source(intent, pins):
    return {
        'intent': asdict(intent),
        'directories': {
            role: {'volume_serial': file.volume_serial, 'file_id': file.file_id, 'handle': handle}
            for role, (file, handle) in pins.items()
        },
    }


@contextmanager
def hold_content_git_source(parent, intent):
    """Export only exact attribute handles of the original staged package."""
    if type(parent) is not PrivatePackageGuard or type(intent) is not ContentGitIntent:
        raise ContentGitCommandError('ORIGINAL_CONTENT_GIT_PARENT_REQUIRED')
    original = parent.verify()
    paths = intent.paths(parent.path)
    roles = (
        ('parent', 'store', 'stage')
        if intent.kind == 'INIT'
        else ('parent', 'store', 'stage', 'repository')
    )
    with (
        PrivatePackageGuard(paths['store']) as store,
        PrivatePackageGuard(paths['stage']) as package,
        ExitStack() as custody,
    ):
        pins = {}
        for role in roles:
            held = custody.enter_context(LocalPathGuard(paths[role], directory=True))
            pins[role] = (held.verify(), _handle_text(held._held[-1][0]))
        if (
            original != pins['parent'][0]
            or store.verify() != pins['store'][0]
            or package.verify() != pins['stage'][0]
        ):
            raise ContentGitCommandError('ORIGINAL_CONTENT_GIT_PACKAGE_DIFFERS')
        if intent.kind != 'INIT':
            config_id = package.verify_member('repo.git/config', directory=False)
            config = custody.enter_context(
                LockedConfigSource(
                    paths['repository'] / 'config',
                    max_file_bytes=4096,
                    expected_file=config_id,
                )
            )
            if config.snapshot.raw != content_config_bytes(intent.object_format):
                raise ContentGitCommandError('ORIGINAL_CONTENT_GIT_CONFIG_DIFFERS')
        source = encode_content_git_source(intent, pins)
        decode_content_git_source(source, expected_parent=original)
        yield pins


def content_config_bytes(format):
    version = b'1' if format == 'sha256' else b'0'
    config = (
        b'[core]\n\trepositoryformatversion = '
        + version
        + b'\n\tfilemode = false\n\tbare = true\n\tsymlinks = false\n\tignorecase = true\n'
    )
    if format == 'sha256':
        config = b'[extensions]\n\tobjectformat = sha256\n' + config
    return config


class GuardContentGitCommand:
    """A fixed Git process can use only the retained private package repository."""

    def __init__(self, intent, directories, package, empty_global, hooks, repo):
        if (
            type(intent) is not ContentGitIntent
            or type(directories) is not GuardAttributeHandles
            or type(package) is not PrivatePackageGuard
            or not package.is_control_git_read_package
            or type(empty_global) is not LockedConfigSource
            or type(hooks) is not ReadOnlyEmptyDirectory
        ):
            raise ContentGitCommandError('ORIGINAL_CONTENT_GIT_COMMAND_RESOURCES_REQUIRED')
        self._intent, self._directories, self._package = intent, directories, package
        self._empty, self._hooks = empty_global, hooks
        self._repo = local_absolute_path(repo)
        self._original = self._verify()

    def _verify(self, directory=None):
        self._directories.verify()
        current = {
            'intent': asdict(self._intent),
            'repository': str(self._repo),
            'process_directory': asdict(self._package.verify()),
            'empty_global_sha256': self._empty.verify().sha256,
            'hooks': asdict(self._hooks.verify().file),
        }
        if directory is not None and (
            type(directory) is not LocalPathGuard
            or directory.path != self._package.path
            or asdict(directory.verify()) != current['process_directory']
        ):
            raise ContentGitCommandError('ORIGINAL_CONTENT_GIT_WORKING_DIRECTORY_DIFFERS')
        return current

    def facts(self, directory=None):
        actual = self._verify(directory)
        if actual != self._original:
            raise ContentGitCommandError('ORIGINAL_CONTENT_GIT_COMMAND_CHANGED')
        return actual

    def arguments(self):
        self.facts()
        return content_git_arguments(self._intent, self._repo, hooks=self._hooks.path)

    def environment(self, windows_directory):
        self.facts()
        return private_git_environment(self._package.path, self._empty._path, windows_directory)

    @contextmanager
    def hold(self, directory):
        with self._empty.hold(), self._hooks.hold():
            self.facts(directory)
            yield self
            self.facts(directory)

    def close(self):
        # The registered preparation owns and closes the actual resources.
        pass
