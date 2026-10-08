"""D-014 exact profile migration on native SQLite and loopback TCP only.

Synthetic replies/counts and expanded private compiler budgets are diagnostics,
not provider compatibility or effect evidence. No real credentials or paid I/O.
"""
from copy import deepcopy
import json
import unittest

from backend.app.guide.context_builder import build_context
from backend.app.guide.counted_context import counting_release, release_identity, compile_counted_candidate, DEEPSEEK_RELEASE_SHA256
from backend.app.infrastructure.production_ai import before_count
from backend.app.infrastructure.model_profile import (
    ModelProfile, MODEL_ID, MODEL_VERSION, DEEPSEEK_MODEL_ID,
    DEEPSEEK_MODEL_VERSION, DEFAULT_PROFILE,
)
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.infrastructure.tokenization import restore_measurement, measurement_summary, DEEPSEEK_STRATEGY
from backend.app.infrastructure.framing_probe import collect_observations, digest
from backend.app.shared.command_execution import Rejected
from backend.tests.infrastructure import test_audit_repository as audit
from backend.tests.infrastructure import test_tokenization as count_tcp
from backend.tests.infrastructure.test_framing_probe import prepared
from backend.tests.guide import test_orchestrator as orch
from backend.tests.guide import test_result_persistence as persistence


def deepseek():
    return ModelProfile.from_environment({'WALLE_MODEL_API_KEY':audit.KEY})


class DeepSeekProfileTests(unittest.TestCase):
    def test_startup_default_and_exact_legacy_override_restore_their_own_snapshot(self):
        current=deepseek()
        self.assertEqual((current.profile_id,current.model_name,current.model_version),
                         (DEFAULT_PROFILE,DEEPSEEK_MODEL_ID,DEEPSEEK_MODEL_VERSION))
        old=ModelProfile.from_environment({'WALLE_MODEL_API_KEY':audit.KEY,
                                         'WALLE_MODEL_ID':MODEL_ID,'WALLE_MODEL_VERSION':MODEL_VERSION})
        self.assertEqual(old,ModelProfile(audit.KEY))
        for profile in (old,current):
            restored=ModelProfile.from_snapshot(profile.snapshot)
            self.assertEqual(restored.snapshot,profile.snapshot)
            self.assertNotIn(audit.KEY,repr(profile))
            self.assertNotIn(audit.KEY,json.dumps(profile.snapshot))
        for model,version in ((DEEPSEEK_MODEL_ID,MODEL_VERSION),(MODEL_ID,DEEPSEEK_MODEL_VERSION),
                              ('deepseek-v4-1-flash',DEEPSEEK_MODEL_VERSION)):
            with self.assertRaises(ConfigInvalid):
                ModelProfile.from_environment({'WALLE_MODEL_API_KEY':audit.KEY,
                                              'WALLE_MODEL_ID':model,'WALLE_MODEL_VERSION':version})

    def test_snapshot_cannot_change_types_parameters_or_add_fields(self):
        for profile in (ModelProfile(audit.KEY),deepseek()):
            for field,value in (('temperature',False),('temperature',0.0),('transport_retries',False),
                                ('max_tokens',True),('stream',0),('model_version','latest'),
                                ('thinking',{'type':'enabled'}),('extra',None)):
                snapshot=profile.snapshot;snapshot[field]=value
                with self.subTest(model=profile.model_name,field=field),self.assertRaises(ConfigInvalid):
                    ModelProfile.from_snapshot(snapshot)

    def test_deepseek_release_is_independent_has_no_invented_framing_reserve(self):
        old=counting_release(ModelProfile(audit.KEY));current=counting_release(deepseek(),release_sha256=DEEPSEEK_RELEASE_SHA256)
        self.assertNotEqual(release_identity(deepseek()),release_identity(ModelProfile(audit.KEY)))
        self.assertEqual(current['model'],DEEPSEEK_MODEL_ID)
        self.assertEqual(current['model_version'],DEEPSEEK_MODEL_VERSION)
        self.assertIsNone(current['framing_reserve_candidate'])
        self.assertFalse(current['production_enabled']);self.assertFalse(current['provider_compatibility_proved'])
        self.assertEqual(current['budget'],old['budget']);self.assertEqual(current['trim_order'],old['trim_order'])


