"""Durable original delivery inputs and the one native reference send fence."""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.git_baseline_ref_transaction import (
    RefCommitPermit,
    RefProcessBinding,
)
from backend.app.infrastructure.git_commit_input import (
    CommitIdentity,
    build_delivery_commit,
    verify_stored_delivery_commit,
)
from backend.app.infrastructure.git_ref_protocol import delivery_update
from backend.app.infrastructure.guard_control_git_input import (
    CONFIG_COMMAND_REF,
    DELIVERY_OBJECT_COMMAND_REF,
    DELIVERY_REF_COMMAND_REF,
    OBJECT_BATCH_COMMAND_REF,
)
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown
from backend.app.infrastructure.windows_config_source import LockedFileSource
from backend.app.infrastructure.windows_local_paths import FileIdentity
from backend.app.infrastructure.windows_private_record import PrivateRecordAppend
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_json_object

from .task_delivery import DELIVER, _deliver_authorization, original_operation
from .task_resume_runtime import _operation, _step


class DeliveryFenced(LaunchOutcomeUnknown):
    """This execution is no longer authorized to send the original write."""


@dataclass(frozen=True)
class OriginalDelivery:
    task: object
    operation: object
    fixed: dict
    steps: tuple
    delivery: object
    acceptance: object
    plan: object
    window: object


def load_original_delivery(connection, operation_id):
    operation, fixed, steps = original_operation(connection, operation_id, DELIVER)
    task = connection.execute(
        'SELECT * FROM code_tasks WHERE id=?', (operation['task_id'],)
    ).fetchone()
    delivery = connection.execute(
        'SELECT * FROM code_deliveries WHERE operation_id=? AND task_id=?',
        (operation_id, operation['task_id']),
    ).fetchone()
    if task is None or delivery is None:
        raise StorageUnavailable('Original delivery task or record is missing')
    acceptance = connection.execute(
        'SELECT * FROM code_acceptances WHERE id=? AND task_id=?',
        (delivery['acceptance_id'], task['id']),
    ).fetchone()
    plan = connection.execute(
        'SELECT * FROM code_delivery_plans WHERE id=? AND task_id=?',
        (delivery['delivery_plan_id'], task['id']),
    ).fetchone()
    window = connection.execute(
        'SELECT * FROM code_delivery_windows WHERE id=? AND delivery_id=?',
        (delivery['current_window_id'], delivery['id']),
    ).fetchone()
    if (
        acceptance is None
        or plan is None
        or window is None
        or plan['id'] != fixed['delivery_plan_id']
        or acceptance['delivery_plan_id'] != plan['id']
        or any(
            acceptance[field] != fixed[field] or plan[field] != fixed[field]
            for field in ('candidate_id', 'test_report_id')
        )
        or plan['expected_target_commit'] != fixed['expected_target_commit']
        or plan['target_branch'] != task['target_branch']
        or acceptance['manual_risk_accepted'] != int(fixed['manual_risk_accepted'])
    ):
        raise StorageUnavailable('Original delivery plan, acceptance or window differs')
    if window['operation_id'] != operation['id']:
        from .task_resume import original_resume_steps

        renewal = connection.execute(
            """SELECT * FROM code_operations WHERE id=? AND task_id=?
               AND operation_type='RESUME' AND status='SUCCEEDED'""",
            (window['operation_id'], task['id']),
        ).fetchone()
        if renewal is None:
            raise StorageUnavailable('Original delivery window renewal is missing')
        fixed_renewal, renewal_steps = original_resume_steps(connection, renewal)
        if (
            fixed_renewal.get('repository_quiescent_confirmed') is not True
            or fixed_renewal['operation_id'] != operation['id']
            or window['confirmed_at'] != renewal['created_at']
            or window['controller_epoch_ref']
            != strict_json_object(renewal_steps[0]['external_identity'])['controller_epoch']
            or strict_json_object(renewal_steps[-1]['result_ref'])
            != {'delivery_window_id': window['id']}
        ):
            raise StorageUnavailable('Original delivery renewed window differs')
    return OriginalDelivery(
        task, operation, fixed, tuple(steps), delivery, acceptance, plan, window
    )


