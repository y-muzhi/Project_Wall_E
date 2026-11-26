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
from .backup_completion import (
    COMPLETE,
    COMPLETE_STATUS,
    LOCAL_STAGE,
    LOCAL_STATUS,
    OFFHOST_COMPLETE,
)
from .backup_operations import ACTION, STEP
from .lifecycle_operations import authorized, expected_versions
from .operation_contract import DENIED, RESOURCE, UNAVAILABLE, VERSION, installed_record
from .operation_store import decoded, stored
from .recovery_catalog import POINT_FIELDS, read_backup_index, time_at
from .recovery_offhost import offhost_freshness

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


def normalized_point(value, identifier, ceiling, *, offhost=False):
    fields = (*POINT_COLUMNS, 'offhost_verification') if offhost else POINT_COLUMNS
    point = exact(value, fields, RESOURCE)
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
        and point['verification_status'] == ('OFFHOST_VERIFIED' if offhost else 'LOCAL_VERIFIED')
        and point['local_snapshot_retrieval'] is None
        and uuid_value(local['verification_id'])
        and time_at(local['verified_at'], ceiling)
        and time_at(point['cutoff_at'], local['verified_at'])
        and local['verified_scopes'] == ['DOCUMENT_CONTENT', 'DOCUMENT_HISTORY'],
        RESOURCE,
    )
    if offhost:
        witness = exact(
            point['offhost_verification'],
            ('verification_id', 'snapshot_id', 'retrieved_at'),
            RESOURCE,
        )
        require(
            uuid_value(witness['verification_id'])
            and sha_value(witness['snapshot_id'])
            and time_at(witness['retrieved_at'], ceiling)
            and witness['retrieved_at'] >= point['cutoff_at'],
            RESOURCE,
        )
    return point


def checked_point_source(record, catalog, operation, grant, captured, *, offhost=False):
    observed = record['observed_at']
    require(
        all(record[key] == value for key, value in catalog.scope.items())
        and record['operation_id'] == grant['operation_id'] == operation['operation_id']
        and record['grant_sha256'] == digest(canonical(grant))
        and record['capture_sha256'] == digest(canonical(captured))
        and time_at(observed, now()),
        RESOURCE,
    )
    point = normalized_point(
        record['point'], operation['environment_id'], observed, offhost=offhost
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
    return point


def original_local_stage(catalog, operation, grant):
    if 'offhost_authority' not in grant:
        return None
    directory = catalog.directory / EXECUTIONS / operation['operation_id']
    try:
        staged = installed_record(directory / LOCAL_STAGE)
    except FileNotFoundError:
        return None
    version_record(
        staged,
        (
            'status',
            *catalog.scope,
            'operation_id',
            'grant_sha256',
            'capture_sha256',
            'local_inputs_sha256',
            'local_policy_sha256',
            'observed_at',
            'point',
        ),
        RESOURCE,
    )
    require(
        staged['status'] == LOCAL_STATUS
        and sha_value(staged['local_inputs_sha256'])
        and sha_value(staged['local_policy_sha256']),
        RESOURCE,
    )
    captured = checked_capture_receipt(installed_record(directory / CAPTURED), grant)
    checked_point_source(staged, catalog, operation, grant, captured)
    return staged


def original_backup_result(catalog, operation, grant):
    directory = catalog.directory / EXECUTIONS / operation['operation_id']
    try:
        complete = installed_record(directory / COMPLETE)
    except FileNotFoundError:
        return None
    captured = checked_capture_receipt(installed_record(directory / CAPTURED), grant)
    authority = grant.get('offhost_authority')
    extras = ('offhost_verification_sha256',) if authority is not None else ()
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
            *extras,
        ),
        RESOURCE,
    )
    expected = COMPLETE_STATUS if authority is None else OFFHOST_COMPLETE
    require(
        complete['status'] == expected
        and sha_value(complete['result_policy_sha256'])
        and (authority is None or sha_value(complete['offhost_verification_sha256'])),
        RESOURCE,
    )
    point = checked_point_source(
        complete, catalog, operation, grant, captured, offhost=authority is not None
    )
    result = {
        'environment_id': operation['environment_id'],
        'observed_at': complete['observed_at'],
        'point': point,
    }
    if authority is not None:
        staged = original_local_stage(catalog, operation, grant)
        original = {key: point[key] for key in POINT_COLUMNS}
        original['verification_status'] = 'LOCAL_VERIFIED'
        require(
            staged is not None
            and staged['point'] == original
            and staged['observed_at'] <= complete['observed_at'],
            RESOURCE,
        )
        result['offhost_observation_max_age_seconds'] = authority['observation_max_age_seconds']
    return result


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
    offhost = previous.get('offhost_verification')
    new_offhost = measured.get('offhost_verification')
    if new_offhost is not None and (
        offhost is None or new_offhost['retrieved_at'] >= offhost['retrieved_at']
    ):
        offhost = new_offhost
    point = {**previous, 'local_verification': local, 'verification_status': 'LOCAL_VERIFIED'}
    if offhost is not None:
        point.update(verification_status='OFFHOST_VERIFIED', offhost_verification=offhost)
    return point


