"""C05 actual comment acceptance and committed rejection; historical body fixtures."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import timedelta
import json
import sqlite3
import unittest
from unittest.mock import patch
from backend.app.guide import commands
from backend.app.comments import commands as comment_commands
from backend.app.documents.commands import start_manual_draft
from backend.app.infrastructure.database import Database, CommitOutcomeUnknown
from backend.app.infrastructure.idempotency import Idempotency, Scope, CommentAnchorRejected
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.shared.validation import MAX_SAFE_INTEGER
from backend.tests.comments import test_commands as fixtures
from backend.tests.documents import test_commands as document_fixtures

KEY=fixtures.KEY
OTHER=document_fixtures.SECOND_KEY
NOW=document_fixtures.LATER+timedelta(seconds=1)


class CommentAcceptanceTests(unittest.TestCase):
    facts=fixtures.CommentCommandTests.facts
    write_body=fixtures.CommentCommandTests.write_body
    row=fixtures.CommentCommandTests.row
    create_payload=fixtures.CommentCommandTests.create_payload
    make_comment=fixtures.CommentCommandTests.create

    def setUp(self): fixtures.CommentCommandTests.setUp(self)

    def command_payload(self,**changes):
        return {'comment_id':1,'expected_content_version':7,'idempotency_key':KEY,**changes}

    def modify(self,**changes):
        return commands.modify_from_comment(self.executor,self.command_payload(**changes),catalog=self.catalog,clock=lambda:NOW)

    def stale_selection(self):
        # Actual comment creator over a valid historical CURRENT snapshot; a
        # second explicit stored snapshot models an anchor needing relocation.
        with self.database.transaction(write=True) as connection: self.write_body(connection,'a\n')
        result=self.make_comment(anchor_type='SELECTION',selection={'selected_text':'a','prefix_text':'','suffix_text':''},expected_content_version=8)
        self.assertEqual(result['code'],'COMMENT_CREATED',result)
        with self.database.transaction(write=True) as connection: self.write_body(connection,'b\n')

    def test_actual_comment_text_source_scope_permissions_and_occupancy_atomic(self):
        self.assertEqual(self.make_comment()['code'],'COMMENT_CREATED');comment=self.row('comments',1);current=self.row('requirement_documents',201)
        result=self.modify();self.assertEqual(result['code'],'GUIDE_ACCEPTED',result);data=result['data'];run=self.row('guide_runs',data['id'])
        self.assertEqual((data['action_type'],data['function_type'],data['source_type'],data['source_id']),('MODIFY','MODIFY_FROM_COMMENT','COMMENT',1))
        self.assertEqual(data['scope'],{'scope_type':'BLOCK','scope_ref':{'block_id':1}})
        message=self.row('conversation_messages',run['trigger_message_id']);self.assertEqual(message['content'],comment['content']);self.assertEqual(message['guide_run_id'],run['id'])
        self.assertEqual([target['block_id'] for target in json.loads(run['allowed_targets_json'])['targets']],[1])
        self.assertEqual(json.loads(run['read_scope_manifest_json'])['source'],{'source_type':'COMMENT','source_id':1})
        self.assertEqual(self.row('requirements',101)['active_operation_id'],run['id']);self.assertEqual(self.row('comments',1),comment);self.assertEqual(self.row('requirement_documents',201),current)

    def test_actual_unicode_selection_authority_never_includes_neighbors(self):
        with self.database.transaction(write=True) as connection: self.write_body(connection,'甲😀乙\n\n相邻区块\n')
        anchor={'selected_text':'😀','prefix_text':'甲','suffix_text':'乙'}
        self.assertEqual(self.make_comment(anchor_type='SELECTION',selection=anchor,expected_content_version=8)['code'],'COMMENT_CREATED')
        result=self.modify(expected_content_version=8);self.assertEqual(result['code'],'GUIDE_ACCEPTED',result)
        run=self.row('guide_runs',result['data']['id']);targets=json.loads(run['allowed_targets_json'])['targets']
        self.assertEqual([(target['block_id'],target['operations'],target['selection_range']) for target in targets],[(1,['REPLACE_BLOCK'],{'start_offset':1,'end_offset':2})])
        self.assertIn(2,json.loads(run['read_scope_manifest_json'])['block_ids']);self.assertEqual(result['data']['scope']['scope_ref'],{'block_id':1,**anchor})

    def test_failed_relocation_commits_only_anchor_status_and_no_success_or_entities(self):
        self.stale_selection();before_comment=self.row('comments',1);current=self.row('requirement_documents',201);root=self.row('requirements',101)
        with self.database.transaction() as connection:
            runs=[dict(row) for row in connection.execute('SELECT * FROM guide_runs')];messages=[dict(row) for row in connection.execute('SELECT * FROM conversation_messages')];claims=[dict(row) for row in connection.execute('SELECT * FROM idempotency_records')]
        result=self.modify(expected_content_version=9);self.assertEqual(result,{'code':'COMMENT_ORPHANED','data':None,'details':None})
        self.assertEqual(self.row('comments',1),{**before_comment,'anchor_status':'ORPHANED'});self.assertEqual(self.row('requirement_documents',201),current);self.assertEqual(self.row('requirements',101),root)
        with self.database.transaction() as connection:
            self.assertEqual([dict(row) for row in connection.execute('SELECT * FROM guide_runs')],runs);self.assertEqual([dict(row) for row in connection.execute('SELECT * FROM conversation_messages')],messages);self.assertEqual([dict(row) for row in connection.execute('SELECT * FROM idempotency_records')],claims)
        before=self.facts();self.assertEqual(self.modify(expected_content_version=9),result);self.assertEqual(self.facts(),before)

    def test_relocation_sql_failure_rolls_back_anchor_and_releases_known_claim(self):
        self.stale_selection()
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("CREATE TRIGGER orphan_fault AFTER UPDATE ON comments BEGIN SELECT RAISE(ABORT,'private orphan correction'); END");connection.commit()
        before=self.facts();self.assertEqual(self.modify(expected_content_version=9)['code'],'STORAGE_UNAVAILABLE');self.assertEqual(self.facts(),before)

    def test_committed_rejection_lost_ack_then_recheck_preserves_only_corrected_anchor(self):
        self.stale_selection()
        class LostAck(Database):
            writes=0
            @contextmanager
            def transaction(database,*,write=False):
                with super().transaction(write=write) as connection: yield connection
                if write:
                    database.writes+=1
                    if database.writes==2: raise CommitOutcomeUnknown('after actual anchor-only rejection commit')
        executor=Idempotency(LostAck(self.path),self.lock,clock=lambda:document_fixtures.INSTANT)
        result=commands.modify_from_comment(executor,self.command_payload(expected_content_version=9),catalog=self.catalog,clock=lambda:NOW)
        self.assertEqual(result['code'],'STORAGE_UNAVAILABLE');self.assertEqual(self.row('comments',1)['anchor_status'],'ORPHANED')
        before=self.facts();self.assertEqual(self.modify(expected_content_version=9)['code'],'COMMENT_ORPHANED');self.assertEqual(self.facts(),before)

    def test_committed_rejection_cannot_be_used_by_other_capability_or_target(self):
        self.make_comment()
        for scope in (Scope('APP-DOC-CMD-C03','Comment:1',KEY),Scope('APP-GUIDE-CMD-C05','Comment:2',KEY)):
            before=self.facts()
            def forbidden(connection):
                connection.execute("UPDATE comments SET anchor_status='ORPHANED' WHERE id=1")
                return CommentAnchorRejected(1)
            with self.assertRaises(ValueError): self.executor.execute(scope,{'comment_id':1},forbidden)
            self.assertEqual(self.facts(),before)

    def test_actual_competing_successes_and_competing_rejections_have_no_duplicate_run(self):
        self.make_comment()
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda key:self.modify(idempotency_key=key),(KEY,OTHER)))
        self.assertEqual(sorted(result['code'] for result in results),['GUIDE_ACCEPTED','WORK_STATE_CONFLICT'])
        with self.database.transaction() as connection: self.assertEqual(connection.execute('SELECT count(*) FROM guide_runs WHERE source_id=1').fetchone()[0],1)

    def test_same_success_key_replays_original_run_after_comment_delete_and_missing_resources(self):
        self.make_comment();original=self.modify();run_id=original['data']['id']
        self.assertEqual(commands.cancel_guide_run(self.executor,{'guide_run_id':run_id,'idempotency_key':OTHER},clock=lambda:NOW+timedelta(seconds=1))['code'],'GUIDE_CANCELLED')
        self.assertEqual(comment_commands.delete_comment(self.executor,{'comment_id':1,'idempotency_key':OTHER},clock=lambda:NOW+timedelta(seconds=2))['code'],'COMMENT_UPDATED')
        before=self.facts()
        with patch('backend.app.guide.commands.ResourceCatalog',side_effect=ConfigInvalid('frozen resources missing')):
            self.assertEqual(commands.modify_from_comment(self.executor,self.command_payload(),clock=lambda:NOW),original)
        self.assertEqual(self.facts(),before);self.assertEqual(self.modify(idempotency_key=OTHER)['code'],'STATE_CONFLICT');self.assertEqual(self.facts(),before)

    def test_success_sql_faults_and_mapping_roll_back_message_run_root_and_claim(self):
        self.make_comment()
        for table,kind,predicate in (('conversation_messages','INSERT',''),('guide_runs','INSERT',''),('requirements','UPDATE',''),('idempotency_records','UPDATE',"WHEN NEW.status='SUCCEEDED'")):
            with closing(sqlite3.connect(self.path)) as connection:
                connection.execute(f"CREATE TRIGGER comment_run_fault AFTER {kind} ON {table} {predicate} BEGIN SELECT RAISE(ABORT,'private comment acceptance'); END");connection.commit()
            before=self.facts();self.assertEqual(self.modify()['code'],'STORAGE_UNAVAILABLE');self.assertEqual(self.facts(),before)
            with closing(sqlite3.connect(self.path)) as connection: connection.execute('DROP TRIGGER comment_run_fault');connection.commit()
        before=self.facts()
        with patch('backend.app.guide.commands.modify_from_comment_result',side_effect=ValueError('after actual accepted writes')): self.assertEqual(self.modify()['code'],'INTERNAL_ERROR')
        self.assertEqual(self.facts(),before)

    def test_invalid_inputs_state_version_work_and_config_never_override_source(self):
        self.make_comment();before=self.facts()
        for change in ({'comment_id':True},{'expected_content_version':False},{'scope':{}},{'source_type':'USER_INSTRUCTION'},{'content':'override'}):
            self.assertEqual(self.modify(**change)['code'],'INVALID_INPUT');self.assertEqual(self.facts(),before)
        self.assertEqual(self.modify(expected_content_version=8)['code'],'CONTENT_VERSION_CONFLICT');self.assertEqual(self.facts(),before)
        self.assertEqual(self.modify(comment_id=999)['code'],'NOT_FOUND');self.assertEqual(self.facts(),before)
        with patch.object(self.catalog,'freeze',side_effect=ConfigInvalid('missing comment function')): self.assertEqual(self.modify()['code'],'CONFIG_INVALID')
        self.assertEqual(self.facts(),before)
        result=start_manual_draft(self.executor,{'requirement_id':101,'expected_content_version':7,'idempotency_key':OTHER},catalog=self.catalog,clock=lambda:NOW)
        self.assertEqual(result['code'],'DRAFT_STARTED');before=self.facts();self.assertEqual(self.modify()['code'],'WORK_STATE_CONFLICT');self.assertEqual(self.facts(),before)

    def test_real_id_capacity_and_processing_scope_preserve_comment_and_current(self):
        self.make_comment();request=commands.modify_from_comment_input(self.command_payload());claim=self.executor.claim(Scope('APP-GUIDE-CMD-C05','Comment:1',KEY),request.business_input())
        before=self.facts();self.assertEqual(self.modify()['code'],'REQUEST_IN_PROGRESS');self.assertEqual(self.facts(),before);self.executor.abandon(claim)
        with self.database.transaction(write=True) as connection: connection.execute("INSERT INTO sequences VALUES ('GuideRun',?) ON CONFLICT(entity_kind) DO UPDATE SET last_value=excluded.last_value",(MAX_SAFE_INTEGER,))
        before=self.facts();self.assertEqual(self.modify()['code'],'CAPACITY_EXHAUSTED');self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
