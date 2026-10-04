"""C03 real SQLite cancellation and persistence gate; historical audit fixtures."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import timedelta
import sqlite3
import unittest
from unittest.mock import patch
from backend.app.documents.commands import start_manual_draft
from backend.app.guide.commands import cancel_guide_run
from backend.app.guide.queries import get_guide_run
from backend.app.infrastructure.database import Database, CommitOutcomeUnknown
from backend.app.infrastructure.idempotency import Idempotency, Scope
from backend.app.shared.time import utc_milliseconds
from backend.tests.guide import test_recovery as recovery
from backend.tests.guide import test_queries as status_fixtures
from backend.tests.requirements import test_create_requirement as creation


class CancelTests(unittest.TestCase):
    facts=recovery.RecoveryTests.facts
    payload=recovery.RecoveryTests.payload
    create=recovery.RecoveryTests.create
    row=recovery.RecoveryTests.row
    audit_fixture=recovery.RecoveryTests.audit_fixture
    protocol_run_fixture=status_fixtures.GuideQueryTests.protocol_run_fixture

    def setUp(self):
        recovery.RecoveryTests.setUp(self)

    def cancel(self,**changes):
        return cancel_guide_run(self.executor,{'guide_run_id':self.run,'idempotency_key':creation.OTHER,**changes},clock=lambda:creation.INSTANT+timedelta(seconds=1))

    def test_running_cancels_run_occupancy_and_only_unfinished_attempt_atomically(self):
        self.audit_fixture(1);self.audit_fixture(2,ended=True)
        closed=self.row('llm_uses',2);current=self.row('requirement_documents',self.created['current_document_id'])
        message=self.row('conversation_messages',1);unfinished=self.row('llm_uses',1)
        with patch('socket.socket.connect',side_effect=AssertionError('Cancellation transaction must not call Provider')):
            result=self.cancel()
        self.assertEqual(result,{'code':'GUIDE_CANCELLED','data':{'id':self.run,'requirement_id':self.req,'status':'CANCELLED','current_step':'FINISHED'},'details':None})
        run=self.row('guide_runs',self.run);root=self.row('requirements',self.req)
        self.assertEqual((run['cancel_reason'],run['final_result_json'],run['ended_at']),('USER_REQUESTED',None,utc_milliseconds(creation.INSTANT+timedelta(seconds=1))))
        self.assertEqual((root['document_work_state'],root['active_operation_type'],root['active_operation_id'],root['state_started_at']),('IDLE',None,None,None))
        attempt=self.row('llm_uses',1)
        expected={**unfinished,'call_status':'CANCELLED','ended_at':run['ended_at']};self.assertEqual(attempt,expected)
        self.assertEqual(self.row('llm_uses',2),closed);self.assertEqual(self.row('conversation_messages',1),message)
        self.assertEqual(self.row('requirement_documents',current['id']),current)
        self.assertEqual(get_guide_run(self.database,self.run)['data']['status'],'CANCELLED')

    def test_waiting_user_cancellation_ends_wait_preserves_waiting_time(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE guide_runs SET status='WAITING_USER',current_step='WAITING_USER',waiting_user_at=? WHERE id=?",(self.at,self.run))
        self.assertEqual(self.cancel()['code'],'GUIDE_CANCELLED')
        self.assertEqual(self.row('guide_runs',self.run)['waiting_user_at'],self.at)
        self.assertEqual(self.row('requirements',self.req)['document_work_state'],'IDLE')

    def test_same_or_new_key_preserves_original_time_and_does_not_release_new_manual_occupancy(self):
        original=self.cancel();run=self.row('guide_runs',self.run)
        started=start_manual_draft(self.executor,{'requirement_id':self.req,'expected_content_version':1,'idempotency_key':'00000000-0000-4000-8000-00000000000c'},catalog=self.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=2))
        self.assertEqual(started['code'],'DRAFT_STARTED',started)
        before=self.row('requirements',self.req);facts=self.facts()
        self.assertEqual(self.cancel(),original);self.assertEqual(self.facts(),facts)
        self.assertEqual(self.cancel(idempotency_key='00000000-0000-4000-8000-00000000000d'),original)
        self.assertEqual(self.row('requirements',self.req),before);self.assertEqual(self.row('guide_runs',self.run),run)

    def test_persisting_and_completed_failed_refuse_without_mutation(self):
        for status,step in (('RUNNING','PERSISTING'),('COMPLETED','FINISHED'),('FAILED','FINISHED')):
            with self.subTest(status=status,step=step):
                with self.database.transaction(write=True) as connection:
                    connection.execute("UPDATE guide_runs SET status=?,current_step=?,ended_at=?,error_code=?,error_message=? WHERE id=?",(status,step,None if status=='RUNNING' else self.at,'MODEL_ERROR' if status=='FAILED' else None,'safe historical failure' if status=='FAILED' else None,self.run))
                before=self.facts();self.assertEqual(self.cancel()['code'],'STATE_CONFLICT');self.assertEqual(self.facts(),before)

    def test_invalid_inputs_and_missing_run_have_no_business_or_claim_writes(self):
        before=self.facts()
        for payload in ({},{'guide_run_id':self.run},{'guide_run_id':True,'idempotency_key':creation.OTHER},{'guide_run_id':'1','idempotency_key':creation.OTHER},{'guide_run_id':1,'idempotency_key':None},{'guide_run_id':1,'idempotency_key':creation.OTHER,'reason':'USER_REQUESTED'}):
            self.assertEqual(cancel_guide_run(self.executor,payload)['code'],'INVALID_INPUT');self.assertEqual(self.facts(),before)
        self.assertEqual(self.cancel(guide_run_id=999)['code'],'NOT_FOUND');self.assertEqual(self.facts(),before)

    def test_wrong_occupancy_cross_requirement_and_multiple_live_runs_are_not_repaired(self):
        other=self.create(idempotency_key='00000000-0000-4000-8000-00000000000c')['data']
        with self.database.transaction(write=True) as connection:
            connection.execute('UPDATE requirements SET active_operation_id=? WHERE id=?',(other['guide_run_id'],self.req))
        before=self.facts();self.assertEqual(self.cancel()['code'],'WORK_STATE_INCONSISTENT');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection:
            connection.execute('UPDATE requirements SET active_operation_id=? WHERE id=?',(self.run,self.req))
        self.protocol_run_fixture(10,action='ASK')
        before=self.facts();self.assertEqual(self.cancel()['code'],'WORK_STATE_INCONSISTENT');self.assertEqual(self.facts(),before)

    def test_each_actual_sql_failure_and_result_conversion_rolls_back_all_cancellation_facts(self):
        self.audit_fixture(1)
        for table,predicate in (('guide_runs',''),('llm_uses',''),('requirements',''),('idempotency_records',"WHEN NEW.status='SUCCEEDED'")):
            with self.subTest(table=table):
                with closing(sqlite3.connect(self.path)) as connection:
                    connection.execute(f"CREATE TRIGGER cancel_fault AFTER UPDATE ON {table} {predicate} BEGIN SELECT RAISE(ABORT,'actual cancellation failure'); END");connection.commit()
                before=self.facts();self.assertEqual(self.cancel()['code'],'STORAGE_UNAVAILABLE');self.assertEqual(self.facts(),before)
                with closing(sqlite3.connect(self.path)) as connection: connection.execute('DROP TRIGGER cancel_fault');connection.commit()
        before=self.facts()
        with patch('backend.app.guide.commands.cancel_guide_run_result',side_effect=ValueError('after real cancellation writes')):
            self.assertEqual(self.cancel()['code'],'INTERNAL_ERROR')
        self.assertEqual(self.facts(),before)

    def test_competing_different_keys_end_once_with_original_time(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=[future.result() for future in (pool.submit(self.cancel),pool.submit(self.cancel,idempotency_key='00000000-0000-4000-8000-00000000000c'))]
        self.assertEqual(results[0],results[1]);self.assertEqual(results[0]['code'],'GUIDE_CANCELLED')
        self.assertEqual(self.row('guide_runs',self.run)['ended_at'],utc_milliseconds(creation.INSTANT+timedelta(seconds=1)))

    def test_real_commit_lost_ack_replays_frozen_cancellation_without_new_writes(self):
        class LostAck(Database):
            writes=0
            @contextmanager
            def transaction(database,*,write=False):
                with super().transaction(write=write) as connection: yield connection
                if write:
                    database.writes+=1
                    if database.writes==2: raise CommitOutcomeUnknown('after actual cancellation commit')
        executor=Idempotency(LostAck(self.path),self.lock,clock=lambda:creation.INSTANT)
        result=cancel_guide_run(executor,{'guide_run_id':self.run,'idempotency_key':creation.OTHER},clock=lambda:creation.INSTANT+timedelta(seconds=1))
        self.assertEqual(result['code'],'STORAGE_UNAVAILABLE');before=self.facts()
        self.assertEqual(self.cancel()['code'],'GUIDE_CANCELLED');self.assertEqual(self.facts(),before)

    def test_processing_scope_blocks_and_canonical_key_replays(self):
        scope=Scope('APP-GUIDE-CMD-C03',f'GuideRun:{self.run}',creation.OTHER)
        claim=self.executor.claim(scope,{'guide_run_id':self.run})
        before=self.facts();self.assertEqual(self.cancel()['code'],'REQUEST_IN_PROGRESS');self.assertEqual(self.facts(),before)
        self.executor.abandon(claim)
        result=self.cancel();before=self.facts();self.assertEqual(self.cancel(idempotency_key=creation.OTHER.upper()),result);self.assertEqual(self.facts(),before)

    def test_future_attempt_and_activity_clock_reject_with_whole_transaction_unchanged(self):
        before=self.facts()
        self.assertEqual(cancel_guide_run(self.executor,{'guide_run_id':self.run,'idempotency_key':creation.OTHER},clock=lambda:creation.INSTANT-timedelta(seconds=1))['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)
        self.audit_fixture(1)
        with self.database.transaction(write=True) as connection:
            connection.execute('UPDATE llm_uses SET started_at=? WHERE id=1',(utc_milliseconds(creation.INSTANT+timedelta(hours=1)),))
        before=self.facts();self.assertEqual(self.cancel()['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