def require_live_delivery(connection, current, epoch, at):
    task, operation, fixed = current.task, current.operation, current.fixed
    if (
        task['stop_requested_at'] is not None
        or task['status'] not in ('AWAITING_ACCEPTANCE', 'WAITING', 'RUNNING')
        or task['phase'] not in ('ACCEPTANCE', 'DELIVERY')
        or task['control_generation'] != operation['control_generation']
        or task['active_session_id'] != operation['session_id']
        or task['current_candidate_id'] != fixed['candidate_id']
        or task['current_test_report_id'] != fixed['test_report_id']
        or task['current_delivery_plan_id'] != fixed['delivery_plan_id']
        or task['current_delivery_id'] != current.delivery['id']
        or operation['status'] not in ('PENDING', 'RUNNING')
        or current.window['controller_epoch_ref'] != epoch
        or not current.window['confirmed_at'] <= at < current.window['expires_at']
        or _deliver_authorization(connection, task) is None
    ):
        raise DeliveryFenced('ORIGINAL_DELIVERY_WINDOW_OR_CONTROL_FENCED')
    blocked = connection.execute(
        """SELECT 1 FROM code_deliveries d JOIN code_tasks t ON t.id=d.task_id
           JOIN code_operations o ON o.id=d.operation_id
           WHERE t.repository_id=? AND d.id<>?
           AND (d.status IN ('PREPARING','WRITING','UNKNOWN')
             OR (d.status='SUCCEEDED' AND o.status IN ('PENDING','RUNNING','UNKNOWN')))
           LIMIT 1""",
        (task['repository_id'], current.delivery['id']),
    ).fetchone()
    if blocked is not None:
        raise DeliveryFenced('ORIGINAL_REPOSITORY_DELIVERY_FENCED')


def _payload_name(current):
    identity = f'DELIVERY-COMMIT:{current.operation["id"]}:{current.delivery["id"]}'
    return sha256(identity.encode('ascii')).hexdigest()[:32] + '.delivery-commit.bin'


def _stored_payload(package, current, *, format, maximum):
    delivery, plan = current.delivery, current.plan
    name = _payload_name(current)
    record = strict_json_object(delivery['commit_input_ref'])
    if set(record) != {'filename', 'sha256', 'byte_count', 'file'} or record['filename'] != name:
        raise StorageUnavailable('Original delivery payload location differs')
    identity = FileIdentity(**record['file'])
    if (
        package.verify_member(name, directory=False) != identity
        or record['sha256'] != delivery['commit_input_sha256']
    ):
        raise StorageUnavailable('Original delivery payload identity differs')
    with LockedFileSource(
        package.path / name, expected_file=identity, max_file_bytes=maximum
    ) as file:
        raw = file.verify().raw
    if len(raw) != record['byte_count']:
        raise StorageUnavailable('Original delivery payload size differs')
    return verify_stored_delivery_commit(
        raw,
        format=format,
        tree_oid=plan['result_tree_oid'],
        parent_oid=plan['expected_target_commit'],
        delivery_id=delivery['id'],
        expected_payload_sha256=delivery['commit_input_sha256'],
        expected_commit_oid=delivery['planned_commit_oid'],
        max_payload_bytes=maximum,
    )


def read_delivery_payload(package, current, *, format, maximum):
    if (
        current.delivery['commit_input_ref'] is None
        or current.delivery['planned_commit_oid'] is None
    ):
        raise StorageUnavailable('Original delivery payload has not been fixed')
    return _stored_payload(package, current, format=format, maximum=maximum)


def read_only_object_claim(delivery):
    """The recovery step is bound to the actual original planned object."""
    planned_oid = delivery['planned_commit_oid']
    return {'planned_commit_oid': planned_oid} if planned_oid is not None else None


def reference_abort_commands(connection, current):
    """Return original closed refs for which a native unsent proof is still required."""
    from .coding_job_evidence import read_closed_candidate_job_ids

    steps, delivery = current.steps, current.delivery
    ref_step, verify_step, send_step = steps[3:6]
    before_saved_lock = (
        ref_step['status'] in ('RUNNING', 'UNKNOWN')
        and ref_step['result_ref'] is None
        and verify_step['status'] in ('PENDING', 'RUNNING', 'UNKNOWN')
        and send_step['status'] == 'PENDING'
    )
    after_saved_lock = (
        ref_step['status'] == 'SUCCEEDED'
        and ref_step['result_ref'] is not None
        and verify_step['status'] == 'SUCCEEDED'
        and send_step['status'] in ('RUNNING', 'UNKNOWN')
    )
    if (
        delivery['commit_input_ref'] is None
        or delivery['planned_commit_oid'] is None
        or delivery['delivered_at'] is not None
        or any(step['status'] != 'SUCCEEDED' for step in steps[:3])
        or steps[0]['result_ref'] is None
        or steps[2]['result_ref'] is None
        or any(
            strict_json_object(steps[index]['result_ref'])
            != {'planned_commit_oid': delivery['planned_commit_oid']}
            for index in (0, 2)
        )
        or not (before_saved_lock or after_saved_lock)
        or any(step['status'] != 'PENDING' for step in steps[6:])
        or ref_step['external_identity'] is not None
        or any(
            step['result_ref'] is not None or step['external_identity'] is not None
            for step in steps[4:]
        )
        or read_closed_candidate_job_ids(connection, current.task['id']) is None
    ):
        return ()
    rows = connection.execute(
        """SELECT * FROM code_commands WHERE operation_id=? AND command_ref=?
           ORDER BY id LIMIT 17""",
        (current.operation['id'], DELIVERY_REF_COMMAND_REF),
    ).fetchall()
    if (
        not rows
        or len(rows) > 16
        or any(
            row['status'] != 'FAILED' or row['exit_code'] != 0 or row['runtime_binding'] is None
            for row in rows
        )
    ):
        return ()
    return tuple(rows)


