"""Read only proven closed original Coding candidate and check Jobs."""

from backend.app.infrastructure.git_content_command import CONTENT_COMMAND_REF
from backend.app.infrastructure.guard_control_git_input import (
    CONFIG_COMMAND_REF,
    DELIVERY_ANCESTOR_COMMAND_REF,
    DELIVERY_OBJECT_COMMAND_REF,
    DELIVERY_REF_COMMAND_REF,
    DELIVERY_TARGET_COMMAND_REF,
    OBJECT_BATCH_COMMAND_REF,
)
from backend.app.shared.validation import strict_json_object


def read_closed_candidate_job_ids(connection, task_id):
    rows = connection.execute(
        """SELECT c.*,o.operation_type,o.status AS operation_status,o.control_generation,o.session_id AS original_session
           FROM code_commands c JOIN code_operations o ON o.id=c.operation_id AND o.task_id=c.task_id
           WHERE c.task_id=? ORDER BY c.id""",
        (task_id,),
    ).fetchall()
    if (
        len(rows)
        != connection.execute(
            'SELECT count(*) FROM code_commands WHERE task_id=?', (task_id,)
        ).fetchone()[0]
    ):
        return None
    for row in rows:
        if (
            row['operation_type']
            not in ('CAPTURE_AND_CHECK', 'VERIFY_CANDIDATE', 'PREPARE_DELIVERY', 'DELIVER')
            or row['session_id'] != row['original_session']
            or row['ended_at'] is None
        ):
            return None
        operation = row['operation_type']
        command = row['command_ref']
        closed_content = command == CONTENT_COMMAND_REF and (
            operation == 'CAPTURE_AND_CHECK'
            or (
                operation == 'PREPARE_DELIVERY'
                and row['operation_status'] in ('SUCCEEDED', 'FAILED', 'CANCELLED')
            )
        )
        delivery_git = operation == 'DELIVER' and command in (
            CONFIG_COMMAND_REF,
            OBJECT_BATCH_COMMAND_REF,
            DELIVERY_ANCESTOR_COMMAND_REF,
            DELIVERY_OBJECT_COMMAND_REF,
            DELIVERY_REF_COMMAND_REF,
            DELIVERY_TARGET_COMMAND_REF,
        )
        if row['purpose'] == 'CONTROL_GIT' and (closed_content or delivery_git):
            kind = 'CONTROL_GIT'
        elif row['purpose'] == 'CHECK' and _closed_project_check(connection, row):
            kind = 'TASK'
        else:
            return None
        if (
            row['status'] == 'CANCELLED'
            and (kind == 'TASK' or row['operation_type'] == 'DELIVER')
            and row['process_identity'] is None
        ):
            if row['runtime_binding'] is not None or row['exit_code'] is not None:
                return None
            continue
        if (
            row['status'] not in ('SUCCEEDED', 'FAILED', 'CANCELLED')
            or row['started_at'] is None
            or row['exit_code'] is None
            or row['process_identity'] is None
            or row['runtime_binding'] is None
        ):
            return None
        binding = strict_json_object(row['runtime_binding'])
        if (
            binding.get('run_kind') != kind
            or not binding.get('job_refs')
            or not binding.get('guard_run_ref')
        ):
            return None
    return tuple(row['id'] for row in rows)


def _closed_project_check(connection, command):
    return (
        connection.execute(
            """SELECT 1 FROM code_verification_items i JOIN code_verifications v ON v.id=i.verification_id
           WHERE i.id=? AND i.command_execution_id=? AND i.evidence_kind='PROCESS_EXIT'
           AND v.task_id=? AND v.operation_id=? AND v.owner_kind='CODING'
           AND v.stop_status='VERIFIED' AND v.cleanup_status='VERIFIED'""",
            (
                command['verification_item_id'],
                command['id'],
                command['task_id'],
                command['operation_id'],
            ),
        ).fetchone()
        is not None
    )
