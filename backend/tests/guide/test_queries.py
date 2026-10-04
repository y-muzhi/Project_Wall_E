"""Status reads actual SQLite facts; terminal results are explicit C07 fixtures."""
from contextlib import contextmanager
import json
import unittest
from unittest.mock import patch
from backend.app.documents.commands import start_manual_draft, complete_manual_draft
from backend.app.guide.queries import get_guide_run
from backend.app.guide.commands import recover_runs
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.guide_repository import GuideRepository
from backend.app.infrastructure.identifiers import message_sequence
from backend.app.infrastructure.message_repository import MessageRepository
from backend.tests.requirements import test_create_requirement as creation
from backend.tests.guide import test_recovery as recovery


class GuideQueryTests(unittest.TestCase):
    facts=creation.CreateRequirementTests.facts
    payload=creation.CreateRequirementTests.payload
    create=creation.CreateRequirementTests.create
    row=recovery.RecoveryTests.row
    terminal=recovery.RecoveryTests.terminal
    batch_fixture=recovery.RecoveryTests.batch_fixture

    def setUp(self):
        creation.CreateRequirementTests.setUp(self)
        self.created=self.create()['data'];self.req=self.created['requirement']['id'];self.run=self.created['guide_run_id']
        self.at=self.created['requirement']['created_at']

    def read(self,identity=None):
        return get_guide_run(self.database,self.run if identity is None else identity)

    def completed_fixture(self,identity=None,batch=None,document=True):
        identity=self.run if identity is None else identity
        message_id=1000+identity
        with self.database.transaction(write=True) as connection:
            connection.execute("INSERT INTO conversation_messages VALUES (?,?,?,?,'ASSISTANT','full visible answer is read through message API','TEXT',NULL,NULL,NULL,?)",(message_id,self.req,identity,message_sequence(connection,self.req),self.at))
            effects={'guide_run_id':identity,'status':'COMPLETED','assistant_message_id':message_id,'current_document':{'id':self.created['current_document_id'],'content_version':1} if document else None,'suggestion_batch_id':batch}
            connection.execute("UPDATE guide_runs SET status='COMPLETED',current_step='FINISHED',ended_at=?,final_result_json=? WHERE id=?",(self.at,json.dumps(effects),identity))
        return effects

    def protocol_run_fixture(self, identity, action='REVIEW', source_type='USER_INSTRUCTION', source_id=None):
        # Explicit historical protocol fixture; not a claim that C07/model ran.
        row=self.row('guide_runs',self.run)
        function=self.catalog.freeze(action,source_type)
        context_key,context_version=function.context_template.split('@')
        _,prompt_version=function.prompt_reference.split('@')
        row.update(id=identity,action_type=action,function_type=function.function_type,context_template_key=context_key,context_template_version=context_version,prompt_version=prompt_version,
            mode_snapshot=None,source_type=source_type,source_id=source_id,trigger_message_id=2000+identity,instruction_summary='explicit protocol history fixture',
            idempotency_key=f'00000000-0000-4000-8000-{identity:012d}')
        with self.database.transaction(write=True) as connection:
            MessageRepository(connection).create_user_text(row['trigger_message_id'],self.req,identity,row['instruction_summary'],row['idempotency_key'],self.at)
            connection.execute('INSERT INTO guide_runs('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')',tuple(row.values()))
            for kind,value in (('GuideRun',identity),('ConversationMessage',row['trigger_message_id'])):
                connection.execute('INSERT INTO sequences VALUES (?,?) ON CONFLICT(entity_kind) DO UPDATE SET last_value=max(last_value,excluded.last_value)',(kind,value))

    def test_actual_accepted_running_model_is_complete_without_prompt_audit_or_side_effect(self):
        before=self.facts();result=self.read();self.assertEqual(result['code'],'READ_OK',result)
        data=result['data'];self.assertEqual((data['id'],data['requirement_id'],data['status'],data['current_step']),(self.run,self.req,'RUNNING','PREPARING'))
        for field in ('final_result','suggestion_batch_id','latest_assistant_message_id','started_at','ended_at','error_code','error_message'):
            self.assertIsNone(data[field])
        self.assertEqual(data['scope'],{'scope_type':'DOCUMENT','scope_ref':None});self.assertEqual(self.facts(),before)
        for hidden in ('idempotency_key','prompt_version','prompt','read_scope_manifest_json','allowed_targets_json','llm_uses','instruction_summary'):
            self.assertNotIn(hidden,data)
        trace=[];original=self.database.transaction
        @contextmanager
        def traced(*,write=False):
            with original(write=write) as connection:
                connection.set_trace_callback(trace.append);yield connection
        with patch.object(self.database,'transaction',new=traced): self.assertEqual(self.read()['code'],'READ_OK')
        queries='\n'.join(trace).lower();self.assertNotIn('llm_uses',queries);self.assertNotIn('prompt_version',queries)

    def test_completed_summary_is_safe_effect_projection_and_preserves_original_written_version(self):
        effects=self.completed_fixture()
        repaired=recover_runs(self.database,{'recovery_reason':'STARTUP','live_run_ids':set(),'operation_time':self.at},process_lock=self.lock)
        self.assertEqual(repaired['code'],'RECOVERED',repaired)
        started=start_manual_draft(self.executor,{'requirement_id':self.req,'expected_content_version':1,'idempotency_key':creation.OTHER},catalog=self.catalog,clock=lambda:creation.INSTANT)
        self.assertEqual(started['code'],'DRAFT_STARTED',started)
        completed=complete_manual_draft(self.executor,{'requirement_id':self.req,'expected_version':1,'idempotency_key':creation.OTHER},catalog=self.catalog,clock=lambda:creation.INSTANT)
        self.assertEqual(completed['code'],'DRAFT_COMPLETED',completed);self.assertEqual(completed['data']['content_version'],2)
        before=self.facts();result=self.read();self.assertEqual(result['code'],'READ_OK',result)
        self.assertEqual(result['data']['final_result'],{'summary':'初始化任务已完成','assistant_message_id':effects['assistant_message_id'],'current_document_version':1,'suggestion_batch_id':None})
        self.assertNotIn('full visible answer',str(result));self.assertEqual(self.facts(),before)

    def test_failed_and_cancelled_are_successful_reads_and_waiting_retains_latest_assistant(self):
        self.completed_fixture()
        for status in ('FAILED','CANCELLED'):
            self.terminal(status);before=self.facts();result=self.read()
            self.assertEqual(result['code'],'READ_OK',result);self.assertEqual(result['data']['status'],status);self.assertIsNone(result['data']['final_result']);self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE guide_runs SET status='WAITING_USER',current_step='WAITING_USER',ended_at=NULL,cancel_reason=NULL,error_code=NULL,error_message=NULL,waiting_user_at=? WHERE id=?",(self.at,self.run))
        result=self.read();self.assertEqual(result['code'],'READ_OK',result);self.assertEqual(result['data']['latest_assistant_message_id'],1000+self.run)

    def test_modify_batch_reference_is_actual_owned_batch_not_guessed_from_current_root(self):
        parent=self.batch_fixture();self.completed_fixture(parent,batch=10,document=False)
        result=self.read(parent);self.assertEqual(result['code'],'READ_OK',result)
        self.assertEqual(result['data']['suggestion_batch_id'],10);self.assertEqual(result['data']['final_result']['current_document_version'],None)
        self.assertEqual(result['data']['final_result']['summary'],'修改建议已生成')

    def test_scope_is_original_reference_even_when_block_no_longer_exists(self):
        for kind,reference in (('SECTION',{'block_id':999}),('BLOCK',{'block_id':998}),('SELECTION',{'block_id':997,'selected_text':'😀','prefix_text':'','suffix_text':''})):
            with self.database.transaction(write=True) as connection:
                connection.execute('UPDATE guide_runs SET scope_type=?,scope_ref_json=? WHERE id=?',(kind,json.dumps(reference),self.run))
            before=self.facts();result=self.read();self.assertEqual(result['code'],'READ_OK',result);self.assertEqual(result['data']['scope'],{'scope_type':kind,'scope_ref':reference});self.assertEqual(self.facts(),before)

    def test_completed_effect_corruption_unknown_fields_duplicate_keys_foreign_ids_reject_safely(self):
        effects=self.completed_fixture()
        variants=[{**effects,'prompt':'private raw prompt'},{**effects,'guide_run_id':True},{**effects,'assistant_message_id':9999},
            {**effects,'current_document':{'id':999,'content_version':1}}, {**effects,'current_document':{'id':self.created['current_document_id'],'content_version':2}},
            {**effects,'suggestion_batch_id':999}]
        texts=[json.dumps(value) for value in variants]+['{"guide_run_id":1,"guide_run_id":2}']
        for text in texts:
            with self.database.transaction(write=True) as connection: connection.execute('UPDATE guide_runs SET final_result_json=? WHERE id=?',(text,self.run))
            before=self.facts();result=self.read();self.assertEqual(result['code'],'INTERNAL_ERROR',result);self.assertIsNone(result['data']);self.assertNotIn('private raw prompt',str(result));self.assertEqual(self.facts(),before)

    def test_scope_and_terminal_error_corruption_are_not_empty_success(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE guide_runs SET scope_type='BLOCK',scope_ref_json='{}' WHERE id=?",(self.run,))
        before=self.facts();self.assertEqual(self.read()['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE guide_runs SET scope_type='DOCUMENT',scope_ref_json=NULL,status='FAILED',current_step='FINISHED',ended_at=?,error_code='RAW_PROVIDER_FAILURE',error_message='private raw exception' WHERE id=?",(self.at,self.run))
        result=self.read();self.assertEqual(result['code'],'INTERNAL_ERROR');self.assertNotIn('private raw exception',str(result))

    def test_not_found_invalid_ids_missing_storage_and_mapping_exception_never_mutate(self):
        before=self.facts()
        for value in (True,0,-1,'1',None):
            self.assertEqual(get_guide_run(self.database,value)['code'],'INVALID_INPUT')
        self.assertEqual(self.read(999)['code'],'NOT_FOUND');self.assertEqual(get_guide_run(self.database)['code'],'INVALID_INPUT')
        missing=Database(self.path.with_name('not-created.sqlite'));self.assertEqual(get_guide_run(missing,1)['code'],'STORAGE_UNAVAILABLE');self.assertFalse(missing.path.exists())
        with patch('backend.app.guide.queries.get_guide_run_result',side_effect=RuntimeError('diagnostic conversion failure')):
            self.assertEqual(self.read()['code'],'INTERNAL_ERROR')
        self.assertEqual(self.facts(),before)

    def test_formal_review_result_is_retained_and_schema_checked_but_never_exposed_as_summary(self):
        self.protocol_run_fixture(10)
        effects=self.completed_fixture(10,document=False)
        review={'schema_version':1,'summary':'full review content retained for later modification','issues':[]}
        effects['review_result']=review
        with self.database.transaction(write=True) as connection:
            connection.execute('UPDATE guide_runs SET final_result_json=? WHERE id=10',(json.dumps(effects),))
        before=self.facts();result=self.read(10);self.assertEqual(result['code'],'READ_OK',result)
        self.assertEqual(result['data']['final_result']['summary'],'检查任务已完成');self.assertNotIn('full review content',str(result));self.assertEqual(self.facts(),before)
        self.assertEqual(json.loads(self.row('guide_runs',10)['final_result_json'])['review_result'],review)
        effects['review_result']={**review,'prompt':'private protocol content'}
        with self.database.transaction(write=True) as connection: connection.execute('UPDATE guide_runs SET final_result_json=? WHERE id=10',(json.dumps(effects),))
        result=self.read(10);self.assertEqual(result['code'],'INTERNAL_ERROR');self.assertNotIn('private protocol content',str(result))

    def test_review_source_requires_same_requirement_completed_review_and_rejects_other_actions(self):
        self.protocol_run_fixture(10)
        self.completed_fixture(10,document=False)
        self.protocol_run_fixture(11,action='MODIFY',source_type='REVIEW_RESULT',source_id=10)
        result=self.read(11);self.assertEqual(result['code'],'READ_OK',result);self.assertEqual(result['data']['source_id'],10)
        with self.database.transaction(write=True) as connection: connection.execute('UPDATE guide_runs SET source_id=? WHERE id=11',(self.run,))
        before=self.facts();self.assertEqual(self.read(11)['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)
        other=self.create(idempotency_key=creation.OTHER)['data']
        with self.database.transaction(write=True) as connection: connection.execute('UPDATE guide_runs SET source_id=? WHERE id=11',(other['guide_run_id'],))
        before=self.facts();self.assertEqual(self.read(11)['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