def record_original_ref_abort(runtime, operation_id, command_ids):
    """Keep a proved native abort as part of the original Delivery."""
    runtime.commands().process_lock.assert_owned()
    with runtime.database.transaction(write=True) as connection:
        current = load_original_delivery(connection, operation_id)
        if (
            current.operation['status'] != 'UNKNOWN'
            or current.task['status'] != 'WAITING'
            or current.task['phase'] != 'DELIVERY'
            or current.task['stop_requested_at'] is not None
            or current.task['control_generation'] != current.operation['control_generation']
            or current.task['active_session_id'] != current.operation['session_id']
            or current.delivery['status'] != 'UNKNOWN'
            or current.delivery['git_write_status'] != 'UNKNOWN'
            or not command_ids
            or command_ids
            != tuple(row['id'] for row in reference_abort_commands(connection, current))
        ):
            return False
        at = max(operation_time(None), current.task['updated_at'])
        connection.execute(
            """UPDATE code_deliveries SET status='PENDING',git_write_status='ABORTED_UNSENT',
               postcheck_status='NOT_RUN',last_reconciled_at=? WHERE id=?""",
            (at, current.delivery['id']),
        )
        return True


def unwritten_delivery_stage(connection, current):
    """Identify the next original step without inferring that a ref write was unsent."""
    delivery, steps = current.delivery, current.steps
    if delivery['status'] == 'PENDING' and delivery['git_write_status'] == 'ABORTED_UNSENT':
        return (
            'VERIFY_ABORTED_REF'
            if delivery['last_reconciled_at'] is not None
            and reference_abort_commands(connection, current)
            else None
        )
    planned_oid = delivery['planned_commit_oid']
    fixed = delivery['commit_input_ref'] is not None
    object_claim = read_only_object_claim(delivery)
    recorded_claim = None if object_claim is None else canonical_input(object_claim)
    if (
        delivery['status'] != 'PENDING'
        or delivery['git_write_status'] != 'NOT_DISPATCHED'
        or any(
            step['external_identity'] is not None for index, step in enumerate(steps) if index != 1
        )
        or steps[1]['external_identity'] not in (None, recorded_claim)
        or any(step['status'] != 'PENDING' or step['result_ref'] is not None for step in steps[4:])
        or fixed != (planned_oid is not None and delivery['commit_input_sha256'] is not None)
        or (not fixed and (planned_oid is not None or delivery['commit_input_sha256'] is not None))
        or steps[0]['status'] != ('SUCCEEDED' if fixed else 'PENDING')
        or (
            steps[0]['result_ref'] is not None
            if not fixed
            else strict_json_object(steps[0]['result_ref']) != {'planned_commit_oid': planned_oid}
        )
    ):
        return None

    operation_id = current.operation['id']
    if (
        steps[1]['status'] in (('PENDING', 'UNKNOWN') if fixed else ('PENDING',))
        and steps[1]['result_ref'] is None
        and steps[1]['external_identity'] is None
        and all(step['status'] == 'PENDING' and step['result_ref'] is None for step in steps[2:4])
        and connection.execute(
            'SELECT 1 FROM code_commands WHERE operation_id=? LIMIT 1', (operation_id,)
        ).fetchone()
        is None
    ):
        return 'BUILD'

    if not fixed or steps[1]['result_ref'] is not None or steps[3]['result_ref'] is not None:
        return None
    interrupted_build = (
        steps[1]['status'] == 'UNKNOWN'
        and steps[1]['started_at'] is not None
        and all(step['status'] == 'PENDING' and step['result_ref'] is None for step in steps[2:4])
    )
    closed_build = (
        steps[1]['status'] == 'SUCCEEDED'
        and steps[2]['status'] == 'SUCCEEDED'
        and strict_json_object(steps[2]['result_ref']) == {'planned_commit_oid': planned_oid}
        and steps[3]['status'] in ('PENDING', 'UNKNOWN')
    )
    if not (interrupted_build or closed_build):
        return None

    # Only closed object/config commands are eligible. Any reference command
    # row, even CANCELLED, requires a separate native recovery proof.
    rows = connection.execute(
        """SELECT COUNT(CASE WHEN command_ref=? THEN 1 END) AS object_writes,
                  COUNT(CASE WHEN purpose<>'CONTROL_GIT' OR task_id<>?
                      OR session_id IS NOT ? OR command_ref NOT IN (?,?,?)
                      OR status NOT IN ('SUCCEEDED','FAILED','CANCELLED')
                      OR ended_at IS NULL
                      OR (status IN ('SUCCEEDED','FAILED') AND
                          (process_identity IS NULL OR runtime_binding IS NULL OR exit_code IS NULL))
                      OR (status='SUCCEEDED' AND exit_code<>0)
                      THEN 1 END) AS ineligible,
                  COUNT(CASE WHEN command_ref=? AND status<>'SUCCEEDED' THEN 1 END) AS unverified_writes
           FROM code_commands WHERE operation_id=?""",
        (
            DELIVERY_OBJECT_COMMAND_REF,
            current.task['id'],
            current.operation['session_id'],
            CONFIG_COMMAND_REF,
            OBJECT_BATCH_COMMAND_REF,
            DELIVERY_OBJECT_COMMAND_REF,
            DELIVERY_OBJECT_COMMAND_REF,
            operation_id,
        ),
    ).fetchone()
    if rows['object_writes'] == 0 or rows['ineligible'] != 0:
        return None
    if interrupted_build:
        return 'RECOVER_OBJECT_BUILD'
    if rows['unverified_writes'] != 0 and steps[1]['external_identity'] is None:
        return None
    return 'VERIFY_OBJECTS'


