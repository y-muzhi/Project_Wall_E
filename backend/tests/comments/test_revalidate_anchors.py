"""All-comment reanchoring in real caller transactions, without independent commits."""
from contextlib import closing
import json
import sqlite3
import unittest
from unittest.mock import patch
from backend.app.comments.commands import revalidate_anchors
from backend.app.documents.snapshot import create_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.comment_repository import CommentRepository
from backend.tests.documents import test_commands as fixtures
from backend.tests.documents.test_snapshot import TEMPLATE, T0, T1
from backend.tests.infrastructure.test_database import insert_requirement


class RevalidateAnchorsTests(unittest.TestCase):
    def setUp(self):
        fixtures.DraftCommandTests.setUp(self)
        self.addCleanup(fixtures.DraftCommandTests.tearDown, self)
        with self.database.transaction(write=True) as connection:
            insert_requirement(connection, 102, 'REQ000002')

    def pair(self, snapshot=None):
        snapshot = self.original if snapshot is None else snapshot
        return {'requirement_id': 101, 'new_document': {'markdown_content': snapshot.parsed.markdown, 'block_state_json': snapshot.state}}

    def seed(self, identity, *, requirement_id=101, block_id=1, reference=None, status='OPEN', anchor_status='ORPHANED', deleted=None, kind='BLOCK'):
        if reference is None:
            reference = {'block_markdown_snapshot': 'immutable original body'}
        with self.database.transaction(write=True) as connection:
            connection.execute('INSERT INTO comments VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', (identity, requirement_id, 'comment '+str(identity), kind, block_id, json.dumps(reference, ensure_ascii=True) if not isinstance(reference,str) else reference, anchor_status, status, T1 if status=='RESOLVED' else None, deleted, T0, T1))

    def rows(self):
        with self.database.transaction() as connection:
            return {row['id']:dict(row) for row in connection.execute('SELECT * FROM comments ORDER BY id')}

    def test_all_open_and_resolved_beyond_page_only_anchor_status_changes(self):
        for identity in range(1,46):
            self.seed(identity, status='RESOLVED' if identity%2==0 else 'OPEN', block_id=1 if identity%3 else 999)
        self.seed(46, deleted=T1, anchor_status='ATTACHED', block_id=999)
        self.seed(47, requirement_id=102, anchor_status='ATTACHED', block_id=999)
        before=self.rows()
        with self.database.transaction(write=True) as connection:
            result=revalidate_anchors(connection,self.pair(),catalog=self.catalog)
            self.assertTrue(connection.in_transaction)
        self.assertEqual(result, {'code':'ANCHORS_UPDATED','data':{'requirement_id':101,'document_id':201,'content_version':7,'attached_comment_ids':[i for i in range(1,46) if i%3],'orphaned_comment_ids':[i for i in range(1,46) if not i%3]},'details':None})
        after=self.rows()
        for identity,row in after.items():
            self.assertEqual({k:v for k,v in row.items() if k!='anchor_status'}, {k:v for k,v in before[identity].items() if k!='anchor_status'})
        self.assertEqual(after[46],before[46]);self.assertEqual(after[47],before[47])

    def write_body(self, connection, markdown):
        snapshot=create_snapshot(markdown,TEMPLATE,T0,DocumentSources(connection,101,self.catalog))
        connection.execute('UPDATE requirement_documents SET markdown_content=?,block_state_json=?,content_version=content_version+1 WHERE id=201',(markdown,snapshot.state_json))
        return snapshot

    def test_selection_unicode_overlap_original_id_only_and_automatic_reattach(self):
        self.seed(1,kind='SELECTION', reference={'selected_text':'😀','prefix_text':'甲','suffix_text':'乙'})
        self.seed(2,kind='SELECTION', reference={'selected_text':'aa','prefix_text':'','suffix_text':''})
        self.seed(3,kind='SELECTION',block_id=99,reference={'selected_text':'😀','prefix_text':'甲','suffix_text':'乙'})
        with self.database.transaction(write=True) as connection:
            snapshot=self.write_body(connection,'甲😀乙 aaa\n')
            result=revalidate_anchors(connection,self.pair(snapshot),catalog=self.catalog)
        self.assertEqual(result['data']['attached_comment_ids'],[1]);self.assertEqual(result['data']['orphaned_comment_ids'],[2,3])
        with self.database.transaction(write=True) as connection:
            snapshot=self.write_body(connection,'甲😀乙 aa\n')
            result=revalidate_anchors(connection,self.pair(snapshot),catalog=self.catalog)
        self.assertEqual(result['data']['attached_comment_ids'],[1,2]);self.assertEqual(result['data']['orphaned_comment_ids'],[3])

    def test_malformed_anchor_aborts_caller_changes_and_prior_anchor_updates(self):
        variants=('{}','{"selected_text":"a","selected_text":"b","prefix_text":"","suffix_text":""}', '{"selected_text":"\\ud800","prefix_text":"","suffix_text":""}')
        for reference in variants:
            with self.subTest(reference=reference):
                with self.database.transaction(write=True) as connection: connection.execute('DELETE FROM comments')
                self.seed(1);self.seed(2,kind='SELECTION',reference=reference)
                with closing(sqlite3.connect(self.path)) as connection: before=list(connection.iterdump())
                with self.assertRaises(Exception):
                    with self.database.transaction(write=True) as connection:
                        snapshot=self.write_body(connection,'a\n')
                        revalidate_anchors(connection,self.pair(snapshot),catalog=self.catalog)
                with closing(sqlite3.connect(self.path)) as connection: self.assertEqual(list(connection.iterdump()),before)

    def test_repository_or_result_failure_rolls_back_outer_transaction(self):
        self.seed(1);self.seed(2)
        original=CommentRepository.set_anchor_status
        def fail_second(repository,req,identity,status):
            original(repository,req,identity,status)
            if identity==2: raise RuntimeError('diagnostic failure after second real write')
        for target, replacement in (('backend.app.comments.commands.revalidate_anchors_result',None),('backend.app.infrastructure.comment_repository.CommentRepository.set_anchor_status',fail_second)):
            with self.subTest(target=target):
                before=self.rows()
                options={'side_effect':RuntimeError('result failure')} if replacement is None else {'new':replacement}
                with patch(target,**options),self.assertRaises(RuntimeError):
                    with self.database.transaction(write=True) as connection:
                        revalidate_anchors(connection,self.pair(),catalog=self.catalog)
                self.assertEqual(self.rows(),before)

    def test_requires_write_transaction_and_actual_current_pair(self):
        with self.database.transaction() as connection,self.assertRaises(RuntimeError):
            revalidate_anchors(connection,self.pair(),catalog=self.catalog)
        invalid=self.pair();invalid['new_document']['markdown_content']+='new\n'
        with self.database.transaction(write=True) as connection,self.assertRaises(ValueError):
            revalidate_anchors(connection,invalid,catalog=self.catalog)

    def test_empty_set_still_returns_full_real_identity_and_no_own_commit(self):
        with self.assertRaises(RuntimeError):
            with self.database.transaction(write=True) as connection:
                snapshot=self.write_body(connection,'changed\n')
                result=revalidate_anchors(connection,self.pair(snapshot),catalog=self.catalog)
                self.assertEqual(result['data'],{'requirement_id':101,'document_id':201,'content_version':8,'attached_comment_ids':[],'orphaned_comment_ids':[]})
                raise RuntimeError('caller abort after successful internal result')
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT content_version FROM requirement_documents WHERE id=201').fetchone()[0],7)


if __name__=='__main__': unittest.main()
