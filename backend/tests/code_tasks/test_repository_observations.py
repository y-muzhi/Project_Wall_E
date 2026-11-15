"""Actual immutable observation GET and strict stored data; fixture producer only."""

import sqlite3
from unittest.mock import patch
from uuid import uuid4

import pytest

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.schema_transport import compact
from backend.tests.infrastructure.test_v20_command_http import package, service

AT = '2026-11-06T00:00:00.000Z'


def seed(database, identity=1, repository=1, format='sha1', **changes):
    oid = ('a' if identity == 1 else 'b') * (40 if format == 'sha1' else 64)
    data = dict(
        id=identity,
        repository_id=repository,
        operation_id=identity,
        head_commit=oid,
        local_branches=[{'full_ref': 'refs/heads/main', 'commit_oid': oid}],
        worktrees=[
            {
                'canonical_path': r'C:\observation-fixture',
                'head_commit': oid,
                'branch_ref': 'refs/heads/main',
            }
        ],
        observed_at=AT,
        status='READABLE',
    )
    data.update(changes)
    with database.transaction(write=True) as connection:
        connection.execute(
            'INSERT OR IGNORE INTO code_repositories VALUES(?,?,?,?,?,?)',
            (
                repository,
                'fixture',
                r'C:\observation-fixture',
                r'C:\observation-fixture\.git' + str(repository),
                format,
                AT,
            ),
        )
        connection.execute(
            "INSERT INTO code_operations VALUES(?,NULL,NULL,'REPOSITORY',?,NULL,'REFRESH_REPOSITORY',?,NULL,'{}',NULL,'SUCCEEDED',?,?,?,NULL)",
            (identity, repository, str(uuid4()), AT, AT, AT),
        )
        connection.execute(
            'INSERT INTO code_repository_observations VALUES(?,?,?,?,?,?,?,?)',
            (
                identity,
                repository,
                data['operation_id'],
                data['head_commit'],
                data['local_branches']
                if type(data['local_branches']) is str
                else compact(data['local_branches']),
                data['worktrees'] if type(data['worktrees']) is str else compact(data['worktrees']),
                data['observed_at'],
                data['status'],
            ),
        )
    return data


def path(repository=1, observation=1):
    return f'/api/v1/code-repositories/{repository}/observations/{observation}'


@pytest.mark.parametrize('format', ['sha1', 'sha256'])
def test_get_returns_exact_old_observation_not_latest_and_never_scans(service, format):
    database, app, client = service
    old = seed(database, format=format)
    newer = seed(database, identity=2, format=format)
    with (
        patch(
            'backend.app.infrastructure.git_object_read.RepositoryObjectCommand',
            side_effect=AssertionError('Read must not invoke Git'),
        ),
        patch(
            'backend.app.infrastructure.windows_local_paths.LocalPathGuard.__enter__',
            side_effect=AssertionError('Read must not scan disk'),
        ),
    ):
        first = client.get(path())
        assert first.status_code == 200, first.text
        assert first.json()['data'] == old
        assert client.get(path(observation=2)).json()['data'] == newer
        assert client.get(path()).json()['data'] == old
    assert set(first.json()['meta']) == {'request_id'}
    with database.transaction() as connection:
        assert (
            connection.execute('SELECT count(*) FROM code_repository_observations').fetchone()[0]
            == 2
        )
        assert connection.execute('SELECT count(*) FROM code_operations').fetchone()[0] == 2
        for table in ('idempotency_records', 'code_tasks', 'testing_tasks', 'llm_uses'):
            assert connection.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0
    assert not any(event['event'].startswith('DISPATCH') for event in app.state.walle_worker.events)


@pytest.mark.parametrize('status', ['UNKNOWN', 'UNAVAILABLE'])
def test_failure_status_and_null_head_are_preserved(service, status):
    database, _, client = service
    data = seed(database, status=status, head_commit=None, local_branches=[], worktrees=[])
    result = client.get(path())
    assert result.status_code == 200, result.text
    assert result.json()['data'] == data


def test_both_repository_and_observation_ids_are_required(service):
    database, _, client = service
    seed(database)
    seed(database, identity=2, repository=2)
    for target in (path(2, 1), path(1, 2), path(99, 1), path(1, 99)):
        response = client.get(target)
        assert response.status_code == 404, response.text
        assert response.json()['data'] is None


@pytest.mark.parametrize(
    'target',
    [
        '/api/v1/code-repositories/0/observations/1',
        '/api/v1/code-repositories/1/observations/latest',
        '/api/v1/code-repositories/1/observations/9007199254740992',
        path() + '?latest=true',
        path() + '?page=1',
        path() + '?x=1&x=2',
    ],
)
def test_invalid_ids_and_unknown_queries_do_not_fall_back(service, target):
    _, _, client = service
    response = client.get(target)
    assert response.status_code == 422, response.text


def test_get_body_and_idempotency_are_rejected_and_storage_error_uses_code_contract(service):
    database, _, client = service
    seed(database)
    assert client.request('GET', path(), json={}).status_code == 422
    assert client.get(path(), headers={'Idempotency-Key': str(uuid4())}).status_code == 422
    with patch.object(
        type(database), 'transaction', side_effect=StorageUnavailable('private error')
    ):
        result = client.get(path())
    assert result.status_code == 503, result.text
    assert result.json()['error']['code'] == 'STORAGE_UNAVAILABLE'
    assert result.json()['error']['details'] == {'capability_codes': ['DATABASE']}
    assert 'private error' not in result.text


@pytest.mark.parametrize(
    'changes',
    [
        {'head_commit': '0' * 40},
        {'head_commit': 'a' * 64},
        {'observed_at': '2026-02-30T00:00:00.000Z'},
        {'local_branches': [{'full_ref': 'main', 'commit_oid': 'a' * 40}]},
        {'local_branches': [{'full_ref': 'refs/heads/main', 'commit_oid': 'b' * 40}]},
        {
            'local_branches': '[{"full_ref":"refs/heads/main","full_ref":"refs/heads/other","commit_oid":"'
            + ('a' * 40)
            + '"}]'
        },
        {
            'worktrees': [
                {
                    'canonical_path': r'C:\fixture\..\other',
                    'head_commit': 'a' * 40,
                    'branch_ref': None,
                }
            ]
        },
    ],
)
def test_bad_stored_observation_is_error_not_empty_or_normalized(service, changes):
    database, _, client = service
    seed(database, **changes)
    result = client.get(path())
    assert result.status_code == 503, result.text
    assert result.json()['data'] is None


def test_schema_accepts_readable_and_rejects_obsolete_verified(service):
    database, _, client = service
    seed(database)
    with pytest.raises(sqlite3.IntegrityError, match='CHECK constraint'):
        with database.transaction(write=True) as connection:
            connection.execute(
                "INSERT INTO code_repository_observations SELECT 2,repository_id,operation_id,head_commit,local_branches,worktrees,observed_at,'VERIFIED' FROM code_repository_observations WHERE id=1"
            )
    assert client.get(path()).json()['data']['status'] == 'READABLE'
