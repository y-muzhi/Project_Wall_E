"""Append-only management receipts and atomic environment registration."""

import sqlite3
from contextlib import contextmanager
from pathlib import PurePosixPath
from uuid import uuid4

from backend.app.infrastructure.environment_files import (
    MAX_REVISION,
    EnvironmentFailure,
    canonical,
    decode,
    digest,
    exact,
    relative,
    require,
)
from backend.app.infrastructure.environment_installation import identity_record, uuid_value

from .attachment_observation import (
    ATTACHMENT_RESOURCE_KINDS,
    PATH_SCOPE,
    now,
    observe_for_attach,
    require_fresh,
)
from .delivery_evidence import prepare_delivery
from .operation_contract import (
    CONFLICT,
    DENIED,
    INVALID,
    MISSING,
    RELEASE_ACTIONS,
    RESOURCE,
    UNAVAILABLE,
    VERSION,
    attach_intent,
    delivery_intent,
    operation_request,
)
from .registry import REGISTRY_ERROR, read_registry, registry_version, verified_registry
from .registry_recovery_outcome import pending_operation_clause
from .registry_schema import SCHEMA_VERSION

KEY_CONFLICT = 'MANAGEMENT_KEY_CONFLICT'
MANAGEMENT_NOT_READY = 'MANAGEMENT_NOT_READY'


def stored(value):
    return canonical(value).decode('utf-8')


def decoded(value):
    return decode(value.encode('utf-8'), REGISTRY_ERROR)


@contextmanager
def mutation(connection, lock):
    lock.assert_owned()
    connection.execute('BEGIN IMMEDIATE')
    try:
        yield
        lock.assert_owned()
    except BaseException:
        if connection.in_transaction:
            connection.execute('ROLLBACK')
        raise
    try:
        connection.execute('COMMIT')
    except sqlite3.Error as error:
        raise EnvironmentFailure(MANAGEMENT_NOT_READY, uncertain=True) from error


def operation_by_key(connection, generation, request_key):
    return connection.execute(
        'SELECT * FROM management_operations WHERE registry_generation = ? AND request_key = ?',
        (generation, request_key),
    ).fetchone()


def reject_historical_key(connection, generation, key, *, control=False):
    if registry_version(connection) == SCHEMA_VERSION:
        return
    prior_generations = (
        'SELECT registry_generation FROM registry_generations WHERE registry_generation != ?'
    )
    if control:
        query = (
            'SELECT 1 FROM management_controls '
            f'WHERE registry_generation IN ({prior_generations}) AND control_key = ? LIMIT 1'
        )
    else:
        query = (
            'SELECT 1 FROM management_operations '
            f'WHERE registry_generation IN ({prior_generations}) AND request_key = ? LIMIT 1'
        )
    require(connection.execute(query, (generation, key)).fetchone() is None, KEY_CONFLICT)


def environment_row(connection, environment_id):
    return connection.execute(
        'SELECT * FROM managed_environments WHERE environment_id = ?', (environment_id,)
    ).fetchone()


def may_read_environment(principal, row):
    return (
        principal.role == 'MANAGER'
        or row['environment_id'] in principal.visible
        or (principal.role == 'DEVELOPER' and principal.id == row['writer_principal'])
    )


def may_read_operation(connection, principal, operation):
    if operation['principal'] == principal.id and operation['original_read_allowed']:
        return True
    row = environment_row(connection, operation['environment_id'])
    return row is not None and may_read_environment(principal, row)


def operation_summary(operation):
    details = {
        key: operation[key]
        for key in (
            'operation_id',
            'request_key',
            'action',
            'environment_id',
            'status',
            'revision',
            'created_at',
            'intent_sha256',
        )
    }
    return {
        **details,
        'cancel_requested': bool(operation['cancel_requested']),
        'submitted_by': operation['principal'],
    }


def operation_result(connection, operation):
    steps = connection.execute(
        'SELECT ordinal, step_kind, status, result_json FROM management_steps '
        'WHERE operation_id = ? ORDER BY ordinal',
        (operation['operation_id'],),
    ).fetchall()
    return {
        'operation': operation_summary(operation),
        'steps': [
            {
                'ordinal': step['ordinal'],
                'kind': step['step_kind'],
                'status': step['status'],
                'result': decoded(step['result_json']) if step['result_json'] else None,
            }
            for step in steps
        ],
    }


