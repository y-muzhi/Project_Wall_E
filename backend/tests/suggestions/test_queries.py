"""I20 real aggregate reads; explicit historical MODIFY/Suggestion fixtures."""
import json
import unittest
from unittest.mock import patch
from backend.app.infrastructure.batch_repository import BatchRepository
from backend.app.infrastructure.database import Database
from backend.app.suggestions.queries import get_batch
from backend.tests.guide import test_recovery as fixtures
from backend.tests.guide import test_queries as source_fixtures


class BatchQueryTests(unittest.TestCase):
    facts=fixtures.RecoveryTests.facts
    payload=fixtures.RecoveryTests.payload
    create=fixtures.RecoveryTests.create
    row=fixtures.RecoveryTests.row
    terminal=fixtures.RecoveryTests.terminal
    batch_fixture=fixtures.RecoveryTests.batch_fixture
    protocol_run_fixture=source_fixtures.GuideQueryTests.protocol_run_fixture

    def setUp(self):
        fixtures.RecoveryTests.setUp(self)
        self.batch_fixture()

    def read(self,identity=10):
        return get_batch(self.database,identity,catalog=self.catalog)

    def add_suggestion(self,identity,order,status='PENDING',operation='REPLACE_BLOCK',**changes):
        value=self.row('suggestions',10)
        value.update(id=identity,order_no=order,status=status,patch_operation=operation,decided_at=None if status=='PENDING' else self.at,user_edited_content='edited Markdown' if status=='EDITED' else None)
        if operation=='REPLACE_TABLE_ROW':
            value.update(selector_json=json.dumps({'key_column_index':0,'key_value':'key'}),proposed_markdown=None,proposed_data_json=json.dumps({'cells':['key','value']}))
        elif operation=='DELETE_BLOCK': value.update(proposed_markdown=None)
        value.update(changes)
        with self.database.transaction(write=True) as connection:
            connection.execute('INSERT INTO suggestions('+','.join(value)+') VALUES ('+','.join('?' for _ in value)+')',tuple(value.values()))
            connection.execute("INSERT INTO sequences VALUES ('Suggestion',?) ON CONFLICT(entity_kind) DO UPDATE SET last_value=max(last_value,excluded.last_value)",(identity,))

    def test_complete_aggregate_over_twenty_stable_order_counts_no_paging_or_writes(self):
        for identity in range(11,55): self.add_suggestion(identity,identity-9,status=('ACCEPTED','REJECTED','EDITED','PENDING')[identity%4])
        before=self.facts();result=self.read();self.assertEqual(result['code'],'READ_OK',result);data=result['data']
        self.assertEqual([item['id'] for item in data['suggestions']],list(range(10,55)))
        expected={'total':45,'pending':12,'accepted':11,'rejected':11,'edited':11}
        self.assertEqual(data['counts'],expected);self.assertNotIn('page',data);self.assertEqual(self.facts(),before)

    def test_decoded_row_selector_cells_and_delete_payload_follow_operation(self):
        self.add_suggestion(11,2,operation='REPLACE_TABLE_ROW');self.add_suggestion(12,3,operation='DELETE_BLOCK',status='REJECTED')
        result=self.read();self.assertEqual(result['code'],'READ_OK',result);row=result['data']['suggestions'][1]
        self.assertEqual(row['target_ref'],{'block_id':1});self.assertEqual(row['selector'],{'key_column_index':0,'key_value':'key'});self.assertEqual(row['proposed_data'],{'cells':['key','value']})
        self.assertIsNone(row['proposed_markdown']);self.assertNotIn('selector_json',row)

    def test_terminal_batch_no_change_changed_and_discarded_read_without_current_body(self):
        with self.database.transaction(write=True) as connection: connection.execute('DELETE FROM requirement_documents')
        for status,completion,applied in (('DISCARDED',None,None),('COMPLETED','NO_CHANGE',None),('COMPLETED','CHANGES_APPLIED',2)):
            with self.database.transaction(write=True) as connection:
                connection.execute('UPDATE suggestion_batches SET status=?,completion_result=?,applied_content_version=?,completed_at=? WHERE id=10',(status,completion,applied,self.at))
            before=self.facts();result=self.read();self.assertEqual(result['code'],'READ_OK',result)
            self.assertEqual(result['data']['status'],status);self.assertEqual(result['data']['applied_content_version'],applied);self.assertEqual(self.facts(),before)

    def test_latest_validation_failure_is_projected_without_revalidation_or_repair(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE suggestions SET validation_status='INVALID',validation_error='目标已变化' WHERE id=10")
            connection.execute("UPDATE suggestion_batches SET error_message='建议无法应用' WHERE id=10")
        before=self.facts();result=self.read();self.assertEqual(result['code'],'READ_OK',result)
        self.assertEqual(result['data']['suggestions'][0]['validation_error'],'目标已变化');self.assertEqual(result['data']['error_message'],'建议无法应用');self.assertEqual(self.facts(),before)

    def test_empty_and_over_capacity_batches_are_corruption_not_successful_truncation(self):
        for identity in range(11,111): self.add_suggestion(identity,identity-9)
        before=self.facts();self.assertEqual(self.read()['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute('DELETE FROM suggestions')
        before=self.facts();self.assertEqual(self.read()['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)

    def test_structured_duplicate_keys_source_and_metadata_corruption_are_safe(self):
        self.add_suggestion(11,2,target_ref_json='{"block_id":1,"block_id":2}')
        before=self.facts();self.assertEqual(self.read()['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute('DELETE FROM suggestions WHERE id=11');connection.execute("UPDATE guide_runs SET status='FAILED',error_code='MODEL_ERROR',error_message='safe fixture failure' WHERE id=10")
        before=self.facts();self.assertEqual(self.read()['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)

    def test_same_snapshot_batch_metadata_and_suggestions_during_actual_writer_commit(self):
        original=BatchRepository.suggestions
        def before_items(repository,identity):
            with self.database.transaction(write=True) as connection:
                connection.execute("UPDATE suggestions SET status='ACCEPTED',decided_at=? WHERE id=10",(self.at,))
                connection.execute("UPDATE suggestion_batches SET status='DISCARDED',completed_at=? WHERE id=10",(self.at,))
            return original(repository,identity)
        with patch.object(BatchRepository,'suggestions',new=before_items): result=self.read()
        self.assertEqual(result['code'],'READ_OK',result);self.assertEqual((result['data']['status'],result['data']['counts']['pending']),('PENDING',1))
        result=self.read();self.assertEqual((result['data']['status'],result['data']['counts']['accepted']),('DISCARDED',1))

    def test_historical_deleted_resolved_comment_source_and_completed_review_are_retained(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE suggestion_batches SET status='DISCARDED',completed_at=? WHERE id=10",(self.at,))
            connection.execute("INSERT INTO comments VALUES (70,?,'historical comment','BLOCK',1,'{\"block_markdown_snapshot\":\"original\"}','ORPHANED','RESOLVED',?,?,?,?)",(self.req,self.at,self.at,self.at,self.at))
        self.batch_fixture(11,parent_id=11,source_type='COMMENT',source_id=70)
        result=self.read(11);self.assertEqual(result['code'],'READ_OK',result);self.assertEqual((result['data']['source_type'],result['data']['source_id']),('COMMENT',70))
        self.protocol_run_fixture(20,action='REVIEW')
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE suggestion_batches SET status='DISCARDED',completed_at=? WHERE id=11",(self.at,))
        self.batch_fixture(12,parent_id=12,source_type='REVIEW_RESULT',source_id=20)
        self.assertEqual(self.read(12)['code'],'READ_OK')
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE guide_runs SET status='FAILED',error_code='MODEL_ERROR',error_message='safe historical failure' WHERE id=20")
        before=self.facts();self.assertEqual(self.read(12)['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)

    def test_invalid_ids_missing_storage_and_result_mapping_do_not_mutate(self):
        before=self.facts()
        for value in (None,True,0,'10',{},9007199254740992): self.assertEqual(self.read(value)['code'],'INVALID_INPUT');self.assertEqual(self.facts(),before)
        self.assertEqual(self.read(999)['code'],'NOT_FOUND');self.assertEqual(self.facts(),before)
        with patch('backend.app.suggestions.queries.get_batch_result',side_effect=ValueError('private result failure')):
            self.assertEqual(self.read()['code'],'INTERNAL_ERROR')
        self.assertEqual(self.facts(),before);path=self.path.with_name('missing.sqlite')
        self.assertEqual(get_batch(Database(path),10)['code'],'STORAGE_UNAVAILABLE');self.assertFalse(path.exists())


if __name__=='__main__': unittest.main()
