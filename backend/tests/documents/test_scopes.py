import unittest

from backend.app.documents.scopes import ScopeInvalid, resolve_scope
from backend.app.documents.snapshot import create_snapshot
from backend.tests.documents.test_snapshot import TEMPLATE, T0, sources


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = create_snapshot('前言\n\n# 重复\n\n正文甲\n\n## 子节\n\n子正文\n\n# 重复\n\n正文乙\n\n| 键 | 值 |\n| --- | --- |\n| A | 一 |\n', TEMPLATE, T0, sources)

    def test_document_all_blocks_and_ask_review_never_write(self):
        resolved = resolve_scope(self.snapshot, 'MODIFY', 'DOCUMENT')
        self.assertEqual(resolved.focus_ids, tuple(range(1, 9)))
        self.assertEqual(resolved.read_ids, resolved.focus_ids)
        self.assertIsNone(resolved.input_ref)
        self.assertEqual(resolved.context_scope, {'scope_type': 'DOCUMENT', 'scope_ref': None})
        self.assertIn('REPLACE_TABLE_ROW', resolved.allowed_targets[-1].operations)
        self.assertNotIn('REPLACE_TABLE_ROW', resolved.allowed_targets[0].operations)
        for action in ('ASK', 'REVIEW'):
            readonly = resolve_scope(self.snapshot, action, 'DOCUMENT')
            self.assertEqual(readonly.allowed_targets, ())
            self.assertEqual(readonly.read_ids, resolved.read_ids)

    def test_section_uses_heading_identity_and_stops_at_same_or_higher_heading(self):
        resolved = resolve_scope(self.snapshot, 'MODIFY', 'SECTION', {'block_id': 2})
        self.assertEqual(resolved.focus_ids, (2, 3, 4, 5))
        self.assertEqual(resolved.context_scope['scope_ref'], {'heading_block_id': 2})
        self.assertEqual(resolved.input_ref, {'block_id': 2})
        self.assertNotIn('INSERT_BEFORE', resolved.allowed_targets[0].operations)
        self.assertEqual(resolve_scope(self.snapshot, 'MODIFY', 'SECTION', {'block_id': 6}).focus_ids, (6, 7, 8))
        subsection = resolve_scope(self.snapshot, 'MODIFY', 'SECTION', {'block_id': 4})
        self.assertEqual(subsection.focus_ids, (4, 5))
        self.assertEqual(subsection.required_read_ids, (2, 4, 5))
        self.assertNotIn(2, [target.block_id for target in subsection.allowed_targets])

    def test_block_reads_ancestors_neighbors_but_only_target_is_writable(self):
        resolved = resolve_scope(self.snapshot, 'MODIFY', 'BLOCK', {'block_id': 5})
        self.assertEqual(resolved.focus_ids, (5,))
        self.assertEqual(resolved.required_read_ids, (2, 4, 5))
        self.assertEqual(resolved.read_ids, (2, 3, 4, 5, 6, 7))
        self.assertEqual([target.block_id for target in resolved.allowed_targets], [5])
        self.assertIn('INSERT_BEFORE', resolved.allowed_targets[0].operations)
        self.assertIn('INSERT_AFTER', resolved.allowed_targets[0].operations)

    def test_selection_range_unique_codepoints_and_replace_only(self):
        resolved = resolve_scope(self.snapshot, 'MODIFY', 'SELECTION', {'block_id': 3, 'selected_text': '甲', 'prefix_text': '正文', 'suffix_text': ''})
        self.assertEqual(resolved.focus_ids, (3,))
        target = resolved.targets_json[0]
        self.assertEqual(target, {'block_id': 3, 'operations': ['REPLACE_BLOCK'], 'selection_range': {'start_offset': 2, 'end_offset': 3}, 'row_selectors': None})
        target['operations'].append('DELETE_BLOCK')
        self.assertEqual(resolved.allowed_targets[0].operations, ('REPLACE_BLOCK',))

    def test_invalid_empty_stale_or_wrong_shape_ranges_fail(self):
        cases = [('DOCUMENT', {}), ('SECTION', None), ('SECTION', {'block_id': 3}), ('BLOCK', {'block_id': 9}), ('BLOCK', {'block_id': True}), ('BLOCK', {'block_id': 1, 'extra': True}), ('SELECTION', {'block_id': 3, 'selected_text': '不存在', 'prefix_text': '', 'suffix_text': ''}), ('SELECTION', {'block_id': 3, 'start_offset': 0, 'end_offset': 2})]
        for kind, ref in cases:
            with self.subTest(kind=kind, ref=ref), self.assertRaises(ScopeInvalid):
                resolve_scope(self.snapshot, 'MODIFY', kind, ref)
        empty = create_snapshot('', TEMPLATE, T0, sources)
        self.assertEqual(resolve_scope(empty, 'MODIFY', 'DOCUMENT').allowed_targets, ())
        with self.assertRaises(ScopeInvalid):
            resolve_scope(empty, 'MODIFY', 'BLOCK', {'block_id': 1})
