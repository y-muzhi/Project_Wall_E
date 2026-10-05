"""Actual audit/C03/schema/business receipts, no C07 or model-effect claim.

Prepared inputs use explicitly expanded diagnostic budgets and persisted
response fixtures. Production budget and Provider gates are not bypassed.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing,contextmanager
from copy import deepcopy
from dataclasses import replace,FrozenInstanceError
from datetime import timedelta
import json
import sqlite3
import unittest
from unittest.mock import patch as fault

from backend.app.guide import commands
from backend.app.guide.context_builder import build_context
from backend.app.guide.queries import get_model_context
from backend.app.guide.trusted_output import produce_trusted_output,require_receipt,TrustedOutput
from backend.app.infrastructure.audit_repository import AuditRepository
from backend.app.infrastructure.database import CommitOutcomeUnknown
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.shared.command_execution import Rejected
from backend.app.shared.time import utc_milliseconds
from backend.tests.infrastructure import test_audit_repository as audit
from backend.tests.guide import test_acceptance as acceptance
from backend.tests.requirements import test_create_requirement as creation
from backend.tests.messages.test_queries import cards_fixture
from backend.app.guide.output_evidence import card_text


class TrustedOutputTests(unittest.TestCase):
    def setUp(self):
        self.fixture=audit.AuditRepositoryTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)

    def produce(self,identity,seconds=4):
        fixture=self.fixture
        return produce_trusted_output(fixture.database,identity,process_lock=fixture.lock,profile=fixture.profile,catalog=fixture.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=seconds))

    def candidate(self,value=None,base=0,call_no=None):
        at=lambda seconds:utc_milliseconds(creation.INSTANT+timedelta(seconds=base+seconds))
        fixture=self.fixture;identity=fixture.prepare(at=at(1),call_no=call_no)['id']
        raw=fixture.response() if value is None else fixture.response(json.dumps(value,ensure_ascii=False))
        fixture.transport(identity,raw,at=at(2));fixture.parse(identity,at=at(3))
        return identity

    def v2(self,instruction='实际新v2用户输入'):
        fixture=self.fixture
        self.assertEqual(commands.cancel_guide_run(fixture.executor,{'guide_run_id':fixture.run,'idempotency_key':creation.OTHER},clock=lambda:creation.INSTANT)['code'],'GUIDE_CANCELLED')
        fixture.catalog=ResourceCatalog()
        result=commands.create_guide_run(fixture.executor,{'requirement_id':fixture.req,'expected_content_version':1,'action_type':'INITIALIZE','instruction':instruction,
            'scope_type':'DOCUMENT','source_type':'USER_INSTRUCTION','idempotency_key':acceptance.KEY},catalog=fixture.catalog,clock=lambda:creation.INSTANT)
        self.assertEqual(result['code'],'GUIDE_ACCEPTED',result);fixture.run=result['data']['guide_run']['id']
        self.compile()

    def compile(self):
        fixture=self.fixture;row=fixture.row('guide_runs',fixture.run)
        fixture.function=fixture.catalog.restore(row['function_type'],row['prompt_version'])
        policy=fixture.function.context_policy;policy['budget'].update(prompt_tokens=100000,input_tokens=100000,total_tokens=120000)
        fixture.context=build_context(get_model_context(fixture.database,fixture.run,catalog=fixture.catalog)['data'],replace(fixture.function,context_json=json.dumps(policy)))

    def test_real_v1_empty_initialize_receipt_and_audit_commit_detached_no_business_writes(self):
        fixture=self.fixture;identity=self.candidate();before={table:fixture.row(table,value) for table,value in (('requirements',fixture.req),('requirement_documents',fixture.created['current_document_id']),('conversation_messages',1))}
        receipt=self.produce(identity);self.assertIsInstance(receipt,TrustedOutput);self.assertIs(require_receipt(receipt),receipt)
        row=fixture.row('llm_uses',identity)
        self.assertEqual((row['validation_status'],row['validation_error'],row['error_code']),('SUCCEEDED',None,None))
        self.assertEqual(json.loads(row['trusted_output_json']),receipt.output)
        self.assertEqual((receipt.guide_run_id,receipt.llm_use_id,receipt.trigger_message_id),(fixture.run,identity,1))
        self.assertEqual((receipt.document_id,receipt.content_version),(fixture.created['current_document_id'],1))
        with self.assertRaises(FrozenInstanceError):receipt.content_version=2
        detached=receipt.output;detached['message']='changed';self.assertNotEqual(detached,receipt.output)
        self.assertNotIn('diagnostic response fixture',repr(receipt));self.assertNotIn(audit.KEY,repr(receipt))
        for table,value in (('requirements',fixture.req),('requirement_documents',fixture.created['current_document_id']),('conversation_messages',1)):
            self.assertEqual(fixture.row(table,value),before[table])
        self.assertEqual(fixture.row('guide_runs',fixture.run)['status'],'RUNNING')
        facts=fixture.facts();self.assertEqual(self.produce(identity,seconds=5),receipt);self.assertEqual(fixture.facts(),facts)

    def test_original_unknown_reasoning_field_fails_even_when_parsed_audit_removed_it(self):
        value={'schema_version':1,'response_type':'INITIALIZE_TEXT','message':'原候选','confirmed_fact_patches':[],'reasoning':'非法未知字段'}
        identity=self.candidate(value);row=self.fixture.row('llm_uses',identity)
        self.assertNotIn('reasoning',json.loads(row['parsed_output_json']))
        self.assertIsNone(self.produce(identity));row=self.fixture.row('llm_uses',identity)
        self.assertEqual((row['validation_status'],row['trusted_output_json'],row['error_code']),('FAILED',None,'OUTPUT_INVALID'))
        self.assertEqual(row['call_status'],'SUCCEEDED');self.assertIsNotNone(row['raw_response_json'])
        with self.assertRaises(Rejected):self.produce(identity,seconds=5)

    def test_actual_v2_card_receipt_preserves_original_complete_message_and_snapshot(self):
        self.v2();cards=cards_fixture();cards['cards'][0]['related_spec_context']=[]
        value={'schema_version':1,'response_type':'INITIALIZE_CARDS','message':card_text(cards),'cards':cards,'confirmed_fact_patches':[]}
        identity=self.candidate(value);receipt=self.produce(identity)
        self.assertEqual(receipt.prompt_version,'v2');self.assertEqual(receipt.output,value)
        self.assertEqual(self.fixture.row('llm_uses',identity)['validation_status'],'SUCCEEDED')

    def test_actual_v2_inconsistent_card_message_is_failed_not_repaired(self):
        self.v2();cards=cards_fixture();cards['cards'][0]['related_spec_context']=[]
        value={'schema_version':1,'response_type':'INITIALIZE_CARDS','message':'不等价摘要','cards':cards,'confirmed_fact_patches':[]}
        identity=self.candidate(value);self.assertIsNone(self.produce(identity))
        self.assertEqual(json.loads(self.fixture.row('llm_uses',identity)['raw_response_json'])['choices'][0]['message']['content'],json.dumps(value,ensure_ascii=False))
        self.assertIsNone(self.fixture.row('llm_uses',identity)['trusted_output_json'])

    def test_actual_cancel_and_version_change_win_without_trusted_or_reopened_run(self):
        identity=self.candidate();fixture=self.fixture
        result=commands.cancel_guide_run(fixture.executor,{'guide_run_id':fixture.run,'idempotency_key':creation.OTHER},clock=lambda:creation.INSTANT+timedelta(seconds=4))
        self.assertEqual(result['code'],'GUIDE_CANCELLED')
        before=fixture.facts()
        with self.assertRaises(Rejected) as caught:self.produce(identity,seconds=5)
        self.assertEqual(caught.exception.code,'STATE_CONFLICT');self.assertEqual(fixture.facts(),before)

    def test_actual_source_version_mismatch_fails_without_repair_or_trusted_write(self):
        identity=self.candidate();fixture=self.fixture
        with fixture.database.transaction(write=True) as connection:
            connection.execute('UPDATE requirement_documents SET content_version=content_version+1 WHERE id=?',(fixture.created['current_document_id'],))
        before=fixture.facts()
        with self.assertRaises(Rejected) as caught:self.produce(identity)
        self.assertEqual(caught.exception.code,'CONTENT_VERSION_CONFLICT');self.assertEqual(fixture.facts(),before)

    def test_sql_failure_rolls_back_validation_and_run_progress_preserving_occurred_call(self):
        identity=self.candidate();fixture=self.fixture
        with closing(sqlite3.connect(fixture.path)) as connection:
            connection.execute("CREATE TRIGGER receipt_fault AFTER UPDATE ON guide_runs BEGIN SELECT RAISE(ABORT,'private failure'); END");connection.commit()
        before=fixture.facts()
        with self.assertRaises(sqlite3.Error):self.produce(identity)
        self.assertEqual(fixture.facts(),before);self.assertEqual(fixture.row('llm_uses',identity)['call_status'],'SUCCEEDED')

    def test_true_commit_lost_ack_reproves_existing_trusted_without_second_call(self):
        identity=self.candidate();fixture=self.fixture;original=fixture.database.transaction
        @contextmanager
        def lost_ack(*,write=False):
            with original(write=write) as connection:yield connection
            if write:raise CommitOutcomeUnknown('actual commit succeeded, ack missing')
        with fault.object(fixture.database,'transaction',new=lost_ack):
            with self.assertRaises(CommitOutcomeUnknown):self.produce(identity)
        self.assertEqual(fixture.row('llm_uses',identity)['validation_status'],'SUCCEEDED')
        before=fixture.facts();receipt=self.produce(identity,seconds=5)
        self.assertIsInstance(receipt,TrustedOutput);self.assertEqual(fixture.facts(),before)
        with fixture.database.transaction() as connection:self.assertEqual(connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0],1)

    def test_real_competing_validations_reprove_same_committed_receipt(self):
        identity=self.candidate()
        with ThreadPoolExecutor(max_workers=2) as pool:receipts=list(pool.map(lambda _:self.produce(identity),range(2)))
        self.assertEqual(receipts[0],receipts[1]);self.assertEqual(self.fixture.row('llm_uses',identity)['validation_status'],'SUCCEEDED')

    def test_arbitrary_dictionary_or_unsealed_instance_cannot_be_trusted_receipt(self):
        for value in ({'schema_version':1,'response_type':'INITIALIZE_TEXT'},TrustedOutput(),None):
            with self.assertRaises(Rejected):require_receipt(value)

    def test_altered_raw_envelope_after_parser_never_produces_success(self):
        identity=self.candidate();fixture=self.fixture;raw=json.loads(fixture.row('llm_uses',identity)['raw_response_json']);raw['model']='unapproved-model'
        with fixture.database.transaction(write=True) as connection:
            connection.execute('UPDATE llm_uses SET raw_response_json=? WHERE id=?',(json.dumps(raw),identity))
        self.assertIsNone(self.produce(identity));self.assertIsNone(fixture.row('llm_uses',identity)['trusted_output_json'])
