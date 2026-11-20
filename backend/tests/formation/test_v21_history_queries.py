"""History reads are bounded, immutable, document-owned and independent from later F."""

import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.formation.api import formation_router
from backend.app.formation.commands import update_state, complete_step
from backend.app.formation.cursors import encode
from backend.app.formation.history_contracts import validate
from backend.app.formation.history_queries import read_history
from backend.app.shared.http_boundary import HttpRuntime
from backend.app.infrastructure.resources import ProtocolInvalid
from backend.tests.formation.test_v21_schema import database, released, workspace, head
from backend.tests.formation.test_v21_state_commands import payload, counts
from backend.tests.formation.test_v21_completion_commands import seed, request

__all__ = ['database', 'released', 'workspace']


def read(workspace, view='events', **fields):
    result = read_history(workspace[0], 1, 1, view, fields)
    assert result['code'] == 'READ_OK', result
    return result['data']


def start(workspace):
    with workspace[0].transaction(write=True) as connection:
        if connection.execute('SELECT count(*) FROM formation_heads').fetchone()[0] == 0:
            head(connection)
    result = update_state(workspace[1], payload(workspace, 'START_STEP', step_ref='s1'))
    assert result['code'] == 'UPDATED', result
    return result['data']


def test_event_upper_bound_survives_later_changes_and_empty_read_has_identical_shape(workspace):
    with workspace[0].transaction(write=True) as connection:
        head(connection)
    empty = read(workspace)
    assert empty['value'] == {'document_id': 1, 'upper_event_id': None, 'total': 0, 'items': []}
    start(workspace)
    for action in ('PAUSE_STEP', 'RESUME_STEP'):
        assert (
            update_state(workspace[1], payload(workspace, action, step_ref='s1'))['code']
            == 'UPDATED'
        )
    first = read(workspace, limit=1)
    upper = first['value']['upper_event_id']
    assert first['value']['total'] == 3 and first['pagination']['has_more']
    assert (
        update_state(workspace[1], payload(workspace, 'PAUSE_STEP', step_ref='s1'))['code']
        == 'UPDATED'
    )
    cursor, seen = first['pagination']['next_cursor'], list(first['value']['items'])
    while cursor:
        page = read(workspace, limit=1, cursor=cursor)
        assert page['value']['upper_event_id'] == upper and page['value']['total'] == 3
        seen.extend(page['value']['items'])
        cursor = page['pagination']['next_cursor']
    assert [event['action'] for event in seen] == ['STEP_RESUMED', 'STEP_PAUSED', 'STEP_STARTED']
    assert len({event['event_id'] for event in seen}) == 3
    assert read(workspace)['value']['total'] == 4


def test_actual_changes_and_members_have_complete_counts_and_no_private_binding(workspace):
    result = start(workspace)
    event = result['event_ids'][0]
    before = counts(workspace[0])
    changes = read(workspace, 'changes', event_id=event, limit=1)
    row = changes['value']['items'][0]
    assert row['entity_kind'] in ('STEP', 'ORDER')
    members = read(workspace, 'members', event_id=event, change_ordinal=row['ordinal'])
    assert members['value']['total'] == row['member_changes']['count']
    assert members['value']['digest'] == row['member_changes']['digest']
    assert counts(workspace[0]) == before
    with workspace[0].transaction() as connection:
        original = json.loads(
            connection.execute(
                'SELECT payload_json FROM document_change_audits WHERE id=?', (event,)
            ).fetchone()[0]
        )
    assert read(workspace)['value']['items'][0] == original['event']


def test_closure_and_evidence_remain_original_after_reopen(workspace):
    seed(workspace, related=True)
    result = complete_step(workspace[1], request(workspace), catalog=workspace[2])
    assert result['code'] == 'UPDATED', result
    with workspace[0].transaction() as connection:
        event = connection.execute('SELECT event_id FROM formation_closures').fetchone()[0]
    old = read(workspace, 'closure', event_id=event, kind='ISSUE')
    evidence = read(workspace, 'evidence', event_id=event, owner_kind='ISSUE', item_ref='i1')
    assert old['value']['total'] == 1
    assert evidence['value']['total'] == 1 and evidence['value']['items'][0]['kind'] == 'SOURCE'
    assert (
        update_state(workspace[1], payload(workspace, 'REOPEN_STEP', step_ref='s1'))['code']
        == 'UPDATED'
    )
    assert read(workspace, 'closure', event_id=event, kind='ISSUE') == old
    assert (
        read(workspace, 'evidence', event_id=event, owner_kind='ISSUE', item_ref='i1') == evidence
    )


@pytest.mark.parametrize(
    'query',
    [
        {'limit': True},
        {'limit': 101},
        {'known_f': 1},
        {'state': 'OPEN'},
        {'cursor': 'bad!'},
        {'cursor': encode(2, 'events', {}, {'upper_event_id': 1, 'before_event_id': 1})},
        {'cursor': encode(1, 'events', {}, {'upper_event_id': 1, 'before_event_id': 2})},
        {'step_ref': 'new_step_1'},
    ],
)
def test_unknown_filters_wrong_cursor_and_unsafe_values_are_validation_errors(workspace, query):
    before = counts(workspace[0])
    result = read_history(workspace[0], 1, 1, 'events', query)
    assert result['code'] == 'INVALID_INPUT', result
    assert counts(workspace[0]) == before


def test_history_http_uses_actual_query_and_error_whitelists(workspace):
    result = start(workspace)
    event = result['event_ids'][0]
    with workspace[0].transaction(write=True) as connection:
        head(connection, 2)
    app = FastAPI()
    app.include_router(formation_router)
    app.state.walle_runtime = HttpRuntime(workspace[0], workspace[2], workspace[1])
    base = '/api/v1/requirements/1/documents/1/formation'
    with TestClient(app) as client:
        response = client.get(base + '/events?limit=1')
        assert response.status_code == 200, response.text
        assert response.json()['meta']['pagination']['page_size'] == 1
        assert client.get(base + '/events?limit=1&limit=2').status_code == 422
        assert client.get(base + f'/events/{event}/changes').status_code == 200
        assert client.get(base + f'/events/{event}/closure-items?kind=RESULT').status_code == 404
        assert client.get(base + f'/events/{event}/changes/999/members').status_code == 404
        assert (
            client.get(
                base.replace('/documents/1/', '/documents/2/') + f'/events/{event}/changes'
            ).status_code
            == 404
        )


def test_strict_snapshots_do_not_accept_arbitrary_json_or_private_proof(workspace):
    result = start(workspace)
    row = read(workspace, 'changes', event_id=result['event_ids'][0])['value']['items'][0]
    row['after']['binding_json'] = {'private': True}
    with pytest.raises(ProtocolInvalid):
        validate('EntityChangeView', row)


def test_history_without_real_head_is_not_a_fabricated_empty_route(workspace):
    result = read_history(workspace[0], 1, 1, 'events', {})
    assert result['code'] == 'STATE_CONFLICT'
    assert result['details']['reason'] == 'FORMATION_NOT_INITIALIZED'
