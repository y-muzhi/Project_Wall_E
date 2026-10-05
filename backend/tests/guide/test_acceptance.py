"""C01/C02 actual SQLite acceptance; waiting/review results are labelled fixtures."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import timedelta
import json
import sqlite3
import unittest
from unittest.mock import patch
from backend.app.guide import commands
from backend.app.guide.queries import get_guide_run
from backend.app.messages.queries import list_messages
from backend.app.requirements.commands import complete_initialization, complete_requirement
from backend.app.infrastructure.database import Database, CommitOutcomeUnknown
from backend.app.infrastructure.idempotency import Idempotency, Scope
from backend.app.infrastructure.resources import ResourceCatalog, ConfigInvalid
from backend.app.shared.validation import MAX_SAFE_INTEGER
from backend.tests.requirements import test_create_requirement as creation
from backend.tests.guide import test_recovery as recovery
from backend.tests.guide import test_queries as history

KEY='00000000-0000-4000-8000-00000000000c'
NEXT='00000000-0000-4000-8000-00000000000d'
NOW=creation.INSTANT+timedelta(seconds=10)


class AcceptanceTests(unittest.TestCase):
    facts=recovery.RecoveryTests.facts
    payload=recovery.RecoveryTests.payload
    create=recovery.RecoveryTests.create
    row=recovery.RecoveryTests.row
    protocol_run_fixture=history.GuideQueryTests.protocol_run_fixture
    completed_fixture=history.GuideQueryTests.completed_fixture

    def setUp(self):
        recovery.RecoveryTests.setUp(self)
        self.assertEqual(commands.cancel_guide_run(self.executor,{'guide_run_id':self.run,'idempotency_key':creation.OTHER},clock=lambda:creation.INSTANT+timedelta(seconds=1))['code'],'GUIDE_CANCELLED')

    def activate(self):
        result=complete_initialization(self.executor,{'requirement_id':self.req,'expected_content_version':1,'idempotency_key':KEY},catalog=self.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=2))
        self.assertEqual(result['code'],'INITIALIZATION_COMPLETED',result)

    def guide_payload(self,**changes):
        return {'requirement_id':self.req,'expected_content_version':1,'action_type':'INITIALIZE','instruction':'\u3000first\r\nsecond\t','scope_type':'DOCUMENT','source_type':'USER_INSTRUCTION','idempotency_key':KEY,**changes}

    def accept(self,**changes):
        return commands.create_guide_run(self.executor,self.guide_payload(**changes),catalog=self.catalog,clock=lambda:NOW)

    def waiting(self,action='ASK'):
        self.activate();result=self.accept(action_type=action);self.assertEqual(result['code'],'GUIDE_ACCEPTED',result)
        self.wait_run=result['data']['guide_run']['id']
        # Explicit waiting-state fixture until C07/model production is connected.
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE guide_runs SET status='WAITING_USER',current_step='WAITING_USER',waiting_user_at=updated_at WHERE id=?",(self.wait_run,))
        return self.wait_run

    def resume(self,**changes):
        return commands.continue_guide_run(self.executor,{'guide_run_id':self.wait_run,'instruction':'\t more\r\ntext\u3000','idempotency_key':NEXT,**changes},catalog=self.catalog,clock=lambda:NOW+timedelta(seconds=1))

    def test_initialization_real_text_run_frozen_protocol_occupancy_and_current_unchanged(self):
        current=self.row('requirement_documents',self.created['current_document_id'])
        with patch('socket.socket.connect',side_effect=AssertionError('No Provider in acceptance transaction')): result=self.accept()
        self.assertEqual(result['code'],'GUIDE_ACCEPTED',result)
        run=self.row('guide_runs',result['data']['guide_run']['id']);message=self.row('conversation_messages',run['trigger_message_id']);root=self.row('requirements',self.req)
        self.assertEqual((run['status'],run['current_step'],run['started_at'],run['mode_snapshot']),('RUNNING','PREPARING',None,'DESIGN'))
        self.assertEqual((message['content'],message['guide_run_id'],message['sequence_no']),('first\nsecond',run['id'],2))
        self.assertEqual((root['document_work_state'],root['active_operation_type'],root['active_operation_id'],root['state_started_at']),('GUIDE_ACTIVE','GUIDE_RUN',run['id'],run['created_at']))
        manifest=json.loads(run['read_scope_manifest_json']);self.catalog.freeze('INITIALIZE','USER_INSTRUCTION').validate_read_manifest(manifest)
        self.assertEqual(manifest['message_ids'],[message['id']]);self.assertNotIn('requirement_id',manifest)
        self.assertEqual(get_guide_run(self.database,run['id'])['code'],'READ_OK')
        self.assertEqual(list_messages(self.database,{'requirement_id':self.req})['data']['items'][-1],result['data']['user_message'])
        self.assertEqual(self.row('requirement_documents',current['id']),current)
        with self.database.transaction() as connection: self.assertEqual(connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0],0)

    def test_active_readonly_action_has_empty_write_permissions_with_server_scope(self):
        self.activate()
        result=self.accept(action_type='REVIEW',scope_type='SECTION',scope_ref={'block_id':1})
        self.assertEqual(result['code'],'GUIDE_ACCEPTED',result)
        run=self.row('guide_runs',result['data']['guide_run']['id'])
        self.assertEqual((run['function_type'],run['mode_snapshot']),('REVIEW_REQUIREMENT',None))
        self.assertEqual(json.loads(run['allowed_targets_json']),{'schema_version':1,'targets':[]})
        self.assertEqual(json.loads(run['scope_ref_json']),{'block_id':1})

    def test_completed_allows_only_ask_and_keeps_completed_time(self):
        self.activate();result=complete_requirement(self.executor,{'requirement_id':self.req,'expected_content_version':1,'idempotency_key':KEY},clock=lambda:creation.INSTANT+timedelta(seconds=3))
        self.assertEqual(result['code'],'REQUIREMENT_COMPLETED');before=self.facts()
        for action in ('INITIALIZE','REVIEW','MODIFY'):
            self.assertEqual(self.accept(action_type=action)['code'],'STATE_CONFLICT');self.assertEqual(self.facts(),before)
        completed=self.row('requirements',self.req)['completed_at']
        self.assertEqual(self.accept(action_type='ASK')['code'],'GUIDE_ACCEPTED')
        self.assertEqual(self.row('requirements',self.req)['completed_at'],completed)

    def test_normalized_replay_is_frozen_after_cancel_and_missing_configuration(self):
        original=self.accept();identity=original['data']['guide_run']['id']
        self.assertEqual(commands.cancel_guide_run(self.executor,{'guide_run_id':identity,'idempotency_key':NEXT},clock=lambda:NOW+timedelta(seconds=1))['code'],'GUIDE_CANCELLED')
        before=self.facts()
        with patch('backend.app.guide.commands.ResourceCatalog',side_effect=ConfigInvalid('missing frozen files')):
            self.assertEqual(commands.create_guide_run(self.executor,self.guide_payload(instruction='first\nsecond',scope_ref=None,source_id=None),clock=lambda:NOW),original)
        self.assertEqual(self.facts(),before)
        self.assertEqual(self.accept(instruction='different')['code'],'IDEMPOTENCY_CONFLICT');self.assertEqual(self.facts(),before)

    def test_invalid_nested_fields_unicode_source_and_scope_have_no_writes(self):
        before=self.facts()
        inputs=[{'requirement_id':True},{'instruction':'\ud800'},{'instruction':'  '},{'scope_type':'BLOCK'},{'scope_type':'BLOCK','scope_ref':{'block_id':1,'write':True}},
            {'scope_type':'DOCUMENT','scope_ref':{}},{'source_type':'COMMENT','source_id':1},{'source_type':'REVIEW_RESULT'},{'source_id':1},{'scope_type':'SELECTION','scope_ref':{'block_id':1,'selected_text':'a','prefix_text':'','suffix_text':'','offset':1}}]
        for change in inputs:
            self.assertEqual(self.accept(**change)['code'],'INVALID_INPUT',change);self.assertEqual(self.facts(),before)
        self.assertEqual(self.accept(source_type='REVIEW_RESULT',source_id=self.run)['code'],'SOURCE_INVALID');self.assertEqual(self.facts(),before)
        self.assertEqual(self.accept(scope_type='BLOCK',scope_ref={'block_id':999})['code'],'SCOPE_INVALID');self.assertEqual(self.facts(),before)
        self.assertEqual(self.accept(expected_content_version=2)['code'],'CONTENT_VERSION_CONFLICT');self.assertEqual(self.facts(),before)
        self.assertEqual(self.accept(requirement_id=999)['code'],'NOT_FOUND');self.assertEqual(self.facts(),before)

    def test_formal_review_source_is_same_requirement_and_new_current_manifest(self):
        self.activate();self.protocol_run_fixture(10,action='REVIEW')
        effects=self.completed_fixture(10,document=False)
        effects['review_result']={'schema_version':1,'summary':'formal historical review fixture','issues':[]}
        with self.database.transaction(write=True) as connection:
            connection.execute('UPDATE guide_runs SET final_result_json=?,cancel_reason=NULL WHERE id=10',(json.dumps(effects),))
        self.assertEqual(get_guide_run(self.database,10)['code'],'READ_OK')
        result=self.accept(action_type='MODIFY',source_type='REVIEW_RESULT',source_id=10)
        self.assertEqual(result['code'],'GUIDE_ACCEPTED',result)
        run=self.row('guide_runs',result['data']['guide_run']['id']);manifest=json.loads(run['read_scope_manifest_json'])
        self.assertEqual((run['function_type'],run['source_id']),('MODIFY_FROM_REVIEW',10));self.assertEqual(manifest['source'],{'source_type':'REVIEW_RESULT','source_id':10})
        self.assertEqual((manifest['document_id'],manifest['content_version']),(self.created['current_document_id'],1))

    def test_review_without_formal_result_and_foreign_source_reject(self):
        self.activate();self.protocol_run_fixture(10,action='REVIEW');self.completed_fixture(10,document=False)
        before=self.facts();self.assertEqual(self.accept(action_type='MODIFY',source_type='REVIEW_RESULT',source_id=10)['code'],'SOURCE_INVALID');self.assertEqual(self.facts(),before)
        other=self.create(idempotency_key=NEXT)['data'];before=self.facts()
        self.assertEqual(self.accept(action_type='MODIFY',source_type='REVIEW_RESULT',source_id=other['guide_run_id'])['code'],'SOURCE_INVALID');self.assertEqual(self.facts(),before)

    def test_acceptance_sql_faults_and_result_conversion_roll_back_all_entities_and_ids(self):
        for table,kind,predicate in (('conversation_messages','INSERT',''),('guide_runs','INSERT',''),('requirements','UPDATE',''),('idempotency_records','UPDATE',"WHEN NEW.status='SUCCEEDED'")):
            with self.subTest(table=table):
                with closing(sqlite3.connect(self.path)) as connection:
                    connection.execute(f"CREATE TRIGGER acceptance_fault AFTER {kind} ON {table} {predicate} BEGIN SELECT RAISE(ABORT,'private fault'); END");connection.commit()
                before=self.facts();self.assertEqual(self.accept()['code'],'STORAGE_UNAVAILABLE');self.assertEqual(self.facts(),before)
                with closing(sqlite3.connect(self.path)) as connection: connection.execute('DROP TRIGGER acceptance_fault');connection.commit()
        before=self.facts()
        with patch('backend.app.guide.commands.create_guide_run_result',side_effect=ValueError('after actual writes')): self.assertEqual(self.accept()['code'],'INTERNAL_ERROR')
        self.assertEqual(self.facts(),before)

    def test_real_competing_acceptances_and_capacity_exhaustion(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE sequences SET last_value=? WHERE entity_kind='GuideRun'",(MAX_SAFE_INTEGER,))
        before=self.facts();self.assertEqual(self.accept()['code'],'CAPACITY_EXHAUSTED');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE sequences SET last_value=? WHERE entity_kind='GuideRun'",(self.run,))
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda key:self.accept(idempotency_key=key),(KEY,NEXT)))
        self.assertEqual(sorted(item['code'] for item in results),['GUIDE_ACCEPTED','WORK_STATE_CONFLICT'])
        with self.database.transaction() as connection: self.assertEqual(connection.execute("SELECT count(*) FROM guide_runs WHERE status='RUNNING'").fetchone()[0],1)

    def test_processing_and_true_commit_lost_ack_preserve_frozen_result(self):
        request=commands.create_guide_run_input(self.guide_payload());claim=self.executor.claim(Scope('APP-GUIDE-CMD-C01',f'Requirement:{self.req}',KEY),request.business_input())
        before=self.facts();self.assertEqual(self.accept()['code'],'REQUEST_IN_PROGRESS');self.assertEqual(self.facts(),before);self.executor.abandon(claim)
        class LostAck(Database):
            writes=0
            @contextmanager
            def transaction(database,*,write=False):
                with super().transaction(write=write) as connection: yield connection
                if write:
                    database.writes+=1
                    if database.writes==2: raise CommitOutcomeUnknown('after actual acceptance commit')
        executor=Idempotency(LostAck(self.path),self.lock,clock=lambda:creation.INSTANT)
        self.assertEqual(commands.create_guide_run(executor,self.guide_payload(),catalog=self.catalog,clock=lambda:NOW)['code'],'STORAGE_UNAVAILABLE')
        before=self.facts();self.assertEqual(self.accept()['code'],'GUIDE_ACCEPTED');self.assertEqual(self.facts(),before)

    def test_continue_same_run_preserves_frozen_protocol_wait_time_and_audit_call_numbers(self):
        self.waiting();old=self.row('guide_runs',self.wait_run);root=self.row('requirements',self.req)
        result=self.resume();self.assertEqual(result['code'],'GUIDE_CONTINUED',result)
        run=self.row('guide_runs',self.wait_run);message=self.row('conversation_messages',run['trigger_message_id'])
        expected={**old,'trigger_message_id':message['id'],'trigger_type':'CONTINUE_GUIDE_RUN','instruction_summary':'more\ntext','status':'RUNNING','current_step':'PREPARING','updated_at':message['created_at']}
        self.assertEqual(run,expected);self.assertEqual(self.row('requirements',self.req),root)
        self.assertEqual((message['message_type'],message['structured_content_json'],message['reply_to_message_id']),('TEXT',None,None))
        before=self.facts();self.assertEqual(self.resume(instruction='more\ntext'),result);self.assertEqual(self.facts(),before)
        self.assertEqual(self.resume(idempotency_key=creation.OTHER)['code'],'STATE_CONFLICT');self.assertEqual(self.facts(),before)
        with self.database.transaction() as connection: self.assertEqual(connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0],0)

    def test_continue_all_actions_but_never_initialize_or_missing_and_wrong_owner(self):
        before=self.facts();self.wait_run=self.run
        self.assertEqual(self.resume()['code'],'STATE_CONFLICT');self.assertEqual(self.facts(),before)
        self.assertEqual(self.resume(guide_run_id=999)['code'],'NOT_FOUND');self.assertEqual(self.facts(),before)
        self.waiting('MODIFY');root=self.row('requirements',self.req)
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE requirements SET document_work_state='IDLE',active_operation_type=NULL,active_operation_id=NULL,state_started_at=NULL WHERE id=?",(self.req,))
        before=self.facts();self.assertEqual(self.resume()['code'],'WORK_STATE_INCONSISTENT');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE requirements SET document_work_state='GUIDE_ACTIVE',active_operation_type='GUIDE_RUN',active_operation_id=?,state_started_at=? WHERE id=?",(self.wait_run,root['state_started_at'],self.req))
        self.assertEqual(self.resume()['code'],'GUIDE_CONTINUED')

    def test_continuation_sql_faults_conversion_and_configuration_roll_back_user_and_run(self):
        self.waiting('REVIEW')
        for table,kind,predicate in (('conversation_messages','INSERT',''),('guide_runs','UPDATE',''),('idempotency_records','UPDATE',"WHEN NEW.status='SUCCEEDED'")):
            with closing(sqlite3.connect(self.path)) as connection:
                connection.execute(f"CREATE TRIGGER continue_fault AFTER {kind} ON {table} {predicate} BEGIN SELECT RAISE(ABORT,'private fault'); END");connection.commit()
            before=self.facts();self.assertEqual(self.resume()['code'],'STORAGE_UNAVAILABLE');self.assertEqual(self.facts(),before)
            with closing(sqlite3.connect(self.path)) as connection: connection.execute('DROP TRIGGER continue_fault');connection.commit()
        before=self.facts()
        with patch('backend.app.guide.commands.continue_guide_run_result',side_effect=ValueError('after actual continuation writes')): self.assertEqual(self.resume()['code'],'INTERNAL_ERROR')
        self.assertEqual(self.facts(),before)
        with patch.object(self.catalog,'restore',side_effect=ConfigInvalid('version unavailable')): self.assertEqual(self.resume()['code'],'CONFIG_INVALID')
        self.assertEqual(self.facts(),before)

    def test_actual_competing_continuations_only_one_user_message_and_clock_guard(self):
        self.waiting();before=self.facts()
        self.assertEqual(commands.continue_guide_run(self.executor,{'guide_run_id':self.wait_run,'instruction':'more','idempotency_key':NEXT},catalog=self.catalog,clock=lambda:creation.INSTANT)['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda key:self.resume(idempotency_key=key),(NEXT,creation.OTHER)))
        self.assertEqual(sorted(item['code'] for item in results),['GUIDE_CONTINUED','STATE_CONFLICT'])
        with self.database.transaction() as connection: self.assertEqual(connection.execute('SELECT count(*) FROM conversation_messages WHERE guide_run_id=?',(self.wait_run,)).fetchone()[0],2)

    def test_first_acceptance_configuration_failure_and_current_corruption_do_not_create_claim_or_entities(self):
        before=self.facts()
        with patch.object(self.catalog,'freeze',side_effect=ConfigInvalid('missing resource version')): self.assertEqual(self.accept()['code'],'CONFIG_INVALID')
        self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE requirement_documents SET markdown_content='broken pairing' WHERE id=?",(self.created['current_document_id'],))
        before=self.facts();self.assertEqual(self.accept()['code'],'WORK_STATE_INCONSISTENT');self.assertEqual(self.facts(),before)

    def test_create_busy_and_idle_dangling_activities_are_not_repaired(self):
        from backend.app.documents.commands import start_manual_draft
        self.assertEqual(start_manual_draft(self.executor,{'requirement_id':self.req,'expected_content_version':1,'idempotency_key':KEY},catalog=self.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=2))['code'],'DRAFT_STARTED')
        before=self.facts();self.assertEqual(self.accept()['code'],'WORK_STATE_CONFLICT');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE requirements SET document_work_state='IDLE',active_operation_type=NULL,active_operation_id=NULL,state_started_at=NULL WHERE id=?",(self.req,))
        before=self.facts();self.assertEqual(self.accept()['code'],'WORK_STATE_INCONSISTENT');self.assertEqual(self.facts(),before)

    def test_continuation_invalid_inputs_processing_and_normalized_conflict(self):
        self.waiting();before=self.facts()
        for payload in ({},{'guide_run_id':self.wait_run,'instruction':'x'}, {'guide_run_id':True,'instruction':'x','idempotency_key':NEXT},
            {'guide_run_id':self.wait_run,'instruction':'\ud800','idempotency_key':NEXT},{'guide_run_id':self.wait_run,'instruction':'x','idempotency_key':NEXT,'responses':[]}):
            self.assertEqual(commands.continue_guide_run(self.executor,payload)['code'],'INVALID_INPUT');self.assertEqual(self.facts(),before)
        request=commands.continue_guide_run_input({'guide_run_id':self.wait_run,'instruction':'more\ntext','idempotency_key':NEXT})
        claim=self.executor.claim(Scope('APP-GUIDE-CMD-C02',f'GuideRun:{self.wait_run}',NEXT),request.business_input())
        before=self.facts();self.assertEqual(self.resume()['code'],'REQUEST_IN_PROGRESS');self.assertEqual(self.facts(),before);self.executor.abandon(claim)
        original=self.resume();before=self.facts();self.assertEqual(self.resume(idempotency_key=NEXT.upper()),original);self.assertEqual(self.facts(),before)
        self.assertEqual(self.resume(instruction='different')['code'],'IDEMPOTENCY_CONFLICT');self.assertEqual(self.facts(),before)

    def test_continuation_real_commit_lost_ack_is_replayed_without_another_user_message(self):
        self.waiting()
        class LostAck(Database):
            writes=0
            @contextmanager
            def transaction(database,*,write=False):
                with super().transaction(write=write) as connection: yield connection
                if write:
                    database.writes+=1
                    if database.writes==2: raise CommitOutcomeUnknown('after actual continuation commit')
        executor=Idempotency(LostAck(self.path),self.lock,clock=lambda:creation.INSTANT)
        payload={'guide_run_id':self.wait_run,'instruction':'more\ntext','idempotency_key':NEXT}
        self.assertEqual(commands.continue_guide_run(executor,payload,catalog=self.catalog,clock=lambda:NOW+timedelta(seconds=1))['code'],'STORAGE_UNAVAILABLE')
        before=self.facts();self.assertEqual(self.resume()['code'],'GUIDE_CONTINUED');self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
