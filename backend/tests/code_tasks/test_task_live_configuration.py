"""Live C39 keeps the original launch and atomically adopts only verified controls."""

import json
import sqlite3
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.code_tasks import task_live_configuration as flow
from backend.app.code_tasks.authorizations import project_grant
from backend.app.code_tasks.execution_profile_content import FIELDS
from backend.app.code_tasks.task_configuration_effective import CONTROL_LIMITS
from backend.app.code_tasks.task_initial_configuration import InitialConfigurationObservation
from backend.app.code_tasks.task_instance_driver import CaptureTurnEvidence
from backend.app.code_tasks.task_start_session import original_active_session_scope
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.opencode_instance_control import NativeTurnCompletion
from backend.app.infrastructure.windows_local_paths import LocalPathGuard
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_json_object
from backend.tests.code_tasks.test_authorizations import approve
from backend.tests.code_tasks.test_coding_model_gateway import fixed_price, opened  # noqa: F401
from backend.tests.code_tasks.test_execution_profile_versions import (
    fixture_snapshot,
    publish,
    resources,
)
from backend.tests.code_tasks.test_task_start import isolated_readiness, stop  # noqa: F401
from backend.tests.code_tasks.test_task_start_instance import original_instance  # noqa: F401
from backend.tests.code_tasks.test_task_start_session import ready  # noqa: F401
from backend.tests.infrastructure.test_v20_command_http import package, service  # noqa: F401
from backend.tests.test_testing_cli_run import _candidate_fixture


@pytest.fixture(autouse=True)
def versioned_runtime_fixture(monkeypatch):
    from backend.tests.code_tasks import test_execution_profile_versions as versions

    original = versions.body

    def prepared():
        value = original()
        value['executor']['runtime_bundle_ref'] = 'opencode-bundle:sha256:' + 'a' * 64
        return value

    monkeypatch.setattr(versions, 'body', prepared)


@pytest.fixture
def idle_task(opened, ready, monkeypatch):  # noqa: F811
    database, runtime, client, ingress, _credential, _admission = opened
    _, _, _, parent, task_id, _, _ = ready
    candidate, _ = _candidate_fixture(database, task_id)
    original = ingress.window
    at = operation_time(None)
    with database.transaction(write=True) as connection:
        capture = connection.execute(
            'SELECT capture_operation_id FROM code_candidates WHERE id=?', (candidate,)
        ).fetchone()[0]
        instance = connection.execute(
            'SELECT * FROM code_instances WHERE id=?', (original.instance_id,)
        ).fetchone()
        guard = strict_json_object(instance['process_identity'])['ownership_ref']
        binding = strict_json_object(instance['runtime_binding'])
        connection.execute(
            """INSERT INTO code_runtime_observations(id,task_id,instance_id,operation_id,
               control_generation,runtime_binding_ref,kind,result,reason_codes,active_process_count,
               observed_at,evidence_ref) VALUES(?,?,?,?,?,?,'QUIESCE','VERIFIED','[]',1,?,'fixture:quiet')""",
            (
                entity_id(connection, EntityKind.RUNTIME_OBSERVATION),
                task_id,
                original.instance_id,
                capture,
                original.generation,
                binding['guard_run_ref'],
                at,
            ),
        )
        session = connection.execute(
            'SELECT model_window FROM code_sessions WHERE id=?', (original.execution_session_id,)
        ).fetchone()
        window = strict_json_object(session[0])
        window.update(state='CLOSED', closed_at=at)
        connection.execute(
            'UPDATE code_sessions SET model_window=? WHERE id=?',
            (canonical_input(window), original.execution_session_id),
        )
        connection.execute(
            "UPDATE code_tasks SET status='VERIFYING',current_candidate_id=?,updated_at=?,last_observed_at=? WHERE id=?",
            (candidate, at, at, task_id),
        )
    monkeypatch.setattr(
        client.app.state,
        'walle_repository_registration',
        SimpleNamespace(
            accepts_live_configuration=True,
            accepts_native_responses=True,
            accepts_model_resumes=True,
            project_check_admissions=(),
            wake=lambda: None,
        ),
        raising=False,
    )
    # This fast state test has a logical candidate; the native package path is
    # exercised separately by the original NTFS/MinGit capture integration.
    from backend.app.code_tasks import task_capture_task_view

    monkeypatch.setattr(task_capture_task_view, 'read_stored_candidate_package', lambda *_: None)
    monkeypatch.setattr(flow, '_OBSERVE_RECHECK_SECONDS', 0)
    return database, runtime, client, ingress, parent, task_id, guard, binding, _admission


