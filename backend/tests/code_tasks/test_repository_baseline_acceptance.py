"""C05 acceptance commits the original fixed reservation without accessing Git."""

from dataclasses import dataclass, replace
from uuid import uuid4

import pytest

from backend.app.code_tasks.command_registry import registered_command
from backend.app.code_tasks.repository_acceptance import (
    accept_repository_operation,
    verify_saved_repository_acceptance,
)
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.shared.command_execution import operation_time
from backend.tests.code_tasks.test_execution_profile_versions import (
    fixture_snapshot,
    parents,
    publish,
    resources,
    seed_price,
)
from backend.tests.infrastructure.test_v20_command_http import package, service


@dataclass(frozen=True)
class BaselineInput:
    repository_id: int
    commit_oid: str
    execution_profile_version_id: int = 1
    key: str | None = None

    @property
    def command(self):
        return registered_command(
            'POST', f'/api/v1/code-repositories/{self.repository_id}/snapshots', self.key
        )

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {
            'repository_id': self.repository_id,
            'commit_oid': self.commit_oid,
            'execution_profile_version_id': self.execution_profile_version_id,
        }


@pytest.fixture
def repository_service(service):
    database, app, client = service
    parents(client)
    seed_price(database)
    with resources():
        assert publish(client).status_code == 201
    with database.transaction(write=True) as connection:
        for repository, format in ((1, 'sha1'), (2, 'sha256')):
            root = f'C:/isolated-baseline/{repository}'
            connection.execute(
                'INSERT INTO code_repositories VALUES(?,?,?,?,?,?)',
                (repository, 'test repository', root, root + '/.git', format, operation_time(None)),
            )
    return database, app.state.walle_runtime, client


def test_baseline_reserves_original_snapshot_and_four_steps_with_unready_model(repository_service):
    database, runtime, client = repository_service
    with resources():
        for identity, oid in ((1, 'a' * 40), (2, 'b' * 64)):
            original = BaselineInput(identity, oid, key=str(uuid4()))
            accepted = accept_repository_operation(runtime, original)
            assert accepted['code'] == 'OPERATION_ACCEPTED', accepted
            assert accepted['data'] == {
                'resource_kind': 'REPOSITORY',
                'resource_id': identity,
                'operation_id': identity,
                'operation_status': 'PENDING',
            }
            operation_id = accepted['data']['operation_id']
            fixed = {
                **original.business_input(),
                'snapshot_id': identity,
                'retention_ref': f'refs/walle/baselines/{identity}',
            }
            with database.transaction() as connection:
                operation = dict(
                    connection.execute(
                        'SELECT * FROM code_operations WHERE id=?', (operation_id,)
                    ).fetchone()
                )
                verify_saved_repository_acceptance(connection, operation)
                assert operation['fixed_input'] == canonical_input(fixed)
                altered = {**fixed, 'retention_ref': 'refs/heads/main'}
                with pytest.raises(StorageUnavailable, match='original repository acceptance'):
                    verify_saved_repository_acceptance(
                        connection, {**operation, 'fixed_input': canonical_input(altered)}
                    )
                steps = connection.execute(
                    'SELECT step_type,fixed_input,status FROM code_operation_steps '
                    'WHERE operation_id=? ORDER BY step_no',
                    (operation_id,),
                ).fetchall()
                assert [row['step_type'] for row in steps] == [
                    'VALIDATE_COMMIT',
                    'PIN_COMMIT',
                    'VERIFY_PINNED_OBJECTS',
                    'SAVE_BASELINE',
                ]
                assert all(row['fixed_input'] == operation['fixed_input'] for row in steps)
                assert all(row['status'] == 'PENDING' for row in steps)
                assert connection.execute('SELECT count(*) FROM code_snapshots').fetchone()[0] == 0
            lookup = client.get(
                '/api/v1/code-command-receipts',
                params={
                    'method': 'POST',
                    'path': original.command.path,
                    'request_key': original.key,
                },
            )
            assert lookup.status_code == 200, lookup.text
            assert lookup.json()['data']['original_http_status'] == 202
            assert lookup.json()['data']['operation_id'] == operation_id
            assert accept_repository_operation(runtime, original) == accepted
            changed = replace(original, commit_oid='c' * len(oid))
            assert accept_repository_operation(runtime, changed)['code'] == 'OPERATION_CONFLICT'


