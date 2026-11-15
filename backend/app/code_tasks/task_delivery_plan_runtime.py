"""Build a delivery preview from the original Guard's protected local Git reads."""

import os
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, replace
from time import monotonic

from backend.app.infrastructure.content_package import TargetPackageBinding, seal_target_package
from backend.app.infrastructure.content_package_publish import (
    create_candidate_stage,
    publish_candidate_package,
)
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.git_content_command import CONTENT_STORE_DIRECTORY
from backend.app.infrastructure.git_metadata_command import decode_metadata_output
from backend.app.infrastructure.git_repository_location import RepositoryLocationLease
from backend.app.infrastructure.git_repository_metadata import RepositoryMetadataLease
from backend.app.infrastructure.git_worktrees import (
    LocalBranch,
    WorktreeError,
    WorktreeListing,
    WorktreeRecord,
    require_target_not_checked_out,
)
from backend.app.infrastructure.identifiers import increment
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown
from backend.app.infrastructure.windows_config_source import LockedFileSource
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.infrastructure.windows_worktree_heads import WorktreeHeadLease
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_json_object

from .repository_baseline_query import load_baseline_query
from .repository_baseline_validation import inspect_baseline_source
from .repository_git_dispatch import (
    OBJECT_BATCH_COMMAND_REF,
    OBSERVATION_COMMANDS,
    BaselineGitDispatch,
)
from .repository_git_runner import RepositoryBaselineValidationRun, RepositoryGitScopeActions
from .task_candidate_commit import capture_package_limits, read_stored_candidate_package
from .task_candidate_git import CandidateGitDispatch
from .task_candidate_reads import _verify_package
from .task_delivery import (
    ACTIVE,
    PREPARE,
    DeliveryTargetObservation,
    current_delivery_inputs,
    original_operation,
)
from .task_delivery_reads import stored_target, verify_target_package
from .task_resume_runtime import _step


def _current(connection, operation_id, *, observe=False):
    operation, fixed, steps = original_operation(connection, operation_id, PREPARE)
    task = connection.execute(
        'SELECT * FROM code_tasks WHERE id=?', (operation['task_id'],)
    ).fetchone()
    if task is None or operation['status'] not in ACTIVE:
        raise StorageUnavailable('Original delivery plan is not active')
    if not observe and (
        task['stop_requested_at'] is not None
        or task['control_generation'] != operation['control_generation']
        or task['state_version'] != operation['expected_state_version'] + 1
        or task['active_session_id'] != operation['session_id']
        or task['current_candidate_id'] != fixed['candidate_id']
        or task['current_test_report_id'] != fixed['test_report_id']
    ):
        raise LaunchOutcomeUnknown('ORIGINAL_DELIVERY_PLAN_FENCED')
    return task, operation, fixed, steps


class DeliveryReadDispatch(BaselineGitDispatch):
    _commands = (*OBSERVATION_COMMANDS, OBJECT_BATCH_COMMAND_REF)
    _external_key = 'git_delivery_read_target'
    _step_no = 2

    @staticmethod
    def _active_step(connection, operation_id, *, allow_unknown=False):
        _, operation, _, steps = _current(connection, operation_id, observe=allow_unknown)
        if operation['status'] not in (('RUNNING', 'UNKNOWN') if allow_unknown else ('RUNNING',)):
            raise StorageUnavailable('Original delivery target read is fenced')
        if steps[1]['status'] not in (
            ('RUNNING', 'UNKNOWN', 'SUCCEEDED') if allow_unknown else ('RUNNING',)
        ):
            raise StorageUnavailable('Original delivery target step differs')
        return steps[1]


class DeliveryPackageDispatch(CandidateGitDispatch):
    _step_no = 3

    def _active_step(self, connection, operation_id, *, allow_unknown=False):
        if operation_id != self._operation_id:
            raise StorageUnavailable('Original delivery package scope differs')
        _, operation, _, steps = _current(connection, operation_id, observe=allow_unknown)
        if (
            steps[1]['status'] != 'SUCCEEDED'
            or steps[2]['status']
            not in (('RUNNING', 'UNKNOWN', 'SUCCEEDED') if allow_unknown else ('RUNNING',))
            or not allow_unknown
            and operation['status'] != 'RUNNING'
        ):
            raise StorageUnavailable('Original delivery package preparation differs')
        return steps[2]

    def _package_owner(self, connection):
        task, operation, _, steps = _current(connection, self._operation_id, observe=True)
        return task['id'], operation['session_id'], _binding(operation, steps)


