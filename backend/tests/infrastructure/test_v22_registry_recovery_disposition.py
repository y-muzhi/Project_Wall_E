"""Require specific preserved facts before any recovery disposition may be written."""

import sqlite3
from contextlib import closing
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
