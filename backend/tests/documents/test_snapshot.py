from copy import deepcopy
import unittest

from backend.app.documents.markdown import DocumentInvalid
from backend.app.documents.snapshot import Provenance, assign_identities, create_snapshot, validate_creation_inheritance, validate_snapshot, validate_template_lock
from backend.app.infrastructure.resources import ResourceCatalog

T0 = '2026-10-03T00:00:00.000Z'
T1 = '2026-10-03T00:00:01.000Z'
T2 = '2026-10-03T00:00:02.000Z'
TEMPLATE = Provenance('SYSTEM', 'TEMPLATE', None)
USER = Provenance('USER', 'MANUAL_EDIT', 42)
AI = Provenance('AI', 'SUGGESTION_BATCH', 77)


def sources(origin):
    # Pure algorithm fixture, not a database relationship guarantee.
    return origin in {TEMPLATE, USER, AI}


class SnapshotTests(unittest.TestCase):
    def test_initial_ids_metadata_and_detached_snapshot(self):
        snapshot = create_snapshot('# A\n\n正文\n', TEMPLATE, T0, sources)
        self.assertEqual(snapshot.next_block_id, 3)
        self.assertEqual(list(snapshot.by_id), [1, 2])
        metadata = snapshot.state['blocks'][0]
        self.assertEqual(metadata['created_source_id'], None)
        self.assertEqual(metadata['created_by_type'], 'SYSTEM')
        self.assertEqual(metadata['created_at'], T0)
        metadata['created_by_type'] = 'FORGED'
        self.assertEqual(snapshot.state['blocks'][0]['created_by_type'], 'SYSTEM')

    def test_full_shape_order_type_section_ids_and_real_calendar_time(self):
        snapshot = create_snapshot('# A\n\n正文\n', TEMPLATE, T0, sources)
        mutations = [
            lambda s: s.update(schema_version=True), lambda s: s.update(next_block_id=2),
            lambda s: s.update(unknown=True), lambda s: s['blocks'][1].update(block_id=1),
            lambda s: s['blocks'][0].update(block_type='paragraph'), lambda s: s['blocks'][1].update(section_path=[]),
            lambda s: s['blocks'][0].update(created_at='2026-02-30T00:00:00.000Z'),
            lambda s: s['blocks'][0].update(created_at=T1), lambda s: s['blocks'][0].update(created_source_id=1),
            lambda s: s['blocks'][0].update(last_modified_source_type='GUIDE_RUN', last_modified_source_id=501),
            lambda s: s['blocks'][0].pop('created_at'), lambda s: s['blocks'].reverse(),
        ]
        for index, mutate in enumerate(mutations):
            value = deepcopy(snapshot.state)
            mutate(value)
            with self.subTest(index=index), self.assertRaises(DocumentInvalid):
                validate_snapshot(snapshot.parsed.markdown, value, sources)

    def test_source_relationships_must_be_checked_and_not_truthy_coerced(self):
        snapshot = create_snapshot('正文\n', TEMPLATE, T0, sources)
        checked = []
        def verifier(origin):
            checked.append(origin)
            return True
        validate_snapshot('正文\n', snapshot.state, verifier)
        self.assertEqual(checked, [TEMPLATE, TEMPLATE])
        for verifier in (lambda _: False, lambda _: 1, lambda _: {'exists': True}):
            with self.assertRaises(DocumentInvalid):
                validate_snapshot('正文\n', snapshot.state, verifier)

    def test_edit_move_section_change_copy_split_merge_and_high_water(self):
        prior = create_snapshot('甲乙\n', TEMPLATE, T0, sources)
        split = assign_identities('甲\n\n乙\n', [1, 2], 3, prior, USER, T1, sources)
        self.assertEqual(split.by_id[1][1]['created_by_type'], 'SYSTEM')
        self.assertEqual(split.by_id[1][1]['last_modified_by_type'], 'USER')
        self.assertEqual(split.by_id[2][1]['created_source_id'], 42)
        merged = assign_identities('甲乙\n', [1], 3, split, USER, T2, sources)
        self.assertEqual(merged.next_block_id, 3)
        copied = assign_identities('甲乙\n\n甲乙\n', [1, 3], 4, merged, USER, T2, sources)
        self.assertEqual(copied.by_id[1][1]['created_at'], T0)
        self.assertEqual(copied.by_id[3][1]['created_at'], T2)
        moved = assign_identities('乙\n\n甲\n', [2, 1], 3, split, USER, T2, sources)
        self.assertEqual(moved.by_id[1][1]['last_modified_at'], T1)
        self.assertEqual(moved.by_id[2][1]['last_modified_at'], T1)
        headings = create_snapshot('# A\n\n甲\n\n# B\n', TEMPLATE, T0, sources)
        changed_section = assign_identities('# A\n\n# B\n\n甲\n', [1, 3, 2], 4, headings, AI, T1, sources)
        self.assertEqual(changed_section.by_id[2][1]['section_path'], ['B'])
        self.assertEqual(changed_section.by_id[2][1]['last_modified_by_type'], 'AI')

    def test_deleted_ids_can_return_only_with_retained_baseline_proof(self):
        initial = create_snapshot('甲\n\n乙\n', TEMPLATE, T0, sources)
        deleted = assign_identities('甲\n', [1], 3, initial, USER, T1, sources)
        with self.assertRaises(DocumentInvalid):
            assign_identities('甲\n\n乙\n', [1, 2], 3, deleted, USER, T2, sources)
        restored = assign_identities('甲\n\n乙\n', [1, 2], 3, deleted, USER, T2, sources, restoration_baseline=initial)
        self.assertEqual(restored.by_id[2][1]['created_at'], T0)
        self.assertEqual(restored.by_id[2][1]['last_modified_at'], T2)
        for ids, next_id in (([1, 2], 2), ([1, 1], 3), ([True, 2], 3)):
            with self.assertRaises(DocumentInvalid):
                assign_identities('甲\n\n乙\n', ids, next_id, initial, USER, T2, sources)

    def test_existing_creation_cannot_be_forged_and_backward_clock_rejected(self):
        prior = create_snapshot('甲\n', TEMPLATE, T1, sources)
        value = prior.state
        value['blocks'][0].update(USER.fields('created'))
        forged = validate_snapshot('甲\n', value, sources)
        with self.assertRaises(DocumentInvalid):
            validate_creation_inheritance(forged, prior)
        with self.assertRaises(DocumentInvalid):
            assign_identities('乙\n', [1], 2, prior, USER, T0, sources)
        unchanged = assign_identities('甲\n', [1], 2, prior, USER, T2, sources)
        self.assertEqual(unchanged.state, prior.state)

    def test_template_lock_checks_original_ids_levels_text_and_relative_order(self):
        template = ResourceCatalog().template('NEW', 'new-requirement', 'v1')
        snapshot = create_snapshot(template.markdown, TEMPLATE, T0, sources)
        ids = tuple(identity for identity, (block, _) in snapshot.by_id.items() if block.block_type == 'heading')
        validate_template_lock(snapshot, template, ids)
        changed = create_snapshot(template.markdown.replace('## 背景与目标', '### 背景与目标'), TEMPLATE, T0, sources)
        with self.assertRaises(DocumentInvalid):
            validate_template_lock(changed, template, ids)
        with self.assertRaises(DocumentInvalid):
            validate_template_lock(snapshot, template, tuple(reversed(ids)))
        with self.assertRaises(DocumentInvalid):
            validate_template_lock(snapshot, template, ids[:-1])
