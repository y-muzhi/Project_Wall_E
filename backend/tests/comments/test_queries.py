"""Actual file reads; explicit comment/body fixtures, not comment producer proof."""
import unittest
from unittest.mock import patch
from backend.app.comments.queries import list_comments, get_comment, get_comment_index
from backend.app.infrastructure.comment_repository import CommentRepository
from backend.app.infrastructure.database import Database
from backend.tests.comments import test_revalidate_anchors as fixtures
from backend.tests.requirements import test_create_requirement as facts_fixture
from backend.tests.documents.test_snapshot import T1


class CommentQueryTests(unittest.TestCase):
    seed=fixtures.RevalidateAnchorsTests.seed
    write_body=fixtures.RevalidateAnchorsTests.write_body
    facts=facts_fixture.CreateRequirementTests.facts

    def setUp(self):
        fixtures.RevalidateAnchorsTests.setUp(self)

    def page(self,**changes):
        return list_comments(self.database,{'requirement_id':101,**changes},catalog=self.catalog)

    def index(self,identity=101):
        return get_comment_index(self.database,identity,catalog=self.catalog)

    def test_pages_fixed_twenty_ascending_and_full_index_counts_all_live_not_just_page(self):
        for identity in range(1,46): self.seed(identity,status='RESOLVED' if identity%2==0 else 'OPEN',block_id=1 if identity%3 else 999)
        self.seed(46,deleted=T1);self.seed(47,requirement_id=102)
        before=self.facts();first=self.page();second=self.page(page=2);third=self.page(page=3)
        self.assertEqual(first['code'],'READ_OK',first);self.assertEqual([item['id'] for item in first['data']['items']],list(range(1,21)))
        self.assertEqual([item['id'] for item in second['data']['items']],list(range(21,41)));self.assertEqual([item['id'] for item in third['data']['items']],list(range(41,46)))
        index=self.index();self.assertEqual(index['code'],'READ_OK',index);data=index['data']
        self.assertEqual((data['requirement_id'],data['document_id'],data['content_version'],data['total_count'],data['open_count']),(101,201,7,45,23))
        ids=[i for i in range(1,46) if i%2 and i%3]
        self.assertEqual(data['blocks'],[{'block_id':1,'open_count':len(ids),'comment_ids':ids}]);self.assertEqual([item['id'] for item in data['comments']],list(range(1,46)))
        self.assertEqual(self.facts(),before)

    def test_current_location_is_independent_of_persistent_anchor_status_unicode_and_ambiguity(self):
        self.seed(1,kind='SELECTION',reference={'selected_text':'😀','prefix_text':'甲','suffix_text':'乙'})
        self.seed(2,kind='SELECTION',reference={'selected_text':'aa','prefix_text':'','suffix_text':''},anchor_status='ATTACHED')
        self.seed(3,kind='SELECTION',block_id=999,reference={'selected_text':'😀','prefix_text':'甲','suffix_text':'乙'},anchor_status='ATTACHED')
        with self.database.transaction(write=True) as connection: self.write_body(connection,'甲😀乙 aaa\n')
        before=self.facts();items=self.page()['data']['items'];data=self.index()['data']
        self.assertEqual(items[0]['anchor_status'],'ORPHANED');self.assertEqual(items[0]['location'],{'status':'ATTACHED','block_id':1,'start_offset':1,'end_offset':2})
        for item in items[1:]: self.assertEqual(item['anchor_status'],'ATTACHED');self.assertEqual(item['location'],{'status':'ORPHANED','block_id':None,'start_offset':None,'end_offset':None})
        self.assertEqual(data['open_count'],3);self.assertEqual(data['blocks'],[{'block_id':1,'open_count':1,'comment_ids':[1]}]);self.assertEqual(self.facts(),before)

    def test_soft_deleted_detail_remains_readable_without_current_body(self):
        self.seed(1,deleted=T1,status='RESOLVED');before=self.facts()
        detail=get_comment(self.database,1);self.assertEqual(detail['code'],'READ_OK',detail);self.assertEqual(detail['data']['deleted_at'],T1);self.assertNotIn('location',detail['data'])
        self.assertEqual(self.page()['data']['total'],0);self.assertEqual(self.index()['data']['total_count'],0);self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute('DELETE FROM requirement_documents WHERE id=201')
        before=self.facts();self.assertEqual(get_comment(self.database,1)['code'],'READ_OK')
        self.assertEqual(self.page()['code'],'INTERNAL_ERROR');self.assertEqual(self.index()['code'],'WORK_STATE_INCONSISTENT');self.assertEqual(self.facts(),before)

    def test_missing_empty_and_out_of_range_are_distinct_no_phantom_body(self):
        self.assertEqual(get_comment(self.database,999)['code'],'NOT_FOUND');self.assertEqual(self.page(requirement_id=999)['code'],'NOT_FOUND');self.assertEqual(self.index(999)['code'],'NOT_FOUND')
        self.assertEqual(self.page(page=100000)['data'],{'items':[],'page':100000,'page_size':20,'total':0,'total_pages':0})
        self.assertEqual(self.index()['data'],{'requirement_id':101,'document_id':201,'content_version':7,'total_count':0,'open_count':0,'blocks':[],'comments':[]})

    def test_strict_inputs_unknown_status_filter_or_index_pagination_reject_without_writes(self):
        before=self.facts()
        for payload in ({},{'requirement_id':True},{'requirement_id':101,'page':None},{'requirement_id':101,'page':'1'},{'requirement_id':101,'page':100001},{'requirement_id':101,'status':['OPEN']}):
            self.assertEqual(list_comments(self.database,payload)['code'],'INVALID_INPUT');self.assertEqual(self.facts(),before)
        for identity in (None,True,0,'1',{'requirement_id':101,'page':1}):
            self.assertEqual(get_comment(self.database,identity)['code'],'INVALID_INPUT');self.assertEqual(self.index(identity)['code'],'INVALID_INPUT');self.assertEqual(self.facts(),before)

    def test_malformed_anchor_duplicates_and_unnormalized_text_are_safe_not_repaired(self):
        self.seed(1,reference='{"block_markdown_snapshot":"first","block_markdown_snapshot":"second"}')
        before=self.facts()
        for result in (get_comment(self.database,1),self.page(),self.index()): self.assertEqual(result['code'],'INTERNAL_ERROR')
        self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute('DELETE FROM comments WHERE id=1')
        self.seed(1)
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE comments SET content=' bad ' WHERE id=1")
        before=self.facts();self.assertEqual(get_comment(self.database,1)['code'],'INTERNAL_ERROR');self.assertEqual(self.facts(),before)

    def test_count_items_and_locations_share_actual_wal_snapshot_even_if_body_and_comments_change(self):
        self.seed(1,kind='SELECTION',reference={'selected_text':'😀','prefix_text':'甲','suffix_text':'乙'})
        with self.database.transaction(write=True) as connection: self.write_body(connection,'甲😀乙\n')
        original=CommentRepository._count_live
        def after_count(repository,identity):
            total=original(repository,identity)
            with self.database.transaction(write=True) as connection:
                self.write_body(connection,'changed\n')
                connection.execute('UPDATE comments SET deleted_at=?,updated_at=? WHERE id=1',(T1,T1))
            return total
        with patch.object(CommentRepository,'_count_live',new=after_count): result=self.page()
        self.assertEqual(result['code'],'READ_OK',result);self.assertEqual(result['data']['total'],1)
        self.assertEqual(result['data']['items'][0]['location']['status'],'ATTACHED');self.assertEqual(self.page()['data']['total'],0)

    def test_index_current_and_complete_collection_share_snapshot_during_real_writer_commit(self):
        self.seed(1,kind='SELECTION',reference={'selected_text':'😀','prefix_text':'甲','suffix_text':'乙'})
        with self.database.transaction(write=True) as connection: self.write_body(connection,'甲😀乙\n')
        original=CommentRepository.all_live
        def before_all(repository,identity):
            with self.database.transaction(write=True) as connection: self.write_body(connection,'changed\n')
            self.seed(2)
            return original(repository,identity)
        with patch.object(CommentRepository,'all_live',new=before_all): result=self.index()
        self.assertEqual(result['code'],'READ_OK',result);self.assertEqual((result['data']['content_version'],result['data']['total_count']),(8,1))
        self.assertEqual(result['data']['comments'][0]['location']['status'],'ATTACHED')
        next_result=self.index();self.assertEqual((next_result['data']['content_version'],next_result['data']['total_count']),(9,2));self.assertEqual(next_result['data']['comments'][0]['location']['status'],'ORPHANED')

    def test_result_mapping_failure_and_uninitialized_storage_never_create_or_mutate(self):
        self.seed(1);before=self.facts()
        for name,invoke in (('list_comments_result',self.page),('get_comment_index_result',self.index),('get_comment_result',lambda:get_comment(self.database,1))):
            with patch('backend.app.comments.queries.'+name,side_effect=ValueError('private mapping failure')):
                self.assertEqual(invoke()['code'],'INTERNAL_ERROR')
            self.assertEqual(self.facts(),before)
        path=self.path.with_name('missing.sqlite');db=Database(path)
        for result in (get_comment(db,1),list_comments(db,{'requirement_id':101}),get_comment_index(db,101)): self.assertEqual(result['code'],'STORAGE_UNAVAILABLE')
        self.assertFalse(path.exists())


if __name__=='__main__': unittest.main()