def original_result(connection, generation, principal, key, intent=None):
    operation = operation_by_key(connection, generation, key)
    if operation is None:
        return None
    require(may_read_operation(connection, principal, operation), DENIED)
    if intent is not None:
        require(operation['principal'] == principal.id, DENIED)
        require(operation['intent_json'] == stored(intent), KEY_CONFLICT)
    return operation_result(connection, operation)


def conflicting_action(connection, environment_id):
    existing = connection.execute(
        'SELECT 1 FROM management_operations AS op WHERE op.environment_id = ? AND '
        + pending_operation_clause(connection),
        (environment_id,),
    ).fetchone()
    return existing is not None


def require_no_conflicting_action(connection, environment_id):
    require(not conflicting_action(connection, environment_id), CONFLICT)


def insert_operation(
    connection,
    generation,
    request_key,
    principal,
    intent,
    environment_id,
    now_at,
    *,
    status='SUCCEEDED',
    operation_id=None,
):
    operation = str(uuid4()) if operation_id is None else operation_id
    require(uuid_value(operation), INVALID)
    raw = stored(intent)
    connection.execute(
        'INSERT INTO management_operations (operation_id, registry_generation, request_key, principal, '
        'original_read_allowed, action, environment_id, expected_record_version, expected_assignment_generation, '
        'intent_version, intent_sha256, intent_json, status, revision, cancel_requested, created_at) '
        'VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, 1, ?, ?, ?, 1, 0, ?)',
        (
            operation,
            generation,
            request_key,
            principal.id,
            intent['action'],
            environment_id,
            intent.get('expected_record_version'),
            intent.get('expected_assignment_generation'),
            digest(raw.encode('utf-8')),
            raw,
            status,
            now_at,
        ),
    )
    return operation


def insert_step(connection, operation, kind, result, *, status='SUCCEEDED'):
    connection.execute(
        'INSERT INTO management_steps (operation_id, ordinal, step_kind, status, result_json) '
        'VALUES (?, 1, ?, ?, ?)',
        (operation, kind, status, stored(result) if result is not None else None),
    )


def validate_claim(claim):
    exact(claim, ('kind', 'scope', 'locator', 'object_identity'), RESOURCE)
    require(
        all(type(claim[key]) is str and claim[key] for key in ('kind', 'scope', 'locator')),
        RESOURCE,
    )
    if claim['scope'] == PATH_SCOPE:
        relative(claim['locator'], RESOURCE)
    if claim['object_identity'] is not None:
        identity_record(claim['object_identity'], RESOURCE)


def path_overlap(left, right):
    a, b = PurePosixPath(left), PurePosixPath(right)
    return a.is_relative_to(b) or b.is_relative_to(a)


def unclaimed(connection, environment_id, claims):
    require(type(claims) is list and claims, RESOURCE)
    current = connection.execute(
        'SELECT * FROM resource_claims WHERE released_at IS NULL AND quota IS NULL'
    ).fetchall()
    fresh = []
    seen = set()
    for claim in claims:
        validate_claim(claim)
        scope, locator = claim['scope'], claim['locator']
        key = claim['kind'], scope, locator
        require(key not in seen, RESOURCE)
        seen.add(key)
        known = False
        for row in current:
            if row['scope_ref'] != scope:
                continue
            same_locator = row['locator'] == locator
            present = decoded(row['identity_json']) if row['identity_json'] else None
            same_object = present is not None and present == claim['object_identity']
            if row['environment_id'] == environment_id:
                if row['kind'] == claim['kind'] and same_locator:
                    require(present == claim['object_identity'], RESOURCE)
                    known = True
                continue
            overlaps = scope == PATH_SCOPE and path_overlap(row['locator'], locator)
            require(not (same_locator or same_object or overlaps), CONFLICT)
        if not known:
            fresh.append(claim)
    return fresh


def register_resources(connection, environment_id, operation, claims):
    for claim in claims:
        connection.execute(
            'INSERT INTO resource_claims (resource_id, environment_id, operation_id, kind, scope_ref, '
            'locator, identity_json) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (
                str(uuid4()),
                environment_id,
                operation,
                claim['kind'],
                claim['scope'],
                claim['locator'],
                stored(claim['object_identity']) if claim['object_identity'] is not None else None,
            ),
        )


def prepare_attachment(catalog, principal, intent, runtime_sha):
    require(principal.role == 'MANAGER', DENIED)
    candidate = catalog.candidate(intent['candidate_ref'], intent['expected_candidate_sha256'])
    owner = catalog.access(candidate['owner_principal'])
    require(owner.role in ('MANAGER', 'DEVELOPER'), DENIED)
    proof = observe_for_attach(catalog, intent, candidate, runtime_sha)
    return candidate, proof