def fix_delivery_payload(
    runtime, package, operation_id, epoch, *, format, maximum, proved_aborts=()
):
    """Claim the original BUILD time, then append its exact bytes before any Git command."""
    runtime.commands().process_lock.assert_owned()
    with runtime.database.transaction(write=True) as connection:
        current = load_original_delivery(connection, operation_id)
        at = operation_time(None)
        require_live_delivery(connection, current, epoch, at)
        delivery, plan, task = current.delivery, current.plan, current.task
        stage = unwritten_delivery_stage(connection, current)
        if current.operation['status'] != 'PENDING' or stage is None:
            raise StorageUnavailable('Original delivery preparation requires observation')
        if delivery['commit_input_ref'] is not None:
            if stage != 'BUILD' and current.window['operation_id'] == operation_id:
                raise StorageUnavailable('Original object verification needs a renewed window')
            if stage == 'VERIFY_ABORTED_REF' and (
                not proved_aborts
                or proved_aborts
                != tuple(row['id'] for row in reference_abort_commands(connection, current))
            ):
                raise StorageUnavailable('Original reference abort receipts must be rechecked')
            commit = read_delivery_payload(package, current, format=format, maximum=maximum)
            next_step = 2
            if stage in ('VERIFY_OBJECTS', 'VERIFY_ABORTED_REF'):
                next_step = 6 if current.steps[3]['status'] == 'SUCCEEDED' else 4
            _operation(connection, operation_id, 'RUNNING', at)
            _step(
                connection,
                operation_id,
                next_step,
                'RUNNING',
                at,
                intent=read_only_object_claim(delivery)
                if stage == 'RECOVER_OBJECT_BUILD'
                else None,
            )
            connection.execute(
                "UPDATE code_deliveries SET status='PREPARING',git_write_status='NOT_DISPATCHED' WHERE id=?",
                (delivery['id'],),
            )
            return commit
        profile = connection.execute(
            'SELECT delivery FROM code_execution_profile_versions WHERE id=?',
            (task['execution_profile_version_id'],),
        ).fetchone()
        options = strict_json_object(profile['delivery'])
        _operation(connection, operation_id, 'RUNNING', at)
        _step(connection, operation_id, 1, 'RUNNING', at)
        connection.execute(
            "UPDATE code_deliveries SET status='PREPARING' WHERE id=?",
            (delivery['id'],),
        )

    commit = build_delivery_commit(
        format=format,
        tree_oid=plan['result_tree_oid'],
        parent_oid=plan['expected_target_commit'],
        delivery_id=delivery['id'],
        fixed_unix_seconds=int(datetime.fromisoformat(at).timestamp()),
        author=CommitIdentity(options['author_name'], options['author_email']),
        committer=CommitIdentity(options['committer_name'], options['committer_email']),
        message_template=options['message_template'],
        task_id=task['id'],
        candidate_id=plan['candidate_id'],
        max_payload_bytes=maximum,
    )
    name = _payload_name(current)
    with PrivateRecordAppend(package, name, commit.payload, max_record_bytes=maximum) as writer:
        reference = writer.publish()

    with runtime.database.transaction(write=True) as connection:
        claimed = load_original_delivery(connection, operation_id)
        now = operation_time(None)
        require_live_delivery(connection, claimed, epoch, now)
        if (
            claimed.steps[0]['started_at'] != at
            or claimed.steps[0]['status'] != 'RUNNING'
            or claimed.delivery['commit_input_ref'] is not None
        ):
            raise StorageUnavailable('Original delivery BUILD claim differs')
        connection.execute(
            """UPDATE code_deliveries SET commit_input_ref=?,commit_input_sha256=?,planned_commit_oid=?
               WHERE id=?""",
            (
                canonical_input(asdict(reference)),
                commit.payload_sha256,
                commit.commit_oid,
                delivery['id'],
            ),
        )
        _step(
            connection,
            operation_id,
            1,
            'SUCCEEDED',
            now,
            result={'planned_commit_oid': commit.commit_oid},
        )
        _step(connection, operation_id, 2, 'RUNNING', now)
    return commit


