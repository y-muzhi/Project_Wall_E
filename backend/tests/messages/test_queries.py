"""I35 same real SQLite snapshot; fixture cards do not represent model output."""
from copy import deepcopy
from datetime import timedelta
import json
import unittest
from unittest.mock import patch
from backend.app.documents.commands import start_manual_draft, cancel_manual_draft
from backend.app.guide.commands import recover_runs
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.infrastructure.database import Database
from backend.app.messages.queries import list_messages
from backend.app.messages.cards import validate_cards, validate_responses, CardsInvalid
from backend.app.infrastructure.resources import ProtocolInvalid
from backend.app.requirements.commands import complete_initialization, complete_requirement
from backend.tests.requirements import test_create_requirement as creation


def cards_fixture():
    option=lambda key:{'option_key':key,'label':key,'description':'description','impact':'impact','risks':''}
    return {'schema_version':1,'intro':'真实可读卡片的历史夹具','cards':[{'card_key':'first','card_type':'SINGLE_SELECT','question':'选择方案','context':'上下文','required':True,'options':[option('a'),option('b')],'selection_rule':{'min':1,'max':1},'custom_answer':{'enabled':True,'max_length':100},'recommendation':{'option_keys':['a'],'reason':'仅供展示'},'related_spec_context':[{'block_id':1,'content_snapshot':'历史快照'}]}]}