def attachment_claims(connection, intent, candidate, proof):
    environment_id = proof['environment_id']
    previous = environment_row(connection, environment_id)
    included = intent.get('environment_id')
    if included is None:
        require(previous is None, CONFLICT)
    else:
        require(included == environment_id and previous is not None, VERSION)
        require(
            previous['record_version'] == intent['expected_record_version']
            and previous['registration_state'] == 'ARCHIVED'
            and previous['assignment_control_state'] == 'OPEN'
            and previous['configuration_sha256'] == proof['configuration_sha256']
            and previous['task_id'] == candidate['task_id']
            and previous['writer_principal'] == candidate['owner_principal']
            and previous['purpose'] == proof['purpose']
            and previous['host_id'] == proof['host_id']
            and previous['program_source'] == proof['program_sha256']
            and previous['profile_ref'] == candidate['profile_ref'],
            VERSION,
        )
        work = decoded(previous['work_package_json'])
        require(
            all(
                work[field] == proof[field]
                for field in ('repository_ref', 'branch', 'data_generation', 'deployment_id')
            ),
            RESOURCE,
        )
        require(
            type(proof['claims']) is list
            and len(proof['claims']) == len(ATTACHMENT_RESOURCE_KINDS)
            and {claim['kind'] for claim in proof['claims']} == ATTACHMENT_RESOURCE_KINDS,
            RESOURCE,
        )
    fresh = unclaimed(connection, environment_id, proof['claims'])
    require(previous is None or not fresh, RESOURCE)
    return previous, fresh


def save_attachment(connection, generation, principal, key, intent, candidate, proof):
    require_fresh(proof)
    environment_id = proof['environment_id']
    require_no_conflicting_action(connection, environment_id)
    previous, claims = attachment_claims(connection, intent, candidate, proof)
    other_task = connection.execute(
        'SELECT 1 FROM managed_environments WHERE task_id = ? AND environment_id <> ?',
        (candidate['task_id'], environment_id),
    ).fetchone()
    require(other_task is None, CONFLICT)
    attachment = {
        key: candidate[key] for key in ('goal', 'scope', 'checks', 'owner_label', 'baseline_commit')
    }
    attachment.update(
        repository_ref=proof['repository_ref'],
        branch=proof['branch'],
        data_generation=proof['data_generation'],
        deployment_id=proof['deployment_id'],
    )
    configuration = stored(
        {'candidate_ref': intent['candidate_ref'], 'sha256': intent['expected_candidate_sha256']}
    )
    new_version = 1 if previous is None else previous['record_version'] + 1
    require(new_version <= MAX_REVISION, VERSION)
    assignment = 1 if previous is None else previous['assignment_generation']
    observed = now()
    if previous is None:
        connection.execute(
            'INSERT INTO managed_environments (environment_id, purpose, display_name, host_id, '
            'record_version, assignment_generation, registration_state, preparation_state, '
            'configuration_sha256, configuration_ref, program_source, profile_ref, task_id, '
            'work_package_json, writer_principal, assignment_control_state, fence_operation_id) '
            "VALUES (?, ?, ?, ?, 1, 1, 'ACTIVE', 'PREPARED', ?, ?, ?, ?, ?, ?, ?, 'OPEN', NULL)",
            (
                environment_id,
                proof['purpose'],
                candidate['display_name'],
                proof['host_id'],
                proof['configuration_sha256'],
                configuration,
                proof['program_sha256'],
                candidate['profile_ref'],
                candidate['task_id'],
                stored(attachment),
                candidate['owner_principal'],
            ),
        )
    else:
        change = connection.execute(
            "UPDATE managed_environments SET record_version = ?, registration_state = 'ACTIVE', "
            "preparation_state = 'PREPARED', configuration_ref = ? WHERE environment_id = ? AND record_version = ?",
            (new_version, configuration, environment_id, previous['record_version']),
        )
        require(change.rowcount == 1, VERSION)
    operation = insert_operation(
        connection, generation, key, principal, intent, environment_id, observed
    )
    register_resources(connection, environment_id, operation, claims)
    receipt = {
        'record_version': new_version,
        'assignment_generation': assignment,
        'environment_id': environment_id,
        'purpose': proof['purpose'],
        'data_generation': proof['data_generation'],
        'configuration_sha256': proof['configuration_sha256'],
        'worktree_evidence_sha256': proof['worktree_evidence_sha256'],
        'proof_id': proof['proof_id'],
        'observed_at': proof['observed_at'],
        'operation_committed_at': observed,
        'preparation_state': 'PREPARED',
        'runtime_state': 'UNKNOWN',
    }
    insert_step(connection, operation, 'ATTACH_REGISTERED', receipt)


