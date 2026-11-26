"""Require specific preserved facts before any recovery disposition may be written."""

import sqlite3
from contextlib import closing, nullcontext
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.infrastructure.environment_files import EnvironmentFailure, canonical, digest
from backend.app.management.registry_schema import STATEMENTS


@pytest.fixture
def undispatched_module():
    pytest.importorskip('fcntl')
    from backend.app.management import registry_recovery_undispatched

    return registry_recovery_undispatched


@pytest.fixture
def original_start():
    generation, environment, operation = (str(uuid4()) for _ in range(3))
    created = '2026-11-22T08:00:00.000Z'
    intent = {
        'action': 'START',
        'environment_id': environment,
        'expected_record_version': 4,
        'expected_assignment_generation': 1,
        'expected_configuration_sha256': 'a' * 64,
    }
    raw = canonical(intent)
    with closing(sqlite3.connect(':memory:')) as connection:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.row_factory = sqlite3.Row
        for statement in STATEMENTS:
            connection.execute(statement)
        connection.execute(
            'INSERT INTO manager_state VALUES (1,1,?,?,?,?)',
            (str(uuid4()), str(uuid4()), generation, created),
        )
        connection.execute(
            'INSERT INTO managed_environments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (
                environment,
                'DEVELOPMENT',
                'Fixture',
                str(uuid4()),
                4,
                1,
                'ACTIVE',
                'PREPARED',
                'a' * 64,
                None,
                None,
                'standard',
                str(uuid4()),
                '{}',
                'owner',
                'OPEN',
                None,
            ),
        )
        connection.execute(
            'INSERT INTO management_operations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (
                operation,
                generation,
                str(uuid4()),
                'owner',
                1,
                'START',
                environment,
                4,
                1,
                1,
                digest(raw),
                raw.decode(),
                'WAITING_CAPACITY',
                1,
                0,
                created,
            ),
        )
        connection.execute(
            'INSERT INTO management_steps VALUES (?,1,?,?,?,?,?)',
            (
                operation,
                'RUNTIME_STARTED',
                'PLANNED',
                None,
                None,
                canonical({'observed_at': created, 'missing': ['memory_bytes']}).decode(),
            ),
        )
        policy = {
            'operation_id': operation,
            'source_registry_generation': generation,
            'source_revision': 1,
            'source_intent_sha256': digest(raw),
        }
        yield connection, policy, environment


def test_undispatched_proof_binds_original_facts(undispatched_module, original_start):
    connection, policy, environment = original_start
    evidence = undispatched_module.undispatched_start_evidence(connection, policy)
    assert evidence == undispatched_module.undispatched_start_evidence(connection, policy)
    assert evidence['disposition'] == 'UNDISPATCHED_CANCELLED'
    assert evidence['operation_id'] == policy['operation_id']
    assert evidence['environment_id'] == environment
    assert evidence['original_status'] == 'WAITING_CAPACITY'
    assert 'intent' not in evidence
    assert (
        connection.execute('SELECT status FROM management_operations').fetchone()[0]
        == 'WAITING_CAPACITY'
    )


@pytest.mark.parametrize(
    'conflict',
    (
        "UPDATE management_operations SET status='UNKNOWN'",
        'UPDATE management_operations SET cancel_requested=1',
        "UPDATE management_steps SET executor_ref='SYSTEMD_ORDINARY_RUNTIME'",
        "UPDATE management_steps SET external_identity_json='{}'",
        "UPDATE management_steps SET result_json='{}'",
        'UPDATE managed_environments SET record_version=5',
        (
            "UPDATE managed_environments SET assignment_control_state='FENCED', fence_operation_id="
            '(SELECT operation_id FROM management_operations)'
        ),
    ),
)
def test_undispatched_proof_rejects_conflicting_state(
    undispatched_module, original_start, conflict
):
    connection, policy, _ = original_start
    connection.execute(conflict)
    with pytest.raises(EnvironmentFailure):
        undispatched_module.undispatched_start_evidence(connection, policy)


def test_even_a_released_resource_conflicts_with_undispatched_proof(
    undispatched_module, original_start
):
    connection, policy, environment = original_start
    connection.execute(
        'INSERT INTO resource_claims VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            str(uuid4()),
            environment,
            policy['operation_id'],
            'MEMORY',
            'HOST',
            'memory',
            None,
            10,
            '2026-11-22T08:00:02.000Z',
            '{}',
        ),
    )
    with pytest.raises(EnvironmentFailure):
        undispatched_module.undispatched_start_evidence(connection, policy)