class DeepSeekAuditTests(unittest.TestCase):
    def setUp(self):
        self.f=audit.AuditRepositoryTests();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def test_stored_legacy_response_parses_after_new_default_selection(self):
        f=self.f;identity=f.prepare()['id'];f.transport(identity)
        self.assertEqual(deepseek().model_name,DEEPSEEK_MODEL_ID)
        self.assertEqual(f.parse(identity)['response_type'],'INITIALIZE_TEXT')
        row=f.row('llm_uses',identity)
        self.assertEqual((row['model_name'],row['model_version']),(MODEL_ID,MODEL_VERSION))
        self.assertEqual(json.loads(row['request_snapshot_json'])['profile'],ModelProfile(audit.KEY).snapshot)

    def test_wrong_transport_profile_rejected_without_changing_audit_or_run(self):
        f=self.f;identity=f.prepare()['id'];before=f.facts();f.profile=deepseek()
        with self.assertRaises(Rejected) as failure:f.transport(identity)
        self.assertEqual(failure.exception.code,'CONFIG_INVALID');self.assertEqual(f.facts(),before)

    def test_same_call_retry_cannot_switch_frozen_model_and_keeps_failure(self):
        f=self.f;identity=f.prepare()['id'];f.transport(identity,f.response(content='bad JSON'));f.parse(identity)
        before=f.facts();f.profile=deepseek()
        with self.assertRaises(Rejected) as failure:f.prepare(at=audit.T3,call_no=1)
        self.assertEqual(failure.exception.code,'CONFIG_INVALID');self.assertEqual(f.facts(),before)

    def test_deepseek_parse_uses_stored_profile_and_refuses_old_response_model(self):
        f=self.f;f.profile=deepseek();identity=f.prepare()['id']
        f.transport(identity,f.response(model=MODEL_ID))
        self.assertIsNone(f.parse(identity))
        self.assertEqual(f.row('llm_uses',identity)['parse_status'],'FAILED')
        self.assertIsNone(f.row('llm_uses',identity)['trusted_output_json'])


class DeepSeekCountTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.w=count_tcp.TokenizationTests();self.w.setUp();self.addCleanup(self.w.tearDown)

    async def test_actual_count_tcp_binds_new_request_response_and_summary_without_old_strategy(self):
        response=count_tcp.envelope();response['model']=DEEPSEEK_MODEL_ID
        self.w.server.body=json.dumps(response).encode()
        result=await self.w.gateway.count(deepseek(),count_tcp.TEXTS)
        self.assertEqual(json.loads(self.w.server.receipts[0]['body'])['model'],DEEPSEEK_MODEL_ID)
        self.assertEqual(result.evidence['strategy'],DEEPSEEK_STRATEGY)
        self.assertEqual(restore_measurement(result.evidence,count_tcp.TEXTS,expected_model=DEEPSEEK_MODEL_ID),result)
        summary=measurement_summary(result.evidence)
        self.assertEqual(restore_measurement(summary,count_tcp.TEXTS,raw_required=False,
                                           expected_model=DEEPSEEK_MODEL_ID).counts,result.counts)
        for evidence,raw in ((result.evidence,True),(summary,False)):
            with self.assertRaises(ConfigInvalid):restore_measurement(evidence,count_tcp.TEXTS,raw_required=raw)
        self.assertTrue(all(t.closed for t in self.w.transports))

    async def test_deepseek_counter_refuses_legacy_response_without_retry(self):
        with self.assertRaises(ConfigInvalid):await self.w.gateway.count(deepseek(),count_tcp.TEXTS)
        self.assertEqual(len(self.w.server.receipts),1)
        self.assertTrue(all(t.closed for t in self.w.transports))

    async def test_old_paid_plan_cannot_transfer_to_new_profile_or_create_journal(self):
        import tempfile
        from pathlib import Path
        plan=deepcopy(prepared())
        with tempfile.TemporaryDirectory(prefix='walle-d014-plan-') as directory:
            path=Path(directory)/'must-not-exist'
            with self.assertRaises(ConfigInvalid):
                await collect_observations(plan,deepseek(),path,authorized_plan_sha256=digest(plan),
                                           counter=self.w.gateway)
            self.assertFalse(path.exists());self.assertEqual(self.w.server.receipts,[])


