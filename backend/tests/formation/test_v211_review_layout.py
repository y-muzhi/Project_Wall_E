from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.app.code_tasks import task_creation, task_start
from backend.app.code_tasks.repository_baseline_query import BaselineQueryResult
from backend.app.code_tasks.repository_registration_worker import RepositoryRegistrationWorker
from backend.app.code_tasks.task_creation import create_fixed_task
from backend.app.code_tasks.task_creation_api import CreateTaskRequest, CreatedTaskResponse

from backend.app.documents.commands import (
    cancel_manual_draft,
    complete_manual_draft,
    save_manual_draft,
    start_manual_draft,
)
from backend.app.documents.queries import get_manual_draft
from backend.app.guide.commands import recover_runs
from backend.app.shared.command_execution import operation_time
from backend.app.infrastructure.database import SchemaMismatch
from backend.app.infrastructure.formation_database import FormationDatabase
from backend.app.infrastructure.formation_schema_release import load_release
from backend.app.infrastructure.review_schema import load_review_release
from backend.app.infrastructure.review_schema_copy import copy_review_database
from backend.app.infrastructure.model_profile import OPENAI_PROFILE
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.requirements.queries import get_requirement as get_requirement_detail
from backend.app.service import create_app
from backend.tests.code_tasks.test_authorizations import approve
from backend.tests.code_tasks.test_execution_profile_versions import resources
from backend.tests.code_tasks.test_task_stop import seed_task
from backend.tests.documents.test_v15_documents import document, metadata
from backend.tests.documents.test_v15_editing import candidate, finish, save, start
from backend.tests.formation.test_v21_schema import workspace

__all__ = ['workspace']


@pytest.fixture
def database(tmp_path):
    database = FormationDatabase(
        Path(tmp_path) / 'review.sqlite', formation_release=load_review_release()
    )
    database.initialize()
    return database


def test_manual_drafts_are_independent_by_document(workspace):
    database, commands, catalog = workspace

    def draft(document_id):
        return start_manual_draft(
            commands,
            {
                'requirement_id': 1,
                'document_id': document_id,
                'expected_version': 1,
                'idempotency_key': str(uuid4()),
            },
            catalog=catalog,
        )

    first, second = draft(1), draft(2)
    assert first['code'] == second['code'] == 'DRAFT_STARTED', (first, second)
    one, two = [result['data']['manual_draft'] for result in (first, second)]
    assert second['data']['requirement']['active_operation_id'] == two['id']
    recovery = recover_runs(
        database,
        {
            'recovery_reason': 'STARTUP',
            'operation_time': operation_time(None),
            'live_run_ids': set(),
        },
        process_lock=commands.process_lock,
        catalog=catalog,
    )
    assert recovery['code'] == 'RECOVERY_NO_CHANGE', recovery
    assert recovery['data']['unchanged_requirement_ids'] == [1]
    assert draft(1)['code'] == draft(2)['code'] == 'WORK_STATE_CONFLICT'
    for document, saved in ((1, one), (2, two)):
        assert get_manual_draft(database, 1, document, catalog=catalog)['data'] == saved
    detail = get_requirement_detail(database, 1, include_document_runs=True, catalog=catalog)
    assert detail['code'] == 'READ_OK', detail
    assert [(row['document_id'], row['id']) for row in detail['data']['document_drafts']] == [
        (1, one['id']),
        (2, two['id']),
    ]

    saved = save_manual_draft(
        commands,
        {
            'requirement_id': 1,
            'document_id': 2,
            'draft_id': two['id'],
            'expected_version': 1,
            'idempotency_key': str(uuid4()),
            'markdown_content': two['markdown_content'],
            'block_state_json': two['block_state_json'],
        },
        catalog=catalog,
    )
    assert saved['code'] == 'DRAFT_SAVED', saved
    assert saved['data']['content_version'] == 2
    assert get_manual_draft(database, 1, 1, catalog=catalog)['data'] == one

    result = complete_manual_draft(
        commands,
        {
            'requirement_id': 1,
            'document_id': 2,
            'draft_id': two['id'],
            'expected_version': 2,
            'idempotency_key': str(uuid4()),
        },
        catalog=catalog,
    )
    assert result['code'] == 'DRAFT_COMPLETED', result
    assert get_manual_draft(database, 1, 1, catalog=catalog)['data'] == one
    replacement = draft(2)
    assert replacement['code'] == 'DRAFT_STARTED', replacement
    remaining = replacement['data']['manual_draft']
    result = cancel_manual_draft(
        commands,
        {
            'requirement_id': 1,
            'document_id': 1,
            'draft_id': one['id'],
            'expected_version': 1,
            'idempotency_key': str(uuid4()),
        },
    )
    assert result['code'] == 'DRAFT_CANCELLED', result
    assert get_manual_draft(database, 1, 2, catalog=catalog)['data'] == remaining
    detail = get_requirement_detail(database, 1, include_document_runs=True, catalog=catalog)[
        'data'
    ]
    assert detail['requirement']['active_operation_id'] == remaining['id']