@pytest.fixture
def original_backup(original_start, tmp_path, monkeypatch):
    pytest.importorskip('fcntl')
    from backend.app.management import operation_contract, registry_recovery_backup
    from backend.app.management.backup_capture import CAPTURED, EXECUTIONS, capture_grant
    from backend.app.management.backup_completion import COMPLETE, COMPLETE_STATUS
    from backend.app.management.backup_operations import ASSETS
    from backend.app.management.operation_contract import Catalog, Principal

    connection, binding, environment = original_start
    operation = binding['operation_id']
    manager = connection.execute('SELECT * FROM manager_state').fetchone()
    created = '2026-11-22T08:00:00.000Z'
    scope = {key: manager[key] for key in ('manager_id', 'host_id', 'registry_generation')}
    plan_id, backup_id, reference = (str(uuid4()) for _ in range(3))
    strategy = {
        'format_version': 1,
        **scope,
        'backup_policy_ref': reference,
        'environment_id': environment,
        'minimum_verification': 'LOCAL_VERIFIED',
        'assets': list(ASSETS),
        'max_database_bytes': 32768,
        'max_audit_files': 8,
        'max_audit_bytes': 8192,
    }
    pins = {reference: digest(canonical(strategy))}
    catalog = Catalog(
        directory=tmp_path,
        scope=scope,
        principals={'owner': Principal('owner', 'MANAGER', ())},
        candidates={},
        resources={},
        checks={},
        registry_anchor_sha256='a' * 64,
        capacity_policy_sha256=None,
        release_candidates={},
        backup_policies=pins,
    )
    path = tmp_path / 'backup-policies' / (reference + '.json')
    path.parent.mkdir()
    path.write_bytes(canonical(strategy))
    monkeypatch.setattr(operation_contract, 'read_protected', lambda path: path.read_bytes())
    source = {
        'data_generation': str(uuid4()),
        'deployment_id': str(uuid4()),
        'control_revision': 2,
        'operation_id': str(uuid4()),
        'control_sha256': '2' * 64,
        'program_sha256': '3' * 64,
        'configuration_sha256': 'a' * 64,
        'installation_sha256': '4' * 64,
    }
    request = {
        'environment_id': environment,
        'expected_record_version': 4,
        'expected_assignment_generation': 1,
        'backup_policy_ref': reference,
        'after_completion': 'KEEP_STOPPED',
    }
    preview = {
        'kind': 'BACKUP',
        **request,
        'plan_id': plan_id,
        'expires_at': created,
        'source': source,
        'source_attachment': {'candidate_ref': str(uuid4()), 'sha256': '5' * 64},
        'completion': 'KEEP_STOPPED',
        'backup_id': backup_id,
        'backup_policy_sha256': pins[reference],
        'minimum_verification': strategy['minimum_verification'],
        'assets': strategy['assets'],
    }
    plan_pin = digest(canonical(preview))
    raw = canonical({'action': 'BACKUP', **request, 'plan_id': plan_id, 'plan_sha256': plan_pin})
    binding = {**binding, 'source_revision': 2, 'source_intent_sha256': digest(raw)}
    connection.execute(
        "UPDATE management_operations SET action='BACKUP', status='RUNNING', revision=2, "
        'intent_sha256=?,intent_json=?',
        (binding['source_intent_sha256'], raw.decode()),
    )
    connection.execute(
        'INSERT INTO management_plans VALUES (?,?,?,?,?,?,?,?,?,?)',
        (
            plan_id,
            environment,
            'owner',
            'BACKUP',
            4,
            1,
            plan_pin,
            canonical(preview).decode(),
            created,
            operation,
        ),
    )
    grant = capture_grant(
        catalog, {'operation_id': operation, 'environment_id': environment}, preview, strategy
    )
    connection.execute(
        "UPDATE management_steps SET step_kind='BACKUP_RECOVERY_POINT',status='DISPATCHING', "
        "executor_ref='NATIVE_DATABASE_BACKUP',external_identity_json=?,result_json=NULL",
        (canonical({'capture': grant}).decode(),),
    )
    artifacts = tmp_path / EXECUTIONS / operation
    artifacts.mkdir(parents=True)
    capture = {
        'format_version': 1,
        'status': 'MANAGED_BACKUP_CAPTURED',
        'operation_id': operation,
        'environment_id': environment,
        'backup_id': backup_id,
        'data_generation': source['data_generation'],
        'deployment_id': source['deployment_id'],
        'control_revision': source['control_revision'],
        'cutoff_at': created,
        'grant_sha256': digest(canonical(grant)),
        'capture_policy_sha256': '6' * 64,
        'capture_receipt_sha256': '7' * 64,
        'database_sha256': '8' * 64,
        'database_bytes': 8192,
    }
    (artifacts / CAPTURED).write_bytes(canonical(capture))
    point = {
        'backup_id': backup_id,
        'source_environment_id': environment,
        'source_data_generation': source['data_generation'],
        'source_deployment_id': source['deployment_id'],
        'source_control_revision': source['control_revision'],
        'cutoff_at': created,
        'backup_manifest_sha256': '9' * 64,
        'database_bytes': capture['database_bytes'],
        'logical_content_sha256': 'b' * 64,
        'count_audit_state': 'EMPTY',
        'program_sha256': source['program_sha256'],
        'configuration_sha256': source['configuration_sha256'],
        'verification_status': 'LOCAL_VERIFIED',
        'local_snapshot_retrieval': None,
        'local_verification': {
            'verification_id': str(uuid4()),
            'verified_at': created,
            'verified_scopes': ['DOCUMENT_CONTENT', 'DOCUMENT_HISTORY'],
        },
    }
    complete = artifacts / COMPLETE
    complete.write_bytes(
        canonical(
            {
                'format_version': 1,
                'status': COMPLETE_STATUS,
                **scope,
                'operation_id': operation,
                'grant_sha256': capture['grant_sha256'],
                'capture_sha256': digest(canonical(capture)),
                'result_policy_sha256': 'c' * 64,
                'observed_at': created,
                'point': point,
            }
        )
    )
    result = {'environment_id': environment, 'observed_at': created, 'point': point}

    def verify():
        return registry_recovery_backup.completed_backup_evidence(connection, catalog, binding)

    return connection, verify, complete, result


