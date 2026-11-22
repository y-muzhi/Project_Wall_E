"""Adopt one verified backup and include it with trusted recovery points."""

from backend.app.infrastructure.environment_files import (
    MAX_REVISION,
    canonical,
    digest,
    exact,
    require,
)
from backend.app.infrastructure.environment_installation import (
    sha_value,
    uuid_value,
    version_record,
)

from .attachment_observation import now
from .backup_capture import CAPTURED, EXECUTIONS, backup_record, checked_capture_receipt
from .backup_completion import COMPLETE, COMPLETE_STATUS
from .backup_operations import ACTION, STEP
from .lifecycle_operations import authorized, expected_versions
from .operation_contract import DENIED, RESOURCE, UNAVAILABLE, VERSION, installed_record
from .operation_store import decoded, stored
from .recovery_catalog import POINT_FIELDS, read_backup_index, time_at

POINT_COLUMNS = (
    *POINT_FIELDS[:-2],
    'source_environment_id',
    'verification_status',
    'local_verification',
    'local_snapshot_retrieval',
)
RESULT_FIELDS = ('environment_id', 'observed_at', 'point')
ATTEMPT = {
    'ACCEPTED': 'CREATING',
    'RUNNING': 'CREATING',
    'UNKNOWN': 'PENDING_RECONCILIATION',
    'FAILED': 'FAILED',
    'SUCCEEDED': 'SUCCEEDED',
}


def normalized_point(value, identifier, ceiling):
    point = exact(value, POINT_COLUMNS, RESOURCE)
    local = exact(
        point['local_verification'], ('verification_id', 'verified_at', 'verified_scopes'), RESOURCE
    )
    require(
        all(
            uuid_value(point[key])
            for key in ('backup_id', 'source_data_generation', 'source_deployment_id')
        )
        and all(
            sha_value(point[key])
            for key in (
                'backup_manifest_sha256',
                'logical_content_sha256',
                'program_sha256',
                'configuration_sha256',
            )
        )
        and type(point['source_control_revision']) is int
        and 1 <= point['source_control_revision'] < MAX_REVISION
        and type(point['database_bytes']) is int
        and 0 < point['database_bytes'] <= 1024**4
        and point['source_environment_id'] == identifier
        and point['count_audit_state'] in ('ABSENT', 'EMPTY', 'FILES')
        and point['verification_status'] == 'LOCAL_VERIFIED'
        and point['local_snapshot_retrieval'] is None
        and uuid_value(local['verification_id'])
        and time_at(local['verified_at'], ceiling)
        and time_at(point['cutoff_at'], local['verified_at'])
        and local['verified_scopes'] == ['DOCUMENT_CONTENT', 'DOCUMENT_HISTORY'],
        RESOURCE,
    )
    return point


def original_backup_result(catalog, operation, grant):
    directory = catalog.directory / EXECUTIONS / operation['operation_id']
    try:
        complete = installed_record(directory / COMPLETE)
    except FileNotFoundError:
        return None
    captured = checked_capture_receipt(installed_record(directory / CAPTURED), grant)
    version_record(
        complete,
        (
            'status',
            *catalog.scope,
            'operation_id',
            'grant_sha256',
            'capture_sha256',
            'result_policy_sha256',
            'observed_at',
            'point',
        ),
        RESOURCE,
    )
    require(
        complete['status'] == COMPLETE_STATUS
        and all(complete[key] == value for key, value in catalog.scope.items())
        and complete['operation_id'] == grant['operation_id'] == operation['operation_id']
        and complete['grant_sha256'] == digest(canonical(grant))
        and complete['capture_sha256'] == digest(canonical(captured))
        and sha_value(complete['result_policy_sha256'])
        and time_at(complete['observed_at'], now()),
        RESOURCE,
    )
    point = normalized_point(
        complete['point'], operation['environment_id'], complete['observed_at']
    )
    require(
        point['backup_id'] == captured['backup_id']
        and point['source_data_generation'] == captured['data_generation']
        and point['source_deployment_id'] == captured['deployment_id']
        and point['source_control_revision'] == captured['control_revision']
        and point['cutoff_at'] == captured['cutoff_at']
        and point['database_bytes'] == captured['database_bytes']
        and point['program_sha256'] == grant['source']['program_sha256']
        and point['configuration_sha256'] == grant['source']['configuration_sha256'],
        RESOURCE,
    )
    return {
        'environment_id': operation['environment_id'],
        'observed_at': complete['observed_at'],
        'point': point,
    }


