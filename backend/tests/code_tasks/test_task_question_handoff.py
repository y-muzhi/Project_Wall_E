"""Actual V2 handoff endpoints preserve original document and execution facts."""

from datetime import datetime, timedelta
from uuid import uuid4

from backend.app.code_tasks import task_runtime_stop
from backend.app.code_tasks.task_native_issues import advance_native_issue_observation
from backend.app.shared.command_execution import operation_time
from backend.tests.code_tasks.test_coding_model_gateway import fixed_price, opened
from backend.tests.code_tasks.test_task_native_issues import OriginalIssueDriver
from backend.tests.code_tasks.test_task_runtime_stop import StopDriver
from backend.tests.code_tasks.test_task_start import isolated_readiness, original_operation, stop
from backend.tests.code_tasks.test_task_start_instance import original_instance
from backend.tests.code_tasks.test_task_start_session import ready
from backend.tests.infrastructure.test_v20_command_http import package, service


def test_handoff_prepare_link_read_and_stop_preserve_document(opened, ready, monkeypatch):
    db, runtime, client, proof, _, _ = opened
    window = proof.window
    observer = OriginalIssueDriver(window)
    advance_native_issue_observation(runtime, observer, 0, cancelled=lambda: False)
    path = f'/api/v1/code-tasks/{window.task_id}'
    task = client.get(path).json()['data']
    before = client.get(path + '/questions').json()['data']['items'][0]
    assert before['status'] == 'OPEN' and task['state_version'] == 5
    assert next(
        action for action in before['available_actions'] if action['action'] == 'PREPARE_HANDOFF'
    )['enabled']

    def evidence():
        tables = (
            'requirement_documents',
            'revisions',
            'conversation_messages',
            'guide_runs',
            'llm_uses',
        )
        with db.transaction() as connection:
            return [
                list(map(tuple, connection.execute(f'SELECT * FROM {table} ORDER BY id')))
                for table in tables
            ]

    original_document = evidence()
    endpoint = f'{path}/questions/{before["id"]}/handoff'

    def post(url, data, key=None):
        return client.post(url, json=data, headers={'Idempotency-Key': key or str(uuid4())})

    refs = [{'kind': 'OPERATION', 'id': window.operation_id}]
    body = {
        'target_document_id': task['document_id'],
        'expected_state_version': 5,
        'evidence_refs': refs,
    }
    wrong_document = post(endpoint, {**body, 'target_document_id': task['document_id'] + 1000})
    assert wrong_document.status_code == 404, wrong_document.text
    invalid = post(
        endpoint,
        {**body, 'evidence_refs': [{'kind': 'OPERATION', 'id': window.operation_id + 1000}]},
    )
    assert invalid.status_code == 422, invalid.text
    key = str(uuid4())
    prepared = post(endpoint, body, key)
    assert prepared.status_code == 201, prepared.text
    result = prepared.json()['data']
    identity = result['handoff_id']
    assert result == {
        'task_id': window.task_id,
        'question_id': before['id'],
        'target_document_id': task['document_id'],
        'handoff_id': identity,
    }
    assert post(endpoint, body, key).json()['data'] == result
    query = client.get(
        '/api/v1/code-command-receipts',
        params={'method': 'POST', 'path': endpoint, 'request_key': key},
    )
    assert query.status_code == 200 and query.json()['data']['original_outcome']['data'] == result
    handoff_path = f'{path}/handoffs/{identity}'
    found = client.get(handoff_path)
    assert found.status_code == 200, found.text
    detail = found.json()['data']
    assert detail['source_question']['status'] == 'OPEN' and detail['evidence_refs'] == refs
    assert detail['source_question']['handoffs'] == [
        {
            'id': identity,
            'created_at': detail['created_at'],
            'target_document_id': task['document_id'],
        }
    ]
    assert [item['kind'] for item in detail['events']] == ['PREPARED']
    assert client.get(handoff_path, params={'page': 2}).json()['data']['events'] == []
    original = original_operation(client, detail['operation_id'])
    assert original['operation_type'] == 'PREPARE_HANDOFF' and original['status'] == 'SUCCEEDED'
    assert original['fixed_input']['fixed_basis'] == [
        {
            'document_id': task['document_id'],
            'revision_id': task['design_revision_id'],
        },
        *task['material_refs'],
    ]
    assert [item['step_type'] for item in original['steps']] == ['VALIDATE', 'SAVE_FACT']
    link = {
        'expected_state_version': 6,
        'kind': 'REVISION_LINKED',
        'guide_run_id': None,
        'message_id': None,
        'revision_id': task['design_revision_id'],
    }
    assert (
        post(
            handoff_path + '/links', {**link, 'revision_id': link['revision_id'] + 1000}
        ).status_code
        == 422
    )
    link_key = str(uuid4())
    linked = post(handoff_path + '/links', link, link_key)
    assert linked.status_code == 201, linked.text
    assert post(handoff_path + '/links', link, link_key).json()['data'] == linked.json()['data']
    receipt = client.get(
        '/api/v1/code-command-receipts',
        params={
            'method': 'POST',
            'path': handoff_path + '/links',
            'request_key': link_key,
        },
    )
    assert receipt.status_code == 200 and receipt.json()['data']['task_id'] == window.task_id
    assert evidence() == original_document
    events = client.get(handoff_path).json()['data']['events']
    assert [item['kind'] for item in events] == ['REVISION_LINKED', 'PREPARED']
    assert events[0]['revision_id'] == task['design_revision_id']
    current = client.get(path).json()['data']
    assert current['waiting_items'] == task['waiting_items'] and current['state_version'] == 7
    assert client.get(path + '/questions').json()['data']['items'][0]['status'] == 'OPEN'

    stopped = stop(client, window.task_id, 7)
    assert stopped.status_code == 202, stopped.text
    clock = datetime.fromisoformat(operation_time(None)) + timedelta(seconds=3)
    monkeypatch.setattr(
        task_runtime_stop,
        'operation_time',
        lambda _: clock.isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
    )
    driver = StopDriver(ready[3])
    for index in range(6):
        if index == 3:
            clock += timedelta(days=1)
        assert task_runtime_stop.advance_owned_stops(runtime, driver, cancelled=lambda: False)
    stopped_task = client.get(path).json()['data']
    assert stopped_task['status'] == 'TERMINATED'
    result_after_stop = client.get(handoff_path).json()['data']
    assert result_after_stop['events'] == events
    assert result_after_stop['source_question']['status'] == 'OBSOLETE'
    conflict = post(
        handoff_path + '/links', {**link, 'expected_state_version': stopped_task['state_version']}
    )
    assert conflict.json()['error']['code'] == 'TASK_ENDED'
    assert evidence() == original_document
