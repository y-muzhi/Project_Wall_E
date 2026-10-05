"""C06 real SQLite transactions; card production/waiting are explicit fixtures."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from copy import deepcopy
from datetime import timedelta
import json
import sqlite3
import unittest
from unittest.mock import patch
from backend.app.guide import commands
from backend.app.guide.queries import get_guide_run
from backend.app.documents.commands import start_manual_draft
from backend.app.infrastructure.database import Database, CommitOutcomeUnknown
from backend.app.infrastructure.idempotency import Idempotency, Scope
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.shared.validation import MAX_SAFE_INTEGER
from backend.tests.messages import test_queries as fixtures
from backend.tests.requirements import test_create_requirement as creation

KEY='00000000-0000-4000-8000-00000000000c'
OTHER='00000000-0000-4000-8000-00000000000d'
NOW=creation.INSTANT+timedelta(seconds=10)


class CardSubmissionTests(unittest.TestCase):
    facts=fixtures.MessageQueryTests.facts
    payload=fixtures.MessageQueryTests.payload
    create=fixtures.MessageQueryTests.create
    row=fixtures.MessageQueryTests.row
    read=fixtures.MessageQueryTests.read
    message_fixture=fixtures.MessageQueryTests.message_fixture
    initialize_cards_fixture=fixtures.MessageQueryTests.initialize_cards_fixture
    waiting_cards_fixture=fixtures.MessageQueryTests.waiting_cards_fixture
    text_fixture=fixtures.MessageQueryTests.text_fixture

    def setUp(self): fixtures.MessageQueryTests.setUp(self)

    def answers(self,**changes):
        return {'message_id':11,'schema_version':1,'responses':[{'card_key':'first','selected_option_keys':['b'],'custom_answer':None,'skipped':False}],'idempotency_key':KEY,**changes}

    def submit(self,**changes):
        return commands.submit_card_responses(self.executor,self.answers(**changes),catalog=self.catalog,clock=lambda:NOW)

    def test_initialize_formal_response_new_run_mode_manifest_and_occupancy_atomic_current_unchanged(self):
        self.initialize_cards_fixture();old=self.row('guide_runs',self.run);current=self.row('requirement_documents',self.created['current_document_id'])
        with patch('socket.socket.connect',side_effect=AssertionError('No Provider inside acceptance')): result=self.submit()
        self.assertEqual(result['code'],'CARDS_ACCEPTED',result);data=result['data'];reply=data['response_message'];new_id=data['guide_run']['id']
        self.assertNotEqual(new_id,self.run);self.assertEqual(reply['reply_to_message_id'],11)
        self.assertEqual((reply['role'],reply['message_type'],reply['structured_content'],data['card_state']),('USER','CARD_RESPONSE',{'schema_version':1,'responses':self.answers()['responses']},'ANSWERED'))
        self.assertEqual(reply['content'],'选择方案\nb');self.assertNotIn('a',reply['content']);self.assertIsNone(reply['card_state'])
        run=self.row('guide_runs',new_id);root=self.row('requirements',self.req)
        self.assertEqual((run['trigger_type'],run['trigger_message_id'],run['mode_snapshot'],run['started_at']),('CARD_RESPONSE',reply['id'],'DESIGN',None))
        self.assertEqual((root['active_operation_id'],root['document_work_state']),(new_id,'GUIDE_ACTIVE'))
        self.assertEqual(json.loads(run['read_scope_manifest_json'])['message_ids'],[11,reply['id']])
        self.assertEqual(self.row('guide_runs',self.run),old);self.assertEqual(self.row('requirement_documents',current['id']),current)
        self.assertEqual(self.read()['data']['items'][-2]['card_state'],'ANSWERED');self.assertEqual(get_guide_run(self.database,new_id)['code'],'READ_OK')

    def test_waiting_answer_continues_same_run_frozen_protocol_and_waiting_time(self):
        self.waiting_cards_fixture(root_status='COMPLETED');old=self.row('guide_runs',2);root=self.row('requirements',self.req)
        result=self.submit();self.assertEqual(result['code'],'CARDS_ACCEPTED',result);self.assertEqual(result['data']['guide_run']['id'],2)
        reply=result['data']['response_message'];run=self.row('guide_runs',2)
        self.assertEqual(run,{**old,'trigger_message_id':reply['id'],'trigger_type':'CARD_RESPONSE','instruction_summary':reply['content'],'status':'RUNNING','current_step':'PREPARING','updated_at':reply['created_at']})
        self.assertEqual(self.row('requirements',self.req),root)
        with self.database.transaction() as connection: self.assertEqual(connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0],2)

    def test_whole_group_invalid_selection_required_skip_and_custom_count_reject_all_without_writes(self):
        self.initialize_cards_fixture();before=self.facts()
        variants=[{'card_key':'foreign','selected_option_keys':['b'],'custom_answer':None,'skipped':False},
            {'card_key':'first','selected_option_keys':['foreign'],'custom_answer':None,'skipped':False},
            {'card_key':'first','selected_option_keys':[],'custom_answer':None,'skipped':False},
            {'card_key':'first','selected_option_keys':[],'custom_answer':None,'skipped':True},
            {'card_key':'first','selected_option_keys':['a'],'custom_answer':'extra','skipped':False},
            {'card_key':'first','selected_option_keys':[],'custom_answer':'x'*101,'skipped':False}]
        for answer in variants:
            result=self.submit(responses=[answer]);self.assertEqual(result['code'],'INVALID_INPUT',result);self.assertEqual(set(result['details']),{'field_errors'});self.assertEqual(self.facts(),before)

    def test_multiselect_plus_custom_and_optional_explicit_skip_complete_group_equivalent_summary(self):
        cards=deepcopy(fixtures.cards_fixture());first=cards['cards'][0];first['card_type']='MULTI_SELECT';first['selection_rule']={'min':1,'max':3}
        second=deepcopy(first);second.update(card_key='second',question='可选问题',required=False);cards['cards'].append(second)
        self.initialize_cards_fixture(structured=cards)
        responses=[{'card_key':'first','selected_option_keys':['b','a'],'custom_answer':'\t补充\r\n回答\u3000','skipped':False}, {'card_key':'second','selected_option_keys':[],'custom_answer':None,'skipped':True}]
        result=self.submit(responses=responses);self.assertEqual(result['code'],'CARDS_ACCEPTED',result)
        message=result['data']['response_message'];self.assertEqual(message['content'],'选择方案\nb\na\n补充\n回答\n可选问题\n已跳过')
        self.assertEqual(message['structured_content']['responses'][0]['custom_answer'],'补充\n回答')
        before=self.facts();responses[0]['custom_answer']='补充\n回答';self.assertEqual(self.submit(responses=responses),result);self.assertEqual(self.facts(),before)

    def test_atomic_whole_group_missing_or_extra_or_duplicate_never_partial_answer(self):
        cards=deepcopy(fixtures.cards_fixture());second=deepcopy(cards['cards'][0]);second['card_key']='second';cards['cards'].append(second)
        self.initialize_cards_fixture(structured=cards);before=self.facts()
        self.assertEqual(self.submit()['code'],'INVALID_INPUT');self.assertEqual(self.facts(),before)
        base=self.answers()['responses'][0]
        self.assertEqual(self.submit(responses=[base,base])['code'],'INVALID_INPUT');self.assertEqual(self.facts(),before)
        self.assertEqual(self.submit(responses=[base,{**base,'card_key':'foreign'}])['code'],'INVALID_INPUT');self.assertEqual(self.facts(),before)

    def test_same_key_frozen_replay_and_different_key_existing_response_reference_after_run_failure(self):
        self.initialize_cards_fixture();original=self.submit();run_id=original['data']['guide_run']['id']
        result=commands.fail_guide_run(self.database,{'guide_run_id':run_id,'error_code':'MODEL_ERROR','safe_message':'实际失败收口测试'},process_lock=self.lock,clock=lambda:NOW+timedelta(seconds=1))
        self.assertEqual(result['code'],'RUN_FAILED');before=self.facts()
        self.assertEqual(self.submit(),original);self.assertEqual(self.facts(),before)
        again=self.submit(idempotency_key=OTHER);self.assertEqual(again,{'code':'CARD_ALREADY_ANSWERED','data':None,'details':{'response_message_id':original['data']['response_message']['id']}});self.assertEqual(self.facts(),before)
        self.assertEqual(self.read()['data']['items'][-2]['card_state'],'ANSWERED')

    def test_real_two_key_competition_creates_one_response_and_one_new_run(self):
        self.initialize_cards_fixture()
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda key:self.submit(idempotency_key=key),(KEY,OTHER)))
        self.assertEqual(sorted(result['code'] for result in results),['CARDS_ACCEPTED','CARD_ALREADY_ANSWERED'])
        success=next(result for result in results if result['code']=='CARDS_ACCEPTED');conflict=next(result for result in results if result['code']=='CARD_ALREADY_ANSWERED')
        self.assertEqual(conflict['details']['response_message_id'],success['data']['response_message']['id'])
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM conversation_messages WHERE message_type='CARD_RESPONSE'").fetchone()[0],1)
            self.assertEqual(connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0],2)

    def test_real_sql_faults_and_result_mapping_roll_back_reply_run_root_and_claim(self):
        self.initialize_cards_fixture()
        for table,kind,predicate in (('conversation_messages','INSERT',''),('guide_runs','INSERT',''),('requirements','UPDATE',''),('idempotency_records','UPDATE',"WHEN NEW.status='SUCCEEDED'")):
            with closing(sqlite3.connect(self.path)) as connection:
                connection.execute(f"CREATE TRIGGER cards_fault AFTER {kind} ON {table} {predicate} BEGIN SELECT RAISE(ABORT,'private fault'); END");connection.commit()
            before=self.facts();self.assertEqual(self.submit()['code'],'STORAGE_UNAVAILABLE');self.assertEqual(self.facts(),before)
            with closing(sqlite3.connect(self.path)) as connection: connection.execute('DROP TRIGGER cards_fault');connection.commit()
        before=self.facts()
        with patch('backend.app.guide.commands.submit_card_responses_result',side_effect=ValueError('after actual formal writes')): self.assertEqual(self.submit()['code'],'INTERNAL_ERROR')
        self.assertEqual(self.facts(),before)

    def test_true_commit_lost_ack_replays_without_second_formal_answer(self):
        self.initialize_cards_fixture()
        class LostAck(Database):
            writes=0
            @contextmanager
            def transaction(database,*,write=False):
                with super().transaction(write=write) as connection: yield connection
                if write:
                    database.writes+=1
                    if database.writes==2: raise CommitOutcomeUnknown('after actual formal response commit')
        executor=Idempotency(LostAck(self.path),self.lock,clock=lambda:creation.INSTANT)
        self.assertEqual(commands.submit_card_responses(executor,self.answers(),catalog=self.catalog,clock=lambda:NOW)['code'],'STORAGE_UNAVAILABLE')
        before=self.facts();self.assertEqual(self.submit()['code'],'CARDS_ACCEPTED');self.assertEqual(self.facts(),before)

    def test_expired_due_to_later_plain_user_or_actual_manual_session_has_no_response(self):
        self.initialize_cards_fixture();result=start_manual_draft(self.executor,{'requirement_id':self.req,'expected_content_version':1,'idempotency_key':KEY},catalog=self.catalog,clock=lambda:NOW)
        self.assertEqual(result['code'],'DRAFT_STARTED');before=self.facts();self.assertEqual(self.submit()['code'],'CARD_EXPIRED');self.assertEqual(self.facts(),before)

    def test_waiting_after_ordinary_continuation_is_expired_and_keeps_plain_text_unanswered(self):
        self.waiting_cards_fixture();result=commands.continue_guide_run(self.executor,{'guide_run_id':2,'instruction':'普通文字不是选择','idempotency_key':OTHER},catalog=self.catalog,clock=lambda:NOW)
        self.assertEqual(result['code'],'GUIDE_CONTINUED');before=self.facts();self.assertEqual(self.submit()['code'],'CARD_EXPIRED');self.assertEqual(self.facts(),before)
        self.assertEqual(self.read()['data']['items'][-2]['card_state'],'EXPIRED')

    def test_invalid_input_source_damaged_cards_missing_ids_and_configuration_do_not_write(self):
        self.initialize_cards_fixture();before=self.facts()
        for changes in ({'schema_version':True},{'schema_version':2},{'responses':[]},{'responses':None},{'message_id':True},{'responses':[{'card_key':'first','selected_option_keys':['a'],'custom_answer':'\ud800','skipped':False}]},
            {'responses':[{'card_key':'first','selected_option_keys':['a','a'],'custom_answer':None,'skipped':False}]}, {'responses':[{'card_key':'first','selected_option_keys':['a'],'custom_answer':None,'skipped':False,'write':True}]}):
            self.assertEqual(self.submit(**changes)['code'],'INVALID_INPUT');self.assertEqual(self.facts(),before)
        self.assertEqual(self.submit(message_id=999)['code'],'NOT_FOUND');self.assertEqual(self.facts(),before)
        self.assertEqual(self.submit(message_id=1)['code'],'SOURCE_INVALID');self.assertEqual(self.facts(),before)
        with patch.object(self.catalog,'restore',side_effect=ConfigInvalid('frozen version missing')): self.assertEqual(self.submit()['code'],'CONFIG_INVALID')
        self.assertEqual(self.facts(),before)
        self.message_fixture(12,structured='{"schema_version":1,"private":"broken raw"}')
        before=self.facts();self.assertEqual(self.submit(message_id=12)['code'],'SOURCE_INVALID');self.assertEqual(self.facts(),before)

    def test_processing_scope_changed_answers_and_real_capacity_failures(self):
        self.initialize_cards_fixture();request=commands.submit_card_responses_input(self.answers())
        claim=self.executor.claim(Scope('APP-GUIDE-CMD-C06','Message:11',KEY),request.business_input());before=self.facts()
        self.assertEqual(self.submit()['code'],'REQUEST_IN_PROGRESS');self.assertEqual(self.facts(),before);self.executor.abandon(claim)
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE sequences SET last_value=? WHERE entity_kind='ConversationMessage'",(MAX_SAFE_INTEGER,))
        before=self.facts();self.assertEqual(self.submit()['code'],'CAPACITY_EXHAUSTED');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE sequences SET last_value=11 WHERE entity_kind='ConversationMessage'")
        self.assertEqual(self.submit()['code'],'CARDS_ACCEPTED');before=self.facts()
        changed=[{**self.answers()['responses'][0],'selected_option_keys':['a']}]
        self.assertEqual(self.submit(responses=changed)['code'],'IDEMPOTENCY_CONFLICT');self.assertEqual(self.facts(),before)

    def test_bad_ownership_and_clock_roll_back_without_guessing(self):
        self.initialize_cards_fixture();before=self.facts()
        self.assertEqual(commands.submit_card_responses(self.executor,self.answers(),catalog=self.catalog,clock=lambda:creation.INSTANT-timedelta(seconds=1))['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)
        result=start_manual_draft(self.executor,{'requirement_id':self.req,'expected_content_version':1,'idempotency_key':OTHER},catalog=self.catalog,clock=lambda:NOW)
        self.assertEqual(result['code'],'DRAFT_STARTED')
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE requirements SET document_work_state='IDLE',active_operation_type=NULL,active_operation_id=NULL,state_started_at=NULL WHERE id=?",(self.req,))
        before=self.facts();self.assertEqual(self.submit()['code'],'WORK_STATE_INCONSISTENT');self.assertEqual(self.facts(),before)

    def test_waiting_reply_run_update_failure_rolls_back_formal_answer_and_mapping(self):
        self.waiting_cards_fixture()
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("CREATE TRIGGER waiting_answer_fault AFTER UPDATE ON guide_runs BEGIN SELECT RAISE(ABORT,'private waiting update'); END");connection.commit()
        before=self.facts();self.assertEqual(self.submit()['code'],'STORAGE_UNAVAILABLE');self.assertEqual(self.facts(),before)
        with closing(sqlite3.connect(self.path)) as connection: connection.execute('DROP TRIGGER waiting_answer_fault');connection.commit()
        before=self.facts()
        with patch('backend.app.guide.commands.submit_card_responses_result',side_effect=ValueError('after actual waiting answer writes')): self.assertEqual(self.submit()['code'],'INTERNAL_ERROR')
        self.assertEqual(self.facts(),before)

    def test_real_card_and_plain_continuation_compete_without_both_user_inputs(self):
        self.waiting_cards_fixture()
        def ordinary():
            return commands.continue_guide_run(self.executor,{'guide_run_id':2,'instruction':'普通补充','idempotency_key':OTHER},catalog=self.catalog,clock=lambda:NOW)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(self.submit);second=pool.submit(ordinary);results=(first.result(),second.result())
        self.assertIn(tuple(result['code'] for result in results),(('CARDS_ACCEPTED','STATE_CONFLICT'),('CARD_EXPIRED','GUIDE_CONTINUED')))
        with self.database.transaction() as connection: self.assertEqual(connection.execute('SELECT count(*) FROM conversation_messages WHERE requirement_id=?',(self.req,)).fetchone()[0],4)


if __name__=='__main__': unittest.main()
