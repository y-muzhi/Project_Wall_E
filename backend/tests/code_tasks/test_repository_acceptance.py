"""Original-key repository reception and SQL reservation boundaries."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from backend.app.code_tasks import repository_acceptance as module
from backend.app.code_tasks.command_registry import registered_command
from backend.app.infrastructure.database import CommitOutcomeUnknown, Database, StorageUnavailable
from backend.app.infrastructure.idempotency import Idempotency, canonical_input
from backend.app.infrastructure.process_lock import ProcessLock
from backend.tests.infrastructure.test_v20_command_http import package, service

AT = '2026-11-06T00:00:00.000Z'


@dataclass(frozen=True)
class Input:
    command: object
    repository_id: int | None = None
    name: str = 'fixture'
    root_path: str = r'C:\fixture'

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        if self.repository_id is None:
            return {'name': self.name, 'root_path': self.root_path}
        return {'repository_id': self.repository_id}


@pytest.fixture
def runtime(package):
    root, release = package
    database = Database(root / (str(uuid4()) + '.sqlite'), schema_release=release)
    database.initialize()
    with ProcessLock.for_database(database.path) as lock:
        executor = Idempotency(database, lock)
        yield SimpleNamespace(database=database, commands=lambda: executor)


def request(repository_id=None, key=None):
    path = '/api/v1/code-repositories'
    if repository_id is not None:
        path += f'/{repository_id}/refresh'
    return Input(registered_command('POST', path, key or str(uuid4())), repository_id)


def counts(runtime):
    with runtime.database.transaction() as c:
        return {
            table: c.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
            for table in (
                'code_operations',
                'code_operation_steps',
                'code_repositories',
                'code_tasks',
            )
        }


def test_registration_reserves_original_ids_no_placeholder_and_terminal_replay(runtime):
    original = request()
    first = module.accept_repository_operation(runtime, original)
    assert first == {
        'code': 'OPERATION_ACCEPTED',
        'data': {
            'resource_kind': 'REPOSITORY',
            'resource_id': 1,
            'operation_id': 1,
            'operation_status': 'PENDING',
        },
        'details': None,
    }
    assert counts(runtime) == {
        'code_operations': 1,
        'code_operation_steps': 2,
        'code_repositories': 0,
        'code_tasks': 0,
    }
    with runtime.database.transaction(write=True) as c:
        row = c.execute('SELECT * FROM code_operations').fetchone()
        assert row['fixed_input'] == canonical_input(original.business_input())
        assert row['idempotency_key'] == original.idempotency_key
        assert row['task_id'] is row['testing_task_id'] is row['control_generation'] is None
        assert [
            tuple(r)
            for r in c.execute(
                'SELECT step_no,step_type,status FROM code_operation_steps ORDER BY step_no'
            )
        ] == [(1, 'VALIDATE', 'PENDING'), (2, 'SAVE_FACT', 'PENDING')]
        c.execute(
            "UPDATE code_operations SET status='FAILED',ended_at=?,failure_code='SOURCE_UNSUPPORTED'",
            (AT,),
        )
    assert module.accept_repository_operation(runtime, original) == first
    receipt = runtime.commands().command_receipt(original.command.scope)
    assert receipt['original_http_status'] == 202
    assert receipt['operation_id'] == 1
    assert receipt['original_outcome']['data'] == first['data']
    assert counts(runtime)['code_operations'] == 1


def test_real_parallel_receivers_share_one_reserved_id(runtime):
    original = request()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: module.accept_repository_operation(runtime, original), range(2))
        )
    assert results[0] == results[1]
    assert results[0]['code'] == 'OPERATION_ACCEPTED'
    assert counts(runtime)['code_operations'] == 1


def test_different_original_intents_reserve_distinct_ids_and_changed_body_conflicts(runtime):
    original = request()
    module.accept_repository_operation(runtime, original)
    changed = Input(original.command, name='other')
    assert module.accept_repository_operation(runtime, changed)['code'] == 'OPERATION_CONFLICT'
    second = module.accept_repository_operation(runtime, request())
    assert second['data']['resource_id'] == second['data']['operation_id'] == 2
    assert counts(runtime)['code_repositories'] == 0


def test_close_before_receive_allocates_nothing(runtime):
    original = request()
    runtime.commands().close_command(original.command.scope)
    assert module.accept_repository_operation(runtime, original)['code'] == 'COMMAND_CLOSED'
    assert all(value == 0 for value in counts(runtime).values())
    with runtime.database.transaction() as c:
        assert c.execute('SELECT count(*) FROM sequences').fetchone()[0] == 0


def test_failure_after_reservation_rolls_back_receipt_operation_and_sequences(runtime):
    original = request()
    with patch.object(module, 'operation_steps', side_effect=OSError('owned failure')):
        assert module.accept_repository_operation(runtime, original)['code'] == 'INTERNAL_ERROR'
    assert (
        runtime.commands().command_receipt(original.command.scope)['lookup_status'] == 'NOT_FOUND'
    )
    assert all(value == 0 for value in counts(runtime).values())
    with runtime.database.transaction() as c:
        assert c.execute('SELECT count(*) FROM sequences').fetchone()[0] == 0
    assert module.accept_repository_operation(runtime, original)['data']['resource_id'] == 1


def test_lost_commit_ack_keeps_original_202_and_ids(runtime):
    original = request()
    transaction = runtime.database.transaction
    armed = True

    @contextmanager
    def lost_ack(*, write=False):
        nonlocal armed
        with transaction(write=write) as c:
            yield c
        if write and armed:
            armed = False
            raise CommitOutcomeUnknown('owned acknowledgment loss')

    with patch.object(runtime.database, 'transaction', lost_ack):
        assert (
            module.accept_repository_operation(runtime, original)['code'] == 'STORAGE_UNAVAILABLE'
        )
    replay = module.accept_repository_operation(runtime, original)
    assert replay['data']['operation_id'] == replay['data']['resource_id'] == 1
    assert runtime.commands().command_receipt(original.command.scope)['original_http_status'] == 202
    assert counts(runtime)['code_operations'] == 1


@pytest.mark.parametrize('kind', ['CodeRepository', 'OperationRecord'])
def test_exhausted_sequence_rejects_without_partial_ids(runtime, kind):
    with runtime.database.transaction(write=True) as c:
        c.execute('INSERT INTO sequences VALUES(?,?)', (kind, 9007199254740991))
    original = request()
    assert module.accept_repository_operation(runtime, original)['code'] == 'PRECONDITION_FAILED'
    assert all(value == 0 for value in counts(runtime).values())
    with runtime.database.transaction() as c:
        assert c.execute('SELECT count(*) FROM sequences').fetchone()[0] == 1
    assert runtime.commands().command_receipt(original.command.scope)['record_status'] == 'REJECTED'


def test_refresh_requires_existing_repository_and_saves_original_steps(runtime):
    missing = request(1)
    assert module.accept_repository_operation(runtime, missing)['code'] == 'NOT_FOUND'
    with runtime.database.transaction(write=True) as c:
        c.execute(
            'INSERT INTO code_repositories VALUES(1,?,?,?,?,?)',
            ('fixture', r'C:\fixture', r'C:\fixture\.git', 'sha1', AT),
        )
    # A certain rejection is immutable even if the resource later appears.
    assert module.accept_repository_operation(runtime, missing)['code'] == 'NOT_FOUND'
    original = request(1)
    result = module.accept_repository_operation(runtime, original)
    assert result['data']['resource_id'] == 1
    with runtime.database.transaction() as c:
        assert [
            r[0] for r in c.execute('SELECT step_type FROM code_operation_steps ORDER BY step_no')
        ] == ['READ_REPOSITORY', 'SAVE_OBSERVATION']
        assert (
            c.execute(
                "SELECT count(*) FROM sequences WHERE entity_kind='CodeRepository'"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    'case',
    [
        'no_claim',
        'wrong_key',
        'wrong_body',
        'missing_field',
        'null_field',
        'no_reservation',
        'wrong_action',
        'wrong_status',
    ],
)
def test_sql_missing_repository_exception_requires_exact_original_claim(runtime, case):
    original = request()
    fixed = original.business_input()
    if case == 'missing_field':
        fixed = {'name': 'fixture', 'unrelated': 'value'}
    if case == 'null_field':
        fixed['root_path'] = None
    encoded = canonical_input(fixed)
    with runtime.database.transaction(write=True) as c:
        if case != 'no_reservation':
            c.execute("INSERT INTO sequences VALUES('CodeRepository',1)")
        if case != 'no_claim':
            c.execute(
                'INSERT INTO idempotency_records(capability_id,target_identity,idempotency_key,business_input_json,status,owner_epoch,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                (
                    'APP-CODE-CMD-C01',
                    'POST /api/v1/code-repositories',
                    original.idempotency_key,
                    '{}' if case == 'wrong_body' else encoded,
                    'PROCESSING',
                    'owned-test',
                    AT,
                    AT,
                ),
            )
        with pytest.raises(sqlite3.IntegrityError):
            c.execute(
                "INSERT INTO code_operations VALUES(1,NULL,NULL,'REPOSITORY',1,NULL,?,?,NULL,?,NULL,?,?,NULL,NULL,NULL)",
                (
                    'REFRESH_REPOSITORY' if case == 'wrong_action' else 'REGISTER_REPOSITORY',
                    str(uuid4()) if case == 'wrong_key' else original.idempotency_key,
                    encoded,
                    'RUNNING' if case == 'wrong_status' else 'PENDING',
                    AT,
                ),
            )


def test_sql_reserved_id_cannot_be_used_for_second_original_operation(runtime):
    original = request()
    assert module.accept_repository_operation(runtime, original)['code'] == 'OPERATION_ACCEPTED'
    with runtime.database.transaction(write=True) as c:
        row = c.execute('SELECT * FROM code_operations').fetchone()
        values = [row[key] for key in row.keys()]
        values[0] = 2
        values[7] = str(uuid4())
        c.execute(
            'INSERT INTO idempotency_records(capability_id,target_identity,idempotency_key,business_input_json,status,owner_epoch,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
            (
                'APP-CODE-CMD-C01',
                'POST /api/v1/code-repositories',
                values[7],
                values[9],
                'PROCESSING',
                'owned-test',
                AT,
                AT,
            ),
        )
        with pytest.raises(sqlite3.IntegrityError, match='UNIQUE constraint failed'):
            c.execute(
                'INSERT INTO code_operations VALUES(' + ','.join('?' for _ in values) + ')', values
            )
    assert counts(runtime)['code_operations'] == 1


def test_saved_acceptance_requires_original_operation_resource_and_fixed_bytes(runtime):
    original = request()
    accepted = module.accept_repository_operation(runtime, original)['data']
    with runtime.database.transaction() as connection:
        row = dict(
            connection.execute(
                'SELECT * FROM code_operations WHERE id=?', (accepted['operation_id'],)
            ).fetchone()
        )
        module.verify_saved_repository_acceptance(connection, row)
        for different in (
            {'id': row['id'] + 1},
            {'resource_id': row['resource_id'] + 1},
            {'fixed_input': canonical_input({'name': 'other', 'root_path': original.root_path})},
            {'idempotency_key': str(uuid4())},
        ):
            with pytest.raises(StorageUnavailable, match='original repository acceptance'):
                module.verify_saved_repository_acceptance(connection, {**row, **different})


def test_c01_without_worker_rolls_back_intent_but_preserves_existing_receipt(service):
    database, app, client = service
    original = request()
    path = original.command.path
    headers = {'Idempotency-Key': original.idempotency_key}
    body = original.business_input()

    unavailable = client.post(path, json=body, headers=headers)
    assert unavailable.status_code == 503
    assert unavailable.json()['error']['code'] == 'CONFIG_NOT_READY'
    assert unavailable.json()['error']['details'] == {
        'capability_codes': ['Q20-WINDOWS', 'Q20-GIT'],
    }
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM idempotency_records').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM code_operations').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM code_repositories').fetchone()[0] == 0

    for invalid in (
        {**body, 'operation_id': 17},
        {**body, 'root_path': r'\\host\git'},
        {**body, 'name': ' '},
    ):
        failure = client.post(path, json=invalid, headers=headers)
        assert failure.status_code == 422
        assert failure.json()['error']['code'] == 'INVALID_INPUT'
    assert client.post(path + '?source=x', json=body, headers=headers).status_code == 422
    assert client.post(path, json=body).status_code == 422

    accepted = module.accept_repository_operation(app.state.walle_runtime, original)
    replay = client.post(path, json=body, headers=headers)
    assert replay.status_code == 202
    assert replay.json()['data'] == accepted['data']
    result = client.post(path, json={**body, 'name': 'different'}, headers=headers)
    assert result.status_code == 409
    assert result.json()['error']['code'] == 'OPERATION_CONFLICT'

    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM idempotency_records').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM code_operations').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM code_repositories').fetchone()[0] == 0


def test_service_rejects_wrong_registration_user_before_opening_evidence(package):
    from fastapi.testclient import TestClient

    from backend.app.code_tasks.repository_git_runner import RegistrationReadLimits
    from backend.app.code_tasks.repository_registration_worker import RegistrationInstallation
    from backend.app.infrastructure.guard_controller_binding import GuardBindingError
    from backend.app.service import create_app

    root, release = package
    database = Database(root / 'registration-wrong-user.sqlite', schema_release=release)
    database.initialize()
    journal_root = root / 'unopened-journal'
    installation = RegistrationInstallation(
        'a' * 64,
        'S-1-5-18',
        root / 'unopened.exe',
        1,
        'b' * 64,
        journal_root,
        (),
        RegistrationReadLimits(4096, 4096, 256, 32768, 4096, 5),
    )
    app = create_app(database=database, registration_installation=installation)
    with pytest.raises(GuardBindingError, match='REGISTRATION_INSTALLATION_BACKEND_SID_DIFFERS'):
        with TestClient(app):
            pytest.fail('Registration startup admitted a different backend user')
    assert not journal_root.exists()
    assert not app.state.walle_repository_registration.accepting
    with ProcessLock.for_database(database.path):
        pass


def test_c02_http_requires_empty_body_and_uses_original_receipt(service):
    database, app, client = service
    original = request(1)
    path = original.command.path
    headers = {'Idempotency-Key': original.idempotency_key}
    with database.transaction(write=True) as connection:
        connection.execute(
            'INSERT INTO code_repositories VALUES(1,?,?,?,?,?)',
            ('fixture', r'C:\fixture', r'C:\fixture\.git', 'sha1', AT),
        )

    response = client.post(path, json={}, headers=headers)
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'CONFIG_NOT_READY'
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM idempotency_records').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM code_operations').fetchone()[0] == 0

    assert client.post(path, headers=headers).status_code == 422
    assert client.post(path, json={'repository_id': 2}, headers=headers).status_code == 422
    assert client.post(path, json={}).status_code == 422
    assert client.post(path + '?repository_id=2', json={}, headers=headers).status_code == 422
    assert (
        client.post('/api/v1/code-repositories/0/refresh', json={}, headers=headers).status_code
        == 422
    )

    accepted = module.accept_repository_operation(app.state.walle_runtime, original)
    for _ in range(2):
        response = client.post(path, json={}, headers=headers)
        assert response.status_code == 202
        assert response.json()['data'] == accepted['data']
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_operations').fetchone()[0] == 1
        assert (
            connection.execute('SELECT count(*) FROM code_repository_observations').fetchone()[0]
            == 0
        )