@pytest.mark.parametrize(
    ('operation_state', 'step_state'),
    (('RUNNING', 'DISPATCHING'), ('UNKNOWN', 'UNKNOWN'), ('SUCCEEDED', 'SUCCEEDED')),
)
def test_original_backup_proves_exact_completed_effect(
    original_backup, operation_state, step_state
):
    connection, verify, _, result = original_backup
    connection.execute('UPDATE management_operations SET status=?', (operation_state,))
    encoded = canonical(result).decode() if operation_state == 'SUCCEEDED' else None
    connection.execute('UPDATE management_steps SET status=?,result_json=?', (step_state, encoded))
    evidence = verify()
    assert evidence['disposition'] == 'BACKUP_COMPLETED'
    assert evidence['original_status'] == operation_state
    assert evidence['step_status'] == step_state
    assert evidence['backup_id'] == result['point']['backup_id']
    assert evidence['completion_result_sha256'] == digest(canonical(result))
    assert (
        connection.execute('SELECT status FROM management_operations').fetchone()[0]
        == operation_state
    )


@pytest.mark.parametrize(
    'conflict',
    (
        "UPDATE management_steps SET executor_ref='ANOTHER_EXECUTOR'",
        "UPDATE management_steps SET external_identity_json='{}'",
        'UPDATE management_plans SET execution_operation_id=NULL',
        'UPDATE management_plans SET record_version=5',
        'UPDATE management_operations SET cancel_requested=1',
    ),
)
def test_original_backup_does_not_certify_a_different_intent(original_backup, conflict):
    connection, verify, _, _ = original_backup
    connection.execute(conflict)
    with pytest.raises(EnvironmentFailure):
        verify()


def test_original_backup_requires_finished_external_evidence(original_backup):
    _, verify, complete, _ = original_backup
    complete.unlink()
    with pytest.raises(EnvironmentFailure):
        verify()


def test_already_succeeded_backup_must_agree_with_external_result(original_backup):
    connection, verify, _, result = original_backup
    connection.execute("UPDATE management_operations SET status='SUCCEEDED'")
    result['point']['logical_content_sha256'] = 'f' * 64
    connection.execute(
        "UPDATE management_steps SET status='SUCCEEDED',result_json=?",
        (canonical(result).decode(),),
    )
    with pytest.raises(EnvironmentFailure):
        verify()


