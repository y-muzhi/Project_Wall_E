"""H06: exact budgets, historical reads, and explicit chapter transactions. No network."""
import asyncio
from dataclasses import replace
import json

import pytest

from backend.tests.requirements.test_v15_foundation import tmp_path, setup
from backend.tests.documents.test_v15_documents import workspace
from backend.tests.guide.test_v15_local_revision import seed
from backend.tests.guide.test_v15_acceptance import accept
from backend.tests.guide.test_v15_execution import Gateway, output
from backend.tests.guide.test_v15_counting import Counter, offline_gate
from backend.app.guide.orchestrator import execute_guide_run
from backend.app.guide.queries import get_guide_run
from backend.app.guide.model_calls import get_model_call
from backend.app.guide.collaboration_context import read_canonical
from backend.app.guide.collaboration_counting import restore_counted
from backend.app.infrastructure.model_profile import ModelProfile, DEFAULT_PROFILE, LONG_OUTPUT_PROFILE
from backend.app.infrastructure.resources import ResourceCatalog, ConfigInvalid


@pytest.mark.parametrize('name,limit', [(DEFAULT_PROFILE,8192),(LONG_OUTPUT_PROFILE,32768)])
def test_exact_profile_selection_and_snapshot_restoration(name, limit):
    profile=ModelProfile.from_environment({'WALLE_MODEL_API_KEY':'offline', 'WALLE_MODEL_PROFILE':name})
    assert profile.snapshot['max_tokens']==limit
    assert ModelProfile.from_snapshot(profile.snapshot).profile_id==name
    with pytest.raises(ConfigInvalid):
        ModelProfile.from_snapshot({**profile.snapshot,'max_tokens':limit+1})
    resources=ResourceCatalog().for_collaboration_profile(name).collaboration
    assert resources.counting['output_limit']==limit
    assert resources.counting['total_limit']==131072+limit
    with pytest.raises(ConfigInvalid): resources.require_live(profile.snapshot)


def test_new_budget_is_explicit_and_mismatched_environment_is_rejected():
    assert ModelProfile.selected_profile({})==DEFAULT_PROFILE
    for changes in ({'WALLE_MODEL_PROFILE':'unknown'}, {'WALLE_MODEL_PROFILE':LONG_OUTPUT_PROFILE,'WALLE_MODEL_ID':'doubao-seed-2-1-pro-260915'}):
        with pytest.raises(ConfigInvalid):ModelProfile.selected_profile(changes)


class LongGateway(Gateway):
    def __init__(self, make=output, *, tokens=17000, truncated=False):
        super().__init__(make);self.tokens=tokens;self.truncated=truncated;self.requests=[]
    async def send(self, profile, context):
        self.requests.append(profile.request(context))
        result=await super().send(profile,context)
        raw=json.loads(result.raw_response_json)
        raw['usage']={'prompt_tokens':1200,'completion_tokens':self.tokens,'total_tokens':1200+self.tokens}
        reason='length' if self.truncated else 'stop'
        raw['choices'][0]['finish_reason']=reason
        return replace(result,raw_response_json=json.dumps(raw),output_tokens=self.tokens,finish_reason=reason)


def execute(workspace, identity, gateway, profile_name=LONG_OUTPUT_PROFILE):
    return asyncio.run(execute_guide_run(workspace[0],{'guide_run_id':identity},process_lock=workspace[1].process_lock,
        catalog=workspace[2],profile=ModelProfile('offline-only',profile_name),gateway=gateway,counting_counter=Counter(['OK'])))


def test_long_output_uses_new_budget_and_history_reads_under_old_active_catalog(workspace, monkeypatch):
    offline_gate(monkeypatch)
    current=(*workspace[:2],workspace[2].for_collaboration_profile(LONG_OUTPUT_PROFILE))
    assert accept(current)['code']=='GUIDE_ACCEPTED'
    gateway=LongGateway()
    result=execute(current,1,gateway)
    assert result['code']=='AI_FINISHED',result
    assert len(gateway.requests)==1 and gateway.requests[0]['max_tokens']==32768
    with workspace[0].transaction() as connection:
        row=connection.execute('SELECT * FROM llm_uses').fetchone()
        saved=json.loads(row['request_snapshot_json'])
        assert row['validation_status']=='SUCCEEDED'
    detail=get_model_call(workspace[0],row['id'],catalog=workspace[2])
    assert detail['code']=='READ_OK',detail
    assert detail['data']['preflight']['budget']['output_tokens']==32768
    with pytest.raises(ConfigInvalid): restore_counted(saved,workspace[2],ModelProfile('offline',LONG_OUTPUT_PROFILE))


def test_old_saved_request_still_uses_8192_after_selecting_new_catalog(workspace,monkeypatch):
    offline_gate(monkeypatch);assert accept(workspace)['code']=='GUIDE_ACCEPTED'
    assert execute(workspace,1,Gateway(),DEFAULT_PROFILE)['code']=='AI_FINISHED'
    newer=workspace[2].for_collaboration_profile(LONG_OUTPUT_PROFILE)
    with workspace[0].transaction() as connection:
        row=connection.execute('SELECT * FROM llm_uses').fetchone();saved=json.loads(row['request_snapshot_json'])
        assert read_canonical(connection,1,newer,require_current=False)
    historical=newer.for_collaboration_release(saved['protocol']['release'])
    assert restore_counted(saved,historical,ModelProfile.from_snapshot(saved['profile']))
    assert get_model_call(workspace[0],row['id'],catalog=newer)['data']['preflight']['budget']['output_tokens']==8192


