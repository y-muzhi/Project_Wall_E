"""Original STOP recovery and hold behavior using owned, isolated Schema200."""

from pathlib import Path
from time import monotonic, sleep
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.code_tasks import task_stop
from backend.app.code_tasks.repository_acceptance import accept_repository_operation
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.service import create_app
from backend.app.shared.command_execution import operation_time
from backend.tests.code_tasks.test_authorizations import scope
from backend.tests.code_tasks.test_execution_profile_versions import (
    parents,
    publish,
    resources,
    seed_price,
)
from backend.tests.code_tasks.test_repository_baseline_acceptance import BaselineInput
from backend.tests.documents.test_v15_documents import document, metadata
from backend.tests.documents.test_v15_editing import candidate, finish, save, start
from backend.tests.infrastructure.test_v20_command_http import package
from backend.tests.requirements.test_v15_foundation import create


def seed_task(database, runtime, client):
    parents(client)
    seed_price(database)
    with resources():
        assert publish(client).status_code == 201
    workspace = (database, runtime.commands(), runtime.catalog)
    create(runtime.commands())
    original = document(workspace, kind='DESIGN')['data']
    doc_id = original['document']['id']
    draft = start(workspace, identity=doc_id, version=1)['data']['manual_draft']
    saved = save(workspace, draft, candidate(workspace, draft, '原固定设计\n'))
    fixed = finish(workspace, saved['data'])['data']['revision_id']
    confirmed = metadata(
        workspace,
        doc_id,
        1,
        {
            'type': 'CONFIRM',
            'expected_content_version': 2,
            'revision_id': fixed,
        },
    )
    assert confirmed['code'] == 'UPDATED', confirmed
    now = operation_time(None)
    with database.transaction(write=True) as connection:
        connection.execute(
            'INSERT INTO code_repositories VALUES(?,?,?,?,?,?)',
            (1, 'isolated', 'C:/isolated-stop', 'C:/isolated-stop/.git', 'sha1', now),
        )
    with resources():
        snapshot_operation = accept_repository_operation(
            runtime, BaselineInput(1, 'a' * 40, key=str(uuid4()))
        )
    assert snapshot_operation['code'] == 'OPERATION_ACCEPTED'
    with database.transaction(write=True) as connection:
        connection.execute(
            'INSERT INTO code_snapshots VALUES(?,?,?,?,?,?,?,?,?,?)',
            (
                1,
                1,
                snapshot_operation['data']['operation_id'],
                1,
                'a' * 40,
                'b' * 40,
                'refs/walle/baselines/1',
                'GIT20-BASELINE-1',
                now,
                now,
            ),
        )
        task = entity_id(connection, EntityKind.CODE_TASK)
        grant = entity_id(connection, EntityKind.AUTHORIZATION_GRANT)
        connection.execute(
            """INSERT INTO code_tasks(id,requirement_id,document_id,design_revision_id,repository_id,
               base_snapshot_id,target_branch,execution_profile_version_id,authorization_id,
               budget_limit_cny,status,phase,state_version,control_generation,created_at,updated_at)
               VALUES(?,1,?,?,1,1,'refs/heads/main',1,?,'0.100000','PENDING','PREPARING',1,1,?,?)""",
            (task, doc_id, fixed, grant, now, now),
        )
        connection.execute(
            """INSERT INTO code_authorizations(id,task_id,profile_version_id,scope,status,approved_at,actor_ref)
               VALUES(?,?,1,?,'BOUND_PENDING_APPLY',?,'isolated-owner')""",
            (grant, task, canonical_input(scope()), now),
        )
    return task


