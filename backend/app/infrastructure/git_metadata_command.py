"""Two exact CONTROL_GIT metadata queries, sharing original read resources."""

from contextlib import contextmanager
from dataclasses import asdict
from threading import RLock

from .git_commit_input import DeliveryReflogIdentity
from .git_config_command import ParsedRepositoryConfig, private_git_environment
from .git_delivery_objects import DeliveryObjectIntent
from .git_ref_protocol import DeliveryAncestorQuery, RefPrepareInput, branch_ref
from .git_repository_metadata import RepositoryMetadataLease
from .git_repository_read import (
    RepositoryReadCommand,
    RepositoryReadError,
    repository_read_arguments,
)
from .git_worktrees import decode_local_branches, decode_worktrees
from .guard_git_metadata_source import ROLES, GuardMetadataDirectories
from .runtime_launch_journal import _hex
from .windows_config_source import LockedConfigSource
from .windows_empty_directory import ReadOnlyEmptyDirectory
from .windows_local_paths import LocalPathGuard, local_absolute_path
from .windows_pipe_capture import require_complete_output
from .windows_private_package import PrivatePackageGuard


class MetadataCommandError(RepositoryReadError):
    pass


def _metadata_arguments(kind):
    if type(kind) is not str:
        raise MetadataCommandError('ORIGINAL_METADATA_COMMAND_KIND_REQUIRED')
    if kind == 'WORKTREES':
        return ('worktree', 'list', '--porcelain', '-z')
    if kind == 'LOCAL_BRANCHES':
        return (
            'for-each-ref',
            '--format=%(refname)%00%(objectname)%00%(objecttype)%00%(symref)%00',
            'refs/heads/',
        )
    raise MetadataCommandError('ORIGINAL_METADATA_COMMAND_KIND_REQUIRED')


class RepositoryMetadataCommand(RepositoryReadCommand):
    def __init__(self, metadata, parsed_config, hooks, *, kind):
        _metadata_arguments(kind)
        self._kind = kind
        super().__init__(metadata, parsed_config, hooks)

    def command_facts(self):
        return {'command': 'METADATA_' + self._kind + '_1'}

    def arguments(self):
        return super().arguments() + _metadata_arguments(self._kind)

    def decode_output(self, output, *, scope, io_nonce, exit_code, max_output_bytes):
        self.facts()
        return decode_metadata_output(
            self._metadata,
            self._kind,
            output,
            scope=scope,
            io_nonce=io_nonce,
            exit_code=exit_code,
            max_output_bytes=max_output_bytes,
        )


def decode_metadata_output(metadata, kind, output, *, scope, io_nonce, exit_code, max_output_bytes):
    if type(metadata) is not RepositoryMetadataLease:
        raise MetadataCommandError('ORIGINAL_METADATA_TREE_REQUIRED')
    _metadata_arguments(kind)
    output = require_complete_output(
        output,
        scope=scope,
        io_nonce=io_nonce,
        exit_code=exit_code,
        max_output_bytes=max_output_bytes,
    )
    snapshot = metadata.verify()
    if kind == 'WORKTREES':
        return decode_worktrees(
            output.stdout,
            format=snapshot.object_format,
            query_exit_code=exit_code,
            max_output_bytes=max_output_bytes,
        )
    branches = decode_local_branches(
        output.stdout,
        format=snapshot.object_format,
        query_exit_code=exit_code,
        max_output_bytes=max_output_bytes,
    )
    if tuple(sorted((row.full_ref, row.commit_oid) for row in branches)) != snapshot.heads:
        raise MetadataCommandError('ORIGINAL_BRANCH_OBSERVATION_DIFFERS')
    return branches