@pytest.fixture
def original_stop(original_start, tmp_path, monkeypatch):
    pytest.importorskip('fcntl')
    from backend.app.management import operation_contract, runtime_stop
    from backend.app.management import registry_recovery_stop as stop_proof

    connection, binding, environment = original_start
    operation = binding['operation_id']
    source, run, proof = (str(uuid4()) for _ in range(3))
    created = '2026-11-22T08:00:00.000Z'
    manager = connection.execute('SELECT * FROM manager_state').fetchone()
    scope = {key: manager[key] for key in ('manager_id', 'host_id', 'registry_generation')}
    intent = {
        'action': 'STOP',
        'environment_id': environment,
        'expected_record_version': 4,
        'expected_assignment_generation': 1,
        'target': {'kind': 'RUN', 'run_id': run},
    }
    raw = canonical(intent)
    binding = {**binding, 'source_revision': 3, 'source_intent_sha256': digest(raw)}
    connection.execute(
        "UPDATE management_operations SET action='STOP',status='SUCCEEDED',revision=3,"
        'intent_sha256=?,intent_json=?',
        (digest(raw), raw.decode()),
    )
    source_raw = canonical(
        {
            'action': 'START',
            'environment_id': environment,
            'expected_record_version': 4,
            'expected_assignment_generation': 1,
            'expected_configuration_sha256': 'a' * 64,
        }
    )
    connection.execute(
        'INSERT INTO management_operations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (
            source,
            scope['registry_generation'],
            str(uuid4()),
            'owner',
            1,
            'START',
            environment,
            4,
            1,
            1,
            digest(source_raw),
            source_raw.decode(),
            'SUCCEEDED',
            2,
            0,
            created,
        ),
    )
    connection.execute(
        'INSERT INTO management_steps VALUES (?,1,?,?,?,?,?)',
        (source, 'RUNTIME_STARTED', 'SUCCEEDED', None, None, canonical({'run_id': run}).decode()),
    )
    external = {'start_operation_id': source, 'run_id': run, 'policy_sha256': 'd' * 64}
    result = {
        'environment_id': environment,
        'run_id': run,
        'runtime_state': 'STOPPED',
        'observed_at': created,
        'proof_id': proof,
    }
    connection.execute(
        "UPDATE management_steps SET step_kind='RUNTIME_STOPPED',status='SUCCEEDED',"
        "executor_ref='SYSTEMD_ORDINARY_RUNTIME',external_identity_json=?,result_json=? "
        'WHERE operation_id=?',
        (canonical(external).decode(), canonical(result).decode(), operation),
    )
    observed = tmp_path / 'observations'
    observed.mkdir()
    common = {
        'format_version': 1,
        **scope,
        'stop_operation_id': operation,
        'environment_id': environment,
        'run_id': run,
        'start_operation_id': source,
        'stop_policy_sha256': external['policy_sha256'],
        'runtime_policy_sha256': 'e' * 64,
    }
    record = observed / f'stop-{operation}.v1.json'
    claim = observed / f'stop-claim-{environment}-{run}.v1.json'
    claim.write_bytes(canonical(common))
    record.write_bytes(
        canonical(
            {
                **common,
                'state': 'STOPPED',
                'dispatch': 'DISPATCH_RECORDED',
                'recorded_at': created,
                'observation': {
                    'proof_id': proof,
                    'environment_id': environment,
                    'observed_at': created,
                    'state': 'STOPPED',
                    'reason_code': 'MANAGED_STOP_CONFIRMED',
                },
            }
        )
    )
    monkeypatch.setattr(operation_contract, 'read_protected', lambda path: path.read_bytes())
    monkeypatch.setattr(stop_proof, 'protected_directory', nullcontext)
    monkeypatch.setattr(
        runtime_stop, 'read_entry', lambda root, name, **_: (root / name).read_bytes()
    )
    catalog = SimpleNamespace(directory=tmp_path, scope=scope)

    def verify():
        evidence = stop_proof.completed_stop_evidence(connection, catalog, binding)
        return {**evidence, 'capacity': stop_proof.stop_capacity_evidence(connection, evidence)}

    return connection, verify, claim, external, environment, binding