def managed_backup_history(connection, catalog, identifier, as_of):
    summary, original = read_backup_index(
        catalog, identifier, catalog.backup_indexes.get(identifier), as_of
    )
    points = {point['backup_id']: point for point in original}
    observed = summary['indexed_at']
    offhost_ages = {}
    rows = connection.execute(
        'SELECT op.operation_id, op.environment_id, op.status, op.created_at, step.result_json, '
        'step.external_identity_json FROM management_operations AS op '
        'JOIN management_steps AS step ON op.operation_id=step.operation_id AND step.ordinal=1 '
        'WHERE op.environment_id=? AND op.registry_generation=? AND op.action=? AND step.step_kind=? '
        "AND op.status!='CANCELLED' ORDER BY op.created_at DESC,op.operation_id DESC",
        (identifier, catalog.scope['registry_generation'], ACTION, STEP),
    )
    for row in rows:
        measured = row['created_at']
        require(row['status'] in ATTEMPT and time_at(measured, as_of), RESOURCE)
        reason = None
        if row['status'] == 'SUCCEEDED':
            result = decoded(row['result_json'])
            age = result.get('offhost_observation_max_age_seconds')
            fields = (
                (*RESULT_FIELDS, 'offhost_observation_max_age_seconds')
                if age is not None
                else RESULT_FIELDS
            )
            exact(result, fields, RESOURCE)
            measured = result['observed_at']
            require(
                result['environment_id'] == identifier
                and time_at(measured, as_of)
                and (age is None or type(age) is int and 1 <= age <= 365 * 86400),
                RESOURCE,
            )
            point = normalized_point(result['point'], identifier, measured, offhost=age is not None)
            backup = point['backup_id']
            combined = merge_points(points.get(backup), point)
            points[backup] = combined
            if (
                age is not None
                and combined['offhost_verification'] == point['offhost_verification']
            ):
                offhost_ages[backup] = age
            observed = max(measured, observed or measured)
        elif row['status'] == 'RUNNING' and row['external_identity_json'] is not None:
            grant = decoded(row['external_identity_json'])['capture']
            staged = original_local_stage(catalog, row, grant)
            if staged is not None:
                measured = staged['observed_at']
                require(time_at(measured, as_of), RESOURCE)
                point = staged['point']
                backup = point['backup_id']
                points[backup] = merge_points(points.get(backup), point)
                observed = max(measured, observed or measured)
                reason = 'OFFHOST_VERIFICATION_REQUIRED'
        previous = summary['latest_attempt']
        if previous is None or measured > previous['observed_at']:
            summary['latest_attempt'] = {
                'operation_id': row['operation_id'],
                'status': ATTEMPT[row['status']],
                'observed_at': measured,
                'reason_code': reason,
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
    latest_offhost = next((point for point in ordered if 'offhost_verification' in point), None)
    if latest_offhost is not None and latest_offhost['backup_id'] in offhost_ages:
        summary['latest_offhost'], summary['rpo_status'] = offhost_freshness(
            latest_offhost,
            as_of,
            summary['rpo_target_seconds'],
            offhost_ages[latest_offhost['backup_id']],
        )
    summary['indexed_at'] = observed
    return summary, ordered
