"""The EV runner's paid-IO boundaries, using only private in-process delegates."""
import asyncio
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
from types import SimpleNamespace
import sys
from tempfile import TemporaryDirectory

import pytest

from backend.tests.requirements.test_v15_foundation import tmp_path, setup
from backend.tests.documents.test_v15_documents import workspace
from backend.tests.guide.test_v15_execution import PROFILE, Gateway, output, execute as offline_execute
from backend.tests.guide.test_v15_acceptance import accept
from backend.tests.guide.test_v15_counting import Counter, offline_gate
from backend.app.infrastructure.resources import ConfigInvalid


def runner():
    spec=spec_from_file_location('walle_v15_ev_runner_test',Path('tools/run-v15-evaluation.py'))
    module=module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module


def test_allowance_is_consumed_before_unknown_io_and_never_refunded_or_retried():
    tool=runner();allowance=tool.Allowance(PROFILE);case=allowance.for_case()
    class Unknown:
        calls=0
        async def count(self,*args):self.calls+=1;raise TimeoutError('unknown count outcome')
        async def send(self,*args):self.calls+=1;raise TimeoutError('unknown Chat outcome')
    delegate=Unknown()
    for _ in range(3):
        with pytest.raises(TimeoutError):asyncio.run(case.counter(delegate).count(PROFILE,('text',)))
    with pytest.raises(ConfigInvalid):asyncio.run(case.counter(delegate).count(PROFILE,('text',)))
    with pytest.raises(TimeoutError):asyncio.run(case.gateway(delegate).send(PROFILE,None))
    with pytest.raises(ConfigInvalid):asyncio.run(case.gateway(delegate).send(PROFILE,None))
    assert delegate.calls==4 and (allowance.counts,allowance.chats)==(3,1)
    never=allowance.for_case(chat_allowed=False)
    with pytest.raises(ConfigInvalid):asyncio.run(never.gateway(delegate).send(PROFILE,None))
    assert never.chat_suppressed and never.chat_calls==0 and delegate.calls==4
    altered=SimpleNamespace(snapshot={**PROFILE.snapshot,'max_tokens':1})
    with pytest.raises(ConfigInvalid):asyncio.run(allowance.for_case().counter(delegate).count(altered,('text',)))
    assert delegate.calls==4


def test_preview_never_reads_credentials_and_execute_requires_complete_exact_allowances(monkeypatch):
    tool=runner();calls=[]
    monkeypatch.setattr(tool,'preparation',lambda:SimpleNamespace(main=lambda args:calls.append(args) or 0))
    def forbidden(*args,**kwargs):raise AssertionError('Preview cannot load a provider profile')
    monkeypatch.setattr('backend.app.infrastructure.model_profile.ModelProfile.from_environment',forbidden)
    assert tool.main([])==0 and calls==[[]]
    for args in (['--credential-file','x'],['--execute'],['--execute','--allow-count-batches','79']):
        with pytest.raises(SystemExit):tool.main(args)


def test_aggregate_allowances_cannot_be_reset_with_new_case_objects():
    tool=runner();allowance=tool.Allowance(PROFILE)
    class Delegate:
        counts=chats=0
        async def count(self,*args):self.counts+=1
        async def send(self,*args):self.chats+=1
    delegate=Delegate()
    async def exhaust():
        for _ in range(26):
            case=allowance.for_case()
            for _ in range(3):await case.counter(delegate).count(PROFILE,('text',))
        for _ in range(24):await allowance.for_case().gateway(delegate).send(PROFILE,None)
        with pytest.raises(ConfigInvalid):await allowance.for_case().counter(delegate).count(PROFILE,('text',))
        with pytest.raises(ConfigInvalid):await allowance.for_case().gateway(delegate).send(PROFILE,None)
    asyncio.run(exhaust())
    assert (allowance.counts,allowance.chats,delegate.counts,delegate.chats)==(78,24,78,24)