def reconcile_backup(connection, catalog, principal, operation):
    require(principal.role == 'MANAGER', DENIED)
    if operation['status'] == 'SUCCEEDED':
        return
    environment = authorized(connection, principal, operation['environment_id'])
    expected_versions(environment, decoded(operation['intent_json']))
    require(
        operation['status'] in ('ACCEPTED', 'RUNNING') and not operation['cancel_requested'],
        UNAVAILABLE,
    )
    if operation['status'] == 'ACCEPTED':
        return
    _, step = backup_record(connection, catalog, operation['operation_id'])
    require(
        step['status'] == 'DISPATCHING' and step['external_identity_json'] is not None, RESOURCE
    )
    grant = decoded(step['external_identity_json'])['capture']
    result = original_backup_result(catalog, operation, grant)
    if result is None:
        return
    require(operation['revision'] < MAX_REVISION, VERSION)
    advanced = connection.execute(
        "UPDATE management_operations SET status='SUCCEEDED',revision=revision+1 "
        "WHERE operation_id=? AND revision=? AND status='RUNNING'",
        (operation['operation_id'], operation['revision']),
    )
    recorded = connection.execute(
        "UPDATE management_steps SET status='SUCCEEDED',result_json=? "
        "WHERE operation_id=? AND ordinal=1 AND step_kind=? AND status='DISPATCHING'",
        (stored(result), operation['operation_id'], STEP),
    )
    require(advanced.rowcount == recorded.rowcount == 1, VERSION)


def merge_points(previous, measured):
    if previous is None:
        return measured
    require(all(previous[key] == measured[key] for key in POINT_FIELDS[:-2]), RESOURCE)
    established = previous['local_verification']
    newer = measured['local_verification']
    local = (
        newer
        if established is None or newer['verified_at'] > established['verified_at']
        else established
    )
    return {**previous, 'local_verification': local, 'verification_status': 'LOCAL_VERIFIED'}


def managed_backup_history(connection, catalog, identifier, as_of):
    summary, original = read_backup_index(
        catalog, identifier, catalog.backup_indexes.get(identifier), as_of
    )
    points = {point['backup_id']: point for point in original}
    observed = summary['indexed_at']
    rows = connection.execute(
        'SELECT op.operation_id, op.status, op.created_at, step.result_json FROM management_operations AS op '
        'JOIN management_steps AS step ON op.operation_id=step.operation_id AND step.ordinal=1 '
        'WHERE op.environment_id=? AND op.registry_generation=? AND op.action=? AND step.step_kind=? '
        "AND op.status!='CANCELLED' ORDER BY op.created_at DESC,op.operation_id DESC",
        (identifier, catalog.scope['registry_generation'], ACTION, STEP),
    )
    for row in rows:
        measured = row['created_at']
        require(row['status'] in ATTEMPT and time_at(measured, as_of), RESOURCE)
        if row['status'] == 'SUCCEEDED':
            result = exact(decoded(row['result_json']), RESULT_FIELDS, RESOURCE)
            measured = result['observed_at']
            require(result['environment_id'] == identifier and time_at(measured, as_of), RESOURCE)
            point = normalized_point(result['point'], identifier, measured)
            points[point['backup_id']] = merge_points(points.get(point['backup_id']), point)
            observed = max(measured, observed or measured)
        previous = summary['latest_attempt']
        if previous is None or measured > previous['observed_at']:
            summary['latest_attempt'] = {
                'operation_id': row['operation_id'],
                'status': ATTEMPT[row['status']],
                'observed_at': measured,
                'reason_code': None,
            }
    ordered = sorted(
        points.values(), key=lambda point: (point['cutoff_at'], point['backup_id']), reverse=True
    )
    latest = next((point for point in ordered if point['local_verification'] is not None), None)
    if latest is not None:
        summary['latest_local'] = {
            'backup_id': latest['backup_id'],
            'cutoff_at': latest['cutoff_at'],
            'verified_at': latest['local_verification']['verified_at'],
        }
    summary['indexed_at'] = observed
    return summary, ordered
