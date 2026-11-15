"""Shared original resources for exact backend-owned repository read commands."""

from abc import ABC, abstractmethod
from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from threading import RLock

from .git_config_command import ConfigParseCommand
from .git_repository_metadata import RepositoryMetadataLease
from .windows_empty_directory import ReadOnlyEmptyDirectory


class RepositoryReadError(RuntimeError):
    pass


def repository_read_arguments(root, git_directory, expected_bare, hooks):
    arguments = [
        '-c',
        'safe.directory=' + str(root),
        '-c',
        'core.hooksPath=' + str(hooks),
        '-c',
        'core.fsmonitor=false',
        '-c',
        'gc.auto=0',
        '-c',
        'maintenance.auto=false',
        '-c',
        'protocol.allow=never',
        '--git-dir=' + str(git_directory),
    ]
    if not expected_bare:
        arguments.append('--work-tree=' + str(root))
    return tuple(arguments)


class RepositoryReadCommand(ABC):
    def __init__(self, metadata, parsed_config, hooks):
        if (
            type(metadata) is not RepositoryMetadataLease
            or type(parsed_config) is not ConfigParseCommand
            or type(hooks) is not ReadOnlyEmptyDirectory
        ):
            raise RepositoryReadError('ORIGINAL_REPOSITORY_COMMAND_RESOURCES_REQUIRED')
        self._metadata, self._config, self._hooks = metadata, parsed_config, hooks
        self._gate = RLock()
        self._uses = 0
        self._closed = False
        self._original = self._verify()

    @abstractmethod
    def command_facts(self):
        """Return fresh exact command-specific input facts."""
        raise NotImplementedError

    def _verify(self, directory=None):
        if self._closed:
            raise RepositoryReadError('REPOSITORY_COMMAND_CLOSED')
        source = self._metadata.location.verify()
        metadata = self._metadata.verify()
        parsed = self._config.validated_config
        config = self._config.facts(directory)
        hooks = self._hooks.verify()
        if (
            parsed.source_file != source.config
            or parsed.source_sha256 != source.config_sha256
            or parsed.local.object_format != metadata.object_format
            or parsed.local.bare != source.expected_bare
        ):
            raise RepositoryReadError('ORIGINAL_PARSED_REPOSITORY_CONFIG_DIFFERS')
        if self._hooks.path.parent != self._config._package.path:
            raise RepositoryReadError('ORIGINAL_PRIVATE_HOOKS_REQUIRED')
        return {
            **self.command_facts(),
            'metadata': asdict(metadata),
            'location': asdict(source),
            'config': config,
            'parsed': asdict(parsed),
            'hooks': asdict(hooks),
        }

    def facts(self, directory=None):
        with self._gate:
            actual = self._verify(directory)
            if actual != self._original:
                raise RepositoryReadError('ORIGINAL_REPOSITORY_COMMAND_INPUT_CHANGED')
            return actual

    def arguments(self):
        self.facts()
        source = self._metadata.location.verify()
        return repository_read_arguments(
            source.root.canonical_path,
            source.git_directory.canonical_path,
            source.expected_bare,
            self._hooks.path,
        )

    def environment(self, windows_directory):
        self.facts()
        return self._config.environment(windows_directory)

    @contextmanager
    def hold(self, directory):
        with self._gate:
            self.facts(directory)
            stack = ExitStack()
            try:
                stack.enter_context(self._metadata.hold())
                stack.enter_context(self._config.hold(directory))
                stack.enter_context(self._hooks.hold())
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

    def close(self):
        with self._gate:
            if self._uses:
                raise RepositoryReadError('REPOSITORY_COMMAND_IN_USE')
            self._closed = True
