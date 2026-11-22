"""Project protected restore-point metadata without opening business data or archives."""

import re

from backend.app.infrastructure.environment_files import MAX_REVISION, exact, require
from backend.app.infrastructure.environment_installation import (
    sha_value,
    uuid_value,
    version_record,
)

from .operation_contract import RESOURCE, installed_record
from .recovery_evidence import parse_local_recovery
from .registry import is_timestamp

POINT_FIELDS = (
    'backup_id',
    'source_data_generation',
    'source_deployment_id',
    'source_control_revision',
    'cutoff_at',
    'backup_manifest_sha256',
    'database_bytes',
    'logical_content_sha256',
    'count_audit_state',
    'program_sha256',
    'configuration_sha256',
    'local_verification_sha256',
    'local_retrieval_sha256',
)
ATTEMPT_STATES = ('CREATING', 'SUCCEEDED', 'FAILED', 'UNVERIFIED', 'PENDING_RECONCILIATION')
REASON = re.compile(r'[A-Z][A-Z0-9_]{1,79}')


def time_at(value, ceiling):
    return is_timestamp(value) and value <= ceiling


def policy_target(value):
    if value is None:
        return {'backup_policy_ref': None, 'rpo_target_seconds': None, 'rto_target_seconds': None}
    exact(value, ('backup_policy_ref', 'rpo_target_seconds', 'rto_target_seconds'), RESOURCE)
    require(
        uuid_value(value['backup_policy_ref'])
        and all(
            type(value[key]) is int and 1 <= value[key] <= 365 * 86400
            for key in ('rpo_target_seconds', 'rto_target_seconds')
        ),
        RESOURCE,
    )
    return value


def attempt_view(value, ceiling):
    if value is None:
        return None
    exact(value, ('operation_id', 'status', 'observed_at', 'reason_code'), RESOURCE)
    reason = value['reason_code']
    require(
        uuid_value(value['operation_id'])
        and value['status'] in ATTEMPT_STATES
        and time_at(value['observed_at'], ceiling)
        and (reason is None or (type(reason) is str and REASON.fullmatch(reason) is not None)),
        RESOURCE,
    )
    return value


def local_view(directory, point, environment, ceiling):
    pin = point['local_verification_sha256']
    if pin is None:
        return None
    evidence = directory / f'{point["backup_id"]}.local.v1.json'
    return local_metadata(
        installed_record(evidence, pin, code=RESOURCE), point, environment, ceiling
    )


def local_metadata(proof, point, environment, ceiling):
    proof = parse_local_recovery(proof, RESOURCE)
    require(
        proof['backup_id'] == point['backup_id']
        and proof['environment_id'] == environment
        and proof['data_generation'] != point['source_data_generation']
        and proof['deployment_id'] != point['source_deployment_id']
        and proof['backup_manifest_sha256'] == point['backup_manifest_sha256']
        and proof['logical_content_sha256'] == point['logical_content_sha256']
        and point['cutoff_at'] <= proof['verified_at'] <= ceiling,
        RESOURCE,
    )
    return {
        'verification_id': proof['verification_id'],
        'verified_at': proof['verified_at'],
        'verified_scopes': proof['verified_scopes'],
    }


