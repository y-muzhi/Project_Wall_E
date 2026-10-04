"""I27/I28/I37 actual ASGI reads with complete index and safe projections."""
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.comments.api import comment_router
from backend.app.comments import queries
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.comments import test_queries as fixtures
from backend.tests.shared import test_http_reads as http_fixtures
from backend.tests.documents.test_snapshot import T1


class HttpCommentReadTests(unittest.TestCase):
    facts=fixtures.CommentQueryTests.facts
    seed=fixtures.CommentQueryTests.seed
    write_body=fixtures.CommentQueryTests.write_body
    envelope=http_fixtures.HttpReadTests.envelope

    def setUp(self):
        fixtures.CommentQueryTests.setUp(self)
        self.app=FastAPI(redirect_slashes=False);self.app.include_router(comment_router)
        self.app.state.walle_runtime=HttpRuntime(self.database,self.catalog)
        self.client=TestClient(self.app);self.addCleanup(self.client.close)
        self.list_url='/api/v1/requirements/101/comments';self.index_url='/api/v1/requirements/101/comment-index'

    def test_three_actual_reads_full_list_detail_and_unpaged_index_are_safe_and_read_only(self):
        for identity in range(1,46): self.seed(identity,status='RESOLVED' if identity%2==0 else 'OPEN')
        self.seed(46,deleted=T1);before=self.facts()
        for name,url in (('list_comments',self.list_url),('get_comment','/api/v1/comments/46'),('get_comment_index',self.index_url)):
            with patch('backend.app.comments.queries.'+name,wraps=getattr(queries,name)) as invoked:
                value=self.envelope(self.client.get(url))
            invoked.assert_called_once()
            if name=='list_comments':
                self.assertEqual(set(value['data']),{'items'});self.assertEqual(len(value['data']['items']),20)
                self.assertEqual(value['meta']['pagination'],{'page':1,'page_size':20,'total':45,'total_pages':3})
                self.assertIn('location',value['data']['items'][0]);self.assertIn('anchor_ref',value['data']['items'][0]);self.assertNotIn('anchor_ref_json',value['data']['items'][0])
            elif name=='get_comment':
                self.assertEqual(value['data']['deleted_at'],T1);self.assertNotIn('location',value['data']);self.assertNotIn('pagination',value['meta'])
            else:
                self.assertEqual((value['data']['total_count'],value['data']['open_count'],len(value['data']['comments'])),(45,23,45))
                self.assertEqual(value['data']['blocks'][0]['comment_ids'],list(range(1,46,2)));self.assertNotIn('pagination',value['meta']);self.assertNotIn('content',value['data']['comments'][0])
            self.assertEqual(self.facts(),before)

    def test_inputs_no_status_filter_and_no_index_paging_reject_before_app(self):
        before=self.facts()
        cases=[('list_comments',self.list_url+'?status=OPEN'),('list_comments',self.list_url+'?page=01'),('list_comments',self.list_url+'?page=1&page=2'),('list_comments','/api/v1/requirements/0101/comments'),('get_comment','/api/v1/comments/01'),('get_comment','/api/v1/comments/1?page=1'),('get_comment_index',self.index_url+'?page=1'),('get_comment_index',self.index_url+'?status=OPEN')]
        for name,url in cases:
            with patch('backend.app.comments.queries.'+name,wraps=getattr(queries,name)) as invoked:
                self.envelope(self.client.get(url),422)
            invoked.assert_not_called();self.assertEqual(self.facts(),before)
        for name,url in (('list_comments',self.list_url),('get_comment','/api/v1/comments/1'),('get_comment_index',self.index_url)):
            with patch('backend.app.comments.queries.'+name,wraps=getattr(queries,name)) as invoked:
                self.envelope(self.client.request('GET',url,content='{}'),422)
            invoked.assert_not_called();self.assertEqual(self.facts(),before)

    def test_not_found_and_broken_current_have_registered_distinct_errors(self):
        self.seed(1);before=self.facts()
        for url in ('/api/v1/comments/999','/api/v1/requirements/999/comments','/api/v1/requirements/999/comment-index'):
            self.envelope(self.client.get(url),404);self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute('DELETE FROM requirement_documents WHERE id=201')
        before=self.facts();self.envelope(self.client.get('/api/v1/comments/1'))
        self.envelope(self.client.get(self.list_url),500);self.envelope(self.client.get(self.index_url),409);self.assertEqual(self.facts(),before)

    def test_location_codepoint_offsets_and_persistent_status_are_independent(self):
        self.seed(1,kind='SELECTION',reference={'selected_text':'😀','prefix_text':'甲','suffix_text':'乙'})
        with self.database.transaction(write=True) as connection: self.write_body(connection,'甲😀乙\n')
        before=self.facts();value=self.envelope(self.client.get(self.list_url));item=value['data']['items'][0]
        self.assertEqual(item['anchor_status'],'ORPHANED');self.assertEqual(item['location'],{'status':'ATTACHED','block_id':1,'start_offset':1,'end_offset':2})
        index=self.envelope(self.client.get(self.index_url));self.assertEqual(index['data']['content_version'],8);self.assertEqual(index['data']['comments'][0]['location'],item['location']);self.assertEqual(self.facts(),before)

    def test_post_query_projection_failures_and_bad_persisted_refs_do_not_leak_or_repair(self):
        self.seed(1);before=self.facts()
        for name,url in (('ListCommentsResponse',self.list_url),('GetCommentResponse','/api/v1/comments/1'),('GetCommentIndexResponse',self.index_url)):
            with patch('backend.app.comments.http_models.'+name+'.project',side_effect=ValueError('private comment error')):
                value=self.envelope(self.client.get(url),500)
            self.assertNotIn('private comment error',str(value));self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute('DELETE FROM comments')
        self.seed(1,reference='{"prompt":"private anchor"}');before=self.facts()
        for url in (self.list_url,self.index_url,'/api/v1/comments/1'):
            value=self.envelope(self.client.get(url),500);self.assertNotIn('private anchor',str(value));self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