def _binding(operation, steps):
    claim = strict_json_object(steps[2]['external_identity'])
    observed = strict_json_object(steps[1]['result_ref'])
    return TargetPackageBinding(
        operation['id'],
        claim['plan_id'],
        operation['control_generation'],
        claim['content_store_key'],
        claim['content_profile_version_id'],
        claim['object_format'],
        observed['target_commit'],
        observed['target_tree'],
    )


class TargetBlobSpool:
    """Bounded, transient original blob bytes outside the candidate and user Git tree."""

    def __init__(self, parent, key):
        self._parent = parent
        self._path = create_private_package(parent.path / ('plan-blobs-' + key))
        self._files = {}
        self._guard = PrivatePackageGuard(self._path)
        self._guard.__enter__()

    def consume(self, entry, raw):
        name = entry.blob_oid
        if name in self._files:
            return
        self._guard.verify()
        stream = (self._path / name).open('xb')
        try:
            with stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            self._files[name] = self._guard.verify_member(name, directory=False)

    def read(self, entry):
        identity = self._files.get(entry.blob_oid)
        if identity is None:
            raise StorageUnavailable('Original target blob was not observed')
        self._guard.verify()
        with LockedFileSource(
            self._path / entry.blob_oid,
            expected_file=identity,
            max_file_bytes=max(1, entry.byte_count),
        ) as source:
            return source.verify().raw

    def close(self):
        if self._guard is None:
            return
        self._parent.verify()
        self._guard.verify()
        for name, identity in self._files.items():
            if self._guard.verify_member(name, directory=False) != identity:
                raise StorageUnavailable('Original preview spool changed before cleanup')
            (self._path / name).unlink()
        self._files.clear()
        self._guard.close()
        self._guard = None
        self._path.rmdir()