@pytest.mark.parametrize('history', ['none', 'prior_start', 'effective_approval'])
def test_restart_reconciles_only_a_provably_empty_original_stop(package, history):
    root, release = package
    database = Database(Path(root) / (str(uuid4()) + '.sqlite'), schema_release=release)
    database.initialize()
    app = create_app(database=database)
    with (
        patch.object(task_stop, 'advance_pending_stops', lambda _: False),
        TestClient(app) as client,
    ):
        task = seed_task(database, app.state.walle_runtime, client)
        if history == 'prior_start':
            with database.transaction(write=True) as connection:
                operation = entity_id(connection, EntityKind.OPERATION_RECORD)
                connection.execute(
                    """INSERT INTO code_operations(id,task_id,resource_kind,resource_id,operation_type,
                       idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at)
                       VALUES(?,?,'TASK',?,'START',?,1,'{}',1,'UNKNOWN',?)""",
                    (operation, task, task, str(uuid4()), operation_time(None)),
                )
        elif history == 'effective_approval':
            with database.transaction(write=True) as connection:
                connection.execute(
                    "UPDATE code_authorizations SET status='EFFECTIVE' WHERE task_id=?", (task,)
                )
        path = f'/api/v1/code-tasks/{task}/terminate'
        key = str(uuid4())
        original = client.post(
            path, json={'expected_state_version': 1}, headers={'Idempotency-Key': key}
        )
        assert original.status_code == 202, original.text
        receipt = original.json()['data']
        operation_id = receipt['operation_id']
        assert (
            client.get(f'/api/v1/code-operations/{operation_id}').json()['data']['status']
            == 'PENDING'
        )

    with TestClient(create_app(database=database)) as reopened:
        deadline = monotonic() + 8
        operation_path = f'/api/v1/code-operations/{operation_id}'
        while True:
            observed = reopened.get(operation_path)
            assert observed.status_code == 200, observed.text
            result = observed.json()['data']
            if result['status'] != 'PENDING':
                break
            assert monotonic() < deadline
            sleep(0.1)
        replay = reopened.post(
            path, json={'expected_state_version': 1}, headers={'Idempotency-Key': key}
        )
        assert replay.status_code == 202 and replay.json()['data'] == receipt
        if history != 'none':
            assert (
                result['status'] == 'UNKNOWN' and result['failure_code'] == 'EXECUTION_NOT_STOPPED'
            )
        else:
            assert result['status'] == 'SUCCEEDED'
        with database.transaction() as connection:
            row = connection.execute('SELECT status FROM code_tasks WHERE id=?', (task,)).fetchone()
            assert row['status'] == ('STOPPING' if history != 'none' else 'TERMINATED')
            count = connection.execute('SELECT count(*) FROM code_runtime_observations').fetchone()[
                0
            ]
            assert count == (0 if history != 'none' else 2)


def test_late_owned_operation_invalidates_empty_scope_before_completion(package):
    root, release = package
    database = Database(Path(root) / (str(uuid4()) + '.sqlite'), schema_release=release)
    database.initialize()
    app = create_app(database=database)
    advance = task_stop.advance_pending_stops
    inspect = task_stop._zero_scope
    with (
        patch.object(task_stop, 'advance_pending_stops', lambda _: False),
        TestClient(app) as client,
    ):
        runtime = app.state.walle_runtime
        task = seed_task(database, runtime, client)
        key = str(uuid4())
        original = client.post(
            f'/api/v1/code-tasks/{task}/terminate',
            json={'expected_state_version': 1},
            headers={'Idempotency-Key': key},
        )
        assert original.status_code == 202, original.text
        operation_id = original.json()['data']['operation_id']
        checked = []

        def inspect_then_receive_late_fact(connection, row, operation):
            evidence = inspect(connection, row, operation)
            checked.append(evidence)
            if len(checked) == 1:
                assert evidence is not None
                # An isolated injected prior-generation fact simulates a late
                # writer. The real application has no launch endpoint yet.
                with database.transaction(write=True) as writer:
                    identity = entity_id(writer, EntityKind.OPERATION_RECORD)
                    writer.execute(
                        """INSERT INTO code_operations(id,task_id,resource_kind,resource_id,
                           operation_type,idempotency_key,expected_state_version,fixed_input,
                           control_generation,status,created_at)
                           VALUES(?,?,'TASK',?,'START',?,1,'{}',1,'UNKNOWN',?)""",
                        (identity, task, task, str(uuid4()), operation_time(None)),
                    )
            return evidence

        with patch.object(task_stop, '_zero_scope', inspect_then_receive_late_fact):
            assert advance(runtime)
        assert len(checked) == 2 and checked[1] is None
        observed = client.get(f'/api/v1/code-operations/{operation_id}')
        assert observed.status_code == 200, observed.text
        assert observed.json()['data']['status'] == 'UNKNOWN'
        with database.transaction() as connection:
            task_row = connection.execute(
                'SELECT status,stopped_at FROM code_tasks WHERE id=?', (task,)
            ).fetchone()
            assert tuple(task_row) == ('STOPPING', None)
            assert (
                connection.execute('SELECT count(*) FROM code_runtime_observations').fetchone()[0]
                == 0
            )
