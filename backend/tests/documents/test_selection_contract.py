import json
from pathlib import Path
import unittest

from backend.app.documents.anchors import locate
from backend.app.documents.snapshot import create_snapshot
from backend.tests.documents.test_snapshot import TEMPLATE, T0, sources


class SelectionContractTests(unittest.TestCase):
    def test_shared_frontend_offsets_match_backend_real_markdown_projection(self):
        path = Path(__file__).resolve().parents[3] / 'shared/fixtures/selection-v1.json'
        fixture = json.loads(path.read_text(encoding='utf-8'))
        for item in fixture['cases']:
            with self.subTest(case=item['name']):
                snapshot = create_snapshot(item['markdown'], TEMPLATE, T0, sources)
                self.assertEqual(snapshot.by_id[1][0].plain_text, item['plain_text'])
                ref = {key: item[key] for key in ('selected_text', 'prefix_text', 'suffix_text')}
                location = locate(snapshot, 'SELECTION', 1, ref)
                self.assertTrue(location.attached)
                self.assertEqual((location.start_offset, location.end_offset), (item['start_offset'], item['end_offset']))