def _report_assets_current(connection, current):
    return (
        connection.execute(
            """SELECT 1 FROM testing_reports r
           JOIN testing_plan_versions p ON p.id=r.plan_version_id
           JOIN testing_pack_versions b ON b.id=r.test_pack_version_id AND b.plan_version_id=p.id
           WHERE r.id=? AND r.result='PASSED' AND p.status='PUBLISHED' AND b.status='PUBLISHED'""",
            (current.fixed['test_report_id'],),
        ).fetchone()
        is not None
    )


class DeliverySendFence:
    """Bind one prepared native writer to the original database/STOP ordering."""

    def __init__(self, runtime, operation_id, epoch, intent, receipts, locked_target):
        self._runtime, self._operation, self._epoch = runtime, operation_id, epoch
        self._intent, self._receipts, self._locked_target = intent, receipts, locked_target
        self._issued = False

    def _validate(self, connection, binding, phase):
        current = load_original_delivery(connection, self._operation)
        now = operation_time(None)
        require_live_delivery(connection, current, self._epoch, now)
        delivery, plan, steps = current.delivery, current.plan, current.steps
        expected = delivery_update(
            delivery['id'],
            plan['target_branch'],
            delivery['planned_commit_oid'],
            plan['expected_target_commit'],
            format=self._intent.object_format,
        )
        if (
            type(binding) is not RefProcessBinding
            or binding.scope.operation_id != self._operation
            or binding.scope.step_no != 4
            or binding.scope != self._receipts._binding.scope
            or binding.intent_sha256 != expected.input_sha256
            or expected != self._intent
            or delivery['git_write_status'] != phase
            or not _report_assets_current(connection, current)
            or any(step['status'] != 'SUCCEEDED' for step in steps[:5])
            or steps[5]['status'] != 'RUNNING'
        ):
            raise DeliveryFenced('ORIGINAL_DELIVERY_REF_FENCE_DIFFERS')
        return current, now

    @contextmanager
    def __call__(self, binding):
        if self._issued:
            raise DeliveryFenced('ORIGINAL_DELIVERY_REF_REQUIRES_OBSERVATION')
        self._issued = True
        self._runtime.commands().process_lock.assert_owned()
        from backend.app.infrastructure.git_receipts import GitReceipt, GitReceiptFacts

        prepared = self._receipts.read_phase('PREPARED')
        if prepared is None or prepared[1].facts.prepared_ack is not True:
            raise DeliveryFenced('ORIGINAL_DELIVERY_PREPARE_RECEIPT_MISSING')
        self._locked_target()
        with self._runtime.database.transaction() as connection:
            _, at = self._validate(connection, binding, 'PREPARED')
        receipt = self._receipts.append(
            GitReceipt(
                self._receipts._binding,
                'COMMIT_MAY_BE_SENT',
                at,
                GitReceiptFacts(True, None, None, None, None, 'NOT_RUN'),
            )
        )
        with self._runtime.database.transaction(write=True) as connection:
            current, at = self._validate(connection, binding, 'PREPARED')
            connection.execute(
                """UPDATE code_deliveries SET status='WRITING',git_write_status='MAY_HAVE_BEEN_SENT'
                   WHERE id=?""",
                (current.delivery['id'],),
            )
            _step(
                connection,
                self._operation,
                6,
                'RUNNING',
                at,
                intent={'git_receipt_ref': asdict(receipt)},
            )

        # Reacquire only after the MAY record is committed. A concurrent STOP
        # wins if it committed first. No pipe reads or Git wait under this lock.
        self._locked_target()
        with self._runtime.database.transaction(write=True) as connection:
            self._validate(connection, binding, 'MAY_HAVE_BEEN_SENT')
            yield RefCommitPermit(binding)


