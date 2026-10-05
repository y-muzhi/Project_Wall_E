"""Real SQLite attempt stages; response fixtures are not Provider calls.

Compilation uses an explicitly expanded diagnostic budget. It does not enable
the production Builder or prove tokenizer compatibility/AI business success.
"""
from contextlib import closing, contextmanager
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import json
import sqlite3
import unittest
from unittest.mock import patch

from backend.app.guide.context_builder import build_context, BuiltContext
from backend.app.guide.queries import get_model_context
from backend.app.guide import commands
from backend.app.infrastructure.audit_repository import AuditRepository
from backend.app.infrastructure.audit_data import AuditCapacityExceeded
from backend.app.infrastructure.database import Database, CommitOutcomeUnknown
from backend.app.infrastructure.model_profile import ModelProfile, MODEL_ID
from backend.app.shared.command_execution import Rejected
from backend.app.shared.validation import MAX_SAFE_INTEGER
from backend.tests.guide import test_recovery as fixtures
from backend.tests.requirements import test_create_requirement as creation

KEY = 'diagnostic-credential-only+/=='
T1 = '2026-10-04T08:00:01.000Z'
T2 = '2026-10-04T08:00:02.000Z'
T3 = '2026-10-04T08:00:03.000Z'


class AuditRepositoryTests(unittest.TestCase):
    facts = fixtures.RecoveryTests.facts
    payload = fixtures.RecoveryTests.payload
    create = fixtures.RecoveryTests.create
    row = fixtures.RecoveryTests.row

    def setUp(self):
        fixtures.RecoveryTests.setUp(self)
        self.function = self.catalog.freeze('INITIALIZE','USER_INSTRUCTION')
        policy = self.function.context_policy
        policy['budget'].update(prompt_tokens=100000,input_tokens=100000,total_tokens=120000)
        diagnostic = replace(self.function,context_json=json.dumps(policy))
        self.context = build_context(get_model_context(self.database,self.run,catalog=self.catalog)['data'],diagnostic)
        self.profile = ModelProfile(KEY)

    def prepare(self, context=None, at=T1, call_no=None):
        self.lock.assert_owned()
        with self.database.transaction(write=True) as connection:
            return dict(AuditRepository(connection).prepare(self.run,self.function,self.profile,context or self.context,at,catalog=self.catalog,call_no=call_no))

    def response(self, content=None, **changes):
        output = {'schema_version':1,'response_type':'INITIALIZE_TEXT','message':'diagnostic response fixture','confirmed_fact_patches':[]}
        return {'model':MODEL_ID,'choices':[{'message':{'role':'assistant','content':json.dumps(output) if content is None else content},'finish_reason':'stop'}],**changes}

    def transport(self, identity, raw=None, *, at=T2, **changes):
        with self.database.transaction(write=True) as connection:
            return dict(AuditRepository(connection).record_transport(identity,self.response() if raw is None else raw,at,profile=self.profile,succeeded=True,finish_reason='stop',**changes))

    def parse(self, identity, at=T3):
        with self.database.transaction(write=True) as connection: return AuditRepository(connection).parse_response(identity,at)

    def test_actual_request_prepared_with_frozen_protocol_owned_run_no_provider_or_other_business_writes(self):
        current = self.row('requirement_documents',self.created['current_document_id']);root = self.row('requirements',self.req);message = self.row('conversation_messages',1)
        with patch('socket.socket.connect',side_effect=AssertionError('No Provider in short transaction')): audit = self.prepare()
        self.assertEqual((audit['call_status'],audit['parse_status'],audit['validation_status'],audit['call_no'],audit['attempt_no']),('RUNNING','NOT_STARTED','NOT_STARTED',1,1))
        request = json.loads(audit['request_snapshot_json'])
        self.assertEqual(request['request'],self.profile.request(self.context));self.assertEqual(request['profile'],self.profile.snapshot)
        self.assertEqual(request['protocol']['prompt'],self.function.prompt_reference);self.assertEqual(audit['prompt_config'],self.function.prompt_reference)
        self.assertEqual(json.loads(audit['context_manifest_json']),self.context.input['read_manifest'])
        self.assertNotIn(KEY,str(audit));self.assertIsNone(audit['trusted_output_json'])
        run = self.row('guide_runs',self.run);self.assertEqual((run['current_step'],run['started_at'],run['updated_at']),('CALLING_MODEL',T1,T1))
        self.assertEqual(self.row('requirements',self.req),root);self.assertEqual(self.row('requirement_documents',current['id']),current);self.assertEqual(self.row('conversation_messages',1),message)
        before = self.facts()
        with self.assertRaises(Rejected):self.prepare(at=T2)
        self.assertEqual(self.facts(),before)

    def test_real_transport_and_single_object_parse_are_distinct_from_schema_and_trusted_business_success(self):
        identity = self.prepare()['id'];row = self.transport(identity,input_tokens=0,output_tokens=12,provider_request_id='opaque/provider:id',duration_ms=44)
        self.assertEqual((row['call_status'],row['parse_status'],row['validation_status']),('SUCCEEDED','NOT_STARTED','NOT_STARTED'))
        parsed = self.parse(identity);self.assertEqual(parsed['response_type'],'INITIALIZE_TEXT')
        row = self.row('llm_uses',identity);self.assertEqual((row['parse_status'],row['validation_status'],row['trusted_output_json']),('SUCCEEDED','NOT_STARTED',None))
        self.assertEqual((row['input_tokens'],row['output_tokens'],row['provider_request_id'],row['duration_ms']),(0,12,'opaque/provider:id',44))
        self.assertEqual((self.row('guide_runs',self.run)['status'],self.row('guide_runs',self.run)['current_step']),('RUNNING','VALIDATING'))

    def test_unknown_fields_survive_actual_parser_return_and_fail_schema_without_audit_scrubbing_becoming_repair(self):
        identity = self.prepare()['id'];value = json.loads(self.response()['choices'][0]['message']['content']);value['reasoning']='unknown model output field'
        self.transport(identity,self.response(content=json.dumps(value)))
        parsed = self.parse(identity);self.assertIn('reasoning',parsed)
        with self.assertRaises(ValueError):self.function.parse_output(json.dumps(parsed))
        # Private audit scrubbing is not the source of business validation.
        self.assertNotIn('reasoning',json.loads(self.row('llm_uses',identity)['parsed_output_json']))
        with self.database.transaction(write=True) as connection: row = AuditRepository(connection).record_validation_failure(identity,T3)
        self.assertEqual((row['call_status'],row['parse_status'],row['validation_status'],row['trusted_output_json']),('SUCCEEDED','SUCCEEDED','FAILED',None))

    def test_fences_multiple_roots_duplicates_wrong_model_tools_refusal_and_length_are_parse_failures_no_repair(self):
        responses = [self.response(content='```json\n{}\n```'),self.response(content='{} {}'),self.response(content='[]'),self.response(content='{"x":1,"x":2}'),self.response(model='other-model'),self.response(content='x'*(1024*1024+1))]
        tools = self.response();tools['choices'][0]['message']['tool_calls']=[{'id':'tool'}];responses.append(tools)
        refusal = self.response();refusal['choices'][0]['message']['refusal']='refused';responses.append(refusal)
        length = self.response();length['choices'][0]['finish_reason']='length';responses.append(length)
        for message in (None,[], 'malformed assistant envelope'):
            malformed = self.response();malformed['choices'][0]['message']=message;responses.append(malformed)
        # Each branch uses its own complete file fixture, not manual resets of
        # a finished audit or a mutable in-memory repository.
        for response in responses:
            fixture = AuditRepositoryTests();fixture.setUp()
            try:
                identity = fixture.prepare()['id'];fixture.transport(identity,response)
                self.assertIsNone(fixture.parse(identity));row = fixture.row('llm_uses',identity)
                self.assertEqual((row['call_status'],row['parse_status'],row['validation_status']),('SUCCEEDED','FAILED','NOT_STARTED'))
                self.assertIsNone(row['trusted_output_json']);self.assertEqual(row['error_code'],'OUTPUT_INVALID')
                self.assertEqual(fixture.row('guide_runs',fixture.run)['status'],'RUNNING')
            finally:fixture.doCleanups()

    def test_retry_attempts_same_call_are_bounded_and_actual_failure_facts_preserved(self):
        first = self.prepare();self.transport(first['id'],self.response(content='invalid JSON'));self.parse(first['id'])
        previous = self.row('llm_uses',first['id'])
        second = self.prepare(at=T3,call_no=1);self.assertEqual((second['call_no'],second['attempt_no']),(1,2));self.assertEqual(self.row('llm_uses',first['id']),previous)
        with self.database.transaction(write=True) as connection:
            AuditRepository(connection).record_transport(second['id'],None,T3,profile=self.profile,succeeded=False)
        third = self.prepare(at=T3,call_no=1);self.assertEqual(third['attempt_no'],3)
        with self.database.transaction(write=True) as connection:
            AuditRepository(connection).record_transport(third['id'],None,T3,profile=self.profile,succeeded=False)
        before = self.facts()
        for call_no in (1,2):
            with self.assertRaises(Rejected):self.prepare(at=T3,call_no=call_no)
            self.assertEqual(self.facts(),before)

    def test_cancelled_attempt_can_record_its_late_transport_usage_without_reopening_run_or_parsing(self):
        identity = self.prepare()['id']
        from datetime import timedelta
        self.assertEqual(commands.cancel_guide_run(self.executor,{'guide_run_id':self.run,'idempotency_key':creation.OTHER},clock=lambda:creation.INSTANT+timedelta(seconds=2))['code'],'GUIDE_CANCELLED')
        run,root = self.row('guide_runs',self.run),self.row('requirements',self.req)
        row = self.transport(identity,at=T3,input_tokens=45,output_tokens=12,provider_request_id='late-actual-fixture-id')
        self.assertEqual(row['call_status'],'CANCELLED');self.assertEqual(row['ended_at'],T2);self.assertEqual(row['input_tokens'],45)
        self.assertEqual(self.row('guide_runs',self.run),run);self.assertEqual(self.row('requirements',self.req),root)
        before = self.facts()
        with self.assertRaises(Rejected):self.parse(identity)
        self.assertEqual(self.facts(),before)

    def test_damaged_context_user_authority_block_content_system_and_manifest_refuse_without_partial_audit(self):
        original = self.context.input
        for changes in ({'user_input':{**original['user_input'],'content':'different instruction'}},
            {'allowed_targets':[]},{'read_manifest':{**original['read_manifest'],'message_ids':[999]}}):
            altered = {**deepcopy(original),**changes};context = replace(self.context,input_json=json.dumps(altered),manifest_json=json.dumps(altered['read_manifest']))
            before = self.facts()
            with self.assertRaises(Rejected):self.prepare(context)
            self.assertEqual(self.facts(),before)
        before = self.facts()
        with self.assertRaises(Rejected):self.prepare(replace(self.context,system='untrusted instructions'))
        self.assertEqual(self.facts(),before)
        original_function = self.function;self.function = replace(self.function,prompt='silently replaced prompt')
        try:
            with self.assertRaises(Rejected):self.prepare()
        finally:self.function = original_function
        self.assertEqual(self.facts(),before)

    def test_real_sql_and_result_conversion_failure_roll_back_audit_id_and_run_progress(self):
        for table in ('llm_uses','guide_runs'):
            with closing(sqlite3.connect(self.path)) as connection:
                connection.execute(f"CREATE TRIGGER audit_fault AFTER {'INSERT' if table=='llm_uses' else 'UPDATE'} ON {table} BEGIN SELECT RAISE(ABORT,'private audit fault'); END");connection.commit()
            before = self.facts()
            with self.assertRaises(sqlite3.IntegrityError):self.prepare()
            self.assertEqual(self.facts(),before)
            with closing(sqlite3.connect(self.path)) as connection:connection.execute('DROP TRIGGER audit_fault');connection.commit()
        before = self.facts();original = AuditRepository.get
        def fail_after_insert(repository,identity):
            row = original(repository,identity)
            if row is not None:raise ValueError('after actual audit insert')
            return row
        with patch.object(AuditRepository,'get',new=fail_after_insert),self.assertRaises(ValueError):self.prepare()
        self.assertEqual(self.facts(),before)

    def test_transport_capacity_invalid_measurements_sensitive_trace_and_sql_failure_roll_back_whole_stage(self):
        identity = self.prepare()['id']
        for changes in ({'input_tokens':-1},{'input_tokens':True},{'provider_request_id':'x'*1025},{'provider_request_id':KEY}):
            before = self.facts()
            with self.assertRaises(ValueError):self.transport(identity,**changes)
            self.assertEqual(self.facts(),before)
        before = self.facts()
        with self.assertRaises(AuditCapacityExceeded):self.transport(identity,{'content':'x'*(4*1024*1024)})
        self.assertEqual(self.facts(),before)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("CREATE TRIGGER transport_fault AFTER UPDATE ON guide_runs BEGIN SELECT RAISE(ABORT,'transport after audit update'); END");connection.commit()
        before = self.facts()
        with self.assertRaises(sqlite3.IntegrityError):self.transport(identity)
        self.assertEqual(self.facts(),before)

    def test_raw_retention_removes_only_old_ended_raw_and_parsed_not_required_request_or_manifest(self):
        identity = self.prepare()['id'];self.transport(identity);self.parse(identity)
        before = self.row('llm_uses',identity)
        with self.database.transaction(write=True) as connection:
            self.assertEqual(AuditRepository(connection).prune_raw('2026-11-03T08:00:02.000Z'),0)
            self.assertEqual(AuditRepository(connection).prune_raw('2026-11-04T08:00:03.000Z'),1)
        after = self.row('llm_uses',identity)
        self.assertEqual(after,{**before,'raw_response_json':None,'parsed_output_json':None})
        with self.database.transaction(write=True) as connection:self.assertEqual(AuditRepository(connection).prune_raw('2026-11-05T08:00:03.000Z'),0)

    def test_real_competing_preparations_commit_one_audit_and_one_run_progress_event(self):
        def competing(_):
            try:return ('PREPARED',self.prepare()['id'])
            except Rejected as error:return (error.code,None)
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(competing,range(2)))
        self.assertEqual(sorted(item[0] for item in results),['PREPARED','STATE_CONFLICT'])
        with self.database.transaction() as connection:self.assertEqual(connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0],1)

    def test_actual_preparation_commit_lost_ack_is_not_a_second_attempt_or_provider_send(self):
        class LostAck(Database):
            @contextmanager
            def transaction(database,*,write=False):
                with super().transaction(write=write) as connection:yield connection
                if write:raise CommitOutcomeUnknown('after actual prepared-request commit')
        original = self.database;self.database = LostAck(self.path)
        try:
            with self.assertRaises(CommitOutcomeUnknown):self.prepare()
        finally:self.database = original
        before = self.facts()
        with self.assertRaises(Rejected):self.prepare(at=T2)
        self.assertEqual(self.facts(),before)
        with self.database.transaction() as connection:
            row = connection.execute('SELECT * FROM llm_uses').fetchone()
            self.assertEqual((row['call_no'],row['attempt_no'],row['call_status'],row['raw_response_json']),(1,1,'RUNNING',None))
        self.assertEqual(commands.recover_runs(self.database,{'recovery_reason':'STARTUP','live_run_ids':set(),'operation_time':T3},process_lock=self.lock)['code'],'RECOVERED')
        self.assertEqual(self.row('guide_runs',self.run)['error_code'],'INTERRUPTED')

    def test_real_parse_and_validation_sql_faults_roll_back_stage_and_progress_then_allow_fact_recheck(self):
        identity = self.prepare()['id'];self.transport(identity)
        for table in ('llm_uses','guide_runs'):
            with closing(sqlite3.connect(self.path)) as connection:
                connection.execute(f"CREATE TRIGGER phase_fault AFTER UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'stage storage failure'); END");connection.commit()
            before = self.facts()
            with self.assertRaises(sqlite3.IntegrityError):self.parse(identity)
            self.assertEqual(self.facts(),before)
            with closing(sqlite3.connect(self.path)) as connection:connection.execute('DROP TRIGGER phase_fault');connection.commit()
        self.assertIsNotNone(self.parse(identity))
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("CREATE TRIGGER validation_fault AFTER UPDATE ON guide_runs BEGIN SELECT RAISE(ABORT,'after validation failure audit'); END");connection.commit()
        before = self.facts()
        with self.assertRaises(sqlite3.IntegrityError):
            with self.database.transaction(write=True) as connection:AuditRepository(connection).record_validation_failure(identity,T3)
        self.assertEqual(self.facts(),before)
