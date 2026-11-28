"""Seal and read minimal original-command receipts from a verified stopped snapshot."""

import fcntl
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from .environment_backup import SNAPSHOT, capture_policy, original_receipt, recovery_directory
from .environment_files import (
    MAX_RECORD_SIZE,
    EnvironmentFailure,
    absolute,
    canonical,
    decode,
    digest,
    exact,
    persisted_write,
    read_entry,
    read_protected,
    require,
)
from .environment_installation import identity_record, load_installation, sha_value, uuid_value
from .idempotency import generation_namespace

POLICY = 'original-result-index-policy.v1.json'
INDEX = 'original-result-index.v1.json'
INVALID = 'ORIGINAL_RESULT_INDEX_INTENT_MISMATCH'
UNVERIFIED = 'ORIGINAL_RESULT_INDEX_UNVERIFIED'
LIMIT = 'ORIGINAL_RESULT_INDEX_LIMIT'
CAPABILITY = re.compile(r'APP-[A-Z]+-CMD-C[0-9]{2}')
FORMATION_DISCUSS_CAPABILITY = 'formation.discuss'
BUCKET = re.compile(r'[0-9a-f]{2}')
SOURCE_FIELDS = ('environment_id', 'data_generation', 'deployment_id', 'control_revision')


def load_index_policy(path, expected):
    require(path.is_absolute() and path.name == POLICY and sha_value(expected), INVALID)
    raw = read_protected(path)
    require(digest(raw) == expected, INVALID)
    plan = exact(
        decode(raw, INVALID),
        (
            'format_version',
            'operation_id',
            'capture_policy',
            'expected_capture_receipt_sha256',
            'index_directory',
            'index_identity',
            'max_entries',
        ),
        INVALID,
    )
    require(
        type(plan['format_version']) is int
        and plan['format_version'] == 1
        and uuid_value(plan['operation_id'])
        and sha_value(plan['expected_capture_receipt_sha256'])
        and type(plan['max_entries']) is int
        and 1 <= plan['max_entries'] <= 50000,
        INVALID,
    )
    output = absolute(plan['index_directory'], INVALID)
    identity_record(plan['index_identity'], INVALID)
    source = exact(plan['capture_policy'], ('path', 'sha256'), INVALID)
    capture = capture_policy(absolute(source['path'], INVALID), source['sha256'])
    backup = Path(capture['recovery_directory'])
    require(
        plan['operation_id'] != capture['operation_id']
        and plan['index_identity'] != capture['recovery_identity']
        and not output.is_relative_to(backup)
        and not backup.is_relative_to(output),
        INVALID,
    )
    return plan, capture


def scope_key(capability, target, key, code):
    require(
        type(capability) is str
        and len(capability) <= 64
        and (CAPABILITY.fullmatch(capability) or capability == FORMATION_DISCUSS_CAPABILITY)
        and type(target) is str
        and 0 < len(target) <= 512
        and target.isascii()
        and all(32 <= ord(character) < 127 for character in target)
        and uuid_value(key),
        code,
    )
    return digest(canonical([capability, target, key]))


def require_summary(status, http_status):
    require(type(status) is str, UNVERIFIED)
    if status == 'PROCESSING':
        require(http_status is None, UNVERIFIED)
    elif status == 'SUCCEEDED':
        require(type(http_status) is int and 200 <= http_status <= 299, UNVERIFIED)
    else:
        require(
            status in ('REJECTED', 'CLOSED')
            and type(http_status) is int
            and 400 <= http_status <= 499,
            UNVERIFIED,
        )


def collect_receipts(path, capture, limit, *, generation_scoped=False):
    """Read only identity and status columns from the sealed database."""
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as source:
        source.execute('PRAGMA query_only=ON')
        source.execute('BEGIN')
        owners = source.execute(
            'SELECT singleton_id,environment_id,data_generation FROM environment_binding LIMIT 2'
        ).fetchall()
        require(owners == [(1, capture['environment_id'], capture['data_generation'])], UNVERIFIED)
        prefix = generation_namespace(capture['data_generation']) if generation_scoped else ''
        query = (
            'SELECT capability_id,target_identity,idempotency_key,status,http_status '
            'FROM idempotency_records'
        )
        parameters = (limit + 1,)
        if prefix:
            query += ' WHERE substr(target_identity,1,?)=?'
            parameters = (len(prefix), prefix, *parameters)
        rows = source.execute(query + ' LIMIT ?', parameters)
        buckets = {}
        count = 0
        for capability, target, key, status, http_status in rows:
            require(count < limit, LIMIT)
            fingerprint = scope_key(capability, target[len(prefix) :], key, UNVERIFIED)
            require_summary(status, http_status)
            bucket = buckets.setdefault(fingerprint[:2], {})
            require(fingerprint not in bucket, UNVERIFIED)
            bucket[fingerprint] = {'record_status': status, 'original_http_status': http_status}
            count += 1
    return buckets, count