def target_pair(fixture, change='controls'):
    database, _, client, _, _, task_id, _, _, _ = fixture
    with database.transaction() as connection:
        task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        row = connection.execute(
            'SELECT * FROM code_execution_profile_versions WHERE id=?',
            (task['execution_profile_version_id'],),
        ).fetchone()
        content = {
            key: row[key]
            if key == 'check_set_version_id' or row[key] is None
            else json.loads(row[key])
            for key in FIELDS
        }
        grant = project_grant(
            connection.execute(
                'SELECT * FROM code_authorizations WHERE id=?', (task['authorization_id'],)
            ).fetchone()
        )
    old = dict(task)
    limits = content['limits']
    limits['query_timeout_seconds'] += 1
    next_scope = deepcopy(grant['scope'])
    next_scope['limits']['query_timeout_seconds'] = limits['query_timeout_seconds']
    if change in ('authorization-only', 'model-revoke', 'delivery-revoke'):
        limits['query_timeout_seconds'] -= 1
        next_scope['limits']['query_timeout_seconds'] = limits['query_timeout_seconds'] - (
            1 if change == 'authorization-only' else 0
        )
        if change == 'model-revoke':
            next_scope['model_profile_refs'] = []
        if change == 'delivery-revoke':
            next_scope['allow_local_delivery'] = False
    elif change == 'native':
        content['executor']['runtime_bundle_ref'] = 'opencode-bundle:sha256:' + 'b' * 64
    elif change == 'noncontrol':
        limits['max_active_seconds'] += 1
    elif change == 'content-capacity':
        limits['max_file_bytes'] += 1
    elif change == 'capture-rules':
        content['capture_rules']['product_include_paths'] = ['src/']
    elif change == 'model-limits':
        limits['max_model_requests'] += 1
        limits['max_output_tokens'] += 1
        limits['max_consecutive_failures'] += 1
        limits['send_timeout_seconds'] += 1
        limits['queue_wait_seconds'] += 1
        for key in CONTROL_LIMITS:
            next_scope['limits'][key] = limits[key]
        next_scope['limits']['max_output_tokens'] = 50
    with resources(fixture_snapshot(content)):
        if change in ('authorization-only', 'model-revoke', 'delivery-revoke'):
            version_id = old['execution_profile_version_id']
        else:
            version = publish(client, content)
            assert version.status_code == 201, version.text
            version_id = version.json()['data']['resource_id']
        approved = approve(client, {'profile_version_id': version_id, 'scope': next_scope})
        assert approved.status_code == 201, approved.text
    return old, version_id, approved.json()['data']['resource_id'], content


class ReadOnlyDriver:
    def __init__(self, fixture, *, unknown=False):
        self.fixture = fixture
        self.unknown = unknown
        self.calls = []
        self.interleave = None
        self.bad_guard = False

    def observe_control_configuration(self, scope, window, credential_ref, checkpoint):
        self.calls.append((scope, window, credential_ref))
        checkpoint()
        if self.unknown:
            return None
        database, _, _, ingress, parent, _, guard, binding, _ = self.fixture
        with database.transaction() as connection:
            executor = strict_json_object(
                connection.execute(
                    'SELECT executor FROM code_execution_profile_versions WHERE id=?',
                    (scope.profile_id,),
                ).fetchone()[0]
            )
        assert window == ingress.window
        with LocalPathGuard(parent.path, directory=True) as directory:
            workspace = directory.verify()
        if self.interleave is not None:
            self.interleave()
            checkpoint()
        return flow.ControlConfigurationObservation(
            CaptureTurnEvidence(
                NativeTurnCompletion(
                    window.native_session_id,
                    window.trigger_message_id,
                    'msg_controlEnd',
                    'COMPLETED',
                ),
                '0' * 64 if self.bad_guard else guard,
                1,
                workspace,
            ),
            InitialConfigurationObservation(
                executor['runtime_bundle_ref'],
                binding['manifest_ref'],
                'f' * 64,
                'isolated-backend',
            ),
            'e' * 64,
        )


