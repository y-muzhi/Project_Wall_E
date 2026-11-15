"""Build and dispatch the original Delivery through the fixed authenticated Git owner."""

from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from pathlib import Path
from time import monotonic, time

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.git_commit_closure import ObjectReadRequest
from backend.app.infrastructure.git_commit_input import DeliveryReflogIdentity
from backend.app.infrastructure.git_delivery_objects import build_original_delivery_objects
from backend.app.infrastructure.git_receipt_store import GitReceiptStore
from backend.app.infrastructure.git_receipts import (
    GitReceipt,
    GitReceiptBinding,
    GitReceiptFacts,
    GitRefObservation,
)
from backend.app.infrastructure.git_ref_protocol import (
    DeliveryAncestorQuery,
    delivery_update,
    exact_direct_ref_observation,
    prepared_ref_observation,
)
from backend.app.infrastructure.git_worktrees import (
    LocalBranch,
    WorktreeError,
    WorktreeListing,
    WorktreeRecord,
    require_target_not_checked_out,
)
from backend.app.infrastructure.guard_control_git_input import (
    CONFIG_COMMAND_REF,
    DELIVERY_ANCESTOR_COMMAND_REF,
    DELIVERY_OBJECT_COMMAND_REF,
    DELIVERY_REF_COMMAND_REF,
    DELIVERY_TARGET_COMMAND_REF,
    OBJECT_BATCH_COMMAND_REF,
)
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown
from backend.app.infrastructure.windows_config_source import LockedFileSource
from backend.app.infrastructure.windows_pipe_capture import (
    require_complete_output,
    verify_original_output,
)
from backend.app.infrastructure.windows_private_package import PrivatePackageGuard
from backend.app.infrastructure.windows_worktree_heads import WorktreeHeadLease
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_json_object

from .repository_baseline_query import load_baseline_query
from .repository_git_runner import _RepositoryRun
from .task_candidate_commit import read_stored_candidate_package
from .task_delivery_git import DeliveryGitDispatch
from .task_delivery_plan_runtime import target_lease
from .task_delivery_reads import stored_target, verify_target_package
from .task_delivery_write import (
    DeliverySendFence,
    block_unwritten_delivery,
    fix_delivery_payload,
    hold_original_delivery,
    load_original_delivery,
    read_delivery_payload,
    read_only_object_claim,
    record_original_ref_abort,
    record_reconciled_delivery,
    recover_fixed_delivery_payload,
    reference_abort_commands,
    require_live_delivery,
)
from .task_report_link import qualify_report, require_current_report_link
from .task_resume_runtime import _step


def _metadata_identities(metadata):
    metadata.verify()
    return (
        {Path(path): pin.identity for path, (pin, _) in metadata._nodes.items()},
        {Path(path): pinned.snapshot.sha256 for path, pinned in metadata._sources.items()},
    )


def _verify_prepared_metadata(before, current, lock, common):
    old_nodes, old_refs = before
    nodes, refs = _metadata_identities(current)
    if lock not in nodes or refs != old_refs:
        raise WorktreeError('ORIGINAL_DELIVERY_PREPARED_METADATA_DIFFERS', code='TARGET_CHANGED')
    # A branch originally in packed-refs may need exact parent directories.
    parents = {
        path
        for path in lock.parents
        if path.is_relative_to(common / 'refs' / 'heads') and path not in old_nodes
    }
    extras = nodes.keys() - old_nodes.keys() - {lock}
    if (
        not extras <= parents
        or any(not nodes[path].is_directory for path in extras)
        or any(nodes.get(path) != identity for path, identity in old_nodes.items())
    ):
        raise WorktreeError('ORIGINAL_DELIVERY_PREPARED_METADATA_DIFFERS', code='TARGET_CHANGED')