def record_reconciled_delivery(
    runtime,
    operation_id,
    commit,
    receipts,
    *,
    observed_target,
    postcheck,
    original_objects_verified,
    verified_descendant=False,
    observation_ref=None,
):
    """Save the original Git fact, preserving an independent postcheck result."""
    from backend.app.infrastructure.git_commit_input import DeliveryCommitInput
    from backend.app.infrastructure.git_receipt_store import GitReceiptStore

    if (
        type(commit) is not DeliveryCommitInput
        or type(receipts) is not GitReceiptStore
        or receipts._binding.scope.operation_id != operation_id
        or receipts._binding.planned_commit_oid != commit.commit_oid
        or type(original_objects_verified) is not bool
        or type(verified_descendant) is not bool
        or verified_descendant
        and observed_target in (None, commit.parent_oid, commit.commit_oid)
        or postcheck not in ('VERIFIED', 'CONFLICT', 'UNKNOWN')
    ):
        raise StorageUnavailable('Original delivery reconciliation input differs')
    sent = receipts.read_phase('COMMIT_MAY_BE_SENT')
    ack = receipts.read_phase('COMMIT_ACK')
    if sent is None or sent[1].facts.prepared_ack is not True:
        raise StorageUnavailable('Original delivery write dispatch proof is missing')
    confirmed = original_objects_verified and (
        observed_target == commit.commit_oid
        or verified_descendant
        or (ack is not None and ack[1].facts.commit_ack is True)
    )
    if postcheck == 'VERIFIED' and not (confirmed and observed_target == commit.commit_oid):
        raise StorageUnavailable('Original delivery postcheck lacks verified current target')
    with runtime.database.transaction(write=True) as connection:
        current = load_original_delivery(connection, operation_id)
        row, task = current.delivery, current.task
        if (
            row['id'] != commit.delivery_id
            or row['planned_commit_oid'] != commit.commit_oid
            or row['commit_input_sha256'] != commit.payload_sha256
            or current.plan['target_branch'] != task['target_branch']
            or row['git_write_status'] not in ('MAY_HAVE_BEEN_SENT', 'UNKNOWN', 'CONFIRMED')
        ):
            raise StorageUnavailable('Original delivery changed during reconciliation')
        at = max(operation_time(None), task['updated_at'])
        if row['git_write_status'] == 'CONFIRMED':
            # A later conflicting tip updates postcheck without undoing delivery.
            confirmed = True
        if confirmed:
            connection.execute(
                """UPDATE code_deliveries SET status='SUCCEEDED',git_write_status='CONFIRMED',
                   postcheck_status=?,observed_target_commit=?,delivered_at=coalesce(delivered_at,?),
                   last_reconciled_at=?,failure_code=NULL WHERE id=?""",
                (postcheck, observed_target, at, at, row['id']),
            )
            if current.steps[5]['status'] != 'SUCCEEDED':
                _step(connection, operation_id, 6, 'SUCCEEDED', at)
            if current.steps[6]['status'] != 'SUCCEEDED':
                _step(
                    connection,
                    operation_id,
                    7,
                    'SUCCEEDED',
                    at,
                    result={
                        'postcheck_status': postcheck,
                        'verified_descendant': verified_descendant,
                        'git_receipt_ref': observation_ref,
                    },
                )
        else:
            connection.execute(
                """UPDATE code_deliveries SET status='UNKNOWN',git_write_status='UNKNOWN',
                   postcheck_status='UNKNOWN',observed_target_commit=?,last_reconciled_at=? WHERE id=?""",
                (observed_target, at, row['id']),
            )
            _step(connection, operation_id, 7, 'UNKNOWN', at)
        _operation(connection, operation_id, 'UNKNOWN', at)
        _wait_for_delivery(connection, task, row, at)
        return confirmed


