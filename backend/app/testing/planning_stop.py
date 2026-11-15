"""Prove the local draft transport is closed without refunding an unknown charge."""

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input

from .planning import CALL_STEP, SAVE_STEP, read_original_draft

DRAFT_STOP_POLICY = 'TEST20-DRAFT-STOP-1'


def original_draft_stop_scope(connection, task, stop, fixed):
    if (
        task['draft_plan_operation_id'] is None
        or task['current_verification_id'] is not None
        or task['report_id'] is not None
        or task['control_generation'] != fixed['prior_generation'] + 1
        or fixed['prior_status'] not in ('DRAFT', 'READY', 'PLANNING', 'WAITING')
        or fixed['prior_operation_id'] not in (None, task['draft_plan_operation_id'])
    ):
        return None
    history = connection.execute(
        """SELECT * FROM code_operations WHERE task_id IS NULL AND testing_task_id=?
           AND id<>? ORDER BY id""",
        (task['id'], stop['id']),
    ).fetchall()
    calls = []
    for operation in history:
        if operation['operation_type'] != 'DRAFT_PLAN':
            if operation['operation_type'] not in (
                'ATTACH_ASSETS',
                'INCREASE_TEST_BUDGET',
                'RECONCILE',
            ) or operation['status'] not in ('SUCCEEDED', 'FAILED', 'CANCELLED'):
                return None
            continue
        try:
            draft = read_original_draft(connection, operation)
        except StorageUnavailable:
            return None
        if (
            operation['control_generation'] > fixed['prior_generation']
            or operation['status'] not in ('SUCCEEDED', 'FAILED', 'UNKNOWN', 'CANCELLED')
            or draft.use['ended_at'] is None
            or draft.use['transport_status'] not in ('NOT_SENT', 'COMPLETE', 'UNKNOWN')
            or draft.reservation['status'] == 'RESERVED'
        ):
            return None
        calls.append(
            {
                'operation_id': operation['id'],
                'llm_use_id': draft.use['id'],
                'transport_status': draft.use['transport_status'],
                'ended_at': draft.use['ended_at'],
            }
        )
    if (
        not calls
        or calls[-1]['operation_id'] != task['draft_plan_operation_id']
        or connection.execute(
            'SELECT count(*) FROM llm_uses WHERE testing_task_id=?', (task['id'],)
        ).fetchone()[0]
        != len(calls)
        or connection.execute(
            'SELECT 1 FROM code_commands WHERE testing_task_id=?', (task['id'],)
        ).fetchone()
        is not None
    ):
        return None
    return {
        'policy': DRAFT_STOP_POLICY,
        'testing_task_id': task['id'],
        'operation_id': stop['id'],
        'closed_generation': task['control_generation'],
        'prior_generation': fixed['prior_generation'],
        'local_call_closures': calls,
    }


def cancel_closed_drafts(connection, proof, at):
    for call in proof['local_call_closures']:
        original = call['operation_id']
        updated = connection.execute(
            """UPDATE code_operations SET status='CANCELLED',failure_code=NULL,ended_at=?
               WHERE id=? AND status='UNKNOWN' AND ended_at IS NULL""",
            (at, original),
        )
        if updated.rowcount:
            connection.execute(
                """UPDATE code_operation_steps SET status='CANCELLED',started_at=COALESCE(started_at,?),
                   ended_at=?,last_observed_at=? WHERE operation_id=? AND step_no IN (?,?)
                   AND status IN ('UNKNOWN','PENDING')""",
                (at, at, at, original, CALL_STEP, SAVE_STEP),
            )
        connection.execute(
            """UPDATE code_waiting_items SET status='RESOLVED',resolved_at=?,resolution_ref=?
               WHERE testing_task_id=? AND kind='MODEL_RESULT' AND source_kind='LLM_USE'
               AND source_id=? AND status='OPEN'""",
            (
                at,
                canonical_input({'termination_operation_id': proof['operation_id']}),
                proof['testing_task_id'],
                call['llm_use_id'],
            ),
        )
