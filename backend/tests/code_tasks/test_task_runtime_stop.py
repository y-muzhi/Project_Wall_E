"""Original Coding termination with SQLite, HTTP and real owned workspace NTFS cleanup."""

from datetime import UTC, datetime, timedelta

import pytest

from backend.app.code_tasks import task_runtime_stop as flow
from backend.app.code_tasks.coding_model_wait import hold_coding_model
from backend.app.code_tasks.task_model_ingress import ModelWindow
from backend.app.code_tasks.task_start_session import advance_start_session
from backend.app.code_tasks.task_workspace_release import OriginalWorkspaceRelease
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.windows_task_directory_release import OwnedTreeDeletion
from backend.app.shared.validation import strict_json_object
from backend.tests.code_tasks.test_task_start import isolated_readiness, original_operation, stop  # noqa: F401
from backend.tests.code_tasks.test_task_start_instance import original_instance  # noqa: F401
from backend.tests.code_tasks.test_task_start_session import NativeDriver, ready  # noqa: F401
from backend.tests.infrastructure.test_v20_check_runner_bundle import bundle  # noqa: F401
from backend.tests.infrastructure.test_v20_command_http import package, service  # noqa: F401
from backend.tests.test_testing_pack_seal import installed  # noqa: F401
from backend.tests.test_testing_report_api import completed_fixture  # noqa: F401

_STOP_REF = 'a' * 32
_CLEANUP_REF = 'd' * 64


class StopDriver:
    def __init__(self, parent):
        self.calls = []
        self.parent = parent
        self.stop_unavailable = False
        self.cleanup_unavailable = False
        self.observe_stage = lambda *_: None

    def revoke_original_gateway(self, original):
        self.calls.append('revoke')

    def abort_original(self, original, checkpoint, *, timeout_ms):
        self.calls.append('abort')
        self.observe_stage('ABORTING', 'NOT_STARTED', None)
        assert original.native_session_id == 'ses_original'
        checkpoint()
        return 'ACKNOWLEDGED'

    def _proof(self, original, action):
        fence = {
            'scope': {
                'controller_ref': 'e' * 64,
                'operation_id': original.claim.operation_id,
                'step_no': 4,
                'nonce': original.claim.nonce,
            },
            'stop_closed': True,
        }
        native = {
            'run_kind': 'TASK',
            'process_state': 'EXITED',
            'job_ref': _STOP_REF,
            'resource_ref': original.runtime_binding_ref,
            'receipt_sha256': original.process_receipt,
            'fence': fence,
        }
        ack = {'binding_ref': _STOP_REF, 'native': native}
        if action == 'RELEASE':
            ack['cleanup_ref'] = _CLEANUP_REF
        return {
            'observed_action': action,
            'action_phase': 'ACKNOWLEDGED',
            'binding_ref': _STOP_REF,
            'input_sha256': 'e' * 64,
            'resource': native,
            'fence': fence,
            'acknowledgement': ack,
            'job_activity': {'process_ids': [], 'complete': True, 'assigned_count': 1},
            'preparation': {'cleanup_state': 'COMPLETE' if action == 'RELEASE' else 'UNKNOWN'},
        }

    def stop_original(self, original, *, timeout_ms, cancelled):
        self.calls.append('stop')
        self.observe_stage('TERMINATING', 'NOT_STARTED', None)
        result = self._proof(original, 'STOP')
        if self.stop_unavailable:
            result['job_activity']['process_ids'] = [100]
        return result

    def release_original(self, original, *, timeout_ms, cancelled):
        self.calls.append('release')
        self.observe_stage('VERIFIED', 'CLEANING', 0)
        if self.cleanup_unavailable:
            raise TaskExecutionError('TEST_GUARD_RELEASE_UNKNOWN')
        return self._proof(original, 'RELEASE')

    def release_workspace_original(self, original, operation_id, guard_ref, checkpoint):
        self.calls.append('workspace')
        return OriginalWorkspaceRelease(self.parent, original, operation_id, guard_ref).release(
            checkpoint
        )

    def retire_original(self, original):
        self.calls.append('retire')


