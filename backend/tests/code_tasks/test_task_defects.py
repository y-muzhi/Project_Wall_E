"""Coding defect HTTP, immutable evidence, and original receipt coverage."""

from uuid import uuid4

import pytest

from backend.tests.code_tasks.test_task_stop import seed_task
from backend.tests.infrastructure.test_v20_command_http import package, service  # noqa: F401
from backend.tests.test_testing_cli_run import _candidate_fixture

_CODE = '/api/v1/code-tasks'
_TASK = _CODE + '/1/defects'


def post(client, body, key=None):
    return client.post(_TASK, json=body, headers={'Idempotency-Key': key or str(uuid4())})


@pytest.fixture
def defect_task(service):  # noqa: F811
    database, app, client = service
    runtime = app.state.walle_runtime
    identity = seed_task(database, runtime, client)
    candidate, basis = _candidate_fixture(database, identity)
    with database.transaction(write=True) as connection:
        connection.execute(
            """UPDATE code_tasks SET status='VERIFYING',phase='BACKEND',current_candidate_id=?
               WHERE id=?""",
            (candidate, identity),
        )
        original = connection.execute(
            'SELECT capture_operation_id FROM code_candidates WHERE id=?', (candidate,)
        ).fetchone()[0]
    return (
        database,
        client,
        {
            'candidate_id': candidate,
            'expected_state_version': 1,
            'actual_behavior': '原操作返回空内容\n另存原行。',
            'expected_behavior': '应保留原固定设计中的内容。',
            'basis_ref': {
                'document_id': basis['document_id'],
                'revision_id': basis['design_revision_id'],
                'quote': '原固定设计',
            },
            'evidence_refs': [{'kind': 'OPERATION', 'id': original}],
        },
    )


def test_defect_snapshot_and_receipt_are_immutable(defect_task):
    database, client, body = defect_task
    key = str(uuid4())
    assert client.get(_TASK).json()['data'] == {'items': []}
    response = post(client, body, key)
    assert response.status_code == 201, response.text
    assert response.json()['data'] == {
        'defect_id': 1,
        'task_id': 1,
        'candidate_id': body['candidate_id'],
    }
    assert post(client, body, key).json()['data'] == response.json()['data']
    assert post(client, body).json()['error']['code'] == 'VERSION_CONFLICT'
    assert (
        post(client, {**body, 'actual_behavior': '更改原记录'}, key).json()['error']['code']
        == 'OPERATION_CONFLICT'
    )
    original = client.get(
        '/api/v1/code-command-receipts',
        params={
            'method': 'POST',
            'path': _TASK,
            'request_key': key,
        },
    )
    assert original.status_code == 200, original.text
    assert original.json()['data']['original_outcome']['data'] == response.json()['data']
    selected = client.get(_TASK + '/1')
    assert selected.status_code == 200, selected.text
    saved = selected.json()['data']
    assert saved['testing_finding_id'] is None and saved['basis_ref'] == body['basis_ref']
    assert (
        saved['actual_behavior'] == body['actual_behavior']
        and saved['evidence_refs'] == body['evidence_refs']
    )
    assert client.get(_TASK + '?page=1').json()['data']['items'] == [saved]
    assert client.get(_TASK + '?page=2').json()['data']['items'] == []
    assert client.get(_CODE + '/2/defects/1').status_code == 404
    assert client.get(_TASK + '/2').status_code == 404
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_defects').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM code_repairs').fetchone()[0] == 0
        assert connection.execute('SELECT status,state_version FROM code_tasks').fetchone()[:] == (
            'VERIFYING',
            2,
        )


def test_defect_rejects_changed_basis_foreign_evidence_and_mixed_import(defect_task):
    database, client, body = defect_task
    assert (
        post(client, {**body, 'basis_ref': {**body['basis_ref'], 'quote': '并非原设计'}}).json()[
            'error'
        ]['code']
        == 'BASIS_REF_INVALID'
    )
    assert (
        post(client, {**body, 'evidence_refs': [{'kind': 'COMMAND', 'id': 999}]}).json()['error'][
            'code'
        ]
        == 'DEFECT_SOURCE_MISMATCH'
    )
    assert post(client, {**body, 'testing_finding_id': 1}).status_code == 422
    imported = {key: body[key] for key in ('candidate_id', 'expected_state_version')}
    assert post(client, {**imported, 'testing_finding_id': 999}).status_code == 404
    assert post(client, {**body, 'candidate_id': 999}).status_code == 404
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_defects').fetchone()[0] == 0
        assert connection.execute('SELECT state_version FROM code_tasks').fetchone()[0] == 1
