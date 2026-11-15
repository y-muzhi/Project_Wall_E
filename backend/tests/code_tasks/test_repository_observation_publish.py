"""Atomic existing-repository observation publication, not a Guard dispatcher."""

from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import patch
from uuid import uuid4

import pytest

from backend.app.code_tasks import repository_observation_publish as module
from backend.app.code_tasks.repository_acceptance import accept_repository_operation
from backend.app.infrastructure.database import CommitOutcomeUnknown, StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.schema_transport import compact
from backend.tests.code_tasks.test_repository_acceptance import request
from backend.tests.infrastructure.test_v20_command_http import package, service

AT = '2026-11-06T00:00:00.000Z'
ROOT = r'C:\fixture'
COMMON = r'C:\fixture\.git'


def insert_repository(runtime):
    with runtime.database.transaction(write=True) as connection:
        connection.execute(
            'INSERT INTO code_repositories VALUES(1,?,?,?,?,?)',
            ('fixture', ROOT, COMMON, 'sha1', AT),
        )


def prepare(runtime):
    insert_repository(runtime)
    accepted = accept_repository_operation(runtime, request(1))['data']
    operation_id = accepted['operation_id']
    module.start_repository_observation(runtime, operation_id)
    with runtime.database.transaction(write=True) as connection:
        at = connection.execute(
            'SELECT started_at FROM code_operations WHERE id=?', (operation_id,)
        ).fetchone()[0]
        connection.execute(
            "UPDATE code_operation_steps SET status='SUCCEEDED',ended_at=?,last_observed_at=? WHERE operation_id=? AND step_no=1",
            (at, at, operation_id),
        )
        connection.execute(
            "UPDATE code_operation_steps SET status='RUNNING',started_at=?,last_observed_at=? WHERE operation_id=? AND step_no=2",
            (at, at, operation_id),
        )


def capture():
    oid = 'a' * 40
    return module.RepositoryObservationCapture(
        ROOT,
        COMMON,
        'sha1',
        'b' * 64,
        'c' * 64,
        canonical_input(
            {
                'head_commit': oid,
                'local_branches': [{'full_ref': 'refs/heads/main', 'commit_oid': oid}],
                'worktrees': [
                    {'canonical_path': ROOT, 'head_commit': oid, 'branch_ref': 'refs/heads/main'}
                ],
                'observed_at': AT,
                'status': 'READABLE',
            }
        ),
    )


def test_atomic_publication_read_by_original_ids_and_replay_no_capture(service):
    database, app, client = service
    prepare(app.state.walle_runtime)
    runtime = app.state.walle_runtime
    assert module.publish_repository_observation(runtime, 1, capture()) == 1
    assert module.publish_repository_observation(runtime, 1) == 1
    response = client.get('/api/v1/code-repositories/1/observations/1')
    assert response.status_code == 200, response.text
    assert response.json()['data'] == {
        'id': 1,
        'repository_id': 1,
        'operation_id': 1,
        **__import__('json').loads(capture().payload_json),
    }
    with database.transaction() as c:
        assert c.execute('SELECT count(*) FROM code_repository_observations').fetchone()[0] == 1
        assert (
            c.execute('SELECT status FROM code_operations WHERE id=1').fetchone()[0] == 'SUCCEEDED'
        )
        assert (
            c.execute(
                'SELECT result_ref FROM code_operation_steps WHERE operation_id=1 AND step_no=2'
            ).fetchone()[0]
            == '{"observation_id":1}'
        )
        assert c.execute('SELECT count(*) FROM code_tasks').fetchone()[0] == 0


@pytest.mark.parametrize(
    'changed',
    [
        {'root': r'C:\other'},
        {'common_directory': r'C:\elsewhere'},
        {'object_format': 'sha256'},
        {'payload_json': '{"id":999}'},
    ],
)
def test_binding_or_payload_mismatch_cannot_allocate_or_publish(service, changed):
    database, app, _ = service
    prepare(app.state.walle_runtime)
    with pytest.raises(StorageUnavailable):
        module.publish_repository_observation(
            app.state.walle_runtime, 1, replace(capture(), **changed)
        )
    with database.transaction() as c:
        assert c.execute('SELECT count(*) FROM code_repository_observations').fetchone()[0] == 0
        assert (
            c.execute(
                "SELECT count(*) FROM sequences WHERE entity_kind='RepositoryObservation'"
            ).fetchone()[0]
            == 0
        )


