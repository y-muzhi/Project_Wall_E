"""Read error classification preserves the existing HTTP privacy boundary without partial data."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.formation.api import formation_router
from backend.app.formation import history_queries, preview_queries, read_queries
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.formation.test_v21_schema import database, released, workspace, head
from backend.tests.formation.test_v21_path_preview import body
from backend.tests.formation.test_v21_path_commands import snapshot

__all__ = ['database', 'released', 'workspace']


class UnexpectedReadFailure(Exception):
    pass


@pytest.mark.parametrize('kind', ['current', 'history', 'preview'])
@pytest.mark.parametrize('error_type', [ValueError, UnexpectedReadFailure])
def test_expected_and_unclassified_read_faults_reach_the_same_safe_http_boundary(
    workspace, monkeypatch, kind, error_type
):
    with workspace[0].transaction(write=True) as connection:
        head(connection)
    request = body(workspace, [{'type': 'SET_GOAL', 'text': '完整预览', 'source_refs': []}])
    frozen = snapshot(workspace[0])

    def failed(*args, **kwargs):
        raise error_type('private SQL text and user content must not escape')

    module, name = {
        'current': (read_queries, 'entity_page'),
        'history': (history_queries, '_events'),
        'preview': (preview_queries, 'prepare_preview'),
    }[kind]
    assert hasattr(module, name)
    monkeypatch.setattr(module, name, failed)
    app = FastAPI()
    app.include_router(formation_router)
    app.state.walle_runtime = HttpRuntime(workspace[0], workspace[2], workspace[1])
    base = '/api/v1/requirements/1/documents/1/formation'
    with TestClient(app) as client:
        response = (
            client.post(base + '/path-preview', json=request)
            if kind == 'preview'
            else client.get(base + ('/steps' if kind == 'current' else '/events'))
        )
    assert response.status_code == 500, response.text
    value = response.json()
    assert value['error']['code'] == 'INTERNAL_ERROR'
    assert value['error']['details'] is None and value['data'] is None
    assert 'private SQL' not in response.text and 'user content' not in response.text
    assert snapshot(workspace[0]) == frozen