def test_local_text_capacity_failure_does_not_consume_ev_network_allowance():
    from backend.app.infrastructure.tokenization import ExactCountUnavailable
    tool=runner();allowance=tool.Allowance(PROFILE);case=allowance.for_case()
    class NoIO:
        async def count(self,*args):raise AssertionError('No delegate before local byte check')
    with pytest.raises(ExactCountUnavailable) as failure:
        asyncio.run(case.counter(NoIO()).count(PROFILE,('汉'*266667,)))
    assert failure.value.reason == 'PROVIDER_INPUT_LIMIT'
    assert (allowance.counts,case.count_calls,allowance.chats) == (0,0,0)


def test_existing_report_is_not_modified_when_execute_preflight_refuses(monkeypatch):
    tool=runner()
    monkeypatch.setattr('backend.app.infrastructure.model_profile.ModelProfile.from_environment',lambda *args:PROFILE)
    monkeypatch.setattr('backend.app.infrastructure.local_credentials.read_local_credential',lambda *args:'private-offline')
    with TemporaryDirectory(prefix='walle-v15-ev-refusal-') as directory:
        root=Path(directory);(root/'data/existing').mkdir(parents=True)
        (root/'docs/verification/v1.5').mkdir(parents=True)
        report=root/'docs/verification/v1.5/existing.md';report.write_bytes(b'User-owned existing report\n')
        source=root/'source.sqlite';source.write_bytes(b'Not opened because output slot is already occupied')
        monkeypatch.setattr(tool,'ROOT',root)
        # Freeze inputs before switching the runner's isolated workspace root.
        original=runner().preparation();monkeypatch.setattr(tool,'preparation',lambda:original)
        assert tool.main(['--execute','--output-dir',str(root/'data/existing'),'--report',str(report),
            '--source-database',str(source),'--llm-use-id','1','--credential-file',str(root/'credential'),
            '--allow-count-batches','78','--allow-chat-calls','24','--max-total-tokens','3342336'])==1
        assert report.read_bytes()==b'User-owned existing report\n'


def test_all_fixed_inputs_execute_once_with_private_providers_and_real_postconditions(workspace,monkeypatch):
    tool=runner();inputs=tool.preparation();offline_gate(monkeypatch)
    assert accept(workspace)['code']=='GUIDE_ACCEPTED'
    assert offline_execute(workspace,Gateway())['code']=='AI_FINISHED'
    made=[]
    def returned(context):
        request=context.input['current_request'];operation=request['operation']
        if operation=='PROPOSE_CHANGES':
            from backend.app.documents.markdown import parse_markdown
            from backend.app.documents.tables import table_model
            doc=next(doc for doc in context.input['documents'] if 'TARGET' in doc['roles'])
            block=next(block for block in doc['blocks'] if block['block_type']=='table')
            table=table_model(parse_markdown(block['markdown_content']).blocks[0])
            domain=next(domain for domain in inputs.DOMAINS if domain.row_name in block['markdown_content'])
            return output(context,response_type='CHANGE_PROPOSALS',suggestions=[{'title':'固定目标行','explanation':'来源A的一行',
                'impact':None,'patch_operation':'REPLACE_TABLE_ROW','target_ref':{'block_id':block['block_id']},
                'selector_json':{'key_column_index':0,'key_value':domain.row_name},'original_content':table.rows[0].markdown,
                'proposed_markdown':None,'proposed_data_json':{'cells':[domain.row_name,domain.new_rule]}}])
        if operation in ('COMPARE','REVIEW'):
            return output(context,response_type='ANALYSIS',analysis={'conclusion':'RESULT','summary':'仅离线检查',
                'findings':[],'covered_refs':[doc['ref'] for doc in context.input['documents']],'unresolved':[]})
        if operation in ('GENERATE','REVISE'):
            target=request['target'];doc=next((doc for doc in context.input['documents'] if 'TARGET' in doc['roles']),None)
            return output(context,response_type='DOCUMENT_RESULT',document_result={'name':target['name'] if doc is None else doc['name'],
                'document_kind':target['document_kind'] if doc is None else doc['document_kind'],
                'markdown_content':'# 主流程\n\n已按绑定范围修订。\n' if doc else '# 目标\n\n独立离线稿。\n','change_summary':'离线样本'})
        return output(context)
    def gateway():
        value=Gateway(returned);made.append(value);return value
    class Counts(Counter):
        def __init__(self):super().__init__(['OK']*3)
        async def count(self,profile,texts):
            # Identify the deliberate fixture, never infer real token counts
            # from character length (the fixed source size can change).
            if '必须完整检查的来源' in texts[1]:self.decisions=['HIGH']*3
            return await super().count(profile,texts)
    monkeypatch.setattr('backend.app.infrastructure.model_gateway.ModelGateway',gateway)
    monkeypatch.setattr('backend.app.infrastructure.tokenization.TokenizationGateway',Counts)
    with TemporaryDirectory(prefix='walle-v15-ev-runner-') as directory:
        root=Path(directory);(root/'data').mkdir();(root/'docs/verification/v1.5').mkdir(parents=True)
        monkeypatch.setattr(tool,'ROOT',root)
        args=SimpleNamespace(source_database=workspace[0].path,llm_use_id=1,output_dir=root/'data/unique',report=root/'docs/verification/v1.5/result.md')
        assert tool.execute(args,PROFILE,workspace[2],inputs)==0
        report=args.report.read_text(encoding='utf-8')
        assert 'application source: '+tool.program_digest() in report
        assert 'actual_total_tokens=1300' in report and 'actual_text_counts=[500,500,' in report
        assert 'exact eight counts=[70000, 70000,' in report
        assert report.count('## ')==26 and report.count('PENDING HUMAN REVIEW')==26
        assert report.count('Program postcondition: PASSED')==6, report
        assert 'Chat=24.' in report and 'Batch stopped:' not in report
        assert sum(len(item.calls) for item in made)==24
        # A claimed batch cannot be sent again, even after a successful run.
        with pytest.raises(ValueError,match='new isolated'):tool.execute(args,PROFILE,workspace[2],inputs)
        assert sum(len(item.calls) for item in made)==24


