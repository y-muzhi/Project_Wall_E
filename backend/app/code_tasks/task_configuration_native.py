"""Retain a managed read-root change inside the immutable original launch boundary."""

import hashlib

from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.managed_read_scopes import (
    BASIS,
    RESOURCE_SHA256,
    WORKSPACE,
    load_managed_read_scopes,
)

from .task_start_authorization import original_start_authorization


class NativeReadAuthorizationError(ValueError):
    pass


def managed_read_change_supported(previous_scope, next_scope):
    for scope in (previous_scope, next_scope):
        if type(scope) is not dict:
            return False
        roots = scope.get('read_roots')
        if (
            type(roots) is not list
            or any(type(ref) is not str for ref in roots)
            or len(set(roots)) != len(roots)
            or WORKSPACE not in roots
            or not set(roots).issubset({WORKSPACE, BASIS})
            or scope.get('write_workspace_only') is not True
            or scope.get('allowed_command_ids') != []
            or scope.get('network_targets') != []
        ):
            return False
    return previous_scope['read_roots'] != next_scope['read_roots']


def compile_native_read_authorization(connection, task_id, previous_scope, next_scope):
    load_managed_read_scopes()
    if not managed_read_change_supported(previous_scope, next_scope):
        raise NativeReadAuthorizationError('NATIVE_READ_CHANGE_UNSUPPORTED')
    origin = original_start_authorization(connection, task_id)
    original = origin['scope']
    roots = set(original['read_roots'])
    if (
        WORKSPACE not in roots
        or not roots.issubset({WORKSPACE, BASIS})
        or original['allowed_command_ids']
        or original['network_targets']
        or not set(previous_scope['read_roots']).issubset(roots)
        or not set(next_scope['read_roots']).issubset(roots)
    ):
        raise NativeReadAuthorizationError('NATIVE_READ_CHANGE_EXCEEDS_LAUNCH')
    return {
        'protocol_version': 'READ20-MANAGED-1',
        'resource_sha256': RESOURCE_SHA256,
        'launch_authorization_id': origin['id'],
        'launch_read_roots': sorted(roots),
        'old_read_roots': sorted(previous_scope['read_roots']),
        'new_read_roots': sorted(next_scope['read_roots']),
        'target_scope_sha256': hashlib.sha256(canonical_input(next_scope).encode()).hexdigest(),
    }


def adopted_native_permission_scopes(connection, scope, creation_scope):
    from dataclasses import asdict

    from backend.app.infrastructure.database import StorageUnavailable
    from backend.app.infrastructure.runtime_launch_journal import LaunchScope
    from backend.app.shared.validation import strict_json_object

    from .task_configuration_effective import effective_control_application

    rows = connection.execute(
        """SELECT o.id,s.external_identity FROM code_operations o
           JOIN code_configuration_applications a ON a.operation_id=o.id AND a.task_id=o.task_id
           JOIN code_operation_steps s ON s.operation_id=o.id AND s.step_no=3
           WHERE o.task_id=? AND o.session_id=? AND o.operation_type='APPLY_CONFIGURATION'
             AND o.status='SUCCEEDED' AND a.status='APPLIED'
             AND json_extract(s.external_identity,'$.mode')='NATIVE_PERMISSION'
           ORDER BY o.id""",
        (scope.task_id, scope.session_id),
    ).fetchall()
    if not rows:
        return ()
    task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (scope.task_id,)).fetchone()
    if task is None:
        raise StorageUnavailable('Original native permission task is missing')
    effective_control_application(
        connection, task, instance_id=scope.instance_id, launch_profile_id=scope.profile_id
    )
    result = []
    prefix = []
    for row in rows:
        identity = strict_json_object(row['external_identity'])
        if (
            identity['session_scope'] != asdict(creation_scope)
            or identity['previous_applications'] != prefix
        ):
            raise StorageUnavailable('Adopted native permission source chain differs')
        application = LaunchScope(creation_scope.controller_ref, row['id'], 3, identity['nonce'])
        result.append(application)
        prefix.append(asdict(application))
    return tuple(result)
