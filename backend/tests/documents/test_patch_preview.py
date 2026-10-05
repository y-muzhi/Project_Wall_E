"""Pure composition over real SQLite-validated originals, no fake future source.

Historical MODIFY/batch rows in the fixture are explicit stored diagnostics,
not a claim that a model or C07 produced them. Preview never saves a Snapshot.
"""
from copy import deepcopy
import json
import unittest

from backend.app.documents.patch_application import Adoption, apply_adoptions, preview_patches
from backend.app.documents.patch_errors import PatchInvalid, TargetStale
from backend.app.documents.scopes import resolve_scope, restore_authority
from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.documents.tables import table_model
from backend.app.infrastructure.identifiers import CapacityExhausted
from backend.app.shared.validation import MAX_SAFE_INTEGER
from backend.tests.suggestions import test_complete as fixtures
from backend.tests.documents.test_patch_validation import patch


class PatchPreviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.CompleteTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)

    def original(self):
        fixture=self.fixture
        with fixture.database.transaction() as connection:
            row=connection.execute("SELECT * FROM requirement_documents WHERE requirement_id=? AND document_type='CURRENT'",(fixture.req,)).fetchone()
            snapshot=validate_snapshot(row['markdown_content'],json.loads(row['block_state_json']),DocumentSources(connection,fixture.req,fixture.catalog))
            parent=connection.execute('SELECT * FROM guide_runs WHERE id=10').fetchone()
            authority=restore_authority(snapshot,'MODIFY',parent['scope_type'],None,parent['allowed_targets_json'])
        return snapshot,authority

    def check_preview_and_real_source_application(self,snapshot,authority,patches):
        before=self.fixture.facts();state=deepcopy(snapshot.state)
        preview=preview_patches(snapshot,patches,authority)
        self.assertEqual(self.fixture.facts(),before);self.assertEqual(snapshot.state,state)
        self.assertFalse(hasattr(preview,'state'));self.assertFalse(hasattr(preview,'provenance'))
        with self.fixture.database.transaction() as connection:
            adopted=apply_adoptions(snapshot,[Adoption(index+1,item,'ACCEPTED') for index,item in enumerate(patches)],authority,
                10,'2026-10-04T08:00:01.000Z',DocumentSources(connection,self.fixture.req,self.fixture.catalog))
        self.assertEqual((preview.markdown,preview.block_ids,preview.next_block_id),
            (adopted.parsed.markdown,tuple(adopted.by_id),adopted.next_block_id))
        self.assertEqual(self.fixture.facts(),before)
        return preview

    def test_preview_matches_actual_complete_current_without_persisting_any_preliminary_fact(self):
        from backend.app.suggestions.contracts import suggestion_from_row,stored_patch
        snapshot,authority=self.original()
        value=stored_patch(suggestion_from_row(self.fixture.row('suggestions',10),protocol=self.fixture.catalog.freeze('MODIFY','USER_INSTRUCTION')))
        before=self.fixture.facts();preview=preview_patches(snapshot,[value],authority)
        self.assertEqual(self.fixture.facts(),before)
        self.assertEqual(self.fixture.decide()['code'],'SUGGESTION_DECIDED')
        result=self.fixture.complete();self.assertEqual(result['code'],'BATCH_APPLIED',result)
        current=result['data']['current_document']
        self.assertEqual(preview.markdown,current['markdown_content'])
        self.assertEqual(preview.block_ids,tuple(item['block_id'] for item in current['block_state_json']['blocks']))
        self.assertEqual(preview.next_block_id,current['block_state_json']['next_block_id'])
        self.assertEqual(current['block_state_json']['blocks'][0]['last_modified_source_id'],10)

    def test_replace_insert_before_after_delete_compose_with_actual_baseline_and_no_future_source(self):
        snapshot,authority=self.original()
        preview=self.check_preview_and_real_source_application(snapshot,authority,[
            patch(snapshot,3,'INSERT_BEFORE','前方事实😀\n'),patch(snapshot,3,'INSERT_AFTER','后方事实😀\n'),
            patch(snapshot,3,'REPLACE_BLOCK','替换事实😀\n'),patch(snapshot,5,'DELETE_BLOCK',None)])
        self.assertEqual(preview.next_block_id,snapshot.next_block_id+2)
        self.assertNotIn(5,preview.block_ids)
        position=preview.block_ids.index(3)
        self.assertEqual(preview.block_ids[position-1],snapshot.next_block_id)
        self.assertEqual(preview.block_ids[position+1],snapshot.next_block_id+1)

    def test_net_identical_keeps_original_raw_pair_and_high_water(self):
        snapshot,authority=self.original()
        preview=self.check_preview_and_real_source_application(snapshot,authority,[patch(snapshot,3,proposed=snapshot.by_id[3][0].markdown)])
        self.assertEqual((preview.markdown,preview.block_ids,preview.next_block_id),
            (snapshot.parsed.markdown,tuple(snapshot.by_id),snapshot.next_block_id))

    def test_invalid_late_patch_conflicting_targets_empty_or_over_capacity_bundle_leave_database_unchanged(self):
        snapshot,authority=self.original();before=self.fixture.facts()
        for values,error in (([],PatchInvalid),([patch(snapshot,3)]*101,PatchInvalid),
            ([patch(snapshot,3),patch(snapshot,3)],PatchInvalid),
            ([patch(snapshot,3),patch(snapshot,5,original='stale source')],TargetStale),
            ([patch(snapshot,3,'DELETE_BLOCK',None),patch(snapshot,3,'INSERT_AFTER','new')],PatchInvalid)):
            with self.assertRaises(error):preview_patches(snapshot,values,authority)
            self.assertEqual(self.fixture.facts(),before)

    def test_standalone_valid_unclosed_fence_cannot_swallow_original_neighbors(self):
        snapshot,authority=self.original();before=self.fixture.facts()
        with self.assertRaises(PatchInvalid):preview_patches(snapshot,[patch(snapshot,3,proposed='```\n代码\n')],authority)
        self.assertEqual(self.fixture.facts(),before)

    def test_selection_permission_and_outside_source_bytes_still_proved(self):
        snapshot,_=self.original();identity=3;old=snapshot.by_id[identity][0]
        selected=old.plain_text[:min(3,len(old.plain_text))]
        authority=resolve_scope(snapshot,'MODIFY','SELECTION',{'block_id':identity,'selected_text':selected,'prefix_text':'','suffix_text':old.plain_text[len(selected):len(selected)+100]})
        # The untouched whole block is valid even for a narrow selection.
        preview=preview_patches(snapshot,[patch(snapshot,identity,proposed=old.markdown)],authority)
        self.assertEqual(preview.markdown,snapshot.parsed.markdown)
        before=self.fixture.facts()
        with self.assertRaises(TargetStale):preview_patches(snapshot,[patch(snapshot,5)],authority)
        with self.assertRaises(PatchInvalid):preview_patches(snapshot,[patch(snapshot,identity,proposed='完全替换越界。')],authority)
        self.assertEqual(self.fixture.facts(),before)

    def test_table_key_swap_uses_whole_original_table_and_rejects_ambiguous_baseline_keys(self):
        snapshot=self.fixture.body_fixture('| 键 | 值 |\n| --- | --- |\n| A | 一 |\n| B | 二 |\n')
        authority=resolve_scope(snapshot,'MODIFY','DOCUMENT');table=table_model(snapshot.parsed.blocks[0])
        values=[patch(snapshot,1,'REPLACE_TABLE_ROW',None,{'key_column_index':0,'key_value':row.cells[0]},
            {'cells':cells},row.markdown) for row,cells in zip(table.rows,(['B','改一'],['A','改二']))]
        before=self.fixture.facts();preview=preview_patches(snapshot,values,authority)
        self.assertEqual(self.fixture.facts(),before)
        from backend.app.documents.markdown import parse_markdown
        self.assertEqual([row.cells for row in table_model(parse_markdown(preview.markdown).blocks[0]).rows],[('B','改一'),('A','改二')])
        self.assertTrue(preview.markdown.startswith('| 键 | 值 |\n| --- | --- |\n'))
        # The approved selector requires a unique key in the actual baseline;
        # it does not impose a new uniqueness constraint on all resulting rows.
        duplicated=preview_patches(snapshot,values[:1],authority)
        ambiguous=self.fixture.body_fixture(duplicated.markdown)
        ambiguous_authority=resolve_scope(ambiguous,'MODIFY','DOCUMENT')
        ambiguous_row=table_model(ambiguous.parsed.blocks[0]).rows[0]
        with self.assertRaises(TargetStale):
            preview_patches(ambiguous,[patch(ambiguous,1,'REPLACE_TABLE_ROW',None,
                {'key_column_index':0,'key_value':'B'},{'cells':['C','新值']},ambiguous_row.markdown)],ambiguous_authority)
        # body_fixture is an explicit new stored diagnostic baseline.
        before=self.fixture.facts()
        self.assertEqual(self.fixture.facts(),before)

    def test_real_high_water_exhaustion_refuses_preview_without_allocating_any_persistent_identity(self):
        current=self.fixture.row('requirement_documents',self.fixture.created['current_document_id'])
        state=json.loads(current['block_state_json']);state['next_block_id']=MAX_SAFE_INTEGER
        with self.fixture.database.transaction(write=True) as connection:
            connection.execute('UPDATE requirement_documents SET block_state_json=? WHERE id=?',(json.dumps(state),current['id']))
        snapshot,authority=self.original();before=self.fixture.facts()
        with self.assertRaises(CapacityExhausted):preview_patches(snapshot,[patch(snapshot,3,'INSERT_AFTER','新事实')],authority)
        self.assertEqual(self.fixture.facts(),before)