def retrieval_view(directory, point, ceiling):
    pin = point['local_retrieval_sha256']
    if pin is None:
        return None
    evidence = directory / f'{point["backup_id"]}.retrieval.v1.json'
    proof = installed_record(evidence, pin, code=RESOURCE)
    version_record(
        proof,
        (
            'status',
            'operation_id',
            'retrieved_at',
            'backup_id',
            'backup_manifest_sha256',
            'snapshot_id',
            'repository_id',
            'restic_sha256',
            'restic_version',
            'snapshot_bytes',
            'snapshot_entries',
        ),
        RESOURCE,
    )
    require(
        proof['status'] == 'LOCAL_SNAPSHOT_RETRIEVED'
        and uuid_value(proof['operation_id'])
        and proof['backup_id'] == point['backup_id']
        and proof['backup_manifest_sha256'] == point['backup_manifest_sha256']
        and all(sha_value(proof[key]) for key in ('snapshot_id', 'repository_id', 'restic_sha256'))
        and proof['restic_version'] == '0.19.1'
        and type(proof['snapshot_bytes']) is int
        and proof['snapshot_bytes'] >= point['database_bytes']
        and type(proof['snapshot_entries']) is int
        and 0 < proof['snapshot_entries'] <= 8192
        and time_at(proof['retrieved_at'], ceiling)
        and proof['retrieved_at'] >= point['cutoff_at'],
        RESOURCE,
    )
    return {'snapshot_id': proof['snapshot_id'], 'retrieved_at': proof['retrieved_at']}


def point_view(directory, environment, raw, ceiling):
    point = exact(raw, POINT_FIELDS, RESOURCE)
    require(
        all(
            uuid_value(point[field])
            for field in ('backup_id', 'source_data_generation', 'source_deployment_id')
        )
        and all(
            sha_value(point[field])
            for field in (
                'backup_manifest_sha256',
                'logical_content_sha256',
                'program_sha256',
                'configuration_sha256',
            )
        )
        and all(
            point[field] is None or sha_value(point[field])
            for field in ('local_verification_sha256', 'local_retrieval_sha256')
        )
        and time_at(point['cutoff_at'], ceiling)
        and type(point['source_control_revision']) is int
        and 1 <= point['source_control_revision'] < MAX_REVISION
        and type(point['database_bytes']) is int
        and 0 < point['database_bytes'] <= 1024**4
        and point['count_audit_state'] in ('ABSENT', 'EMPTY', 'FILES'),
        RESOURCE,
    )
    local = local_view(directory, point, environment, ceiling)
    retrieval = retrieval_view(directory, point, ceiling)
    return {
        **{field: point[field] for field in POINT_FIELDS[:-2]},
        'source_environment_id': environment,
        'verification_status': 'LOCAL_VERIFIED' if local is not None else 'UNVERIFIED',
        'local_verification': local,
        'local_snapshot_retrieval': retrieval,
    }


def read_backup_index(catalog, environment, reference, as_of):
    target = policy_target(None)
    record = {
        'as_of': as_of,
        'indexed_at': None,
        **target,
        'latest_attempt': None,
        'latest_local': None,
        'latest_offhost': None,
        'rpo_status': 'UNVERIFIED',
    }
    if reference is None:
        return record, []
    path, pin = reference
    raw = installed_record(path, pin, code=RESOURCE)
    version_record(
        raw,
        (
            *catalog.scope,
            'environment_id',
            'indexed_at',
            'backup_policy',
            'latest_attempt',
            'points',
        ),
        RESOURCE,
    )
    require(
        all(raw[key] == value for key, value in catalog.scope.items())
        and raw['environment_id'] == environment
        and time_at(raw['indexed_at'], as_of)
        and type(raw['points']) is list
        and len(raw['points']) <= 128,
        RESOURCE,
    )
    ceiling = raw['indexed_at']
    record.update(
        policy_target(raw['backup_policy']),
        indexed_at=ceiling,
        latest_attempt=attempt_view(raw['latest_attempt'], ceiling),
    )
    evidence = path.parent / 'backup-evidence'
    points = [point_view(evidence, environment, value, ceiling) for value in raw['points']]
    require(len({point['backup_id'] for point in points}) == len(points), RESOURCE)
    points.sort(key=lambda point: (point['cutoff_at'], point['backup_id']), reverse=True)
    latest = next((point for point in points if point['local_verification'] is not None), None)
    if latest is not None:
        record['latest_local'] = {
            'backup_id': latest['backup_id'],
            'cutoff_at': latest['cutoff_at'],
            'verified_at': latest['local_verification']['verified_at'],
        }
    return record, points