class DeliveryWriteRun(_RepositoryRun):
    """Backend thread only. No original command or ref COMMIT is replayed."""

    _dispatcher = DeliveryGitDispatch
    _records_business_progress = True

    def __init__(self, *args, admissions, **kwargs):
        super().__init__(*args, **kwargs)
        self._admissions = admissions
        self._dispatch.bind(self._operation_id)
        self._pending = {}
        self._extra = []

    def _original(self, connection, *, live=False):
        current = load_original_delivery(connection, self._operation_id)
        if live:
            if self._cancelled() or monotonic() >= self._deadline:
                raise LaunchOutcomeUnknown('ORIGINAL_DELIVERY_DEADLINE_EXCEEDED')
            require_live_delivery(
                connection, current, self._binding.owner_epoch, operation_time(None)
            )
        return current

    def _check_active(self):
        self._binding.assert_backend(self._runtime.commands().process_lock)
        with self._runtime.database.transaction() as connection:
            self._original(connection, live=True)

    @contextmanager
    def _alternate_dispatch(self):
        before = self._dispatch
        owner = self._dispatcher(self._runtime, before._frames, self._binding, before._journal)
        owner.bind(self._operation_id)
        owner._ref_retry_window = before._ref_retry_window
        self._extra.append(owner)
        self._dispatch = owner
        try:
            yield
        finally:
            self._dispatch = before

    @contextmanager
    def _fixed(self, step, reference, location, *, intent_sha256=None, target_ref=None, **options):
        dispatch = self._dispatch
        original = dispatch.reserve(
            step, reference, intent_sha256=intent_sha256, target_ref=target_ref
        )
        with self._prepared_read(original, location, target_ref=target_ref, **options) as ready:
            self._pending[dispatch] = ready[0]
            try:
                yield original, ready
            finally:
                if dispatch._original is None:
                    self._pending.pop(dispatch)

    def _query(self, step, reference, location, *, allow_negative_ancestry=False, **options):
        with self._fixed(step, reference, location, **options) as (original, (command, prepare)):
            output, nonce, exit_code = command.run(
                prepare,
                deadline=self._deadline,
                cancelled=self._cancelled,
                max_output_bytes=self._limits.max_git_output_bytes,
            )
            verified = False
            try:
                if allow_negative_ancestry and exit_code == 1:
                    result = verify_original_output(
                        output,
                        scope=original.scope,
                        io_nonce=nonce,
                        max_output_bytes=self._limits.max_git_output_bytes,
                    )
                    if result.stdout or result.stderr:
                        raise LaunchOutcomeUnknown('ORIGINAL_DELIVERY_ANCESTRY_OUTPUT_DIFFERS')
                else:
                    result = require_complete_output(
                        output,
                        scope=original.scope,
                        io_nonce=nonce,
                        exit_code=exit_code,
                        max_output_bytes=self._limits.max_git_output_bytes,
                    )
                verified = True
                return result, original, nonce, exit_code
            finally:
                self._dispatch.complete(exit_code, output_verified=verified)

    def _delivery_config(self, step, location):
        from backend.app.infrastructure.git_config_command import parse_original_config_output

        raw, original, nonce, exit_code = self._query(step, CONFIG_COMMAND_REF, location)
        return parse_original_config_output(
            raw,
            location,
            scope=original.scope,
            io_nonce=nonce,
            exit_code=exit_code,
            max_output_bytes=self._limits.max_git_output_bytes,
            max_entries=self._limits.max_metadata_entries,
        )

    def _object(self, step, location, parsed, format, kind, oid, maximum):
        metadata = self._metadata(location, format=format)
        try:
            with self._fixed(
                step,
                OBJECT_BATCH_COMMAND_REF,
                location,
                kind='OBJECT_BATCH',
                parsed=parsed,
                metadata=metadata,
            ) as (_, (command, prepare)):
                result, _ = command.run_batch(
                    prepare,
                    lambda read: (
                        read(
                            ObjectReadRequest(
                                format, kind, oid, maximum, self._deadline - monotonic()
                            )
                        ).raw
                    ),
                    format=format,
                    max_requests=1,
                    max_output_bytes=self._limits.max_git_output_bytes,
                    deadline=self._deadline,
                    cancelled=self._cancelled,
                )
                self._dispatch.complete(0, output_verified=True)
                return result
        finally:
            metadata.close()

    def _write_object(self, location, parsed, format, intent, raw):
        metadata = self._metadata(location, format=format)
        try:
            with self._fixed(
                2,
                DELIVERY_OBJECT_COMMAND_REF,
                location,
                kind='DELIVERY_OBJECT',
                parsed=parsed,
                metadata=metadata,
                object_intent=intent,
                intent_sha256=intent.digest,
            ) as (original, (command, prepare)):
                output, nonce, exit_code = command.run(
                    prepare,
                    deadline=self._deadline,
                    cancelled=self._cancelled,
                    max_output_bytes=self._limits.max_git_output_bytes,
                    input_bytes=raw,
                )
                verified = False
                try:
                    bounded = require_complete_output(
                        output,
                        scope=original.scope,
                        io_nonce=nonce,
                        exit_code=exit_code,
                        max_output_bytes=self._limits.max_git_output_bytes,
                    )
                    intent.verify_output(bounded.stdout)
                    verified = True
                    return bounded.stdout
                finally:
                    self._dispatch.complete(exit_code, output_verified=verified)
        finally:
            metadata.close()

    def _inputs(self):
        with ExitStack() as held, self._runtime.database.transaction() as connection:
            original = self._original(connection, live=True)
            if original.delivery['status'] != 'PENDING':
                raise StorageUnavailable('Original local delivery needs reconciliation')
            require_current_report_link(connection, original.task)
            candidate = connection.execute(
                'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
                (original.fixed['candidate_id'], original.task['id']),
            ).fetchone()
            report = connection.execute(
                'SELECT * FROM testing_reports WHERE id=?', (original.fixed['test_report_id'],)
            ).fetchone()
            if candidate is None or report is None:
                raise StorageUnavailable('Original delivery candidate or report is missing')
            reason, report_view = qualify_report(
                connection,
                self._runtime.catalog,
                self._admissions,
                original.task,
                candidate,
                report,
                held,
            )
            if (
                reason is not None
                or bool(report_view['manual_coverage_ids'])
                != original.fixed['manual_risk_accepted']
            ):
                raise WorktreeError(
                    'ORIGINAL_DELIVERY_REPORT_CHANGED', code='TEST_REPORT_NOT_ELIGIBLE'
                )
            package = read_stored_candidate_package(connection, candidate)
            target = stored_target(connection, original.plan)
        _, source, _, _ = load_baseline_query(self._runtime, original.task['base_snapshot_id'])
        verify_target_package(target, package.limits, package.git_limits)
        with target_lease(
            source,
            target.original_target,
            self._private_roots,
            self._limits,
            checkpoint=self._check_active,
        ):
            return original, source, package, target

    def _reference_receipts(self, original, command, commit):
        dispatch = self._dispatch
        scope = dispatch.original_command(command)
        prepared = dispatch.read_action(scope, 'PREPARE', 'ACKNOWLEDGED')
        stopped = dispatch.read_action(scope, 'STOP', 'ACKNOWLEDGED')
        released = dispatch.read_action(scope, 'RELEASE', 'ACKNOWLEDGED')
        if (
            scope.scope.step_no != 4
            or prepared is None
            or stopped is None
            or released is None
            or stopped['result']['native']['fence']['stop_closed'] is not True
            or released['result']['native']['cleanup_verified'] is not True
        ):
            raise StorageUnavailable('Original delivery ref cleanup is not proved')
        ready = prepared['result']
        stop = stopped['result']
        release = released['result']
        intent = delivery_update(
            commit.delivery_id,
            original.plan['target_branch'],
            commit.commit_oid,
            commit.parent_oid,
            format=commit.format,
        )
        if (
            ready['metadata_source']['ref_intent_sha256'] != intent.input_sha256
            or stop['binding_ref'] != ready['binding_ref']
            or release['binding_ref'] != ready['binding_ref']
            or stop['native']['guard_run_ref'] != ready['guard_run_ref']
            or strict_json_object(command['runtime_binding'])['guard_run_ref']
            != ready['guard_run_ref']
            or release['native']['preparation']['handles_released'] is not True
        ):
            raise StorageUnavailable('Original delivery ref input or release differs')
        return self._keep(
            GitReceiptStore,
            dispatch._journal,
            GitReceiptBinding(
                scope.scope,
                ready['guard_run_ref'],
                original.task['repository_id'],
                ready['metadata_source']['metadata_sha256'],
                commit.commit_oid,
                commit.format,
            ),
            max_receipt_bytes=16384,
            max_records=100000,
            unique_phases=True,
        )

    def _proved_aborts(self, original, commands, commit, *, require_saved_lock=False):
        if not commands:
            return ()
        saved = original.steps[3]['result_ref'] if require_saved_lock else None
        if require_saved_lock and saved is None:
            return ()
        saved_lock_verified = not require_saved_lock
        identities = []
        for command in commands:
            if command['status'] != 'FAILED' or command['exit_code'] != 0:
                return ()
            try:
                receipts = self._reference_receipts(original, command, commit)
            except StorageUnavailable:
                return ()
            if (
                receipts.read_phase('COMMIT_MAY_BE_SENT') is not None
                or receipts.read_phase('COMMIT_ACK') is not None
            ):
                return ()
            aborted = receipts.read_phase('ABORTED')
            if aborted is None or aborted[1].facts != GitReceiptFacts(
                True, False, None, None, None, 'NOT_RUN'
            ):
                return ()
            if not saved_lock_verified:
                prepared = receipts.read_phase('PREPARED')
                saved_lock_verified = (
                    prepared is not None
                    and prepared[1].facts.prepared_ack is True
                    and strict_json_object(saved) == {'git_receipt_ref': asdict(prepared[0])}
                )
            identities.append(command['id'])
        return tuple(identities) if saved_lock_verified else ()

    def _read_original_commit(self, original):
        return read_delivery_payload(
            self._dispatch._journal._package,
            original,
            format='sha1' if len(original.plan['expected_target_commit']) == 40 else 'sha256',
            maximum=self._limits.max_git_output_bytes,
        )

    def _recover_aborted_refs(self):
        with self._runtime.database.transaction() as connection:
            original = self._original(connection)
            if (
                original.operation['status'] != 'UNKNOWN'
                or original.delivery['git_write_status'] != 'UNKNOWN'
                or original.task['stop_requested_at'] is not None
            ):
                return False
            commands = reference_abort_commands(connection, original)
        if not commands:
            return False
        commit = self._read_original_commit(original)
        proven = self._proved_aborts(
            original,
            commands,
            commit,
            require_saved_lock=original.steps[3]['status'] == 'SUCCEEDED',
        )
        return bool(proven and record_original_ref_abort(self._runtime, self._operation_id, proven))

    def _run(self):
        self._started = True
        original, source, package, target = self._inputs()
        location = self._location(source.root)
        if location.verify().common_directory.canonical_path != source.common_directory:
            raise StorageUnavailable('Original delivery Git location differs')
        proved_aborts = ()
        reuse_completed_preparation = original.steps[3]['status'] == 'SUCCEEDED'
        if original.delivery['git_write_status'] == 'ABORTED_UNSENT':
            with self._runtime.database.transaction() as connection:
                current = self._original(connection, live=True)
                aborted = reference_abort_commands(connection, current)
            proved_aborts = self._proved_aborts(
                original,
                aborted,
                self._read_original_commit(original),
                require_saved_lock=reuse_completed_preparation,
            )
            if not proved_aborts:
                raise StorageUnavailable('Original reference abort receipts must be rechecked')
        commit = fix_delivery_payload(
            self._runtime,
            self._dispatch._journal._package,
            self._operation_id,
            self._binding.owner_epoch,
            format=source.format,
            maximum=package.git_limits.max_object_bytes,
            proved_aborts=proved_aborts,
        )
        if reuse_completed_preparation:
            if not proved_aborts:
                raise StorageUnavailable('Original completed Git preparation has no retry proof')
            self._dispatch._ref_retry_window = original.window['operation_id']
        completed_build = original.steps[1]['status'] == 'SUCCEEDED'
        object_step = 4 if completed_build else 2
        with self._runtime.database.transaction() as connection:
            claimed = self._original(connection, live=True).steps[1]['external_identity']
        read_only = completed_build or (
            claimed is not None
            and strict_json_object(claimed) == read_only_object_claim(original.delivery)
        )
        parsed = self._delivery_config(object_step, location)

        def write_object(intent, raw):
            return self._write_object(location, parsed, source.format, intent, raw)

        with PrivatePackageGuard(package.directory.canonical_path) as verified:
            if verified.verify() != package.directory:
                raise StorageUnavailable('Original delivery candidate directory differs')
            build_original_delivery_objects(
                verified,
                package.binding,
                commit,
                expected_manifest_sha256=package.seal['manifest_sha256'],
                limits=package.limits,
                git_limits=package.git_limits,
                started_at=self._started_at,
                active=self._check_active,
                exchange=None if read_only else write_object,
                read_object=lambda kind, oid, maximum: self._object(
                    object_step, location, parsed, source.format, kind, oid, maximum
                ),
            )
        if not completed_build:
            with self._runtime.database.transaction(write=True) as connection:
                fixed = self._original(connection, live=True)
                if (
                    fixed.steps[1]['status'] != 'RUNNING'
                    or fixed.delivery['planned_commit_oid'] != commit.commit_oid
                ):
                    raise StorageUnavailable('Original local delivery planned object differs')
                at = operation_time(None)
                _step(connection, self._operation_id, 2, 'SUCCEEDED', at)
                _step(
                    connection,
                    self._operation_id,
                    3,
                    'SUCCEEDED',
                    at,
                    result={'planned_commit_oid': commit.commit_oid},
                )
                _step(connection, self._operation_id, 4, 'RUNNING', at)
        receipts = self._ref(
            original,
            target,
            location,
            source.format,
            commit,
            parsed=parsed if completed_build else None,
        )
        self._verify_ack_result(original, target, location, source.format, commit, receipts)
        return original.delivery['id']

    def _head_lease(self, target, location, metadata, *, replace_target=None):
        facts = target.original_target['worktrees']
        listing = WorktreeListing(
            facts['object_format'],
            tuple(WorktreeRecord(**row) for row in facts['entries']),
            facts['listing_sha256'],
        )
        target_ref = target.original_target['target_branch']
        refs = tuple(
            LocalBranch(name, replace_target if name == target_ref and replace_target else oid)
            for name, oid in metadata.verify().heads
        )
        require_target_not_checked_out(listing, refs, target.original_target['target_branch'])
        return WorktreeHeadLease(
            listing,
            refs,
            common_directory=location.verify().common_directory.canonical_path,
            private_roots=self._private_roots,
            max_file_bytes=self._limits.max_file_bytes,
            max_open_handles=self._limits.max_open_handles,
        )

    def _ref(self, original, target, location, format, commit, *, parsed=None):
        if parsed is None:
            parsed = self._delivery_config(4, location)
        metadata = self._metadata(location, format=format)
        snapshot = metadata.verify()
        original_metadata = _metadata_identities(metadata)
        plan = original.plan
        full_ref = plan['target_branch']
        intent = delivery_update(
            original.delivery['id'],
            full_ref,
            commit.commit_oid,
            plan['expected_target_commit'],
            format=format,
        )
        if snapshot.lock_paths or dict(snapshot.heads).get(full_ref) != intent.expected_oid:
            raise WorktreeError('ORIGINAL_DELIVERY_TARGET_CHANGED', code='TARGET_CHANGED')
        reflog = DeliveryReflogIdentity(commit.committer.name, commit.committer.email, int(time()))
        lock_path = location._common.path.joinpath(*full_ref.split('/'))
        lock_path = lock_path.with_name(lock_path.name + '.lock')
        head_lease = self._keep(self._head_lease, target, location, metadata)
        if head_lease.fingerprint_sha256 != target.original_target['worktrees_sha256']:
            raise WorktreeError('ORIGINAL_DELIVERY_WORKTREE_CHANGED', code='TARGET_CHANGED')
        checked_lock = None
        reuse_completed_preparation = self._dispatch._ref_retry_window is not None

        def locked():
            self._check_active()
            head_lease.verify()
            location.verify()
            expected = intent.new_oid.encode('ascii') + b'\n'
            with LockedFileSource(
                lock_path, expected_file=checked_lock, max_file_bytes=len(expected)
            ) as source:
                state = source.verify()
                if state.raw != expected:
                    raise LaunchOutcomeUnknown('ORIGINAL_DELIVERY_REF_LOCK_DIFFERS')
                return state.file

        with self._fixed(
            4,
            DELIVERY_REF_COMMAND_REF,
            location,
            kind='DELIVERY_REF',
            parsed=parsed,
            metadata=metadata,
            ref_intent=intent,
            reflog=reflog,
            intent_sha256=intent.input_sha256,
        ) as (scope, (command, prepare)):
            receipts = None

            def record_prepared(binding):
                nonlocal receipts, checked_lock
                dispatch = self._dispatch
                prepared = dispatch.read_action(scope, 'PREPARE', 'ACKNOWLEDGED')['result']
                if (
                    prepared['stdio_binding']['io_nonce'] != binding.io_nonce
                    or prepared['metadata_source']['ref_intent_sha256'] != binding.intent_sha256
                    or prepared['metadata_source']['metadata_sha256'] != snapshot.fingerprint_sha256
                ):
                    raise LaunchOutcomeUnknown('ORIGINAL_DELIVERY_REF_PROCESS_DIFFERS')
                receipts = self._keep(
                    GitReceiptStore,
                    dispatch._journal,
                    GitReceiptBinding(
                        binding.scope,
                        prepared['guard_run_ref'],
                        original.task['repository_id'],
                        snapshot.fingerprint_sha256,
                        intent.new_oid,
                        format,
                    ),
                    max_receipt_bytes=16384,
                    max_records=100000,
                    unique_phases=True,
                )
                checked_lock = locked()
                with self._runtime.database.transaction(write=True) as connection:
                    current = self._original(connection, live=True)
                    if current.delivery['git_write_status'] != 'NOT_DISPATCHED':
                        raise LaunchOutcomeUnknown('ORIGINAL_DELIVERY_PREPARE_REQUIRES_OBSERVATION')
                    if not reuse_completed_preparation:
                        _step(connection, self._operation_id, 5, 'RUNNING', operation_time(None))
                with self._alternate_dispatch():
                    parsed_query = self._delivery_config(5, location)
                    active_meta = self._metadata(location, format=format)
                    try:
                        state = active_meta.verify()
                        _verify_prepared_metadata(
                            original_metadata, active_meta, lock_path, location._common.path
                        )
                        lock_relative = lock_path.relative_to(location._common.path).as_posix()
                        if state.heads != snapshot.heads or state.lock_paths != (lock_relative,):
                            raise WorktreeError(
                                'ORIGINAL_DELIVERY_LOCKED_TARGET_CHANGED', code='TARGET_CHANGED'
                            )
                        output, _, _, exit_code = self._query(
                            5,
                            DELIVERY_TARGET_COMMAND_REF,
                            location,
                            kind='DELIVERY_TARGET',
                            parsed=parsed_query,
                            metadata=active_meta,
                            target_ref=full_ref,
                        )
                        prepared_ref_observation(
                            output.stdout,
                            intent,
                            query_exit_code=exit_code,
                            max_output_bytes=self._limits.max_git_output_bytes,
                        )
                    finally:
                        active_meta.close()
                locked()
                record = receipts.append(
                    GitReceipt(
                        receipts._binding,
                        'PREPARED',
                        operation_time(None),
                        GitReceiptFacts(
                            True,
                            None,
                            None,
                            GitRefObservation(full_ref, intent.expected_oid, None),
                            head_lease.fingerprint_sha256,
                            'NOT_RUN',
                        ),
                    )
                )
                with self._runtime.database.transaction(write=True) as connection:
                    current = self._original(connection, live=True)
                    if current.delivery['git_write_status'] != 'NOT_DISPATCHED':
                        raise LaunchOutcomeUnknown('ORIGINAL_DELIVERY_PREPARE_REQUIRES_OBSERVATION')
                    connection.execute(
                        "UPDATE code_deliveries SET git_write_status='PREPARED' WHERE id=?",
                        (current.delivery['id'],),
                    )
                    if not reuse_completed_preparation:
                        at = operation_time(None)
                        _step(
                            connection,
                            self._operation_id,
                            4,
                            'SUCCEEDED',
                            at,
                            result={'git_receipt_ref': asdict(record)},
                        )
                        _step(connection, self._operation_id, 5, 'SUCCEEDED', at)
                        _step(connection, self._operation_id, 6, 'RUNNING', at)

            def send(binding):
                if receipts is None:
                    raise LaunchOutcomeUnknown('ORIGINAL_DELIVERY_REF_RECEIPT_MISSING')
                return DeliverySendFence(
                    self._runtime,
                    self._operation_id,
                    self._binding.owner_epoch,
                    intent,
                    receipts,
                    locked,
                )(binding)

            def confirm_ack(binding):
                if receipts is None or receipts._binding.scope != binding.scope:
                    raise LaunchOutcomeUnknown('ORIGINAL_DELIVERY_ACK_SCOPE_DIFFERS')
                receipts.append(
                    GitReceipt(
                        receipts._binding,
                        'COMMIT_ACK',
                        operation_time(None),
                        GitReceiptFacts(True, True, None, None, None, 'NOT_RUN'),
                    )
                )

            def confirm_abort(binding):
                if receipts is None:
                    return
                if receipts._binding.scope != binding.scope:
                    raise LaunchOutcomeUnknown('ORIGINAL_DELIVERY_ABORT_SCOPE_DIFFERS')
                receipts.append(
                    GitReceipt(
                        receipts._binding,
                        'ABORTED',
                        operation_time(None),
                        GitReceiptFacts(True, False, None, None, None, 'NOT_RUN'),
                    )
                )

            exit_code = command.run_delivery_ref(
                prepare,
                intent,
                record_prepared,
                send,
                confirm_ack,
                confirm_abort,
                release_read_lease=metadata.close,
                max_output_bytes=self._limits.max_git_output_bytes,
                deadline=self._deadline,
                cancelled=self._cancelled,
            )
            self._dispatch.complete(exit_code, output_verified=True)
        head_lease.close()
        self._owners.remove(head_lease)
        return receipts

    def _verify_ack_result(self, original, target, location, format, commit, receipts):
        with self._runtime.database.transaction(write=True) as connection:
            current = self._original(connection)
            if current.delivery['git_write_status'] not in (
                'MAY_HAVE_BEEN_SENT',
                'UNKNOWN',
                'CONFIRMED',
            ):
                raise LaunchOutcomeUnknown('ORIGINAL_DELIVERY_ACK_REQUIRES_OBSERVATION')
            if current.steps[6]['status'] != 'SUCCEEDED':
                _step(connection, self._operation_id, 7, 'RUNNING', operation_time(None))
        parsed = self._delivery_config(7, location)
        raw = self._object(
            7, location, parsed, format, 'commit', commit.commit_oid, len(commit.payload)
        )
        self._object(
            7, location, parsed, format, 'tree', commit.tree_oid, self._limits.max_git_output_bytes
        )
        if raw != commit.payload:
            raise StorageUnavailable('Original delivered commit bytes differ')
        branch = original.plan['target_branch']
        observation = None
        verified_descendant = False
        postcheck = 'UNKNOWN'
        metadata = self._metadata(location, format=format)
        try:
            output, _, _, exit_code = self._query(
                7,
                DELIVERY_TARGET_COMMAND_REF,
                location,
                kind='DELIVERY_TARGET',
                parsed=parsed,
                metadata=metadata,
                target_ref=branch,
            )
            observation = exact_direct_ref_observation(
                output.stdout,
                branch,
                format,
                query_exit_code=exit_code,
                max_output_bytes=self._limits.max_git_output_bytes,
            )['oid']
            snapshot = metadata.verify()
            if dict(snapshot.heads).get(branch) != observation:
                raise LaunchOutcomeUnknown('ORIGINAL_DELIVERY_POSTCHECK_TARGET_DIFFERS')
            if observation not in (None, commit.commit_oid, commit.parent_oid):
                query = DeliveryAncestorQuery(format, commit.commit_oid, observation)
                ancestry, _, _, ancestry_exit = self._query(
                    7,
                    DELIVERY_ANCESTOR_COMMAND_REF,
                    location,
                    kind='DELIVERY_ANCESTOR',
                    parsed=parsed,
                    metadata=metadata,
                    ancestry=query,
                    intent_sha256=query.digest,
                    allow_negative_ancestry=True,
                )
                metadata.verify()
                if ancestry.stdout or ancestry.stderr:
                    raise LaunchOutcomeUnknown('ORIGINAL_DELIVERY_ANCESTRY_OUTPUT_DIFFERS')
                verified_descendant = ancestry_exit == 0
            if observation != commit.commit_oid or snapshot.lock_paths:
                postcheck = 'CONFLICT'
            else:
                with self._head_lease(
                    target, location, metadata, replace_target=commit.parent_oid
                ) as heads:
                    heads.verify()
                    postcheck = (
                        'VERIFIED'
                        if heads.fingerprint_sha256 == target.original_target['worktrees_sha256']
                        else 'CONFLICT'
                    )
        except WorktreeError:
            postcheck = 'CONFLICT'
        finally:
            metadata.close()
        ack = receipts.read_phase('COMMIT_ACK')
        observer = self._keep(
            GitReceiptStore,
            self._dispatch._journal,
            receipts._binding,
            max_receipt_bytes=16384,
            max_records=100000,
        )
        observed_receipt = observer.append(
            GitReceipt(
                receipts._binding,
                'OBSERVED',
                operation_time(None),
                GitReceiptFacts(
                    True,
                    True if ack is not None else None,
                    None,
                    GitRefObservation(branch, observation, None),
                    None,
                    postcheck,
                ),
            )
        )
        record_reconciled_delivery(
            self._runtime,
            self._operation_id,
            commit,
            receipts,
            observed_target=observation,
            postcheck=postcheck,
            original_objects_verified=True,
            verified_descendant=verified_descendant,
            observation_ref=asdict(observed_receipt),
        )

    def _record_failure(self, error):
        closed = not self._pending and self._dispatch._original is None
        if (
            closed
            and isinstance(error, WorktreeError)
            and block_unwritten_delivery(self._runtime, self._operation_id, error.code)
        ):
            return
        hold_original_delivery(
            self._runtime,
            self._operation_id,
            native_commands_closed=closed,
        )

    def reconcile_cleanup(self, frames, *, timeout_ms, cancelled):
        for dispatch, command in reversed(tuple(self._pending.items())):
            dispatch.reconnect(frames)
            if command.cleanup_required:
                command.reconcile_cleanup(frames, timeout_ms=timeout_ms, cancelled=cancelled)
            stopped = dispatch.read_action(dispatch._original, 'STOP', 'ACKNOWLEDGED')
            observation = (
                None if stopped is None else stopped['result']['native'].get('observation')
            )
            if type(observation) is not dict or type(observation.get('exit_code')) is not int:
                raise LaunchOutcomeUnknown('ORIGINAL_DELIVERY_GIT_CLEANUP_UNVERIFIED')
            dispatch.complete(observation['exit_code'], output_verified=False)
            self._pending.pop(dispatch)
        hold_original_delivery(self._runtime, self._operation_id, native_commands_closed=True)
        self._recover_aborted_refs()
        self.close()

    def close(self):
        for extra in reversed(self._extra):
            extra.close()
        super().close()