def hold_original_delivery(runtime, operation_id, *, native_commands_closed=False):
    """Retain an unresolved original operation without giving it another write permit."""
    with runtime.database.transaction(write=True) as connection:
        current = load_original_delivery(connection, operation_id)
        if current.operation['status'] not in ('PENDING', 'RUNNING', 'UNKNOWN'):
            return
        delivery, task = current.delivery, current.task
        at = max(operation_time(None), task['updated_at'])
        write_status = delivery['git_write_status']
        original_ref_claimed = (
            connection.execute(
                """SELECT 1 FROM code_commands WHERE operation_id=? AND command_ref=?
               AND started_at IS NOT NULL LIMIT 1""",
                (operation_id, DELIVERY_REF_COMMAND_REF),
            ).fetchone()
            is not None
        )
        # The private MAY receipt can survive a failed SQLite write. A closed Job
        # alone cannot prove that an earlier reference command never sent COMMIT.
        uncertain = write_status in ('PREPARED', 'MAY_HAVE_BEEN_SENT', 'UNKNOWN') or (
            write_status == 'NOT_DISPATCHED' and original_ref_claimed
        )
        if uncertain:
            connection.execute(
                """UPDATE code_deliveries SET status='UNKNOWN',git_write_status='UNKNOWN',
                   postcheck_status='UNKNOWN' WHERE id=?""",
                (delivery['id'],),
            )
        elif native_commands_closed and write_status == 'NOT_DISPATCHED':
            connection.execute(
                "UPDATE code_deliveries SET status='PENDING' WHERE id=?", (delivery['id'],)
            )
        for step in current.steps:
            if step['status'] == 'RUNNING':
                _step(connection, operation_id, step['step_no'], 'UNKNOWN', at)
        _operation(connection, operation_id, 'UNKNOWN', at)
        _wait_for_delivery(connection, task, delivery, at)


def _wait_for_delivery(connection, task, delivery, at):
    if task['stop_requested_at'] is not None or task['status'] in ('COMPLETED', 'TERMINATED'):
        return
    wait = connection.execute(
        """SELECT 1 FROM code_waiting_items WHERE task_id=? AND source_kind='DELIVERY'
           AND source_id=? AND kind='DELIVERY_RESULT' AND status='OPEN'""",
        (task['id'], delivery['id']),
    ).fetchone()
    if wait is not None and task['status'] == 'WAITING' and task['resume_phase'] == 'DELIVERY':
        return
    if wait is None:
        connection.execute(
            """INSERT INTO code_waiting_items(id,task_id,kind,source_kind,source_id,resume_phase,
               status,created_at) VALUES(?,?,'DELIVERY_RESULT','DELIVERY',?,'DELIVERY','OPEN',?)""",
            (entity_id(connection, EntityKind.WAITING_ITEM), task['id'], delivery['id'], at),
        )
    connection.execute(
        """UPDATE code_tasks SET status='WAITING',phase='DELIVERY',resume_phase='DELIVERY',
           state_version=?,updated_at=?,last_observed_at=? WHERE id=?""",
        (increment(task['state_version']), at, at, task['id']),
    )