def shard_name(bucket):
    return f'receipts-{bucket}.v1.json'


def common_fields(plan, capture, policy_sha):
    return {
        'format_version': 1,
        'operation_id': plan['operation_id'],
        'policy_sha256': policy_sha,
        'capture_receipt_sha256': plan['expected_capture_receipt_sha256'],
        **{field: capture[field] for field in SOURCE_FIELDS},
    }


def read_sealed(directory, name, installation):
    return read_entry(
        directory,
        name,
        owner=installation.maintenance_uid,
        group=installation.group,
        reject_writers=0o277,
    )


def write_missing(directory, name, raw, installation):
    try:
        current = read_sealed(directory, name, installation)
    except FileNotFoundError:
        persisted_write(directory, name, raw, mode=0o400)
        current = read_sealed(directory, name, installation)
    require(current == raw, UNVERIFIED)


def index_names(directory):
    names = set()
    with os.scandir(directory) as entries:
        for entry in entries:
            require(len(names) < 257, UNVERIFIED)
            names.add(entry.name)
    return names


def read_index(directory, installation, common, limit, *, expected_sha=None):
    raw = read_sealed(directory, INDEX, installation)
    measured = digest(raw)
    require(expected_sha is None or measured == expected_sha, UNVERIFIED)
    value = exact(decode(raw, UNVERIFIED), (*common, 'shards', 'entry_count'), UNVERIFIED)
    require(
        canonical({key: value[key] for key in common}) == canonical(common)
        and type(value['entry_count']) is int
        and 0 <= value['entry_count'] <= limit
        and type(value['shards']) is dict
        and len(value['shards']) <= 256,
        UNVERIFIED,
    )
    count = 0
    for bucket, item in value['shards'].items():
        require(BUCKET.fullmatch(bucket) is not None, UNVERIFIED)
        exact(item, ('bytes', 'sha256', 'entry_count'), UNVERIFIED)
        require(
            type(item['bytes']) is int
            and 0 < item['bytes'] <= MAX_RECORD_SIZE
            and sha_value(item['sha256'])
            and type(item['entry_count']) is int
            and 0 < item['entry_count'] <= limit,
            UNVERIFIED,
        )
        count += item['entry_count']
    require(
        count == value['entry_count']
        and index_names(directory) == {INDEX, *(shard_name(part) for part in value['shards'])},
        UNVERIFIED,
    )
    return value, measured


def read_shard(directory, installation, bucket, reference, policy_sha):
    raw = read_sealed(directory, shard_name(bucket), installation)
    return parse_shard(raw, bucket, reference, policy_sha)


def parse_shard(raw, bucket, reference, policy_sha):
    require(len(raw) == reference['bytes'] and digest(raw) == reference['sha256'], UNVERIFIED)
    shard = exact(
        decode(raw, UNVERIFIED),
        ('format_version', 'bucket', 'policy_sha256', 'entries'),
        UNVERIFIED,
    )
    entries = shard['entries']
    require(
        type(shard['format_version']) is int
        and shard['format_version'] == 1
        and shard['bucket'] == bucket
        and shard['policy_sha256'] == policy_sha
        and type(entries) is dict
        and len(entries) == reference['entry_count'],
        UNVERIFIED,
    )
    for fingerprint, summary in entries.items():
        require(sha_value(fingerprint) and fingerprint[:2] == bucket, UNVERIFIED)
        exact(summary, ('record_status', 'original_http_status'), UNVERIFIED)
        require_summary(summary['record_status'], summary['original_http_status'])
    return entries


def load_inputs(args, active, entry):
    plan, capture = load_index_policy(args.result_index_policy, args.result_index_policy_sha256)
    require(capture['installation_sha256'] == args.anchor_sha256, INVALID)
    program = Path(capture['source_program'])
    require(entry['verify_program'](program) == capture['source_program_sha256'], INVALID)
    installation = load_installation(
        args.anchor, args.anchor_sha256, active.runtime_manifest_sha256, program
    )
    installation.check_identity(maintenance=True)
    require(all(capture[key] == getattr(installation, key) for key in SOURCE_FIELDS[:-1]), INVALID)
    target = {
        'operation_id': plan['operation_id'],
        'recovery_directory': plan['index_directory'],
        'recovery_identity': plan['index_identity'],
    }
    common = common_fields(plan, capture, args.result_index_policy_sha256)
    return plan, capture, installation, target, common


