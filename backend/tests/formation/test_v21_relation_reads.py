"""Relationship pages and artifact views read actual manual association transactions."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.formation.api import formation_router
from backend.app.formation.commands import update_path
from backend.app.formation.read_queries import read_detail
from backend.app.formation.relation_queries import read_relations, read_ranges, read_lineage
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.formation.test_v21_schema import database, released, workspace, head
from backend.tests.formation.test_v21_path_commands import request, snapshot
from backend.tests.formation.test_v21_artifact_links import material, link_input
from backend.tests.formation.test_v21_contracts import add_step

__all__ = ['database', 'released', 'workspace']


def associated(workspace):
    document_id, revision = material(workspace)
    with workspace[0].transaction() as connection:
        link = link_input(connection, document_id, revision)
    result = update_path(
        workspace[1],
        request(
            workspace,
            [
                {'type': 'LINK_CONTENT', **link},
            ],
            document_id=document_id,
        ),
        catalog=workspace[2],
    )
    assert result['code'] == 'UPDATED', result
    return document_id


def data(result):
    assert result['code'] == 'READ_OK', result
    return result['data']


def test_actual_association_detail_ranges_and_single_root_lineage(workspace):
    doc = associated(workspace)
    before = snapshot(workspace[0])
    detail = data(read_detail(workspace[0], 1, doc, 'artifacts', 'a1', {}, catalog=workspace[2]))[
        'value'
    ]
    assert detail['is_active'] is True and detail['successor_ref'] is None
    assert detail['predecessor_ref'] is None
    assert detail['origin_block_count'] == detail['current_block_count'] == 2
    assert detail['result_refs'] == ['s1.o1']
    assert all(row['availability'] == 'AVAILABLE' for row in detail['sources'])
    first = data(
        read_ranges(
            workspace[0], 1, doc, 'a1', {'role': 'ORIGIN', 'limit': 1}, catalog=workspace[2]
        )
    )
    second = data(
        read_ranges(
            workspace[0],
            1,
            doc,
            'a1',
            {
                'role': 'ORIGIN',
                'limit': 1,
                'known_f': 2,
                'cursor': first['pagination']['next_cursor'],
            },
            catalog=workspace[2],
        )
    )
    assert first['value']['total'] == second['value']['total'] == 2
    assert first['value']['items'][0]['ordinal'] == 1
    assert second['value']['items'][0]['ordinal'] == 2
    lineage = data(read_lineage(workspace[0], 1, doc, 'a1', {}, catalog=workspace[2]))['value']
    assert lineage['total'] == 1 and lineage['items'][0]['artifact_ref'] == 'a1'
    assert snapshot(workspace[0]) == before


def test_relation_owner_and_cursor_are_exact_and_dependency_rows_are_directional(workspace):
    with workspace[0].transaction(write=True) as connection:
        head(connection)
    result = update_path(
        workspace[1],
        request(workspace, [add_step(1, ['s1']), add_step(2, ['s1'])]),
        catalog=workspace[2],
    )
    assert result['code'] == 'UPDATED', result
    # Dependencies belong to each new step, rather than being outgoing from s1.
    source = data(
        read_relations(
            workspace[0], 1, 1, 's1', {'relation_kind': 'DEPENDENCY'}, catalog=workspace[2]
        )
    )
    assert source['value']['total'] == 0
    new = data(
        read_relations(
            workspace[0], 1, 1, 's2', {'relation_kind': 'DEPENDENCY'}, catalog=workspace[2]
        )
    )
    assert new['value']['items'] == [
        {'relation_kind': 'DEPENDENCY', 'from_step_ref': 's2', 'to_step_ref': 's1'}
    ]
    assert (
        read_relations(
            workspace[0], 1, 1, 's99', {'relation_kind': 'DEPENDENCY'}, catalog=workspace[2]
        )['code']
        == 'NOT_FOUND'
    )
    assert (
        read_relations(
            workspace[0],
            1,
            1,
            's1',
            {'relation_kind': 'TOPIC', 'state': 'OPEN'},
            catalog=workspace[2],
        )['code']
        == 'INVALID_INPUT'
    )
    assert (
        read_relations(
            workspace[0],
            1,
            1,
            's1',
            {'relation_kind': 'DEPENDENCY', 'step_ref': 's2'},
            catalog=workspace[2],
        )['code']
        == 'INVALID_INPUT'
    )


def test_actual_relation_and_range_http_boundaries(workspace):
    doc = associated(workspace)
    app = FastAPI()
    app.include_router(formation_router)
    app.state.walle_runtime = HttpRuntime(workspace[0], workspace[2], workspace[1])
    base = f'/api/v1/requirements/1/documents/{doc}/formation'
    with TestClient(app) as client:
        response = client.get(
            base + '/steps/s1/relations?relation_kind=ARTIFACT&include_superseded=false'
        )
        assert response.status_code == 200, response.text
        assert response.json()['data']['total'] == 1
        assert response.json()['data']['items'][0]['artifact']['artifact_ref'] == 'a1'
        assert client.get(base + '/steps/s1/relations').status_code == 422
        assert (
            client.get(base + '/steps/s1/relations?relation_kind=TOPIC&step_ref=s2').status_code
            == 422
        )
        assert client.get(base + '/artifacts/a1/ranges?role=CURRENT&limit=1').status_code == 200
        assert client.get(base + '/artifacts/a1/ranges').status_code == 422
        assert client.get(base + '/artifacts/a1/lineage').status_code == 200
        assert client.get(base + '/artifacts/a9/lineage').status_code == 404