@pytest.mark.parametrize(
    'mode',
    [
        'success',
        'unknown',
        'stop',
        'native',
        'content-capacity',
        'capture-rules',
        'noncontrol',
        'repeat',
        'stop-during-read',
        'integrity',
        'model-limits',
        'bad-observation',
        'cancelled-worker',
        'authorization-only',
        'budget-during-read',
    ],
)
def test_live_control_application_preserves_launch_and_only_adopts_verified_pair(idle_task, mode):
    database, runtime, client, ingress, parent, task_id, _, _, admission = idle_task
    old, profile, grant, content = target_pair(idle_task, mode)
    path = f'/api/v1/code-tasks/{task_id}'
    data = {
        'expected_state_version': old['state_version'],
        'execution_profile_version_id': profile,
        'authorization_id': grant,
        'reason': '明确调整已停止写入任务的控制限制',
    }
    key = str(uuid4())
    with resources(fixture_snapshot(content)):
        result = client.post(path + '/configuration', json=data, headers={'Idempotency-Key': key})
    if mode in ('native', 'noncontrol', 'content-capacity', 'capture-rules'):
        assert result.status_code in (409, 503), result.text
        if mode in ('content-capacity', 'capture-rules'):
            assert result.status_code == 409, result.text
            assert result.json()['error']['code'] == 'PRECONDITION_FAILED'
        with database.transaction() as connection:
            assert connection.execute(
                'SELECT task_id,status FROM code_authorizations WHERE id=?', (grant,)
            ).fetchone()[:] == (None, 'APPROVED_UNBOUND')
        return
    assert result.status_code == 202, result.text
    receipt = result.json()['data']
    assert receipt['task_status'] == 'WAITING'
    identity = receipt['operation_id']
    original = client.get(path + f'/operations/{identity}')
    assert original.status_code == 200, original.text
    assert [s['status'] for s in original.json()['data']['steps']] == ['SUCCEEDED'] + [
        'PENDING'
    ] * 3
    detail = client.get(path)
    assert detail.status_code == 200, detail.text
    assert (
        detail.json()['data']['execution_profile_version_id'] == old['execution_profile_version_id']
    )
    assert detail.json()['data']['configuration_application']['status'] == 'PENDING'
    assert detail.json()['data']['active_operations'] == [
        {'id': identity, 'operation_type': 'APPLY_CONFIGURATION', 'status': 'RUNNING'}
    ]
    if mode == 'integrity':
        from backend.app.code_tasks.task_read_api import validate_saved_task_view

        lost = {**detail.json()['data'], 'active_operations': []}
        with pytest.raises(ValueError):
            validate_saved_task_view(lost, task_id)
    driver = ReadOnlyDriver(idle_task, unknown=mode == 'unknown')
    driver.bad_guard = mode == 'bad-observation'
    if mode in ('stop', 'stop-during-read'):
        from datetime import UTC, datetime, timedelta

        from backend.app.code_tasks import task_runtime_stop
        from backend.tests.code_tasks.test_task_runtime_stop import StopDriver

        def stop_original():
            stopped = stop(client, task_id, receipt['state_version'])
            assert stopped.status_code == 202, stopped.text

        if mode == 'stop-during-read':
            driver.interleave = stop_original
        else:
            stop_original()
        assert not flow.advance_live_configuration(runtime, driver, cancelled=lambda: False)
        assert len(driver.calls) == (1 if mode == 'stop-during-read' else 0)
        clock = datetime.now(UTC) + timedelta(days=1)

        def after_grace(_):
            nonlocal clock
            clock += timedelta(minutes=2)
            return clock.isoformat(timespec='milliseconds').replace('+00:00', 'Z')

        monkeypatch = pytest.MonkeyPatch()
        try:
            monkeypatch.setattr(task_runtime_stop, 'operation_time', after_grace)
            stopped_driver = StopDriver(parent)
            for _ in range(10):
                task_runtime_stop.advance_owned_stops(
                    runtime, stopped_driver, cancelled=lambda: False
                )
                terminal = client.get(path)
                assert terminal.status_code == 200, terminal.text
                if terminal.json()['data']['status'] == 'TERMINATED':
                    break
            assert terminal.json()['data']['status'] == 'TERMINATED', terminal.text
            assert terminal.json()['data']['runtime']['cleanup_status'] == 'VERIFIED'
            assert (
                terminal.json()['data']['execution_profile_version_id']
                == old['execution_profile_version_id']
            )
            assert terminal.json()['data']['configuration_application']['status'] == 'FAILED'
            assert (
                client.get(path + f'/operations/{identity}').json()['data']['status'] == 'CANCELLED'
            )
            with database.transaction() as connection:
                assert (
                    connection.execute(
                        'SELECT status FROM code_authorizations WHERE id=?', (grant,)
                    ).fetchone()[0]
                    == 'APPLY_FAILED'
                )
        finally:
            monkeypatch.undo()
        return
    if mode == 'budget-during-read':

        def increase_while_observing():
            increased = client.post(
                path + '/budget',
                json={
                    'expected_state_version': receipt['state_version'],
                    'new_budget_limit_cny': '0.200000',
                    'reason': '核对配置时明确提高预算总额',
                },
                headers={'Idempotency-Key': str(uuid4())},
            )
            assert increased.status_code == 200, increased.text
            budget_view = increased.json()['data']
            assert budget_view['status'] == 'WAITING'
            assert budget_view['configuration_application']['status'] == 'PENDING'
            assert budget_view['active_operations'] == [
                {'id': identity, 'operation_type': 'APPLY_CONFIGURATION', 'status': 'RUNNING'}
            ]

        driver.interleave = increase_while_observing
        assert not flow.advance_live_configuration(runtime, driver, cancelled=lambda: False)
        pending = client.get(path)
        assert pending.status_code == 200, pending.text
        assert pending.json()['data']['budget']['limit_cny'] == '0.200000'
        assert pending.json()['data']['configuration_application']['status'] == 'PENDING'
        assert (
            pending.json()['data']['execution_profile_version_id']
            == old['execution_profile_version_id']
        )
        driver.interleave = None
    if mode == 'cancelled-worker':
        from threading import Event

        cancelled = Event()
        driver.interleave = cancelled.set
        assert not flow.advance_live_configuration(runtime, driver, cancelled=cancelled.is_set)
        pending = client.get(path)
        assert pending.status_code == 200, pending.text
        assert pending.json()['data']['configuration_application']['status'] == 'PENDING'
        assert (
            pending.json()['data']['execution_profile_version_id']
            == old['execution_profile_version_id']
        )
        driver.interleave = None
    assert flow.advance_live_configuration(runtime, driver, cancelled=lambda: False)
    if mode in ('unknown', 'bad-observation'):
        pending = client.get(path)
        assert pending.status_code == 200, pending.text
        assert pending.json()['data']['configuration_application']['status'] == 'UNKNOWN'
        assert (
            pending.json()['data']['execution_profile_version_id']
            == old['execution_profile_version_id']
        )
        driver.unknown = False
        driver.bad_guard = False
        assert flow.advance_live_configuration(runtime, driver, cancelled=lambda: False)
    outcome = client.get(path + f'/operations/{identity}')
    assert outcome.status_code == 200, outcome.text
    assert outcome.json()['data']['status'] == 'SUCCEEDED'
    detail = client.get(path)
    assert detail.status_code == 200, detail.text
    view = detail.json()['data']
    assert view['status'] == 'VERIFYING'
    assert (view['execution_profile_version_id'], view['authorization_id']) == (profile, grant)
    assert view['configuration_application']['status'] == 'APPLIED'
    assert view['waiting_items'] == []
    with database.transaction() as connection:
        task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        session = connection.execute(
            'SELECT * FROM code_sessions WHERE id=?', (ingress.window.execution_session_id,)
        ).fetchone()
        scope = original_active_session_scope(connection, task, session)
        assert scope.profile_id == old['execution_profile_version_id']
        assert scope.authorization_id == grant
        active_scope = project_grant(
            connection.execute('SELECT * FROM code_authorizations WHERE id=?', (grant,)).fetchone()
        )['scope']
        assert scope.query_timeout_seconds == min(
            content['limits']['query_timeout_seconds'],
            active_scope['limits']['query_timeout_seconds'],
        )
        instance = connection.execute(
            'SELECT * FROM code_instances WHERE id=?', (scope.instance_id,)
        ).fetchone()
        assert instance['effective_profile_version_id'] == old['execution_profile_version_id']
        assert strict_json_object(session['model_window'])['state'] == 'CLOSED'
        assert (
            connection.execute(
                'SELECT status FROM code_authorizations WHERE id=?', (old['authorization_id'],)
            ).fetchone()[0]
            == 'RETIRED'
        )
    # The original accepted result is stable after the task adopts another pair.
    assert (
        client.post(path + '/configuration', json=data, headers={'Idempotency-Key': key}).json()[
            'data'
        ]
        == receipt
    )

    if mode == 'model-limits':
        from backend.app.code_tasks.coding_model_admission import effective_coding_binding

        with database.transaction() as connection:
            binding = effective_coding_binding(
                connection,
                runtime.catalog,
                {admission.evidence_ref: admission},
                ingress.window,
                'walle-code',
                operation_time(None),
            )
        assert binding.profile_version_id == profile
        assert binding.max_requests == content['limits']['max_model_requests']
        assert binding.max_consecutive_failures == content['limits']['max_consecutive_failures']
        assert binding.contract.permitted_output == 50
        assert scope.send_timeout_seconds == content['limits']['send_timeout_seconds']

    if mode == 'integrity':
        from backend.app.code_tasks.task_configuration_effective import (
            effective_control_application,
        )
        from backend.app.code_tasks.task_configuration_live_records import (
            live_configuration_records,
        )
        from backend.app.infrastructure.database import StorageUnavailable

        with database.transaction() as connection:
            operation = connection.execute(
                'SELECT * FROM code_operations WHERE id=?', (identity,)
            ).fetchone()
            for field in ('control_generation', 'session_id'):
                forged = {**dict(operation), field: operation[field] + 1}
                with pytest.raises(StorageUnavailable):
                    live_configuration_records(connection, forged)

        class RollbackRetainedFixture(Exception):
            pass

        immutable_changes = [
            ("UPDATE code_operations SET status='CANCELLED' WHERE id=?", (identity,)),
            (
                'UPDATE code_operation_steps SET result_ref=? WHERE operation_id=? AND step_no=4',
                (canonical_input({'configuration_application_id': identity}), identity),
            ),
            (
                'UPDATE code_operation_steps SET external_identity=? WHERE operation_id=? AND step_no=1',
                (canonical_input({'source': {}}), identity),
            ),
        ]
        for statement, parameters in immutable_changes:
            with (
                database.transaction(write=True) as connection,
                pytest.raises(sqlite3.IntegrityError),
            ):
                connection.execute(statement, parameters)
        with pytest.raises(RollbackRetainedFixture), database.transaction(write=True) as connection:
            connection.execute(
                "UPDATE code_authorizations SET status='RETIRED' WHERE id=?", (grant,)
            )
            task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
            with pytest.raises(StorageUnavailable):
                effective_control_application(
                    connection,
                    task,
                    instance_id=ingress.window.instance_id,
                    launch_profile_id=old['execution_profile_version_id'],
                )
            # Use the original transaction rollback; SAVEPOINT is forbidden.
            raise RollbackRetainedFixture()
        assert client.get(path).status_code == 200

    if mode == 'repeat':
        latest, following_profile, following_grant, following_content = target_pair(idle_task)
        next_input = {
            'expected_state_version': latest['state_version'],
            'execution_profile_version_id': following_profile,
            'authorization_id': following_grant,
            'reason': '再次明确调整查询等待限制',
        }
        with resources(fixture_snapshot(following_content)):
            next_result = client.post(
                path + '/configuration', json=next_input, headers={'Idempotency-Key': str(uuid4())}
            )
        assert next_result.status_code == 202, next_result.text
        assert flow.advance_live_configuration(runtime, driver, cancelled=lambda: False)
        latest_view = client.get(path)
        assert latest_view.status_code == 200, latest_view.text
        assert latest_view.json()['data']['execution_profile_version_id'] == following_profile
        assert latest_view.json()['data']['authorization_id'] == following_grant
        assert client.get(path + f'/operations/{identity}').json()['data']['status'] == 'SUCCEEDED'
        with database.transaction() as connection:
            task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
            session = connection.execute(
                'SELECT * FROM code_sessions WHERE id=?', (ingress.window.execution_session_id,)
            ).fetchone()
            adopted_scope = original_active_session_scope(connection, task, session)
            assert adopted_scope.profile_id == old['execution_profile_version_id']
            assert adopted_scope.authorization_id == following_grant
            assert (
                connection.execute(
                    "SELECT count(*) FROM code_operations WHERE task_id=? AND operation_type='APPLY_CONFIGURATION'",
                    (task_id,),
                ).fetchone()[0]
                == 2
            )


