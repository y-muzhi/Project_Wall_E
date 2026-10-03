from copy import deepcopy
import unittest

from backend.app.documents.markdown import DocumentInvalid
from backend.app.documents.patch_application import Adoption, apply_adoptions
from backend.app.documents.patch_errors import PatchInvalid, TargetStale
from backend.app.documents.scopes import resolve_scope
from backend.app.documents.snapshot import Provenance, create_snapshot, validate_snapshot
from backend.app.documents.tables import table_model
from backend.app.infrastructure.identifiers import CapacityExhausted
from backend.app.shared.validation import MAX_SAFE_INTEGER
from backend.tests.documents.test_patch_validation import patch
from backend.tests.documents.test_snapshot import AI, TEMPLATE, T0, T1, T2

EDITED = Provenance('USER', 'SUGGESTION_BATCH', 77)


def sources(origin):
    # Explicit pure fixture; actual same-requirement DB checking is still pending.
    return origin in (AI, EDITED, TEMPLATE)


class PatchApplicationTests(unittest.TestCase):
    def apply(self, old, inputs, authority=None, time=T1, verifier=sources):
        return apply_adoptions(old, inputs, authority or resolve_scope(old, 'MODIFY', 'DOCUMENT'), 77, time, verifier)

    def test_insert_order_identity_allocation_mixed_sources_and_exact_untouched_gaps(self):
        old = create_snapshot('\r\n# A\r\n\r\n原段\r\n\r\n尾段\r\n\r\n', TEMPLATE, T0, sources)
        inputs = [
            Adoption(40, patch(old, 2, 'INSERT_AFTER', '后2\r\n'), 'EDITED', '用户后2\r\n'),
            Adoption(10, patch(old, 2, 'INSERT_BEFORE', '前1\r\n'), 'ACCEPTED'),
            Adoption(30, patch(old, 2, 'INSERT_AFTER', '后1\r\n'), 'ACCEPTED'),
            Adoption(20, patch(old, 2, 'INSERT_BEFORE', '前2\r\n'), 'ACCEPTED'),
        ]
        result = self.apply(old, inputs)
        self.assertEqual([b.plain_text for b in result.parsed.blocks], ['A', '前1', '前2', '原段', '后1', '用户后2', '尾段'])
        self.assertEqual(list(result.by_id), [1, 4, 5, 2, 6, 7, 3])
        self.assertEqual(result.next_block_id, 8)
        self.assertTrue(result.parsed.markdown.startswith('\r\n# A\r\n\r\n'))
        self.assertTrue(result.parsed.markdown.endswith('\r\n\r\n尾段\r\n\r\n'))
        for identity in (1, 2, 3):
            self.assertEqual(result.by_id[identity][0].markdown, old.by_id[identity][0].markdown)
            self.assertEqual(result.by_id[identity][1], old.by_id[identity][1])
        self.assertEqual(result.by_id[7][1]['created_by_type'], 'USER')
        self.assertEqual(result.by_id[6][1]['created_by_type'], 'AI')
        self.assertEqual(old.next_block_id, 4)

    def test_replace_type_delete_and_creation_preservation(self):
        old = create_snapshot('第一\n\n删除\n\n保留\n', TEMPLATE, T0, sources)
        result = self.apply(old, [Adoption(1, patch(old, 1, proposed='# 新标题\n'), 'ACCEPTED'), Adoption(2, patch(old, 2, 'DELETE_BLOCK', None), 'ACCEPTED')])
        self.assertEqual(list(result.by_id), [1, 3])
        self.assertEqual(result.next_block_id, 4)
        self.assertEqual(result.by_id[1][0].block_type, 'heading')
        self.assertEqual(result.by_id[1][1]['created_by_type'], 'SYSTEM')
        self.assertEqual(result.by_id[1][1]['last_modified_by_type'], 'AI')
        self.assertEqual(result.by_id[3][0].markdown, old.by_id[3][0].markdown)
        self.assertEqual(result.by_id[3][1]['section_path'], ['新标题'])
        self.assertEqual(result.by_id[3][1]['last_modified_at'], T1)

    def test_table_key_swap_uses_original_baseline_and_last_actual_row_modifier(self):
        old = create_snapshot('| 键 | 值 |\n| --- | --- |\n| A | 一 |\n| B | 二 |\n', TEMPLATE, T0, sources)
        table = table_model(old.by_id[1][0])
        inputs = []
        for order, row, cells, decision in ((1, table.rows[0], ['B', 'AI改'], 'ACCEPTED'), (2, table.rows[1], ['A', '用户改'], 'EDITED')):
            value = patch(old, 1, 'REPLACE_TABLE_ROW', None, {'key_column_index': 0, 'key_value': row.cells[0]}, {'cells': cells}, row.markdown)
            inputs.append(Adoption(order, value, decision, '{"cells":["A","用户改"]}' if decision == 'EDITED' else None))
        result = self.apply(old, list(reversed(inputs)))
        self.assertEqual([row.cells for row in table_model(result.by_id[1][0]).rows], [('B', 'AI改'), ('A', '用户改')])
        self.assertEqual(result.by_id[1][1]['last_modified_by_type'], 'USER')
        self.assertEqual(result.by_id[1][1]['created_by_type'], 'SYSTEM')
        self.assertTrue(result.parsed.markdown.startswith('| 键 | 值 |\n| --- | --- |\n'))

    def test_heading_causes_are_per_block_and_final_net_no_change_keeps_metadata(self):
        old = create_snapshot('# A\n原段\n\n# B\n另一段\n', TEMPLATE, T0, sources)
        result = self.apply(old, [Adoption(1, patch(old, 1, proposed='# AI标题\n'), 'ACCEPTED'), Adoption(2, patch(old, 4), 'EDITED', '用户正文\n')])
        self.assertEqual(result.by_id[2][1]['last_modified_by_type'], 'AI')
        self.assertEqual(result.by_id[3][1], old.by_id[3][1])
        self.assertEqual(result.by_id[4][1]['last_modified_by_type'], 'USER')
        for identity in result.by_id:
            for field in old.by_id[identity][1]:
                if field.startswith('created_'):
                    self.assertEqual(result.by_id[identity][1][field], old.by_id[identity][1][field])
        unchanged = self.apply(old, [Adoption(1, patch(old, 1, proposed=old.by_id[1][0].markdown), 'ACCEPTED')], time=T2)
        self.assertIs(unchanged, old)
        self.assertIs(self.apply(old, []), old)

    def test_all_checked_first_conflicts_and_late_failure_leave_original_unchanged(self):
        old = create_snapshot('甲\n\n乙\n', TEMPLATE, T0, sources)
        original = deepcopy(old.state)
        with self.assertRaises(TargetStale):
            self.apply(old, [Adoption(1, patch(old), 'ACCEPTED'), Adoption(2, patch(old, 2, original='旧原文'), 'ACCEPTED')])
        with self.assertRaises(PatchInvalid):
            self.apply(old, [Adoption(1, patch(old), 'ACCEPTED'), Adoption(2, patch(old), 'ACCEPTED')])
        # An unclosed fence is one standalone block, but would swallow the next
        # block on composition. Never silently change that neighbor's identity.
        with self.assertRaises(PatchInvalid):
            self.apply(old, [Adoption(1, patch(old, proposed='```\n代码\n'), 'ACCEPTED')])
        self.assertEqual(old.state, original)
        self.assertEqual(old.parsed.markdown, '甲\n\n乙\n')

    def test_eof_insert_separates_paragraphs_and_target_boundary_has_source(self):
        old = create_snapshot('末段', TEMPLATE, T0, sources)
        result = self.apply(old, [Adoption(1, patch(old, operation='INSERT_AFTER', proposed='新增'), 'ACCEPTED')])
        self.assertEqual(result.parsed.markdown, '末段\n\n新增')
        self.assertEqual(list(result.by_id), [1, 2])
        self.assertEqual(result.by_id[1][1]['last_modified_by_type'], 'AI')
        self.assertEqual(result.by_id[1][1]['created_at'], T0)

    def test_scope_permission_and_selection_remain_checked_at_adoption(self):
        old = create_snapshot('😀审批人为部**门**经理。\n\n另一段\n', TEMPLATE, T0, sources)
        authority = resolve_scope(old, 'MODIFY', 'SELECTION', {'block_id': 1, 'selected_text': '部门经理', 'prefix_text': '审批人为', 'suffix_text': '。'})
        result = self.apply(old, [Adoption(1, patch(old, proposed='😀审批人为部门主管。\n'), 'ACCEPTED')], authority)
        self.assertEqual(result.by_id[2][0].markdown, old.by_id[2][0].markdown)
        self.assertEqual(result.by_id[2][1], old.by_id[2][1])
        self.assertEqual(result.by_id[2][0].start_offset, old.by_id[2][0].start_offset - 4)
        with self.assertRaises(TargetStale):
            self.apply(old, [Adoption(1, patch(old, 2), 'ACCEPTED')], authority)
        with self.assertRaises(PatchInvalid):
            self.apply(old, [Adoption(1, patch(old), 'EDITED', '越界。\n')], authority)

    def test_order_decision_source_clock_and_highwater_failure_are_explicit(self):
        old = create_snapshot('原\n', TEMPLATE, T0, sources)
        value = patch(old)
        for inputs in ([Adoption(True, value, 'ACCEPTED')], [Adoption(1, value, 'PENDING')], [Adoption(1, value, 'EDITED')], [Adoption(1, value, 'ACCEPTED', '不应存在')], [Adoption(1, value, 'ACCEPTED'), Adoption(1, value, 'ACCEPTED')]):
            with self.subTest(inputs=inputs), self.assertRaises(PatchInvalid):
                self.apply(old, inputs)
        with self.assertRaises(DocumentInvalid):
            self.apply(old, [Adoption(1, value, 'ACCEPTED')], verifier=lambda _: False)
        with self.assertRaises(DocumentInvalid):
            self.apply(old, [Adoption(1, value, 'ACCEPTED')], time='2026-10-02T00:00:00.000Z')
        state = old.state
        state['next_block_id'] = MAX_SAFE_INTEGER
        exhausted = validate_snapshot(old.parsed.markdown, state, sources)
        with self.assertRaises(CapacityExhausted):
            self.apply(exhausted, [Adoption(1, patch(exhausted, operation='INSERT_AFTER'), 'ACCEPTED')])
        self.assertEqual(exhausted.next_block_id, MAX_SAFE_INTEGER)

    def test_every_supported_block_can_be_inserted_without_losing_neighbors(self):
        old = create_snapshot('前段\n\n后段\n', TEMPLATE, T0, sources)
        samples = ('# 标题\n', '段落\n', '> 引用\n', '- 条目\n', '1. 条目\n', '- [ ] 任务\n', '```\n代码\n```\n', '---\n', '| 键 | 值 |\n| --- | --- |\n| A | B |\n', '<div>惰性HTML</div>\n', '[引用]: /url\n')
        for sample in samples:
            with self.subTest(sample=sample):
                result = self.apply(old, [Adoption(1, patch(old, 1, 'INSERT_AFTER', sample), 'ACCEPTED')])
                self.assertEqual(list(result.by_id), [1, 3, 2])
                self.assertEqual(result.by_id[1][0].markdown, old.by_id[1][0].markdown)
                self.assertEqual(result.by_id[2][0].markdown, old.by_id[2][0].markdown)
                self.assertEqual(result.by_id[3][0].markdown, sample)

    def test_deleting_all_blocks_retains_authored_gaps_and_highwater(self):
        old = create_snapshot('\n甲\n\n乙\n\n', TEMPLATE, T0, sources)
        result = self.apply(old, [Adoption(2, patch(old, 2, 'DELETE_BLOCK', None), 'ACCEPTED'), Adoption(1, patch(old, 1, 'DELETE_BLOCK', None), 'ACCEPTED')])
        self.assertEqual(result.parsed.markdown, '\n\n\n')
        self.assertEqual(result.state['blocks'], [])
        self.assertEqual(result.next_block_id, 3)


if __name__ == '__main__':
    unittest.main()