def test_invalid_or_unavailable_baseline_does_not_reserve_any_snapshot(repository_service):
    database, runtime, _ = repository_service
    with resources():
        for oid in ('HEAD', 'a' * 64, '0' * 40):
            original = BaselineInput(1, oid, key=str(uuid4()))
            result = accept_repository_operation(runtime, original)
            assert result['code'] == 'INVALID_INPUT', result
            assert result['details']['field_errors'][0]['field'] == 'commit_oid'
        missing = BaselineInput(1, 'a' * 40, execution_profile_version_id=99, key=str(uuid4()))
        assert accept_repository_operation(runtime, missing)['code'] == 'NOT_FOUND'
    original = BaselineInput(1, 'a' * 40, key=str(uuid4()))
    snapshot = fixture_snapshot()
    snapshot['CONTENT_POLICY'] = []
    with resources(snapshot):
        result = accept_repository_operation(runtime, original)
        assert result['code'] == 'CONFIG_NOT_READY', result
        assert result['details'] == {'capability_codes': ['Q20-CONTENT']}
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_operations').fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT count(*) FROM sequences WHERE entity_kind='CodeSnapshot'"
            ).fetchone()[0]
            == 0
        )
    with resources():
        assert accept_repository_operation(runtime, original)['code'] == 'OPERATION_ACCEPTED'


@pytest.mark.parametrize('verified_content_differs', [False, True])
def test_baseline_operation_get_reports_steps_without_private_source_or_proof(
    repository_service, verified_content_differs
):
    database, runtime, client = repository_service
    original = BaselineInput(1, 'a' * 40, key=str(uuid4()))
    with resources():
        receipt = accept_repository_operation(runtime, original)
    operation_id = receipt['data']['operation_id']
    path = '/api/v1/code-operations/' + str(operation_id)
    pending = client.get(path)
    assert pending.status_code == 200, pending.text
    assert pending.json()['data']['fixed_input'] == original.business_input()
    assert all(row['status'] == 'PENDING' for row in pending.json()['data']['steps'])
    now = operation_time(None)
    proof = {
        'commit_oid': original.commit_oid,
        'tree_oid': 'b' * 40,
        'repository_sha256': 'c' * 64,
        'closure_sha256': 'd' * 64,
        'content_sha256': 'e' * 64,
    }
    with database.transaction(write=True) as connection:
        connection.execute(
            "UPDATE code_operations SET status='RUNNING',started_at=? WHERE id=?",
            (now, operation_id),
        )
        connection.execute(
            "UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,external_identity=?,"
            'started_at=?,ended_at=?,last_observed_at=? WHERE operation_id=? AND step_no=1',
            (canonical_input(proof), '{"guard_run_ref":"private"}', now, now, now, operation_id),
        )
        pin = {
            key: {'private': 'never-in-operation-view'}
            for key in ('process', 'prepared', 'dispatch', 'committed', 'ref')
        }
        connection.execute(
            "UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,external_identity=?,"
            'started_at=?,ended_at=?,last_observed_at=? WHERE operation_id=? AND step_no=2',
            (canonical_input(pin), '{"git_baseline_pin":{}}', now, now, now, operation_id),
        )
    observed = client.get(path)
    assert observed.status_code == 200, observed.text
    progress = observed.json()['data']
    assert [step['status'] for step in progress['steps']] == [
        'SUCCEEDED',
        'SUCCEEDED',
        'PENDING',
        'PENDING',
    ]
    assert progress['content_capture'] is None
    assert progress['steps'][0]['external_identity'] == {}
    assert all(step['result_ref'] is None for step in progress['steps'])
    assert 'closure_sha256' not in observed.text and 'retention_ref' not in observed.text
    assert (
        'never-in-operation-view' not in observed.text and 'git_baseline_pin' not in observed.text
    )

    with database.transaction(write=True) as connection:
        connection.execute(
            "UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=? "
            'WHERE operation_id=? AND step_no=4',
            (canonical_input({'snapshot_id': 1}), operation_id),
        )
    assert client.get(path).status_code == 503
    with database.transaction(write=True) as connection:
        connection.execute(
            'INSERT INTO code_snapshots VALUES(?,?,?,?,?,?,?,?,?,?)',
            (
                1,
                1,
                operation_id,
                1,
                original.commit_oid,
                proof['tree_oid'],
                'refs/walle/baselines/1',
                'GIT20-BASELINE-1',
                now,
                now,
            ),
        )
        connection.execute(
            'UPDATE code_operation_steps SET result_ref=? WHERE operation_id=? AND step_no=3',
            (
                canonical_input(
                    {**proof, 'content_sha256': 'f' * 64} if verified_content_differs else proof
                ),
                operation_id,
            ),
        )
        connection.execute(
            "UPDATE code_operations SET status='SUCCEEDED',ended_at=? WHERE id=?",
            (now, operation_id),
        )
        connection.execute(
            "UPDATE code_operation_steps SET status='SUCCEEDED',ended_at=?,last_observed_at=? WHERE operation_id=?",
            (now, now, operation_id),
        )
    completed = client.get(path)
    if verified_content_differs:
        assert completed.status_code == 503, completed.text
    else:
        assert completed.status_code == 200, completed.text
        assert completed.json()['data']['steps'][3]['result_ref'] == {'snapshot_id': 1}
        detail = client.get('/api/v1/code-snapshots/1')
        assert detail.status_code == 503, detail.text
        assert detail.json()['error']['code'] == 'CONFIG_NOT_READY'
        assert client.get('/api/v1/code-snapshots/999').status_code == 404
        invalid = client.get('/api/v1/code-snapshots/1/files?page=100001')
        assert invalid.status_code == 422, invalid.text


