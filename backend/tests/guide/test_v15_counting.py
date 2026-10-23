"""Private exact-count fixtures; no Tokenization or Chat network requests."""
import asyncio
from dataclasses import replace
import hashlib
import json
from uuid import uuid4

import pytest

from backend.tests.requirements.test_v15_foundation import tmp_path, setup
from backend.tests.documents.test_v15_documents import workspace, document
from backend.tests.guide.test_v15_acceptance import accept
from backend.app.guide.collaboration_context import read_canonical
from backend.app.guide.collaboration_counting import compile_counted, verify_counted
from backend.app.guide.context_builder import ContextLimitExceeded
from backend.app.infrastructure.collaboration_resources import CollaborationResources
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.infrastructure.model_profile import ModelProfile, DEFAULT_PROFILE
from backend.app.infrastructure.practical_usage import validate_collaboration_usage
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.infrastructure.tokenization import TokenCounts


def measurement(profile, texts, counts):
    request = json.dumps({'model': profile.model_name, 'text': list(texts)}, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    rows = [{'object': 'tokenization', 'index': index, 'total_tokens': count, 'token_ids': [1]*count, 'offset_mapping': [[0, 0]]*count} for index, count in enumerate(counts)]
    response = {'object': 'list', 'model': profile.model_name, 'id': 'offline-only-count', 'created': 1, 'data': rows}
    return TokenCounts(profile.model_name, response['id'], 1, tuple(counts), tuple(hashlib.sha256(text.encode('utf-8')).hexdigest() for text in texts), hashlib.sha256(request).hexdigest(), json.dumps(response))


class Counter:
    def __init__(self, decisions):
        self.decisions = decisions;self.calls = []

    async def count(self, profile, texts):
        self.calls.append(texts)
        if self.decisions[len(self.calls)-1] == 'FAIL':
            raise ConfigInvalid('Injected count failure')
        high = self.decisions[len(self.calls)-1] == 'HIGH'
        counts = [70000 if high else 500, 70000 if high else 500, *[1 if text else 0 for text in texts[2:]]]
        return measurement(profile, texts, counts)


def inputs(workspace, *, neighbors=False, history=False):
    if history:
        with workspace[0].transaction(write=True) as connection:
            at = connection.execute('SELECT updated_at FROM requirements WHERE id=1').fetchone()[0]
            identity = entity_id(connection, EntityKind.MESSAGE)
            MessageRepository(connection).create_user_text(identity, 1, None, '可选旧历史', str(uuid4()), at)
    changes = {}
    if neighbors:
        current = document(workspace, reference=workspace[2].collaboration.reference('structure.brief'))['data']['document']
        changes = {'operation': 'REVISE', 'target': {'kind': 'EXISTING', 'document_id': current['id'], 'expected_content_version': 1},
            'scope': {'scope_type': 'BLOCK', 'scope_ref': {'block_id': current['block_state_json']['blocks'][3]['block_id']}}}
    assert accept(workspace, **changes)['code'] == 'GUIDE_ACCEPTED'
    with workspace[0].transaction() as connection:
        return read_canonical(connection, 1, workspace[2])


def offline_gate(monkeypatch):
    # Explicit private test substitution. No runtime configuration/HTTP path
    # can change the frozen OFFLINE_READY release or install this override.
    calls = []
    monkeypatch.setattr(CollaborationResources, 'require_live', lambda self, profile, **private: calls.append(profile))
    return calls


def test_offline_release_blocks_before_the_first_count(workspace):
    counter = Counter(['OK']);canonical = inputs(workspace)
    with pytest.raises(ConfigInvalid):
        asyncio.run(compile_counted(canonical, workspace[2], ModelProfile('offline', DEFAULT_PROFILE), counter=counter))
    assert counter.calls == []


def test_first_acceptable_candidate_counts_exactly_eight_texts_once_and_replays(workspace, monkeypatch):
    gates = offline_gate(monkeypatch);counter = Counter(['OK']);canonical = inputs(workspace)
    profile = ModelProfile('offline', DEFAULT_PROFILE)
    result = asyncio.run(compile_counted(canonical, workspace[2], profile, counter=counter))
    assert len(counter.calls) == 1 and len(counter.calls[0]) == 8 and len(gates) == 2
    assert result.counting_evidence['input_tokens_candidate'] == 2024
    assert verify_counted(result, workspace[2], profile) == result.counting_evidence
    assert result.counting_evidence['compatibility_proved'] is False
    altered = result.counting_evidence;altered['release_sha256'] = '0'*64
    with pytest.raises(ConfigInvalid):
        verify_counted(replace(result, counting_json=json.dumps(altered)), workspace[2], profile)


def test_three_candidates_remove_history_then_only_optional_neighbors(workspace, monkeypatch):
    offline_gate(monkeypatch);counter = Counter(['HIGH', 'HIGH', 'OK']);canonical = inputs(workspace, history=True, neighbors=True)
    profile = ModelProfile('offline', DEFAULT_PROFILE)
    result = asyncio.run(compile_counted(canonical, workspace[2], profile, counter=counter))
    assert len(counter.calls) == 3
    assert [len(json.loads(texts[1])['recent_history']) for texts in counter.calls] == [2, 0, 0]
    assert [len(json.loads(texts[1])['documents'][0]['blocks']) for texts in counter.calls] == [5, 5, 1]
    assert '电影' in result.input_json and result.input['current_request']['content']
    assert verify_counted(result, workspace[2], profile) == result.counting_evidence


def test_no_optional_material_skips_duplicate_candidates_and_never_retries_count_failures(workspace, monkeypatch):
    offline_gate(monkeypatch);canonical = inputs(workspace);profile = ModelProfile('offline', DEFAULT_PROFILE)
    counter = Counter(['HIGH'])
    with pytest.raises(ContextLimitExceeded):
        asyncio.run(compile_counted(canonical, workspace[2], profile, counter=counter))
    assert len(counter.calls) == 1
    failed = Counter(['FAIL'])
    with pytest.raises(ConfigInvalid):
        asyncio.run(compile_counted(canonical, workspace[2], profile, counter=failed))
    assert len(failed.calls) == 1


def test_actual_usage_requires_the_new_release_eight_counts_and_bounded_observed_framing(workspace, monkeypatch):
    offline_gate(monkeypatch);profile = ModelProfile('offline', DEFAULT_PROFILE)
    context = asyncio.run(compile_counted(inputs(workspace), workspace[2], profile, counter=Counter(['OK'])))
    raw = {'object': 'chat.completion', 'model': profile.model_name, 'usage': {'prompt_tokens': 1200, 'completion_tokens': 100, 'total_tokens': 1300}}
    validate_collaboration_usage(raw, profile=profile, context=context, catalog=workspace[2], input_tokens=1200, output_tokens=100)
    for usage in [{'prompt_tokens': 999, 'completion_tokens': 100, 'total_tokens': 1099},
            {'prompt_tokens': 2025, 'completion_tokens': 100, 'total_tokens': 2125},
            {'prompt_tokens': 1200, 'completion_tokens': 8193, 'total_tokens': 9393}]:
        with pytest.raises(ConfigInvalid):
            validate_collaboration_usage({**raw, 'usage': usage}, profile=profile, context=context, catalog=workspace[2], input_tokens=usage['prompt_tokens'], output_tokens=usage['completion_tokens'])
