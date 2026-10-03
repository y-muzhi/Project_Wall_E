import unittest
import json
from pathlib import Path

from backend.app.documents.markdown import BLOCK_TYPES, DocumentInvalid, parse_markdown
from backend.app.infrastructure.resources import ResourceCatalog


class MarkdownTests(unittest.TestCase):
    def test_shared_independent_golden_fixtures(self):
        directory = Path(__file__).resolve().parents[3] / 'shared' / 'fixtures'
        cases = []
        for name in ('markdown-v1.json', 'markdown-editor-v1.json'):
            cases.extend(json.loads((directory / name).read_text(encoding='utf-8'))['cases'])
        for case in cases:
            with self.subTest(case=case['name']):
                parsed = parse_markdown(case['markdown'])
                actual = [{'type': block.block_type, 'plain_text': block.plain_text, 'section_path': list(block.section_path), 'heading_level': block.heading_level} for block in parsed.blocks]
                self.assertEqual(actual, case['blocks'])
                self.assertEqual(''.join(parsed.source_parts()), case['markdown'])

    def test_each_registered_top_level_type_and_exact_source_round_trip(self):
        samples = {
            'heading': '# 标题\n', 'paragraph': '段落 **加粗**。\n',
            'blockquote': '> 引用\n>\n> 第二段\n', 'bullet_list': '- 一\n- 二\n',
            'ordered_list': '1. 一\n2. 二\n', 'task_list': '- [ ] 待办\n- [x] 完成\n',
            'code_block': '```python\nprint("甲")\n```\n', 'thematic_break': '---\n',
            'table': '| 键 | 值 |\n| --- | --- |\n| A | 一 |\n',
            'html_block': '<script>window.bad()</script>\n',
            'link_definition': '[引用]: https://example.test "标题"\n',
        }
        self.assertEqual(set(samples), set(BLOCK_TYPES))
        for kind, source in samples.items():
            with self.subTest(kind=kind):
                parsed = parse_markdown('\n' + source + '\n')
                self.assertEqual(len(parsed.blocks), 1)
                self.assertEqual(parsed.blocks[0].block_type, kind)
                self.assertEqual(parsed.blocks[0].markdown, source)
                self.assertEqual(''.join(parsed.source_parts()), '\n' + source + '\n')

    def test_empty_whitespace_crlf_lone_cr_unicode_separator_and_no_final_newline(self):
        for source in ('', '\n\n', ' \r\n\t\r\n'):
            parsed = parse_markdown(source)
            self.assertEqual(parsed.blocks, ())
            self.assertEqual(''.join(parsed.source_parts()), source)
        source = '\r\n# 第一章\r\n\r\n甲\u2028乙😀\r\r下一段'
        parsed = parse_markdown(source)
        self.assertEqual([block.block_type for block in parsed.blocks], ['heading', 'paragraph', 'paragraph'])
        self.assertEqual(parsed.blocks[1].plain_text, '甲\u2028乙😀')
        self.assertEqual(parsed.blocks[-1].markdown, '下一段')
        self.assertEqual(''.join(parsed.source_parts()), source)
        for block in parsed.blocks:
            self.assertEqual(source[block.start_offset:block.end_offset], block.markdown)

    def test_section_path_heading_levels_repeats_and_skipped_levels(self):
        parsed = parse_markdown('序言\n\n# A\n\n### C\n\n正文\n\n## B\n\n# A\n')
        self.assertEqual([block.section_path for block in parsed.blocks], [(), ('A',), ('A', 'C'), ('A', 'C'), ('A', 'B'), ('A',)])
        self.assertEqual([block.heading_level for block in parsed.blocks], [None, 1, 3, None, 2, 1])
        self.assertEqual(parse_markdown('标题\n====\n').blocks[0].heading_level, 1)

    def test_plain_text_inline_marks_links_images_unicode_and_breaks(self):
        source = '**甲** _乙_ ~~丙~~ `x<y` [链接](https://example.test) ![图😀](x.png)\n软换行  \n硬换行 <em>原样</em>\n'
        block = parse_markdown(source).blocks[0]
        self.assertEqual(block.plain_text, '甲 乙 丙 x<y 链接 图😀\n软换行\n硬换行 <em>原样</em>')
        self.assertEqual(block.markdown, source)

    def test_table_cells_tab_rows_lf_escaped_pipe_and_nested_inline(self):
        block = parse_markdown('| 键 | 值 |\n| --- | --- |\n| A\\|B | **加粗** |\n| 😀 | `code` |\n').blocks[0]
        self.assertEqual(block.plain_text, '键\t值\nA|B\t加粗\n😀\tcode')

    def test_tasks_lists_and_nested_containers_stay_one_block(self):
        source = '- [ ] 待办\n- [x] 完成\n  - 内层\n'
        parsed = parse_markdown(source)
        self.assertEqual(len(parsed.blocks), 1)
        self.assertEqual(parsed.blocks[0].block_type, 'task_list')
        self.assertEqual(parsed.blocks[0].plain_text, '待办\n完成\n内层')
        authored = '- [ ] <input class="task-list-item-checkbox">保留\n'
        self.assertEqual(parse_markdown(authored).blocks[0].plain_text, '<input class="task-list-item-checkbox">保留')
        self.assertEqual(parse_markdown('> - **一**\n> - 二\n').blocks[0].plain_text, '一\n二')

    def test_definitions_duplicates_and_html_remain_inert_visible_source(self):
        source = '[a]: https://a.test\n[a]: https://b.test\n\n[标签][a]\n\n<div>\n原样\n</div>\n'
        parsed = parse_markdown(source)
        self.assertEqual([block.block_type for block in parsed.blocks], ['link_definition', 'link_definition', 'paragraph', 'html_block'])
        self.assertEqual(parsed.blocks[2].plain_text, '标签')
        self.assertEqual(parsed.blocks[0].plain_text, '[a]: https://a.test\n')
        self.assertEqual(parsed.blocks[-1].plain_text, '<div>\n原样\n</div>\n')
        self.assertEqual(''.join(parsed.source_parts()), source)

    def test_unfinished_syntax_and_unknown_extensions_keep_original_markdown(self):
        for source in ('**未闭合\n', '```python\nunfinished\n', '$$数学$$\n', ':::扩展\n', 'www.example.test email@example.test\n'):
            parsed = parse_markdown(source)
            self.assertEqual(len(parsed.blocks), 1)
            self.assertEqual(''.join(parsed.source_parts()), source)

    def test_both_approved_templates_have_complete_locked_heading_order(self):
        catalog = ResourceCatalog()
        for type_, key in (('NEW', 'new-requirement'), ('CHANGE', 'change-requirement')):
            template = catalog.template(type_, key, 'v1')
            parsed = parse_markdown(template.markdown)
            headings = [(block.heading_level, block.plain_text) for block in parsed.blocks if block.block_type == 'heading']
            self.assertEqual(headings, [(heading.level, heading.text) for heading in template.locked_headings])
            self.assertEqual(''.join(parsed.source_parts()), template.markdown)

    def test_capacity_invalid_unicode_and_type_reject_without_truncating(self):
        for source in (None, 'x' * 1_000_001, '\ud800', 'a\n\n' * 10_001):
            with self.assertRaises(DocumentInvalid):
                parse_markdown(source)
        source = '😀' * 1_000_000
        self.assertEqual(parse_markdown(source).markdown, source)