def test_unknown_inflight_result_stops_before_preparing_or_sending_the_next_case(workspace,monkeypatch):
    tool=runner();inputs=tool.preparation();offline_gate(monkeypatch)
    assert accept(workspace)['code']=='GUIDE_ACCEPTED'
    assert offline_execute(workspace,Gateway())['code']=='AI_FINISHED'
    async def unknown(*args,**kwargs):return {'code':'INTERNAL_ERROR'}
    monkeypatch.setattr('backend.app.guide.orchestrator.execute_guide_run',unknown)
    with TemporaryDirectory(prefix='walle-v15-ev-unknown-') as directory:
        root=Path(directory);(root/'data').mkdir();(root/'docs/verification/v1.5').mkdir(parents=True)
        monkeypatch.setattr(tool,'ROOT',root)
        args=SimpleNamespace(source_database=workspace[0].path,llm_use_id=1,output_dir=root/'data/unknown',report=root/'docs/verification/v1.5/result.md')
        assert tool.execute(args,PROFILE,workspace[2],inputs)==1
        report=args.report.read_text(encoding='utf-8')
        assert report.count('## ')==1 and 'Batch stopped: unknown in-flight' in report
        assert not (args.output_dir/'movie/discuss-long-preference').exists()
        # Unknown slots are also permanently claimed.
        with pytest.raises(ValueError,match='new isolated'):tool.execute(args,PROFILE,workspace[2],inputs)


@pytest.mark.parametrize('reason,status,phase', [('HTTP_STATUS', 413, 'FAILED'),
    ('RESPONSE_CAPACITY', None, 'FAILED'), ('TRANSPORT_ERROR', None, 'INTERRUPTED')])