class DeliveryRecoveryRun(DeliveryWriteRun):
    """Close old owners and reread one original planned write without sending again."""

    def _run(self):
        self._started = True
        identity = self._operation_id
        database = self._runtime.database
        with database.transaction() as connection:
            original = self._original(connection)
            pending = connection.execute(
                """SELECT * FROM code_commands WHERE operation_id=?
                   AND status IN ('PENDING','RUNNING','UNKNOWN') ORDER BY id DESC""",
                (identity,),
            ).fetchall()
        for command in pending:
            self._dispatch.recover_original(
                command, deadline=self._deadline, cancelled=self._cancelled
            )
        if original.delivery['git_write_status'] not in (
            'MAY_HAVE_BEEN_SENT',
            'UNKNOWN',
            'CONFIRMED',
        ):
            recover_fixed_delivery_payload(
                self._runtime,
                self._dispatch._journal._package,
                identity,
                maximum=self._limits.max_git_output_bytes,
            )
            hold_original_delivery(self._runtime, identity, native_commands_closed=True)
        if self._recover_aborted_refs():
            return None
        with database.transaction() as connection:
            original = self._original(connection)
            if original.delivery['git_write_status'] not in (
                'MAY_HAVE_BEEN_SENT',
                'UNKNOWN',
                'CONFIRMED',
            ):
                return None
            target = stored_target(connection, original.plan)
            commands = connection.execute(
                """SELECT * FROM code_commands WHERE operation_id=? AND command_ref=?
                   AND started_at IS NOT NULL ORDER BY id LIMIT 18""",
                (identity, DELIVERY_REF_COMMAND_REF),
            ).fetchall()
        if not commands or len(commands) > 17:
            raise StorageUnavailable('Original delivery write process differs')
        commit = self._read_original_commit(original)
        previous = commands[:-1]
        if previous and self._proved_aborts(original, previous, commit) != tuple(
            row['id'] for row in previous
        ):
            raise StorageUnavailable('Earlier original ref attempts remain unresolved')
        receipts = self._reference_receipts(original, commands[-1], commit)
        _, source, _, _ = load_baseline_query(self._runtime, original.task['base_snapshot_id'])
        location = self._location(source.root)
        if (
            location.verify().common_directory.canonical_path != source.common_directory
            or source.format != commit.format
        ):
            raise StorageUnavailable('Original delivery recovery repository differs')
        self._verify_ack_result(original, target, location, source.format, commit, receipts)
        return original.delivery['id']
