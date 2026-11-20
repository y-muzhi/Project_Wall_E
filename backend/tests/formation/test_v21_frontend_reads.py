"""Real ASGI responses cross the production frontend decoder and read owner via memory only."""

import json
from pathlib import Path
import shutil
import subprocess

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.app.formation.api import formation_router
from backend.app.requirements.api import req_router
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.formation.test_v21_schema import database, released, workspace
from backend.tests.formation.test_v21_relation_reads import associated
from backend.tests.formation.test_v21_content_maintenance import edit, change_first, state
from backend.tests.formation.test_v21_completion_commands import request as completion_request
from backend.app.formation.commands import complete_step
from backend.tests.formation.test_v21_path_commands import snapshot

__all__ = ['database', 'released', 'workspace']
ROOT = Path(__file__).resolve().parents[3]


def probe(workspace, document_id, stage, *, exists, freshness=None):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Frontend contract probe requires the installed project Node runtime')
    app = FastAPI()
    app.include_router(req_router)
    app.include_router(formation_router)
    app.state.walle_runtime = HttpRuntime(workspace[0], workspace[2], workspace[1])
    base = f'/api/v1/requirements/1/documents/{document_id}/formation'
    responses = []
    before = snapshot(workspace[0])
    closure_event_id = None
    with TestClient(app) as client:

        def capture(url):
            response = client.get(url)
            assert response.status_code == 200, response.text
            value = response.json()
            responses.append({'url': url, 'status': response.status_code, 'body': value})
            return value

        capture(f'/api/v1/requirements/1?expand=discussion&document_id={document_id}')
        if not exists:
            response = client.get(base + '/steps')
            assert response.status_code == 409, response.text
            responses.append(
                {'url': base + '/steps', 'status': response.status_code, 'body': response.json()}
            )
        else:
            for path in ('steps', 'steps/s1', 'branches', 'issues', 'artifacts', 'artifacts/a1'):
                capture(base + '/' + path)
            for kind in ('DEPENDENCY', 'REPLACES', 'TOPIC', 'ISSUE', 'BRANCH', 'ARTIFACT'):
                capture(base + '/steps/s1/relations?relation_kind=' + kind)
            for role in ('ORIGIN', 'CURRENT'):
                path = base + '/artifacts/a1/ranges'
                first = capture(path + f'?limit=1&role={role}')
                cursor = first['meta']['pagination']['next_cursor']
                from urllib.parse import urlencode

                capture(path + '?' + urlencode({'limit': 1, 'role': role, 'cursor': cursor}))
            capture(base + '/artifacts/a1/lineage')
            version = responses[0]['body']['data']['discussion']['formation_summary'][
                'formation_version'
            ]
            capture(base + f'/steps?limit=20&known_f={version}&include_cancelled=false')
            capture(base + f'/steps/s1?known_f={version}')
            events = capture(base + '/events')
            for event in events['data']['items']:
                event_path = base + f'/events/{event["event_id"]}/changes'
                changes = capture(event_path)
                for change in changes['data']['items']:
                    capture(event_path + f'/{change["ordinal"]}/members')
            closure_event = next(
                (row for row in events['data']['items'] if row['closure'] is not None), None
            )
            if closure_event is not None:
                closure_event_id = closure_event['event_id']
                for kind in ('RESULT', 'ISSUE', 'BRANCH'):
                    capture(base + f'/events/{closure_event_id}/closure-items?kind={kind}')
                capture(base + f'/events/{closure_event_id}/closure-items/RESULT/s1.o1/evidence')
    fixture = {
        'stage': stage,
        'closure_event_id': closure_event_id,
        'document_id': document_id,
        'exists': exists,
        'freshness': freshness,
        'responses': responses,
    }
    result = subprocess.run(
        [node, '--experimental-strip-types', 'frontend/tests/support/formation-wire-probe.mjs'],
        cwd=ROOT,
        input=json.dumps(fixture, ensure_ascii=False).encode('utf-8'),
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout.decode(
        'utf-8', errors='replace'
    ) + result.stderr.decode('utf-8', errors='replace')
    assert snapshot(workspace[0]) == before


def test_actual_asgi_envelopes_match_frontend_before_initialization(workspace):
    probe(workspace, 1, 'uninitialized', exists=False)


def test_actual_association_and_body_change_match_frontend_without_mock_dtos(workspace):
    doc = associated(workspace)
    probe(workspace, doc, 'associated', exists=True, freshness='CURRENT')
    body = completion_request(
        workspace,
        result_dispositions=[
            {'result_ref': 's1.o1', 'status': 'LANDED', 'artifact_refs': ['a1'], 'source_refs': []}
        ],
    )
    body.update(
        document_id=doc, expected_discussion_version=state(workspace, doc)[0]['discussion_version']
    )
    completed = complete_step(workspace[1], body, catalog=workspace[2])
    assert completed['code'] == 'UPDATED', completed
    probe(workspace, doc, 'completed', exists=True, freshness='CURRENT')
    result, _ = edit(workspace, doc, change_first)
    assert result['code'] == 'DRAFT_COMPLETED', result
    probe(workspace, doc, 'changed', exists=True, freshness='NEEDS_REVIEW')