@pytest.mark.parametrize('kind', ['HANDOFF_ROLE', 'VERIFY_CANDIDATE', 'REPAIR'])
def test_configuration_action_respects_existing_operation_before_reading_transition_source(
    idle_task, monkeypatch, kind
):
    database, _, _, _, _, task_id, _, _, _ = idle_task
    with database.transaction() as connection:
        task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        # A role transition may have retired its source but not created a target.
        task = {**dict(task), 'active_session_id': None}
        data = {
            'active_operations': [{'id': 900, 'operation_type': kind, 'status': 'RUNNING'}],
            'available_actions': [
                {
                    'action': 'APPLY_CONFIGURATION',
                    'enabled': False,
                    'reason_code': 'INVALID_STATE',
                    'related_id': None,
                }
            ],
        }

        def incomplete_source(*_):
            raise AssertionError('An incomplete active operation cannot have an idle source')

        monkeypatch.setattr(flow, 'idle_configuration_source', incomplete_source)
        flow.project_live_configuration_activity(connection, task, data, True)
    assert data['available_actions'][0] == {
        'action': 'APPLY_CONFIGURATION',
        'enabled': False,
        'reason_code': 'OPERATION_IN_PROGRESS',
        'related_id': None,
    }


def test_original_launch_grant_cannot_change_without_verified_c39_history(idle_task):
    from backend.app.code_tasks.task_configuration_effective import effective_control_application
    from backend.app.infrastructure.database import StorageUnavailable

    database, _, _, ingress, _, task_id, _, _, _ = idle_task
    with database.transaction() as connection:
        task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        assert (
            effective_control_application(
                connection,
                task,
                instance_id=ingress.window.instance_id,
                launch_profile_id=task['execution_profile_version_id'],
            )
            is None
        )
        with pytest.raises(StorageUnavailable):
            effective_control_application(
                connection,
                {**dict(task), 'authorization_id': task['authorization_id'] + 1},
                instance_id=ingress.window.instance_id,
                launch_profile_id=task['execution_profile_version_id'],
            )