@pytest.mark.parametrize('interruption', ['abort_intent', 'native_and_cleanup'])
def test_original_running_task_stops_then_releases_workspace(ready, monkeypatch, interruption):  # noqa: F811
    database, runtime, client, parent, task_id, _, start_receipt = ready
    native = NativeDriver()
    options = {'cancelled': lambda: False, 'driver': native}
    assert advance_start_session(runtime, parent, **options)
    assert advance_start_session(runtime, parent, **options)
    stop_version = 4
    if interruption == 'abort_intent':
        scope = native.calls[-1][1]
        window = ModelWindow(
            task_id,
            scope.instance_id,
            scope.control_generation,
            scope.session_id,
            'ses_original',
            start_receipt['operation_id'],
            'msg_original',
        )
        with database.transaction(write=True) as connection:
            hold_coding_model(connection, window, native.credential, kind='BUDGET')
        stop_version = 5
    response = stop(client, task_id, stop_version)
    assert response.status_code == 202, response.text
    receipt = response.json()['data']
    identity = receipt['operation_id']
    path = f'/api/v1/code-tasks/{task_id}'
    clock = datetime.now(UTC) + timedelta(seconds=3)
    monkeypatch.setattr(
        flow,
        'operation_time',
        lambda unused: clock.isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
    )
    driver = StopDriver(parent)

    def observe_stage(stop_stage, cleanup_stage, count):
        current = client.get(path)
        assert current.status_code == 200, current.text
        view = current.json()['data']
        assert view['status'] == 'STOPPING'
        assert view['stopped_at'] is None
        assert view['runtime']['stop_status'] == stop_stage
        assert view['runtime']['cleanup_status'] == cleanup_stage
        assert view['runtime']['active_process_count'] == count

    observe_stage('REQUESTED', 'NOT_STARTED', None)

    def remember_live_stage(stop_stage, cleanup_stage, count):
        # Once an I/O result is unknown, retrying the original path must not
        # relabel it as freshly dispatched. The positive proof changes the view.
        original = original_operation(client, identity)
        if original['status'] == 'UNKNOWN':
            observe_stage('VERIFIED' if stop_stage == 'VERIFIED' else 'UNKNOWN', 'UNKNOWN', count)
        else:
            observe_stage(stop_stage, cleanup_stage, count)

    driver.observe_stage = remember_live_stage

    def advance():
        return flow.advance_owned_stops(runtime, driver, cancelled=lambda: False)

    with database.transaction() as connection:
        workspace = connection.execute('SELECT * FROM code_workspaces').fetchone()
        working = parent.path / workspace['private_location_key']
        assert working.is_dir()
        if interruption == 'native_and_cleanup':
            # The fixed test snapshot is empty. Add only an owned fixture entry so
            # interruption occurs before the native delete reaches the workspace root.
            with (working / 'owned-delete-fixture.txt').open('xb') as stream:
                stream.write(b'one original fixture entry')
        audit = tuple(parent.path.glob('*.workspace-tree.json'))
        assert len(audit) == 1
        window = connection.execute('SELECT model_window FROM code_sessions').fetchone()[0]
        assert strict_json_object(window)['state'] == 'CLOSED'
    assert advance()
    assert advance()
    if interruption == 'abort_intent':
        with database.transaction(write=True) as connection:
            connection.execute(
                """UPDATE code_operation_steps SET status='RUNNING',started_at=?,last_observed_at=?
                   WHERE operation_id=? AND step_no=3""",
                (flow.operation_time(None), flow.operation_time(None), identity),
            )
    assert advance()
    progress = original_operation(client, identity)
    assert progress['status'] == 'RUNNING'
    assert [step['status'] for step in progress['steps']] == ['SUCCEEDED'] * 3 + ['PENDING'] * 3
    observe_stage('ABORTING', 'NOT_STARTED', None)
    assert not advance()
    clock += timedelta(days=1)
    if interruption == 'native_and_cleanup':
        driver.stop_unavailable = True
        assert not advance()
        assert original_operation(client, identity)['status'] == 'UNKNOWN'
        assert client.get(path).json()['data']['runtime']['active_process_count'] is None
        driver.stop_unavailable = False
    assert advance()
    assert client.get(path).json()['data']['runtime']['active_process_count'] == 0
    assert advance()
    if interruption == 'native_and_cleanup':
        driver.cleanup_unavailable = True
        assert not advance()
        status = client.get(path).json()['data']
        assert status['status'] == 'STOPPING' and working.exists()
        assert status['runtime']['stop_status'] == 'VERIFIED'
        assert status['runtime']['cleanup_status'] == 'UNKNOWN'
        driver.cleanup_unavailable = False
        delete = OwnedTreeDeletion.delete

        def interrupt_after_delete(owner, entry, checkpoint):
            delete(owner, entry, checkpoint)
            raise OSError('Fixture interrupted after deleting one exact original file')

        with monkeypatch.context() as isolated:
            isolated.setattr(OwnedTreeDeletion, 'delete', interrupt_after_delete)
            assert not advance()
        assert working.is_dir()
        assert tuple(parent.path.glob('*.workspace-release-intent.json'))
        assert not tuple(parent.path.glob('*.workspace-release-ack.json'))
    assert advance()
    assert not advance()
    assert not working.exists()
    assert audit[0].is_file()
    ended = client.get(path)
    assert ended.status_code == 200, ended.text
    terminal = ended.json()['data']
    assert (terminal['status'], terminal['phase'], terminal['state_version']) == (
        'TERMINATED',
        'FINISHED',
        stop_version + 2,
    )
    assert terminal['waiting_items'] == []
    assert terminal['workspace_id'] == workspace['id'] and terminal['active_session_id'] is None
    assert terminal['runtime']['cleanup_status'] == 'VERIFIED'
    terminal_stop = stop(client, task_id, terminal['state_version'])
    assert terminal_stop.status_code == 200, terminal_stop.text
    assert terminal_stop.json()['data'] == terminal
    assert original_operation(client, start_receipt['operation_id'])['status'] == 'SUCCEEDED'
    progress = original_operation(client, identity)
    assert progress['status'] == 'SUCCEEDED'
    assert set(progress['steps'][3]['result_ref']) == {
        'stop_observation_id',
        'cleanup_observation_id',
    }
    assert _STOP_REF not in str(progress) and 'ses_original' not in str(progress)
    assert driver.calls.count('abort') == int(interruption != 'abort_intent')
    assert driver.calls[-2:] == ['workspace', 'retire']
    assert driver.calls.count('workspace') == (2 if interruption == 'native_and_cleanup' else 1)
    with database.transaction() as connection:
        assert [
            tuple(row)
            for row in connection.execute(
                'SELECT kind,result,active_process_count FROM code_runtime_observations ORDER BY id'
            )
        ] == [('STOP', 'VERIFIED', 0), ('CLEANUP', 'VERIFIED', 0)]
        assert connection.execute('SELECT status FROM code_sessions').fetchone()[0] == 'RETIRED'
        waits = connection.execute(
            'SELECT status,resolution_ref FROM code_waiting_items'
        ).fetchall()
        if interruption == 'abort_intent':
            (waiting,) = waits
            assert waiting['status'] == 'RESOLVED'
            assert strict_json_object(waiting['resolution_ref']) == {
                'operation_id': identity,
                'outcome': 'TASK_TERMINATED',
            }
        else:
            assert not waits