def test_count_failures_are_sanitized_and_stop_the_batch_before_any_chat(workspace,monkeypatch,reason,status,phase):
    import json
    from backend.app.infrastructure.tokenization import ExactCountUnavailable
    tool=runner();inputs=tool.preparation();offline_gate(monkeypatch)
    assert accept(workspace)['code']=='GUIDE_ACCEPTED'
    assert offline_execute(workspace,Gateway())['code']=='AI_FINISHED'
    class FailedCounter:
        calls=0
        async def count(self,*args):
            self.calls+=1
            detail=None if reason!='HTTP_STATUS' else {'body_state':'JSON_ERROR','category':'PARAMETER',
                'code':'InvalidParameter','parameter':'text','message':'private provider error '+PROFILE.api_key,
                'message_truncated':False,'request_id':'local-count-error'}
            raise ExactCountUnavailable(reason,status,provider_error=detail) from ValueError(PROFILE.api_key)
    failed=FailedCounter();gateway=Gateway()
    monkeypatch.setattr('backend.app.infrastructure.tokenization.TokenizationGateway',lambda:failed)
    monkeypatch.setattr('backend.app.infrastructure.model_gateway.ModelGateway',lambda:gateway)
    with TemporaryDirectory(prefix='walle-v15-ev-count-failure-') as directory:
        root=Path(directory);(root/'data').mkdir();(root/'docs/verification/v1.5').mkdir(parents=True)
        monkeypatch.setattr(tool,'ROOT',root)
        args=SimpleNamespace(source_database=workspace[0].path,llm_use_id=1,output_dir=root/'data/failed',report=root/'docs/verification/v1.5/result.md')
        assert tool.execute(args,PROFILE,workspace[2],inputs)==1
        report=args.report.read_text(encoding='utf-8')
        assert 'Batch stopped: failed/unknown exact counting evidence' in report
        assert 'Aggregate counts=1; Chat=0.' in report and report.count('## ')==1
        assert not (args.output_dir/'movie/discuss-long-preference').exists()
        assert failed.calls==1 and gateway.calls==[] and PROFILE.api_key not in report
        receipt=next(args.output_dir.rglob('*.finished.json'))
        value=json.loads(receipt.read_text(encoding='utf-8'))
        assert value['phase']==phase and value['failure_reason']==reason and value['http_status']==status
        assert PROFILE.api_key not in receipt.read_text(encoding='utf-8')
        if reason=='HTTP_STATUS':
            assert value['provider_error']['code']=='InvalidParameter' and value['provider_error']['parameter']=='text'
            assert 'private provider error' not in report
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(next(args.output_dir.rglob('evaluation.sqlite')))) as connection:
            message=connection.execute('SELECT error_message FROM guide_runs ORDER BY id DESC LIMIT 1').fetchone()[0]
            assert 'Token' in message and '计数' in message and PROFILE.api_key not in message


@pytest.mark.parametrize('has_response', [False, True])
def test_failed_transport_stops_batch_even_when_local_run_is_terminal(workspace, monkeypatch, has_response):
    tool=runner();inputs=tool.preparation();offline_gate(monkeypatch)
    assert accept(workspace)['code']=='GUIDE_ACCEPTED'
    assert offline_execute(workspace,Gateway())['code']=='AI_FINISHED'
    gateway=Gateway(output if has_response else lambda context:None,failed=True)
    monkeypatch.setattr('backend.app.infrastructure.model_gateway.ModelGateway',lambda:gateway)
    monkeypatch.setattr('backend.app.infrastructure.tokenization.TokenizationGateway',lambda:Counter(['OK']*3))
    with TemporaryDirectory(prefix='walle-v15-ev-transport-stop-') as directory:
        root=Path(directory);(root/'data').mkdir();(root/'docs/verification/v1.5').mkdir(parents=True)
        monkeypatch.setattr(tool,'ROOT',root)
        args=SimpleNamespace(source_database=workspace[0].path,llm_use_id=1,output_dir=root/'data/failed',report=root/'docs/verification/v1.5/result.md')
        assert tool.execute(args,PROFILE,workspace[2],inputs)==1
        report=args.report.read_text(encoding='utf-8')
        assert 'Batch stopped: failed/unknown Chat transport evidence' in report
        assert 'Aggregate counts=1; Chat=1.' in report and report.count('## ')==1
        assert not (args.output_dir/'movie/discuss-long-preference').exists()
        assert len(gateway.calls)==1
        from contextlib import closing
        import sqlite3
        with closing(sqlite3.connect(next(args.output_dir.rglob('evaluation.sqlite')))) as connection:
            assert connection.execute("SELECT count(*) FROM guide_runs WHERE status='RUNNING'").fetchone()[0]==0
            assert connection.execute('SELECT call_status FROM llm_uses').fetchone()[0]=='FAILED'