class DeliveryPlanRun(RepositoryBaselineValidationRun):
    _dispatcher = DeliveryReadDispatch
    _records_business_progress = False

    def __init__(self, *args, parent, admissions, **kwargs):
        super().__init__(*args, **kwargs)
        self._parent = parent
        self._admissions = admissions
        self._package_dispatch = None

    def _check_active(self):
        super()._check_active()
        self._binding.assert_backend(self._runtime.commands().process_lock)
        with self._runtime.database.transaction() as connection:
            _current(connection, self._operation_id)

    def _run(self):
        try:
            return self._advance()
        except WorktreeError as error:
            if (self._command is not None and self._command.cleanup_required) or (
                self._package_dispatch is not None and self._package_dispatch._original is not None
            ):
                raise
            with self._runtime.database.transaction(write=True) as connection:
                task, operation, _, steps = _current(connection, self._operation_id, observe=True)
                at = max(operation_time(None), task['updated_at'])
                step = 2 if steps[1]['status'] != 'SUCCEEDED' else 3
                code = (
                    error.code
                    if error.code in ('TARGET_CHANGED', 'TARGET_CHECKED_OUT')
                    else 'REPOSITORY_UNSUPPORTED'
                )
                if task['stop_requested_at'] is not None:
                    self._cancelled_plan(connection, operation, at)
                else:
                    self._failed(connection, operation, step, code, at)
            return None

    def _advance(self):
        database = self._runtime.database
        identity = self._operation_id
        with ExitStack() as held, database.transaction(write=True) as connection:
            task, original, fixed, steps = _current(connection, identity, observe=True)
            if original['status'] == 'PENDING' and task['stop_requested_at'] is not None:
                self._cancelled_plan(
                    connection, original, max(operation_time(None), task['updated_at'])
                )
                return None
            if original['status'] != 'PENDING':
                recover = True
            else:
                recover = False
                _current(connection, identity)
                result = current_delivery_inputs(
                    connection,
                    self._runtime,
                    fixed,
                    task,
                    self._admissions,
                    held,
                    active=identity,
                )
                at = max(operation_time(None), task['updated_at'])
                if not isinstance(result, tuple):
                    self._failed(connection, original, 1, result.code, at)
                    return None
                candidate, _ = result
                stored_candidate = read_stored_candidate_package(connection, candidate)
                connection.execute(
                    "UPDATE code_operations SET status='RUNNING',started_at=? WHERE id=?",
                    (at, identity),
                )
                _step(
                    connection,
                    identity,
                    1,
                    'SUCCEEDED',
                    at,
                    result={'test_report_id': fixed['test_report_id']},
                )
                _step(connection, identity, 2, 'RUNNING', at)
        if recover:
            return self._recover(original, steps)
        # Private target content is copied only after the current candidate package is verified.
        _verify_package(stored_candidate, active=self._check_active)
        claim = strict_json_object(steps[2]['external_identity'])
        _, source, _, _ = load_baseline_query(self._runtime, task['base_snapshot_id'])
        if source.format != claim['object_format']:
            raise StorageUnavailable('Original delivery object format differs')
        config, worktrees, branches, objects = self._dispatch.reserve(identity)
        location = self._location(source.root)
        facts = location.verify()
        if (
            facts.root.canonical_path != source.root
            or facts.common_directory.canonical_path != source.common_directory
        ):
            raise StorageUnavailable('Original delivery repository location differs')
        parsed = self._config(config, location)
        if parsed.local.object_format != source.format:
            raise StorageUnavailable('Original delivery repository format differs')
        metadata = self._metadata(location, format=source.format)
        tree_output, tree_nonce, tree_exit = self._read(
            worktrees,
            location,
            kind='WORKTREES',
            parsed=parsed,
            metadata=metadata,
        )
        branch_output, branch_nonce, branch_exit = self._read(
            branches,
            location,
            kind='LOCAL_BRANCHES',
            parsed=parsed,
            metadata=metadata,
        )
        listing = decode_metadata_output(
            metadata,
            'WORKTREES',
            tree_output,
            scope=worktrees.scope,
            io_nonce=tree_nonce,
            exit_code=tree_exit,
            max_output_bytes=self._limits.max_git_output_bytes,
        )
        refs = decode_metadata_output(
            metadata,
            'LOCAL_BRANCHES',
            branch_output,
            scope=branches.scope,
            io_nonce=branch_nonce,
            exit_code=branch_exit,
            max_output_bytes=self._limits.max_git_output_bytes,
        )
        target = task['target_branch']
        require_target_not_checked_out(listing, refs, target)
        tip = next(row.commit_oid for row in refs if row.full_ref == target)
        source = replace(source, commit_oid=tip)
        spool = self._keep(TargetBlobSpool, self._parent, claim['content_store_key'])
        with (
            metadata.hold(),
            WorktreeHeadLease(
                listing,
                refs,
                common_directory=facts.common_directory.canonical_path,
                private_roots=self._private_roots,
                max_file_bytes=self._limits.max_file_bytes,
                max_open_handles=self._limits.max_open_handles,
            ) as heads,
        ):

            def verify_source():
                self._check_active()
                metadata.verify()
                heads.verify()

            verify_source()
            with self._prepared_read(
                objects,
                location,
                kind='OBJECT_BATCH',
                parsed=parsed,
                metadata=metadata,
            ) as (command, prepare):
                inspection, completed = command.run_batch(
                    prepare,
                    lambda read: inspect_baseline_source(
                        source,
                        metadata,
                        read,
                        check_active=verify_source,
                        materialization_root=self._parent.path / 'delivery-materialization',
                        consume_file=spool.consume,
                    ),
                    format=source.format,
                    max_requests=source.read_limits.max_edges + source.read_limits.max_objects + 1,
                    max_output_bytes=min(source.output_budget, self._limits.max_git_output_bytes),
                    deadline=self._deadline,
                    cancelled=self._cancelled,
                )
            self._dispatch._verify_completed_batch(
                identity, source, metadata, parsed, inspection.proof, completed
            )
            observed = {
                'repository_id': task['repository_id'],
                'target_branch': target,
                'target_commit': tip,
                'target_tree': inspection.proof.tree_oid,
                'observed_at': operation_time(None),
                'repository_sha256': metadata.verify().fingerprint_sha256,
                'worktrees_sha256': heads.fingerprint_sha256,
                'worktrees': asdict(listing),
            }
            with database.transaction(write=True) as connection:
                _, operation, _, now_steps = _current(connection, identity)
                if now_steps[1]['status'] != 'RUNNING' or now_steps[1]['result_ref'] is not None:
                    raise StorageUnavailable('Original target read was already sealed')
                at = observed['observed_at']
                _step(connection, identity, 2, 'SUCCEEDED', at, result=observed)
                _step(connection, identity, 3, 'RUNNING', at)
                _, _, _, now_steps = _current(connection, identity)
                binding = _binding(operation, now_steps)
                limits, git_limits = capture_package_limits(
                    connection, binding.content_profile_version_id, task_id=operation['task_id']
                )
            store = self._store()
            stage = create_candidate_stage(store, binding)
            self._package_dispatch = self._keep(
                DeliveryPackageDispatch,
                self._runtime,
                self._dispatch._frames,
                self._binding,
                self._dispatch._journal,
                identity,
                self._parent,
                cancelled=self._cancelled,
            )
            with PrivatePackageGuard(stage) as package:
                sealed = seal_target_package(
                    package,
                    binding,
                    inspection.entries,
                    spool.read,
                    secret_policy_ref=source.secret_policy_ref,
                    limits=limits,
                    git_limits=git_limits,
                    started_at=monotonic(),
                    active=verify_source,
                    verify_source=verify_source,
                    exchange=self._package_dispatch.exchange,
                    materialization_root=self._parent.path / 'delivery-materialization',
                )
            return self._publish(store, binding, limits, git_limits, verify_source, expected=sealed)

    def _store(self):
        path = self._parent.path / CONTENT_STORE_DIRECTORY
        try:
            path.lstat()
        except FileNotFoundError:
            create_private_package(path)
        guard = PrivatePackageGuard(path)
        guard.__enter__()
        self._owners.append(guard)
        return guard

    def _publish(self, store, binding, limits, git_limits, verify_source, *, expected=None):
        original = publish_candidate_package(
            store,
            binding,
            limits=limits,
            git_limits=git_limits,
            started_at=monotonic(),
            active=verify_source,
            materialization_root=self._parent.path / 'delivery-materialization',
            expected=expected,
        )
        verify_source()
        identity = self._operation_id
        database = self._runtime.database
        with ExitStack() as held, database.transaction(write=True) as connection:
            task, operation, fixed, steps = _current(connection, identity)
            if _binding(operation, steps) != original.seal.binding:
                raise StorageUnavailable('Original delivery plan binding changed')
            result = current_delivery_inputs(
                connection,
                self._runtime,
                fixed,
                task,
                self._admissions,
                held,
                active=identity,
            )
            at = max(operation_time(None), task['updated_at'], original.seal.captured_at)
            if not isinstance(result, tuple):
                self._failed(connection, operation, 4, result.code, at)
                return None
            if connection.execute(
                """SELECT 1 FROM code_commands WHERE operation_id=?
                   AND (status<>'SUCCEEDED' OR ended_at IS NULL OR exit_code IS NULL OR exit_code<>0) LIMIT 1""",
                (identity,),
            ).fetchone():
                raise StorageUnavailable('Original target package commands are unverified')
            candidate, _ = result
            connection.execute(
                """INSERT INTO code_delivery_plans(id,task_id,candidate_id,test_report_id,repository_id,
                   target_branch,expected_target_commit,target_tree_oid,target_content_store_key,
                   target_manifest_sha256,result_tree_oid,operation_id,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    binding.plan_id,
                    task['id'],
                    candidate['id'],
                    fixed['test_report_id'],
                    task['repository_id'],
                    task['target_branch'],
                    binding.target_commit,
                    binding.target_tree,
                    binding.content_store_key,
                    original.seal.manifest_sha256,
                    candidate['content_tree_oid'],
                    identity,
                    at,
                ),
            )
            _step(
                connection,
                identity,
                3,
                'SUCCEEDED',
                at,
                result={
                    'directory': asdict(original.directory),
                    'manifest_sha256': original.seal.manifest_sha256,
                },
            )
            _step(
                connection,
                identity,
                4,
                'SUCCEEDED',
                at,
                result={'delivery_plan_id': binding.plan_id},
            )
            connection.execute(
                "UPDATE code_operations SET status='SUCCEEDED',ended_at=?,failure_code=NULL WHERE id=?",
                (at, identity),
            )
            changed = connection.execute(
                """UPDATE code_tasks SET current_delivery_plan_id=?,state_version=?,updated_at=?,last_observed_at=?
                   WHERE id=? AND state_version=? AND stop_requested_at IS NULL""",
                (
                    binding.plan_id,
                    increment(task['state_version']),
                    at,
                    at,
                    task['id'],
                    task['state_version'],
                ),
            )
            if changed.rowcount != 1:
                raise StorageUnavailable('Original delivery plan publication was fenced')
        return binding.plan_id

    @staticmethod
    def _failed(connection, operation, step, reason, at):
        _step(connection, operation['id'], step, 'FAILED', at)
        connection.execute(
            """UPDATE code_operations SET status='FAILED',started_at=COALESCE(started_at,?),
               ended_at=?,failure_code=? WHERE id=?""",
            (at, at, reason, operation['id']),
        )

    @staticmethod
    def _cancelled_plan(connection, operation, at):
        connection.execute(
            """UPDATE code_operation_steps SET status='CANCELLED',ended_at=?,last_observed_at=?
               WHERE operation_id=? AND status IN ('PENDING','RUNNING','UNKNOWN')""",
            (at, at, operation['id']),
        )
        connection.execute(
            """UPDATE code_operations SET status='CANCELLED',ended_at=?,failure_code='TASK_ENDED'
               WHERE id=? AND status IN ('PENDING','RUNNING','UNKNOWN')""",
            (at, operation['id']),
        )

    def _recover(self, original, steps):
        database = self._runtime.database
        identity = self._operation_id
        if steps[1]['external_identity'] is not None:
            for scope in self._dispatch.original(identity):
                action = RepositoryGitScopeActions(
                    self._runtime, self._binding, self._dispatch, scope
                )
                if action.cleanup_pending():
                    action.use_boundary(self._deadline, self._cancelled)
                    action.original_preparation(observe=True)
                    action.finish_cleanup()
        if steps[1]['result_ref'] is None:
            with database.transaction(write=True) as connection:
                task, _, _, _ = _current(connection, identity, observe=True)
                at = max(operation_time(None), task['updated_at'])
                if task['stop_requested_at'] is not None:
                    self._cancelled_plan(connection, original, at)
                else:
                    self._failed(connection, original, 2, 'CONTENT_NOT_READY', at)
            return None
        binding = _binding(original, steps)
        with database.transaction() as connection:
            task, _, _, _ = _current(connection, identity, observe=True)
            limits, git_limits = capture_package_limits(
                connection, binding.content_profile_version_id, task_id=task['id']
            )
            running = connection.execute(
                "SELECT id FROM code_commands WHERE operation_id=? AND status IN ('PENDING','RUNNING','UNKNOWN')",
                (identity,),
            ).fetchall()
        if running:
            dispatch = self._keep(
                DeliveryPackageDispatch,
                self._runtime,
                self._dispatch._frames,
                self._binding,
                self._dispatch._journal,
                identity,
                self._parent,
                cancelled=self._cancelled,
            )
            if not all(dispatch.recover_released(command['id']) for command in running):
                raise LaunchOutcomeUnknown('ORIGINAL_DELIVERY_PACKAGE_CLEANUP_REQUIRED')
        if task['stop_requested_at'] is not None:
            with database.transaction(write=True) as connection:
                latest, _, _, _ = _current(connection, identity, observe=True)
                self._cancelled_plan(
                    connection, original, max(operation_time(None), latest['updated_at'])
                )
            return None
        store = self._store()
        if not any(
            (store.path / binding.package_name(staged=staged) / 'seal.json').is_file()
            for staged in (True, False)
        ):
            with database.transaction(write=True) as connection:
                _current(connection, identity)
                self._failed(connection, original, 3, 'CONTENT_NOT_READY', operation_time(None))
            return None
        observed = strict_json_object(steps[1]['result_ref'])
        with self._target_lease(observed, task['base_snapshot_id']) as verify:
            return self._publish(store, binding, limits, git_limits, verify)

    def _target_lease(self, observed, baseline_id):
        _, source, _, _ = load_baseline_query(self._runtime, baseline_id)
        return target_lease(
            source,
            observed,
            self._private_roots,
            self._limits,
            checkpoint=self._check_active,
        )

    def reconcile_cleanup(self, frames, *, timeout_ms, cancelled):
        dispatch = self._package_dispatch
        if dispatch is not None and dispatch._original is not None:
            dispatch.reconcile_cleanup(frames, timeout_ms=timeout_ms, cancelled=cancelled)
        super().reconcile_cleanup(frames, timeout_ms=timeout_ms, cancelled=cancelled)


@contextmanager
def target_lease(source, observed, private_roots, limits, *, checkpoint):
    """Revalidate the complete original worktree cohort and target ref via held paths."""
    data = observed['worktrees']
    listing = WorktreeListing(
        data['object_format'],
        tuple(WorktreeRecord(**row) for row in data['entries']),
        data['listing_sha256'],
    )
    with (
        RepositoryLocationLease(
            source.root,
            private_roots=private_roots,
            max_file_bytes=limits.max_file_bytes,
            max_open_handles=limits.max_open_handles,
            max_metadata_entries=limits.max_metadata_entries,
        ) as location,
        RepositoryMetadataLease(
            location,
            format=source.format,
            max_entries=limits.max_metadata_entries,
            max_open_handles=limits.max_open_handles,
            max_file_bytes=limits.max_file_bytes,
            max_metadata_bytes=limits.max_metadata_bytes,
        ) as metadata,
    ):
        facts = location.verify()
        snapshot = metadata.verify()
        refs = tuple(LocalBranch(name, oid) for name, oid in snapshot.heads)
        target = observed['target_branch']
        if dict(snapshot.heads).get(target) != observed['target_commit']:
            raise WorktreeError('ORIGINAL_DELIVERY_TARGET_CHANGED', code='TARGET_CHANGED')
        require_target_not_checked_out(listing, refs, target)
        with WorktreeHeadLease(
            listing,
            refs,
            common_directory=facts.common_directory.canonical_path,
            private_roots=private_roots,
            max_file_bytes=limits.max_file_bytes,
            max_open_handles=limits.max_open_handles,
        ) as heads:

            def verify():
                checkpoint()
                if (
                    facts.common_directory.canonical_path != source.common_directory
                    or metadata.verify().fingerprint_sha256 != observed['repository_sha256']
                    or heads.fingerprint_sha256 != observed['worktrees_sha256']
                ):
                    raise WorktreeError('ORIGINAL_DELIVERY_TARGET_CHANGED', code='TARGET_CHANGED')
                heads.verify()

            verify()
            yield verify
            verify()


def observe_saved_delivery_target(runtime, task_id, plan_id, epoch, private_roots, limits):
    """Reopen the exact Plan and target snapshot before the separate acceptance transaction."""
    with runtime.database.transaction() as connection:
        row = connection.execute(
            """SELECT p.*,t.base_snapshot_id FROM code_delivery_plans p JOIN code_tasks t ON t.id=p.task_id
               WHERE p.id=? AND p.task_id=?""",
            (plan_id, task_id),
        ).fetchone()
        if row is None:
            return None
        stored = stored_target(connection, row)
        content_limits, git_limits = capture_package_limits(
            connection, stored.binding.content_profile_version_id, task_id=task_id
        )
        candidate = connection.execute(
            'SELECT * FROM code_candidates WHERE id=? AND task_id=?', (row['candidate_id'], task_id)
        ).fetchone()
        if candidate is None or candidate['content_tree_oid'] != row['result_tree_oid']:
            raise StorageUnavailable('Original delivery candidate differs')
        original = read_stored_candidate_package(connection, candidate)
    _, source, _, _ = load_baseline_query(runtime, row['base_snapshot_id'])
    runtime.commands().process_lock.assert_owned()
    try:
        verify_target_package(stored, content_limits, git_limits)
        _verify_package(original)
    except (OSError, RuntimeError, ValueError):
        return 'CONTENT_NOT_READY'
    try:
        with target_lease(
            source,
            stored.original_target,
            private_roots,
            limits,
            checkpoint=runtime.commands().process_lock.assert_owned,
        ):
            return DeliveryTargetObservation(
                plan_id,
                stored.binding.target_commit,
                stored.binding.target_tree,
                operation_time(None),
                epoch,
            )
    except WorktreeError as error:
        if error.code in ('TARGET_CHECKED_OUT', 'TARGET_CHANGED'):
            return error.code
        return 'REPOSITORY_UNSUPPORTED'
    except (OSError, RuntimeError, ValueError):
        return 'TARGET_CHANGED'