@pytest.mark.parametrize('completed_fixture', ['candidate-delivery'], indirect=True)
def test_delivery_naturally_closes_original_workspace_only_after_native_proof(
    completed_fixture,  # noqa: F811
    tmp_path,
    isolated_readiness,  # noqa: F811
    monkeypatch,
):
    from backend.app.code_tasks import (
        task_start,
        task_start_basis,
        task_start_workspace,
    )
    from backend.app.code_tasks.task_start_instance import advance_start_instance
    from backend.app.infrastructure.windows_private_package import (
        PrivatePackageGuard,
        create_private_package,
    )
    from backend.app.shared.command_execution import operation_time
    from backend.tests.code_tasks.test_task_start import start
    from backend.tests.code_tasks.test_task_start_basis import WorkspaceActor
    from backend.tests.code_tasks.test_task_start_instance import _evidence

    client, _ = completed_fixture
    runtime = client.app.state.walle_runtime
    database = runtime.database
    with database.transaction(write=True) as connection:
        task_id = connection.execute('SELECT id FROM code_tasks').fetchone()['id']
        connection.execute(
            "UPDATE code_tasks SET status='PENDING',phase='PREPARING' WHERE id=?", (task_id,)
        )

    class Driver:
        def start(self, original, checkpoint, *, cancelled):
            checkpoint()
            return _evidence(original.claim)

    with PrivatePackageGuard(create_private_package(tmp_path / 'natural-finalization')) as parent:
        # The report fixture creates its candidate before this isolated START.
        with monkeypatch.context() as setup:
            setup.setattr(
                task_start,
                'EXECUTION_TABLES',
                tuple(name for name in task_start.EXECUTION_TABLES if name != 'code_candidates'),
            )
            response = start(client, task_id)
        assert response.status_code == 202, response.text
        start_id = response.json()['data']['operation_id']
        task_start_workspace.advance_workspace_start(
            runtime, WorkspaceActor(), None, parent, cancelled=lambda: False
        )
        assert task_start_basis.advance_start_basis(runtime, parent, cancelled=lambda: False)
        with database.transaction(write=True) as connection:
            at = operation_time(None)
            connection.execute(
                """UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,
                   started_at=?,ended_at=?,last_observed_at=? WHERE operation_id=? AND step_no=3""",
                (
                    '{"fixed_content_verified":true,"capability_codes":[],"system_config_clear":true,"runtime_launch_admission":true}',
                    at,
                    at,
                    at,
                    start_id,
                ),
            )
        assert advance_start_instance(runtime, parent, cancelled=lambda: False, driver=Driver())
        _verify_natural_delivery(database, runtime, parent, task_id, client, monkeypatch)


