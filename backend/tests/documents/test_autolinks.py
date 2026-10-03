import json
from pathlib import Path
import unittest
import unicodedata

from backend.app.documents.markdown import _parser, parse_markdown


def inline_links(markdown):
    links = []
    for token in _parser().parse(markdown, {}):
        current = None
        for child in token.children or []:
            if child.type == 'link_open':
                current = {'text': '', 'href': child.attrGet('href')}
            elif child.type == 'link_close':
                links.append(current)
                current = None
            elif current is not None:
                current['text'] += child.content
    return links


class AutolinkTests(unittest.TestCase):
    def test_all_codepoint_categories_match_shared_frontend_compatibility_profile(self):
        path = Path(__file__).resolve().parents[3] / 'shared/markdown/url-domain-unicode-v1.json'
        profile = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(profile['schema_version'], 1)
        self.assertEqual(profile['unicode_version'], unicodedata.unidata_version)
        previous = -1
        for start, end in profile['ranges']:
            self.assertTrue(previous < start <= end < 0x110000)
            previous = end
        index = 0
        for point in range(0x110000):
            while index < len(profile['ranges']) and point > profile['ranges'][index][1]:
                index += 1
            expected = index < len(profile['ranges']) and point >= profile['ranges'][index][0]
            self.assertEqual(expected, chr(point).isalnum(), f'U+{point:X}')

    def test_independent_gfm_cases_keep_projection_and_complete_source(self):
        path = Path(__file__).resolve().parents[3] / 'shared/fixtures/autolink-v1.json'
        for case in json.loads(path.read_text(encoding='utf-8'))['cases']:
            with self.subTest(case=case['name']):
                parsed = parse_markdown(case['markdown'])
                self.assertEqual(parsed.blocks[0].plain_text, case['plain_text'])
                self.assertEqual(''.join(parsed.source_parts()), case['markdown'])
                self.assertEqual(inline_links(case['markdown']), case['links'])

    def test_container_and_table_inline_boundaries(self):
        url = 'www.example.test/a*b*c'
        for markdown in (f'# {url}\n', f'> {url}\n', f'- {url}\n', f'- [ ] {url}\n',
                         f'| {url}|标题|\n|---|---|\n| 值|值|\n'):
            with self.subTest(markdown=markdown):
                self.assertEqual(inline_links(markdown), [{'text': url, 'href': 'http://' + url}])

    def test_independent_source_and_container_contexts(self):
        path = Path(__file__).resolve().parents[3] / 'shared/fixtures/autolink-context-v1.json'
        for case in json.loads(path.read_text(encoding='utf-8'))['cases']:
            with self.subTest(case=case['name']):
                parsed = parse_markdown(case['markdown'])
                self.assertEqual([block.plain_text for block in parsed.blocks], case['plain_text'])
                self.assertEqual(''.join(parsed.source_parts()), case['markdown'])
                self.assertEqual(inline_links(case['markdown']), case['links'])

    def test_long_plain_candidates_and_nested_url_path(self):
        self.assertEqual(inline_links('httpſ://example.test'), [])
        plain = 'www.invalid_domain.test ' * 10000
        parsed = parse_markdown(plain)
        self.assertEqual(parsed.blocks[0].plain_text, plain.rstrip())
        self.assertEqual(inline_links(plain), [])
        path = 'www.example.test/' + 'www.example.test/' * 10000
        self.assertEqual(parse_markdown(path).blocks[0].plain_text, path)
        self.assertEqual(inline_links(path), [{'text': path, 'href': 'http://' + path}])

    def test_independent_unicode_url_domain_cases(self):
        path = Path(__file__).resolve().parents[3] / 'shared/fixtures/autolink-unicode-v1.json'
        for case in json.loads(path.read_text(encoding='utf-8'))['cases']:
            with self.subTest(case=case['name']):
                parsed = parse_markdown(case['markdown'])
                self.assertEqual([block.plain_text for block in parsed.blocks], case['plain_text'])
                self.assertEqual(inline_links(case['markdown']), case['links'])
                self.assertEqual(''.join(parsed.source_parts()), case['markdown'])