def test_review_layout_copies_legacy_business_rows_and_preserves_source(tmp_path):
    path = tmp_path / 'source.sqlite'
    old = FormationDatabase(path, formation_release=load_release())
    old.initialize()
    catalog = ResourceCatalog().for_formation_profile(OPENAI_PROFILE)
    app = create_app(database=old, schema_version=210, catalog=catalog)
    with TestClient(app) as client:
        task_id = seed_task(old, app.state.walle_runtime, client)
    source = path.read_bytes()
    target = tmp_path / 'review.sqlite'
    with pytest.raises(SchemaMismatch):
        with FormationDatabase(path, formation_release=load_review_release()).transaction():
            pass
    assert len(copy_review_database(path, target)) == 64
    assert path.read_bytes() == source
    with pytest.raises(FileExistsError):
        copy_review_database(path, target)
    copy = FormationDatabase(target, formation_release=load_review_release())
    with old.transaction() as original, copy.transaction() as migrated:
        query = 'SELECT * FROM requirements'
        assert original.execute(query).fetchall() == migrated.execute(query).fetchall()
        task_query = 'SELECT * FROM code_tasks WHERE id=?'
        previous = original.execute(task_query, (task_id,)).fetchone()
        assert previous['budget_limit_cny'] == '0.100000'
        assert previous == migrated.execute(task_query, (task_id,)).fetchone()
        assert migrated.execute('PRAGMA foreign_key_check').fetchall() == []
        assert (
            "budget_limit_cny<>'0.000000'"
            not in migrated.execute(
                "SELECT sql FROM sqlite_schema WHERE name='code_tasks'"
            ).fetchone()[0]
        )


def test_zero_amount_coding_creation_start_and_legacy_amount_readback(database, monkeypatch):
    catalog = ResourceCatalog().for_formation_profile(OPENAI_PROFILE)
    app = create_app(database=database, schema_version=210, catalog=catalog)
    with TestClient(app) as client:
        runtime = app.state.walle_runtime
        legacy_id = seed_task(database, runtime, client)
        workspace = database, runtime.commands(), catalog
        new_document = document(workspace, name='不设金额的代码设计', kind='DESIGN')
        assert new_document['code'] == 'CREATED', new_document
        document_id = new_document['data']['document']['id']
        draft = start(workspace, identity=document_id)['data']['manual_draft']
        updated = save(workspace, draft, candidate(workspace, draft, '确认设计内容\n'))
        assert updated['code'] == 'DRAFT_SAVED', updated
        effect = finish(workspace, updated['data'])['data']
        confirm = metadata(
            workspace,
            document_id,
            1,
            {
                'type': 'CONFIRM',
                'expected_content_version': 2,
                'revision_id': effect['revision_id'],
            },
        )
        assert confirm['code'] == 'UPDATED', confirm
        grant = approve(client)
        assert grant.status_code == 201, grant.text
        path = f'/api/v1/documents/{document_id}/code-tasks'
        key = str(uuid4())
        request = CreateTaskRequest.parse(
            Request(
                {
                    'type': 'http',
                    'method': 'POST',
                    'path': path,
                    'query_string': b'',
                    'path_params': {'document_id': str(document_id)},
                    'headers': [(b'idempotency-key', key.encode('ascii'))],
                }
            ),
            {
                'design_revision_id': effect['revision_id'],
                'material_refs': [],
                'repository_id': 1,
                'base_snapshot_id': 1,
                'target_branch': 'refs/heads/main',
                'execution_profile_version_id': 1,
                'authorization_id': grant.json()['data']['resource_id'],
                'budget_limit_cny': '0.000000',
            },
        )

        def read_mock_snapshot(_self, identity, *, cancelled, finish):
            assert not cancelled.is_set()
            with database.transaction() as connection:
                snapshot = dict(
                    connection.execute(
                        'SELECT * FROM code_snapshots WHERE id=?', (identity,)
                    ).fetchone()
                )
            return finish(BaselineQueryResult(snapshot, ()), lambda: None)

        monkeypatch.setattr(
            task_creation,
            'read_registered_baseline',
            lambda connection, identity: connection.execute(
                'SELECT * FROM code_snapshots WHERE id=?', (identity,)
            ).fetchone(),
        )
        monkeypatch.setattr(RepositoryRegistrationWorker, 'read_snapshot', read_mock_snapshot)
        worker = object.__new__(RepositoryRegistrationWorker)
        with resources():
            result = create_fixed_task(runtime, request, worker, Event())
        assert result['code'] == 'CREATED', result
        task, _ = CreatedTaskResponse.project(result['data'], request)
        task_id = task['id']
        assert task['budget']['limit_cny'] == '0.000000'
        assert (
            client.get(f'/api/v1/code-tasks/{legacy_id}').json()['data']['budget']['limit_cny']
            == '0.100000'
        )
        assert create_fixed_task(runtime, request, worker, Event()) == result
        monkeypatch.setattr(task_start, '_check_start_readiness', lambda *_: None)
        started = client.post(
            f'/api/v1/code-tasks/{task_id}/start',
            json={'expected_state_version': 1},
            headers={'Idempotency-Key': str(uuid4())},
        )
        assert started.status_code == 202, started.text
