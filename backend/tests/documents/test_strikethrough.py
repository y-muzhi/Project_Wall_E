import json
from pathlib import Path
import unittest

from backend.app.documents.markdown import _parser, parse_markdown


def deleted_text(markdown):
    result = []
    for token in _parser().parse(markdown, {}):
        depth = 0
        value = ''
        for child in token.children or []:
            if child.type == 's_open':
                depth += 1
            elif child.type == 's_close':
                depth -= 1
                if depth == 0:
                    result.append(value)
                    value = ''
            elif depth:
                if child.type in ('text', 'code_inline', 'html_inline'):
                    value += child.content
                elif child.type in ('softbreak', 'hardbreak'):
                    value += '\n'
    return result


class StrikethroughTests(unittest.TestCase):
    def test_independent_gfm_width_and_context_cases(self):
        path = Path(__file__).resolve().parents[3] / 'shared/fixtures/strikethrough-v1.json'
        for case in json.loads(path.read_text(encoding='utf-8'))['cases']:
            with self.subTest(case=case['name']):
                parsed = parse_markdown(case['markdown'])
                self.assertEqual([block.plain_text for block in parsed.blocks], case['plain_text'])
                self.assertEqual(deleted_text(case['markdown']), case['deleted'])
                self.assertEqual(''.join(parsed.source_parts()), case['markdown'])
