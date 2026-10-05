"""C07 real audit proof -> actual atomic business commits and conflicts.

Response fixtures and expanded budgets are explicit diagnostics, not Provider
compatibility or effects. No SQL fixture manufactures trusted audit success.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing,contextmanager
from copy import deepcopy
from datetime import timedelta
import json
import sqlite3
import unittest
from unittest.mock import patch as fault

from backend.app.guide import commands
from backend.app.guide.queries import get_guide_run,get_model_context
from backend.app.guide.output_evidence import fact_declaration,card_text
from backend.app.documents.patch_validation import validate_patch
from backend.app.documents.scopes import resolve_scope
from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.database import CommitOutcomeUnknown
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.messages.queries import list_messages
from backend.app.requirements.commands import complete_initialization
from backend.app.suggestions.queries import get_batch
from backend.app.comments.commands import create_comment
from backend.app.shared.validation import MAX_SAFE_INTEGER
from backend.tests.guide import test_trusted_output as proof
from backend.tests.requirements import test_create_requirement as creation
from backend.tests.guide import test_acceptance as acceptance
from backend.tests.documents.test_patch_validation import patch
from backend.tests.messages.test_queries import cards_fixture


class ResultPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.helper=proof.TrustedOutputTests();self.helper.setUp();self.addCleanup(self.helper.doCleanups)
        self.fixture=self.helper.fixture

    def prove(self,output=None,base=0):
        identity=self.helper.candidate(output,base=base);receipt=self.helper.produce(identity,seconds=base+4)
        self.assertIsNotNone(receipt);return receipt

    def persist(self,receipt,seconds=5,**changes):
        fixture=self.fixture
        return commands.persist_ai_result(fixture.database,{'guide_run_id':receipt.guide_run_id,'llm_use_id':receipt.llm_use_id,'trusted_output':receipt,**changes},
            process_lock=fixture.lock,profile=fixture.profile,catalog=fixture.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=seconds))

    def accept(self,action='ASK'):
        fixture=self.fixture
        self.assertEqual(commands.cancel_guide_run(fixture.executor,{'guide_run_id':fixture.run,'idempotency_key':creation.OTHER},clock=lambda:creation.INSTANT)['code'],'GUIDE_CANCELLED')
        self.assertEqual(complete_initialization(fixture.executor,{'requirement_id':fixture.req,'expected_content_version':1,'idempotency_key':acceptance.KEY},catalog=fixture.catalog,clock=lambda:creation.INSTANT)['code'],'INITIALIZATION_COMPLETED')
        fixture.catalog=ResourceCatalog()
        result=commands.create_guide_run(fixture.executor,{'requirement_id':fixture.req,'expected_content_version':1,'action_type':action,'instruction':'真实接受指令',
            'scope_type':'DOCUMENT','source_type':'USER_INSTRUCTION','idempotency_key':acceptance.NEXT},catalog=fixture.catalog,clock=lambda:creation.INSTANT)
        self.assertEqual(result['code'],'GUIDE_ACCEPTED',result);fixture.run=result['data']['guide_run']['id'];self.helper.compile()

    def facts_candidate(self):
        fixture=self.fixture
        with fixture.database.transaction() as connection:
            data=get_model_context(fixture.database,fixture.run,catalog=fixture.catalog)['data']
            current=data['current_document'];snapshot=validate_snapshot(current['markdown_content'],current['block_state_json'],DocumentSources(connection,fixture.req,fixture.catalog))
            authority=resolve_scope(snapshot,'INITIALIZE','DOCUMENT');value=patch(snapshot,3,proposed='审批人为部门经理😀。\n')
            declaration=fact_declaration(snapshot,validate_patch(snapshot,value,authority))
        self.helper.v2(declaration)
        user=fixture.context.input['user_input']
        return {'schema_version':1,'response_type':'INITIALIZE_TEXT','message':'按完整确认写入事实','confirmed_fact_patches':[{'patch':value,'evidence':[{'message_id':user['message_id'],'quoted_text':user['content']}]}]}

    def test_initial_text_zero_facts_actual_message_run_effect_and_idle_without_body_version_change(self):
        fixture=self.fixture;current=fixture.row('requirement_documents',fixture.created['current_document_id']);receipt=self.prove()
        result=self.persist(receipt);self.assertEqual(result['code'],'AI_RESULT_PERSISTED',result)
        effects=result['data'];self.assertEqual(effects['current_document'],{'id':current['id'],'content_version':1})
        self.assertIsNone(effects['suggestion_batch_id']);self.assertEqual(effects['status'],'COMPLETED')
        self.assertEqual(fixture.row('requirement_documents',current['id']),current)
        run=fixture.row('guide_runs',fixture.run);self.assertEqual(json.loads(run['final_result_json']),effects)
        self.assertEqual((run['status'],run['current_step'],run['ended_at']),('COMPLETED','FINISHED','2026-10-04T08:00:05.000Z'))
        root=fixture.row('requirements',fixture.req);self.assertEqual((root['document_work_state'],root['active_operation_id']),('IDLE',None))
        self.assertEqual(get_guide_run(fixture.database,fixture.run,catalog=fixture.catalog)['code'],'READ_OK')
        before=fixture.facts();self.assertEqual(self.persist(receipt)['code'],'STATE_CONFLICT');self.assertEqual(fixture.facts(),before)

    def test_real_confirmed_fact_adoption_uses_initializer_source_keeps_creation_and_increments_once(self):
        output=self.facts_candidate();fixture=self.fixture;current=fixture.row('requirement_documents',fixture.created['current_document_id'])
        receipt=self.prove(output);self.assertEqual(self.persist(receipt)['code'],'AI_RESULT_PERSISTED')
        updated=fixture.row('requirement_documents',current['id']);old=json.loads(current['block_state_json']);new=json.loads(updated['block_state_json'])
        self.assertEqual(updated['content_version'],2);self.assertIn('部门经理😀',updated['markdown_content'])
        self.assertEqual(new['next_block_id'],old['next_block_id']);self.assertEqual([x['block_id'] for x in new['blocks']],[x['block_id'] for x in old['blocks']])
        for before,after in zip(old['blocks'],new['blocks']):
            for field in before:
                if field.startswith('created_'):self.assertEqual(after[field],before[field])
        changed=new['blocks'][2];self.assertEqual((changed['last_modified_by_type'],changed['last_modified_source_type'],changed['last_modified_source_id']),('AI','GUIDE_RUN',fixture.run))
        with fixture.database.transaction() as connection:
            validate_snapshot(updated['markdown_content'],new,DocumentSources(connection,fixture.req,fixture.catalog))
            for table in ('suggestion_batches','suggestions','revisions'):
                self.assertEqual(connection.execute('SELECT count(*) FROM '+table).fetchone()[0],0)

    def test_initial_cards_become_real_available_message_and_c06_creates_new_v2_run(self):
        self.helper.v2();cards=cards_fixture();cards['cards'][0]['related_spec_context']=[]
        receipt=self.prove({'schema_version':1,'response_type':'INITIALIZE_CARDS','message':card_text(cards),'cards':cards,'confirmed_fact_patches':[]})
        result=self.persist(receipt);self.assertEqual(result['code'],'AI_RESULT_PERSISTED',result)
        message_id=result['data']['assistant_message_id'];fixture=self.fixture
        messages=list_messages(fixture.database,{'requirement_id':fixture.req},catalog=fixture.catalog)['data']['items']
        self.assertEqual(messages[-1]['id'],message_id);self.assertEqual(messages[-1]['card_state'],'AVAILABLE')
        answer=commands.submit_card_responses(fixture.executor,{'message_id':message_id,'schema_version':1,'responses':[{'card_key':'first','selected_option_keys':['b'],'custom_answer':None,'skipped':False}],'idempotency_key':creation.OTHER},catalog=fixture.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=6))
        self.assertEqual(answer['code'],'CARDS_ACCEPTED',answer)
        new=fixture.row('guide_runs',answer['data']['guide_run']['id']);self.assertNotEqual(new['id'],fixture.run);self.assertEqual(new['prompt_version'],'v2')

    def test_ask_final_and_review_formal_result_complete_readonly(self):
        for action in ('ASK','REVIEW'):
            if action == 'REVIEW':
                self.fixture.doCleanups();self.helper.setUp();self.addCleanup(self.helper.doCleanups);self.fixture=self.helper.fixture
            self.accept(action);fixture=self.fixture;before=fixture.row('requirement_documents',fixture.created['current_document_id'])
            output={'schema_version':1,'response_type':'ANSWER' if action=='ASK' else 'REVIEW_RESULT','message':'正式诊断输出'}
            if action=='REVIEW':output['review_result']={'schema_version':1,'summary':'正式检查结果','issues':[]}
            result=self.persist(self.prove(output));self.assertEqual(result['code'],'AI_RESULT_PERSISTED',result)
            self.assertIsNone(result['data']['current_document']);self.assertEqual(fixture.row('requirement_documents',before['id']),before)
            if action=='REVIEW':self.assertEqual(json.loads(fixture.row('guide_runs',fixture.run)['final_result_json'])['review_result'],output['review_result'])
            self.assertEqual(get_guide_run(fixture.database,fixture.run,catalog=fixture.catalog)['code'],'READ_OK')

    def test_ask_clarify_text_waits_and_actual_c02_continues_same_frozen_run(self):
        self.accept();fixture=self.fixture
        result=self.persist(self.prove({'schema_version':1,'response_type':'CLARIFY_TEXT','message':'请明确边界'}));self.assertEqual(result['code'],'AI_RESULT_PERSISTED',result)
        run=fixture.row('guide_runs',fixture.run);self.assertEqual((run['status'],run['current_step'],run['final_result_json'],run['ended_at']),('WAITING_USER','WAITING_USER',None,None))
        self.assertEqual(fixture.row('requirements',fixture.req)['active_operation_id'],fixture.run)
        resumed=commands.continue_guide_run(fixture.executor,{'guide_run_id':fixture.run,'instruction':'明确了边界','idempotency_key':creation.KEY},catalog=fixture.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=6))
        self.assertEqual(resumed['code'],'GUIDE_CONTINUED',resumed);self.assertEqual(resumed['data']['id'],fixture.run)

    def test_real_clarify_cards_waiting_and_formal_c06_continues_original_run(self):
        self.accept();fixture=self.fixture;cards=cards_fixture();cards['cards'][0]['related_spec_context']=[]
        result=self.persist(self.prove({'schema_version':1,'response_type':'CLARIFY_CARDS','message':card_text(cards),'cards':cards}))
        self.assertEqual(result['code'],'AI_RESULT_PERSISTED',result)
        answer=commands.submit_card_responses(fixture.executor,{'message_id':result['data']['assistant_message_id'],'schema_version':1,
            'responses':[{'card_key':'first','selected_option_keys':['b'],'custom_answer':None,'skipped':False}],'idempotency_key':creation.KEY},
            catalog=fixture.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=6))
        self.assertEqual(answer['code'],'CARDS_ACCEPTED',answer);self.assertEqual(answer['data']['guide_run']['id'],fixture.run)
        self.assertEqual(get_model_context(fixture.database,fixture.run,catalog=fixture.catalog)['code'],'READ_OK')

    def test_modify_no_change_completes_without_empty_batch_or_current_mutation(self):
        self.accept('MODIFY');fixture=self.fixture;before=fixture.row('requirement_documents',fixture.created['current_document_id'])
        result=self.persist(self.prove({'schema_version':1,'response_type':'NO_CHANGE','message':'未形成修改建议'}))
        self.assertEqual(result['code'],'AI_RESULT_PERSISTED',result);self.assertIsNone(result['data']['suggestion_batch_id'])
        self.assertEqual(fixture.row('requirement_documents',before['id']),before)
        self.assertEqual(fixture.row('requirements',fixture.req)['document_work_state'],'IDLE')
        with fixture.database.transaction() as connection:self.assertEqual(connection.execute('SELECT count(*) FROM suggestion_batches').fetchone()[0],0)

    def test_actual_comment_source_suggestion_keeps_comment_open_and_current_unchanged(self):
        fixture=self.fixture
        self.assertEqual(commands.cancel_guide_run(fixture.executor,{'guide_run_id':fixture.run,'idempotency_key':creation.OTHER},clock=lambda:creation.INSTANT)['code'],'GUIDE_CANCELLED')
        self.assertEqual(complete_initialization(fixture.executor,{'requirement_id':fixture.req,'expected_content_version':1,'idempotency_key':acceptance.KEY},catalog=fixture.catalog,clock=lambda:creation.INSTANT)['code'],'INITIALIZATION_COMPLETED')
        fixture.catalog=ResourceCatalog()
        created=create_comment(fixture.executor,{'requirement_id':fixture.req,'expected_content_version':1,'content':'请说明审批人','anchor_type':'BLOCK','block_id':3,'idempotency_key':acceptance.NEXT},catalog=fixture.catalog,clock=lambda:creation.INSTANT)
        self.assertEqual(created['code'],'COMMENT_CREATED',created);comment=created['data']
        accepted=commands.modify_from_comment(fixture.executor,{'comment_id':comment['id'],'expected_content_version':1,'idempotency_key':creation.KEY},catalog=fixture.catalog,clock=lambda:creation.INSTANT)
        self.assertEqual(accepted['code'],'GUIDE_ACCEPTED',accepted);fixture.run=accepted['data']['id'];self.helper.compile()
        current=fixture.row('requirement_documents',fixture.created['current_document_id'])
        with fixture.database.transaction() as connection:snapshot=validate_snapshot(current['markdown_content'],json.loads(current['block_state_json']),DocumentSources(connection,fixture.req,fixture.catalog))
        result=self.persist(self.prove({'schema_version':1,'response_type':'SUGGESTIONS','message':'评论范围建议','title':'审批说明','summary':'明确审批','suggestions':[patch(snapshot,3)]}))
        self.assertEqual(result['code'],'AI_RESULT_PERSISTED',result)
        batch=get_batch(fixture.database,result['data']['suggestion_batch_id'],catalog=fixture.catalog)['data']
        self.assertEqual((batch['source_type'],batch['source_id']),('COMMENT',comment['id']))
        self.assertEqual(fixture.row('comments',comment['id'])['status'],'OPEN');self.assertEqual(fixture.row('requirement_documents',current['id']),current)

    def test_actual_completed_review_is_formal_source_for_new_current_modify_run_and_batch(self):
        self.accept('REVIEW');fixture=self.fixture;review_id=fixture.run
        review={'schema_version':1,'summary':'实际正式诊断检查','issues':[]}
        self.assertEqual(self.persist(self.prove({'schema_version':1,'response_type':'REVIEW_RESULT','message':'检查完成','review_result':review}))['code'],'AI_RESULT_PERSISTED')
        accepted=commands.create_guide_run(fixture.executor,{'requirement_id':fixture.req,'expected_content_version':1,'action_type':'MODIFY','instruction':'按检查提出建议',
            'scope_type':'DOCUMENT','source_type':'REVIEW_RESULT','source_id':review_id,'idempotency_key':creation.KEY},catalog=fixture.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=6))
        self.assertEqual(accepted['code'],'GUIDE_ACCEPTED',accepted);fixture.run=accepted['data']['guide_run']['id'];self.helper.compile()
        self.assertEqual(fixture.function.function_type,'MODIFY_FROM_REVIEW')
        self.assertEqual(fixture.context.input['source']['review_result'],review)
        current=fixture.row('requirement_documents',fixture.created['current_document_id'])
        with fixture.database.transaction() as connection:snapshot=validate_snapshot(current['markdown_content'],json.loads(current['block_state_json']),DocumentSources(connection,fixture.req,fixture.catalog))
        receipt=self.prove({'schema_version':1,'response_type':'SUGGESTIONS','message':'根据正式检查提出建议','title':'检查建议','summary':'摘要','suggestions':[patch(snapshot,3)]},base=6)
        result=self.persist(receipt,seconds=11);self.assertEqual(result['code'],'AI_RESULT_PERSISTED',result)
        batch=get_batch(fixture.database,result['data']['suggestion_batch_id'],catalog=fixture.catalog)['data']
        self.assertEqual((batch['source_type'],batch['source_id']),('REVIEW_RESULT',review_id))
        self.assertEqual(fixture.row('requirement_documents',current['id']),current)

    def test_review_duplicate_foreign_or_invented_evidence_records_failure_never_trusted(self):
        self.accept('REVIEW');fixture=self.fixture
        issue={'issue_key':'approval','severity':'WARNING','category':'AMBIGUOUS','title':'审批人','description':'说明缺失','block_ids':[3],'evidence':'待确认。','recommendation':'请补充'}
        values=[]
        values.append([issue,deepcopy(issue)])
        wrong=deepcopy(issue);wrong['block_ids']=[999];values.append([wrong])
        wrong=deepcopy(issue);wrong['evidence']='原文不存在的证据';values.append([wrong])
        for index,issues in enumerate(values):
            identity=self.helper.candidate({'schema_version':1,'response_type':'REVIEW_RESULT','message':'待验证检查','review_result':{'schema_version':1,'summary':'摘要','issues':issues}},base=index*4,call_no=None if index==0 else 1)
            self.assertIsNone(self.helper.produce(identity,seconds=index*4+4))
            self.assertEqual(fixture.row('llm_uses',identity)['validation_status'],'FAILED');self.assertIsNone(fixture.row('llm_uses',identity)['trusted_output_json'])
        self.assertEqual(fixture.row('guide_runs',fixture.run)['status'],'RUNNING')

    def test_review_literal_evidence_can_span_adjacent_cited_blocks_without_concatenating_unread_blocks(self):
        self.accept('REVIEW');fixture=self.fixture;current=fixture.row('requirement_documents',fixture.created['current_document_id'])
        with fixture.database.transaction() as connection:snapshot=validate_snapshot(current['markdown_content'],json.loads(current['block_state_json']),DocumentSources(connection,fixture.req,fixture.catalog))
        evidence=snapshot.parsed.markdown[snapshot.by_id[3][0].start_offset:snapshot.by_id[4][0].end_offset]
        issue={'issue_key':'span','severity':'INFO','category':'AMBIGUOUS','title':'相邻原文','description':'实际逐字检查','block_ids':[3,4],'evidence':evidence,'recommendation':''}
        output={'schema_version':1,'response_type':'REVIEW_RESULT','message':'检查完成','review_result':{'schema_version':1,'summary':'摘要','issues':[issue]}}
        result=self.persist(self.prove(output));self.assertEqual(result['code'],'AI_RESULT_PERSISTED',result)
        self.assertEqual(json.loads(fixture.row('guide_runs',fixture.run)['final_result_json'])['review_result'],output['review_result'])

    def test_modify_suggestions_persist_all_pending_with_server_identity_and_no_current_write(self):
        self.accept('MODIFY');fixture=self.fixture;current=fixture.row('requirement_documents',fixture.created['current_document_id'])
        with fixture.database.transaction() as connection:
            snapshot=validate_snapshot(current['markdown_content'],json.loads(current['block_state_json']),DocumentSources(connection,fixture.req,fixture.catalog))
        suggestions=[patch(snapshot,3,proposed='新事实一'),patch(snapshot,5,proposed='新事实二')]
        result=self.persist(self.prove({'schema_version':1,'response_type':'SUGGESTIONS','message':'提出两条建议','title':'改进需求','summary':'摘要','suggestions':suggestions}))
        self.assertEqual(result['code'],'AI_RESULT_PERSISTED',result);identity=result['data']['suggestion_batch_id']
        value=get_batch(fixture.database,identity,catalog=fixture.catalog);self.assertEqual(value['code'],'READ_OK',value)
        self.assertEqual(value['data']['status'],'PENDING');self.assertEqual([item['order_no'] for item in value['data']['suggestions']],[1,2])
        self.assertTrue(all(item['status']=='PENDING' and item['decided_at'] is None and item['user_edited_content'] is None for item in value['data']['suggestions']))
        self.assertEqual(fixture.row('requirement_documents',current['id']),current)
        root=fixture.row('requirements',fixture.req);self.assertEqual((root['document_work_state'],root['active_operation_type'],root['active_operation_id']),('SUGGESTION_REVIEWING','SUGGESTION_BATCH',identity))
        self.assertEqual(get_guide_run(fixture.database,fixture.run,catalog=fixture.catalog)['code'],'READ_OK')

    def test_batch_and_message_faults_roll_back_all_business_but_keep_valid_call_audit(self):
        self.accept('MODIFY');fixture=self.fixture;current=fixture.row('requirement_documents',fixture.created['current_document_id'])
        with fixture.database.transaction() as connection:snapshot=validate_snapshot(current['markdown_content'],json.loads(current['block_state_json']),DocumentSources(connection,fixture.req,fixture.catalog))
        receipt=self.prove({'schema_version':1,'response_type':'SUGGESTIONS','message':'待实际提交','title':'建议','summary':'摘要','suggestions':[patch(snapshot,3),patch(snapshot,5)]})
        for table,kind in (('suggestion_batches','INSERT'),('suggestions','INSERT'),('conversation_messages','INSERT'),('guide_runs','UPDATE'),('requirements','UPDATE')):
            with closing(sqlite3.connect(fixture.path)) as connection:
                connection.execute(f"CREATE TRIGGER c07_fault AFTER {kind} ON {table} BEGIN SELECT RAISE(ABORT,'private SQL fault'); END");connection.commit()
            before=fixture.facts();self.assertEqual(self.persist(receipt)['code'],'STORAGE_UNAVAILABLE');self.assertEqual(fixture.facts(),before)
            self.assertEqual(fixture.row('llm_uses',receipt.llm_use_id)['validation_status'],'SUCCEEDED')
            with closing(sqlite3.connect(fixture.path)) as connection:connection.execute('DROP TRIGGER c07_fault');connection.commit()
        self.assertEqual(self.persist(receipt)['code'],'AI_RESULT_PERSISTED')

    def test_fact_comment_revalidation_and_result_conversion_fault_roll_back_current_message_and_run(self):
        receipt=self.prove(self.facts_candidate());fixture=self.fixture
        for target in ('backend.app.guide.result_persistence.revalidate_anchors','backend.app.guide.result_persistence.persist_ai_result_result'):
            before=fixture.facts()
            with fault(target,side_effect=ValueError('actual late failure')):self.assertEqual(self.persist(receipt)['code'],'INTERNAL_ERROR')
            self.assertEqual(fixture.facts(),before)
        self.assertEqual(self.persist(receipt)['code'],'AI_RESULT_PERSISTED')

    def test_actual_cancel_races_c07_and_exactly_one_terminal_business_outcome_wins(self):
        receipt=self.prove();fixture=self.fixture
        def cancel():return commands.cancel_guide_run(fixture.executor,{'guide_run_id':fixture.run,'idempotency_key':creation.OTHER},clock=lambda:creation.INSTANT+timedelta(seconds=5))
        with ThreadPoolExecutor(max_workers=2) as pool:
            submitted=pool.submit(self.persist,receipt);cancelled=pool.submit(cancel);result,stop=submitted.result(),cancelled.result()
        run=fixture.row('guide_runs',fixture.run)
        if run['status']=='COMPLETED':self.assertEqual((result['code'],stop['code']),('AI_RESULT_PERSISTED','STATE_CONFLICT'))
        else:self.assertEqual(run['status'],'CANCELLED');self.assertEqual((result['code'],stop['code']),('STATE_CONFLICT','GUIDE_CANCELLED'))
        with fixture.database.transaction() as connection:
            count=connection.execute("SELECT count(*) FROM conversation_messages WHERE role='ASSISTANT'").fetchone()[0]
            self.assertEqual(count,int(run['status']=='COMPLETED'))
        self.assertEqual(fixture.row('llm_uses',receipt.llm_use_id)['validation_status'],'SUCCEEDED')

    def test_capacity_exhaustion_and_wrong_receipt_binding_no_partial_write_or_phase_change(self):
        receipt=self.prove();fixture=self.fixture;before=fixture.facts()
        self.assertEqual(self.persist(receipt,guide_run_id=999)['code'],'OUTPUT_INVALID');self.assertEqual(fixture.facts(),before)
        self.assertEqual(self.persist(receipt,trusted_output=receipt.output)['code'],'OUTPUT_INVALID');self.assertEqual(fixture.facts(),before)
        with fixture.database.transaction(write=True) as connection:
            connection.execute("UPDATE sequences SET last_value=? WHERE entity_kind='ConversationMessage'",(MAX_SAFE_INTEGER,))
        before=fixture.facts();self.assertEqual(self.persist(receipt)['code'],'CAPACITY_EXHAUSTED');self.assertEqual(fixture.facts(),before)
        self.assertEqual(fixture.row('guide_runs',fixture.run)['current_step'],'VALIDATING')

    def test_true_final_commit_lost_ack_keeps_complete_effect_then_duplicate_is_terminal_conflict(self):
        receipt=self.prove();fixture=self.fixture;original=fixture.database.transaction
        @contextmanager
        def lost_ack(*,write=False):
            with original(write=write) as connection:yield connection
            if write:raise CommitOutcomeUnknown('real complete commit, no delivery ack')
        with fault.object(fixture.database,'transaction',new=lost_ack):self.assertEqual(self.persist(receipt)['code'],'STORAGE_UNAVAILABLE')
        self.assertEqual(get_guide_run(fixture.database,fixture.run,catalog=fixture.catalog)['data']['status'],'COMPLETED')
        before=fixture.facts();self.assertEqual(self.persist(receipt)['code'],'STATE_CONFLICT');self.assertEqual(fixture.facts(),before)
