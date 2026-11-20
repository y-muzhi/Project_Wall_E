"""Current pages use complete counts, fixed F and document ownership."""

from copy import deepcopy
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.formation.api import formation_router
from backend.app.formation.commands import update_path, update_state
from backend.app.formation.read_queries import read_entities, read_detail
from backend.app.formation.read_contracts import validate
from backend.app.infrastructure.resources import ProtocolInvalid
from backend.app.requirements.api import req_router
from backend.app.requirements.queries import get_requirement
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.formation.test_v21_schema import database, released, workspace, head
from backend.tests.formation.test_v21_state_commands import payload
from backend.tests.formation.test_v21_path_commands import request, snapshot

__all__ = ['database', 'released', 'workspace']


def page(workspace, kind='steps', **query):
    result = read_entities(workspace[0], 1, 1, kind, query, catalog=workspace[2])
    assert result['code'] == 'READ_OK', result
    return result['data']


def seed_many(workspace, count=31):
    with workspace[0].transaction(write=True) as connection:
        head(connection)
        connection.executemany(
            "INSERT INTO formation_steps VALUES(1,?,1,2,?,?,'PLANNED',NULL)",
            [(f's{number}', number, f'步骤{number}') for number in range(2, count + 1)],
        )
        connection.executemany(
            "INSERT INTO formation_results VALUES(1,?,?,?,'CONTENT')",
            [(f's{number}', f's{number}.o1', f'成果{number}') for number in range(2, count + 1)],
        )
        connection.execute(
            'UPDATE formation_heads SET next_step_no=? WHERE document_id=1', (count + 1,)
        )


def test_summary_false_and_true_use_same_keys_and_full_counts(workspace):
    empty = get_requirement(workspace[0], 1, document_id=1, expand='discussion')
    assert empty['code'] == 'READ_OK', empty
    summary = empty['data']['discussion']['formation_summary']
    assert summary['exists'] is False and summary['formation_version'] is None
    before = deepcopy(summary)
    seed_many(workspace)
    current = get_requirement(workspace[0], 1, document_id=1, expand='discussion')
    assert current['code'] == 'READ_OK', current
    summary = current['data']['discussion']['formation_summary']
    assert set(summary) == set(before)
    assert summary['counts']['steps']['PLANNED'] == 31
    assert summary['counts']['proposals']['SUPERSEDED'] == 0
    assert summary['counts']['pending_review_artifacts'] == 0
    assert all(item['available'] for item in summary['availability'])


def test_page_total_and_cursor_version_are_independent_of_loaded_page(workspace):
    seed_many(workspace)
    before = snapshot(workspace[0])
    first = page(workspace, limit=20)
    assert first['value']['total'] == 31 and len(first['value']['items']) == 20
    second = page(workspace, limit=20, known_f=1, cursor=first['pagination']['next_cursor'])
    assert [item['step_ref'] for item in second['value']['items']] == [
        f's{number}' for number in range(21, 32)
    ]
    assert second['value']['total'] == 31 and second['pagination']['next_cursor'] is None
    assert snapshot(workspace[0]) == before
    result = update_state(workspace[1], payload(workspace, 'SWITCH_STEP', step_ref='s2'))
    assert result['code'] == 'UPDATED', result
    stale = read_entities(
        workspace[0],
        1,
        1,
        'steps',
        {'cursor': first['pagination']['next_cursor'], 'limit': 20},
        catalog=workspace[2],
    )
    assert stale['code'] == 'STATE_CONFLICT' and stale['details']['reason'] == 'PATH_CHANGED'


def test_actual_cancelled_step_keeps_original_display_position_and_detail(workspace):
    seed_many(workspace, 2)
    result = update_path(
        workspace[1],
        request(
            workspace,
            [
                {'type': 'CANCEL_STEP', 'step_ref': 's1', 'replacement_step_refs': ['s2']},
            ],
            routes=[
                {
                    'from_result_ref': 's1.o1',
                    'disposition': 'REPLACED',
                    'target_result_refs': ['s2.o1'],
                    'reason': '由下一步承接',
                }
            ],
        ),
        catalog=workspace[2],
    )
    assert result['code'] == 'UPDATED', result
    assert page(workspace)['value']['total'] == 1
    all_steps = page(workspace, include_cancelled=True)['value']
    assert all_steps['total'] == 2
    cancelled = next(item for item in all_steps['items'] if item['step_ref'] == 's1')
    assert cancelled['position'] == 1 and cancelled['status'] == 'CANCELLED'
    assert cancelled['last_event']['action'] == 'RESULT_ROUTE'
    detail = read_detail(workspace[0], 1, 1, 'steps', 's1', {}, catalog=workspace[2])
    assert detail['code'] == 'READ_OK', detail
    assert detail['data']['value']['closure'] is None
    assert detail['data']['value']['expected_results'][0]['result_ref'] == 's1.o1'


@pytest.mark.parametrize(
    'kind,query',
    [
        ('steps', {'step_ref': 's1'}),
        ('steps', {'include_superseded': True}),
        ('issues', {'include_cancelled': True}),
        ('branches', {'branch_ref': 'b1'}),
        ('artifacts', {'state': 'OPEN'}),
        ('steps', {'include_cancelled': 'false'}),
        ('steps', {'limit': 101}),
        ('issues', {'branch_ref': 'new_branch_1'}),
        ('steps', {'private_basis': {}}),
    ],
)
def test_inapplicable_filters_and_wrong_types_are_not_silently_ignored(workspace, kind, query):
    result = read_entities(workspace[0], 1, 1, kind, query, catalog=workspace[2])
    assert result['code'] == 'INVALID_INPUT', result


def test_real_summary_and_entity_http_routes_validate_pagination_and_ownership(workspace):
    seed_many(workspace, 2)
    app = FastAPI()
    app.include_router(req_router)
    app.include_router(formation_router)
    app.state.walle_runtime = HttpRuntime(workspace[0], workspace[2], workspace[1])
    base = '/api/v1/requirements/1/documents/1/formation'
    with TestClient(app) as client:
        result = client.get('/api/v1/requirements/1?document_id=1&expand=discussion')
        assert result.status_code == 200, result.text
        assert (
            result.json()['data']['discussion']['formation_summary']['counts']['steps']['PLANNED']
            == 2
        )
        result = client.get(base + '/steps?limit=1&include_cancelled=false')
        assert result.status_code == 200, result.text
        assert result.json()['meta']['pagination']['has_more'] is True
        assert client.get(base + '/steps?include_cancelled=no').status_code == 422
        assert client.get(base + '/steps/s1').status_code == 200
        assert client.get(base + '/steps/s3').status_code == 404
        assert (
            client.get(base.replace('/documents/1/', '/documents/999/') + '/steps').status_code
            == 404
        )
        assert client.get(base + '/steps?known_f=2').status_code == 409


def test_strict_summary_rejects_missing_counts_unknown_fields_and_fake_exists(workspace):
    value = get_requirement(workspace[0], 1, document_id=1, expand='discussion')['data'][
        'discussion'
    ]['formation_summary']
    for change in (
        lambda v: v.update(target={}),
        lambda v: v.update(formation_version=1),
        lambda v: v['counts']['issues'].pop('DROPPED'),
        lambda v: v['counts']['steps'].update(PLANNED=1),
    ):
        bad = deepcopy(value)
        change(bad)
        with pytest.raises(ProtocolInvalid):
            validate('Summary', bad)