def test_restart_selects_only_the_original_active_baseline_scope(repository_service):
    from backend.app.code_tasks.repository_baseline_pin import BaselinePinGitDispatch
    from backend.app.code_tasks.repository_git_recovery import _recover_baseline_step

    database, runtime, _ = repository_service
    original = BaselineInput(1, 'a' * 40, key=str(uuid4()))
    with resources():
        operation_id = accept_repository_operation(runtime, original)['data']['operation_id']
    now = operation_time(None)
    with database.transaction(write=True) as connection:
        connection.execute(
            "UPDATE code_operations SET status='RUNNING',started_at=? WHERE id=?",
            (now, operation_id),
        )
        connection.execute(
            "UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,external_identity=?,"
            'started_at=?,ended_at=?,last_observed_at=? WHERE operation_id=? AND step_no=1',
            ('{}', '{"original":"validation"}', now, now, now, operation_id),
        )
        assert _recover_baseline_step(connection, operation_id) is None
        connection.execute(
            "UPDATE code_operation_steps SET status='RUNNING',external_identity=?,started_at=?,"
            'last_observed_at=? WHERE operation_id=? AND step_no=2',
            ('{"original":"pin"}', now, now, operation_id),
        )
        assert _recover_baseline_step(connection, operation_id) is BaselinePinGitDispatch
        assert _recover_baseline_step(connection, operation_id) is BaselinePinGitDispatch
        assert tuple(
            connection.execute(
                'SELECT status,failure_code FROM code_operations WHERE id=?', (operation_id,)
            ).fetchone()
        ) == ('UNKNOWN', 'EXTERNAL_RESULT_UNKNOWN')
        assert [
            tuple(step)
            for step in connection.execute(
                'SELECT status,external_identity FROM code_operation_steps WHERE operation_id=? '
                'ORDER BY step_no',
                (operation_id,),
            )
        ] == [
            ('SUCCEEDED', '{"original":"validation"}'),
            ('UNKNOWN', '{"original":"pin"}'),
            ('PENDING', None),
            ('PENDING', None),
        ]


def test_snapshot_post_validates_public_input_and_requires_the_registered_worker(
    repository_service,
):
    database, _, client = repository_service
    path = '/api/v1/code-repositories/1/snapshots'
    headers = {'Idempotency-Key': str(uuid4())}
    assert (
        client.post(
            path, json={'commit_oid': 'HEAD', 'execution_profile_version_id': 1}, headers=headers
        ).status_code
        == 422
    )
    body = {'commit_oid': 'a' * 40, 'execution_profile_version_id': 1}
    assert client.post(path, json={**body, 'snapshot_id': 1}, headers=headers).status_code == 422
    unavailable = client.post(path, json=body, headers=headers)
    assert unavailable.status_code == 503
    assert unavailable.json()['error']['code'] == 'CONFIG_NOT_READY'
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_operations').fetchone()[0] == 0


def test_only_exact_baseline_replay_queues_a_hint_for_its_original_operation(repository_service):
    from threading import Lock
    from types import SimpleNamespace
    from unittest.mock import PropertyMock, patch

    from backend.app.code_tasks.repository_registration_worker import RepositoryRegistrationWorker

    database, _, client = repository_service
    worker = object.__new__(RepositoryRegistrationWorker)
    worker._observation_lock = Lock()
    worker._observation_hints = {}
    operation_ids = []
    collector = SimpleNamespace(request_pin_observation=operation_ids.append)
    path = '/api/v1/code-repositories/1/snapshots'
    headers = {'Idempotency-Key': str(uuid4())}
    body = {'commit_oid': 'a' * 40, 'execution_profile_version_id': 1}

    with (
        patch.object(client.app.state, 'walle_repository_registration', worker, create=True),
        patch.object(
            RepositoryRegistrationWorker, 'accepting', new_callable=PropertyMock, return_value=True
        ),
        patch.object(worker, 'wake'),
        resources(),
    ):
        original = client.post(path, json=body, headers=headers)
        assert original.status_code == 202, original.text
        assert not worker._forward_observation_hint(collector)
        conflict = client.post(path, json={**body, 'commit_oid': 'b' * 40}, headers=headers)
        assert conflict.status_code == 409, conflict.text
        assert not worker._forward_observation_hint(collector)
        for _ in range(2):
            replay = client.post(path, json=body, headers=headers)
            assert replay.status_code == 202
            assert replay.json()['data'] == original.json()['data']
        operation_id = original.json()['data']['operation_id']
        assert worker._forward_observation_hint(collector)
        assert operation_ids == [operation_id]
        assert not worker._forward_observation_hint(collector)
        assert client.get(f'/api/v1/code-operations/{operation_id}').status_code == 200
        assert not worker._forward_observation_hint(collector)
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_operations').fetchone()[0] == 1
