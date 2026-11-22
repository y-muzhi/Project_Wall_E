"""Freeze a stopped environment's installed backup policy in its original management operation."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from backend.app.infrastructure.environment_control import normal_stop
from backend.app.infrastructure.environment_files import canonical, digest, exact, require
from backend.app.infrastructure.environment_installation import (
    sha_value,
    uuid_value,
    version_record,
)
from backend.app.shared.time import utc_milliseconds

from .attachment_observation import FRESH_MS
from .lifecycle_operations import authorized, expected_versions
from .operation_contract import DENIED, INVALID, RESOURCE, UNAVAILABLE, installed_record, version
from .operation_store import (
    decoded,
    insert_operation,
    insert_step,
    mutation,
    operation_by_key,
    operation_result,
    require_no_conflicting_action,
    stored,
)
from .registry import is_timestamp, verified_registry
from .release_configuration import CHANGED
from .release_maintenance_view import confirmed_current_control
from .release_operations import no_live_reservation, raw_plan

ACTION = 'BACKUP'
STEP = 'BACKUP_RECOVERY_POINT'
ASSET_UNSUPPORTED = 'BACKUP_ASSET_UNSUPPORTED'
DRAIN_BLOCKED = 'MAINTENANCE_DRAIN_BLOCKED'
FIELDS = (
    'environment_id',
    'expected_record_version',
    'expected_assignment_generation',
    'backup_policy_ref',
    'after_completion',
)
ASSETS = ('BUSINESS_DATABASE', 'COUNT_AUDIT', 'FIXED_RESOURCES', 'ORIGINAL_RESULTS')
LIMITS = ('max_database_bytes', 'max_audit_files', 'max_audit_bytes')


def backup_input(raw, *, confirmed=False):
    mode = 'action' if confirmed else 'kind'
    more = ('plan_id', 'plan_sha256') if confirmed else ()
    exact(raw, (mode, *FIELDS, *more), INVALID)
    require(
        raw[mode] == ACTION
        and all(uuid_value(raw[key]) for key in ('environment_id', 'backup_policy_ref'))
        and all(version(raw[key]) for key in FIELDS[1:3])
        and raw['after_completion'] in ('RESUME_PREVIOUS', 'KEEP_STOPPED'),
        INVALID,
    )
    if confirmed:
        require(uuid_value(raw['plan_id']) and sha_value(raw['plan_sha256']), INVALID)
    return {key: raw[key] for key in FIELDS}


def backup_policy(catalog, reference, identifier, *, supported=True):
    pin = catalog.backup_policies.get(reference)
    require(uuid_value(reference) and sha_value(pin), RESOURCE)
    record = installed_record(catalog.directory / 'backup-policies' / (reference + '.json'), pin)
    version_record(
        record,
        (
            *catalog.scope,
            'backup_policy_ref',
            'environment_id',
            'minimum_verification',
            'assets',
            *LIMITS,
        ),
        RESOURCE,
    )
    require(
        all(record[key] == value for key, value in catalog.scope.items())
        and record['backup_policy_ref'] == reference
        and record['environment_id'] == identifier
        and record['minimum_verification'] in ('LOCAL_VERIFIED', 'OFFHOST_VERIFIED')
        and record['assets'] == list(ASSETS)
        and type(record['max_database_bytes']) is int
        and 4096 <= record['max_database_bytes'] <= 1024**4
        and type(record['max_audit_files']) is int
        and 1 <= record['max_audit_files'] <= 512
        and type(record['max_audit_bytes']) is int
        and 1 <= record['max_audit_bytes'] <= 1024**4,
        ASSET_UNSUPPORTED,
    )
    if supported:
        require(record['minimum_verification'] == 'LOCAL_VERIFIED', ASSET_UNSUPPORTED)
    return record, pin


def stopped_source(connection, catalog, principal, intent):
    require(principal.role == 'MANAGER', DENIED)
    row = authorized(connection, principal, intent['environment_id'])
    expected_versions(row, intent)
    require(row['configuration_ref'] is not None, UNAVAILABLE)
    current = confirmed_current_control(catalog, row)
    require(
        current is not None and normal_stop(current),
        DRAIN_BLOCKED,
    )
    no_live_reservation(connection, row['environment_id'])
    attachment = decoded(row['configuration_ref'])
    candidate = catalog.candidate(attachment['candidate_ref'], attachment['sha256'])
    source = {
        **{
            key: current[key]
            for key in (
                'data_generation',
                'deployment_id',
                'configuration_sha256',
                'program_sha256',
                'control_revision',
                'operation_id',
            )
        },
        'control_sha256': digest(canonical(current)),
        'installation_sha256': candidate['installation']['sha256'],
    }
    policy, pin = backup_policy(catalog, intent['backup_policy_ref'], row['environment_id'])
    return source, attachment, policy, pin


def plan_backup(native, installation, catalog, principal, raw, runtime_sha):
    require(principal.role == 'MANAGER', DENIED)
    intent = backup_input(raw)
    with verified_registry(native, installation, writable=True) as (connection, lock):
        with mutation(connection, lock):
            require_no_conflicting_action(connection, intent['environment_id'])
            source, attachment, policy, policy_pin = stopped_source(
                connection, catalog, principal, intent
            )
            plan = str(uuid4())
            expires = utc_milliseconds(datetime.now(UTC) + timedelta(milliseconds=FRESH_MS))
            preview = {
                'kind': ACTION,
                'plan_id': plan,
                'expires_at': expires,
                **intent,
                'source': source,
                'source_attachment': attachment,
                'completion': 'KEEP_STOPPED',
                'backup_id': str(uuid4()),
                'backup_policy_sha256': policy_pin,
                'minimum_verification': policy['minimum_verification'],
                'assets': policy['assets'],
            }
            pin = digest(canonical(preview))
            connection.execute(
                'INSERT INTO management_plans (plan_id,environment_id,principal,kind,record_version,'
                'assignment_generation,plan_sha256,preview_json,expires_at) VALUES (?,?,?,?,?,?,?,?,?)',
                (
                    plan,
                    intent['environment_id'],
                    principal.id,
                    ACTION,
                    intent['expected_record_version'],
                    intent['expected_assignment_generation'],
                    pin,
                    stored(preview),
                    expires,
                ),
            )
    return {'plan_id': plan, 'plan_sha256': pin, 'expires_at': expires, 'preview': preview}


def confirmed_backup(plan, principal_id, intent, *, unused=False):
    require(
        plan is not None
        and plan['principal'] == principal_id
        and plan['environment_id'] == intent['environment_id']
        and plan['kind'] == ACTION
        and (not unused or plan['execution_operation_id'] is None),
        CHANGED,
    )
    preview = decoded(plan['preview_json'])
    require(
        preview['kind'] == ACTION
        and preview['plan_id'] == plan['plan_id'] == intent['plan_id']
        and preview['expires_at'] == plan['expires_at']
        and is_timestamp(plan['expires_at'])
        and digest(canonical(preview)) == plan['plan_sha256'] == intent['plan_sha256']
        and all(preview[key] == intent[key] for key in FIELDS),
        CHANGED,
    )
    if unused:
        require(datetime.now(UTC) < datetime.fromisoformat(plan['expires_at']), CHANGED)
    return preview


def accept_backup(connection, lock, catalog, principal, key, intent):
    require(principal.role == 'MANAGER', DENIED)
    with mutation(connection, lock):
        plan = raw_plan(connection, intent['plan_id'])
        preview = confirmed_backup(plan, principal.id, intent, unused=True)
        require_no_conflicting_action(connection, intent['environment_id'])
        source, attachment, _policy, pin = stopped_source(connection, catalog, principal, intent)
        require(
            source == preview['source']
            and attachment == preview['source_attachment']
            and pin == preview['backup_policy_sha256'],
            CHANGED,
        )
        generation = catalog.scope['registry_generation']
        operation = insert_operation(
            connection,
            generation,
            key,
            principal,
            intent,
            intent['environment_id'],
            utc_milliseconds(datetime.now(UTC)),
            status='ACCEPTED',
        )
        consumed = connection.execute(
            'UPDATE management_plans SET execution_operation_id=? WHERE plan_id=? AND execution_operation_id IS NULL',
            (operation, intent['plan_id']),
        )
        require(consumed.rowcount == 1, CHANGED)
        insert_step(connection, operation, STEP, None, status='PLANNED')
        return operation_result(connection, operation_by_key(connection, generation, key))
