"""Real route preview: complete impact, bounded slices and no identity or state consumption."""

from copy import deepcopy
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.app.formation.api import formation_router
from backend.app.formation.commands import update_path, update_state
from backend.app.formation.preview_queries import preview_path
from backend.app.formation.preview_contracts import validate
from backend.app.infrastructure.resources import ProtocolInvalid
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.formation.test_v21_schema import database, released, workspace
from backend.tests.formation.test_v21_path_commands import request, snapshot
from backend.tests.formation.test_v21_state_commands import payload
from backend.tests.formation.test_v21_current_reads import seed_many
from backend.tests.formation.test_v21_contracts import add_step
from backend.tests.formation.test_v21_artifact_links import material, link_input

__all__ = ['database', 'released', 'workspace']


def body(workspace, changes, *, doc=1, **options):
    original = request(workspace, changes, document_id=doc)
    return {
        'expected_discussion_version': original['expected_discussion_version'],
        'discussion_command': original['discussion_command'],
        **options,
    }


def preview(workspace, value, doc=1):
    result = preview_path(workspace[0], 1, doc, value, catalog=workspace[2])
    assert result['code'] == 'READ_OK', result
    return result['data']


def test_more_than_a_page_of_implicit_moves_and_warnings_stay_complete_without_allocations(
    workspace,
):
    seed_many(workspace, 105)
    change = add_step(1)
    change['before_step_ref'] = 's1'
    original = body(
        workspace,
        [
            {'type': 'SET_GOAL', 'text': '明确新的设计目标', 'source_refs': []},
            change,
        ],
        limit=20,
    )
    frozen = snapshot(workspace[0])
    first = preview(workspace, original)
    assert first['affected_items']['total'] == 107  # Goal + add + 105 actual shifts.
    assert len(first['affected_items']['items']) == 20
    assert first['warnings']['total'] == 106
    assert first['reference_map'] == [
        {'temp_ref': 'new_step_1', 'preview_label': change['title']},
        {'temp_ref': 'new_result_1', 'preview_label': '新增成果1'},
    ]
    for section, field in (('AFFECTED', 'affected_items'), ('WARNINGS', 'warnings')):
        page = first
        items = list(page[field]['items'])
        while page[field]['has_more']:
            page = preview(
                workspace,
                {
                    **original,
                    'section': section,
                    'cursor': page[field]['next_cursor'],
                },
            )
            items.extend(page[field]['items'])
        assert len(items) == first[field]['total']
        assert [row['ordinal'] for row in items] == list(range(1, len(items) + 1))
    assert snapshot(workspace[0]) == frozen
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT next_step_no FROM formation_heads').fetchone()[0] == 106
        assert connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0


def test_unchanged_route_has_no_preview_effect_or_fake_warning(workspace):
    seed_many(workspace, 1)
    frozen = snapshot(workspace[0])
    value = preview(
        workspace, body(workspace, [{'type': 'RENAME_STEP', 'step_ref': 's1', 'title': '讨论方案'}])
    )
    assert value['affected_items']['items'] == [] and value['affected_items']['total'] == 0
    assert value['warnings']['items'] == [] and value['reference_map'] == []
    assert snapshot(workspace[0]) == frozen


def test_source_blocks_are_verified_but_preview_allocates_no_artifact(workspace):
    doc, revision = material(workspace)
    with workspace[0].transaction() as connection:
        link = link_input(connection, doc, revision)
    value = body(workspace, [{'type': 'LINK_CONTENT', **link}], doc=doc)
    frozen = snapshot(workspace[0])
    result = preview(workspace, value, doc)
    assert result['affected_items']['items'][0]['entity_ref'] == 's1'
    assert result['affected_items']['items'][0]['after'] == {'kind': 'ARTIFACT_LINK', **link}
    assert result['reference_map'] == []
    assert snapshot(workspace[0]) == frozen
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT count(*) FROM formation_artifacts').fetchone()[0] == 0
    committed = update_path(
        workspace[1],
        {
            'requirement_id': 1,
            'document_id': doc,
            **value,
            'idempotency_key': str(uuid4()),
        },
        catalog=workspace[2],
    )
    assert committed['code'] == 'UPDATED', committed
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT count(*) FROM formation_artifacts').fetchone()[0] == 1


def test_preview_cannot_turn_a_cycle_into_an_accepted_plan(workspace):
    seed_many(workspace, 1)
    frozen = snapshot(workspace[0])
    value = body(
        workspace,
        [
            add_step(1, ['s1']),
            {'type': 'SET_DEPENDENCIES', 'step_ref': 's1', 'dependencies': ['new_step_1']},
        ],
    )
    result = preview_path(workspace[0], 1, 1, value, catalog=workspace[2])
    assert result['code'] == 'FORMATION_INVALID', result
    assert snapshot(workspace[0]) == frozen


def test_cursor_binds_original_input_and_live_versions_but_never_grants_commit_authority(workspace):
    seed_many(workspace, 3)
    change = add_step(1)
    change['before_step_ref'] = 's1'
    value = body(workspace, [change], limit=1)
    first = preview(workspace, value)
    cursor = first['affected_items']['next_cursor']
    assert cursor
    altered = deepcopy(value)
    altered['discussion_command']['changes'][0]['title'] = '其他方案'
    altered.update(section='AFFECTED', cursor=cursor)
    assert (
        preview_path(workspace[0], 1, 1, altered, catalog=workspace[2])['code'] == 'STATE_CONFLICT'
    )
    switched = update_state(workspace[1], payload(workspace, 'SWITCH_STEP', step_ref='s2'))
    assert switched['code'] == 'UPDATED', switched
    result = preview_path(
        workspace[0], 1, 1, {**value, 'section': 'AFFECTED', 'cursor': cursor}, catalog=workspace[2]
    )
    assert result['code'] == 'STATE_CONFLICT' and result['details']['reason'] == 'PATH_CHANGED'


def test_preview_real_http_is_keyless_strict_read_and_uses_body_pagination(workspace):
    seed_many(workspace, 1)
    app = FastAPI()
    app.include_router(formation_router)
    app.state.walle_runtime = HttpRuntime(workspace[0], workspace[2], workspace[1])
    path = '/api/v1/requirements/1/documents/1/formation/path-preview'
    value = body(workspace, [add_step(1)])
    frozen = snapshot(workspace[0])
    with TestClient(app) as client:
        result = client.post(path, json=value)
        assert result.status_code == 200, result.text
        assert result.json()['data']['reference_map'][0]['temp_ref'] == 'new_step_1'
        assert client.post(path + '?limit=1', json=value).status_code == 422
        assert client.post(path, json={**value, 'private_binding': {}}).status_code == 422
        assert client.post(path, json={**value, 'idempotency_key': str(uuid4())}).status_code == 422
        assert client.post(path, json={**value, 'limit': 101}).status_code == 422
        assert client.post(path, json={**value, 'cursor': 'missing-section'}).status_code == 422
    assert snapshot(workspace[0]) == frozen


def test_preview_strict_output_rejects_private_authority_and_inconsistent_slice(workspace):
    seed_many(workspace, 1)
    value = preview(workspace, body(workspace, [add_step(1)]))
    for mutate in (
        lambda item: item.update(authorization_token='not-allowed'),
        lambda item: item['reference_map'][0].update(resolved_ref='s2'),
        lambda item: item['affected_items'].update(has_more=True, next_cursor=None),
        lambda item: item['affected_items']['items'][0]['after'].update(private_basis={}),
    ):
        bad = deepcopy(value)
        mutate(bad)
        with pytest.raises(ProtocolInvalid):
            validate(bad)
