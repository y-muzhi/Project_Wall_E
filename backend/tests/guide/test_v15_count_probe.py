"""Count-only diagnostic boundaries, using no provider connection."""
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
from tempfile import TemporaryDirectory
import json

import pytest

from backend.tests.guide.test_v15_execution import PROFILE
from backend.tests.guide.test_v15_counting import Counter
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.infrastructure.tokenization import ExactCountUnavailable


def tool():
    spec=spec_from_file_location('walle_v15_count_probe_test',Path('tools/count-v15-evaluation-once.py'))
    value=module_from_spec(spec);spec.loader.exec_module(value);return value


def test_preview_does_not_load_credentials_and_execution_requires_one_count_zero_chat(monkeypatch):
    value=tool();calls=[]
    from types import SimpleNamespace
    monkeypatch.setattr(value,'inputs',lambda:SimpleNamespace(main=lambda args:calls.append(args) or 0))
    def forbidden(*args,**kwargs):raise AssertionError('Preview may not load a key')
    monkeypatch.setattr('backend.app.infrastructure.model_profile.ModelProfile.from_environment',forbidden)
    assert value.main([])==0 and calls==[['--domain','movie','--case','analysis-required-over-budget']]
    for args in (['--execute'],['--allow-chat-calls','0'],['--execute','--allow-chat-calls','1']):
        with pytest.raises(SystemExit):value.main(args)


@pytest.mark.parametrize('outcome', ['over_budget','summary_over_budget','summary_within_budget','http_failure','unknown'])
def test_one_count_no_chat_safe_evidence_release_and_exclusive_slot(monkeypatch,outcome):
    value=tool();fixed=value.inputs();catalog=ResourceCatalog()
    class Counts(Counter):
        attempts=0
        async def count(self,profile,texts):
            self.attempts+=1
            if outcome=='http_failure':raise ExactCountUnavailable('HTTP_STATUS',413,provider_error={
                'body_state':'JSON_ERROR','category':'CONTEXT_LIMIT','code':None,'parameter':'text',
                'message':'PRIVATE_PROVIDER_MESSAGE '+PROFILE.api_key,'message_truncated':False,'request_id':'local-id',
                'body_keys':['detail']})
            if outcome=='unknown':raise TimeoutError(PROFILE.api_key)
            receipt = await super().count(profile,texts)
            if outcome in ('summary_over_budget','summary_within_budget'):
                from backend.app.infrastructure.tokenization import measurement_summary, restore_measurement
                return restore_measurement(measurement_summary(receipt.evidence), texts,
                    raw_required=False, expected_model=profile.model_name)
            return receipt
    counter=Counts(['OK' if outcome=='summary_within_budget' else 'HIGH'])
    def no_chat(*args,**kwargs):raise AssertionError('Count diagnostic must not create a Chat gateway')
    monkeypatch.setattr('backend.app.infrastructure.model_gateway.ModelGateway',no_chat)
    with TemporaryDirectory(prefix='walle-v15-count-probe-') as directory:
        root=Path(directory);(root/'data').mkdir();(root/'docs/verification/v1.5').mkdir(parents=True)
        monkeypatch.setattr(value,'ROOT',root)
        output=root/'data/unique';report=root/'docs/verification/v1.5/once.md'
        if outcome=='unknown':
            with pytest.raises(TimeoutError):value.count_once(output,report,PROFILE,catalog,counter=counter,fixed_inputs=fixed)
        else:
            assert value.count_once(output,report,PROFILE,catalog,counter=counter,fixed_inputs=fixed)==(0 if outcome in ('over_budget','summary_over_budget') else 1)
        assert counter.attempts==1
        text=report.read_text(encoding='utf-8');assert 'Chat=0' in text and PROFILE.api_key not in text
        receipt=json.loads(next(output.rglob('*.finished.json')).read_text(encoding='utf-8'))
        assert receipt['phase']=={'over_budget':'SUCCEEDED','summary_over_budget':'SUCCEEDED','summary_within_budget':'SUCCEEDED','http_failure':'FAILED','unknown':'INTERRUPTED'}[outcome]
        if outcome in ('summary_over_budget','summary_within_budget'):
            assert receipt['raw_omitted_reason'] == 'AUDIT_CAPACITY'
            assert 'response' not in receipt['measurement'] and len(receipt['measurement']['response_sha256']) == 64
        if outcome == 'summary_within_budget':
            assert 'over_budget=False' in text
        if outcome=='http_failure':
            assert receipt['failure_reason']=='HTTP_STATUS' and receipt['http_status']==413
            assert receipt['provider_error']['parameter']=='text'
            assert 'PRIVATE_PROVIDER_MESSAGE' not in text and 'category=CONTEXT_LIMIT' in text and "fields=['detail']" in text
            assert PROFILE.api_key not in json.dumps(receipt)
        import sqlite3
        c=sqlite3.connect(output/'counting.sqlite')
        assert c.execute('select count(*) from llm_uses').fetchone()[0]==0
        assert c.execute('select document_work_state from requirements').fetchone()[0]=='IDLE';c.close()
        with pytest.raises(ValueError,match='new isolated'):
            value.count_once(output,report,PROFILE,catalog,counter=counter,fixed_inputs=fixed)
        assert counter.attempts==1


