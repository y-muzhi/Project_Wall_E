import json
from pathlib import Path
import unittest

from backend.app.documents.markdown import _parser, parse_markdown


class RawSourceTests(unittest.TestCase):
    def test_independent_container_source_and_projection(self):
        fixtures = Path(__file__).resolve().parents[3] / 'shared/fixtures/raw-source-containers-v1.json'
        for entry in json.loads(fixtures.read_text(encoding='utf-8'))['cases']:
            with self.subTest(case=entry['name']):
                parsed = parse_markdown(entry['markdown'])
                self.assertEqual(len(parsed.blocks), 1)
                block = parsed.blocks[0]
                self.assertEqual(block.block_type, entry['block_type'])
                self.assertEqual(block.plain_text, entry['plain_text'])
                self.assertEqual(block.markdown, entry['markdown'])
                self.assertEqual(''.join(parsed.source_parts()), entry['markdown'])

    def test_duplicate_container_definitions_keep_first_reference_destination(self):
        tokens = _parser().parse('> [a]: /first\r\n> [a]: /second\r\n>\r\n> [标签][a]\r\n', {})
        definitions = [token.meta['walle_raw_source'] for token in tokens if token.type == 'definition']
        self.assertEqual(definitions, ['[a]: /first\r\n', '[a]: /second\r\n'])
        links = [child.attrGet('href') for token in tokens for child in token.children or [] if child.type == 'link_open']
        self.assertEqual(links, ['/first'])