class DeepSeekProofTests(unittest.TestCase):
    def fixture(self,profile,v2=False):
        h=persistence.ResultPersistenceTests();h.setUp();self.addCleanup(h.doCleanups)
        if v2:h.helper.v2()
        f=h.fixture;f.profile=profile;original=f.response
        f.response=lambda content=None,**changes:original(content,**({'model':profile.model_name}|changes))
        return h

    def test_old_and_new_audits_validate_and_persist_both_frozen_resource_versions(self):
        for profile in (ModelProfile(audit.KEY),deepseek()):
            for v2 in (False,True):
                with self.subTest(model=profile.model_name,v2=v2):
                    h=self.fixture(profile,v2);f=h.fixture
                    current=f.row('requirement_documents',f.created['current_document_id'])
                    identity=h.helper.candidate();receipt=h.helper.produce(identity)
                    self.assertIsNotNone(receipt);self.assertEqual(receipt.prompt_version,'v2' if v2 else 'v1')
                    stored=f.row('llm_uses',identity)
                    self.assertEqual(h.persist(receipt)['code'],'AI_RESULT_PERSISTED')
                    self.assertEqual(f.row('llm_uses',identity),stored)
                    self.assertEqual(f.row('requirement_documents',current['id']),current)
                    self.assertEqual(f.row('guide_runs',f.run)['status'],'COMPLETED')

    def test_boolean_lookalikes_in_stored_profile_and_request_cannot_pass_adoption(self):
        for place in ('profile','request'):
            h=self.fixture(deepseek());f=h.fixture;identity=h.helper.candidate()
            with f.database.transaction(write=True) as connection:
                snapshot=json.loads(f.row('llm_uses',identity)['request_snapshot_json'])
                snapshot[place]['temperature']=False
                connection.execute('UPDATE llm_uses SET request_snapshot_json=? WHERE id=?',(json.dumps(snapshot),identity))
            before=f.facts()
            with self.assertRaises(Rejected) as failure:h.helper.produce(identity)
            self.assertEqual(failure.exception.code,'CONFIG_INVALID');self.assertEqual(f.facts(),before)


class DeepSeekOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.h=orch.OrchestratorTests();await self.h.asyncSetUp()
        self.addCleanup(lambda:self.assertTrue(self.h.helper.doCleanups()))
        self.addAsyncCleanup(self.h.asyncTearDown)
        self.f=self.h.fixture;self.f.profile=deepseek()

    async def test_new_model_loopback_response_audit_validation_and_c07_atomically_complete(self):
        current=self.f.row('requirement_documents',self.f.created['current_document_id'])
        self.h.queue()
        status,body,headers,behavior=self.h.server.responses.pop()
        response=json.loads(body);response['model']=DEEPSEEK_MODEL_ID
        self.h.server.responses.append((status,json.dumps(response).encode(),headers,behavior))
        outcome=await self.h.advance()
        self.assertEqual(outcome['code'],'AI_FINISHED',outcome)
        self.assertEqual(len(self.h.server.receipts),1)
        sent=json.loads(self.h.server.receipts[0]['body']);self.assertEqual(sent['model'],DEEPSEEK_MODEL_ID)
        row=self.h.attempts()[0]
        self.assertEqual((row['model_name'],row['model_version']),(DEEPSEEK_MODEL_ID,DEEPSEEK_MODEL_VERSION))
        self.assertEqual((row['call_status'],row['parse_status'],row['validation_status']),('SUCCEEDED',)*3)
        self.assertEqual(json.loads(row['request_snapshot_json'])['profile'],self.f.profile.snapshot)
        self.assertEqual(self.f.row('requirement_documents',current['id']),current)
        self.assertEqual(self.f.row('requirements',self.f.req)['document_work_state'],'IDLE')
        before=self.f.facts();self.assertEqual((await self.h.advance())['code'],'AI_STOPPED')
        self.assertEqual(self.f.facts(),before);self.assertEqual(len(self.h.server.receipts),1)

    async def test_no_deepseek_admission_blocks_before_count_chat_and_audit(self):
        w=count_tcp.TokenizationTests();w.setUp();self.addCleanup(w.tearDown)
        result=await self.h.advance(context_compiler=build_context,counting_counter=w.gateway,
                                    counting_compatibility_check=before_count)
        self.assertEqual(result['code'],'AI_FAILED',result)
        self.assertEqual(result['details']['error_code'],'CONFIG_INVALID')
        self.assertEqual(w.server.receipts,[]);self.assertEqual(self.h.server.receipts,[])
        self.assertEqual(self.h.attempts(),[])
        self.assertEqual(self.f.row('requirements',self.f.req)['document_work_state'],'IDLE')

    async def test_production_compatibility_gate_remains_closed_for_new_default(self):
        # Expand only the offline compiler budget to reach the distinct proof
        # gate; the real builder's earlier budget rejection remains intact.
        result=await self.h.advance(compatibility_check=None)
        self.assertEqual(result['code'],'AI_FAILED',result)
        self.assertEqual(result['details']['error_code'],'CONFIG_INVALID')
        self.assertEqual(self.h.server.receipts,[]);self.assertEqual(self.h.attempts(),[])
