"""Actual C07 publication and original C06 ASGI adoption cross real frontend codecs."""

import json
from pathlib import Path
import shutil
import subprocess

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.app.formation.api import formation_router
from backend.app.guide.api import guide_router
from backend.app.messages.api import message_router
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.formation.test_v21_discuss_acceptance import (
    database,
    released,
    base_workspace,
    workspace,
)
from backend.tests.formation.test_v21_model_publication import publish
from backend.tests.formation.test_v21_card_apply import answer

__all__ = ['database', 'released', 'base_workspace', 'workspace']
ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize('purpose', ('STAGED_WRITE', 'FORMATION_PATH_CHANGE'))
def test_real_publication_and_formal_answer_wire_decodes_in_existing_frontend(
    workspace, monkeypatch, purpose
):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Installed frontend Node runtime is required')
    message, _ = publish(workspace, monkeypatch, purpose=purpose, initial=purpose == 'STAGED_WRITE')
    payload = answer(workspace, message)
    key = payload.pop('idempotency_key')
    payload.pop('message_id')
    app = FastAPI()
    app.include_router(guide_router)
    app.include_router(message_router)
    app.include_router(formation_router)
    app.state.walle_runtime = HttpRuntime(workspace[0], workspace[2], workspace[1])
    responses = []
    with TestClient(app) as client:
        url = f'/api/v1/conversation-messages/{message["id"]}/responses'
        result = client.post(url, json=payload, headers={'Idempotency-Key': key})
        assert result.status_code == 200, result.text
        responses.append(
            {'method': 'POST', 'url': url, 'status': result.status_code, 'body': result.json()}
        )
        for url in (
            '/api/v1/guide-runs/1',
            '/api/v1/requirements/1/messages?document_id=1',
            '/api/v1/requirements/1/documents/1/formation/proposals',
        ):
            result = client.get(url)
            assert result.status_code == 200, result.text
            responses.append(
                {'method': 'GET', 'url': url, 'status': result.status_code, 'body': result.json()}
            )
    result = subprocess.run(
        [node, '--experimental-strip-types', 'frontend/tests/support/formation-workflow-probe.mjs'],
        cwd=ROOT,
        input=json.dumps(
            {
                'responses': responses,
                'key': key,
                'answers': payload,
                'message_id': message['id'],
                'purpose': purpose,
            },
            ensure_ascii=False,
        ).encode('utf-8'),
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout.decode(
        'utf-8', errors='replace'
    ) + result.stderr.decode('utf-8', errors='replace')
