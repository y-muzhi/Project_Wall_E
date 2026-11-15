"""Original START, durable workspace, and stop fencing with isolated Schema200."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.code_tasks import task_start, task_start_workspace
from backend.app.code_tasks.repository_baseline_query import BaselineQueryResult
from backend.app.code_tasks.workspace_materialization import (
    FixedWorkspaceStage,
    WorkspaceMaterializationError,
)
from backend.app.infrastructure.content_manifest import ContentEntry
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.service import create_app
from backend.tests.code_tasks.test_task_stop import seed_task
from backend.tests.infrastructure.test_v20_command_http import package, service


def start(client, task_id, version=1, key=None, **body):
    return client.post(
        f'/api/v1/code-tasks/{task_id}/start',
        json={'expected_state_version': version, **body},
        headers={'Idempotency-Key': key or str(uuid4())},
    )


def stop(client, task_id, version):
    return client.post(
        f'/api/v1/code-tasks/{task_id}/terminate',
        json={'expected_state_version': version},
        headers={'Idempotency-Key': str(uuid4())},
    )


def original_operation(client, identity):
    reply = client.get(f'/api/v1/code-operations/{identity}')
    assert reply.status_code == 200, reply.text
    return reply.json()['data']


@pytest.fixture
def isolated_readiness(monkeypatch):
    def admitted(*_):
        return None

    monkeypatch.setattr(task_start, '_check_start_readiness', admitted)
    monkeypatch.setattr(task_start_workspace, '_check_start_readiness', admitted)


def test_unconfigured_start_preserves_key_and_creates_no_workspace(service):
    database, app, client = service
    task_id = seed_task(database, app.state.walle_runtime, client)
    key = str(uuid4())
    unavailable = start(client, task_id, key=key)
    assert unavailable.status_code == 503, unavailable.text
    assert unavailable.json()['error']['code'] == 'CONFIG_NOT_READY'
    assert start(client, task_id, key=key, nonce='foreign').status_code == 422
    receipt = client.get(
        '/api/v1/code-command-receipts',
        params={
            'method': 'POST',
            'path': f'/api/v1/code-tasks/{task_id}/start',
            'request_key': key,
        },
    )
    assert receipt.json()['data']['lookup_status'] == 'NOT_FOUND', receipt.text
    with database.transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM code_operations WHERE operation_type='START'"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute('SELECT count(*) FROM code_workspaces').fetchone()[0] == 0


def test_concurrent_start_replay_and_new_key_are_bound_to_one_operation(
    service, isolated_readiness
):
    database, app, client = service
    task_id = seed_task(database, app.state.walle_runtime, client)
    keys = [str(uuid4()), str(uuid4())]
    with ThreadPoolExecutor(max_workers=2) as callers:
        first, second = callers.map(lambda key: start(client, task_id, key=key), keys)
    assert sorted((first.status_code, second.status_code)) == [202, 409]
    original, key = (first, keys[0]) if first.status_code == 202 else (second, keys[1])
    data = original.json()['data']
    assert data == {
        'task_id': task_id,
        'operation_id': data['operation_id'],
        'operation_status': 'PENDING',
        'task_status': 'PENDING',
        'state_version': 2,
    }
    duplicate = start(client, task_id, version=2)
    assert duplicate.json()['error']['code'] == 'OPERATION_IN_PROGRESS'
    assert duplicate.json()['error']['details']['related_operation_id'] == data['operation_id']
    original_read = original_operation(client, data['operation_id'])
    assert original_read['status'] == 'PENDING'
    assert [row['step_type'] for row in original_read['steps']] == list(task_start.START_STEPS)
    stopped = stop(client, task_id, 2)
    assert stopped.status_code == 202, stopped.text
    stop_id = stopped.json()['data']['operation_id']
    deadline = monotonic() + 5
    while original_operation(client, stop_id)['status'] != 'SUCCEEDED':
        assert monotonic() < deadline
        sleep(0.03)
    cancelled = original_operation(client, data['operation_id'])
    assert cancelled['status'] == 'CANCELLED' and cancelled['started_at'] is None
    assert all(
        step['status'] == 'CANCELLED' and step['external_identity'] is None
        for step in cancelled['steps']
    )
    detail = client.get(f'/api/v1/code-tasks/{task_id}')
    assert detail.status_code == 200, detail.text
    assert detail.json()['data']['status'] == 'TERMINATED'
    assert detail.json()['data']['state_version'] == 4
    assert start(client, task_id, key=key).json()['data'] == data
    assert start(client, task_id, version=2, key=key).status_code == 409
    with database.transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM code_operations WHERE operation_type='START'"
            ).fetchone()[0]
            == 1
        )
        assert connection.execute('SELECT count(*) FROM code_workspaces').fetchone()[0] == 0


@pytest.mark.parametrize('stopping', [False, True])
def test_original_stage_and_ready_publication_or_late_stop(
    service,
    tmp_path,
    isolated_readiness,
    stopping,
):
    database, app, client = service
    runtime = app.state.walle_runtime
    task_id = seed_task(database, runtime, client)
    first = start(client, task_id)
    assert first.status_code == 202, first.text
    original_id = first.json()['data']['operation_id']
    raw = b'\xef\xbb\xbffixed\r\n\0\xff'
    entry = ContentEntry(
        'fixture.bin', '100755', 'a' * 40, len(raw), hashlib.sha256(raw).hexdigest()
    )

    class StageActor:
        def restore_snapshot(
            self, snapshot_id, _frames, *, parent, nonce, check_active, cancelled, record_stage
        ):
            del cancelled
            operation = original_operation(client, original_id)
            assert operation['steps'][0]['status'] == 'RUNNING'
            assert operation['steps'][0]['external_identity'] == {}
            assert not list(parent.path.iterdir())
            stage = FixedWorkspaceStage(
                parent,
                nonce,
                check_active,
                record_stage=lambda identity: record_stage(identity, 'a' * 32),
            )
            assert (parent.path / (nonce + '.workspace-stage.json')).is_file()
            stage.consume(entry, raw)
            result = stage.publish(BaselineQueryResult({'id': snapshot_id}, (entry,)), lambda: None)
            if stopping:
                stopped = stop(client, task_id, 2)
                assert stopped.status_code == 202, stopped.text
            return result

    with PrivatePackageGuard(create_private_package(tmp_path / 'working')) as parent:
        if stopping:
            with pytest.raises(WorkspaceMaterializationError, match='FENCED'):
                task_start_workspace.advance_workspace_start(
                    runtime, StageActor(), None, parent, cancelled=lambda: False
                )
        else:
            task_start_workspace.advance_workspace_start(
                runtime, StageActor(), None, parent, cancelled=lambda: False
            )
        assert [p.read_bytes() for p in parent.path.glob('working-*/fixture.bin')] == [raw]
        before = list(parent.path.iterdir())
        task_start_workspace.advance_workspace_start(
            runtime, StageActor(), None, parent, cancelled=lambda: False
        )
        assert list(parent.path.iterdir()) == before

    observed = original_operation(client, original_id)
    assert observed['status'] == ('UNKNOWN' if stopping else 'RUNNING')
    step = observed['steps'][0]
    assert step['status'] == ('UNKNOWN' if stopping else 'SUCCEEDED')
    assert 'nonce' not in str(observed) and 'canonical_path' not in str(observed)
    detail = client.get(f'/api/v1/code-tasks/{task_id}')
    assert detail.status_code == 200, detail.text
    assert detail.json()['data']['status'] == ('STOPPING' if stopping else 'PENDING')
    with database.transaction() as connection:
        task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        (workspace,) = connection.execute(
            'SELECT * FROM code_workspaces WHERE task_id=?', (task_id,)
        ).fetchall()
        assert workspace['status'] == ('UNKNOWN' if stopping else 'READY')
        assert task['status'] == ('STOPPING' if stopping else 'PENDING')
        assert task['workspace_id'] == (None if stopping else workspace['id'])
        assert step['result_ref'] == (None if stopping else {'workspace_id': workspace['id']})


def test_interrupted_allocation_becomes_unknown_on_actual_service_restart(
    package, tmp_path, isolated_readiness
):
    root, release = package
    database = Database(Path(root) / (str(uuid4()) + '.sqlite'), schema_release=release)
    database.initialize()
    app = create_app(database=database)
    key = str(uuid4())
    with PrivatePackageGuard(create_private_package(tmp_path / 'working')) as parent:
        with TestClient(app) as client:
            task_id = seed_task(database, app.state.walle_runtime, client)
            accepted = start(client, task_id, key=key).json()['data']
            allocation = task_start_workspace.reserve_workspace(app.state.walle_runtime, parent)
            assert allocation.operation_id == accepted['operation_id']
            assert list(parent.path.iterdir()) == []
        with TestClient(create_app(database=database)) as restarted:
            observed = original_operation(restarted, allocation.operation_id)
            assert observed['status'] == 'UNKNOWN'
            assert observed['steps'][0]['status'] == 'UNKNOWN'
            assert start(restarted, task_id, key=key).json()['data'] == accepted
            assert (
                start(restarted, task_id, version=2).json()['error']['code']
                == 'EXTERNAL_RESULT_UNKNOWN'
            )
            assert list(parent.path.iterdir()) == []