def check_capture(directory, plan, capture, installation):
    receipt = original_receipt(directory, capture, installation, plan['capture_policy']['sha256'])
    require(
        receipt is not None
        and digest(canonical(receipt)) == plan['expected_capture_receipt_sha256'],
        UNVERIFIED,
    )


def shard_bytes(buckets, policy_sha):
    references = {}
    shards = {}
    for bucket, entries in buckets.items():
        raw = canonical(
            {'format_version': 1, 'bucket': bucket, 'policy_sha256': policy_sha, 'entries': entries}
        )
        require(len(raw) <= MAX_RECORD_SIZE, LIMIT)
        references[bucket] = {'entry_count': len(entries), 'bytes': len(raw), 'sha256': digest(raw)}
        shards[bucket] = raw
    return references, shards


def seal_index(active, args, entry):
    plan, capture, installation, target, common = load_inputs(args, active, entry)
    maximum = plan['max_entries']
    policy_sha = args.result_index_policy_sha256
    with recovery_directory(target, installation) as (_, output):
        fcntl.flock(output, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with recovery_directory(capture, installation) as (folder, source):
            check_capture(source, plan, capture, installation)
            try:
                buckets, count = collect_receipts(
                    folder / SNAPSHOT,
                    capture,
                    maximum,
                    generation_scoped=installation.restore_generation_sha256 is not None,
                )
            except sqlite3.Error as error:
                raise EnvironmentFailure(UNVERIFIED) from error
            check_capture(source, plan, capture, installation)

        references, shards = shard_bytes(buckets, policy_sha)
        raw = canonical({**common, 'entry_count': count, 'shards': references})
        names = index_names(output)
        if INDEX not in names:
            require(names <= {shard_name(bucket) for bucket in shards}, UNVERIFIED)
            for bucket, chunk in shards.items():
                if shard_name(bucket) in names:
                    require(
                        read_sealed(output, shard_name(bucket), installation) == chunk, UNVERIFIED
                    )
            for bucket, chunk in shards.items():
                write_missing(output, shard_name(bucket), chunk, installation)
            persisted_write(output, INDEX, raw, mode=0o400)
        index, measured = read_index(
            output,
            installation,
            common,
            maximum,
            expected_sha=digest(raw),
        )
        for bucket, reference in index['shards'].items():
            read_shard(output, installation, bucket, reference, policy_sha)
    return {
        'status': 'ORIGINAL_RESULT_INDEX_SEALED',
        'operation_id': plan['operation_id'],
        'environment_id': capture['environment_id'],
        'data_generation': capture['data_generation'],
        'index': {'name': INDEX, 'bytes': len(raw), 'sha256': measured},
        'entry_count': count,
    }


def indexed_summary(directory, installation, index, key):
    bucket = key[:2]
    reference = index['shards'].get(bucket)
    if reference is None:
        return None
    entries = read_shard(directory, installation, bucket, reference, index['policy_sha256'])
    receipt = entries.get(key)
    if receipt is None or receipt['record_status'] == 'PROCESSING':
        return None
    return receipt


def original_result(result, capture, index_sha, capture_receipt_sha):
    return {
        'status': 'KNOWN' if result is not None else 'UNVERIFIABLE',
        'environment_id': capture['environment_id'],
        'data_generation': capture['data_generation'],
        'result_summary': result,
        'evidence': {
            'kind': 'SEALED_IDEMPOTENCY_RECEIPTS',
            'index_sha256': index_sha,
            'capture_receipt_sha256': capture_receipt_sha,
        },
    }


def lookup_index(active, args, entry):
    plan, capture, installation, target, common = load_inputs(args, active, entry)
    require(
        sha_value(args.result_index_sha256)
        and args.source_environment_id == capture['environment_id']
        and args.source_data_generation == capture['data_generation'],
        INVALID,
    )
    key = scope_key(
        args.original_capability, args.original_target, args.original_request_key, INVALID
    )
    with recovery_directory(target, installation) as (_, output):
        fcntl.flock(output, fcntl.LOCK_SH | fcntl.LOCK_NB)
        index, measured = read_index(
            output, installation, common, plan['max_entries'], expected_sha=args.result_index_sha256
        )
        result = indexed_summary(output, installation, index, key)
    return original_result(result, capture, measured, plan['expected_capture_receipt_sha256'])
