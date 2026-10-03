import unittest

from backend.app.documents.markdown import parse_markdown
from backend.app.documents.patch_errors import PatchInvalid, TargetStale
from backend.app.documents.tables import RowReplacement, replace_rows, select_row, table_model, validate_cells


def table(source):
    return table_model(parse_markdown(source).blocks[0])


class TableTests(unittest.TestCase):
    def test_raw_header_separator_rows_crlf_and_plain_key_selection(self):
        source = '| 键 | 值 |\r\n| :--- | ---: |\r\n| A\\|B | **甲** |\r\n| 😀 | `x` |'
        model = table(source)
        self.assertEqual(model.headers, ('键', '值'))
        self.assertEqual(model.rows[0].cells, ('A|B', '甲'))
        self.assertEqual(model.rows[0].markdown, '| A\\|B | **甲** |\r\n')
        self.assertEqual(select_row(model, {'key_column_index': 0, 'key_value': 'A|B'}), 0)
        self.assertEqual(model.rows[-1].markdown, '| 😀 | `x` |')

    def test_duplicate_absent_header_key_and_wrong_selector_reject(self):
        model = table('| 键 | 值 |\n| --- | --- |\n| A | 一 |\n| A | 二 |\n')
        for key in ('A', '键', '不存在', 'a'):
            with self.assertRaises(TargetStale):
                select_row(model, {'key_column_index': 0, 'key_value': key})
        for selector in ({'key_column_index': 1, 'key_value': 'A'}, {'key_column_index': True, 'key_value': 'A'}, {'key_column_index': 0, 'key_value': 1}, {'key_column_index': 0, 'key_value': 'A', 'extra': None}):
            with self.assertRaises(PatchInvalid):
                select_row(model, selector)

    def test_multiple_rows_use_one_baseline_and_keep_all_other_source_exact(self):
        source = '| 键 | 值 |\r\n| :--- | ---: |\r\n| A | 甲 |\r\n| B | 乙 |\r\n| C | 丙 |\r\n'
        model = table(source)
        replacement = lambda index, cells: RowReplacement({'key_column_index': 0, 'key_value': model.rows[index].cells[0]}, model.rows[index].markdown, cells)
        result = replace_rows(model, (replacement(0, ('B', '新的甲')), replacement(1, ('A', '新的乙'))))
        self.assertTrue(result.startswith('| 键 | 值 |\r\n| :--- | ---: |\r\n'))
        self.assertTrue(result.endswith('| C | 丙 |\r\n'))
        self.assertEqual([row.cells for row in table(result).rows], [('B', '新的甲'), ('A', '新的乙'), ('C', '丙')])

    def test_literal_cell_escaping_preserves_markup_html_entities_spaces_tabs_and_pipes(self):
        model = table('| 键 | 值 |\n| --- | --- |\n| A | 原文 |\n')
        for cell in ('**不是加粗** _不是斜体_ ~~文本~~ `code`', '<script>alert("x")</script>', '&lt; &amp; &#32;', '  甲\t乙  ', '反斜\\与竖线|及\\|', '[链接](x) ![图](x)', '😀\u2028甲'):
            with self.subTest(cell=cell):
                replacement = RowReplacement({'key_column_index': 0, 'key_value': 'A'}, model.rows[0].markdown, ('A', cell))
                result = replace_rows(model, (replacement,))
                self.assertEqual(table(result).rows[0].cells, ('A', cell))

    def test_column_count_newline_nonstring_unknown_fields_stale_and_duplicate_patch_reject(self):
        model = table('| 键 | 值 |\n| --- | --- |\n| A | 甲 |\n')
        for value in ({'cells': ['A']}, {'cells': ['A', 1]}, {'cells': ['A', 'x\ny']}, {'cells': ['A', '甲'], 'extra': None}):
            with self.assertRaises(PatchInvalid):
                validate_cells(value, 2)
        row = RowReplacement({'key_column_index': 0, 'key_value': 'A'}, model.rows[0].markdown, ('A', '乙'))
        with self.assertRaises(PatchInvalid):
            replace_rows(model, (row, row))
        with self.assertRaises(TargetStale):
            replace_rows(model, (RowReplacement(row.selector, 'wrong', row.cells),))
        self.assertEqual(replace_rows(model, ()), model.markdown)