def test_native_read_scope_stays_unbound_until_real_permission_admission(idle_task):
    field = 'read_roots'
    database, _, client, _, _, task_id, _, _, _ = idle_task
    old, version, _, content = target_pair(idle_task, 'authorization-only')
    with database.transaction() as connection:
        original_grant = project_grant(
            connection.execute(
                'SELECT * FROM code_authorizations WHERE id=?',
                (old['authorization_id'],),
            ).fetchone()
        )
        operations_before = connection.execute(
            'SELECT count(*) FROM code_operations WHERE task_id=?', (task_id,)
        ).fetchone()[0]
    proposed = deepcopy(original_grant['scope'])
    proposed[field] = ['test-new-read-root']
    assert proposed[field] != original_grant['scope'][field]
    snapshot = fixture_snapshot(content)
    snapshot['SCOPE'] = [
        {
            'ready': False,
            'value': {
                'scope_ref': 'test-new-read-root',
                'scope_kind': 'READ_ROOT',
            },
        }
    ]
    with resources(snapshot):
        granted = approve(client, {'profile_version_id': version, 'scope': proposed})
        assert granted.status_code == 201, granted.text
        grant = granted.json()['data']['resource_id']
        response = client.post(
            f'/api/v1/code-tasks/{task_id}/configuration',
            json={
                'expected_state_version': old['state_version'],
                'execution_profile_version_id': version,
                'authorization_id': grant,
                'reason': '明确提出原生授权变化',
            },
            headers={'Idempotency-Key': str(uuid4())},
        )
    assert response.status_code == 503, response.text
    assert response.json()['error']['code'] == 'CONFIG_NOT_READY'
    with database.transaction() as connection:
        current = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        assert current['state_version'] == old['state_version']
        assert current['authorization_id'] == old['authorization_id']
        assert (
            connection.execute(
                'SELECT count(*) FROM code_operations WHERE task_id=?', (task_id,)
            ).fetchone()[0]
            == operations_before
        )
        assert connection.execute(
            'SELECT task_id,status FROM code_authorizations WHERE id=?', (grant,)
        ).fetchone()[:] == (None, 'APPROVED_UNBOUND')