def test_original_stop_requires_final_receipt_and_run_claim(original_stop):
    connection, verify, claim, external, environment, binding = original_stop
    evidence = verify()
    assert evidence['disposition'] == 'STOP_COMPLETED'
    assert evidence['start_operation_id'] == external['start_operation_id']
    assert evidence['run_id'] == external['run_id']
    assert evidence['environment_id'] == environment
    assert evidence['operation_id'] == binding['operation_id']
    assert (
        connection.execute(
            'SELECT status FROM management_operations WHERE operation_id=?',
            (binding['operation_id'],),
        ).fetchone()[0]
        == 'SUCCEEDED'
    )
    claim.unlink()
    with pytest.raises(EnvironmentFailure):
        verify()


def test_original_stop_does_not_certify_an_unreleased_capacity_reservation(original_stop):
    connection, verify, _, external, environment, _ = original_stop
    from backend.app.management.runtime_capacity import CLAIM_KIND, CLAIM_SCOPE

    connection.execute(
        'INSERT INTO resource_claims VALUES (?,?,?,?,?,?,?,?,?,?)',
        (
            str(uuid4()),
            environment,
            external['start_operation_id'],
            CLAIM_KIND,
            CLAIM_SCOPE,
            'memory_bytes',
            '{}',
            64,
            None,
            None,
        ),
    )
    with pytest.raises(EnvironmentFailure):
        verify()


@pytest.mark.parametrize(
    ('state', 'pid', 'empty', 'expected'),
    (
        ('ABSENT_OBSERVED', 0, True, None),
        ('QUIET_OBSERVED', 0, True, None),
        ('QUIET_OBSERVED', 0, False, 'ORIGINAL_STEP_UNRESOLVED'),
        ('QUIET_OBSERVED', 18, True, 'ORIGINAL_STEP_UNRESOLVED'),
        ('PRESENT_OBSERVED', 18, False, 'ORIGINAL_RUNTIME_UNVERIFIED'),
        ('UNKNOWN', None, None, 'ORIGINAL_STEP_UNRESOLVED'),
    ),
)
def test_stopped_original_unit_requires_a_fresh_empty_group(
    original_stop, state, pid, empty, expected
):
    from backend.app.management import registry_recovery_dispatch_review as review
    from backend.app.management.registry_recovery_stop import stopped_runtime_unit

    _, verify, _, external, environment, _ = original_stop
    evidence = verify()
    unit = stopped_runtime_unit(environment, external['start_operation_id'])
    row = {
        'environment_id': environment,
        'ordinal': 1,
        'original_status': 'SUCCEEDED',
        'step_kind': 'RUNTIME_STOPPED',
        'state': 'UNKNOWN' if state == 'UNKNOWN' else 'OBSERVED',
        'units': [{'unit': unit, 'state': state, 'main_pid': pid, 'cgroup_empty': empty}],
    }
    blocker = review.completed_effect_blocker(row, {'evidence': evidence})
    assert blocker == (None if expected is None else {'reason_code': expected, 'unit': unit})
    row['units'][0]['unit'] = stopped_runtime_unit(environment, str(uuid4()))
    with pytest.raises(EnvironmentFailure):
        review.completed_effect_blocker(row, {'evidence': evidence})


