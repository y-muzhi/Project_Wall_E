"""Read an approved archived business command without opening the active database."""

from backend.app.infrastructure.environment_files import (
    MAX_RECORD_SIZE,
    MAX_REVISION,
    EnvironmentFailure,
    decode,
    digest,
    exact,
    read_protected,
    require,
)
from backend.app.infrastructure.environment_installation import (
    sha_value,
    uuid_value,
    version_record,
)
from backend.app.infrastructure.environment_result_archive import (
    BUCKET,
    parse_shard,
    scope_key,
    shard_name,
)

from .operation_contract import DENIED, INVALID, MISSING, RESOURCE
from .operation_store import environment_row, may_read_environment

INDEX = 'prior-command-index.v1.json'
ENVELOPE = (
    'status',
    'environment_id',
    'source_data_generation',
    'source_deployment_id',
    'source_control_revision',
    'operation_id',
    'backup_manifest_sha256',
    'index_sha256',
    'capture_receipt_sha256',
    'policy_sha256',
    'entry_count',
    'shards',
)
MAX_ENTRIES = 50000


def archived_index(path, pin, environment, generation):
    raw = read_protected(path)
    require(sha_value(pin) and digest(raw) == pin, RESOURCE)
    record = decode(raw, RESOURCE)
    version_record(record, ENVELOPE, RESOURCE)
    require(
        record['status'] == 'PRIOR_COMMAND_INDEX_EXPORTED'
        and record['environment_id'] == environment
        and record['source_data_generation'] == generation
        and all(uuid_value(record[field]) for field in ('operation_id', 'source_deployment_id'))
        and all(sha_value(value) for field, value in record.items() if field.endswith('_sha256'))
        and type(record['source_control_revision']) is int
        and 1 <= record['source_control_revision'] < MAX_REVISION
        and type(record['entry_count']) is int
        and 0 <= record['entry_count'] <= MAX_ENTRIES
        and type(record['shards']) is dict
        and len(record['shards']) <= 256,
        RESOURCE,
    )
    count = 0
    for bucket, reference in record['shards'].items():
        require(BUCKET.fullmatch(bucket) is not None, RESOURCE)
        exact(reference, ('bytes', 'sha256', 'entry_count'), RESOURCE)
        require(
            type(reference['bytes']) is int
            and 0 < reference['bytes'] <= MAX_RECORD_SIZE
            and sha_value(reference['sha256'])
            and type(reference['entry_count']) is int
            and 0 < reference['entry_count'] <= MAX_ENTRIES,
            RESOURCE,
        )
        count += reference['entry_count']
    require(count == record['entry_count'], RESOURCE)
    return record


def archived_shard(path, index, bucket):
    raw = read_protected(path.parent / shard_name(bucket))
    return parse_shard(raw, bucket, index['shards'][bucket], index['policy_sha256'])


def visible_prior_environment(connection, principal, environment):
    require(uuid_value(environment), INVALID)
    row = environment_row(connection, environment)
    require(row is not None, MISSING)
    require(may_read_environment(principal, row), DENIED)


def prior_command_scopes(connection, catalog, principal, environment):
    visible_prior_environment(connection, principal, environment)
    return {
        'format_version': 1,
        'environment_id': environment,
        'source_data_generations': sorted(
            generation
            for (identifier, generation), grant in catalog.prior_result_grants.items()
            if identifier == environment and principal.id in grant['read_principals']
        ),
    }


def prior_command_result(connection, catalog, principal, environment, parameters):
    fields = ('source_data_generation', 'original_capability', 'original_target', 'request_key')
    values = dict(parameters.multi_items())
    require(
        uuid_value(environment)
        and len(parameters.multi_items()) == len(fields)
        and set(values) == set(fields),
        INVALID,
    )
    generation, capability, target, key = (values[field] for field in fields)
    require(uuid_value(generation), INVALID)
    fingerprint = scope_key(capability, target, key, INVALID)
    visible_prior_environment(connection, principal, environment)
    grant = catalog.prior_result_grants.get((environment, generation))
    require(grant is not None and principal.id in grant['read_principals'], DENIED)
    result = {
        'format_version': 1,
        'environment_id': environment,
        'source_data_generation': generation,
        'status': 'UNVERIFIABLE',
        'result_summary': None,
        'evidence': None,
    }
    if grant['index'] is None:
        return result
    path, pin = grant['index']
    try:
        record = archived_index(path, pin, environment, generation)
        bucket = fingerprint[:2]
        summary = (
            archived_shard(path, record, bucket).get(fingerprint)
            if bucket in record['shards']
            else None
        )
    except (EnvironmentFailure, OSError, ValueError, KeyError, TypeError):
        return result
    evidence = {
        'kind': 'SEALED_IDEMPOTENCY_RECEIPTS',
        **{
            field: record[field]
            for field in (
                'backup_manifest_sha256',
                'index_sha256',
                'capture_receipt_sha256',
            )
        },
    }
    if summary is None or summary['record_status'] == 'PROCESSING':
        return {**result, 'evidence': evidence}
    return {**result, 'status': 'KNOWN', 'result_summary': summary, 'evidence': evidence}