@pytest.mark.parametrize(
    ('frontier', 'status', 'corrupt'),
    [
        (3, 'RUNNING', False),
        (3, 'UNKNOWN', False),
        (4, 'RUNNING', False),
        (4, 'UNKNOWN', False),
        (3, 'RUNNING', True),
    ],
)
def test_independent_apply_frontier_is_readable_and_stop_preserves_quiet_proof(
    idle_task, frontier, status, corrupt
):
    database, runtime, client, ingress, _, task_id, _, _, _ = idle_task
    old, profile, grant, content = target_pair(idle_task)
    path = f'/api/v1/code-tasks/{task_id}'
    with resources(fixture_snapshot(content)):
        accepted = client.post(
            path + '/configuration',
            json={
                'expected_state_version': old['state_version'],
                'execution_profile_version_id': profile,
                'authorization_id': grant,
                'reason': '明确调整控制限制',
            },
            headers={'Idempotency-Key': str(uuid4())},
        )
    assert accepted.status_code == 202, accepted.text
    identity = accepted.json()['data']['operation_id']
    with database.transaction() as connection:
        current = flow._current(connection, identity)
    source, scope = current[4:]
    driver = ReadOnlyDriver(idle_task)
    observation = driver.observe_control_configuration(
        scope, ingress.window, source['credential_ref'], lambda: None
    )
    at = operation_time(None)
    with database.transaction(write=True) as connection:
        current = flow._current(connection, identity)
        quiet, _ = flow._verified_observation(connection, current, observation, at)
        quiet_id = flow._observe_record(connection, current, at, result='VERIFIED', proof=quiet)
        if corrupt:
            quiet['guard_receipt_sha256'] = '0' * 64
        connection.execute(
            """UPDATE code_operation_steps SET status='SUCCEEDED',started_at=?,ended_at=?,
               last_observed_at=?,result_ref=? WHERE operation_id=? AND step_no=2""",
            (
                at,
                at,
                at,
                canonical_input({'quiesce_observation_id': quiet_id, 'proof': quiet}),
                identity,
            ),
        )
        if frontier == 4:
            connection.execute(
                """UPDATE code_operation_steps SET status='SUCCEEDED',started_at=?,ended_at=?,
                   last_observed_at=?,result_ref=? WHERE operation_id=? AND step_no=3""",
                (
                    at,
                    at,
                    at,
                    canonical_input({'configuration_application_id': current[2]['id']}),
                    identity,
                ),
            )
        connection.execute(
            """UPDATE code_operation_steps SET status=?,started_at=?,last_observed_at=?
               WHERE operation_id=? AND step_no=?""",
            (status, at, at, identity, frontier),
        )
        if status == 'UNKNOWN':
            connection.execute(
                "UPDATE code_operations SET status='UNKNOWN',failure_code='EXTERNAL_RESULT_UNKNOWN' WHERE id=?",
                (identity,),
            )
            connection.execute(
                "UPDATE code_configuration_applications SET status='UNKNOWN' WHERE operation_id=?",
                (identity,),
            )
            connection.execute(
                "UPDATE code_authorizations SET status='APPLY_UNKNOWN' WHERE id=?", (grant,)
            )
    original = client.get(path + f'/operations/{identity}')
    if corrupt:
        assert original.status_code == 503, original.text
        return
    assert original.status_code == 200, original.text
    public = original.json()['data']
    assert public['steps'][frontier - 1]['status'] == status
    assert public['steps'][1]['result_ref'] == {'scope': 'CURRENT_SESSION'}
    assert all(step['external_identity'] is None for step in public['steps'])
    task = client.get(path)
    assert task.status_code == 200, task.text
    assert task.json()['data']['configuration_application']['status'] != 'APPLIED'
    # The existing read-only stage2 worker cannot reinterpret a later possible-send step.
    assert not flow.advance_live_configuration(runtime, driver, cancelled=lambda: False)
    assert len(driver.calls) == 1
    with database.transaction(write=True) as connection:
        flow.interrupt_live_configurations(connection, task_id, operation_time(None))
    stopped = client.get(path + f'/operations/{identity}')
    assert stopped.status_code == 200, stopped.text
    steps = stopped.json()['data']['steps']
    assert [step['status'] for step in steps] == (
        ['SUCCEEDED'] * (frontier - 1) + ['CANCELLED'] * (5 - frontier)
    )
    assert steps[1] == public['steps'][1]