@pytest.mark.parametrize('tokens',[32768,32769])
def test_new_actual_usage_boundary(workspace,monkeypatch,tokens):
    offline_gate(monkeypatch);current=(*workspace[:2],workspace[2].for_collaboration_profile(LONG_OUTPUT_PROFILE))
    assert accept(current)['code']=='GUIDE_ACCEPTED'
    assert execute(current,1,LongGateway(tokens=tokens))['code']=='AI_FINISHED'
    with workspace[0].transaction() as connection:
        row=connection.execute('SELECT * FROM llm_uses').fetchone()
        assert row['validation_status']==('SUCCEEDED' if tokens==32768 else 'FAILED')


def test_two_explicit_chapters_then_truncation_keep_completed_content(workspace,monkeypatch):
    offline_gate(monkeypatch)
    current=(*workspace[:2],workspace[2].for_collaboration_profile(LONG_OUTPUT_PROFILE))
    document=seed(current,'# 第一章\n\n待写甲\n\n# 第二章\n\n待写乙\n\n# 第三章\n\n保留丙\n')
    original_third='# 第三章\n\n保留丙\n'
    for index,heading,body in [(1,1,'# 第一章\n\n第一章完整内容\n'),(2,3,'# 第二章\n\n第二章完整内容\n'),(3,5,'{"schema_version":1')]:
        with current[0].transaction() as connection:
            root=connection.execute('SELECT * FROM requirements').fetchone()
            before=dict(connection.execute('SELECT * FROM requirement_documents WHERE id=?',(document['id'],)).fetchone())
        accepted=accept(current,expected_discussion_version=root['discussion_version'],operation='REVISE',
            target={'kind':'EXISTING','document_id':document['id'],'expected_content_version':before['content_version']},
            scope={'scope_type':'SECTION','scope_ref':{'heading_block_id':heading}})
        assert accepted['code']=='GUIDE_ACCEPTED',accepted
        identity=accepted['data']['guide_run_id']
        gateway=LongGateway(lambda context:body if index==3 else output(context,response_type='DOCUMENT_RESULT',document_result={
            'name':document['name'],'document_kind':'brief','markdown_content':body,'change_summary':'本章完成'}),truncated=index==3)
        result=execute(current,identity,gateway);assert result['code']=='AI_FINISHED',result
        run=get_guide_run(current[0],identity)['data']
        assert run['application_result']==('NOT_APPLIED' if index==3 else 'APPLIED'),run
        with current[0].transaction() as connection:
            after=dict(connection.execute('SELECT * FROM requirement_documents WHERE id=?',(document['id'],)).fetchone())
        assert after['markdown_content'].endswith(original_third)
        if index>=2:assert '第一章完整内容' in after['markdown_content'] and '第二章完整内容' in after['markdown_content']
        if index==3:
            assert after['markdown_content']==before['markdown_content'] and after['content_version']==before['content_version']
            assert '输出不完整，未写入' in run['final_result']['summary']
            assert len(run['returned_responses'])==1
        assert len(gateway.calls)==1


def test_long_observation_keeps_exact_explicit_allowance(workspace):
    from backend.app.infrastructure.collaboration_observation import CollaborationObservation
    catalog=workspace[2].for_collaboration_profile(LONG_OUTPUT_PROFILE)
    profile=ModelProfile('offline-only',LONG_OUTPUT_PROFILE)
    assert accept((*workspace[:2],catalog))['code']=='GUIDE_ACCEPTED'
    with pytest.raises(ConfigInvalid):
        CollaborationObservation(workspace[0],1,catalog,profile,count_batches=1,chat_calls=1,total_tokens=139264)
    permit=CollaborationObservation(workspace[0],1,catalog,profile,count_batches=1,chat_calls=1,total_tokens=163840)
    assert permit.budget=={'count_batches':1,'chat_calls':1,'input_tokens':131072,'output_tokens':32768,'total_tokens':163840,'framing_reserve':1024,'transport_retries':0}
    assert permit.check(workspace[0],1,catalog,profile)
    assert permit.count_calls==permit.chat_calls==0


def test_truncated_generation_creates_no_document_and_explains_framework_route(workspace,monkeypatch):
    offline_gate(monkeypatch);current=(*workspace[:2],workspace[2].for_collaboration_profile(LONG_OUTPUT_PROFILE))
    assert accept(current,operation='GENERATE',target={'kind':'NEW','name':'长规格','document_kind':'specification','template_ref':None})['code']=='GUIDE_ACCEPTED'
    gateway=LongGateway(lambda context:'{"schema_version":1',truncated=True)
    assert execute(current,1,gateway)['code']=='AI_FINISHED'
    run=get_guide_run(current[0],1)['data']
    assert run['application_result']=='NOT_APPLIED' and '固定框架' in run['final_result']['summary']
    assert len(run['returned_responses'])==1 and len(gateway.calls)==1
    with current[0].transaction() as connection:
        assert connection.execute('SELECT count(*) FROM requirement_documents').fetchone()[0]==0
