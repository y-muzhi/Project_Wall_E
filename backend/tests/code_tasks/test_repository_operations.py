"""Actual API17 original repository progress, including pre-resource registration."""

from dataclasses import replace
from unittest.mock import patch

import pytest

from backend.app.code_tasks.repository_acceptance import accept_repository_operation
from backend.app.code_tasks.repository_git_runner import (
    RegistrationReadLimits,
    RepositoryRegistrationRun,
)
from backend.app.code_tasks.repository_registration import (
    publish_repository_registration,
    start_repository_registration,
)
from backend.app.infrastructure.git_repository_location import RepositoryLocationError
from backend.app.infrastructure.guard_controller_binding import bind_backend_controller
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal
from backend.app.infrastructure.windows_local_paths import PathBoundaryError
from backend.app.infrastructure.windows_private_package import create_private_package
from backend.tests.code_tasks.test_repository_acceptance import request
from backend.tests.code_tasks.test_repository_registration import capture
from backend.tests.infrastructure.test_v20_command_http import package, service


def accept(app, repository_id=None):
    original = request(repository_id)
    runtime = app.state.walle_runtime
    result = accept_repository_operation(runtime, original)
    assert result['code'] == 'OPERATION_ACCEPTED', result
    return original, result['data']['operation_id']


def test_actual_read_before_repository_exists_preserves_original_ids_and_no_side_effects(service):
    database, app, client = service
    original, operation_id = accept(app)
    with patch(
        'backend.app.code_tasks.repository_registration.capture_repository_registration',
        side_effect=AssertionError('GET must not inspect'),
    ):
        first = client.get(f'/api/v1/code-operations/{operation_id}')
        second = client.get(f'/api/v1/code-operations/{operation_id}')
    assert first.status_code == second.status_code == 200, first.text
    data = first.json()['data']
    assert data == second.json()['data']
    assert first.json()['meta']['request_id'] != second.json()['meta']['request_id']
    assert data['status'] == 'PENDING'
    assert data['id'] == operation_id and data['resource_id'] == 1
    assert data['fixed_input'] == {'name': 'fixture'}
    assert data['task_id'] is data['testing_task_id'] is data['content_capture'] is None
    assert data['idempotency_key'] == original.idempotency_key
    assert len(data['steps']) == 2 and data['steps'][0]['status'] == 'PENDING'
    assert 'C:\\fixture' not in first.text
    assert 'pagination' not in first.json()['meta']
    with database.transaction() as c:
        assert c.execute('SELECT count(*) FROM code_repositories').fetchone()[0] == 0
        assert c.execute('SELECT count(*) FROM code_tasks').fetchone()[0] == 0
        assert c.execute('SELECT count(*) FROM code_operations').fetchone()[0] == 1


def test_progress_then_complete_original_repository_and_immutable_202(service):
    _, app, client = service
    original, operation_id = accept(app)
    runtime = app.state.walle_runtime
    start_repository_registration(runtime, operation_id)
    running = client.get(f'/api/v1/code-operations/{operation_id}').json()['data']
    assert running['status'] == running['steps'][0]['status'] == 'RUNNING'
    assert running['steps'][1]['status'] == 'PENDING'
    publish_repository_registration(runtime, operation_id, capture())
    response = client.get(f'/api/v1/code-operations/{operation_id}')
    assert response.status_code == 200, response.text
    data = response.json()['data']
    assert data['status'] == 'SUCCEEDED'
    assert data['steps'][0]['result_ref'] is None
    assert data['steps'][1]['result_ref'] == {'repository_id': 1}
    assert runtime.commands().command_receipt(original.command.scope)['original_http_status'] == 202


def test_actual_failed_operation_is_200_with_original_failure_code_not_empty(service):
    database, app, client = service
    runtime = app.state.walle_runtime
    source = database.path.parent / 'unregistered-empty-directory'
    source.mkdir()
    original = replace(request(), root_path=str(source))
    accepted = accept_repository_operation(runtime, original)
    operation_id = accepted['data']['operation_id']
    binding = bind_backend_controller(runtime.commands().process_lock, 'a' * 64)
    with LaunchJournal(
        create_private_package(database.path.parent / 'failed-register-evidence')
    ) as journal:
        runner = RepositoryRegistrationRun(
            runtime,
            operation_id,
            object(),
            binding,
            journal,
            private_roots=(journal.root,),
            limits=RegistrationReadLimits(4096, 4096, 256, 32768, 4096, 5),
        )
        with (
            patch(
                'backend.app.code_tasks.repository_git_dispatch.exchange_guard_control_git',
                side_effect=AssertionError('Invalid source must not reach Guard'),
            ),
            pytest.raises((PathBoundaryError, RepositoryLocationError)) as error,
        ):
            runner.run(cancelled=lambda: False)
        assert error.value.retained_owner is runner
        assert not runner._owners and runner._command is None
    response = client.get(f'/api/v1/code-operations/{operation_id}')
    assert response.status_code == 200, response.text
    data = response.json()['data']
    assert data['failure_code'] == 'SOURCE_UNSUPPORTED'
    assert data['status'] == data['steps'][0]['status'] == 'FAILED'
    assert data['ended_at'] == data['steps'][0]['ended_at']
    assert data['steps'][1]['status'] == 'PENDING'
    assert accept_repository_operation(runtime, original) == accepted
    assert runtime.commands().command_receipt(original.command.scope)['original_http_status'] == 202
    assert str(source) not in response.text
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_repositories').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM code_tasks').fetchone()[0] == 0


