"""Invalid actual usage stays readable and cannot apply model business output."""
from dataclasses import replace
import json

import pytest

from backend.tests.requirements.test_v15_foundation import tmp_path, setup, counts
from backend.tests.documents.test_v15_documents import workspace
from backend.tests.guide.test_v15_acceptance import accept
from backend.tests.guide.test_v15_counting import offline_gate
from backend.tests.guide.test_v15_execution import execute, Gateway, output, delta
from backend.app.guide.queries import get_guide_run
from backend.app.guide.model_calls import get_model_call, list_model_calls


@pytest.mark.parametrize('total,cache', [(9999, None), (None, None), (1300, 1201)])
def test_provider_total_and_cache_anomalies_remain_original_and_do_not_write_content_or_progress(workspace, monkeypatch, total, cache):
    offline_gate(monkeypatch)
    assert accept(workspace, operation='GENERATE', target={'kind': 'NEW', 'name': '不应写入的稿件', 'document_kind': 'brief', 'template_ref': None})['code'] == 'GUIDE_ACCEPTED'
    class UsageGateway(Gateway):
        async def send(self, profile, context):
            result = await super().send(profile, context);raw = result.raw_response
            if total is None: raw['usage'].pop('total_tokens')
            else: raw['usage']['total_tokens'] = total
            if cache is not None: raw['usage']['prompt_tokens_details'] = {'cached_tokens': cache}
            return replace(result, raw_response_json=json.dumps(raw), cache_info_json=None if cache is None else json.dumps({'cached_tokens': cache}))
    gateway = UsageGateway(lambda context: output(context, response_type='DOCUMENT_RESULT', document_result={
        'name': '不应写入的稿件', 'document_kind': 'brief', 'markdown_content': '完整但不可采用的正文。', 'change_summary': '不可应用'}, progress_delta=delta(context)))
    assert execute(workspace, gateway)['code'] == 'AI_FINISHED'
    assert len(gateway.calls) == 1 and counts(workspace[0])['requirement_documents'] == counts(workspace[0])['revisions'] == 0
    run = get_guide_run(workspace[0], 1, catalog=workspace[2]);assert run['code'] == 'READ_OK', run
    assert run['data']['application_result'] == 'NOT_APPLIED' and run['data']['progress_result'] != 'APPLIED'
    assert run['data']['returned_responses']
    listing = list_model_calls(workspace[0], 1);detail = get_model_call(workspace[0], 1)
    assert listing['code'] == detail['code'] == 'READ_OK'
    for actual in (listing['data']['items'][0], detail['data']['call']):
        assert actual['input_tokens'] == 1200 and actual['output_tokens'] == 100
        assert actual['total_tokens'] == total and actual['cached_tokens'] == cache
    with workspace[0].transaction() as connection:
        row = connection.execute('SELECT validation_status,raw_response_json FROM llm_uses').fetchone()
        assert row[0] == 'FAILED' and json.loads(row[1])['usage'].get('total_tokens') == total
        assert json.loads(connection.execute('SELECT discussion_state_json FROM requirements').fetchone()[0])['pending_user_message_ids'] == [2]