def delivery_subject(connection, principal, intent):
    row = environment_row(connection, intent['environment_id'])
    require(
        row is not None
        and principal.role in ('MANAGER', 'DEVELOPER')
        and row['writer_principal'] == principal.id,
        DENIED,
    )
    require(
        row['registration_state'] == 'ACTIVE'
        and row['preparation_state'] == 'PREPARED'
        and row['assignment_control_state'] == 'OPEN'
        and row['record_version'] == intent['expected_record_version']
        and row['assignment_generation'] == intent['expected_assignment_generation'],
        VERSION,
    )
    require(
        (row['purpose'] == 'INTEGRATION' and 'source_environment_ids' in intent)
        or (row['purpose'] == 'DEVELOPMENT' and 'source_environment_ids' not in intent),
        INVALID,
    )
    return row


def verify_workspace_claim(connection, row, proof, selected):
    work = decoded(row['work_package_json'])
    require(
        proof['repository_ref'] == work['repository_ref']
        and selected['branch'] == work['branch']
        and selected['purpose'] == row['purpose'],
        RESOURCE,
    )
    original = connection.execute(
        'SELECT locator, identity_json FROM resource_claims WHERE environment_id = ? '
        "AND kind = 'WORKTREE' AND scope_ref = ? AND released_at IS NULL",
        (row['environment_id'], PATH_SCOPE),
    ).fetchall()
    require(
        len(original) == 1
        and original[0]['locator'] == selected['worktree_locator']
        and original[0]['identity_json'] == stored(selected['worktree_identity']),
        RESOURCE,
    )


def integrated_sources(connection, principal, intent, proof):
    refs = []
    environment_ids = intent.get('source_environment_ids', ())
    commits = intent.get('source_commits', ())
    for environment, selected in zip(environment_ids, commits, strict=True):
        row = environment_row(connection, environment)
        require(row is not None and may_read_environment(principal, row), DENIED)
        require(row['purpose'] == 'DEVELOPMENT', RESOURCE)
        verify_workspace_claim(connection, row, proof, proof['commits'][environment])
        original = connection.execute(
            'SELECT snapshot.operation_id, snapshot.evidence_json FROM delivery_snapshots AS snapshot '
            'JOIN management_operations AS operation ON snapshot.operation_id = operation.operation_id '
            "WHERE snapshot.environment_id = ? AND snapshot.commit_oid = ? AND operation.status = 'SUCCEEDED' "
            'ORDER BY snapshot.verified_at DESC, snapshot.operation_id DESC LIMIT 1',
            (environment, selected),
        ).fetchone()
        require(original is not None, RESOURCE)
        receipt = decoded(original['evidence_json'])
        require(
            receipt['repository_ref'] == proof['repository_ref']
            and receipt['tree'] == proof['commits'][environment]['tree'],
            RESOURCE,
        )
        refs.append(
            {
                'environment_id': environment,
                'commit': selected,
                'delivery_operation_id': original['operation_id'],
            }
        )
    return refs


def save_delivery(connection, generation, principal, key, intent, evidence):
    proof, resources, checks = evidence
    require_fresh(proof)
    row = delivery_subject(connection, principal, intent)
    environment = row['environment_id']
    require_no_conflicting_action(connection, environment)
    observed = proof['commits'][environment]
    verify_workspace_claim(connection, row, proof, observed)
    sources = integrated_sources(connection, principal, intent, proof)
    next_version = row['record_version'] + 1
    require(next_version <= MAX_REVISION, VERSION)
    updated = connection.execute(
        'UPDATE managed_environments SET record_version = ? '
        'WHERE environment_id = ? AND record_version = ? AND assignment_generation = ?',
        (next_version, environment, row['record_version'], row['assignment_generation']),
    )
    require(updated.rowcount == 1, VERSION)
    now_at = now()
    operation = insert_operation(
        connection, generation, key, principal, intent, environment, now_at
    )
    receipt = {
        'environment_id': environment,
        'repository_ref': proof['repository_ref'],
        'record_version': next_version,
        'assignment_generation': row['assignment_generation'],
        'commit': intent['commit'],
        'tree': observed['tree'],
        'branch': observed['branch'],
        'proof_id': proof['proof_id'],
        'workspace_evidence_sha256': proof['workspace_evidence_sha256'],
        'resource_refs': resources,
        'check_refs': checks,
        'manual_notes': intent['manual_notes'],
        'not_covered': intent['not_covered'],
        'source_deliveries': sources,
        'submitted_by': principal.id,
        'verified_at': now_at,
    }
    connection.execute(
        'INSERT INTO delivery_snapshots (operation_id, environment_id, assignment_generation, '
        'commit_oid, evidence_json, submitted_by, verified_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (
            operation,
            environment,
            row['assignment_generation'],
            intent['commit'],
            stored(receipt),
            principal.id,
            now_at,
        ),
    )
    insert_step(connection, operation, 'DELIVERY_REGISTERED', receipt)


