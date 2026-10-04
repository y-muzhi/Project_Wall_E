"""Actual CURRENT/comment/session/proof/audit/idempotency completion transactions."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import timedelta
import json
import sqlite3
import unittest
from unittest.mock import patch
from backend.app.documents.commands import complete_manual_draft, start_manual_draft
from backend.app.documents.queries import get_current_document
from backend.app.documents.snapshot import Provenance, assign_identities, validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.database import Database, CommitOutcomeUnknown
from backend.app.infrastructure.idempotency import Idempotency, Scope
from backend.app.shared.time import utc_milliseconds
from backend.app.shared.validation import MAX_SAFE_INTEGER
from backend.tests.documents import test_save_manual_draft as saves
from backend.tests.documents import test_commands as drafts
from backend.tests.comments import test_revalidate_anchors as comments


class CompleteManualDraftTests(unittest.TestCase):
    start_payload = drafts.DraftCommandTests.start_payload
    start = drafts.DraftCommandTests.start
    facts = drafts.DraftCommandTests.facts
    current_facts = drafts.DraftCommandTests.current_facts
    payload = saves.SaveManualDraftTests.payload
    appended = saves.SaveManualDraftTests.appended
    save = saves.SaveManualDraftTests.save
    read = saves.SaveManualDraftTests.read
    seed = comments.RevalidateAnchorsTests.seed
    rows = comments.RevalidateAnchorsTests.rows

    def setUp(self):
        saves.SaveManualDraftTests.setUp(self)
        self.addCleanup(drafts.DraftCommandTests.tearDown,self)

    def complete_payload(self, **changes):
        return {'requirement_id':101,'expected_version':self.draft['content_version'],'idempotency_key':drafts.KEY,**changes}

    def complete(self, **changes):
        return complete_manual_draft(self.executor,self.complete_payload(**changes),catalog=self.catalog,clock=lambda:drafts.LATER+timedelta(seconds=1))

    def edited(self):
        self.draft=self.save(self.appended())['data']
        return self.draft

    def test_completion_preserves_current_identity_copies_exact_saved_pair_and_closes_source(self):
        saved=self.edited();current=self.current_facts()
        for identity in range(1,46): self.seed(identity,status='RESOLVED' if identity%2==0 else 'OPEN',block_id=saved['block_state_json']['blocks'][-1]['block_id'] if identity%3 else 999)
        before=self.rows();result=self.complete()
        self.assertEqual(result['code'],'DRAFT_COMPLETED',result)
        value=result['data'];self.assertEqual((value['id'],value['document_type'],value['content_version']),(201,'CURRENT',8))
        self.assertEqual(value['created_at'],current[6]);self.assertEqual(value['markdown_content'],saved['markdown_content']);self.assertEqual(value['block_state_json'],saved['block_state_json'])
        self.assertEqual(get_current_document(self.database,101,catalog=self.catalog)['data'],value)
        for identity,row in self.rows().items():
            self.assertEqual(row['anchor_status'],'ATTACHED' if identity%3 else 'ORPHANED')
            self.assertEqual({k:v for k,v in row.items() if k!='anchor_status'},{k:v for k,v in before[identity].items() if k!='anchor_status'})
        with self.database.transaction() as connection:
            for table in ('manual_draft_context','manual_block_origins','manual_block_allocation_ranges'):
                self.assertEqual(connection.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
            self.assertEqual(connection.execute("SELECT count(*) FROM requirement_documents WHERE document_type='MANUAL_DRAFT'").fetchone()[0],0)
            self.assertEqual(connection.execute('SELECT status FROM manual_edit_sessions').fetchone()[0],'COMPLETED')
            self.assertEqual(connection.execute('SELECT document_work_state FROM requirements').fetchone()[0],'IDLE')
            self.assertEqual(connection.execute('SELECT count(*) FROM revisions').fetchone()[0],1)
            audit=dict(connection.execute('SELECT * FROM document_change_audits').fetchone())
            self.assertEqual((audit['document_id'],audit['source_id'],audit['reason_code'],audit['before_content_version'],audit['after_content_version']),(201,saved['id'],'USER_MANUAL_EDIT',7,8))
            record=connection.execute("SELECT success_result_json FROM idempotency_records WHERE capability_id='APP-DOC-CMD-C03'").fetchone()
            self.assertEqual(json.loads(record[0]),result)

    def test_identical_body_still_increments_current_version_without_fabricated_change_audit(self):
        result=self.complete();self.assertEqual(result['code'],'DRAFT_COMPLETED',result)
        self.assertEqual(result['data']['content_version'],8)
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM document_change_audits').fetchone()[0],0)

    def test_draft_version_and_current_baseline_are_checked_independently(self):
        self.edited();before=self.facts()
        self.assertEqual(self.complete(expected_version=1)['code'],'CONTENT_VERSION_CONFLICT');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute('UPDATE requirement_documents SET content_version=8 WHERE id=201')
        before=self.facts();self.assertEqual(self.complete()['code'],'CONTENT_VERSION_CONFLICT');self.assertEqual(self.facts(),before)

    def test_missing_root_wrong_state_and_dangling_occupancy_preserve_all_facts(self):
        before=self.facts();self.assertEqual(self.complete(requirement_id=999)['code'],'NOT_FOUND');self.assertEqual(self.facts(),before)
        for sql,code in (("UPDATE requirements SET status='COMPLETED',completed_at=updated_at",'STATE_CONFLICT'),("UPDATE requirements SET active_operation_id=999",'WORK_STATE_INCONSISTENT')):
            with self.database.transaction(write=True) as connection: connection.execute(sql)
            before=self.facts();self.assertEqual(self.complete()['code'],code);self.assertEqual(self.facts(),before)
            with self.database.transaction(write=True) as connection: connection.execute("UPDATE requirements SET status='ACTIVE',completed_at=NULL,active_operation_id=?",(self.draft['id'],))

    def test_bad_saved_pair_is_document_invalid_missing_birth_proof_is_internal(self):
        saved=self.edited()
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE requirement_documents SET block_state_json='{}' WHERE id=?",(saved['id'],))
        before=self.facts();self.assertEqual(self.complete()['code'],'DOCUMENT_INVALID');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection:
            connection.execute('UPDATE requirement_documents SET block_state_json=? WHERE id=?',(json.dumps(saved['block_state_json']),saved['id']))
            connection.execute('DELETE FROM manual_block_origins')
        before=self.facts();self.assertEqual(self.complete()['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)

    def test_every_real_write_failure_rolls_back_current_comments_proofs_audit_source_and_success(self):
        self.edited();self.seed(1)
        for table,event,predicate in (
            ('requirement_documents','AFTER UPDATE',"WHEN NEW.document_type='CURRENT'"),
            ('comments','AFTER UPDATE',''),('document_change_audits','AFTER INSERT',''),
            ('manual_block_origins','AFTER DELETE',''),('manual_block_allocation_ranges','AFTER DELETE',''),
            ('manual_draft_context','AFTER DELETE',''),('requirement_documents','AFTER DELETE',''),
            ('requirements','AFTER UPDATE',''),('manual_edit_sessions','AFTER UPDATE',''),
            ('idempotency_records','BEFORE UPDATE',"WHEN NEW.status='SUCCEEDED'")):
            with self.subTest(table=table,event=event):
                with closing(sqlite3.connect(self.path)) as connection:
                    connection.execute(f"CREATE TRIGGER test_complete_fault {event} ON {table} {predicate} BEGIN SELECT RAISE(ABORT,'actual SQL failure'); END");connection.commit()
                before=self.facts();self.assertEqual(self.complete()['code'],'STORAGE_UNAVAILABLE');self.assertEqual(self.facts(),before)
                with closing(sqlite3.connect(self.path)) as connection: connection.execute('DROP TRIGGER test_complete_fault');connection.commit()

    def test_corrupt_comment_and_result_conversion_failure_abort_entire_completion(self):
        self.edited();self.seed(1);self.seed(2,kind='SELECTION',reference='{}')
        before=self.facts();self.assertEqual(self.complete()['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute('DELETE FROM comments WHERE id=2')
        before=self.facts()
        with patch('backend.app.documents.commands.complete_manual_draft_result',side_effect=ValueError('mapping failure after all real writes')):
            self.assertEqual(self.complete()['code'],'INTERNAL_ERROR')
        self.assertEqual(self.facts(),before)

    def test_current_version_and_audit_id_exhaustion_do_not_partially_complete(self):
        self.edited()
        with self.database.transaction(write=True) as connection:
            connection.execute('UPDATE requirement_documents SET content_version=? WHERE id=201',(MAX_SAFE_INTEGER,))
            connection.execute('UPDATE manual_draft_context SET base_content_version=?',(MAX_SAFE_INTEGER,))
        before=self.facts();self.assertEqual(self.complete()['code'],'CAPACITY_EXHAUSTED');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection:
            connection.execute('UPDATE requirement_documents SET content_version=7 WHERE id=201');connection.execute('UPDATE manual_draft_context SET base_content_version=7')
            connection.execute("INSERT INTO sequences VALUES ('DocumentChangeAudit',?)",(MAX_SAFE_INTEGER,))
        before=self.facts();self.assertEqual(self.complete()['code'],'CAPACITY_EXHAUSTED');self.assertEqual(self.facts(),before)

    def test_replay_returns_original_current_and_does_not_complete_newer_draft(self):
        result=self.complete();self.assertEqual(result['code'],'DRAFT_COMPLETED',result)
        started=start_manual_draft(self.executor,self.start_payload(expected_content_version=8,idempotency_key=drafts.SECOND_KEY),catalog=self.catalog,clock=lambda:drafts.LATER+timedelta(seconds=3))
        self.assertEqual(started['code'],'DRAFT_STARTED',started);before=self.facts()
        self.assertEqual(self.complete(),result);self.assertEqual(self.facts(),before)
        self.assertEqual(self.complete(expected_version=2)['code'],'IDEMPOTENCY_CONFLICT');self.assertEqual(self.facts(),before)

    def test_real_commit_lost_ack_can_replay_exact_success_without_second_effect(self):
        self.edited()
        class LostAck(Database):
            writes=0
            @contextmanager
            def transaction(database,*,write=False):
                with super().transaction(write=write) as connection: yield connection
                if write:
                    database.writes+=1
                    if database.writes==2: raise CommitOutcomeUnknown('after actual CURRENT/comment/session/success commit')
        executor=Idempotency(LostAck(self.path),self.lock,clock=lambda:drafts.LATER)
        result=complete_manual_draft(executor,self.complete_payload(),catalog=self.catalog,clock=lambda:drafts.LATER+timedelta(seconds=1))
        self.assertEqual(result['code'],'STORAGE_UNAVAILABLE');before=self.facts()
        replay=self.complete();self.assertEqual(replay['code'],'DRAFT_COMPLETED',replay);self.assertEqual(self.facts(),before)

    def test_actual_competing_completions_adopt_only_once(self):
        self.edited()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(self.complete,idempotency_key=key) for key in (drafts.KEY,drafts.SECOND_KEY)]
            codes=[future.result()['code'] for future in futures]
        self.assertCountEqual(codes,['DRAFT_COMPLETED','WORK_STATE_CONFLICT'])
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT content_version FROM requirement_documents WHERE id=201').fetchone()[0],8)
            self.assertEqual(connection.execute('SELECT count(*) FROM document_change_audits').fetchone()[0],1)

    def test_strict_input_invalid_and_processing_key_cannot_mutate(self):
        before=self.facts()
        for value in ({},self.complete_payload(expected_version=True),self.complete_payload(extra=1)):
            self.assertEqual(complete_manual_draft(self.executor,value)['code'],'INVALID_INPUT');self.assertEqual(self.facts(),before)
        self.executor.claim(Scope('APP-DOC-CMD-C03','Requirement:101',drafts.KEY),{'requirement_id':101,'expected_version':1})
        before=self.facts();self.assertEqual(self.complete()['code'],'REQUEST_IN_PROGRESS');self.assertEqual(self.facts(),before)


class InitializationCompletionTests(unittest.TestCase):
    start_payload=drafts.DraftCommandTests.start_payload
    start=drafts.DraftCommandTests.start
    facts=drafts.DraftCommandTests.facts

    def setUp(self):
        drafts.DraftCommandTests.setUp(self)
        self.addCleanup(drafts.DraftCommandTests.tearDown,self)
        self.draft=self.start()['data']['manual_draft']

    def complete(self):
        return complete_manual_draft(self.executor,{'requirement_id':101,'expected_version':1,'idempotency_key':drafts.KEY},catalog=self.catalog,clock=lambda:drafts.LATER)

    def test_initialization_finish_does_not_activate_or_create_revision(self):
        result=self.complete();self.assertEqual(result['code'],'DRAFT_COMPLETED',result)
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT status,document_work_state FROM requirements').fetchone()[:],('INITIALIZING','IDLE'))
            self.assertEqual(connection.execute('SELECT count(*) FROM revisions').fetchone()[0],0)
            self.assertEqual(connection.execute('SELECT count(*) FROM document_change_audits').fetchone()[0],0)

    def test_persisted_pair_with_changed_locked_heading_is_template_invalid(self):
        with self.database.transaction(write=True) as connection:
            sources=DocumentSources(connection,101,self.catalog);prior=validate_snapshot(self.draft['markdown_content'],self.draft['block_state_json'],sources)
            snapshot=assign_identities(prior.parsed.markdown.replace('# 需求新增规格','# 改名',1),list(prior.by_id),prior.next_block_id,prior,Provenance('USER','MANUAL_EDIT',self.draft['id']),utc_milliseconds(drafts.INSTANT),sources)
            connection.execute('UPDATE requirement_documents SET markdown_content=?,block_state_json=? WHERE id=?',(snapshot.parsed.markdown,snapshot.state_json,self.draft['id']))
        before=self.facts();self.assertEqual(self.complete()['code'],'TEMPLATE_INVALID');self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
