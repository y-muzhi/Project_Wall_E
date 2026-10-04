"""C01-C05 actual file commands, native ACTIVE baseline and atomic failures."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import timedelta
import sqlite3
import unittest
from unittest.mock import patch
from backend.app.comments import commands
from backend.app.comments.queries import get_comment, get_comment_index
from backend.app.documents.commands import start_manual_draft
from backend.app.infrastructure.database import Database, CommitOutcomeUnknown
from backend.app.infrastructure.idempotency import Idempotency, Scope
from backend.app.requirements.commands import complete_initialization
from backend.app.shared.time import utc_milliseconds
from backend.app.shared.validation import MAX_SAFE_INTEGER
from backend.tests.comments import test_queries as query_fixtures
from backend.tests.documents import test_commands as draft_fixtures
from backend.tests.documents.test_snapshot import T1

KEY=draft_fixtures.KEY


class CommentCommandTests(unittest.TestCase):
    facts=query_fixtures.CommentQueryTests.facts
    write_body=query_fixtures.CommentQueryTests.write_body

    def setUp(self):
        query_fixtures.CommentQueryTests.setUp(self)
        result=complete_initialization(self.executor,{'requirement_id':101,'expected_content_version':7,'idempotency_key':draft_fixtures.BASE_KEY},catalog=self.catalog,clock=lambda:draft_fixtures.INSTANT)
        self.assertEqual(result['code'],'INITIALIZATION_COMPLETED',result)

    def create_payload(self,**changes):
        return {'requirement_id':101,'expected_content_version':7,'content':' \r\n说明😀\r\n第二行\t','anchor_type':'BLOCK','block_id':1,'idempotency_key':KEY,**changes}

    def create(self,**changes):
        return commands.create_comment(self.executor,self.create_payload(**changes),catalog=self.catalog,clock=lambda:draft_fixtures.LATER)

    def action(self,name,identity=1,**changes):
        payload={'comment_id':identity,'idempotency_key':KEY,**changes}
        return getattr(commands,name+'_comment')(self.executor,payload,clock=lambda:draft_fixtures.LATER+timedelta(seconds=1))

    def row(self,table,identity):
        with self.database.transaction() as connection: return dict(connection.execute('SELECT * FROM '+table+' WHERE id=?',(identity,)).fetchone())

    def test_actual_block_creation_normalizes_text_keeps_authoritative_anchor_and_other_aggregates(self):
        root=self.row('requirements',101);current=self.row('requirement_documents',201)
        with self.database.transaction() as connection: revisions=[dict(row) for row in connection.execute('SELECT * FROM revisions')]
        result=self.create();self.assertEqual(result['code'],'COMMENT_CREATED',result);value=result['data']
        self.assertEqual((value['content'],value['status'],value['anchor_status'],value['created_at'],value['updated_at']),('说明😀\n第二行','OPEN','ATTACHED',utc_milliseconds(draft_fixtures.LATER),utc_milliseconds(draft_fixtures.LATER)))
        self.assertEqual(value['anchor_ref'],{'block_markdown_snapshot':self.original.by_id[1][0].markdown})
        self.assertEqual(self.row('requirements',101),root);self.assertEqual(self.row('requirement_documents',201),current)
        with self.database.transaction() as connection: self.assertEqual([dict(row) for row in connection.execute('SELECT * FROM revisions')],revisions)
        self.assertEqual(get_comment_index(self.database,101)['data']['blocks'][0]['comment_ids'],[value['id']])

    def test_selection_derived_from_actual_body_unicode_and_nonunique_or_foreign_block_refuse(self):
        with self.database.transaction(write=True) as connection: self.write_body(connection,'甲😀乙 aaa\n')
        selected={'selected_text':'😀','prefix_text':'甲','suffix_text':'乙'}
        result=self.create(anchor_type='SELECTION',selection=selected,expected_content_version=8)
        self.assertEqual(result['code'],'COMMENT_CREATED',result);self.assertEqual(result['data']['anchor_ref'],selected)
        for changes in ({'block_id':999,'selection':selected},{'block_id':1,'selection':{'selected_text':'aa','prefix_text':'','suffix_text':''}},{'block_id':1,'selection':{'selected_text':'😀','prefix_text':'wrong','suffix_text':'乙'}}):
            before=self.facts();result=self.create(anchor_type='SELECTION',expected_content_version=8,idempotency_key=draft_fixtures.SECOND_KEY,**changes)
            self.assertEqual(result['code'],'ANCHOR_INVALID');self.assertEqual(self.facts(),before)

    def test_all_invalid_structural_inputs_unicode_and_selection_conditions_are_zero_claim(self):
        before=self.facts();base=self.create_payload()
        variants=[{k:v for k,v in base.items() if k!=missing} for missing in base]
        variants += [self.create_payload(**changes) for changes in ({'content':' '},{'content':'x'*2001},{'content':'\ud800'},{'block_id':True},{'selection':{}},{'anchor_type':'SELECTION'},{'anchor_type':'SELECTION','selection':{'selected_text':'😀','prefix_text':'','suffix_text':'','offset':0}},{'extra':1})]
        for payload in variants:
            self.assertEqual(commands.create_comment(self.executor,payload)['code'],'INVALID_INPUT');self.assertEqual(self.facts(),before)
        self.assertEqual(commands.edit_comment(self.executor,{'comment_id':1,'content':'\ud800','idempotency_key':KEY})['code'],'INVALID_INPUT');self.assertEqual(self.facts(),before)

    def test_state_occupancy_and_current_version_rechecked_inside_creation_transaction(self):
        before=self.facts();self.assertEqual(self.create(expected_content_version=6)['code'],'CONTENT_VERSION_CONFLICT');self.assertEqual(self.facts(),before)
        started=start_manual_draft(self.executor,{'requirement_id':101,'expected_content_version':7,'idempotency_key':draft_fixtures.SECOND_KEY},catalog=self.catalog,clock=lambda:draft_fixtures.INSTANT)
        self.assertEqual(started['code'],'DRAFT_STARTED',started);before=self.facts()
        self.assertEqual(self.create()['code'],'WORK_STATE_CONFLICT');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE requirements SET status='COMPLETED',completed_at=? WHERE id=101",(T1,))
        before=self.facts();self.assertEqual(self.create()['code'],'STATE_CONFLICT');self.assertEqual(self.facts(),before)

    def test_orphaned_comments_can_edit_resolve_reopen_and_soft_delete_keeps_reference(self):
        created=self.create()['data'];original=self.row('comments',created['id'])
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE comments SET anchor_status='ORPHANED' WHERE id=?",(created['id'],))
        edited=self.action('edit',content=' changed\r\n正文 ');self.assertEqual(edited['code'],'COMMENT_UPDATED',edited);self.assertEqual(edited['data']['content'],'changed\n正文')
        self.assertEqual(edited['data']['anchor_ref'],created['anchor_ref']);self.assertEqual(edited['data']['anchor_status'],'ORPHANED')
        resolved=self.action('resolve');self.assertEqual(resolved['data']['status'],'RESOLVED');self.assertIsNotNone(resolved['data']['resolved_at'])
        reopened=self.action('reopen');self.assertEqual(reopened['data']['status'],'OPEN');self.assertIsNone(reopened['data']['resolved_at'])
        deleted=self.action('delete');self.assertEqual(deleted['code'],'COMMENT_UPDATED');self.assertIsNotNone(deleted['data']['deleted_at'])
        self.assertEqual(get_comment(self.database,1)['data'],deleted['data']);self.assertEqual(get_comment_index(self.database,101)['data']['total_count'],0)
        row=self.row('comments',1)
        for field in ('id','requirement_id','anchor_type','block_id','anchor_ref_json','created_at'): self.assertEqual(row[field],original[field])
        for action in ('edit','resolve','reopen'):
            before=self.facts();changes={'content':'late'} if action=='edit' else {}
            self.assertEqual(self.action(action,idempotency_key=draft_fixtures.SECOND_KEY,**changes)['code'],'STATE_CONFLICT');self.assertEqual(self.facts(),before)

    def test_repeated_status_operations_keep_times_and_original_success_replays_after_lifecycle_changes(self):
        self.create();resolved=self.action('resolve');row=self.row('comments',1)
        again=self.action('resolve',idempotency_key=draft_fixtures.SECOND_KEY);self.assertEqual(again,resolved);self.assertEqual(self.row('comments',1),row)
        reopened=self.action('reopen');row=self.row('comments',1)
        self.assertEqual(self.action('reopen',idempotency_key=draft_fixtures.SECOND_KEY),reopened);self.assertEqual(self.row('comments',1),row)
        deleted=self.action('delete');row=self.row('comments',1)
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE requirements SET status='COMPLETED',completed_at=? WHERE id=101",(T1,))
        self.assertEqual(self.action('delete',idempotency_key=draft_fixtures.SECOND_KEY),deleted);self.assertEqual(self.row('comments',1),row)
        self.assertEqual(self.action('resolve'),resolved)
        before=self.facts();self.assertEqual(self.create()['code'],'COMMENT_CREATED');self.assertEqual(self.facts(),before)

    def test_edit_requires_open_and_active_idle_but_no_current_body_read(self):
        self.create();self.action('resolve');before=self.facts()
        self.assertEqual(self.action('edit',content='late')['code'],'STATE_CONFLICT');self.assertEqual(self.facts(),before)
        self.action('reopen')
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE requirement_documents SET markdown_content='damaged' WHERE id=201")
        result=self.action('edit',content='new text');self.assertEqual(result['code'],'COMMENT_UPDATED',result)
        self.assertEqual(self.row('requirement_documents',201)['markdown_content'],'damaged')

    def test_creation_sql_result_and_id_capacity_failures_roll_back_all_new_comment_facts(self):
        for table,event,predicate in (('sequences','AFTER INSERT',''),('comments','AFTER INSERT',''),('idempotency_records','AFTER UPDATE',"WHEN NEW.status='SUCCEEDED'")):
            with closing(sqlite3.connect(self.path)) as connection:
                connection.execute(f"CREATE TRIGGER comment_fault {event} ON {table} {predicate} BEGIN SELECT RAISE(ABORT,'actual comment create fault'); END");connection.commit()
            before=self.facts();self.assertEqual(self.create()['code'],'STORAGE_UNAVAILABLE');self.assertEqual(self.facts(),before)
            with closing(sqlite3.connect(self.path)) as connection: connection.execute('DROP TRIGGER comment_fault');connection.commit()
        before=self.facts()
        with patch('backend.app.comments.commands.create_comment_result',side_effect=ValueError('after real creation writes')):
            self.assertEqual(self.create()['code'],'INTERNAL_ERROR')
        self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute("INSERT INTO sequences VALUES ('Comment',?)",(MAX_SAFE_INTEGER,))
        before=self.facts();self.assertEqual(self.create()['code'],'CAPACITY_EXHAUSTED');self.assertEqual(self.facts(),before)

    def test_each_lifecycle_and_edit_rolls_back_real_update_on_sql_or_result_failure(self):
        self.create()
        for name,changes in (('edit',{'content':'new'}),('resolve',{}),('delete',{})):
            with closing(sqlite3.connect(self.path)) as connection:
                connection.execute("CREATE TRIGGER comment_fault AFTER UPDATE ON comments BEGIN SELECT RAISE(ABORT,'actual update failure'); END");connection.commit()
            before=self.facts();self.assertEqual(self.action(name,**changes)['code'],'STORAGE_UNAVAILABLE');self.assertEqual(self.facts(),before)
            with closing(sqlite3.connect(self.path)) as connection: connection.execute('DROP TRIGGER comment_fault');connection.commit()
            before=self.facts()
            with patch('backend.app.comments.commands.'+name+'_comment_result',side_effect=ValueError('after real action update')):
                self.assertEqual(self.action(name,**changes)['code'],'INTERNAL_ERROR')
            self.assertEqual(self.facts(),before)
        self.action('resolve');before=self.facts()
        with patch('backend.app.comments.commands.reopen_comment_result',side_effect=ValueError('after real reopen')):
            self.assertEqual(self.action('reopen')['code'],'INTERNAL_ERROR')
        self.assertEqual(self.facts(),before)

    def test_normalized_idempotency_original_snapshots_and_changed_input_conflict(self):
        first=self.create();before=self.facts();self.assertEqual(self.create(content='说明😀\n第二行',selection=None,idempotency_key=KEY.upper()),first);self.assertEqual(self.facts(),before)
        self.assertEqual(self.create(content='different')['code'],'IDEMPOTENCY_CONFLICT');self.assertEqual(self.facts(),before)
        self.assertEqual(self.action('edit',content='first')['code'],'COMMENT_UPDATED');before=self.facts()
        self.assertEqual(self.action('edit',content='second')['code'],'IDEMPOTENCY_CONFLICT');self.assertEqual(self.facts(),before)

    def test_actual_commit_lost_ack_create_replays_one_comment_and_update_keeps_original_event(self):
        class LostAck(Database):
            writes=0
            @contextmanager
            def transaction(database,*,write=False):
                with super().transaction(write=write) as connection: yield connection
                if write:
                    database.writes+=1
                    if database.writes==2: raise CommitOutcomeUnknown('after actual comment commit')
        executor=Idempotency(LostAck(self.path),self.lock,clock=lambda:draft_fixtures.INSTANT)
        result=commands.create_comment(executor,self.create_payload(),catalog=self.catalog,clock=lambda:draft_fixtures.LATER)
        self.assertEqual(result['code'],'STORAGE_UNAVAILABLE');before=self.facts();self.assertEqual(self.create()['code'],'COMMENT_CREATED');self.assertEqual(self.facts(),before)
        executor=Idempotency(LostAck(self.path),self.lock,clock=lambda:draft_fixtures.INSTANT)
        result=commands.resolve_comment(executor,{'comment_id':1,'idempotency_key':KEY},clock=lambda:draft_fixtures.LATER)
        self.assertEqual(result['code'],'STORAGE_UNAVAILABLE');before=self.facts();self.assertEqual(self.action('resolve')['code'],'COMMENT_UPDATED');self.assertEqual(self.facts(),before)

    def test_serial_edit_replacement_and_soft_delete_winner_with_real_competing_writers(self):
        self.create()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=[future.result() for future in (pool.submit(self.action,'edit',content='edit won first'),pool.submit(self.action,'delete'))]
        self.assertEqual(results[1]['code'],'COMMENT_UPDATED');self.assertIn(results[0]['code'],('COMMENT_UPDATED','STATE_CONFLICT'))
        self.assertIsNotNone(self.row('comments',1)['deleted_at']);before=self.facts()
        self.assertEqual(self.action('edit',content='late',idempotency_key=draft_fixtures.SECOND_KEY)['code'],'STATE_CONFLICT');self.assertEqual(self.facts(),before)

    def test_missing_comments_processing_claim_and_clock_do_not_write_partial_business(self):
        before=self.facts();self.assertEqual(self.action('resolve',999)['code'],'NOT_FOUND');self.assertEqual(self.facts(),before)
        claim=self.executor.claim(Scope('APP-COMMENT-CMD-C01','Requirement:101',KEY),commands.create_comment_input(self.create_payload()).business_input())
        before=self.facts();self.assertEqual(self.create()['code'],'REQUEST_IN_PROGRESS');self.assertEqual(self.facts(),before);self.executor.abandon(claim)
        before=self.facts();result=commands.create_comment(self.executor,self.create_payload(),catalog=self.catalog,clock=lambda:draft_fixtures.INSTANT-timedelta(seconds=1))
        self.assertEqual(result['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
