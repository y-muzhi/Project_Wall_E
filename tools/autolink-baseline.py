"""Measure existing backend semantics against independent D-004/GFM cases."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.documents.markdown import _parser, parse_markdown  # noqa: E402


def main():
    path = Path(__file__).resolve().parents[1] / 'shared/fixtures/autolink-v1.json'
    records = []
    for entry in json.loads(path.read_text(encoding='utf-8'))['cases']:
        links = []
        for token in _parser().parse(entry['markdown'], {}):
            current = None
            for child in token.children or []:
                if child.type == 'link_open':
                    current = {'text': '', 'href': child.attrGet('href')}
                elif child.type == 'link_close':
                    if current is None:
                        raise AssertionError('Link close without open')
                    links.append(current)
                    current = None
                elif current is not None:
                    current['text'] += child.content
        parsed = parse_markdown(entry['markdown'])
        if len(parsed.blocks) != 1:
            raise AssertionError(f"{entry['name']}: fixture has no complete single block")
        actual = {'plain_text': parsed.blocks[0].plain_text, 'links': links}
        expected = {'plain_text': entry['plain_text'], 'links': entry['links']}
        records.append({'name': entry['name'], 'markdown': entry['markdown'], 'actual': actual,
                        'expected': expected, 'conforms': actual == expected})
    print(json.dumps({'scope': 'Observed backend baseline, not a conformance pass', 'records': records,
                      'mismatches': [record['name'] for record in records if not record['conforms']]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
