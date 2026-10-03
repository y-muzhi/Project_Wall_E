from copy import deepcopy
import unittest

from backend.app.documents.patch_errors import PatchInvalid, TargetStale
from backend.app.documents.patch_validation import validate_bundle, validate_combination, validate_patch
from backend.app.documents.scopes import resolve_scope
from backend.app.documents.snapshot import create_snapshot
from backend.app.documents.tables import table_model
from backend.tests.documents.test_snapshot import TEMPLATE, T0, sources


def patch(snapshot, identity=1, operation='REPLACE_BLOCK', proposed='新正文\n', selector=None, data=None, original=None):
    return {'title': '修改', 'explanation': '用户要求', 'impact': None, 'target_ref': {'block_id': identity}, 'original_content': snapshot.by_id[identity][0].markdown if original is None else original, 'patch_operation': operation, 'selector_json': selector, 'proposed_markdown': proposed, 'proposed_data_json': data}


class PatchValidationTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = create_snapshot('原正文\n\n另段\n\n| 键 | 值 |\n| --- | --- |\n| A | 一 |\n| B | 二 |\n', TEMPLATE, T0, sources)
        self.authority = resolve_scope(self.snapshot, 'MODIFY', 'DOCUMENT')

    def test_all_five_operations_and_exact_original_comparison(self):
        for operation in ('REPLACE_BLOCK', 'INSERT_BEFORE', 'INSERT_AFTER'):
            checked = validate_patch(self.snapshot, patch(self.snapshot, operation=operation), self.authority)
            self.assertEqual(checked.operation, operation)
        validate_patch(self.snapshot, patch(self.snapshot, operation='DELETE_BLOCK', proposed=None), self.authority)
        row = table_model(self.snapshot.by_id[3][0]).rows[0]
        row_patch = patch(self.snapshot, 3, 'REPLACE_TABLE_ROW', None, {'key_column_index': 0, 'key_value': 'A'}, {'cells': ['A', '新值']}, row.markdown)
        self.assertEqual(validate_patch(self.snapshot, row_patch, self.authority).row_cells, ('A', '新值'))
        with self.assertRaises(TargetStale):
            validate_patch(self.snapshot, patch(self.snapshot, original='原正文'), self.authority)

    def test_scope_neighbor_read_is_not_authority_and_bad_structure_is_never_repaired(self):
        focused = resolve_scope(self.snapshot, 'MODIFY', 'BLOCK', {'block_id': 1})
        self.assertIn(2, focused.read_ids)
        with self.assertRaises(TargetStale):
            validate_patch(self.snapshot, patch(self.snapshot, 2), focused)
        for mutation in (lambda p: p.update(unknown=True), lambda p: p['target_ref'].update(extra=True), lambda p: p.update(proposed_markdown='第一段\n\n第二段\n'), lambda p: p.update(proposed_markdown='\n\n')):
            value = patch(self.snapshot)
            mutation(value)
            with self.assertRaises(PatchInvalid):
                validate_patch(self.snapshot, value, self.authority)
        with self.assertRaises(TargetStale):
            validate_patch(self.snapshot, patch(self.snapshot), resolve_scope(self.snapshot, 'ASK', 'DOCUMENT'))

    def test_edited_block_and_cells_json_cannot_change_frozen_target_or_operation(self):
        checked = validate_patch(self.snapshot, patch(self.snapshot), self.authority, edited_content='用户版本\n')
        self.assertEqual(checked.proposed_markdown, '用户版本\n')
        self.assertEqual(checked.patch['proposed_markdown'], '新正文\n')
        with self.assertRaises(PatchInvalid):
            validate_patch(self.snapshot, patch(self.snapshot, operation='DELETE_BLOCK', proposed=None), self.authority, edited_content='不能编辑删除')
        row = table_model(self.snapshot.by_id[3][0]).rows[0]
        value = patch(self.snapshot, 3, 'REPLACE_TABLE_ROW', None, {'key_column_index': 0, 'key_value': 'A'}, {'cells': ['A', '新值']}, row.markdown)
        self.assertEqual(validate_patch(self.snapshot, value, self.authority, edited_content='{"cells":["A","编辑"]}').row_cells, ('A', '编辑'))
        for content in ('```json\n{"cells":["A","x"]}\n```', '{"cells":["A","x"],"target_ref":{}}', '{"cells":["A","x"],"cells":["A","y"]}'):
            with self.assertRaises(PatchInvalid):
                validate_patch(self.snapshot, value, self.authority, edited_content=content)

    def test_selection_exact_bounds_formatted_text_unicode_and_outside_marker_changes(self):
        old = create_snapshot('😀审批人为部**门**经理。\n', TEMPLATE, T0, sources)
        authority = resolve_scope(old, 'MODIFY', 'SELECTION', {'block_id': 1, 'selected_text': '部门经理', 'prefix_text': '审批人为', 'suffix_text': '。'})
        validate_patch(old, patch(old, proposed='😀审批人为部门主管。\n'), authority)
        for proposed in ('😀**审批人为**部门主管。\n', '前缀😀审批人为部门主管。\n', '😀审批人为部门主管！\n'):
            with self.subTest(proposed=proposed), self.assertRaises(PatchInvalid):
                validate_patch(old, patch(old, proposed=proposed), authority)
        with self.assertRaises(TargetStale):
            validate_patch(old, patch(old, operation='INSERT_AFTER'), authority)

    def test_combination_conflicts_and_multiple_insert_order_preserved(self):
        replace = validate_patch(self.snapshot, patch(self.snapshot), self.authority)
        delete = validate_patch(self.snapshot, patch(self.snapshot, operation='DELETE_BLOCK', proposed=None), self.authority)
        insert = validate_patch(self.snapshot, patch(self.snapshot, operation='INSERT_AFTER'), self.authority)
        for combination in ((replace, replace), (replace, delete), (delete, insert)):
            with self.assertRaises(PatchInvalid):
                validate_combination(combination)
        inputs = [patch(self.snapshot, operation='INSERT_AFTER', proposed='先插入\n'), patch(self.snapshot, operation='INSERT_AFTER', proposed='后插入\n')]
        self.assertEqual([checked.proposed_markdown for checked in validate_bundle(self.snapshot, inputs, self.authority)], ['先插入\n', '后插入\n'])
        model = table_model(self.snapshot.by_id[3][0])
        rows = [patch(self.snapshot, 3, 'REPLACE_TABLE_ROW', None, {'key_column_index': 0, 'key_value': row.cells[0]}, {'cells': [row.cells[0], '新值']}, row.markdown) for row in model.rows]
        checked = validate_bundle(self.snapshot, rows, self.authority)
        self.assertEqual([item.row_index for item in checked], [0, 1])
        with self.assertRaises(PatchInvalid):
            validate_combination((checked[0], checked[0]))
        with self.assertRaises(PatchInvalid):
            validate_combination((checked[0], validate_patch(self.snapshot, patch(self.snapshot, 3, proposed='整块\n'), self.authority)))
        for values in ([], [inputs[0]] * 101):
            with self.assertRaises(PatchInvalid):
                validate_bundle(self.snapshot, values, self.authority)