@pytest.mark.parametrize('last_status', ('ACCEPTED', 'UNKNOWN'))
def test_known_stop_can_release_only_the_preserved_group(original_stop, last_status):
    from backend.app.management import registry_recovery_stop as stop_proof
    from backend.app.management.runtime_capacity import CLAIM_KIND, CLAIM_SCOPE, MINIMUM

    connection, verify, _, external, environment, binding = original_stop
    owner = external['start_operation_id']
    operation = binding['operation_id']
    connection.execute(
        'UPDATE management_operations SET status=? WHERE operation_id=?', (last_status, operation)
    )
    if last_status == 'ACCEPTED':
        connection.execute(
            "UPDATE management_steps SET status='PLANNED',executor_ref=NULL,"
            'external_identity_json=NULL,result_json=NULL WHERE operation_id=?',
            (operation,),
        )
    else:
        connection.execute(
            "UPDATE management_steps SET status='UNKNOWN',result_json=NULL WHERE operation_id=?",
            (operation,),
        )
    capacity_binding = canonical(
        {'policy_sha256': '5' * 64, 'profile_ref': 'standard', 'configuration_sha256': 'a' * 64}
    ).decode()
    for locator, quota in MINIMUM.items():
        connection.execute(
            'INSERT INTO resource_claims VALUES (?,?,?,?,?,?,?,?,?,?)',
            (
                str(uuid4()),
                environment,
                owner,
                CLAIM_KIND,
                CLAIM_SCOPE,
                locator,
                capacity_binding,
                quota,
                None,
                None,
            ),
        )
    evidence = verify()
    assert evidence['capacity']['count'] == len(MINIMUM)
    connection.execute("UPDATE resource_claims SET quota=quota+1 WHERE locator='memory_bytes'")
    with pytest.raises(EnvironmentFailure):
        stop_proof.settle_stop_capacity(connection, evidence, recorded=False)
    connection.execute("UPDATE resource_claims SET quota=quota-1 WHERE locator='memory_bytes'")
    stop_proof.settle_stop_capacity(connection, evidence, recorded=False)
    released = connection.execute('SELECT released_at,release_json FROM resource_claims').fetchall()
    assert len(released) == len(MINIMUM)
    assert all(
        row[0]
        and row[1] == canonical({'stop_operation_id': operation, **evidence['completion']}).decode()
        for row in released
    )
    stop_proof.settle_stop_capacity(connection, evidence, recorded=True)
    connection.execute("UPDATE resource_claims SET release_json='{}' WHERE locator='memory_bytes'")
    with pytest.raises(EnvironmentFailure):
        stop_proof.settle_stop_capacity(connection, evidence, recorded=True)


def test_reserved_undispatched_start_requires_its_complete_original_binding(
    undispatched_module, original_start, tmp_path
):
    from backend.app.management.registry_recovery_capacity import settle_capacity
    from backend.app.management.runtime_capacity import MINIMUM, CapacityPolicy, reserve_capacity

    connection, policy, environment = original_start
    operation = policy['operation_id']
    connection.execute("UPDATE management_operations SET status='ACCEPTED'")
    connection.execute('UPDATE management_steps SET result_json=NULL')
    profile = {'profile_ref': 'standard', 'limits': MINIMUM}
    capacity_pin = 'b' * 64
    capacity = CapacityPolicy(capacity_pin, tmp_path, tmp_path, MINIMUM, {'DEVELOPMENT': profile})
    row = connection.execute('SELECT * FROM managed_environments').fetchone()
    reserve_capacity(connection, operation, capacity, row, lambda value: canonical(value).decode())
    scope = {'host_id': row['host_id']}
    catalog = SimpleNamespace(capacity_policy_sha256=capacity_pin, scope=scope)
    evidence = undispatched_module.reserved_start_evidence(connection, catalog, policy)
    measured = undispatched_module.reserved_start_capacity(connection, evidence)
    assert measured['count'] == len(MINIMUM)
    assert evidence['disposition'] == 'UNDISPATCHED_RESERVED_CANCELLED'
    published = {'recovery_operation_id': str(uuid4()), 'disposition': evidence['disposition']}
    foreign_host = SimpleNamespace(
        capacity_policy_sha256=capacity_pin, scope={'host_id': str(uuid4())}
    )
    with pytest.raises(EnvironmentFailure):
        undispatched_module.reserved_start_evidence(connection, foreign_host, policy)
    other_catalog = SimpleNamespace(capacity_policy_sha256='c' * 64, scope=scope)
    changed = undispatched_module.reserved_start_evidence(connection, other_catalog, policy)
    with pytest.raises(EnvironmentFailure):
        undispatched_module.reserved_start_capacity(connection, changed)
    connection.execute("UPDATE management_steps SET external_identity_json='{}'")
    with pytest.raises(EnvironmentFailure):
        undispatched_module.reserved_start_evidence(connection, catalog, policy)
    connection.execute('UPDATE management_steps SET external_identity_json=NULL')
    settle_capacity(connection, operation, environment, measured, published, recorded=False)
    settle_capacity(connection, operation, environment, measured, published, recorded=True)
    with pytest.raises(EnvironmentFailure):
        undispatched_module.reserved_start_capacity(connection, evidence)
    assert (
        connection.execute('SELECT status FROM management_operations').fetchone()[0] == 'ACCEPTED'
    )
