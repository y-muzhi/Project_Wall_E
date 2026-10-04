"""C08 failure bookkeeping on actual files, no Provider or synthetic success."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import timedelta
import sqlite3
import unittest
from unittest.mock import patch
from backend.app.guide.commands import fail_guide_run, cancel_guide_run
from backend.app.infrastructure.database import Database, CommitOutcomeUnknown
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.shared.time import utc_milliseconds
from backend.tests.guide import test_recovery as recovery
from backend.tests.guide import test_queries as status_fixtures
from backend.tests.requirements import test_create_requirement as creation


class FailTests(unittest.TestCase):
    facts=recovery.RecoveryTests.facts
    payload=recovery.RecoveryTests.payload
    create=recovery.RecoveryTests.create
    row=recovery.RecoveryTests.row
    audit_fixture=recovery.RecoveryTests.audit_fixture
    terminal=recovery.RecoveryTests.terminal
    protocol_run_fixture=status_fixtures.GuideQueryTests.protocol_run_fixture

    def setUp(self):
        recovery.RecoveryTests.setUp(self)

    def fail(self,**changes):
        return fail_guide_run(self.database,{'guide_run_id':self.run,'error_code':'MODEL_ERROR','safe_message':'模型请求未能完成',**changes},process_lock=self.lock,clock=lambda:creation.INSTANT+timedelta(seconds=1))

    def test_actual_failure_releases_only_owned_run_and_preserves_document_message_and_closed_audit(self):
        self.audit_fixture(1);self.audit_fixture(2,ended=True)
        current=self.row('requirement_documents',self.created['current_document_id']);message=self.row('conversation_messages',1)
        closed=self.row('llm_uses',2);unfinished=self.row('llm_uses',1)
        with patch('socket.socket.connect',side_effect=AssertionError('Failure bookkeeping must not call Provider')): result=self.fail()
        at=creation.INSTANT+timedelta(seconds=1)
        self.assertEqual(result,{'code':'RUN_FAILED','data':{'guide_run_id':self.run,'status':'FAILED','ended_at':utc_milliseconds(at),'occupancy_released':True},'details':None})
        run=self.row('guide_runs',self.run);self.assertEqual((run['current_step'],run['error_code'],run['error_message'],run['final_result_json']),('FINISHED','MODEL_ERROR','模型请求未能完成',None))
        self.assertEqual(self.row('llm_uses',1),{**unfinished,'call_status':'FAILED','ended_at':run['ended_at'],'error_code':'MODEL_ERROR','error_message':'模型请求未能完成'})
        self.assertEqual(self.row('llm_uses',2),closed);self.assertEqual(self.row('requirement_documents',current['id']),current);self.assertEqual(self.row('conversation_messages',1),message)
        self.assertEqual(self.row('requirements',self.req)['document_work_state'],'IDLE')

    def test_repeat_failure_and_all_terminal_states_never_overwrite_original_result(self):
        first=self.fail();before=self.facts();again=self.fail(error_code='OUTPUT_INVALID',safe_message='后到错误')
        self.assertEqual(again['code'],'RUN_FINAL_UNCHANGED');self.assertEqual(again['data'],{**first['data'],'occupancy_released':False});self.assertEqual(self.facts(),before)
        for status in ('COMPLETED','CANCELLED'):
            self.terminal(status);before=self.facts();result=self.fail()
            self.assertEqual(result['code'],'RUN_FINAL_UNCHANGED');self.assertEqual(result['data']['status'],status);self.assertFalse(result['data']['occupancy_released']);self.assertEqual(self.facts(),before)

    def test_committed_waiting_user_result_is_preserved_by_running_only_gate(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE guide_runs SET status='WAITING_USER',current_step='WAITING_USER',waiting_user_at=? WHERE id=?",(self.at,self.run))
        before=self.facts();result=self.fail()
        self.assertEqual(result,{'code':'RUN_FINAL_UNCHANGED','data':{'guide_run_id':self.run,'status':'WAITING_USER','ended_at':None,'occupancy_released':False},'details':None});self.assertEqual(self.facts(),before)

    def test_orphan_running_failure_never_releases_a_different_actual_live_owner(self):
        self.protocol_run_fixture(10,action='ASK')
        root=self.row('requirements',self.req);run=self.row('guide_runs',self.run)
        result=self.fail(guide_run_id=10)
        self.assertEqual(result['code'],'RUN_FAILED',result);self.assertFalse(result['data']['occupancy_released'])
        self.assertEqual(self.row('requirements',self.req),root);self.assertEqual(self.row('guide_runs',self.run),run)

    def test_persisting_running_can_fail_without_committing_any_ai_business_output(self):
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE guide_runs SET current_step='PERSISTING' WHERE id=?",(self.run,))
        current=self.row('requirement_documents',self.created['current_document_id']);result=self.fail(error_code='OUTPUT_INVALID',safe_message='输出无法采用')
        self.assertEqual(result['code'],'RUN_FAILED');self.assertEqual(self.row('requirement_documents',current['id']),current)

    def test_input_unknown_error_unicode_empty_and_lock_ownership_reject_without_writes(self):
        base={'guide_run_id':self.run,'error_code':'MODEL_ERROR','safe_message':'安全摘要'};before=self.facts()
        for payload in ({},{**base,'guide_run_id':True},{**base,'error_code':'RAW_PROVIDER_FAILURE'},{**base,'safe_message':''},{**base,'safe_message':'\ud800'},{**base,'safe_message':None},{**base,'exception':'private exception'}):
            self.assertEqual(fail_guide_run(self.database,payload,process_lock=self.lock)['code'],'INVALID_INPUT');self.assertEqual(self.facts(),before)
        other=ProcessLock.for_database(self.path.with_name('other.sqlite')).acquire()
        try: self.assertEqual(fail_guide_run(self.database,base,process_lock=other)['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)
        finally: other.release()
        self.assertEqual(fail_guide_run(self.database,base,process_lock=ProcessLock.for_database(self.path))['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)
        self.assertEqual(self.fail(guide_run_id=999)['code'],'NOT_FOUND');self.assertEqual(self.facts(),before)

    def test_each_sql_and_result_mapping_failure_rolls_back_run_attempt_and_root(self):
        self.audit_fixture(1)
        for table in ('guide_runs','llm_uses','requirements'):
            with self.subTest(table=table):
                with closing(sqlite3.connect(self.path)) as connection:
                    connection.execute(f"CREATE TRIGGER failure_fault AFTER UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'actual failure persistence error'); END");connection.commit()
                before=self.facts();self.assertEqual(self.fail()['code'],'STORAGE_UNAVAILABLE');self.assertEqual(self.facts(),before)
                with closing(sqlite3.connect(self.path)) as connection: connection.execute('DROP TRIGGER failure_fault');connection.commit()
        before=self.facts()
        with patch('backend.app.guide.commands.fail_guide_run_result',side_effect=ValueError('actual writes precede mapping error')):
            self.assertEqual(self.fail()['code'],'INTERNAL_ERROR')
        self.assertEqual(self.facts(),before)

    def test_actual_commit_lost_ack_is_observable_and_late_failure_is_unchanged(self):
        class LostAck(Database):
            @contextmanager
            def transaction(database,*,write=False):
                with super().transaction(write=write) as connection: yield connection
                if write: raise CommitOutcomeUnknown('after actual failure commit')
        result=fail_guide_run(LostAck(self.path),{'guide_run_id':self.run,'error_code':'MODEL_ERROR','safe_message':'模型请求未能完成'},process_lock=self.lock,clock=lambda:creation.INSTANT+timedelta(seconds=1))
        self.assertEqual(result['code'],'STORAGE_UNAVAILABLE');before=self.facts()
        self.assertEqual(self.fail()['code'],'RUN_FINAL_UNCHANGED');self.assertEqual(self.facts(),before)

    def test_real_competing_cancel_and_failure_have_exactly_one_terminal_winner(self):
        def cancel(): return cancel_guide_run(self.executor,{'guide_run_id':self.run,'idempotency_key':creation.OTHER},clock=lambda:creation.INSTANT+timedelta(seconds=1))
        with ThreadPoolExecutor(max_workers=2) as pool: failed,cancelled=[future.result() for future in (pool.submit(self.fail),pool.submit(cancel))]
        status=self.row('guide_runs',self.run)['status']
        if status=='FAILED': self.assertEqual((failed['code'],cancelled['code']),('RUN_FAILED','STATE_CONFLICT'))
        else: self.assertEqual(status,'CANCELLED');self.assertEqual((failed['code'],cancelled['code']),('RUN_FINAL_UNCHANGED','GUIDE_CANCELLED'))
        self.assertEqual(self.row('requirements',self.req)['document_work_state'],'IDLE')

    def test_owned_root_with_other_live_run_and_future_clock_are_atomic_rejections(self):
        before=self.facts()
        result=fail_guide_run(self.database,{'guide_run_id':self.run,'error_code':'MODEL_ERROR','safe_message':'安全摘要'},process_lock=self.lock,clock=lambda:creation.INSTANT-timedelta(seconds=1))
        self.assertEqual(result['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)
        self.protocol_run_fixture(10,action='ASK');before=self.facts()
        self.assertEqual(self.fail()['code'],'WORK_STATE_INCONSISTENT');self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
