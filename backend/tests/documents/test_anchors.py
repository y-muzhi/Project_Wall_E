import unittest

from backend.app.documents.anchors import AnchorInvalid, ORPHANED, create_block_anchor, create_selection_anchor, locate
from backend.app.documents.snapshot import assign_identities, create_snapshot
from backend.tests.documents.test_snapshot import TEMPLATE, USER, T0, T1, sources


class AnchorTests(unittest.TestCase):
    def test_block_snapshot_created_server_side_and_identity_not_old_content(self):
        original = create_snapshot('旧正文\n', TEMPLATE, T0, sources)
        anchor = create_block_anchor(original, 1)
        self.assertEqual(anchor, {'block_markdown_snapshot': '旧正文\n'})
        modified = assign_identities('新正文\n', [1], 2, original, USER, T1, sources)
        self.assertEqual(locate(modified, 'BLOCK', 1, anchor).as_dict(), {'block_id': 1, 'start_offset': None, 'end_offset': None})
        deleted = assign_identities('', [], 2, modified, USER, T1, sources)
        self.assertEqual(locate(deleted, 'BLOCK', 1, anchor), ORPHANED)
        self.assertEqual(anchor, {'block_markdown_snapshot': '旧正文\n'})

    def test_selection_unicode_codepoints_immediate_context_and_relocation(self):
        original = create_snapshot('😀审批人为部门经理。\n', TEMPLATE, T0, sources)
        ref = {'selected_text': '部门经理', 'prefix_text': '审批人为', 'suffix_text': '。'}
        self.assertEqual(locate(original, 'SELECTION', 1, ref).as_dict(), {'block_id': 1, 'start_offset': 5, 'end_offset': 9})
        anchor = create_selection_anchor(original, 1, ref)
        changed = assign_identities('前缀😀审批人为部门经理。\n', [1], 2, original, USER, T1, sources)
        self.assertEqual(locate(changed, 'SELECTION', 1, anchor).start_offset, 7)
        anchor['prefix_text'] = 'other'
        self.assertEqual(ref['prefix_text'], '审批人为')

    def test_duplicates_overlap_empty_context_and_changed_context_are_orphaned(self):
        cases = [
            ('经理与经理\n', {'selected_text': '经理', 'prefix_text': '', 'suffix_text': ''}),
            ('aaa\n', {'selected_text': 'aa', 'prefix_text': '', 'suffix_text': ''}),
            ('部门经理。\n', {'selected_text': '经理', 'prefix_text': '别的', 'suffix_text': '。'}),
            ('已变更\n', {'selected_text': '经理', 'prefix_text': '', 'suffix_text': ''}),
        ]
        for text, ref in cases:
            with self.subTest(text=text):
                snapshot = create_snapshot(text, TEMPLATE, T0, sources)
                self.assertEqual(locate(snapshot, 'SELECTION', 1, ref), ORPHANED)
                with self.assertRaises(AnchorInvalid):
                    create_selection_anchor(snapshot, 1, ref)
        unique = create_snapshot('甲经理乙经理丙\n', TEMPLATE, T0, sources)
        self.assertEqual(locate(unique, 'SELECTION', 1, {'selected_text': '经理', 'prefix_text': '乙', 'suffix_text': '丙'}).start_offset, 4)

    def test_cannot_cross_block_or_find_other_identical_block_and_can_reattach(self):
        initial = create_snapshot('前经理后\n\n经理后\n', TEMPLATE, T0, sources)
        ref = {'selected_text': '经理', 'prefix_text': '前', 'suffix_text': '后'}
        self.assertTrue(locate(initial, 'SELECTION', 1, ref).attached)
        changed = assign_identities('已变更\n\n前经理后\n', [1, 2], 3, initial, USER, T1, sources)
        self.assertEqual(locate(changed, 'SELECTION', 1, ref), ORPHANED)
        self.assertTrue(locate(initial, 'SELECTION', 1, ref).attached)

    def test_bad_persisted_structure_is_error_instead_of_fake_orphan(self):
        snapshot = create_snapshot('正文\n', TEMPLATE, T0, sources)
        invalid = [
            ('BLOCK', {'block_markdown_snapshot': '正文', 'fingerprint': 'forbidden'}),
            ('SELECTION', {'selected_text': '', 'prefix_text': '', 'suffix_text': ''}),
            ('SELECTION', {'selected_text': '正文', 'prefix_text': 'x' * 101, 'suffix_text': ''}),
            ('UNKNOWN', {}),
        ]
        for kind, ref in invalid:
            with self.assertRaises(AnchorInvalid):
                locate(snapshot, kind, 1, ref)
        with self.assertRaises(AnchorInvalid):
            locate(snapshot, 'BLOCK', True, {'block_markdown_snapshot': ''})