class GuardRepositoryCommand:
    """Fixed repository command argv from the Guard's copied original identities."""

    def __init__(
        self,
        directories,
        source,
        package,
        empty_global,
        hooks,
        parsed,
        metadata_sha256,
        *,
        kind,
        ref_intent=None,
        object_intent=None,
        reflog_identity=None,
        target_ref=None,
        ancestry=None,
    ):
        if (
            type(directories) is not GuardMetadataDirectories
            or type(source) is not LockedConfigSource
            or type(package) is not PrivatePackageGuard
            or type(empty_global) is not LockedConfigSource
            or type(hooks) is not ReadOnlyEmptyDirectory
            or type(parsed) is not ParsedRepositoryConfig
        ):
            raise MetadataCommandError('ORIGINAL_GUARD_METADATA_RESOURCES_REQUIRED')
        _hex(metadata_sha256)
        if (
            (ancestry is not None) != (kind == 'DELIVERY_ANCESTOR')
            or ancestry is not None
            and (
                type(ancestry) is not DeliveryAncestorQuery
                or ancestry.object_format != parsed.local.object_format
            )
        ):
            raise MetadataCommandError('ORIGINAL_DELIVERY_ANCESTRY_REQUIRED')
        if (target_ref is not None) != (kind == 'DELIVERY_TARGET'):
            raise MetadataCommandError('ORIGINAL_DELIVERY_TARGET_REQUIRED')
        if kind in ('BASELINE_REF', 'DELIVERY_REF'):
            ref_kind = 'BASELINE_CREATE' if kind == 'BASELINE_REF' else 'DELIVERY_UPDATE'
            if (
                type(ref_intent) is not RefPrepareInput
                or ref_intent.kind != ref_kind
                or ref_intent.object_format != parsed.local.object_format
                or object_intent is not None
                or (type(reflog_identity) is DeliveryReflogIdentity) != (kind == 'DELIVERY_REF')
                or (kind == 'BASELINE_REF' and reflog_identity is not None)
            ):
                raise MetadataCommandError('ORIGINAL_GUARD_REF_INTENT_REQUIRED')
            self._query = ('-c', 'core.logAllRefUpdates=false') + ref_intent.arguments()
        elif kind == 'DELIVERY_OBJECT':
            if (
                type(object_intent) is not DeliveryObjectIntent
                or object_intent.object_format != parsed.local.object_format
                or ref_intent is not None
                or reflog_identity is not None
            ):
                raise MetadataCommandError('ORIGINAL_GUARD_DELIVERY_OBJECT_REQUIRED')
            self._query = object_intent.arguments()
        else:
            if any(value is not None for value in (ref_intent, object_intent, reflog_identity)):
                raise MetadataCommandError('ORIGINAL_GUARD_READ_COMMAND_HAS_WRITE_INTENT')
            self._query = (
                ancestry.arguments()
                if kind == 'DELIVERY_ANCESTOR'
                else (
                    'for-each-ref',
                    '--format=%(refname)%00%(objectname)%00%(symref)%00',
                    branch_ref(target_ref),
                )
                if kind == 'DELIVERY_TARGET'
                else ('cat-file', '--batch')
                if kind == 'OBJECT_BATCH'
                else _metadata_arguments(kind)
            )
        self._target_ref = target_ref
        self._ancestry = ancestry
        self._ref_intent = ref_intent
        self._object_intent = object_intent
        self._reflog_identity = reflog_identity
        self._directories, self._source, self._package = directories, source, package
        self._empty, self._hooks, self._parsed = empty_global, hooks, parsed
        self._metadata_sha256, self._kind = metadata_sha256, kind
        self._gate = RLock()
        self._uses = 0
        self._closed = False
        self._original = self._verify()

    def _verify(self, directory=None):
        if self._closed:
            raise MetadataCommandError('ORIGINAL_GUARD_METADATA_COMMAND_CLOSED')
        package = self._package.verify()
        original = self._directories.verify()
        source = self._source.verify()
        empty = self._empty.verify()
        hooks = self._hooks.verify()
        common_config = (
            local_absolute_path(original.common_directory.file.canonical_path) / 'config'
        )
        if (
            local_absolute_path(source.file.canonical_path) != common_config
            or source.file != self._parsed.source_file
            or source.sha256 != self._parsed.source_sha256
            or self._parsed.local.bare != original.expected_bare
        ):
            raise MetadataCommandError('ORIGINAL_GUARD_METADATA_CONFIG_DIFFERS')
        if (
            empty.raw != b''
            or self._empty._path.parent != self._package.path
            or self._package.verify_member(self._empty._path.name, directory=False) != empty.file
            or self._hooks.path != self._package.path / 'hooks'
        ):
            raise MetadataCommandError('ORIGINAL_GUARD_METADATA_PRIVATE_ENVIRONMENT_DIFFERS')
        if directory is not None and (
            type(directory) is not LocalPathGuard
            or not directory.directory
            or directory.verify() != package
        ):
            raise MetadataCommandError('ORIGINAL_GUARD_METADATA_WORK_DIRECTORY_DIFFERS')
        facts = {
            'command': 'RAW_GIT_OBJECT_BATCH_1'
            if self._kind == 'OBJECT_BATCH'
            else 'METADATA_' + self._kind + '_1',
            'location_sha256': original.location_sha256,
            'metadata_sha256': self._metadata_sha256,
            'directories': {role: asdict(getattr(original, role).file) for role in ROLES},
            'config': asdict(self._parsed),
            'package': asdict(package),
            'empty_global': asdict(empty.file),
            'hooks': asdict(hooks),
        }
        if self._ancestry is not None:
            facts['ancestry_sha256'] = self._ancestry.digest
        if self._target_ref is not None:
            facts['target_ref'] = self._target_ref
        if self._ref_intent is not None:
            facts['ref_intent_sha256'] = self._ref_intent.input_sha256
        if self._object_intent is not None:
            facts['object_intent_sha256'] = self._object_intent.digest
        if self._reflog_identity is not None:
            facts['reflog_sha256'] = self._reflog_identity.digest
        return facts

    def facts(self, directory=None):
        with self._gate:
            actual = self._verify(directory)
            if actual != self._original:
                raise MetadataCommandError('ORIGINAL_GUARD_METADATA_INPUT_CHANGED')
            return actual

    def arguments(self):
        facts = self.facts()
        paths = facts['directories']
        return (
            repository_read_arguments(
                paths['root']['canonical_path'],
                paths['git_directory']['canonical_path'],
                self._parsed.local.bare,
                self._hooks.path,
            )
            + self._query
        )

    def environment(self, windows_directory):
        self.facts()
        environment = private_git_environment(
            self._package.path, self._empty._path, windows_directory
        )
        if self._reflog_identity is not None:
            environment.update(self._reflog_identity.environment())
        return environment

    @contextmanager
    def hold(self, directory):
        with self._gate:
            self.facts(directory)
            self._uses += 1
        try:
            with self._source.hold(), self._empty.hold(), self._hooks.hold():
                self.facts(directory)
                yield self
        finally:
            with self._gate:
                self._uses -= 1

    def close(self):
        with self._gate:
            if self._uses:
                raise MetadataCommandError('ORIGINAL_GUARD_METADATA_COMMAND_IN_USE')
            self._closed = True
