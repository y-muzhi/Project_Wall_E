"""Atomic pending-only acceptance using the actual saved proposal/HTTP path."""
from uuid import uuid4
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.tests.requirements.test_v15_foundation import tmp_path, setup, counts
from backend.tests.documents.test_v15_documents import workspace
from backend.tests.suggestions.test_v15_batches import pending, decide, complete
from backend.app.suggestions.commands import accept_pending_suggestions
from backend.app.suggestions.queries import get_batch
from backend.app.suggestions.api import batch_router
from backend.app.shared.http_boundary import HttpRuntime


def request(batch, **changes):
    return {'batch_id': batch['id'], 'expected_content_version': batch['base_content_version'],
        'expected_pending_ids': [item['id'] for item in batch['suggestions'] if item['status'] == 'PENDING'],
        'idempotency_key': str(uuid4()), **changes}


def read(workspace):
    return get_batch(workspace[0], 1, catalog=workspace[2])['data']


@pytest.mark.parametrize('decision', ['ACCEPTED', 'REJECTED', 'EDITED'])
def test_bulk_preserves_recorded_decisions_and_only_applies_on_original_completion(workspace, monkeypatch, decision):
    source, target, batch = pending(workspace, monkeypatch)
    first, second = batch['suggestions']
    assert decide(workspace, first['id'], decision, '# 已编辑标题' if decision == 'EDITED' else None)['code'] == 'SUGGESTION_DECIDED'
    before = read(workspace);body = request(before)
    result = accept_pending_suggestions(workspace[1], body, catalog=workspace[2])
    assert result['code'] == 'SUGGESTIONS_ACCEPTED', result
    actual = result['data']['batch']
    assert result['data']['accepted_suggestion_ids'] == [second['id']]
    assert actual['suggestions'][0] == before['suggestions'][0]
    assert actual['suggestions'][1]['status'] == 'ACCEPTED' and actual['counts']['pending'] == 0
    assert actual['status'] == 'PENDING'
    assert accept_pending_suggestions(workspace[1], body, catalog=workspace[2]) == result
    assert accept_pending_suggestions(workspace[1], {**body, 'expected_pending_ids': [first['id']]}, catalog=workspace[2])['code'] == 'IDEMPOTENCY_CONFLICT'
    with workspace[0].transaction() as c:
        assert c.execute('SELECT content_version FROM requirement_documents WHERE id=?', (target['id'],)).fetchone()[0] == 1
        assert c.execute('SELECT markdown_content FROM requirement_documents WHERE id=?', (source['id'],)).fetchone()[0] == source['markdown_content']
    calls = counts(workspace[0])['llm_uses']
    assert complete(workspace)['code'] == 'BATCH_APPLIED'
    assert counts(workspace[0])['llm_uses'] == calls == 1


def test_bulk_rejects_changed_pending_set_wrong_order_and_stale_version_without_partial_decisions(workspace, monkeypatch):
    _, _, batch = pending(workspace, monkeypatch);before = read(workspace)
    body = request(batch)
    for changes, code in [({'expected_content_version': 99}, 'CONTENT_VERSION_CONFLICT'),
        ({'expected_pending_ids': list(reversed(body['expected_pending_ids']))}, 'STATE_CONFLICT'),
        ({'expected_pending_ids': [999]}, 'STATE_CONFLICT')]:
        assert accept_pending_suggestions(workspace[1], {**body, **changes, 'idempotency_key': str(uuid4())}, catalog=workspace[2])['code'] == code
        assert read(workspace) == before
    assert decide(workspace, batch['suggestions'][0]['id'], 'REJECTED')['code'] == 'SUGGESTION_DECIDED'
    prior = read(workspace)
    assert accept_pending_suggestions(workspace[1], body, catalog=workspace[2])['code'] == 'STATE_CONFLICT'
    assert read(workspace) == prior


def test_bulk_validates_all_before_any_write_and_rolls_back_repository_failure(workspace, monkeypatch):
    from backend.app.infrastructure.batch_repository import BatchRepository
    _, _, batch = pending(workspace, monkeypatch);body = request(batch)
    from backend.app.suggestions import commands
    from backend.app.documents.patch_errors import TargetStale
    original_validate = commands.validate_patch;validated = []
    def reject_second(*args, **kwargs):
        validated.append(True)
        if len(validated) == 2: raise TargetStale('private stale fixture')
        return original_validate(*args, **kwargs)
    monkeypatch.setattr(commands, 'validate_patch', reject_second)
    assert accept_pending_suggestions(workspace[1], body, catalog=workspace[2])['code'] == 'TARGET_STALE'
    assert read(workspace)['counts']['pending'] == 2
    monkeypatch.setattr(commands, 'validate_patch', original_validate)
    original = BatchRepository.decide;writes = []
    def fail_second(self, row, decision, content, at):
        writes.append(row['id'])
        if len(writes) == 2: raise RuntimeError('private rollback fixture')
        return original(self, row, decision, content, at)
    monkeypatch.setattr(BatchRepository, 'decide', fail_second)
    assert accept_pending_suggestions(workspace[1], body, catalog=workspace[2])['code'] == 'INTERNAL_ERROR'
    assert read(workspace)['counts']['pending'] == 2


def test_bulk_http_strict_body_and_replay_returns_full_actual_pending_batch(workspace, monkeypatch):
    _, _, batch = pending(workspace, monkeypatch)
    app = FastAPI();app.state.walle_runtime = HttpRuntime(workspace[0], workspace[2], workspace[1]);app.include_router(batch_router)
    body = request(batch);headers = {'Idempotency-Key': body.pop('idempotency_key')};body.pop('batch_id')
    path = '/api/v1/suggestion-batches/1/accept-pending'
    with TestClient(app) as client:
        for ids in (None, [], [True], [1, 1], ['1'], list(range(1, 102))):
            assert client.post(path, json={**body, 'expected_pending_ids': ids}, headers=headers).status_code == 422
        assert client.post(path, json={**body, 'scope': 'DOCUMENT'}, headers=headers).status_code == 422
        first = client.post(path, json=body, headers=headers)
        assert first.status_code == 200, first.text
        assert first.json()['data']['batch']['counts']['pending'] == 0
        assert client.post(path, json=body, headers=headers).json()['data'] == first.json()['data']


def test_concurrent_nonpending_decision_is_preserved_without_rebinding_pending_set(workspace, monkeypatch):
    _, _, batch = pending(workspace, monkeypatch)
    first = batch['suggestions'][0]['id']
    assert decide(workspace, first, 'REJECTED')['code'] == 'SUGGESTION_DECIDED'
    body = request(read(workspace))
    assert decide(workspace, first, 'EDITED', '# 另一窗口已保存的标题')['code'] == 'SUGGESTION_DECIDED'
    actual = read(workspace)['suggestions'][0]
    result = accept_pending_suggestions(workspace[1], body, catalog=workspace[2])
    assert result['code'] == 'SUGGESTIONS_ACCEPTED', result
    assert result['data']['batch']['suggestions'][0] == actual