def test_private_external_identity_is_not_returned(service):
    database, app, client = service
    _, operation_id = accept(app)
    with database.transaction(write=True) as c:
        c.execute(
            'UPDATE code_operation_steps SET external_identity=? WHERE operation_id=? AND step_no=1',
            ('{"guard_run_ref":"private-evidence","job_refs":["C:\\\\private"]}', operation_id),
        )
    response = client.get(f'/api/v1/code-operations/{operation_id}')
    assert response.status_code == 200, response.text
    assert response.json()['data']['steps'][0]['external_identity'] == {}
    assert 'private-evidence' not in response.text and 'job_refs' not in response.text


def test_missing_final_observation_is_storage_failure_not_fake_success(service):
    database, app, client = service
    _, registration = accept(app)
    runtime = app.state.walle_runtime
    start_repository_registration(runtime, registration)
    publish_repository_registration(runtime, registration, capture())
    _, operation_id = accept(app, 1)
    with database.transaction(write=True) as c:
        c.execute(
            'UPDATE code_operation_steps SET result_ref=? WHERE operation_id=? AND step_no=2',
            ('{"observation_id":999}', operation_id),
        )
    response = client.get(f'/api/v1/code-operations/{operation_id}')
    assert response.status_code == 503, response.text
    assert response.json()['error']['code'] == 'STORAGE_UNAVAILABLE'
    assert response.json()['data'] is None


@pytest.mark.parametrize(
    'path',
    [
        '/api/v1/code-operations/01',
        '/api/v1/code-operations/0',
        '/api/v1/code-operations/true',
        '/api/v1/code-operations/9007199254740992',
        '/api/v1/code-operations/1?refresh=true',
    ],
)
def test_invalid_ids_or_unknown_query_are_rejected(service, path):
    _, _, client = service
    assert client.get(path).status_code == 422


def test_absent_operation_and_write_key_on_get(service):
    _, _, client = service
    assert client.get('/api/v1/code-operations/1').status_code == 404
    response = client.get(
        '/api/v1/code-operations/1', headers={'Idempotency-Key': request().idempotency_key}
    )
    assert response.status_code == 422


def test_stopped_http_admission_uses_code_error_contract(service):
    _, app, client = service
    app.state.walle_worker.accepting = False
    response = client.get('/api/v1/code-operations/1')
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'STORAGE_UNAVAILABLE'


def test_completed_refresh_reads_its_original_observation_reference(service):
    from backend.app.code_tasks.repository_observation_publish import (
        publish_repository_observation,
        start_repository_observation,
    )
    from backend.tests.code_tasks.test_repository_observation_publish import (
        capture as observation_capture,
    )

    database, app, client = service
    _, registration = accept(app)
    runtime = app.state.walle_runtime
    start_repository_registration(runtime, registration)
    publish_repository_registration(runtime, registration, capture())
    _, operation_id = accept(app, 1)
    start_repository_observation(runtime, operation_id)
    with database.transaction(write=True) as c:
        at = c.execute(
            'SELECT started_at FROM code_operations WHERE id=?', (operation_id,)
        ).fetchone()[0]
        c.execute(
            "UPDATE code_operation_steps SET status='SUCCEEDED',started_at=?,ended_at=? WHERE operation_id=? AND step_no=1",
            (at, at, operation_id),
        )
        c.execute(
            "UPDATE code_operation_steps SET status='RUNNING',started_at=? WHERE operation_id=? AND step_no=2",
            (at, operation_id),
        )
    observation_id = publish_repository_observation(runtime, operation_id, observation_capture())
    response = client.get(f'/api/v1/code-operations/{operation_id}')
    assert response.status_code == 200, response.text
    data = response.json()['data']
    assert data['status'] == 'SUCCEEDED'
    assert data['fixed_input'] == {'repository_id': 1}
    assert data['steps'][1]['result_ref'] == {'observation_id': observation_id}
    observed = client.get(f'/api/v1/code-repositories/1/observations/{observation_id}')
    assert observed.status_code == 200
    assert observed.json()['data']['operation_id'] == operation_id
