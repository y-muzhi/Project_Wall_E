"""Original C39 receipt, pending grant, and evidence-gated activation on Schema200."""

from time import monotonic, sleep
from uuid import uuid4

import pytest

from backend.app.code_tasks import task_start_basis
from backend.app.code_tasks.task_initial_configuration import (
    InitialConfigurationObservation,
    InitialNativeSession,
    current_effective_configuration,
)
from backend.app.code_tasks.task_start_instance import advance_start_instance
from backend.app.code_tasks.task_start_session import advance_start_session
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.tests.code_tasks.test_authorizations import approve, scope
from backend.tests.code_tasks.test_execution_profile_versions import publish, resources
from backend.tests.code_tasks.test_task_start import (
    isolated_readiness,
    original_operation,
    start,
    stop,
)
from backend.tests.code_tasks.test_task_start_basis import prepare
from backend.tests.code_tasks.test_task_start_instance import _evidence
from backend.tests.code_tasks.test_task_start_session import NativeDriver
from backend.tests.code_tasks.test_task_stop import seed_task
from backend.tests.infrastructure.test_v20_command_http import package, service


def select_pair(client, task_id, *, version=1):
    with resources():
        profile = publish(client).json()['data']['resource_id']
        approved = approve(client, {'profile_version_id': profile, 'scope': scope()})
        assert approved.status_code == 201, approved.text
        grant = approved.json()['data']['resource_id']
        key = str(uuid4())
        path = f'/api/v1/code-tasks/{task_id}/configuration'
        data = {
            'expected_state_version': version,
            'execution_profile_version_id': profile,
            'authorization_id': grant,
            'reason': '明确选用已批准配置',
        }
        result = client.post(path, json=data, headers={'Idempotency-Key': key})
    assert result.status_code == 202, result.text
    receipt = result.json()['data']
    assert receipt['state_version'] == version + 1
    assert receipt['operation_status'] == 'RUNNING'
    # Original replay requires neither resource discovery nor a fresh task version.
    assert client.post(path, json=data, headers={'Idempotency-Key': key}).json()['data'] == receipt
    readback = client.get(
        '/api/v1/code-command-receipts',
        params={'method': 'POST', 'path': path, 'request_key': key},
    )
    assert readback.status_code == 200, readback.text
    assert readback.json()['data']['original_outcome']['data'] == receipt
    conflict = client.post(
        path, json={**data, 'reason': '不同内容'}, headers={'Idempotency-Key': key}
    )
    assert conflict.status_code == 409, conflict.text
    return receipt, profile, grant


@pytest.mark.parametrize('queued_start', [False, True])
def test_prepared_configuration_keeps_original_pending_until_start_or_stop(
    service, isolated_readiness, queued_start
):
    database, app, client = service
    task_id = seed_task(database, app.state.walle_runtime, client)
    receipt, profile, grant = select_pair(client, task_id)
    path = f'/api/v1/code-tasks/{task_id}'
    operation = client.get(path + f'/operations/{receipt["operation_id"]}')
    assert operation.status_code == 200, operation.text
    assert [row['status'] for row in operation.json()['data']['steps']] == ['SUCCEEDED'] * 3 + [
        'PENDING'
    ]
    detail = client.get(path)
    assert detail.status_code == 200, detail.text
    data = detail.json()['data']
    assert data['execution_profile_version_id'] == profile
    assert data['authorization_id'] == grant
    assert data['configuration_application']['status'] == 'PENDING'
    assert data['configuration_application']['evidence_result'] is None
    with database.transaction() as connection:
        assert [
            row['status']
            for row in connection.execute('SELECT status FROM code_authorizations ORDER BY id')
        ] == ['RETIRED', 'BOUND_PENDING_APPLY']
        assert connection.execute('SELECT count(*) FROM code_instances').fetchone()[0] == 0
    if queued_start:
        starting = start(client, task_id, receipt['state_version'])
        assert starting.status_code == 202, starting.text
        start_id = starting.json()['data']['operation_id']
    stopped = stop(client, task_id, receipt['state_version'] + int(queued_start))
    assert stopped.status_code == 202, stopped.text
    stop_id = stopped.json()['data']['operation_id']
    deadline = monotonic() + 7
    while original_operation(client, stop_id)['status'] == 'PENDING':
        assert monotonic() < deadline
        sleep(0.04)
    assert original_operation(client, stop_id)['status'] == 'SUCCEEDED'
    assert original_operation(client, receipt['operation_id'])['status'] == 'CANCELLED'
    if queued_start:
        assert original_operation(client, start_id)['status'] == 'CANCELLED'
    detail = client.get(path)
    assert detail.status_code == 200, detail.text
    assert detail.json()['data']['configuration_application']['status'] == 'FAILED'


