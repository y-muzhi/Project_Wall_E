"""C02 actual atomic adoption, complete source proofs and comment revalidation."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import timedelta
import json
import sqlite3
import unittest
from unittest.mock import patch
from backend.app.infrastructure.database import Database, CommitOutcomeUnknown
from backend.app.infrastructure.idempotency import Idempotency
from backend.app.documents.commands import start_manual_draft
from backend.app.documents.snapshot import create_snapshot, Provenance, validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.documents.scopes import resolve_scope
from backend.app.documents.scopes import ScopeInvalid
from backend.app.documents.markdown import parse_markdown
from backend.app.guide.commands import recover_runs
from backend.app.suggestions import commands
from backend.tests.suggestions import test_decision as fixtures
from backend.tests.requirements import test_create_requirement as creation

KEY2=fixtures.KEY2


class CompleteTests(unittest.TestCase):
    facts=fixtures.DecisionTests.facts
    payload=fixtures.DecisionTests.payload
    create=fixtures.DecisionTests.create
    row=fixtures.DecisionTests.row
    terminal=fixtures.DecisionTests.terminal
    batch_fixture=fixtures.DecisionTests.batch_fixture
    add_suggestion=fixtures.DecisionTests.add_suggestion
    decide=fixtures.DecisionTests.decide
    discard=fixtures.DecisionTests.discard

    def setUp(self): fixtures.DecisionTests.setUp(self)

    def complete(self,**changes):
        return commands.complete_batch(self.executor,{'batch_id':10,'expected_content_version':1,'idempotency_key':creation.KEY,**changes},catalog=self.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=2))

    def comment_fixture(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("INSERT INTO comments VALUES (70,?,'historical comment','BLOCK',1,?,'ATTACHED','OPEN',NULL,NULL,?,?)",(self.req,json.dumps({'block_markdown_snapshot':'explicit historical anchor'}),self.at,self.at))

    def body_fixture(self,text):
        # Explicit historical source fixture; production adoption is the actual APP.
        with self.database.transaction(write=True) as connection:
            sources=DocumentSources(connection,self.req,self.catalog)
            snapshot=create_snapshot(text,Provenance('SYSTEM','TEMPLATE',None),self.at,sources)
            connection.execute('UPDATE requirement_documents SET markdown_content=?,block_state_json=?',(text,snapshot.state_json))
            connection.execute('DELETE FROM suggestions')
        return snapshot

    def test_accepted_updates_current_once_actual_batch_source_and_all_comment_anchors(self):
        self.comment_fixture();self.assertEqual(self.decide()['code'],'SUGGESTION_DECIDED');original=self.row('requirement_documents',self.created['current_document_id'])
        result=self.complete();self.assertEqual(result['code'],'BATCH_APPLIED',result);data=result['data']
        self.assertEqual((data['batch']['status'],data['batch']['completion_result'],data['batch']['applied_content_version']),('COMPLETED','CHANGES_APPLIED',2))
        current=data['current_document'];self.assertEqual(current['id'],original['id']);self.assertEqual(current['content_version'],2)
        self.assertTrue(current['markdown_content'].startswith('# replacement'))
        with self.database.transaction() as connection:
            snapshot=validate_snapshot(current['markdown_content'],current['block_state_json'],DocumentSources(connection,self.req,self.catalog))
            old=json.loads(original['block_state_json'])['blocks'][0]
            new=snapshot.by_id[1][1];self.assertEqual(new['created_at'],old['created_at']);self.assertEqual((new['last_modified_by_type'],new['last_modified_source_type'],new['last_modified_source_id']),('AI','SUGGESTION_BATCH',10))
            self.assertEqual(connection.execute('SELECT count(*) FROM revisions').fetchone()[0],1)
        self.assertEqual(self.row('requirements',self.req)['document_work_state'],'IDLE');self.assertEqual(self.row('comments',70)['status'],'OPEN')

    def test_edited_source_is_user_and_preserves_creation_metadata(self):
        self.assertEqual(self.decide('EDITED',edited_content='# user replacement')['code'],'SUGGESTION_DECIDED')
        result=self.complete();self.assertEqual(result['code'],'BATCH_APPLIED',result)
        block=result['data']['current_document']['block_state_json']['blocks'][0]
        self.assertEqual((block['created_by_type'],block['last_modified_by_type'],block['last_modified_source_id']),('SYSTEM','USER',10))

    def test_all_rejected_changes_only_batch_and_owner_without_current_or_c06(self):
        self.comment_fixture();self.decide('REJECTED');current=self.row('requirement_documents',self.created['current_document_id']);comment=self.row('comments',70)
        with patch('backend.app.suggestions.commands.revalidate_anchors',side_effect=AssertionError('No-change must not revalidate comments')):
            result=self.complete()
        self.assertEqual(result['code'],'BATCH_NO_CHANGE',result);self.assertEqual(result['data']['current_document']['content_version'],1)
        self.assertEqual(result['data']['batch']['completion_result'],'NO_CHANGE');self.assertIsNone(result['data']['batch']['applied_content_version'])
        self.assertEqual(self.row('requirement_documents',current['id']),current);self.assertEqual(self.row('comments',70),comment)

    def test_net_identical_accepted_patch_keeps_raw_pair_metadata_version_and_comments(self):
        original=self.row('suggestions',10)
        self.add_suggestion(11,2,proposed_markdown=original['original_content'])
        with self.database.transaction(write=True) as connection: connection.execute('DELETE FROM suggestions WHERE id=10')
        self.decide(suggestion_id=11);current=self.row('requirement_documents',self.created['current_document_id'])
        result=self.complete();self.assertEqual(result['code'],'BATCH_NO_CHANGE',result);self.assertEqual(self.row('requirement_documents',current['id']),current)

    def test_delete_anchor_orphans_comment_without_auto_resolve(self):
        self.comment_fixture();item=self.row('suggestions',10)
        self.add_suggestion(11,2,operation='DELETE_BLOCK',original_content=item['original_content'])
        with self.database.transaction(write=True) as connection: connection.execute('DELETE FROM suggestions WHERE id=10')
        self.decide(suggestion_id=11)
        result=self.complete();self.assertEqual(result['code'],'BATCH_APPLIED',result)
        self.assertEqual((self.row('comments',70)['anchor_status'],self.row('comments',70)['status']),('ORPHANED','OPEN'))
        self.assertNotIn(1,[block['block_id'] for block in result['data']['current_document']['block_state_json']['blocks']])

    def test_three_versions_pending_and_owned_state_are_checked_in_actual_write_transaction(self):
        before=self.facts();self.assertEqual(self.complete()['code'],'BATCH_PENDING');self.assertEqual(self.facts(),before)
        self.decide();before=self.facts();self.assertEqual(self.complete(expected_content_version=2)['code'],'CONTENT_VERSION_CONFLICT');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute('UPDATE requirement_documents SET content_version=2')
        before=self.facts();self.assertEqual(self.complete(expected_content_version=2)['code'],'CONTENT_VERSION_CONFLICT');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute('UPDATE requirements SET active_operation_id=999')
        before=self.facts();self.assertEqual(self.complete()['code'],'WORK_STATE_INCONSISTENT');self.assertEqual(self.facts(),before)

    def test_stale_items_safe_complete_errors_and_no_partial_validation_or_body_write(self):
        self.add_suggestion(11,2,target_ref_json='{"block_id":999}',original_content='private stale text')
        self.decide();self.decide(suggestion_id=11)
        before=self.facts();result=self.complete();self.assertEqual(result['code'],'TARGET_STALE',result)
        self.assertEqual(result['details']['suggestion_errors'][0]['suggestion_id'],11);self.assertNotIn('private stale text',str(result));self.assertEqual(self.facts(),before)

    def test_conflicting_effective_patches_and_invalid_frozen_authority_roll_back_everything(self):
        self.add_suggestion(11,2);self.decide();self.decide(suggestion_id=11)
        before=self.facts();self.assertEqual(self.complete()['code'],'PATCH_INVALID');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE suggestions SET status='REJECTED' WHERE id=11")
        with patch('backend.app.suggestions.commands.restore_authority',side_effect=ScopeInvalid('private grant failure')):
            before=self.facts();self.assertEqual(self.complete()['code'],'TARGET_STALE');self.assertEqual(self.facts(),before)

    def test_two_row_replacements_use_original_keys_and_preserve_table_header_plain_cells(self):
        snapshot=self.body_fixture('| 键 | 值 |\n| --- | --- |\n| A | 一 |\n| B | 二 |\n')
        from backend.app.documents.tables import table_model
        table=table_model(snapshot.parsed.blocks[0])
        # add_suggestion copies an actual complete stored row; retain that shape.
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE suggestion_batches SET status='DISCARDED',completed_at=? WHERE id=10",(self.at,))
        self.batch_fixture(11,parent_id=11,authority_snapshot=snapshot)
        result=recover_runs(self.database,{'recovery_reason':'STARTUP','live_run_ids':set(),'operation_time':self.at},process_lock=self.lock)
        self.assertEqual(result['code'],'RECOVERED',result)
        template=dict(id=12,batch_id=11,order_no=1,title='row',explanation='row explanation',impact=None,patch_operation='REPLACE_TABLE_ROW',target_ref_json='{"block_id":1}',selector_json=json.dumps({'key_column_index':0,'key_value':'A'}),proposed_markdown=None,proposed_data_json=json.dumps({'cells':['B','AI改']}),original_content=table.rows[0].markdown,status='ACCEPTED',user_edited_content=None,validation_status='VALID',validation_error=None,created_at=self.at,decided_at=self.at,updated_at=self.at)
        with self.database.transaction(write=True) as connection:
            connection.execute('DELETE FROM suggestions WHERE id=11')
            connection.execute('INSERT INTO suggestions('+','.join(template)+') VALUES ('+','.join('?' for _ in template)+')',tuple(template.values()))
        # add_suggestion copies fixture id10, so insert the second row directly.
        template.update(id=13,order_no=2,status='EDITED',selector_json=json.dumps({'key_column_index':0,'key_value':'B'}),original_content=table.rows[1].markdown,user_edited_content='{"cells":["A","用户改"]}')
        with self.database.transaction(write=True) as connection:
            connection.execute('INSERT INTO suggestions('+','.join(template)+') VALUES ('+','.join('?' for _ in template)+')',tuple(template.values()))
        result=self.complete(batch_id=11)
        self.assertEqual(result['code'],'BATCH_APPLIED',result)
        parsed=parse_markdown(result['data']['current_document']['markdown_content'])
        self.assertEqual([row.cells for row in table_model(parsed.blocks[0]).rows],[('B','AI改'),('A','用户改')])
        self.assertEqual(result['data']['current_document']['block_state_json']['blocks'][0]['last_modified_by_type'],'USER')

    def test_actual_body_comment_batch_root_idempotency_and_mapping_failures_all_roll_back(self):
        # DELETE makes C06 perform an actual anchor update, allowing a real SQL fault.
        self.comment_fixture();item=self.row('suggestions',10);self.add_suggestion(11,2,operation='DELETE_BLOCK',original_content=item['original_content'])
        with self.database.transaction(write=True) as connection: connection.execute('DELETE FROM suggestions WHERE id=10')
        self.decide(suggestion_id=11)
        for table,predicate in (('requirement_documents',''),('comments',''),('suggestion_batches',''),('requirements',''),('idempotency_records',"WHEN NEW.status='SUCCEEDED'")):
            with closing(sqlite3.connect(self.path)) as connection:
                connection.execute(f"CREATE TRIGGER complete_fault AFTER UPDATE ON {table} {predicate} BEGIN SELECT RAISE(ABORT,'actual completion fault'); END");connection.commit()
            before=self.facts();self.assertEqual(self.complete()['code'],'STORAGE_UNAVAILABLE');self.assertEqual(self.facts(),before)
            with closing(sqlite3.connect(self.path)) as connection: connection.execute('DROP TRIGGER complete_fault');connection.commit()
        before=self.facts()
        with patch('backend.app.suggestions.commands.complete_batch_result',side_effect=ValueError('after all actual adoption writes')): self.assertEqual(self.complete()['code'],'INTERNAL_ERROR')
        self.assertEqual(self.facts(),before)

    def test_commit_lost_ack_original_replay_does_not_touch_later_real_manual_session(self):
        self.decide()
        class LostAck(Database):
            writes=0
            @contextmanager
            def transaction(database,*,write=False):
                with super().transaction(write=write) as connection: yield connection
                if write:
                    database.writes+=1
                    if database.writes==2: raise CommitOutcomeUnknown('after actual complete commit')
        executor=Idempotency(LostAck(self.path),self.lock,clock=lambda:creation.INSTANT)
        result=commands.complete_batch(executor,{'batch_id':10,'expected_content_version':1,'idempotency_key':creation.KEY},catalog=self.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=2))
        self.assertEqual(result['code'],'STORAGE_UNAVAILABLE');first=self.complete();self.assertEqual(first['code'],'BATCH_APPLIED')
        started=start_manual_draft(self.executor,{'requirement_id':self.req,'expected_content_version':2,'idempotency_key':creation.OTHER},catalog=self.catalog,clock=lambda:creation.INSTANT+timedelta(seconds=3))
        self.assertEqual(started['code'],'DRAFT_STARTED',started);before=self.facts();self.assertEqual(self.complete(),first);self.assertEqual(self.facts(),before)
        self.assertEqual(self.complete(idempotency_key=creation.OTHER)['code'],'STATE_CONFLICT');self.assertEqual(self.facts(),before)

    def test_two_actual_complete_writers_increment_once(self):
        self.decide()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=[future.result() for future in (pool.submit(self.complete),pool.submit(self.complete,idempotency_key=creation.OTHER))]
        self.assertCountEqual([value['code'] for value in results],['BATCH_APPLIED','STATE_CONFLICT'])
        self.assertEqual(self.row('requirement_documents',self.created['current_document_id'])['content_version'],2)

    def test_invalid_request_missing_batch_and_clock_regression_preserve_facts(self):
        before=self.facts()
        for payload in ({},{'batch_id':10,'expected_content_version':True,'idempotency_key':creation.KEY},{'batch_id':10,'expected_content_version':1,'idempotency_key':creation.KEY,'extra':1}):
            self.assertEqual(commands.complete_batch(self.executor,payload)['code'],'INVALID_INPUT');self.assertEqual(self.facts(),before)
        self.assertEqual(self.complete(batch_id=999)['code'],'NOT_FOUND');self.assertEqual(self.facts(),before)
        self.decide();before=self.facts()
        result=commands.complete_batch(self.executor,{'batch_id':10,'expected_content_version':1,'idempotency_key':creation.KEY},catalog=self.catalog,clock=lambda:creation.INSTANT)
        self.assertEqual(result['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)

    def test_insert_allocates_from_actual_block_high_water_and_preserves_anchor_identity(self):
        current=self.row('requirement_documents',self.created['current_document_id']);old=json.loads(current['block_state_json']);target=parse_markdown(current['markdown_content']).blocks[2]
        self.add_suggestion(11,2,operation='INSERT_AFTER',target_ref_json='{"block_id":3}',original_content=target.markdown,proposed_markdown='new inserted paragraph\n')
        self.decide('REJECTED');self.decide(suggestion_id=11)
        result=self.complete();self.assertEqual(result['code'],'BATCH_APPLIED',result)
        state=result['data']['current_document']['block_state_json'];new_id=old['next_block_id'];ids=[item['block_id'] for item in state['blocks']]
        self.assertEqual(ids[ids.index(3)+1],new_id);self.assertEqual(state['next_block_id'],new_id+1)
        self.assertEqual(next(item for item in state['blocks'] if item['block_id']==new_id)['created_source_id'],10)

    def test_real_maximum_current_version_cannot_increment_and_entire_batch_remains_pending(self):
        from backend.app.shared.validation import MAX_SAFE_INTEGER
        with self.database.transaction(write=True) as connection:
            connection.execute('UPDATE requirement_documents SET content_version=?',(MAX_SAFE_INTEGER,))
            connection.execute("UPDATE suggestion_batches SET status='DISCARDED',completed_at=? WHERE id=10",(self.at,))
        self.batch_fixture(11,parent_id=11)
        result=recover_runs(self.database,{'recovery_reason':'STARTUP','live_run_ids':set(),'operation_time':self.at},process_lock=self.lock)
        self.assertEqual(result['code'],'RECOVERED',result);self.decide(suggestion_id=11)
        before=self.facts();self.assertEqual(self.complete(batch_id=11,expected_content_version=MAX_SAFE_INTEGER)['code'],'CAPACITY_EXHAUSTED');self.assertEqual(self.facts(),before)

    def test_complete_discard_competing_actual_writers_have_one_terminal_winner(self):
        self.decide()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=[future.result() for future in (pool.submit(self.complete),pool.submit(self.discard))]
        self.assertCountEqual([value['code'] for value in results if value['code']=='STATE_CONFLICT'],['STATE_CONFLICT'])
        self.assertIn(self.row('suggestion_batches',10)['status'],('COMPLETED','DISCARDED'))


if __name__=='__main__': unittest.main()