def _verify_natural_delivery(database, runtime, parent, task_id, client, monkeypatch):
    from uuid import uuid4

    from backend.app.code_tasks import repository_registration_worker, task_delivery_finalize
    from backend.app.code_tasks.operation_protocol import operation_steps
    from backend.app.code_tasks.task_delivery_write import _wait_for_delivery
    from backend.app.code_tasks.task_stop import _close_task_model_windows
    from backend.app.infrastructure.idempotency import canonical_input
    from backend.app.infrastructure.identifiers import EntityKind, entity_id
    from backend.app.shared.command_execution import operation_time

    options = {'cancelled': lambda: False, 'driver': NativeDriver()}
    assert advance_start_session(runtime, parent, **options)
    assert advance_start_session(runtime, parent, **options)
    with database.transaction(write=True) as connection:
        task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        workspace = connection.execute(
            'SELECT * FROM code_workspaces WHERE task_id=?', (task_id,)
        ).fetchone()
        working = parent.path / workspace['private_location_key']
        assert working.is_dir()
        at = operation_time(None)
        identity = entity_id(connection, EntityKind.OPERATION_RECORD)
        _close_task_model_windows(connection, task, at)
        candidate = task['current_candidate_id']
        expected_target = 'a' * 40
        fixed = canonical_input(
            {
                'expected_state_version': task['state_version'],
                'candidate_id': candidate,
                'test_report_id': 1,
                'delivery_plan_id': 1,
                'expected_target_commit': expected_target,
                'repository_quiescent_confirmed': True,
                'manual_risk_accepted': False,
            }
        )
        connection.execute(
            """INSERT INTO code_operations(id,task_id,resource_kind,resource_id,session_id,
               operation_type,idempotency_key,expected_state_version,fixed_input,control_generation,
               status,created_at,started_at)
               VALUES(?,?,'TASK',?,?,'DELIVER',?,?,?,?,'UNKNOWN',?,?)""",
            (
                identity,
                task_id,
                task_id,
                task['active_session_id'],
                str(uuid4()),
                task['state_version'],
                fixed,
                task['control_generation'],
                at,
                at,
            ),
        )
        for number, name in enumerate(operation_steps('CODING', 'DELIVER'), 1):
            connection.execute(
                """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input)
                   VALUES(?,?,?,?,?)""",
                (identity, number, name, 'PENDING' if number == 8 else 'SUCCEEDED', fixed),
            )
        # The observed Git fact is a fixture. The candidate and report are original
        # to the same database, with foreign keys and immutable evidence enabled.
        connection.execute(
            """INSERT INTO code_delivery_plans(id,task_id,candidate_id,test_report_id,repository_id,
               target_branch,expected_target_commit,target_tree_oid,target_content_store_key,
               target_manifest_sha256,result_tree_oid,operation_id,created_at)
               VALUES(1,?,?,1,?,?,?,?,?,?,?,?,?)""",
            (
                task_id,
                candidate,
                task['repository_id'],
                task['target_branch'],
                expected_target,
                'b' * 40,
                'fixture:target',
                'c' * 64,
                'd' * 40,
                identity,
                at,
            ),
        )
        connection.execute(
            """INSERT INTO code_acceptances(id,task_id,candidate_id,test_report_id,delivery_plan_id,
               manual_risk_accepted,actor_ref,accepted_at) VALUES(1,?,?,1,1,0,'isolated-owner',?)""",
            (task_id, candidate, at),
        )
        connection.execute(
            """INSERT INTO code_deliveries(id,task_id,acceptance_id,delivery_plan_id,operation_id,
               status,git_write_status,postcheck_status,created_at,planned_commit_oid,delivered_at,current_window_id)
               VALUES(1,?,1,1,?,'SUCCEEDED','CONFIRMED','VERIFIED',?,?,?,1)""",
            (task_id, identity, at, 'e' * 40, at),
        )
        connection.execute(
            """INSERT INTO code_delivery_windows VALUES(1,1,?,?,?,'isolated-controller')""",
            (identity, at, at),
        )
        connection.execute(
            """UPDATE code_tasks SET status='WAITING',phase='DELIVERY',resume_phase='DELIVERY',
               current_delivery_plan_id=1,current_delivery_id=1,current_test_report_id=1,
               last_observed_at=?,updated_at=? WHERE id=?""",
            (at, at, task_id),
        )
        saved = task_delivery_finalize.load_original_delivery(connection, identity)
        _wait_for_delivery(connection, saved.task, saved.delivery, at)

    class FinalizationWorker:
        accepts_model_resumes = False
        delivery_writes_ready = True
        delivery_finalization_ready = True
        delivery_epoch = 'a' * 32

        def wake(self):
            return None

    monkeypatch.setattr(
        repository_registration_worker, 'RepositoryRegistrationWorker', FinalizationWorker
    )
    monkeypatch.setattr(
        client.app.state, 'walle_repository_registration', FinalizationWorker(), raising=False
    )
    url = f'/api/v1/code-tasks/{task_id}/resume'

    def resume_cleanup():
        with database.transaction() as connection:
            current = task_delivery_finalize.load_original_delivery(connection, identity)
            _, wait = task_delivery_finalize.resumable_finalization(
                connection, current.task, identity
            )
        body = {
            'expected_state_version': current.task['state_version'],
            'operation_id': identity,
            'waiting_item_ids': [wait['id']],
        }
        refused = client.post(
            url,
            headers={'Idempotency-Key': str(uuid4())},
            json={**body, 'repository_quiescent_confirmed': True},
        )
        assert refused.status_code == 409, refused.text
        headers = {'Idempotency-Key': str(uuid4())}
        accepted = client.post(url, headers=headers, json=body)
        assert accepted.status_code == 202, accepted.text
        assert task_delivery_finalize.advance_delivery_finalization_resume(runtime)
        recorded = original_operation(client, accepted.json()['data']['operation_id'])
        assert recorded['status'] == 'SUCCEEDED'
        assert recorded['steps'][-1]['result_ref'] == {'delivery_id': current.delivery['id']}
        assert (
            client.post(url, headers=headers, json=body).json()['data'] == accepted.json()['data']
        )

    driver = StopDriver(parent)

    def advance():
        return task_delivery_finalize.advance_owned_delivery_finalization(
            runtime, driver, parent, cancelled=lambda: False
        )

    assert advance()
    assert working.exists()
    driver.stop_unavailable = True
    assert not advance()
    assert working.exists()
    assert 'release' not in driver.calls and 'revoke' not in driver.calls
    with database.transaction() as connection:
        step = task_delivery_finalize.load_original_delivery(connection, identity).steps[7]
        assert step['status'] == 'UNKNOWN' and step['result_ref'] is None
    driver.stop_unavailable = False
    assert not advance()
    resume_cleanup()
    assert advance()
    driver.cleanup_unavailable = True
    assert not advance()
    assert working.exists()
    driver.cleanup_unavailable = False
    assert not advance()
    resume_cleanup()
    assert advance()
    assert not working.exists()
    assert driver.calls.count('stop') == 2
    assert driver.calls.index('stop') < driver.calls.index('revoke') < driver.calls.index('release')
    with database.transaction() as connection:
        final = task_delivery_finalize.load_original_delivery(connection, identity)
        result = task_delivery_finalize.read_finalized_delivery(connection, final)
        assert set(result) == {'stop', 'cleanup'}
        assert final.task['status'] == 'COMPLETED' and final.task['phase'] == 'FINISHED'
        assert final.task['stop_requested_at'] is None and final.task['stopped_at'] is None
        assert final.operation['status'] == 'SUCCEEDED'
        assert final.task['control_generation'] == task['control_generation'] + 1
        assert connection.execute('SELECT COUNT(*) FROM code_delivery_windows').fetchone()[0] == 1
        assert final.delivery['delivered_at'] == at
        assert [
            tuple(row)
            for row in connection.execute(
                'SELECT kind,result,operation_id FROM code_runtime_observations WHERE task_id=? ORDER BY id',
                (task_id,),
            )
        ] == [('STOP', 'VERIFIED', identity), ('CLEANUP', 'VERIFIED', identity)]