def test_failure_after_insert_rolls_back_observation_sequence_and_steps(service):
    database, app, _ = service
    prepare(app.state.walle_runtime)
    original = module.compact

    def fail(value):
        if type(value) is dict and 'observation_id' in value:
            raise OSError('owned write failure')
        return original(value)

    with patch.object(module, 'compact', fail), pytest.raises(OSError):
        module.publish_repository_observation(app.state.walle_runtime, 1, capture())
    with database.transaction() as c:
        assert c.execute('SELECT count(*) FROM code_repository_observations').fetchone()[0] == 0
        assert (
            c.execute(
                "SELECT count(*) FROM sequences WHERE entity_kind='RepositoryObservation'"
            ).fetchone()[0]
            == 0
        )
        assert c.execute('SELECT status FROM code_operations WHERE id=1').fetchone()[0] == 'RUNNING'
    assert module.publish_repository_observation(app.state.walle_runtime, 1, capture()) == 1


def test_lost_commit_acknowledgment_reconciles_original_result(service):
    database, app, _ = service
    prepare(app.state.walle_runtime)
    transaction = database.transaction

    @contextmanager
    def lost(*args, **kwargs):
        with transaction(*args, **kwargs) as c:
            yield c
        if kwargs.get('write'):
            raise CommitOutcomeUnknown('owned acknowledgment loss')

    with patch.object(database, 'transaction', lost), pytest.raises(CommitOutcomeUnknown):
        module.publish_repository_observation(app.state.walle_runtime, 1, capture())
    assert module.publish_repository_observation(app.state.walle_runtime, 1) == 1


def test_no_pending_or_stopped_operation_can_publish(service):
    database, app, _ = service
    prepare(app.state.walle_runtime)
    with database.transaction(write=True) as c:
        c.execute("UPDATE code_operations SET status='CANCELLED',ended_at=? WHERE id=1", (AT,))
    with pytest.raises(StorageUnavailable):
        module.publish_repository_observation(app.state.walle_runtime, 1, capture())


def test_start_accepts_only_untouched_original_and_pins_saved_repository(service):
    database, app, client = service
    runtime = app.state.walle_runtime
    insert_repository(runtime)
    original = request(1)
    accepted = accept_repository_operation(runtime, original)
    operation_id = accepted['data']['operation_id']
    source = module.start_repository_observation(runtime, operation_id)
    assert source == module.RepositoryObservationSource(1, ROOT, COMMON, 'sha1')
    with pytest.raises(StorageUnavailable, match='execution history'):
        module.start_repository_observation(runtime, operation_id)
    assert accept_repository_operation(runtime, original) == accepted
    result = client.get(f'/api/v1/code-operations/{operation_id}').json()['data']
    assert result['status'] == 'RUNNING'
    assert [step['status'] for step in result['steps']] == ['RUNNING', 'PENDING']
    with database.transaction() as connection:
        assert (
            connection.execute('SELECT count(*) FROM code_repository_observations').fetchone()[0]
            == 0
        )


def test_observation_publish_refuses_synthetic_operation_without_original_receipt(service):
    database, app, _ = service
    runtime = app.state.walle_runtime
    insert_repository(runtime)
    fixed = compact({'repository_id': 1})
    with database.transaction(write=True) as connection:
        connection.execute(
            "INSERT INTO code_operations VALUES(1,NULL,NULL,'REPOSITORY',1,NULL,'REFRESH_REPOSITORY',?,NULL,?,NULL,'RUNNING',?,?,NULL,NULL)",
            (str(uuid4()), fixed, AT, AT),
        )
        for number, kind, state in (
            (1, 'READ_REPOSITORY', 'SUCCEEDED'),
            (2, 'SAVE_OBSERVATION', 'RUNNING'),
        ):
            connection.execute(
                'INSERT INTO code_operation_steps VALUES(?,?,?,?,NULL,?,NULL,?,NULL,?)',
                (1, number, kind, state, fixed, AT, AT),
            )
    with pytest.raises(StorageUnavailable, match='acceptance is invalid'):
        module.publish_repository_observation(runtime, 1, capture())
    with database.transaction() as connection:
        assert (
            connection.execute('SELECT count(*) FROM code_repository_observations').fetchone()[0]
            == 0
        )