def recover_fixed_delivery_payload(runtime, package, operation_id, *, maximum):
    """Recover the original immutable BUILD bytes after losing only their SQLite publication."""
    from backend.app.infrastructure.git_object_read import git_object_id
    from backend.app.infrastructure.windows_private_record import PrivateRecordReference

    with runtime.database.transaction() as connection:
        original = load_original_delivery(connection, operation_id)
        step = original.steps[0]
        if (
            original.delivery['commit_input_ref'] is not None
            or original.delivery['git_write_status'] != 'NOT_DISPATCHED'
            or step['status'] not in ('RUNNING', 'UNKNOWN')
            or step['started_at'] is None
            or connection.execute(
                'SELECT 1 FROM code_commands WHERE operation_id=? LIMIT 1', (operation_id,)
            ).fetchone()
            is not None
        ):
            return False
        options = connection.execute(
            'SELECT delivery FROM code_execution_profile_versions WHERE id=?',
            (original.task['execution_profile_version_id'],),
        ).fetchone()
        if options is None:
            raise StorageUnavailable('Original delivery configuration is missing')
        options = strict_json_object(options['delivery'])
    name = _payload_name(original)
    path = package.path / name
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    identity = package.verify_member(name, directory=False)
    with LockedFileSource(path, expected_file=identity, max_file_bytes=maximum) as source:
        original_bytes = source.verify()
        raw = original_bytes.raw
    format = 'sha1' if len(original.plan['expected_target_commit']) == 40 else 'sha256'
    planned_oid = git_object_id(raw, format=format, object_type='commit')
    commit = verify_stored_delivery_commit(
        raw,
        format=format,
        tree_oid=original.plan['result_tree_oid'],
        parent_oid=original.plan['expected_target_commit'],
        delivery_id=original.delivery['id'],
        expected_payload_sha256=original_bytes.sha256,
        expected_commit_oid=planned_oid,
        max_payload_bytes=maximum,
    )
    if (
        commit.fixed_unix_seconds != int(datetime.fromisoformat(step['started_at']).timestamp())
        or commit.author != CommitIdentity(options['author_name'], options['author_email'])
        or commit.committer != CommitIdentity(options['committer_name'], options['committer_email'])
    ):
        raise StorageUnavailable('Original delivery recovered payload does not belong to BUILD')
    reference = PrivateRecordReference(name, commit.payload_sha256, len(raw), identity)
    with runtime.database.transaction(write=True) as connection:
        current = load_original_delivery(connection, operation_id)
        if (
            current.steps[0]['started_at'] != step['started_at']
            or current.delivery['git_write_status'] != 'NOT_DISPATCHED'
            or current.delivery['commit_input_ref'] is not None
        ):
            raise StorageUnavailable('Original delivery BUILD observation changed')
        at = operation_time(None)
        connection.execute(
            """UPDATE code_deliveries SET commit_input_ref=?,commit_input_sha256=?,planned_commit_oid=?
               WHERE id=?""",
            (
                canonical_input(asdict(reference)),
                commit.payload_sha256,
                planned_oid,
                commit.delivery_id,
            ),
        )
        _step(
            connection, operation_id, 1, 'SUCCEEDED', at, result={'planned_commit_oid': planned_oid}
        )
    return True


def block_unwritten_delivery(runtime, operation_id, reason):
    """Keep original acceptance history and allow a fresh preview after a proved refusal."""
    if reason not in ('TARGET_CHANGED', 'TARGET_CHECKED_OUT', 'TEST_REPORT_NOT_ELIGIBLE'):
        return False
    with runtime.database.transaction(write=True) as connection:
        original = load_original_delivery(connection, operation_id)
        delivery, task = original.delivery, original.task
        if (
            original.operation['status'] not in ('PENDING', 'RUNNING', 'UNKNOWN')
            or delivery['git_write_status'] not in ('NOT_DISPATCHED', 'ABORTED_UNSENT')
            or original.steps[5]['external_identity'] is not None
            or connection.execute(
                """SELECT 1 FROM code_commands WHERE operation_id=?
                   AND status IN ('PENDING','RUNNING','UNKNOWN') LIMIT 1""",
                (operation_id,),
            ).fetchone()
            is not None
        ):
            return False
        at = max(operation_time(None), task['updated_at'])
        connection.execute(
            "UPDATE code_deliveries SET status='BLOCKED',failure_code=? WHERE id=?",
            (reason, delivery['id']),
        )
        current = next(
            (
                step
                for step in original.steps
                if step['status'] in ('PENDING', 'RUNNING', 'UNKNOWN')
            ),
            None,
        )
        if current is not None:
            _step(connection, operation_id, current['step_no'], 'FAILED', at)
        _operation(connection, operation_id, 'FAILED', at, reason)
        if task['stop_requested_at'] is None and task['current_delivery_id'] == delivery['id']:
            bad_report = reason == 'TEST_REPORT_NOT_ELIGIBLE'
            connection.execute(
                """UPDATE code_tasks SET status=?,phase=?,resume_phase=NULL,current_delivery_id=NULL,
                   current_delivery_plan_id=NULL,current_test_report_id=?,state_version=?,updated_at=?
                   WHERE id=?""",
                (
                    'AWAITING_TESTING' if bad_report else 'AWAITING_ACCEPTANCE',
                    'TESTING' if bad_report else 'ACCEPTANCE',
                    None if bad_report else task['current_test_report_id'],
                    increment(task['state_version']),
                    at,
                    task['id'],
                ),
            )
            connection.execute(
                """UPDATE code_waiting_items SET status='RESOLVED',resolved_at=?,resolution_ref=?
                   WHERE task_id=? AND source_kind='DELIVERY' AND source_id=? AND status='OPEN'""",
                (
                    at,
                    canonical_input({'operation_id': operation_id, 'outcome': reason}),
                    task['id'],
                    delivery['id'],
                ),
            )
        return True