@pytest.mark.parametrize('verified', [True, False])
def test_original_start_requires_real_configuration_evidence_for_selected_pair(
    service, tmp_path, isolated_readiness, verified
):
    database, app, client = service
    runtime = app.state.walle_runtime
    selected = []

    def before_start(task_id):
        receipt, profile, grant = select_pair(client, task_id)
        selected.extend((receipt['operation_id'], profile, grant))
        return receipt['state_version']

    class InstanceDriver:
        def start(self, original, checkpoint, *, cancelled):
            checkpoint()
            return _evidence(original.claim)

    class SessionDriver(NativeDriver):
        def create_session(self, session, checkpoint):
            native = super().create_session(session, checkpoint)
            assert session.profile_id == selected[1] and session.authorization_id == selected[2]
            if not verified:
                return native
            return InitialNativeSession(
                native,
                InitialConfigurationObservation(
                    'opencode-bundle:sha256:' + 'a' * 64, 'e' * 64, 'f' * 64, 'isolated-backend'
                ),
            )

    with PrivatePackageGuard(create_private_package(tmp_path / 'staged-config-start')) as parent:
        task_id, _, _, _, receipt = prepare(
            database, app, client, parent, before_start=before_start
        )
        start_id = receipt['operation_id']
        assert task_start_basis.advance_start_basis(runtime, parent, cancelled=lambda: False)
        with database.transaction(write=True) as connection:
            at = connection.execute(
                'SELECT ended_at FROM code_operation_steps WHERE operation_id=? AND step_no=2',
                (start_id,),
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
                (report, at, at, at, start_id),
            )
        assert advance_start_instance(
            runtime, parent, cancelled=lambda: False, driver=InstanceDriver()
        )
        driver = SessionDriver()
        assert advance_start_session(runtime, parent, cancelled=lambda: False, driver=driver)
        original = original_operation(client, selected[0])
        if verified:
            assert original['status'] == 'SUCCEEDED'
            assert original['steps'][-1]['result_ref']['start_operation_id'] == start_id
            assert advance_start_session(runtime, parent, cancelled=lambda: False, driver=driver)
        else:
            assert original['status'] == 'UNKNOWN'
            assert not advance_start_session(
                runtime, parent, cancelled=lambda: False, driver=driver
            )
        with database.transaction() as connection:
            application = connection.execute(
                'SELECT * FROM code_configuration_applications'
            ).fetchall()
            assert len(application) == 1 and application[0]['operation_id'] == selected[0]
            assert application[0]['status'] == ('APPLIED' if verified else 'UNKNOWN')
            grant = connection.execute(
                'SELECT status FROM code_authorizations WHERE id=?', (selected[2],)
            ).fetchone()
            assert grant[0] == ('EFFECTIVE' if verified else 'BOUND_PENDING_APPLY')
            if verified:
                task = connection.execute(
                    'SELECT * FROM code_tasks WHERE id=?', (task_id,)
                ).fetchone()
                claim = driver.calls[0][1]
                assert (
                    current_effective_configuration(connection, task, start_scope=claim)['id']
                    == application[0]['id']
                )
