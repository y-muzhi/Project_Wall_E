"""Preview and accept the confirmed management operation for an ordinary restore."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from backend.app.infrastructure.environment_backup_package import VERIFY_POLICY
from backend.app.infrastructure.environment_control import normal_stop
from backend.app.infrastructure.environment_files import canonical, digest, exact, require
from backend.app.infrastructure.environment_installation import (
    sha_value,
    uuid_value,
    version_record,
)
from backend.app.infrastructure.environment_release_deployment import RESTORE_POLICY
from backend.app.infrastructure.environment_release_preflight import (
    candidate_target,
    read_reference,
)
from backend.app.infrastructure.environment_restore_preflight import (
    restore_authorization,
    restore_plan,
    selected_offhost_report,
)
from backend.app.shared.time import utc_milliseconds

from .attachment_observation import FRESH_MS, now
from .backup_reconciliation import managed_backup_history
from .lifecycle_operations import authorized, expected_versions
from .operation_contract import DENIED, INVALID, RESOURCE, installed_record, path_reference, version
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
from .recovery_evidence import parse_local_recovery
from .registry import is_timestamp, verified_registry
from .release_candidates import installed_candidate
from .release_configuration import CHANGED, INCOMPATIBLE, read_recovery_policy
from .release_maintenance_view import confirmed_current_control
from .release_operations import no_live_reservation, raw_plan

ACTION = 'RESTORE'
STEP = 'RESTORE_ENVIRONMENT'
DRAIN_BLOCKED = 'MAINTENANCE_DRAIN_BLOCKED'
FIELDS = (
    'environment_id',
    'expected_record_version',
    'expected_assignment_generation',
    'backup_id',
    'target_release_ref',
    'target_configuration_ref',
    'recovery_policy_ref',
    'source_data_generation',
)


def restore_input(raw, *, confirmed=False):
    discriminator = 'action' if confirmed else 'kind'
    more = ('plan_id', 'plan_sha256') if confirmed else ()
    exact(raw, (discriminator, *FIELDS, *more), INVALID)
    require(
        raw[discriminator] == ACTION
        and all(uuid_value(raw[key]) for key in (FIELDS[0], *FIELDS[3:]))
        and all(version(raw[key]) for key in FIELDS[1:3]),
        INVALID,
    )
    if confirmed:
        require(uuid_value(raw['plan_id']) and sha_value(raw['plan_sha256']), INVALID)
    return {key: raw[key] for key in FIELDS}


def registered_restore(catalog, reference):
    pin = catalog.restore_configurations.get(reference)
    require(uuid_value(reference) and sha_value(pin), RESOURCE)
    record = installed_record(
        catalog.directory / 'restore-configurations' / (reference + '.json'), pin
    )
    version_record(
        record,
        (
            *catalog.scope,
            'configuration_ref',
            'environment_id',
            'release_ref',
            'release_candidate_sha256',
            'source_attachment',
            'target_attachment_ref',
            'source_control_sha256',
            'source_database_identity_sha256',
            'deployment_policy',
            'preflight_template',
            'recovery_policy',
        ),
        RESOURCE,
    )
    require(
        all(record[key] == value for key, value in catalog.scope.items())
        and record['configuration_ref'] == reference
        and all(
            uuid_value(record[key])
            for key in ('environment_id', 'release_ref', 'target_attachment_ref')
        )
        and all(
            sha_value(record[field])
            for field in ('source_control_sha256', 'source_database_identity_sha256')
        ),
        RESOURCE,
    )
    exact(record['source_attachment'], ('candidate_ref', 'sha256'), RESOURCE)
    exact(record['recovery_policy'], ('ref', 'sha256'), RESOURCE)
    return record, pin


def restore_recovery_policy(catalog, policy_reference, template):
    recovery = read_recovery_policy(catalog, policy_reference, allow_offhost=True)
    require(recovery.get('offhost_authority') == template.get('offhost_authority'), CHANGED)
    return recovery


def checked_restore_point(point, environment, template, ceiling):
    require(
        point is not None
        and point['verification_status'] in ('LOCAL_VERIFIED', 'OFFHOST_VERIFIED')
        and point['local_verification'] is not None
        and point['source_environment_id'] == environment
        and point['cutoff_at'] == template['accepted_backup_cutoff_at'],
        CHANGED,
    )
    if template['format_version'] == 1:
        return None
    offhost = point.get('offhost_verification')
    require(point['verification_status'] == 'OFFHOST_VERIFIED' and offhost is not None, CHANGED)
    verified = selected_offhost_report(template, point, environment, ceiling, CHANGED)
    require(
        offhost
        == {field: verified[field] for field in ('verification_id', 'snapshot_id', 'retrieved_at')},
        CHANGED,
    )
    return verified


def selected_point(connection, catalog, intent, template):
    ceiling = now()
    environment = intent['environment_id']
    _, points = managed_backup_history(connection, catalog, environment, ceiling)
    point = next((item for item in points if item['backup_id'] == intent['backup_id']), None)
    offhost = checked_restore_point(point, environment, template, ceiling)
    selected = template['selected']
    verification = read_reference(selected['verification'], name=VERIFY_POLICY)
    read = parse_local_recovery(read_reference(selected['local_verification']), RESOURCE)
    require(
        selected['backup_id']
        == verification['backup_id']
        == read['backup_id']
        == point['backup_id']
        and verification['backup_manifest_sha256']
        == read['backup_manifest_sha256']
        == point['backup_manifest_sha256']
        and read['environment_id'] == point['source_environment_id']
        and read['logical_content_sha256'] == point['logical_content_sha256']
        and read['verification_id'] == point['local_verification']['verification_id']
        and read['verified_at'] == point['local_verification']['verified_at'],
        CHANGED,
    )
    selected = {
        field: point[field]
        for field in (
            'backup_id',
            'source_data_generation',
            'source_deployment_id',
            'cutoff_at',
            'backup_manifest_sha256',
            'logical_content_sha256',
        )
    }
    return selected, offhost


def restore_subject(connection, catalog, principal, intent, runtime_sha):
    require(principal.role == 'MANAGER', DENIED)
    row = authorized(connection, principal, intent['environment_id'])
    expected_versions(row, intent)
    no_live_reservation(connection, row['environment_id'])
    require(row['configuration_ref'] is not None, CHANGED)
    current = confirmed_current_control(catalog, row)
    require(current is not None and normal_stop(current), DRAIN_BLOCKED)
    record, configuration_pin = registered_restore(catalog, intent['target_configuration_ref'])
    attachment = decoded(row['configuration_ref'])
    require(
        record['environment_id'] == row['environment_id']
        and record['source_attachment'] == attachment
        and record['release_ref'] == intent['target_release_ref']
        and record['target_attachment_ref'] not in catalog.candidates
        and record['recovery_policy']['ref'] == intent['recovery_policy_ref']
        and current['data_generation'] == intent['source_data_generation'],
        CHANGED,
    )
    source = catalog.candidate(attachment['candidate_ref'], attachment['sha256'])
    template_path, template_pin = path_reference(record['preflight_template'])
    template = restore_plan(template_path, template_pin)
    recovery = restore_recovery_policy(catalog, record['recovery_policy'], template)
    deployment = read_reference(record['deployment_policy'], name=RESTORE_POLICY)
    require(
        template['installation_sha256']
        == deployment['installation_sha256']
        == source['installation']['sha256']
        and template['source_data_generation'] == current['data_generation']
        and template['source_deployment_id']
        == deployment['source_deployment_id']
        == current['deployment_id']
        and template['source_configuration_sha256'] == current['configuration_sha256']
        and template['source_control_revision'] == current['control_revision'] + 1
        and all(
            template[field] == deployment[field]
            for field in (
                'operation_id',
                'target_data_generation',
                'target_deployment_id',
                'target_manifest',
                'target_schema_directory',
                'candidate_proof',
            )
        ),
        CHANGED,
    )
    candidate_record = installed_candidate(
        catalog, record['release_ref'], record['release_candidate_sha256']
    )
    proof, release, schema, program = candidate_target(
        template, SimpleNamespace(runtime_manifest_sha256=runtime_sha)
    )
    require(
        template['target_manifest'] == candidate_record['manifest_ref']
        and release['release_id'] == record['release_ref']
        and proof['candidate_sha256'] == record['release_candidate_sha256']
        and proof['schema_contract_sha256'] == schema.schema_contract_sha256,
        INCOMPATIBLE,
    )
    point, offhost = selected_point(connection, catalog, intent, template)
    return {
        'operation_id': template['operation_id'],
        'source': {
            **{
                field: current[field]
                for field in (
                    'data_generation',
                    'deployment_id',
                    'configuration_sha256',
                    'program_sha256',
                    'control_revision',
                    'operation_id',
                )
            },
            'control_sha256': record['source_control_sha256'],
            'control_observation_sha256': digest(canonical(current)),
            'installation_sha256': template['installation_sha256'],
            'database_identity_sha256': record['source_database_identity_sha256'],
        },
        'target': {
            'data_generation': template['target_data_generation'],
            'deployment_id': template['target_deployment_id'],
            'configuration_sha256': template['target_configuration_sha256'],
            'program_sha256': program,
        },
        'source_attachment': attachment,
        'target_attachment_ref': record['target_attachment_ref'],
        'configuration_record_sha256': configuration_pin,
        'release_candidate_sha256': record['release_candidate_sha256'],
        'release_manifest_sha256': candidate_record['manifest_ref']['sha256'],
        'schema_contract_sha256': schema.schema_contract_sha256,
        'recovery_requirement': recovery['minimum_verification'],
        'recovery_policy_sha256': record['recovery_policy']['sha256'],
        'restore_authorization_sha256': restore_authorization(template),
        'preserved_backup_id': template['preserved']['backup_id'],
        'data_handling': template['data_handling'],
        'backup': point,
        **({'offhost_recovery': offhost} if offhost is not None else {}),
    }


def plan_restore(native, installation, catalog, principal, raw, runtime_sha):
    require(principal.role == 'MANAGER', DENIED)
    intent = restore_input(raw)
    with (
        verified_registry(native, installation, writable=True) as (connection, lock),
        mutation(connection, lock),
    ):
        require_no_conflicting_action(connection, intent['environment_id'])
        subject = restore_subject(connection, catalog, principal, intent, runtime_sha)
        require(not operation_exists(connection, subject['operation_id']), CHANGED)
        identifier = str(uuid4())
        expires = utc_milliseconds(datetime.now(UTC) + timedelta(milliseconds=FRESH_MS))
        preview = {
            'kind': ACTION,
            'plan_id': identifier,
            'expires_at': expires,
            **intent,
            **subject,
        }
        pin = digest(canonical(preview))
        connection.execute(
            'INSERT INTO management_plans (plan_id,environment_id,principal,kind,record_version,'
            'assignment_generation,plan_sha256,preview_json,expires_at) VALUES (?,?,?,?,?,?,?,?,?)',
            (
                identifier,
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
    return {'plan_id': identifier, 'plan_sha256': pin, 'expires_at': expires, 'preview': preview}


def operation_exists(connection, operation):
    return (
        connection.execute(
            'SELECT 1 FROM management_operations WHERE operation_id=?', (operation,)
        ).fetchone()
        is not None
    )


def confirmed_restore(plan, principal_id, intent, *, unused=False):
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


def accept_restore(connection, lock, catalog, principal, key, raw, runtime_sha):
    require(principal.role == 'MANAGER', DENIED)
    intent = restore_input(raw, confirmed=True)
    with mutation(connection, lock):
        preview = confirmed_restore(
            raw_plan(connection, raw['plan_id']), principal.id, raw, unused=True
        )
        require_no_conflicting_action(connection, intent['environment_id'])
        subject = restore_subject(connection, catalog, principal, intent, runtime_sha)
        operation = subject['operation_id']
        require(
            all(preview[field] == value for field, value in subject.items())
            and not operation_exists(connection, operation),
            CHANGED,
        )
        generation = catalog.scope['registry_generation']
        insert_operation(
            connection,
            generation,
            key,
            principal,
            raw,
            intent['environment_id'],
            utc_milliseconds(datetime.now(UTC)),
            status='ACCEPTED',
            operation_id=operation,
        )
        consumed = connection.execute(
            'UPDATE management_plans SET execution_operation_id=? WHERE plan_id=? AND execution_operation_id IS NULL',
            (operation, raw['plan_id']),
        )
        require(consumed.rowcount == 1, CHANGED)
        insert_step(connection, operation, STEP, None, status='PLANNED')
        return operation_result(connection, operation_by_key(connection, generation, key))
