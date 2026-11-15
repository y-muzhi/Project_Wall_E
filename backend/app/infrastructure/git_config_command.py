"""One typed CONTROL_GIT config parser bound to original private resources.

No arbitrary arguments, environment overrides or Git repository discovery.
Native process ownership borrows this command until the original Job is empty.
"""

from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, field
from threading import RLock

from .git_bundle import BUNDLE_PARENT
from .git_local_config import LocalConfigFacts, infer_local_config_output
from .git_repository_location import RepositoryLocationLease
from .runtime_launch_journal import LaunchScope
from .windows_config_copy import PrivateConfigCopy
from .windows_config_source import LockedConfigSource
from .windows_local_paths import FileIdentity, LocalPathGuard, local_absolute_path
from .windows_pipe_capture import require_complete_output


class ConfigCommandError(RuntimeError):
    pass


@dataclass(frozen=True)
class ParsedRepositoryConfig:
    source_file: FileIdentity = field(repr=False)
    source_sha256: str
    local: LocalConfigFacts
    scope: LaunchScope = field(repr=False)
    io_nonce: str = field(repr=False)


def parse_original_config_output(
    output, location, *, scope, io_nonce, exit_code, max_output_bytes, max_entries
):
    if type(location) is not RepositoryLocationLease or type(scope) is not LaunchScope:
        raise ConfigCommandError('ORIGINAL_CONFIG_RESULT_BINDING_REQUIRED')
    original = location.verify()
    require_complete_output(
        output,
        scope=scope,
        io_nonce=io_nonce,
        exit_code=exit_code,
        max_output_bytes=max_output_bytes,
    )
    local = infer_local_config_output(
        output.stdout,
        expected_bare=original.expected_bare,
        max_output_bytes=max_output_bytes,
        max_entries=max_entries,
    )
    if location.verify() != original:
        raise ConfigCommandError('CONFIG_RESULT_SOURCE_DIFFERS')
    return ParsedRepositoryConfig(original.config, original.config_sha256, local, scope, io_nonce)


def private_git_environment(package_path, global_config_path, windows_directory):
    windows = str(local_absolute_path(windows_directory))
    private = str(package_path)
    return {
        'SystemRoot': windows,
        'WINDIR': windows,
        'PATH': str(BUNDLE_PARENT / 'win-x64/cmd'),
        'TEMP': private,
        'TMP': private,
        'HOME': private,
        'XDG_CONFIG_HOME': private,
        'GIT_CONFIG_NOSYSTEM': '1',
        'GIT_CONFIG_SYSTEM': 'NUL',
        'GIT_CONFIG_GLOBAL': str(global_config_path),
        'GIT_CEILING_DIRECTORIES': str(package_path.parent),
        'GIT_ATTR_NOSYSTEM': '1',
        'GIT_TERMINAL_PROMPT': '0',
        'GIT_NO_LAZY_FETCH': '1',
        'GIT_NO_REPLACE_OBJECTS': '1',
        'GIT_OPTIONAL_LOCKS': '0',
        'GIT_LITERAL_PATHSPECS': '1',
    }


class ConfigParseCommand:
    def __init__(self, copied, empty_global):
        if type(copied) is not PrivateConfigCopy or type(empty_global) is not LockedConfigSource:
            raise ConfigCommandError('ORIGINAL_PRIVATE_CONFIG_RESOURCES_REQUIRED')
        self._copy, self._empty = copied, empty_global
        self._package = copied._package
        self._gate = RLock()
        self._uses = 0
        self._closed = False
        self._validated_config = None
        self._original_facts = self._verify()

    def _verify(self, directory=None):
        if self._closed:
            raise ConfigCommandError('CONFIG_COMMAND_CLOSED')
        package = self._package.verify()
        copied = self._copy.verify()
        empty = self._empty.verify()
        if empty.raw != b'' or self._empty._path.parent != self._package.path:
            raise ConfigCommandError('PRIVATE_EMPTY_GLOBAL_CONFIG_REQUIRED')
        if self._package.verify_member(self._empty._path.name, directory=False) != empty.file:
            raise ConfigCommandError('PRIVATE_GLOBAL_CONFIG_IDENTITY_DIFFERS')
        if directory is not None and (
            type(directory) is not LocalPathGuard
            or not directory.directory
            or directory.verify() != package
        ):
            raise ConfigCommandError('ORIGINAL_PRIVATE_NONREPOSITORY_DIRECTORY_REQUIRED')
        try:
            (self._package.path / '.git').lstat()
        except FileNotFoundError:
            pass
        else:
            raise ConfigCommandError('PRIVATE_NONREPOSITORY_DIRECTORY_REQUIRED')
        return {
            'command': 'CONFIG_PARSE_1',
            'package': asdict(package),
            'copy': {'file': asdict(copied.file), 'sha256': copied.sha256},
            'source': {
                'file': asdict(self._copy._original.file),
                'sha256': self._copy._original.sha256,
            },
            'empty_global': {'file': asdict(empty.file), 'sha256': empty.sha256},
        }

    def facts(self, directory=None):
        with self._gate:
            actual = self._verify(directory)
            if actual != self._original_facts:
                raise ConfigCommandError('ORIGINAL_CONFIG_COMMAND_INPUT_CHANGED')
            return actual

    def accept_output(
        self, output, location, *, scope, io_nonce, exit_code, max_output_bytes, max_entries
    ):
        with self._gate:
            self.facts()
            if type(location) is not RepositoryLocationLease or type(scope) is not LaunchScope:
                raise ConfigCommandError('ORIGINAL_CONFIG_RESULT_BINDING_REQUIRED')
            original = location.verify()
            if (
                self._copy._original.file != original.config
                or self._copy._original.sha256 != original.config_sha256
            ):
                raise ConfigCommandError('CONFIG_RESULT_SOURCE_DIFFERS')
            validated = parse_original_config_output(
                output,
                location,
                scope=scope,
                io_nonce=io_nonce,
                exit_code=exit_code,
                max_output_bytes=max_output_bytes,
                max_entries=max_entries,
            )
            if self._validated_config is not None and self._validated_config != validated:
                raise ConfigCommandError('ORIGINAL_CONFIG_RESULT_CANNOT_REBIND')
            self._validated_config = validated
            return validated

    @property
    def validated_config(self):
        self.facts()
        if self._validated_config is None:
            raise ConfigCommandError('CONFIG_PARSE_RESULT_NOT_VALIDATED')
        return self._validated_config

    def arguments(self):
        self.facts()
        return ('config', '--file', str(self._copy._path), '--no-includes', '--null', '--list')

    def environment(self, windows_directory):
        self.facts()
        return private_git_environment(self._package.path, self._empty._path, windows_directory)

    @contextmanager
    def hold(self, directory):
        with self._gate:
            self.facts(directory)
            # ExitStack construction occurs before any native dispatch. Its
            # original contexts stay in the native resource owner until release.
            stack = ExitStack()
            try:
                stack.enter_context(self._copy.parse_path())
                stack.enter_context(self._empty.hold())
                self.facts(directory)
            except BaseException:
                stack.close()
                raise
            self._uses += 1
        try:
            yield self
        finally:
            with self._gate:
                self._uses -= 1
                stack.close()
                self.facts(directory)

    def close(self):
        with self._gate:
            if self._uses:
                raise ConfigCommandError('CONFIG_COMMAND_IN_USE')
            self._closed = True
