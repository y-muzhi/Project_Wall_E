"""Immutable launch provenance and subsequently verified WALL-E control pairs."""

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.shared.validation import strict_json_object

from .execution_profile_content import FIELDS

CONTROL_LIMITS = frozenset(
    (
        'max_model_requests',
        'max_output_tokens',
        'max_consecutive_failures',
        'query_timeout_seconds',
        'send_timeout_seconds',
        'queue_wait_seconds',
    )
)


FIXED_CONTENT_LIMITS = frozenset(
    (
        'max_file_bytes',
        'max_snapshot_bytes',
        'max_snapshot_files',
        'max_capture_entries',
        'max_capture_seconds',
        'max_manifest_bytes',
        'max_git_seconds',
        'max_git_output_bytes',
    )
)


def fixed_content_changed(before, after):
    return before['capture_rules'] != after['capture_rules'] or any(
        before['limits'][key] != after['limits'][key] for key in FIXED_CONTENT_LIMITS
    )


CHECK_LIMITS = frozenset(('max_check_output_bytes',))
LIVE_LIMITS = CONTROL_LIMITS | CHECK_LIMITS


def supported_live_changes(before, after, previous_scope, next_scope):
    if any(
        before[key] != after[key] for key in FIELDS if key not in ('limits', 'check_set_version_id')
    ):
        return False
    if any(
        before['limits'][key] != after['limits'][key]
        for key in before['limits']
        if key not in LIVE_LIMITS
    ):
        return False
    if any(
        previous_scope[key] != next_scope[key]
        for key in previous_scope
        if key not in ('limits', 'model_profile_refs', 'allow_local_delivery', 'read_roots')
    ):
        return False
    if previous_scope['read_roots'] != next_scope['read_roots']:
        from .task_configuration_native import managed_read_change_supported

        if not managed_read_change_supported(previous_scope, next_scope):
            return False
    return all(
        previous_scope['limits'][key] == next_scope['limits'][key]
        for key in previous_scope['limits']
        if key not in LIVE_LIMITS
    )


def effective_control_application(connection, task, *, instance_id, launch_profile_id):
    """Every adoption must extend the original launch; a task reference is insufficient."""
    from .task_configuration_live_records import live_configuration_records

    rows = connection.execute(
        """SELECT o.* FROM code_operations o JOIN code_configuration_applications a
           ON a.operation_id=o.id AND a.task_id=o.task_id
           WHERE o.task_id=? AND o.operation_type='APPLY_CONFIGURATION'
             AND o.session_id IS NOT NULL AND o.status='SUCCEEDED' AND a.status='APPLIED'
           ORDER BY o.id""",
        (task['id'],),
    ).fetchall()
    profile = launch_profile_id
    initial = connection.execute(
        """SELECT o.status,s.external_identity FROM code_operations o JOIN code_operation_steps s
           ON s.operation_id=o.id AND s.step_no=5 AND s.status='SUCCEEDED'
           WHERE o.task_id=? AND o.operation_type='START' AND o.status IN ('RUNNING','SUCCEEDED')""",
        (task['id'],),
    ).fetchall()
    if len(initial) != 1 or (rows and initial[0]['status'] != 'SUCCEEDED'):
        raise StorageUnavailable('Original configuration launch is not confirmed')
    origin = strict_json_object(initial[0]['external_identity'])
    if origin['instance_id'] != instance_id or origin['profile_id'] != launch_profile_id:
        raise StorageUnavailable('Original configuration launch pair differs')
    grant_id = origin['authorization_id']
    current = None
    for operation in rows:
        _, application, _, source = live_configuration_records(connection, operation)
        if (
            source['instance_id'] != instance_id
            or source['launch_profile_id'] != launch_profile_id
            or application['old_profile_version_id'] != profile
            or source['old_authorization_id'] != grant_id
            or application['applied_at'] is None
        ):
            raise StorageUnavailable('Verified control configuration lineage differs')
        profile = application['new_profile_version_id']
        grant_id = application['authorization_id']
        current = application
    if profile != task['execution_profile_version_id'] or grant_id != task['authorization_id']:
        raise StorageUnavailable('Current control pair has no verified original application')
    if current is not None:
        grant = connection.execute(
            'SELECT * FROM code_authorizations WHERE id=? AND task_id=?',
            (grant_id, task['id']),
        ).fetchone()
        if (
            grant is None
            or grant['status'] != 'EFFECTIVE'
            or grant['profile_version_id'] != profile
        ):
            raise StorageUnavailable('Current control authorization is not effective')
        observed = strict_json_object(current['effective_evidence'])
        if observed['instance_id'] != instance_id or observed['result'] != 'VERIFIED':
            raise StorageUnavailable('Current control observation differs')
    return current
