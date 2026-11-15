"""Materialize and observe a fixed candidate under the original CHECK workspace ACL."""

import os
from dataclasses import dataclass, field
from time import monotonic

from .check_fixture import RegisteredCheckFixture, hold_check_fixture
from .check_input_transfer import import_check_input
from .content_package import verify_candidate_package
from .content_package_publish import PublishedCandidate
from .runtime_launch_journal import LaunchOutcomeUnknown, LaunchScope, TestingLaunchScope
from .windows_config_source import LockedFileSource
from .windows_local_paths import FileIdentity, LocalPathGuard
from .windows_private_package import PrivatePackageGuard
from .windows_task_directories import (
    ProjectCheckInput,
    SnapshotCheckInput,
    TaskLpacDirectories,
    _policy,
    _TaskDirectory,
)
from .windows_task_workspace_tree import _scan_task_workspace_tree, workspace_tree_sha256


class CheckInputError(LaunchOutcomeUnknown):
    pass


@dataclass(frozen=True)
class CheckInputFacts:
    scope: LaunchScope
    check: ProjectCheckInput | SnapshotCheckInput
    directory: FileIdentity = field(repr=False)
    members: tuple[FileIdentity, ...] = field(repr=False)
    tree_identity_sha256: str


class TaskCheckWorkspace:
    """One candidate, one native workspace. An uncertain publication stays owned."""

    def __init__(self, directories, candidate=None, *, fixture=None):
        if (
            type(directories) is not TaskLpacDirectories
            or not directories.is_project_check
            or candidate is not None
            and type(candidate) is not PublishedCandidate
            or fixture is not None
            and (
                type(fixture) is not RegisteredCheckFixture
                or type(directories.scope) is not TestingLaunchScope
                or candidate is not None
            )
        ):
            raise CheckInputError('ORIGINAL_PROJECT_CHECK_INPUT_REQUIRED')
        fixed = directories.check_input
        if candidate is not None:
            seal = candidate.seal
            if (
                type(fixed) is not ProjectCheckInput
                or seal.binding.candidate_id != fixed.candidate_id
                or seal.manifest_sha256 != fixed.manifest_sha256
                or (
                    fixed.owner_kind == 'CODING'
                    and seal.binding.control_generation > fixed.control_generation
                )
            ):
                raise CheckInputError('ORIGINAL_PROJECT_CHECK_CANDIDATE_DIFFERS')
        directories.verify()
        self._directories, self._candidate, self._fixture = directories, candidate, fixture
        role = 'workspace' if fixture is None else 'basis'
        self._registration = '_check_publication' if fixture is None else '_check_fixture'
        self._workspace = directories._directories[role]
        self._identity = self._workspace.verify().file
        self._files, self._children = {}, {}
        self._retained = []
        self._facts = None

    def _checkpoint(self, cancelled):
        self._directories._require_open(cancelled)
        if self._workspace.verify().file != self._identity:
            raise CheckInputError('ORIGINAL_PROJECT_CHECK_DIRECTORY_DIFFERS')

    def _copy(self, entry, raw, checkpoint):
        self._copy_file(entry.path, entry.byte_count, entry.sha256, raw, checkpoint)

    def _copy_file(self, path, byte_count, digest, raw, checkpoint):
        checkpoint()
        root = self._workspace.path
        parts = path.split('/')
        owner = self._directories
        aces, label = _policy('basis', owner._operator, owner._user, owner.package_sid)
        for count in range(1, len(parts)):
            parent = '/'.join(parts[:count])
            directory = _TaskDirectory(root / parent, 'check-input', owner._operator, aces, label)
            try:
                if parent in self._children:
                    directory.pin(self._children[parent])
                else:
                    directory.create()
                    self._children[parent] = directory.verify().file
            finally:
                try:
                    directory.close()
                except BaseException as error:
                    error.retained_owner = directory
                    raise
        target = root / path
        with target.open('xb') as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        with LocalPathGuard(target, directory=False) as pin:
            self._files[path] = (pin.verify(), byte_count, digest)
        checkpoint()

    def _read_facts(self, checkpoint):
        checkpoint()
        actual = self._workspace.verify().file
        if actual != self._identity:
            raise CheckInputError('ORIGINAL_PROJECT_CHECK_DIRECTORY_DIFFERS')
        files, directories, _, _ = _scan_task_workspace_tree(
            self._workspace.path, actual, checkpoint
        )
        if files != self._files or directories != self._children:
            raise CheckInputError('INPUT_CHANGED')
        ordered = (
            *(directories[name] for name in sorted(directories)),
            *(files[name][0] for name in sorted(files)),
        )
        checkpoint()
        return CheckInputFacts(
            self._directories.scope,
            self._directories.check_input,
            self._identity,
            ordered,
            workspace_tree_sha256(files, directories),
        )

    def _publish(self, receive, cancelled):
        if not callable(cancelled):
            raise CheckInputError('ORIGINAL_PROJECT_CHECK_CANCELLATION_REQUIRED')

        def checkpoint():
            self._checkpoint(cancelled)

        owner = self._directories
        with owner._actions._journal._scope(owner.scope):
            checkpoint()
            if getattr(owner, self._registration) is not None:
                raise CheckInputError('ORIGINAL_PROJECT_CHECK_ALREADY_RESERVED')
            setattr(owner, self._registration, self)
            try:
                with os.scandir(self._workspace.path) as items:
                    if next(items, None) is not None:
                        raise CheckInputError('ORIGINAL_PROJECT_CHECK_WORKSPACE_NOT_EMPTY')
                receive(checkpoint, lambda entry, raw: self._copy(entry, raw, checkpoint))
                self._facts = self._read_facts(checkpoint)
                return self._facts
            except BaseException as error:
                retained = getattr(error, 'retained_owner', None)
                if retained is not None and retained is not self:
                    self._retained.append(retained)
                error.retained_owner = self
                raise

    def publish(self, *, limits, git_limits, cancelled):
        original = self._candidate
        if type(original) is not PublishedCandidate or not callable(cancelled):
            raise CheckInputError('ORIGINAL_PROJECT_CHECK_PACKAGE_REQUIRED')
        started = monotonic()

        def receive(checkpoint, consume):
            with PrivatePackageGuard(original.directory.canonical_path) as package:
                if (
                    package.verify() != original.directory
                    or package.path.name != original.seal.binding.package_name(staged=False)
                    or package.path.is_relative_to(self._directories.root)
                    or self._directories.root.is_relative_to(package.path)
                ):
                    raise CheckInputError('ORIGINAL_PROJECT_CHECK_PACKAGE_DIFFERS')
                verify_candidate_package(
                    package,
                    original.seal.binding,
                    limits=limits,
                    git_limits=git_limits,
                    started_at=started,
                    active=checkpoint,
                    materialization_root=self._workspace.path,
                    expected=original.seal,
                    consume_file=consume,
                )

        return self._publish(
            receive, lambda: cancelled() or monotonic() - started >= git_limits.max_seconds
        )

    def publish_transferred(self, descriptor, source_parent, *, limits, cancelled):
        if self._candidate is not None or self._fixture is not None:
            raise CheckInputError('ORIGINAL_PROJECT_CHECK_TRANSFER_SCOPE_DIFFERS')
        owner = self._directories

        def receive(checkpoint, consume):
            import_check_input(
                owner._controller,
                descriptor,
                source_parent,
                owner.scope,
                owner.check_input
                if type(owner.check_input) is SnapshotCheckInput
                else owner.check_input.manifest_sha256,
                limits=limits,
                materialization_root=self._workspace.path,
                checkpoint=checkpoint,
                consume=consume,
            )

        return self._publish(receive, cancelled)

    def publish_fixture(self, *, cancelled):
        fixture = self._fixture
        if fixture is None:
            raise CheckInputError('ORIGINAL_TESTING_FIXTURE_REQUIRED')

        def receive(checkpoint, _):
            with hold_check_fixture(fixture, checkpoint) as (package, files):
                if not files:
                    raise CheckInputError('ORIGINAL_TESTING_FIXTURE_EMPTY')
                for path, (identity, count, digest) in files.items():
                    with LockedFileSource(
                        package.path / path,
                        max_file_bytes=max(1, count),
                        expected_file=identity,
                        checkpoint=checkpoint,
                    ) as source:
                        raw = source.snapshot
                        if raw.sha256 != digest or raw.byte_count != count:
                            raise CheckInputError('ORIGINAL_TESTING_FIXTURE_CONTENT_DIFFERS')
                        self._copy_file(path, count, digest, raw.raw, checkpoint)
                        source.verify()

        return self._publish(receive, cancelled)

    def close(self):
        for retained in reversed(tuple(self._retained)):
            retained.close()
            self._retained.remove(retained)

    def verify(self, checkpoint):
        """Recheck the same byte tree, separately from a verified process stop."""
        if (
            self._facts is None
            or getattr(self._directories, self._registration) is not self
            or not callable(checkpoint)
        ):
            raise CheckInputError('ORIGINAL_PROJECT_CHECK_PUBLICATION_REQUIRED')
        self._directories.verify()
        if self._read_facts(checkpoint) != self._facts:
            raise CheckInputError('INPUT_CHANGED')
        return self._facts
