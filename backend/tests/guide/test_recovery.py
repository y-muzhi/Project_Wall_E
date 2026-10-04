"""C09 real file recovery; explicit historical audit/batch fixtures, no model calls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import timedelta
import json
import sqlite3
import unittest
from unittest.mock import patch
from backend.app.documents.commands import start_manual_draft
from backend.app.guide.commands import recover_runs
from backend.app.infrastructure.database import Database, CommitOutcomeUnknown
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.documents.markdown import parse_markdown
from backend.app.requirements.commands import complete_initialization
from backend.app.shared.time import utc_milliseconds
from backend.tests.requirements import test_create_requirement as creation


class RecoveryTests(unittest.TestCase):
    facts=creation.CreateRequirementTests.facts
    payload=creation.CreateRequirementTests.payload
    create=creation.CreateRequirementTests.create

    def setUp(self):
        creation.CreateRequirementTests.setUp(self)
        self.created=self.create()['data']
        self.req=self.created['requirement']['id'];self.run=self.created['guide_run_id']
        self.at=utc_milliseconds(creation.INSTANT)

    def recover(self,reason='STARTUP',live=frozenset(),seconds=900):
        return recover_runs(self.database,{'recovery_reason':reason,'live_run_ids':set(live),'operation_time':utc_milliseconds(creation.INSTANT+timedelta(seconds=seconds))},process_lock=self.lock)

    def row(self,table,identity):
        with self.database.transaction() as connection:
            return dict(connection.execute('SELECT * FROM '+table+' WHERE id=?',(identity,)).fetchone())

    def audit_fixture(self,identity,*,ended=False):
        run=self.row('guide_runs',self.run)
        fields={'id':identity,'guide_run_id':self.run,'call_no':identity,'attempt_no':1,'provider':'diagnostic historical fixture','model_name':'diagnostic-only','model_version':None,
            'function_type':run['function_type'],'prompt_config':run['prompt_version'],
            'request_snapshot_json':json.dumps({'diagnostic_fixture':True,'trigger_message_id':run['trigger_message_id']}),'parsed_output_json':None,'trusted_output_json':None,
            'input_summary':run['instruction_summary'],'context_manifest_json':run['read_scope_manifest_json'],'raw_response_json':None,'finish_reason':None,
            'parse_status':'NOT_STARTED','parse_error':None,'validation_status':'NOT_STARTED','validation_error':None,'call_status':'FAILED' if ended else 'RUNNING',
            'input_tokens':None,'output_tokens':None,'cache_info_json':None,'provider_request_id':None,'started_at':self.at,'ended_at':self.at if ended else None,
            'duration_ms':None,'error_code':'MODEL_ERROR' if ended else None,'error_message':'fixture known failure' if ended else None,'cost':None,'cost_currency':None}
        with self.database.transaction(write=True) as connection:
            connection.execute('INSERT INTO llm_uses('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+')',tuple(fields.values()))

    def terminal(self,status='COMPLETED'):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE guide_runs SET status=?,current_step='FINISHED',ended_at=?,updated_at=?,final_result_json=?,error_code=?,error_message=?,cancel_reason=? WHERE id=?",(status,self.at,self.at,json.dumps({'summary':'explicit historical fixture'}) if status=='COMPLETED' else None,'MODEL_ERROR' if status=='FAILED' else None,'safe fixture failure' if status=='FAILED' else None,'USER_REQUESTED' if status=='CANCELLED' else None,self.run))

    def batch_fixture(self,identity=10,*,parent_id=10,status='PENDING',owned=True):
        # Native initialization is used for the ACTIVE baseline; remaining
        # historical MODIFY/batch rows are explicit complete storage fixtures.
        root=self.row('requirements',self.req)
        if root['status']=='INITIALIZING':
            self.terminal()
            with self.database.transaction(write=True) as connection:
                connection.execute("UPDATE requirements SET document_work_state='IDLE',active_operation_type=NULL,active_operation_id=NULL,state_started_at=NULL WHERE id=?",(self.req,))
            result=complete_initialization(self.executor,{'requirement_id':self.req,'expected_content_version':1,'idempotency_key':creation.OTHER},catalog=self.catalog,clock=lambda:creation.INSTANT)
            self.assertEqual(result['code'],'INITIALIZATION_COMPLETED',result)
        run=self.row('guide_runs',self.run)
        function=self.catalog.freeze('MODIFY','USER_INSTRUCTION')
        run.update(id=parent_id,action_type='MODIFY',function_type=function.function_type,context_template_key='MODIFY_CONTEXT',context_template_version='v1',prompt_version='v1',mode_snapshot=None,
            status='COMPLETED',current_step='FINISHED',ended_at=self.at,final_result_json=json.dumps({'summary':'explicit batch fixture'}),idempotency_key=f'00000000-0000-4000-8000-{parent_id:012d}')
        manifest=json.loads(run['read_scope_manifest_json'])
        manifest.update(function_type=function.function_type,context_template={'key':'MODIFY_CONTEXT','version':'v1'},prompt={'key':'MODIFY_REQUIREMENT','version':'v1'},message_ids=[100+parent_id])
        run.update(trigger_message_id=100+parent_id,instruction_summary='explicit historical modification instruction',read_scope_manifest_json=json.dumps(manifest))
        original=parse_markdown(self.row('requirement_documents',self.created['current_document_id'])['markdown_content']).blocks[0].markdown
        with self.database.transaction(write=True) as connection:
            MessageRepository(connection).create_user_text(100+parent_id,self.req,parent_id,run['instruction_summary'],run['idempotency_key'],self.at)
            connection.execute('INSERT INTO guide_runs('+','.join(run)+') VALUES ('+','.join('?' for _ in run)+')',tuple(run.values()))
            connection.execute("INSERT INTO suggestion_batches VALUES (?, ?, ?, 'USER_INSTRUCTION', NULL, 'fixture batch', 'fixture summary', ?, NULL, NULL, 1, NULL, ?, ?, ?)",(identity,self.req,parent_id,status,self.at,self.at if status=='DISCARDED' else None,self.at))
            connection.execute("INSERT INTO suggestions(id,batch_id,order_no,title,explanation,impact,patch_operation,target_ref_json,selector_json,proposed_markdown,proposed_data_json,original_content,status,user_edited_content,validation_status,validation_error,created_at,updated_at,decided_at) VALUES (?,?,1,'fixture suggestion','fixture explanation',NULL,'REPLACE_BLOCK','{\"block_id\":1}',NULL,'# replacement',NULL,?,'PENDING',NULL,'VALID',NULL,?,?,NULL)",(identity,identity,original,self.at,self.at))
            if owned:
                connection.execute("UPDATE requirements SET document_work_state='GUIDE_ACTIVE',active_operation_type='GUIDE_RUN',active_operation_id=?,state_started_at=? WHERE id=?",(parent_id,self.at,self.req))
        return parent_id

    def test_startup_fails_unowned_running_and_only_unfinished_attempt_with_no_provider(self):
        self.audit_fixture(1);self.audit_fixture(2,ended=True)
        closed=self.row('llm_uses',2);current=self.row('requirement_documents',self.created['current_document_id'])
        with patch('socket.socket.connect',side_effect=AssertionError('Recovery must never call Provider')):
            result=self.recover()
        self.assertEqual(result['code'],'RECOVERED',result)
        self.assertEqual(result['data'],{'recovery_reason':'STARTUP','operation_time':utc_milliseconds(creation.INSTANT+timedelta(minutes=15)),'recovered_run_ids':[self.run],'repaired_requirement_ids':[self.req],'unchanged_requirement_ids':[]})
        run=self.row('guide_runs',self.run);self.assertEqual((run['status'],run['current_step'],run['error_code']),('FAILED','FINISHED','INTERRUPTED'))
        attempt=self.row('llm_uses',1);self.assertEqual((attempt['call_status'],attempt['error_code'],attempt['input_tokens'],attempt['output_tokens'],attempt['duration_ms']),('FAILED','INTERRUPTED',None,None,None))
        self.assertEqual(self.row('llm_uses',2),closed);self.assertEqual(self.row('requirement_documents',self.created['current_document_id']),current)
        before=self.facts();again=self.recover(seconds=1800);self.assertEqual(again['code'],'RECOVERY_NO_CHANGE');self.assertEqual(self.facts(),before)

    def test_no_progress_boundary_899_vs_900_seconds_includes_live_hung_run(self):
        before=self.facts();self.assertEqual(self.recover('NO_PROGRESS',{self.run},899)['code'],'RECOVERY_NO_CHANGE');self.assertEqual(self.facts(),before)
        result=self.recover('NO_PROGRESS',{self.run},900);self.assertEqual(result['code'],'RECOVERED',result)
        self.assertEqual(self.row('guide_runs',self.run)['error_code'],'EXECUTION_TIMEOUT')

    def test_startup_preserves_actual_live_run_even_when_old(self):
        before=self.facts();result=self.recover(live={self.run},seconds=7200)
        self.assertEqual(result['code'],'RECOVERY_NO_CHANGE',result);self.assertEqual(self.facts(),before)

    def test_waiting_user_and_manual_draft_preserved_indefinitely(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE guide_runs SET status='WAITING_USER',current_step='WAITING_USER',waiting_user_at=? WHERE id=?",(self.at,self.run))
        before=self.facts()
        for reason in ('STARTUP','NO_PROGRESS'):
            self.assertEqual(self.recover(reason,seconds=86400)['code'],'RECOVERY_NO_CHANGE');self.assertEqual(self.facts(),before)
        self.terminal();self.recover(seconds=0)
        started=start_manual_draft(self.executor,{'requirement_id':self.req,'expected_content_version':1,'idempotency_key':creation.OTHER},catalog=self.catalog,clock=lambda:creation.INSTANT)
        self.assertEqual(started['code'],'DRAFT_STARTED',started);before=self.facts()
        self.assertEqual(self.recover(seconds=86400)['code'],'RECOVERY_NO_CHANGE');self.assertEqual(self.facts(),before)

    def test_terminal_run_without_pending_batch_releases_for_all_terminal_states(self):
        for status in ('COMPLETED','FAILED','CANCELLED'):
            self.terminal(status)
            with self.database.transaction(write=True) as connection:
                connection.execute("UPDATE requirements SET document_work_state='GUIDE_ACTIVE',active_operation_type='GUIDE_RUN',active_operation_id=?,state_started_at=? WHERE id=?",(self.run,self.at,self.req))
            result=self.recover();self.assertEqual(result['code'],'RECOVERED',result)
            self.assertEqual(self.row('guide_runs',self.run)['status'],status);self.assertEqual(self.row('requirements',self.req)['document_work_state'],'IDLE')

    def test_unique_trusted_modify_batch_switches_and_pending_is_then_unchanged(self):
        self.batch_fixture();before=self.row('suggestion_batches',10)
        result=self.recover();self.assertEqual(result['code'],'RECOVERED',result)
        root=self.row('requirements',self.req);self.assertEqual((root['document_work_state'],root['active_operation_type'],root['active_operation_id'],root['state_started_at']),('SUGGESTION_REVIEWING','SUGGESTION_BATCH',10,self.at))
        self.assertEqual(self.row('suggestion_batches',10),before)
        facts=self.facts();self.assertEqual(self.recover('NO_PROGRESS',seconds=86400)['code'],'RECOVERY_NO_CHANGE');self.assertEqual(self.facts(),facts)

    def test_terminal_batch_pointer_clears_without_rewriting_batch(self):
        self.batch_fixture(status='DISCARDED')
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET document_work_state='SUGGESTION_REVIEWING',active_operation_type='SUGGESTION_BATCH',active_operation_id=10 WHERE id=?",(self.req,))
        before=self.row('suggestion_batches',10);result=self.recover();self.assertEqual(result['code'],'RECOVERED',result);self.assertEqual(self.row('suggestion_batches',10),before)

    def test_missing_cross_requirement_multiple_candidates_and_empty_batch_are_not_guessed(self):
        before=self.facts()
        with self.database.transaction(write=True) as connection: connection.execute('UPDATE requirements SET active_operation_id=999')
        damaged=self.facts();self.assertEqual(self.recover()['code'],'WORK_STATE_INCONSISTENT');self.assertEqual(self.facts(),damaged)
        with self.database.transaction(write=True) as connection: connection.execute('UPDATE requirements SET active_operation_id=?',(self.run,))
        self.assertEqual(self.facts(),before)
        other=self.create(idempotency_key=creation.OTHER)['data']
        with self.database.transaction(write=True) as connection: connection.execute('UPDATE requirements SET active_operation_id=? WHERE id=?',(other['guide_run_id'],self.req))
        before=self.facts();self.assertEqual(self.recover()['code'],'WORK_STATE_INCONSISTENT');self.assertEqual(self.facts(),before)

    def test_multiple_pending_or_unowned_parent_or_empty_candidates_preserve_all(self):
        self.batch_fixture()
        with self.database.transaction(write=True) as connection: connection.execute('DELETE FROM suggestions WHERE batch_id=10')
        before=self.facts();self.assertEqual(self.recover()['code'],'WORK_STATE_INCONSISTENT');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE suggestion_batches SET status='DISCARDED',completed_at=? WHERE id=10",(self.at,))
        self.batch_fixture(11,parent_id=11)
        self.batch_fixture(12,parent_id=12,owned=False)
        before=self.facts();self.assertEqual(self.recover()['code'],'WORK_STATE_INCONSISTENT');self.assertEqual(self.facts(),before)

    def test_each_real_failure_and_result_conversion_rolls_back_entire_recovery(self):
        self.audit_fixture(1)
        for table in ('guide_runs','llm_uses','requirements'):
            with self.subTest(table=table):
                with closing(sqlite3.connect(self.path)) as connection:
                    connection.execute(f"CREATE TRIGGER recovery_fault AFTER UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'actual recovery failure'); END");connection.commit()
                before=self.facts();self.assertEqual(self.recover()['code'],'STORAGE_UNAVAILABLE');self.assertEqual(self.facts(),before)
                with closing(sqlite3.connect(self.path)) as connection: connection.execute('DROP TRIGGER recovery_fault');connection.commit()
        before=self.facts()
        with patch('backend.app.guide.commands.recover_runs_result',side_effect=ValueError('after all actual recovery writes')):
            self.assertEqual(self.recover()['code'],'INTERNAL_ERROR')
        self.assertEqual(self.facts(),before)

    def test_requires_owned_same_database_os_lock_and_strict_internal_input(self):
        payload={'recovery_reason':'STARTUP','live_run_ids':set(),'operation_time':self.at};before=self.facts()
        for changes in ({'recovery_reason':'UNKNOWN'},{'live_run_ids':[]},{'live_run_ids':{True}},{'operation_time':'2026-02-30T00:00:00.000Z'},{'extra':1}):
            self.assertEqual(recover_runs(self.database,{**payload,**changes},process_lock=self.lock)['code'],'INVALID_INPUT');self.assertEqual(self.facts(),before)
        other=ProcessLock.for_database(self.path.with_name('other.sqlite')).acquire()
        try:
            self.assertEqual(recover_runs(self.database,payload,process_lock=other)['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)
        finally: other.release()
        unowned=ProcessLock.for_database(self.path)
        self.assertEqual(recover_runs(self.database,payload,process_lock=unowned)['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)

    def test_real_commit_unknown_can_be_observed_and_not_applied_twice(self):
        class LostAck(Database):
            @contextmanager
            def transaction(database,*,write=False):
                with super().transaction(write=write) as connection: yield connection
                if write: raise CommitOutcomeUnknown('after actual recovery commit')
        result=recover_runs(LostAck(self.path),{'recovery_reason':'STARTUP','live_run_ids':set(),'operation_time':self.at},process_lock=self.lock)
        self.assertEqual(result['code'],'STORAGE_UNAVAILABLE');before=self.facts();self.assertEqual(self.recover()['code'],'RECOVERY_NO_CHANGE');self.assertEqual(self.facts(),before)

    def test_real_competing_recovery_updates_each_run_only_once(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=[future.result()['code'] for future in (pool.submit(self.recover),pool.submit(self.recover))]
        self.assertCountEqual(results,['RECOVERED','RECOVERY_NO_CHANGE'])

    def test_recovery_clock_and_unfinished_attempt_future_time_abort_without_partial_failure(self):
        before=self.facts();self.assertEqual(self.recover(seconds=-1)['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)
        self.audit_fixture(1)
        with self.database.transaction(write=True) as connection:
            connection.execute('UPDATE llm_uses SET started_at=? WHERE id=1',(utc_milliseconds(creation.INSTANT+timedelta(hours=1)),))
        before=self.facts();self.assertEqual(self.recover()['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)

    def test_multi_requirement_recovery_leaves_other_waiting_run_and_occupancy_exactly_unchanged(self):
        other=self.create(idempotency_key=creation.OTHER)['data']
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE guide_runs SET status='WAITING_USER',current_step='WAITING_USER',waiting_user_at=? WHERE id=?",(self.at,other['guide_run_id']))
        other_run=self.row('guide_runs',other['guide_run_id']);other_root=self.row('requirements',other['requirement']['id'])
        result=self.recover();self.assertEqual(result['code'],'RECOVERED',result)
        self.assertEqual(result['data']['recovered_run_ids'],[self.run]);self.assertEqual(result['data']['repaired_requirement_ids'],[self.req]);self.assertEqual(result['data']['unchanged_requirement_ids'],[other_root['id']])
        self.assertEqual(self.row('guide_runs',other['guide_run_id']),other_run);self.assertEqual(self.row('requirements',other_root['id']),other_root)


if __name__=='__main__': unittest.main()