class MessageQueryTests(unittest.TestCase):
    facts=creation.CreateRequirementTests.facts
    payload=creation.CreateRequirementTests.payload
    create=creation.CreateRequirementTests.create

    def setUp(self):
        creation.CreateRequirementTests.setUp(self)
        self.created=self.create()['data'];self.req=self.created['requirement']['id'];self.run=self.created['guide_run_id']
        self.at='2026-10-04T08:00:00.000Z'

    def row(self,table,identity):
        with self.database.transaction() as connection: return dict(connection.execute('SELECT * FROM '+table+' WHERE id=?',(identity,)).fetchone())

    def read(self,**changes):
        return list_messages(self.database,{'requirement_id':self.req,**changes},catalog=self.catalog)

    def message_fixture(self,identity,kind='INTERACTION_CARDS',structured=None,run_id=None,reply=None):
        role='USER' if kind=='CARD_RESPONSE' else 'ASSISTANT'
        with self.database.transaction(write=True) as connection:
            sequence=connection.execute('SELECT COALESCE(MAX(sequence_no),0)+1 FROM conversation_messages WHERE requirement_id=?',(self.req,)).fetchone()[0]
            connection.execute('INSERT INTO conversation_messages VALUES (?,?,?,?,?,?,?,?,?,?,?)',(identity,self.req,self.run if run_id is None else run_id,sequence,role,'Readable historical content 😀',kind,json.dumps(cards_fixture() if structured is None else structured,ensure_ascii=False) if type(structured) is not str else structured,reply,f'00000000-0000-4000-8000-{identity:012d}' if role=='USER' else None,self.at))
            connection.execute("INSERT INTO sequences VALUES ('ConversationMessage',?) ON CONFLICT(entity_kind) DO UPDATE SET last_value=max(last_value,excluded.last_value)",(identity,))
        return identity

    def initialize_cards_fixture(self,identity=11,structured=None):
        self.message_fixture(identity,structured=structured)
        final={'guide_run_id':self.run,'status':'COMPLETED','assistant_message_id':identity,'current_document':{'id':self.created['current_document_id'],'content_version':1},'suggestion_batch_id':None}
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE guide_runs SET status='COMPLETED',current_step='FINISHED',final_result_json=?,ended_at=?,updated_at=? WHERE id=?",(json.dumps(final),self.at,self.at,self.run))
        result=recover_runs(self.database,{'recovery_reason':'STARTUP','live_run_ids':set(),'operation_time':self.at},process_lock=self.lock)
        self.assertEqual(result['code'],'RECOVERED',result)

    def text_fixture(self,identity):
        with self.database.transaction(write=True) as connection:
            MessageRepository(connection).create_user_text(identity,self.req,self.run,'historical text '+str(identity),f'00000000-0000-4000-8000-{identity:012d}',self.at)

    def waiting_cards_fixture(self,*,root_status='ACTIVE'):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE guide_runs SET status='COMPLETED',current_step='FINISHED',final_result_json='{}',ended_at=?,updated_at=? WHERE id=?",(self.at,self.at,self.run))
        recover_runs(self.database,{'recovery_reason':'STARTUP','live_run_ids':set(),'operation_time':self.at},process_lock=self.lock)
        result=complete_initialization(self.executor,{'requirement_id':self.req,'expected_content_version':1,'idempotency_key':creation.OTHER},catalog=self.catalog,clock=lambda:creation.INSTANT)
        self.assertEqual(result['code'],'INITIALIZATION_COMPLETED',result)
        if root_status=='COMPLETED':
            result=complete_requirement(self.executor,{'requirement_id':self.req,'expected_content_version':1,'idempotency_key':creation.OTHER},clock=lambda:creation.INSTANT)
            self.assertEqual(result['code'],'REQUIREMENT_COMPLETED',result)
        original=self.row('guide_runs',self.run);function=self.catalog.freeze('ASK','USER_INSTRUCTION');manifest=json.loads(original['read_scope_manifest_json'])
        context_key,context_version=function.context_template.split('@');prompt_key,prompt_version=function.prompt_reference.split('@')
        manifest.update(function_type=function.function_type,context_template={'key':context_key,'version':context_version},prompt={'key':prompt_key,'version':prompt_version},message_ids=[10])
        original.update(id=2,idempotency_key='00000000-0000-4000-8000-000000000002',trigger_message_id=10,action_type='ASK',function_type=function.function_type,context_template_key=context_key,context_template_version=context_version,prompt_version=prompt_version,mode_snapshot=None,status='WAITING_USER',current_step='WAITING_USER',final_result_json=None,ended_at=None,waiting_user_at=self.at,read_scope_manifest_json=json.dumps(manifest),allowed_targets_json='{"schema_version":1,"targets":[]}')
        with self.database.transaction(write=True) as connection:
            MessageRepository(connection).create_user_text(10,self.req,2,'explicit historical ask',original['idempotency_key'],self.at)
            connection.execute('INSERT INTO guide_runs('+','.join(original)+') VALUES ('+','.join('?' for _ in original)+')',tuple(original.values()))
            connection.execute("UPDATE requirements SET document_work_state='GUIDE_ACTIVE',active_operation_type='GUIDE_RUN',active_operation_id=2,state_started_at=? WHERE id=?",(self.at,self.req))
            connection.execute("INSERT INTO sequences VALUES ('GuideRun',2) ON CONFLICT(entity_kind) DO UPDATE SET last_value=max(last_value,excluded.last_value)")
        self.message_fixture(11,run_id=2)

    def test_latest_twenty_exclusive_cursor_ascending_stable_no_total_or_write(self):
        for identity in range(101,145): self.text_fixture(identity)
        before=self.facts();first=self.read();self.assertEqual(first['code'],'READ_OK',first)
        self.assertEqual([item['sequence_no'] for item in first['data']['items']],list(range(26,46)))
        self.assertEqual((first['data']['page_size'],first['data']['has_more'],first['data']['next_cursor']),(20,True,26))
        second=self.read(before_sequence_no=26);self.assertEqual([item['sequence_no'] for item in second['data']['items']],list(range(6,26)))
        last=self.read(before_sequence_no=6);self.assertEqual([item['sequence_no'] for item in last['data']['items']],list(range(1,6)))
        self.assertEqual((last['data']['has_more'],last['data']['next_cursor']),(False,None));self.assertNotIn('total',first['data']);self.assertEqual(self.facts(),before)

    def test_empty_exclusive_window_and_invalid_ids_cursor_missing_root_no_mutations(self):
        before=self.facts();value=self.read(before_sequence_no=1);self.assertEqual(value['data'],{'items':[],'page_size':20,'has_more':False,'next_cursor':None})
        for changes in ({'before_sequence_no':True},{'before_sequence_no':0},{'before_sequence_no':'1'},{'requirement_id':True},{'page':1}): self.assertEqual(self.read(**changes)['code'],'INVALID_INPUT');self.assertEqual(self.facts(),before)
        self.assertEqual(self.read(requirement_id=999)['code'],'NOT_FOUND');self.assertEqual(self.facts(),before)

    def test_initialization_available_temporary_real_manual_edit_cancel_restores_without_time_expiry(self):
        self.initialize_cards_fixture();before=self.facts();value=self.read();self.assertEqual(value['code'],'READ_OK',value)
        self.assertEqual(value['data']['items'][-1]['card_state'],'AVAILABLE');self.assertEqual(self.facts(),before)
        started=start_manual_draft(self.executor,{'requirement_id':self.req,'expected_content_version':1,'idempotency_key':creation.OTHER},catalog=self.catalog,clock=lambda:creation.INSTANT+timedelta(days=20))
        self.assertEqual(started['code'],'DRAFT_STARTED',started);self.assertEqual(self.read()['data']['items'][-1]['card_state'],'EXPIRED')
        cancelled=cancel_manual_draft(self.executor,{'requirement_id':self.req,'expected_version':1,'idempotency_key':creation.OTHER},clock=lambda:creation.INSTANT+timedelta(days=21))
        self.assertEqual(cancelled['code'],'DRAFT_CANCELLED',cancelled);self.assertEqual(self.read()['data']['items'][-1]['card_state'],'AVAILABLE')

    def test_completed_initialization_changed_version_new_input_newer_cards_permanently_expire(self):
        self.initialize_cards_fixture();self.text_fixture(12)
        self.assertEqual(self.read()['data']['items'][-2]['card_state'],'EXPIRED')
        self.message_fixture(13);before=self.facts();value=self.read()
        # Latest card does not match the source run's committed assistant effect.
        self.assertEqual(value['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)

    def test_only_latest_waiting_card_group_is_available_without_skipping_invalid_new_group(self):
        self.waiting_cards_fixture();self.message_fixture(12,run_id=2)
        value=self.read();self.assertEqual(value['code'],'READ_OK',value)
        self.assertEqual([item['card_state'] for item in value['data']['items'] if item['message_type']=='INTERACTION_CARDS'],['EXPIRED','AVAILABLE'])
        self.message_fixture(13,run_id=2,structured={'schema_version':1,'intro':'bad','cards':[]})
        value=self.read();self.assertEqual([item['card_state'] for item in value['data']['items'] if item['message_type']=='INTERACTION_CARDS'],['EXPIRED','EXPIRED',None])

    def test_actual_lifecycle_completion_expires_init_cards_and_body_version_gate(self):
        self.initialize_cards_fixture()
        with self.database.transaction(write=True) as connection: connection.execute('UPDATE requirement_documents SET content_version=2')
        self.assertEqual(self.read()['data']['items'][-1]['card_state'],'EXPIRED')
        result=complete_initialization(self.executor,{'requirement_id':self.req,'expected_content_version':2,'idempotency_key':creation.OTHER},catalog=self.catalog,clock=lambda:creation.INSTANT)
        self.assertEqual(result['code'],'INITIALIZATION_COMPLETED',result);self.assertEqual(self.read()['data']['items'][-1]['card_state'],'EXPIRED')

    def test_waiting_user_available_only_actual_owner_same_document_version_and_new_run_expires(self):
        self.waiting_cards_fixture();value=self.read();self.assertEqual(value['code'],'READ_OK',value);self.assertEqual(value['data']['items'][-1]['card_state'],'AVAILABLE')
        with self.database.transaction(write=True) as connection: connection.execute('UPDATE requirement_documents SET content_version=2')
        self.assertEqual(self.read()['data']['items'][-1]['card_state'],'EXPIRED')

        with self.database.transaction(write=True) as connection: connection.execute('UPDATE requirement_documents SET content_version=1')
        original=self.row('guide_runs',2);original.update(id=3,idempotency_key='00000000-0000-4000-8000-000000000003',status='FAILED',current_step='FINISHED',ended_at=self.at,error_code='MODEL_ERROR',error_message='safe historical error')
        with self.database.transaction(write=True) as connection: connection.execute('INSERT INTO guide_runs('+','.join(original)+') VALUES ('+','.join('?' for _ in original)+')',tuple(original.values()))
        self.assertEqual(self.read()['data']['items'][-1]['card_state'],'EXPIRED')

    def test_completed_requirement_still_allows_current_waiting_ask_card_group(self):
        self.waiting_cards_fixture(root_status='COMPLETED');before=self.facts();value=self.read()
        self.assertEqual(value['code'],'READ_OK',value);self.assertEqual(value['data']['items'][-1]['card_state'],'AVAILABLE')
        self.assertEqual(self.row('requirements',self.req)['status'],'COMPLETED');self.assertEqual(self.facts(),before)

    def test_formal_response_priority_survives_lifecycle_new_input_and_damaged_answer_payload(self):
        self.initialize_cards_fixture();self.message_fixture(12,kind='CARD_RESPONSE',structured={'schema_version':1,'responses':[{'card_key':'first','selected_option_keys':['b'],'custom_answer':None,'skipped':False}]},reply=11)
        self.text_fixture(13);value=self.read();self.assertEqual(value['code'],'READ_OK',value);self.assertEqual(value['data']['items'][1]['card_state'],'ANSWERED')
        self.assertEqual(value['data']['items'][2]['structured_content']['responses'][0]['selected_option_keys'],['b'])
        with self.database.transaction(write=True) as connection: connection.execute('DELETE FROM conversation_messages WHERE id=12')
        self.message_fixture(14,kind='CARD_RESPONSE',structured={'private_bad_answer':'sensitive marker'},reply=11)
        before=self.facts();value=self.read();self.assertEqual(value['data']['items'][1]['card_state'],'ANSWERED');self.assertIsNone(value['data']['items'][-1]['structured_content']);self.assertNotIn('sensitive marker',str(value));self.assertEqual(self.facts(),before)

    def test_invalid_historical_card_schema_duplicate_keys_and_semantics_degrade_content_only(self):
        invalid=cards_fixture();invalid['cards'][0]['recommendation']['option_keys']=['unknown-sensitive']
        self.message_fixture(11,structured=invalid);self.message_fixture(12,structured='{"schema_version":1,"schema_version":2,"private":"sensitive marker"}')
        before=self.facts();value=self.read();self.assertEqual(value['code'],'READ_OK',value)
        for item in value['data']['items'][1:]: self.assertEqual(item['content'],'Readable historical content 😀');self.assertIsNone(item['structured_content']);self.assertIsNone(item['card_state'])
        self.assertNotIn('sensitive marker',str(value));self.assertNotIn('unknown-sensitive',str(value));self.assertEqual(self.facts(),before)

    def test_same_snapshot_window_and_card_state_across_actual_user_writer_commit(self):
        self.initialize_cards_fixture();original=MessageRepository.window
        def after_window(repository,requirement_id,cursor):
            rows=original(repository,requirement_id,cursor);self.text_fixture(12);return rows
        with patch.object(MessageRepository,'window',new=after_window): value=self.read()
        self.assertEqual(value['code'],'READ_OK',value);self.assertEqual(value['data']['items'][-1]['card_state'],'AVAILABLE')
        value=self.read();self.assertEqual(value['data']['items'][-2]['card_state'],'EXPIRED')

    def test_foreign_run_association_and_response_original_ref_are_safe_failure_no_repair(self):
        other=self.create(idempotency_key=creation.OTHER)['data'];self.message_fixture(11,run_id=other['guide_run_id'])
        before=self.facts();self.assertEqual(self.read()['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)

    def test_card_semantic_rules_and_formal_response_whole_group_are_not_schema_only(self):
        protocol=self.catalog.freeze('ASK','USER_INSTRUCTION');cards=cards_fixture();validate_cards(cards,protocol)
        for mutation in ('duplicate_key','bad_rule','bad_custom','bad_recommendation'):
            value=deepcopy(cards)
            if mutation=='duplicate_key': value['cards'].append(deepcopy(value['cards'][0]))
            if mutation=='bad_rule': value['cards'][0]['selection_rule']={'min':2,'max':1}
            if mutation=='bad_custom': value['cards'][0]['custom_answer']={'enabled':False,'max_length':20}
            if mutation=='bad_recommendation': value['cards'][0]['recommendation']['option_keys']=['unknown']
            with self.assertRaises((CardsInvalid,ProtocolInvalid)): validate_cards(value,protocol)
        base={'schema_version':1,'responses':[{'card_key':'first','selected_option_keys':['a'],'custom_answer':None,'skipped':False}]}
        validate_responses(base,cards,protocol)
        for changes in ({'skipped':True},{'selected_option_keys':['unknown']},{'selected_option_keys':['a','a']},{'custom_answer':'custom'},{'selected_option_keys':[],'custom_answer':' '},{'selected_option_keys':[],'custom_answer':None}):
            value=deepcopy(base);value['responses'][0].update(changes)
            with self.assertRaises((CardsInvalid,ProtocolInvalid)): validate_responses(value,cards,protocol)
        custom=deepcopy(base);custom['responses'][0].update(selected_option_keys=[],custom_answer='用户回答');validate_responses(custom,cards,protocol)

    def test_multi_custom_counts_optional_explicit_skip_and_full_group_coverage(self):
        protocol=self.catalog.freeze('ASK','USER_INSTRUCTION');cards=cards_fixture();multi=cards['cards'][0]
        multi.update(card_type='MULTI_SELECT',selection_rule={'min':1,'max':3})
        optional=deepcopy(multi);optional.update(card_key='optional',required=False);cards['cards'].append(optional)
        validate_cards(cards,protocol)
        responses={'schema_version':1,'responses':[{'card_key':'first','selected_option_keys':['a','b'],'custom_answer':'附加回答','skipped':False},{'card_key':'optional','selected_option_keys':[],'custom_answer':None,'skipped':True}]}
        validate_responses(responses,cards,protocol)
        for kind in ('missing','duplicate','unmarked_empty','skipped_with_content'):
            bad=deepcopy(responses)
            if kind=='missing': bad['responses'].pop()
            if kind=='duplicate': bad['responses'][1]=deepcopy(bad['responses'][0])
            if kind=='unmarked_empty': bad['responses'][1]['skipped']=False
            if kind=='skipped_with_content': bad['responses'][1]['custom_answer']='answer'
            with self.assertRaises(CardsInvalid): validate_responses(bad,cards,protocol)

    def test_dangling_actual_manual_activity_rejects_available_claim_without_query_repair(self):
        self.initialize_cards_fixture()
        started=start_manual_draft(self.executor,{'requirement_id':self.req,'expected_content_version':1,'idempotency_key':creation.OTHER},catalog=self.catalog,clock=lambda:creation.INSTANT)
        self.assertEqual(started['code'],'DRAFT_STARTED',started)
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE requirements SET document_work_state='IDLE',active_operation_type=NULL,active_operation_id=NULL,state_started_at=NULL")
        before=self.facts();self.assertEqual(self.read()['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)

    def test_missing_storage_and_result_mapping_failure_are_safe_without_initialization_or_writes(self):
        path=self.path.with_name('missing.sqlite');self.assertEqual(list_messages(Database(path),{'requirement_id':self.req})['code'],'STORAGE_UNAVAILABLE');self.assertFalse(path.exists())
        before=self.facts()
        with patch('backend.app.messages.queries.list_messages_result',side_effect=ValueError('private conversion failure')): self.assertEqual(self.read()['code'],'INTERNAL_ERROR')
        self.assertEqual(self.facts(),before)

    def test_outside_window_formal_reply_foreign_guide_is_not_treated_as_answered(self):
        self.initialize_cards_fixture();other=self.create(idempotency_key=creation.OTHER)['data']
        self.message_fixture(20,kind='CARD_RESPONSE',run_id=other['guide_run_id'],structured={'private_bad_answer':'sensitive marker'},reply=11)
        before=self.facts();value=self.read(before_sequence_no=3)
        self.assertEqual(value['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