def execute_operation(native, installation, catalog, request, runtime_sha):
    """Return the original receipt and whether the request already existed."""
    principal, key, raw = operation_request(request, catalog)
    action = raw.get('action')
    require(type(action) is str, INVALID)
    if action in ('CONTROL', 'LOOKUP_CONTROL'):
        from .runtime_controls import control_input

        control_input(raw)
    elif action in ('LOOKUP', 'RECONCILE_RUNTIME'):
        exact(raw, ('action',), INVALID)
    elif action == 'ATTACH':
        attach_intent(raw)
    elif action == 'REGISTER_DELIVERY':
        delivery_intent(raw)
    elif action in RELEASE_ACTIONS:
        from .release_operations import release_input

        release_input(raw, confirmation=True)
        require(principal.role == 'MANAGER', DENIED)
    elif action == 'BACKUP':
        from .backup_operations import backup_input

        backup_input(raw, confirmed=True)
        require(principal.role == 'MANAGER', DENIED)
    elif action == 'RESTORE':
        from .restore_operations import restore_input

        restore_input(raw, confirmed=True)
        require(principal.role == 'MANAGER', DENIED)
    elif action == 'ARCHIVE':
        from .environment_archive import archive_intent

        archive_intent(raw)
        require(principal.role == 'MANAGER', DENIED)
    elif action in ('START', 'STOP'):
        from .lifecycle_operations import lifecycle_intent

        lifecycle_intent(raw)
    else:
        raise EnvironmentFailure(UNAVAILABLE)
    generation = installation.registry_generation
    if action == 'LOOKUP_CONTROL':
        from .runtime_controls import lookup_control

        with read_registry(native, installation, runtime_sha) as connection:
            return lookup_control(connection, catalog, principal, key, raw), True
    with verified_registry(native, installation, writable=action != 'LOOKUP') as (connection, lock):
        if action == 'CONTROL':
            from .runtime_controls import control_operation

            return control_operation(connection, lock, catalog, principal, key, raw)
        if action == 'RECONCILE_RUNTIME':
            from .lifecycle_operations import reconcile_runtime

            return reconcile_runtime(connection, lock, catalog, generation, principal, key), True
        result = original_result(
            connection, generation, principal, key, None if action == 'LOOKUP' else raw
        )
        if result is not None:
            return result, True
        if action == 'LOOKUP':
            raise EnvironmentFailure(MISSING)
        reject_historical_key(connection, generation, key)
        if action in RELEASE_ACTIONS:
            from .release_operations import accept_release

            return accept_release(connection, lock, catalog, principal, key, raw), False
        if action == 'BACKUP':
            from .backup_operations import accept_backup

            return accept_backup(connection, lock, catalog, principal, key, raw), False
        if action == 'RESTORE':
            from .restore_operations import accept_restore

            return accept_restore(
                connection, lock, catalog, principal, key, raw, runtime_sha
            ), False
        if action == 'ARCHIVE':
            from .environment_archive import accept_archive

            return accept_archive(connection, lock, catalog, principal, key, raw), False
        if action in ('START', 'STOP'):
            from .lifecycle_operations import accept_runtime

            return accept_runtime(connection, lock, catalog, generation, principal, key, raw), False
        if action == 'ATTACH':
            candidate, proof = prepare_attachment(catalog, principal, raw, runtime_sha)
            with mutation(connection, lock):
                save_attachment(connection, generation, principal, key, raw, candidate, proof)
                result = original_result(connection, generation, principal, key, raw)
            return result, False
        delivery_subject(connection, principal, raw)
        evidence = prepare_delivery(catalog, principal, key, raw)
        with mutation(connection, lock):
            save_delivery(connection, generation, principal, key, raw, evidence)
            result = original_result(connection, generation, principal, key, raw)
        return result, False


def run_operation(native, installation, catalog, request, runtime_sha):
    result, _existing = execute_operation(native, installation, catalog, request, runtime_sha)
    return result
