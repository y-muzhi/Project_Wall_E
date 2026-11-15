"""Real original START receipts and the atomic instance step on isolated Schema 200."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from backend.app.code_tasks import task_start_basis, task_start_instance
from backend.app.code_tasks.task_instance_driver import (
    TaskInstanceDriver,
    TaskLaunchInstallation,
    _Owner,
)
from backend.app.code_tasks.task_model_ingress import ModelWindow, read_original_open_window
from backend.app.code_tasks.task_start_instance import ReadyInstanceEvidence, advance_start_instance
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import LaunchScope
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.shared.validation import strict_json_object
from backend.tests.code_tasks.test_task_start import (
    isolated_readiness,
    original_operation,
    start,
    stop,
)
from backend.tests.code_tasks.test_task_start_basis import prepare
from backend.tests.infrastructure.test_v20_command_http import package, service
from backend.tests.infrastructure.test_v20_windows_task_endpoints import _plan


@pytest.fixture
def original_instance(service, tmp_path, isolated_readiness):
    database, app, client = service
    runtime = app.state.walle_runtime
    with PrivatePackageGuard(create_private_package(tmp_path / 'instance-source')) as parent:
        task_id, _, _, key, receipt = prepare(database, app, client, parent)
        operation_id = receipt['operation_id']
        assert task_start_basis.advance_start_basis(runtime, parent, cancelled=lambda: False)
        # Deliberate isolated admission input. No production model or WFP checks are bypassed.
        with database.transaction(write=True) as connection:
            basis_at = connection.execute(
                'SELECT ended_at FROM code_operation_steps WHERE operation_id=? AND step_no=2',
                (operation_id,),
            ).fetchone()[0]
            report = canonical_input(
                {
                    'fixed_content_verified': True,
                    'capability_codes': [],
                    'system_config_clear': True,
                    'runtime_launch_admission': True,
                }
            )
            connection.execute(
                """UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,
                   started_at=?,ended_at=?,last_observed_at=? WHERE operation_id=? AND step_no=3""",
                (report, basis_at, basis_at, basis_at, operation_id),
            )
        yield database, runtime, client, parent, task_id, key, receipt


def _evidence(claim):
    running = {
        'process_state': 'RUNNING',
        'job_ref': 'a' * 32,
        'resource_ref': 'b' * 32,
        'receipt_sha256': 'c' * 64,
        'process_identity': {
            'pid': 100,
            'creation_time_hex': '01dc517c764d7200',
            'is_appcontainer': True,
            'is_elevated': False,
            'is_lpac': None,
        },
    }
    verified = {'job_ref': 'a' * 32, 'credential_ref': 'd' * 32, 'file_evidence_sha256': 'e' * 64}
    profile = {'job_ref': 'a' * 32, 'profile_sha256': 'f' * 64}
    return ReadyInstanceEvidence.from_running(
        running,
        launch_input=verified,
        profile=profile,
        credential_ref='d' * 32,
        scope=LaunchScope('e' * 64, claim.operation_id, 4, claim.nonce),
    )


def test_original_instance_ready_is_committed_with_original_step_and_safe_http(original_instance):
    database, runtime, client, parent, task_id, key, receipt = original_instance
    operation_id = receipt['operation_id']
    assert not advance_start_instance(runtime, parent, cancelled=lambda: False)
    assert original_operation(client, operation_id)['steps'][2]['status'] == 'SUCCEEDED'

    class Driver:
        def start(self, original, checkpoint, *, cancelled):
            assert not cancelled()
            checkpoint()
            current = original_operation(client, operation_id)
            assert current['steps'][3]['status'] == 'RUNNING'
            assert current['steps'][3]['external_identity'] == {}
            assert current['steps'][3]['result_ref'] is None
            assert client.get(f'/api/v1/code-tasks/{task_id}').status_code == 200
            return _evidence(original.claim)

    assert advance_start_instance(runtime, parent, cancelled=lambda: False, driver=Driver())
    assert not advance_start_instance(runtime, parent, cancelled=lambda: False, driver=Driver())
    current = original_operation(client, operation_id)
    assert current['status'] == 'RUNNING'
    assert [step['status'] for step in current['steps'][3:]] == ['SUCCEEDED', 'PENDING', 'PENDING']
    result = current['steps'][3]['result_ref']
    assert set(result) == {'instance_id'}
    assert 'ownership_ref' not in str(current) and 'native_storage_ref' not in str(current)
    assert client.get(f'/api/v1/code-tasks/{task_id}').status_code == 200
    assert start(client, task_id, key=key).json()['data'] == receipt
    with database.transaction() as connection:
        row = connection.execute('SELECT * FROM code_instances').fetchone()
        assert row['id'] == result['instance_id'] and row['status'] == 'READY'
        assert strict_json_object(row['process_identity'])['pid'] == 100
        assert strict_json_object(row['runtime_binding'])['run_kind'] == 'TASK'
        assert connection.execute('SELECT count(*) FROM code_sessions').fetchone()[0] == 0


@pytest.mark.parametrize('interruption', ['restart', 'result_unknown', 'stop'])
def test_original_instance_unknown_never_redispatches(original_instance, interruption):
    database, runtime, client, parent, task_id, _, receipt = original_instance
    operation_id = receipt['operation_id']
    attempts = []

    fenced = []

    class Driver:
        def fence_failed(self, identity):
            fenced.append(identity)

        def start(self, original, checkpoint, *, cancelled):
            attempts.append(original.claim)
            if interruption == 'stop':
                result = stop(client, task_id, original.claim.state_version)
                assert result.status_code == 202, result.text
                checkpoint()
            raise TaskExecutionError('TEST_ORIGINAL_INSTANCE_RESULT_UNKNOWN')

    if interruption == 'restart':
        with database.transaction(write=True) as connection:
            task_start_instance._claim(connection, parent, operation_id)
    driver = Driver()
    assert advance_start_instance(runtime, parent, cancelled=lambda: False, driver=driver)
    assert not advance_start_instance(runtime, parent, cancelled=lambda: False, driver=driver)
    assert len(attempts) == int(interruption != 'restart')
    assert fenced == ([] if interruption == 'restart' else [operation_id])
    current = original_operation(client, operation_id)
    assert current['status'] == 'UNKNOWN'
    assert current['steps'][3]['status'] == 'UNKNOWN'
    assert current['steps'][3]['result_ref'] is None
    with database.transaction() as connection:
        assert connection.execute('SELECT status FROM code_instances').fetchall()[0][0] == 'UNKNOWN'
        assert connection.execute('SELECT count(*) FROM code_instances').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM code_sessions').fetchone()[0] == 0


def test_model_preflight_reads_only_active_current_sqlite_window(original_instance):
    from backend.app.code_tasks.task_start_session import advance_start_session
    from backend.tests.code_tasks.test_task_start_session import NativeDriver

    database, runtime, _, parent, task_id, _, receipt = original_instance

    class Driver:
        def start(self, original, checkpoint, *, cancelled):
            checkpoint()
            return _evidence(original.claim)

    assert advance_start_instance(runtime, parent, cancelled=lambda: False, driver=Driver())
    native = NativeDriver()
    assert advance_start_session(runtime, parent, cancelled=lambda: False, driver=native)
    assert advance_start_session(runtime, parent, cancelled=lambda: False, driver=native)
    with database.transaction(write=True) as connection:
        task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        session = connection.execute(
            'SELECT * FROM code_sessions WHERE id=?', (task['active_session_id'],)
        ).fetchone()
        window = strict_json_object(session['model_window'])
        expected = ModelWindow(
            task_id,
            session['instance_id'],
            task['control_generation'],
            session['id'],
            session['native_session_id'],
            receipt['operation_id'],
            window['native_trigger_message_id'],
        )
        reference = session['gateway_credential_ref']
        assert read_original_open_window(connection, expected, reference) == expected
        assert read_original_open_window(connection, expected, 'b' * 32) is None
        connection.execute(
            'UPDATE code_sessions SET model_window=? WHERE id=?',
            (canonical_input({**window, 'state': 'HELD'}), session['id']),
        )
        assert read_original_open_window(connection, expected, reference) is None
        connection.execute(
            'UPDATE code_sessions SET model_window=? WHERE id=?',
            (canonical_input(window), session['id']),
        )
        connection.execute(
            "UPDATE code_tasks SET stop_requested_at=?,status='STOPPING' WHERE id=?",
            (task['started_at'], task_id),
        )
        assert read_original_open_window(connection, expected, reference) is None


def test_active_row_and_effective_grant_cannot_replace_original_start_proof(original_instance):
    database, runtime, _, parent, task_id, _, receipt = original_instance
    operation_id = receipt['operation_id']

    class Driver:
        def start(self, original, checkpoint, *, cancelled):
            checkpoint()
            return _evidence(original.claim)

    assert advance_start_instance(runtime, parent, cancelled=lambda: False, driver=Driver())
    with database.transaction(write=True) as connection:
        instance = connection.execute('SELECT * FROM code_instances').fetchone()
        generation, instance_id, at = (
            instance['control_generation'],
            instance['id'],
            instance['ready_at'],
        )
        expected = ModelWindow(
            task_id, instance_id, generation, 1, 'ses_original', operation_id, 'msg_initial'
        )
        window = {
            'operation_id': operation_id,
            'native_trigger_message_id': 'msg_initial',
            'state': 'OPEN',
            'opened_at': at,
            'closed_at': None,
        }
        reference = 'a' * 32
        connection.execute(
            """INSERT INTO code_sessions(id,task_id,instance_id,role,control_generation,status,
               created_at,native_session_id,native_message_id,gateway_credential_ref,model_window)
               VALUES(1,?,?,'BACKEND',?,'ACTIVE',?,?,?,?,?)""",
            (
                task_id,
                instance_id,
                generation,
                at,
                expected.native_session_id,
                expected.trigger_message_id,
                reference,
                canonical_input(window),
            ),
        )
        connection.execute(
            "UPDATE code_tasks SET active_session_id=1,status='RUNNING',phase='BACKEND',started_at=? WHERE id=?",
            (at, task_id),
        )
        from backend.app.infrastructure.database import StorageUnavailable

        connection.execute(
            "UPDATE code_authorizations SET status='EFFECTIVE' WHERE task_id=?", (task_id,)
        )
        with pytest.raises(StorageUnavailable, match='launch is not confirmed'):
            read_original_open_window(connection, expected, reference)


def test_installation_and_original_shutdown_fail_closed():
    plan = _plan(12404, 12405)
    installation = TaskLaunchInstallation(plan, 'e' * 64, 3000)
    effective = {
        **plan.executor,
        'configuration_policy_version': 'OC20-CONFIG-1',
        'runtime_policy_version': 'WIN20-ISOLATION-1',
    }
    assert installation.matches(effective)
    assert not installation.matches({**effective, 'configuration_policy_version': 'other'})
    attempts, closed = [], []
    observed = [False]
    frames = object()

    @contextmanager
    def connect():
        yield frames

    def stop_original(*, timeout_ms, cancelled):
        assert 0 < timeout_ms <= 5000 and not cancelled()
        attempts.append('STOP')
        if not observed[0]:
            raise TaskExecutionError('ORIGINAL_TASK_LAUNCH_REQUIRES_OBSERVATION')
        return {'process_state': 'EXITED'}

    launch = SimpleNamespace(
        _input='f' * 64, reconnect=lambda value: attempts.append(value), stop=stop_original
    )
    owner = _Owner(launch=launch, streams=SimpleNamespace(close=lambda: closed.append('streams')))
    driver = TaskInstanceDriver(installation, None, None, None, connect)
    driver._owners[33] = owner
    with pytest.raises(TaskExecutionError, match='SHUTDOWN_FENCE_UNVERIFIED') as unknown:
        driver.close()
    assert unknown.value.retained_owner is owner
    assert driver.has_owners and not closed
    observed[0] = True
    driver.close()
    assert not driver.has_owners and closed == ['streams']
    assert attempts == [frames, 'STOP', frames, 'STOP']
