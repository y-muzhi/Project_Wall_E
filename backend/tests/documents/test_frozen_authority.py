from copy import deepcopy
import json
import unittest

from backend.app.documents.patch_errors import TargetStale
from backend.app.documents.patch_validation import validate_patch
from backend.app.documents.scopes import ScopeInvalid, resolve_scope, restore_authority
from backend.app.documents.snapshot import create_snapshot
from backend.app.documents.tables import table_model
from backend.tests.documents.test_patch_validation import patch
from backend.tests.documents.test_snapshot import TEMPLATE, T0, sources


class FrozenAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = create_snapshot('# A\n\n正文\n\n| 键 | 值 |\n| --- | --- |\n| X | 一 |\n| Y | 二 |\n\n# B\n', TEMPLATE, T0, sources)

    def test_server_generated_envelope_round_trip_and_detached_projections(self):
        resolved = resolve_scope(self.snapshot, 'MODIFY', 'SECTION', {'block_id': 1})
        frozen = restore_authority(self.snapshot, 'MODIFY', 'SECTION', {'block_id': 1}, resolved.authority_json)
        self.assertEqual(frozen.allowed_targets, resolved.allowed_targets)
        state = json.loads(frozen.state_json)
        self.assertEqual(state['schema_version'], 1)
        state['targets'][0]['operations'].append('INSERT_BEFORE')
        self.assertNotIn('INSERT_BEFORE', frozen.allowed_targets[0].operations)
        for action in ('ASK', 'REVIEW'):
            empty = resolve_scope(self.snapshot, action, 'DOCUMENT')
            self.assertEqual(restore_authority(self.snapshot, action, 'DOCUMENT', None, empty.authority_json).allowed_targets, ())

    def test_strict_structure_duplicates_integers_and_missing_are_not_repaired(self):
        resolved = resolve_scope(self.snapshot, 'MODIFY', 'DOCUMENT')
        baseline = json.loads(resolved.authority_json)
        mutations = (lambda s: s.update(schema_version=True), lambda s: s.update(schema_version=2), lambda s: s.update(extra=True), lambda s: s.pop('targets'), lambda s: s['targets'][0].update(block_id=1.0), lambda s: s['targets'][0].pop('row_selectors'), lambda s: s['targets'].append(s['targets'][0]), lambda s: s['targets'][0]['operations'].append('REPLACE_BLOCK'))
        for index, mutate in enumerate(mutations):
            value = deepcopy(baseline)
            mutate(value)
            with self.subTest(index=index), self.assertRaises(ScopeInvalid):
                restore_authority(self.snapshot, 'MODIFY', 'DOCUMENT', None, value)
        for content in ('{"schema_version":1,"schema_version":1,"targets":[]}', '```json\n{}\n```', '[]'):
            with self.assertRaises(ScopeInvalid):
                restore_authority(self.snapshot, 'MODIFY', 'DOCUMENT', None, content)

    def test_frozen_grants_cannot_expand_scope_or_read_only_action(self):
        all_targets = json.loads(resolve_scope(self.snapshot, 'MODIFY', 'DOCUMENT').authority_json)
        for action, kind, ref in (('ASK', 'DOCUMENT', None), ('REVIEW', 'DOCUMENT', None), ('MODIFY', 'BLOCK', {'block_id': 2}), ('MODIFY', 'SECTION', {'block_id': 1})):
            with self.subTest(action=action, kind=kind), self.assertRaises(ScopeInvalid):
                restore_authority(self.snapshot, action, kind, ref, all_targets)
        narrowed = {'schema_version': 1, 'targets': [all_targets['targets'][1]]}
        narrowed['targets'][0]['operations'] = ['REPLACE_BLOCK']
        frozen = restore_authority(self.snapshot, 'MODIFY', 'BLOCK', {'block_id': 2}, narrowed)
        validate_patch(self.snapshot, patch(self.snapshot, 2), frozen)
        with self.assertRaises(TargetStale):
            validate_patch(self.snapshot, patch(self.snapshot, 2, 'DELETE_BLOCK', None), frozen)

    def test_selection_range_must_match_original_codepoints_and_only_replace(self):
        ref = {'block_id': 2, 'selected_text': '文', 'prefix_text': '正', 'suffix_text': ''}
        state = json.loads(resolve_scope(self.snapshot, 'MODIFY', 'SELECTION', ref).authority_json)
        frozen = restore_authority(self.snapshot, 'MODIFY', 'SELECTION', ref, state)
        self.assertEqual(frozen.allowed_targets[0].selection_range, (1, 2))
        for update in ({'selection_range': None}, {'selection_range': {'start_offset': 0, 'end_offset': 2}}, {'operations': ['DELETE_BLOCK']}):
            value = deepcopy(state)
            value['targets'][0].update(update)
            with self.assertRaises(ScopeInvalid):
                restore_authority(self.snapshot, 'MODIFY', 'SELECTION', ref, value)

    def test_row_whitelist_empty_is_no_rows_and_exact_keys_only(self):
        ref = {'block_id': 3}
        state = json.loads(resolve_scope(self.snapshot, 'MODIFY', 'BLOCK', ref).authority_json)
        entry = state['targets'][0]
        entry['operations'] = ['REPLACE_TABLE_ROW']
        entry['row_selectors'] = [{'key_column_index': 0, 'key_value': 'X'}]
        frozen = restore_authority(self.snapshot, 'MODIFY', 'BLOCK', ref, state)
        table = table_model(self.snapshot.by_id[3][0])
        for row in table.rows:
            value = patch(self.snapshot, 3, 'REPLACE_TABLE_ROW', None, {'key_column_index': 0, 'key_value': row.cells[0]}, {'cells': [row.cells[0], '替换']}, row.markdown)
            if row.cells[0] == 'X':
                validate_patch(self.snapshot, value, frozen)
            else:
                with self.assertRaises(TargetStale):
                    validate_patch(self.snapshot, value, frozen)
        entry['row_selectors'] = []
        empty = restore_authority(self.snapshot, 'MODIFY', 'BLOCK', ref, state)
        with self.assertRaises(TargetStale):
            validate_patch(self.snapshot, value, empty)
        for selectors in ([{'key_column_index': 1, 'key_value': '一'}], [{'key_column_index': 0, 'key_value': '不存在'}], [{'key_column_index': 0, 'key_value': 'X'}] * 2):
            entry['row_selectors'] = selectors
            with self.assertRaises(ScopeInvalid):
                restore_authority(self.snapshot, 'MODIFY', 'BLOCK', ref, state)
