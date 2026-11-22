"""Dispatch the confirmed stopped source through the original SQLite backup operation."""

import os

from backend.app.infrastructure.environment_backup import capture_policy, capture_status
from backend.app.infrastructure.environment_files import (
    MAX_REVISION,
    EnvironmentFailure,
    canonical,
    digest,
    exact,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value

from .attachment_observation import candidate_environment, invoke_observer
from .backup_operations import ACTION, LIMITS, STEP, backup_policy, confirmed_backup, stopped_source
from .operation_contract import DENIED, INVALID, RESOURCE, UNAVAILABLE, VERSION
from .operation_store import decoded, mutation, stored
from .recovery_evidence import backup_cutoff
from .release_configuration import CHANGED
from .release_execution import (
    environment_command,
    execution_directory,
    manager_command,
    optional_fact,
    write_fact,
)
from .release_maintenance_view import confirmed_control
from .release_operations import raw_plan

EXECUTIONS = 'backup-executions'
CAPTURE_ISSUED = 'capture-issued.v1.json'
CAPTURED = 'captured.v1.json'
CAPTURE_FIELDS = (
    'operation_id',
    'environment_id',
    'data_generation',
    'deployment_id',
    'control_revision',
)
UNVERIFIED = 'MANAGED_BACKUP_CAPTURE_UNVERIFIED'


def backup_record(connection, catalog, operation_id):
    require(uuid_value(operation_id), INVALID)
    row = connection.execute(
        'SELECT * FROM management_operations WHERE operation_id=? AND registry_generation=? AND action=?',
        (operation_id, catalog.scope['registry_generation'], ACTION),
    ).fetchone()
    require(row is not None, RESOURCE)
    step = connection.execute(
        'SELECT * FROM management_steps WHERE operation_id=? AND ordinal=1 AND step_kind=?',
        (operation_id, STEP),
    ).fetchone()
    require(step is not None, RESOURCE)
    return row, step


def capture_grant(catalog, operation, preview, record):
    return {
        'format_version': 1,
        **catalog.scope,
        'operation_id': operation['operation_id'],
        'environment_id': operation['environment_id'],
        'plan_sha256': digest(canonical(preview)),
        **{
            key: preview[key]
            for key in (
                'backup_id',
                'backup_policy_ref',
                'backup_policy_sha256',
                'source',
                'source_attachment',
            )
        },
        'limits': {key: record[key] for key in LIMITS},
    }


def claim_backup(connection, lock, catalog, request):
    exact(request, ('operation_id',), INVALID)
    with mutation(connection, lock):
        operation, step = backup_record(connection, catalog, request['operation_id'])
        principal = catalog.access(operation['principal'])
        require(principal.role == 'MANAGER', DENIED)
        intent = decoded(operation['intent_json'])
        plan = raw_plan(connection, intent['plan_id'])
        preview = confirmed_backup(plan, principal.id, intent)
        require(plan['execution_operation_id'] == operation['operation_id'], CHANGED)
        policy, pin = backup_policy(
            catalog, preview['backup_policy_ref'], operation['environment_id']
        )
        require(pin == preview['backup_policy_sha256'], CHANGED)
        grant = capture_grant(catalog, operation, preview, policy)
        if step['external_identity_json'] is not None:
            existing = decoded(step['external_identity_json'])
            require(
                operation['status'] in ('RUNNING', 'SUCCEEDED')
                and not operation['cancel_requested']
                and existing.get('capture') == grant,
                RESOURCE,
            )
            return grant
        require(
            operation['status'] == 'ACCEPTED'
            and step['status'] == 'PLANNED'
            and operation['revision'] < MAX_REVISION
            and not operation['cancel_requested'],
            UNAVAILABLE,
        )
        current, attachment, _, _ = stopped_source(connection, catalog, principal, intent)
        require(current == grant['source'] and attachment == grant['source_attachment'], CHANGED)
        dispatched = connection.execute(
            "UPDATE management_operations SET status='RUNNING',revision=revision+1 "
            "WHERE operation_id=? AND status='ACCEPTED' AND revision=?",
            (operation['operation_id'], operation['revision']),
        )
        saved = connection.execute(
            "UPDATE management_steps SET status='DISPATCHING',executor_ref=?,external_identity_json=? "
            "WHERE operation_id=? AND ordinal=1 AND step_kind=? AND status='PLANNED'",
            ('NATIVE_DATABASE_BACKUP', stored({'capture': grant}), operation['operation_id'], STEP),
        )
        require(dispatched.rowcount == saved.rowcount == 1, VERSION)
        return grant


def admitted_backup(catalog, registry, args, launcher):
    operation = args.backup_operation_id
    grant = invoke_observer(
        registry.uid,
        registry.gid,
        manager_command('_claim-managed-backup', args, launcher),
        catalog.directory / 'observations',
        input_bytes=canonical({'operation_id': operation}),
    )
    require(
        grant['operation_id'] == operation
        and uuid_value(grant['backup_id'])
        and all(grant[key] == value for key, value in catalog.scope.items()),
        RESOURCE,
    )
    ref = grant['source_attachment']
    candidate = catalog.candidate(ref['candidate_ref'], ref['sha256'])
    source = candidate_environment(candidate, args.sha256)
    expected = grant['source']
    require(
        source.environment_id == grant['environment_id']
        and source.anchor_sha256 == expected['installation_sha256']
        and source.description['program_source']['sha256'] == expected['program_sha256']
        and all(
            getattr(source, key) == expected[key]
            for key in ('data_generation', 'deployment_id', 'configuration_sha256')
        ),
        CHANGED,
    )
    return grant, source


def check_capture_plan(plan, grant, source):
    require(
        plan['format_version'] == 2
        and 'maintenance' not in plan
        and plan['operation_id'] == grant['backup_id']
        and plan['environment_id'] == grant['environment_id']
        and plan['source_program'] == str(source.project)
        and plan['source_program_sha256'] == grant['source']['program_sha256']
        and all(
            plan[key] == grant['source'][key]
            for key in (
                'data_generation',
                'deployment_id',
                'control_revision',
                'installation_sha256',
            )
        )
        and all(plan[key] == grant['limits'][key] for key in LIMITS),
        CHANGED,
    )


def captured_result(fact, grant, capture_sha, policy):
    exact(
        fact,
        (
            'format_version',
            'status',
            'intent_sha256',
            *CAPTURE_FIELDS,
            'cutoff_at',
            'database_artifact',
            'asset_index',
        ),
        UNVERIFIED,
    )
    database = exact(fact['database_artifact'], ('identity', 'bytes', 'sha256'), UNVERIFIED)
    require(
        fact['format_version'] == 2
        and fact['status'] == capture_status(2)
        and fact['intent_sha256'] == capture_sha
        and all(fact[key] == policy[key] for key in CAPTURE_FIELDS)
        and type(database['bytes']) is int
        and 0 < database['bytes'] <= policy['max_database_bytes']
        and sha_value(database['sha256'])
        and type(fact['asset_index']) is dict,
        UNVERIFIED,
    )
    return {
        'format_version': 1,
        'status': 'MANAGED_BACKUP_CAPTURED',
        **{key: fact[key] for key in CAPTURE_FIELDS[1:]},
        'cutoff_at': backup_cutoff(fact['cutoff_at'], UNVERIFIED),
        'operation_id': grant['operation_id'],
        'backup_id': grant['backup_id'],
        'grant_sha256': digest(canonical(grant)),
        'capture_policy_sha256': capture_sha,
        'capture_receipt_sha256': digest(canonical(fact)),
        'database_sha256': database['sha256'],
        'database_bytes': database['bytes'],
    }


def checked_capture_receipt(receipt, grant):
    exact(
        receipt,
        (
            'format_version',
            'status',
            *CAPTURE_FIELDS,
            'cutoff_at',
            'backup_id',
            'grant_sha256',
            'capture_policy_sha256',
            'capture_receipt_sha256',
            'database_sha256',
            'database_bytes',
        ),
        RESOURCE,
    )
    require(
        receipt['format_version'] == 1
        and receipt['status'] == 'MANAGED_BACKUP_CAPTURED'
        and all(
            receipt[key] == grant[key] for key in ('operation_id', 'environment_id', 'backup_id')
        )
        and all(receipt[key] == grant['source'][key] for key in CAPTURE_FIELDS[2:])
        and receipt['grant_sha256'] == digest(canonical(grant))
        and all(
            sha_value(receipt[key])
            for key in ('capture_policy_sha256', 'capture_receipt_sha256', 'database_sha256')
        )
        and type(receipt['database_bytes']) is int
        and 0 < receipt['database_bytes'] <= grant['limits']['max_database_bytes']
        and backup_cutoff(receipt['cutoff_at'], RESOURCE) == receipt['cutoff_at'],
        RESOURCE,
    )
    return receipt


def capture_managed_backup(catalog, registry, args, launcher):
    operation = args.backup_operation_id
    require(os.geteuid() == 0 and uuid_value(operation), DENIED)
    with execution_directory(catalog, EXECUTIONS, operation, create=True) as (_, fd):
        grant, source = admitted_backup(catalog, registry, args, launcher)
        policy = capture_policy(args.capture_policy, args.capture_sha256)
        check_capture_plan(policy, grant, source)
        identity = {
            'format_version': 1,
            'operation_id': operation,
            'backup_id': grant['backup_id'],
            'grant_sha256': digest(canonical(grant)),
            'capture_policy_sha256': args.capture_sha256,
        }
        previous = optional_fact(fd, CAPTURE_ISSUED)
        if previous is None:
            current = confirmed_control((source,))
            require(digest(canonical(current)) == grant['source']['control_sha256'], CHANGED)
            write_fact(fd, CAPTURE_ISSUED, identity)
        else:
            require(previous == identity, CHANGED)
        known = optional_fact(fd, CAPTURED)
        if known is not None:
            require(all(known[key] == value for key, value in identity.items()), RESOURCE)
            return checked_capture_receipt(known, grant)
        try:
            measured = invoke_observer(
                source.maintenance_uid,
                source.group,
                environment_command(
                    'capture-database',
                    args,
                    launcher,
                    source,
                    '--capture-policy',
                    args.capture_policy,
                    '--capture-sha256',
                    args.capture_sha256,
                ),
                catalog.directory / 'observations',
                timeout=150,
            )
            receipt = captured_result(measured, grant, args.capture_sha256, policy)
            write_fact(fd, CAPTURED, receipt)
        except (EnvironmentFailure, OSError, RuntimeError, ValueError) as error:
            raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
        return receipt
