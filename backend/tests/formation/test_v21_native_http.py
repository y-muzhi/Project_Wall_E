"""Real PATCH adapters over the shared transaction and response boundary."""

from uuid import uuid4
from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.requirements.api import req_router
from backend.app.shared.http_boundary import HttpRuntime
from backend.app.formation.http_projection import program_receipt
from backend.tests.formation.test_v21_schema import database, released, workspace, head

__all__ = ['database', 'released', 'workspace']


def client_for(workspace):
    app = FastAPI()
    app.include_router(req_router)
    app.state.walle_runtime = HttpRuntime(workspace[0], workspace[2], workspace[1])
    return TestClient(app)


def body(workspace, command=None):
    with workspace[0].transaction(write=True) as connection:
        if connection.execute('SELECT count(*) FROM formation_heads').fetchone()[0] == 0:
            head(connection)
        version = RequirementRepository(connection).get_for_document(1, 1)['discussion_version']
    return {
        'document_id': 1,
        'expected_discussion_version': version,
        'discussion_command': command
        or {'type': 'FORMATION', 'action': 'START_STEP', 'step_ref': 's1'},
    }


def test_actual_patch_receipt_replay_and_no_change_use_same_original_database(workspace):
    with client_for(workspace) as client:
        payload = body(workspace)
        key = str(uuid4())
        first = client.patch(
            '/api/v1/requirements/1', json=payload, headers={'Idempotency-Key': key}
        )
        assert first.status_code == 200, first.text
        data = first.json()['data']
        assert data['processing'] == 'PROGRAM' and data['result'] == 'APPLIED'
        assert data['operation'] == 'NATIVE_FORMATION'
        second = client.patch(
            '/api/v1/requirements/1', json=payload, headers={'Idempotency-Key': key}
        )
        assert second.json()['data'] == data
        payload = body(workspace, {'type': 'FORMATION', 'action': 'SWITCH_STEP', 'step_ref': 's1'})
        same = client.patch(
            '/api/v1/requirements/1', json=payload, headers={'Idempotency-Key': str(uuid4())}
        )
        assert same.status_code == 200, same.text
        assert same.json()['data']['result'] == 'NO_CHANGE'
        with workspace[0].transaction() as connection:
            assert (
                connection.execute('SELECT count(*) FROM formation_event_changes').fetchone()[0]
                >= 1
            )
            assert connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] == 0
            assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0


@pytest.mark.parametrize(
    'case', ('extra', 'private_basis', 'wrong_document', 'stale', 'missing_key', 'upper_key')
)
def test_invalid_transport_and_stale_input_leave_no_formation_effects(workspace, case):
    payload = body(workspace)
    key = str(uuid4())
    headers = {'Idempotency-Key': key}
    status = 422
    if case == 'extra':
        payload['target'] = {'step_ref': 's1'}
    elif case == 'private_basis':
        payload['discussion_command']['binding'] = {}
    elif case == 'wrong_document':
        payload['document_id'] = 999
        status = 404
    elif case == 'stale':
        payload['expected_discussion_version'] += 1
        status = 409
    elif case == 'missing_key':
        headers = {}
    else:
        headers['Idempotency-Key'] = key.upper()
    with client_for(workspace) as client:
        response = client.patch('/api/v1/requirements/1', json=payload, headers=headers)
        assert response.status_code == status, response.text
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT count(*) FROM formation_event_changes').fetchone()[0] == 0
        assert connection.execute('SELECT status FROM formation_steps').fetchone()[0] == 'PLANNED'


def test_output_boundary_never_silently_strips_private_fields(workspace):
    with client_for(workspace) as client:
        response = client.patch(
            '/api/v1/requirements/1',
            json=body(workspace),
            headers={'Idempotency-Key': str(uuid4())},
        )
    assert response.status_code == 200, response.text
    value = response.json()['data']
    assert program_receipt(value) == value
    for change in (
        lambda v: v.update(binding={}),
        lambda v: v['effects'].update(formation_changed='true'),
        lambda v: v.update(result='NO_CHANGE'),
        lambda v: v['reference_map'].append(
            {'temp_ref': 'new_step_1', 'resolved_ref': 's1', 'private': {}}
        ),
    ):
        bad = deepcopy(value)
        change(bad)
        with pytest.raises(ValueError):
            program_receipt(bad)
