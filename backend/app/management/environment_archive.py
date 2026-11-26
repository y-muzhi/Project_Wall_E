"""Archive a registered workspace after the fixed host verifies its stopped state."""

import os

from backend.app.infrastructure.environment_control import normal_stop
from backend.app.infrastructure.environment_files import (
    MAX_REVISION,
    canonical,
    digest,
    exact,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value
from backend.app.infrastructure.environment_lock import NativeEnvironmentFiles

from .attachment_observation import (
    ATTACHMENT_RESOURCE_KINDS,
    candidate_environment,
    invoke_observer,
    machine_clock,
    now,
    observation_path,
    public_facts,
    publish_observation,
    require_fresh,
    verified_workspace,
)
from .lifecycle_operations import authorized, expected_versions
from .operation_contract import (
    CONFLICT,
    DENIED,
    INVALID,
    MISSING,
    RELEASE_ACTIONS,
    RESOURCE,
    UNAVAILABLE,
    VERSION,
    installed_record,
    version,
)
from .operation_store import (
    decoded,
    insert_operation,
    insert_step,
    mutation,
    operation_result,
    require_no_conflicting_action,
    stored,
)
from .registry import is_timestamp
from .registry_recovery_backup import completed_backup_evidence
from .registry_recovery_effects import helper_observation, resource_observation
from .registry_recovery_inventory import PROJECTIONS
from .registry_recovery_observation import observed_assignment, observed_stopped, registered_subject
from .registry_recovery_outcome import pending_operation_clause, pending_step_clause
from .registry_recovery_release_retirement import retired_release_evidence
from .registry_recovery_restore_retirement import retired_restore_evidence
from .release_execution import manager_command
from .release_maintenance_view import confirmed_current_control
from .runtime_capacity import held_capacity

STEP = 'ENVIRONMENT_ARCHIVED'
PHYSICAL_ARCHIVE = 'MANAGEMENT_ARCHIVE_RESOURCES_VERIFIED'


def archive_intent(raw):
    exact(
        raw,
        ('action', 'environment_id', 'expected_record_version', 'expected_assignment_generation'),
        INVALID,
    )
    require(
        raw['action'] == 'ARCHIVE'
        and uuid_value(raw['environment_id'])
        and version(raw['expected_record_version'])
        and version(raw['expected_assignment_generation']),
        INVALID,
    )
    return raw


def archive_reason(catalog, principal, row, busy, *, capacity_held):
    if principal.role != 'MANAGER':
        return DENIED
    if (
        row['purpose'] not in ('DEVELOPMENT', 'INTEGRATION')
        or row['registration_state'] != 'ACTIVE'
        or row['preparation_state'] != 'PREPARED'
        or row['assignment_control_state'] != 'OPEN'
        or row['configuration_ref'] is None
    ):
        return UNAVAILABLE
    if busy or capacity_held:
        return CONFLICT
    actual = confirmed_current_control(catalog, row)
    return None if actual is not None and normal_stop(actual) else RESOURCE


def has_capacity(connection, environment):
    return any(row['environment_id'] == environment for row in held_capacity(connection))


def accept_archive(connection, lock, catalog, principal, key, intent):
    require(principal.role == 'MANAGER', DENIED)
    with mutation(connection, lock):
        row = authorized(connection, principal, intent['environment_id'])
        expected_versions(row, intent)
        require_no_conflicting_action(connection, row['environment_id'])
        reason = archive_reason(
            catalog,
            principal,
            row,
            False,
            capacity_held=has_capacity(connection, row['environment_id']),
        )
        require(reason is None, reason)
        operation = insert_operation(
            connection,
            catalog.scope['registry_generation'],
            key,
            principal,
            intent,
            row['environment_id'],
            now(),
            status='ACCEPTED',
        )
        insert_step(connection, operation, STEP, None, status='PLANNED')
        return operation_result(connection, archive_operation(connection, catalog, operation))


def archive_operation(connection, catalog, operation):
    require(uuid_value(operation), INVALID)
    row = connection.execute(
        'SELECT * FROM management_operations '
        "WHERE operation_id=? AND registry_generation=? AND action='ARCHIVE'",
        (operation, catalog.scope['registry_generation']),
    ).fetchone()
    require(row is not None, MISSING)
    return row


def scoped_projection(connection, name, environment, **arguments):
    query = PROJECTIONS[name].format(**arguments)
    return [
        dict(row)
        for row in connection.execute(
            f'SELECT * FROM ({query}) WHERE environment_id=?', (environment,)
        )
    ]


def original_binding(connection, step):
    op = connection.execute(
        'SELECT intent_sha256 FROM management_operations WHERE operation_id=?',
        (step['operation_id'],),
    ).fetchone()
    require(op is not None, RESOURCE)
    return {
        'operation_id': step['operation_id'],
        'source_registry_generation': step['registry_generation'],
        'source_revision': step['original_revision'],
        'source_intent_sha256': op['intent_sha256'],
    }


def terminal_helper(connection, catalog, step):
    action = step['original_action']
    if action == 'BACKUP' and step['original_operation_status'] == 'SUCCEEDED':
        return completed_backup_evidence(connection, catalog, original_binding(connection, step))
    if action == 'RESTORE' and step['original_operation_status'] == 'CANCELLED':
        return retired_restore_evidence(connection, catalog, original_binding(connection, step))
    if action in RELEASE_ACTIONS and step['original_operation_status'] == 'CANCELLED':
        return retired_release_evidence(connection, catalog, original_binding(connection, step))
    return None


def archive_subject(connection, catalog, operation):
    require(operation['status'] == 'ACCEPTED' and not operation['cancel_requested'], UNAVAILABLE)
    intent = archive_intent(decoded(operation['intent_json']))
    principal = catalog.access(operation['principal'])
    require(principal.role == 'MANAGER', DENIED)
    environment = operation['environment_id']
    row = authorized(connection, principal, environment)
    expected_versions(row, intent)
    require(
        intent['environment_id'] == environment
        and digest(canonical(intent)) == operation['intent_sha256']
        and not has_capacity(connection, environment)
        and connection.execute(
            'SELECT 1 FROM management_operations AS op '
            'WHERE environment_id=? AND operation_id<>? AND '
            + pending_operation_clause(connection),
            (environment, operation['operation_id']),
        ).fetchone()
        is None,
        CONFLICT,
    )
    step = connection.execute(
        'SELECT ordinal,step_kind,status,executor_ref,'
        'external_identity_json,result_json FROM management_steps '
        'WHERE operation_id=? ORDER BY ordinal',
        (operation['operation_id'],),
    ).fetchall()
    require(len(step) == 1 and tuple(step[0]) == (1, STEP, 'PLANNED', None, None, None), RESOURCE)
    registrations = scoped_projection(connection, 'environments.jsonl', environment)
    require(len(registrations) == 1, RESOURCE)
    claims = scoped_projection(connection, 'claims.jsonl', environment)
    require({claim['kind'] for claim in claims} == ATTACHMENT_RESOURCE_KINDS, RESOURCE)
    candidates = scoped_projection(
        connection, 'steps.jsonl', environment, pending_step=pending_step_clause(connection)
    )
    helpers = []
    for candidate in candidates:
        settled = terminal_helper(connection, catalog, candidate)
        if settled is None:
            require(candidate['status'] not in ('DISPATCHING', 'UNKNOWN'), RESOURCE)
            helpers.append(candidate)
    return {
        'operation_id': operation['operation_id'],
        'intent_sha256': operation['intent_sha256'],
        'revision': operation['revision'],
        'environment': registrations[0],
        'claims': claims,
        'helpers': helpers,
    }


def read_archive_subject(connection, catalog, request):
    exact(request, ('operation_id',), INVALID)
    operation = archive_operation(connection, catalog, request['operation_id'])
    if operation['status'] == 'SUCCEEDED':
        return {'receipt': operation_result(connection, operation)}
    return {'subject': archive_subject(connection, catalog, operation)}


def archive_ref(operation):
    return f'archive-{operation}'


def complete_archive(connection, lock, catalog, request):
    exact(request, ('operation_id', 'proof_sha256'), INVALID)
    identifier = request['operation_id']
    pin = request['proof_sha256']
    require(uuid_value(identifier) and sha_value(pin), INVALID)
    with mutation(connection, lock):
        operation = archive_operation(connection, catalog, identifier)
        if operation['status'] == 'SUCCEEDED':
            return operation_result(connection, operation)
        subject = archive_subject(connection, catalog, operation)
        proof = exact(
            installed_record(observation_path(catalog, archive_ref(identifier)), pin),
            (
                'format_version',
                *catalog.scope,
                'status',
                'operation_id',
                'subject_sha256',
                'control_sha256',
                'boot_id',
                'observed_at',
                'observed_monotonic_ms',
            ),
            RESOURCE,
        )
        require(
            proof['format_version'] == 1
            and proof['status'] == PHYSICAL_ARCHIVE
            and all(proof[key] == value for key, value in catalog.scope.items())
            and proof['operation_id'] == identifier
            and proof['subject_sha256'] == digest(canonical(subject))
            and sha_value(proof['control_sha256'])
            and is_timestamp(proof['observed_at']),
            RESOURCE,
        )
        require_fresh(proof)
        row = subject['environment']
        revision = row['record_version']
        require(revision < MAX_REVISION and operation['revision'] < MAX_REVISION, VERSION)
        result = {
            'environment_id': row['environment_id'],
            'record_version': revision + 1,
            'assignment_generation': row['assignment_generation'],
            'archived_at': now(),
        }
        changed = connection.execute(
            "UPDATE managed_environments SET registration_state='ARCHIVED',record_version=? "
            'WHERE environment_id=? AND record_version=? AND '
            "assignment_generation=? AND registration_state='ACTIVE'",
            (
                result['record_version'],
                row['environment_id'],
                revision,
                row['assignment_generation'],
            ),
        )
        advanced = connection.execute(
            "UPDATE management_operations SET status='SUCCEEDED',revision=revision+1 "
            "WHERE operation_id=? AND revision=? AND status='ACCEPTED'",
            (identifier, operation['revision']),
        )
        settled = connection.execute(
            "UPDATE management_steps SET status='SUCCEEDED',result_json=? "
            "WHERE operation_id=? AND ordinal=1 AND status='PLANNED'",
            (stored(result), identifier),
        )
        require(changed.rowcount == advanced.rowcount == settled.rowcount == 1, VERSION)
        return operation_result(connection, archive_operation(connection, catalog, identifier))


def verified_archive_host(catalog, args, entry, subject, environment, lock, native):
    stopped = observed_stopped(native, environment, lock)
    require(stopped['closed_reason'] == 'NORMAL_STOP', RESOURCE)
    row = subject['environment']
    reference = decoded(row['configuration_ref'])
    candidate = catalog.candidate(reference['candidate_ref'], reference['sha256'])

    def observe_workspace(path, pin):
        return verified_workspace(
            (path, pin), args, catalog.directory / 'observations', ownership_only=True
        )

    assignment, head = observed_assignment(environment, candidate, observe_workspace)
    actual = {**stopped, 'assignment_claims': assignment}
    resources = [resource_observation(claim, actual) for claim in subject['claims']]
    require(
        all(claim['state'] in ('BOUND', 'PRESERVED') for claim in resources)
        and {claim['resource_kind'] for claim in resources if claim['state'] == 'BOUND'}
        == ATTACHMENT_RESOURCE_KINDS,
        RESOURCE,
    )
    for recorded in subject['helpers']:
        observed = helper_observation(recorded, catalog)
        require(
            observed['state'] == 'OBSERVED'
            and all(
                unit['state'] in ('ABSENT_OBSERVED', 'QUIET_OBSERVED') for unit in observed['units']
            ),
            RESOURCE,
        )
    require(
        stopped == observed_stopped(native, environment, lock)
        and observed_assignment(environment, candidate, observe_workspace) == (assignment, head)
        and entry['verify_program'](environment.project) == row['program_source'],
        RESOURCE,
    )
    return stopped['control_sha256']


def archive_environment(catalog, registry, args, entry, launcher):
    identifier = args.archive_operation_id
    require(os.geteuid() == 0 and uuid_value(identifier), INVALID)
    area = catalog.directory / 'observations'

    def invoke(action, body):
        return invoke_observer(
            registry.uid,
            registry.gid,
            manager_command(action, args, launcher),
            area,
            input_bytes=canonical(body),
        )

    original = invoke('_archive-subject', {'operation_id': identifier})
    if 'receipt' in original:
        return original['receipt']
    subject = original['subject']
    require(subject['operation_id'] == identifier, RESOURCE)
    row = subject['environment']
    reference, pin = (decoded(row['configuration_ref'])[key] for key in ('candidate_ref', 'sha256'))
    candidate = catalog.candidate(reference, pin)
    environment = candidate_environment(candidate, args.sha256)
    require(
        row['host_id'] == catalog.scope['host_id']
        and public_facts(environment) == registered_subject(row),
        RESOURCE,
    )
    environment.check_hold(offline=True)
    native = NativeEnvironmentFiles(args.root)
    boot, started = machine_clock()
    with environment.lock(native) as lock:
        control = verified_archive_host(catalog, args, entry, subject, environment, lock, native)
        observed_boot, elapsed = machine_clock()
        require(boot == observed_boot and elapsed >= started, RESOURCE)
        proof = {
            'format_version': 1,
            **catalog.scope,
            'status': PHYSICAL_ARCHIVE,
            'operation_id': identifier,
            'subject_sha256': digest(canonical(subject)),
            'control_sha256': control,
            'boot_id': boot,
            'observed_at': now(),
            'observed_monotonic_ms': elapsed,
        }
        require_fresh({**proof, 'observed_monotonic_ms': started})
        publish_observation(catalog, archive_ref(identifier), proof)
        lock.assert_owned()
        return invoke(
            '_complete-archive',
            {'operation_id': identifier, 'proof_sha256': digest(canonical(proof))},
        )
