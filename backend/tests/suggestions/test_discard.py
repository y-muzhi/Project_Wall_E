"""C03 actual SQLite discard; historical suggestions are explicit fixtures."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import timedelta
import sqlite3
import unittest
from unittest.mock import patch
from backend.app.documents.commands import start_manual_draft
from backend.app.guide.commands import recover_runs
from backend.app.infrastructure.database import Database, CommitOutcomeUnknown
from backend.app.infrastructure.idempotency import Idempotency
from backend.app.suggestions.commands import discard_batch
from backend.app.shared.time import utc_milliseconds
from backend.tests.suggestions import test_queries as fixtures
from backend.tests.requirements import test_create_requirement as creation


class DiscardTests(unittest.TestCase):
    facts=fixtures.BatchQueryTests.facts
    payload=fixtures.BatchQueryTests.payload
    create=fixtures.BatchQueryTests.create
    row=fixtures.BatchQueryTests.row
    terminal=fixtures.BatchQueryTests.terminal
    batch_fixture=fixtures.BatchQueryTests.batch_fixture
    add_suggestion=fixtures.BatchQueryTests.add_suggestion

    def setUp(self):
        fixtures.BatchQueryTests.setUp(self)
        result=recover_runs(self.database,{'recovery_reason':'STARTUP','live_run_ids':set(),'operation_time':self.at},process_lock=self.lock)
        self.assertEqual(result['code'],'RECOVERED',result)

    def discard(self,**changes):
        return discard_batch(self.executor,{'batch_id':10,'idempotency_key':creation.KEY,**changes},clock=lambda:creation.INSTANT+timedelta(seconds=1))

    def test_actual_discard_releases_only_owner_and_preserves_every_decision_and_source(self):
        for identity,status in ((11,'ACCEPTED'),(12,'REJECTED'),(13,'EDITED')): self.add_suggestion(identity,identity-9,status)
        with self.database.transaction() as connection:
            preserved={table:[dict(row) for row in connection.execute('SELECT * FROM '+table)] for table in ('suggestions','guide_runs','conversation_messages','requirement_documents','revisions','comments','sequences')}
        batch=self.row('suggestion_batches',10);result=self.discard()
        self.assertEqual(result['code'],'BATCH_DISCARDED',result)
        self.assertEqual(result['data']['counts'],{'total':4,'pending':1,'accepted':1,'rejected':1,'edited':1})
        root=self.row('requirements',self.req)
        self.assertEqual((root['document_work_state'],root['active_operation_type'],root['active_operation_id'],root['state_started_at']),('IDLE',None,None,None))
        after=self.row('suggestion_batches',10)
        for field,value in batch.items():
            if field not in ('status','completed_at','updated_at'): self.assertEqual(after[field],value)
        self.assertEqual(after['completed_at'],utc_milliseconds(creation.INSTANT+timedelta(seconds=1)))
        with self.database.transaction() as connection:
            for table,rows in preserved.items(): self.assertEqual([dict(row) for row in connection.execute('SELECT * FROM '+table)],rows)

    def test_frozen_success_replay_does_not_release_later_manual_session_new_key_conflicts(self):
        result=self.discard()
        started=start_manual_draft(self.executor,{'requirement_id':self.req,'expected_content_version':1,'idempotency_key':creation.OTHER},catalog=self.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=2))
        self.assertEqual(started['code'],'DRAFT_STARTED',started);before=self.facts()
        self.assertEqual(self.discard(),result);self.assertEqual(self.facts(),before)
        self.assertEqual(self.discard(idempotency_key=creation.OTHER)['code'],'STATE_CONFLICT');self.assertEqual(self.facts(),before)

    def test_discard_does_not_parse_stale_current_or_modify_stored_validation(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirement_documents SET markdown_content='damaged historical body'")
            connection.execute("UPDATE suggestions SET validation_status='INVALID',validation_error='safe prior failure'")
        current=self.row('requirement_documents',self.created['current_document_id']);item=self.row('suggestions',10)
        self.assertEqual(self.discard()['code'],'BATCH_DISCARDED')
        self.assertEqual(self.row('requirement_documents',current['id']),current);self.assertEqual(self.row('suggestions',10),item)

    def test_invalid_and_missing_inputs_leave_no_claim(self):
        before=self.facts()
        for payload in ({},{'batch_id':True,'idempotency_key':creation.KEY},{'batch_id':10,'idempotency_key':'bad'},{'batch_id':10,'idempotency_key':creation.KEY,'extra':1}):
            self.assertEqual(discard_batch(self.executor,payload)['code'],'INVALID_INPUT');self.assertEqual(self.facts(),before)
        self.assertEqual(self.discard(batch_id=999)['code'],'NOT_FOUND');self.assertEqual(self.facts(),before)

    def test_wrong_lifecycle_and_terminal_batch_are_atomic_rejections(self):
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE requirements SET status='COMPLETED',completed_at=?",(self.at,))
        before=self.facts();self.assertEqual(self.discard()['code'],'STATE_CONFLICT');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET status='ACTIVE',completed_at=NULL")
            connection.execute("UPDATE suggestion_batches SET status='DISCARDED',completed_at=?",(self.at,))
        before=self.facts();self.assertEqual(self.discard()['code'],'STATE_CONFLICT');self.assertEqual(self.facts(),before)

    def test_bad_owner_parent_and_multiple_activity_are_not_repaired_by_discard(self):
        with self.database.transaction(write=True) as connection: connection.execute('UPDATE requirements SET active_operation_id=999')
        before=self.facts();self.assertEqual(self.discard()['code'],'WORK_STATE_INCONSISTENT');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection:
            connection.execute('UPDATE requirements SET active_operation_id=10')
            connection.execute("UPDATE guide_runs SET status='FAILED',error_code='MODEL_ERROR',error_message='safe fixture failure' WHERE id=10")
        before=self.facts();self.assertEqual(self.discard()['code'],'WORK_STATE_INCONSISTENT');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE guide_runs SET status='COMPLETED',error_code=NULL,error_message=NULL WHERE id=10")
        self.batch_fixture(11,parent_id=11,owned=False)
        before=self.facts();self.assertEqual(self.discard()['code'],'WORK_STATE_INCONSISTENT');self.assertEqual(self.facts(),before)

    def test_empty_overcapacity_and_clock_regression_are_safe_atomic_failures(self):
        before=self.facts()
        result=discard_batch(self.executor,{'batch_id':10,'idempotency_key':creation.KEY},clock=lambda:creation.INSTANT-timedelta(seconds=1))
        self.assertEqual(result['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)
        for identity in range(11,111): self.add_suggestion(identity,identity-9)
        before=self.facts();self.assertEqual(self.discard()['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute('DELETE FROM suggestions')
        before=self.facts();self.assertEqual(self.discard()['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)

    def test_each_actual_write_and_result_conversion_failure_rolls_back_whole_aggregate(self):
        for table,predicate in (('suggestion_batches',''),('requirements',''),('idempotency_records',"WHEN NEW.status='SUCCEEDED'")):
            with closing(sqlite3.connect(self.path)) as connection:
                connection.execute(f"CREATE TRIGGER discard_fault AFTER UPDATE ON {table} {predicate} BEGIN SELECT RAISE(ABORT,'actual discard fault'); END");connection.commit()
            before=self.facts();self.assertEqual(self.discard()['code'],'STORAGE_UNAVAILABLE');self.assertEqual(self.facts(),before)
            with closing(sqlite3.connect(self.path)) as connection: connection.execute('DROP TRIGGER discard_fault');connection.commit()
        before=self.facts()
        with patch('backend.app.suggestions.commands.discard_batch_result',side_effect=ValueError('private conversion failure')): self.assertEqual(self.discard()['code'],'INTERNAL_ERROR')
        self.assertEqual(self.facts(),before)

    def test_real_commit_lost_ack_replays_committed_success_without_second_discard(self):
        class LostAck(Database):
            writes=0
            @contextmanager
            def transaction(database,*,write=False):
                with super().transaction(write=write) as connection: yield connection
                if write:
                    database.writes+=1
                    if database.writes==2: raise CommitOutcomeUnknown('after actual discard commit')
        executor=Idempotency(LostAck(self.path),self.lock,clock=lambda:creation.INSTANT)
        result=discard_batch(executor,{'batch_id':10,'idempotency_key':creation.KEY},clock=lambda:creation.INSTANT+timedelta(seconds=1))
        self.assertEqual(result['code'],'STORAGE_UNAVAILABLE');self.assertEqual(self.row('suggestion_batches',10)['status'],'DISCARDED')
        before=self.facts();self.assertEqual(self.discard()['code'],'BATCH_DISCARDED');self.assertEqual(self.facts(),before)

    def test_two_actual_writers_yield_one_success_and_one_state_conflict(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=[future.result() for future in (pool.submit(self.discard),pool.submit(self.discard,idempotency_key=creation.OTHER))]
        self.assertCountEqual([value['code'] for value in results],['BATCH_DISCARDED','STATE_CONFLICT'])
        self.assertEqual(self.row('requirements',self.req)['document_work_state'],'IDLE')


if __name__=='__main__': unittest.main()
