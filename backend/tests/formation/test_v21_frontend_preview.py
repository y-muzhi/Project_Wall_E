"""Actual read-only ASGI previews cross the production frontend binding in memory."""

import json
from pathlib import Path
import shutil
import subprocess

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.app.formation.api import formation_router
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.formation.test_v21_schema import database, released, workspace
from backend.tests.formation.test_v21_current_reads import seed_many
from backend.tests.formation.test_v21_path_preview import body
from backend.tests.formation.test_v21_contracts import add_step
from backend.tests.formation.test_v21_path_commands import snapshot

__all__ = ['database', 'released', 'workspace']


def test_actual_preview_matches_frontend_read_only_binding_and_separate_cursors(workspace):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Project Node required')
    seed_many(workspace, 31)
    added = add_step(1)
    added['before_step_ref'] = 's1'
    request = body(
        workspace,
        [
            {'type': 'SET_GOAL', 'text': '明确完整路线', 'source_refs': []},
            added,
        ],
    )
    before = snapshot(workspace[0])
    app = FastAPI()
    app.include_router(formation_router)
    app.state.walle_runtime = HttpRuntime(workspace[0], workspace[2], workspace[1])
    url = '/api/v1/requirements/1/documents/1/formation/path-preview'
    with TestClient(app) as client:
        first = client.post(url, json=request)
        assert first.status_code == 200, first.text
        cursor = first.json()['data']['affected_items']['next_cursor']
        assert cursor
        second = client.post(url, json={**request, 'section': 'AFFECTED', 'cursor': cursor})
        assert second.status_code == 200, second.text
    fixture = {'input': request, 'first': first.json(), 'next': second.json()}
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [node, 'frontend/tests/support/formation-preview-probe.mjs'],
        cwd=root,
        input=json.dumps(fixture, ensure_ascii=False).encode('utf-8'),
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout.decode(
        'utf-8', errors='replace'
    ) + result.stderr.decode('utf-8', errors='replace')
    assert json.loads(result.stdout)['passed']
    assert snapshot(workspace[0]) == before