def test_original_oversized_fixture_is_preserved_and_rejected_locally_without_count_or_chat(monkeypatch):
    import hashlib
    import sys
    from contextlib import closing
    import sqlite3
    path = Path('docs/sources/v1.5/prepare-v15-evaluation-v12-frozen.py')
    assert hashlib.sha256(path.read_bytes()).hexdigest() == '6b0de89db48479ef770d6cbc9d4df00a10ff0f748548359f8c72402d4066bdd3'
    spec = spec_from_file_location('walle_v15_original_fixed_input', path)
    original = module_from_spec(spec);sys.modules[spec.name] = original;spec.loader.exec_module(original)
    value = tool();catalog = ResourceCatalog()
    class NoIO:
        async def count(self, *args):raise AssertionError('Local limit must stop before a delegate is called')
    with TemporaryDirectory(prefix='walle-v15-count-capacity-') as directory:
        root = Path(directory);(root/'data').mkdir();(root/'docs/verification/v1.5').mkdir(parents=True)
        monkeypatch.setattr(value, 'ROOT', root)
        output = root/'data/unique';report = root/'docs/verification/v1.5/once.md'
        assert value.count_once(output, report, PROFILE, catalog, counter=NoIO(), fixed_inputs=original) == 1
        receipt = json.loads(next(output.rglob('*.finished.json')).read_text(encoding='utf-8'))
        assert receipt['failure_reason'] == 'PROVIDER_INPUT_LIMIT' and receipt['phase'] == 'FAILED'
        assert 'Tokenization sent=0; Chat=0' in report.read_text(encoding='utf-8')
        with closing(sqlite3.connect(output/'counting.sqlite')) as connection:
            assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0
            assert connection.execute('SELECT document_work_state FROM requirements').fetchone()[0] == 'IDLE'

    # Exercise the actual orchestration path too, including safe task feedback
    # and terminal release rather than only the diagnostic's explicit cancel.
    import asyncio
    from backend.app.infrastructure.database import Database
    from backend.app.infrastructure.process_lock import ProcessLock
    from backend.app.guide.orchestrator import execute_guide_run
    from backend.tests.guide.test_v15_counting import offline_gate
    offline_gate(monkeypatch)
    with TemporaryDirectory(prefix='walle-v15-count-capacity-run-') as directory:
        database = Database(Path(directory)/'isolated.sqlite');database.initialize()
        with ProcessLock.for_database(database.path) as lock:
            identity, _, _ = original.prepare_case(database, lock, catalog, original.DOMAINS[0], 'analysis-required-over-budget')
            class NoChat:
                async def send(self,*args):raise AssertionError('No Chat after local capacity failure')
            asyncio.run(execute_guide_run(database, {'guide_run_id': identity}, process_lock=lock,
                catalog=catalog, profile=PROFILE, counting_counter=NoIO(), gateway=NoChat()))
            with database.transaction() as connection:
                row = connection.execute('SELECT status,error_code,error_message FROM guide_runs').fetchone()
                assert row['status'] == 'FAILED' and row['error_code'] == 'CONFIG_INVALID'
                assert '800,000' in row['error_message'] and '当前计数批次未发送' in row['error_message']
                assert connection.execute('SELECT document_work_state FROM requirements').fetchone()[0] == 'IDLE'
                assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0
            receipt = json.loads(next(Path(directory).rglob('*.finished.json')).read_text(encoding='utf-8'))
            assert receipt['failure_reason'] == 'PROVIDER_INPUT_LIMIT' and receipt['http_status'] is None
