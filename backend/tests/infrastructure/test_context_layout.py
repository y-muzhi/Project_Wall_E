"""CTX-001 future offline coverage; written but not executed this iteration."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from backend.app.guide.context_builder import (
    assemble_input, serialize_input, transport_input, restore_transport_input)
from backend.app.guide.counted_context import (
    compile_counted_candidate, counting_release_for_function, verify_counting_evidence)
from backend.app.guide.model_context import get_model_context
from backend.app.infrastructure.audit_repository import AuditRepository, verify_actual_context
from backend.app.infrastructure.model_profile import ModelProfile, DEFAULT_PROFILE
from backend.app.infrastructure.production_ai import before_count, before_send
from backend.app.infrastructure.resources import (
    ResourceCatalog, ConfigInvalid, FUNCTIONS, DEFAULT_ROOT, V2_ROOT, V3_ROOT, V4_ROOT, STABLE_FIELD_ORDER)
from backend.app.infrastructure.schema_transport import compact
from backend.app.infrastructure.tokenization import TokenCounts
from backend.app.shared.command_execution import Rejected
from backend.tests.requirements import test_create_requirement as creation

PROFILE = ModelProfile('offline-context-layout-fixture', DEFAULT_PROFILE)


def layout_catalog():
    # CTX-001 remains a historical v4/v5 deployment, independently of FLOW-002.
    return ResourceCatalog(DEFAULT_ROOT, versioned_root=V2_ROOT, extended_root=V3_ROOT, layout_root=V4_ROOT)


class FixtureCounter:
    """Synthetic receipts exercise replay; no token accuracy/provider claim."""
    def __init__(self, measurements=None):
        self.texts = []
        self.measurements = measurements

    async def count(self, profile, texts):
        self.texts.append(texts)
        counts = (1000, 5000, 100, 10, 100, 10) if self.measurements is None else self.measurements(texts)
        raw = {'id': 'layout-fixture-' + str(len(self.texts)), 'object': 'list',
            'model': profile.model_name, 'created': 1791289200,
            'data': [{'object': 'tokenization', 'index': index, 'total_tokens': count,
                'token_ids': [0] * count, 'offset_mapping': [[0, 0] for _ in range(count)]}
                for index, count in enumerate(counts)]}
        return TokenCounts(profile.model_name, raw['id'], raw['created'], tuple(counts),
            tuple(hashlib.sha256(text.encode('utf-8')).hexdigest() for text in texts),
            hashlib.sha256(compact({'model': profile.model_name, 'text': list(texts)}).encode('utf-8')).hexdigest(), compact(raw))


class ContextLayoutTests(unittest.IsolatedAsyncioTestCase):
    def actual(self, template_version='v1'):
        fixture = creation.CreateRequirementTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.catalog = layout_catalog()
        accepted = fixture.create(template_version=template_version)
        self.assertEqual(accepted['code'], 'CREATED', accepted)
        identity = accepted['data']['guide_run_id']
        data = get_model_context(fixture.database, identity, catalog=fixture.catalog)['data']
        function = fixture.catalog.restore(data['run']['function_type'], data['run']['prompt_version'])
        return fixture, identity, data, function

    def test_two_budget_sets_and_all_historical_releases_remain_distinct(self):
        catalog = layout_catalog()
        for action, source in FUNCTIONS:
            ordinary = catalog.freeze(action, source)
            full = catalog.freeze(action, source, template_key='new-requirement', template_version='v2')
            self.assertEqual((ordinary.version, full.version), ('v4', 'v5'))
            for current, previous in ((ordinary, 'v2'), (full, 'v3')):
                old = catalog.restore(current.function_type, previous)
                self.assertIsNone(old.transport_input_schema_json)
                self.assertEqual(current.context_policy['budget'], old.context_policy['budget'])
                self.assertEqual(current.output_schema_json, old.output_schema_json)
                release = counting_release_for_function(PROFILE, current)
                self.assertTrue(before_count(PROFILE, current, release))
                with self.assertRaises(ConfigInvalid):
                    before_count(PROFILE, old, release)
            self.assertIsNone(catalog.restore(ordinary.function_type, 'v1').transport_input_schema_json)

    def test_roundtrip_preserves_every_fact_and_moves_volatile_identity_after_input(self):
        fixture, identity, data, function = self.actual()
        canonical = assemble_input(data, function)
        before = deepcopy(canonical)
        wire = transport_input(canonical, function)
        self.assertEqual(tuple(wire), STABLE_FIELD_ORDER)
        self.assertEqual(restore_transport_input(wire, function), canonical)
        changed = deepcopy(canonical)
        changed['user_input']['message_id'] += 100
        changed['user_input']['content'] = '新的输入'
        changed['current_document']['content_version'] += 1
        changed['template']['locked_heading_block_ids'] = []
        prefix = lambda value: serialize_input(value, function).split(',"user_input":', 1)[0]
        self.assertEqual(prefix(canonical), prefix(changed))
        self.assertEqual(canonical, before)
        broken = deepcopy(wire)
        broken['request_metadata']['read_block_metadata'].pop()
        with self.assertRaises(ValueError): restore_transport_input(broken, function)

    def test_actual_audit_rejects_repaired_or_swapped_identity_pairs(self):
        fixture, identity, data, function = self.actual()
        canonical = assemble_input(data, function)
        wire = transport_input(canonical, function)
        system = function.prompt + '\n' + compact(json.loads(function.output_schema_json))
        with fixture.database.transaction() as connection:
            _, supplied = verify_actual_context(connection, identity, function, wire, system,
                compact(canonical['read_manifest']), fixture.catalog)
            self.assertEqual(supplied, canonical)
            broken = deepcopy(wire)
            metadata = broken['request_metadata']['read_block_metadata']
            metadata[0], metadata[1] = metadata[1], metadata[0]
            with self.assertRaises(Rejected):
                verify_actual_context(connection, identity, function, broken, system,
                    compact(canonical['read_manifest']), fixture.catalog)

    async def test_both_budget_requests_count_send_and_audit_the_identical_wire(self):
        for template_version in ('v1', 'v2'):
            fixture, identity, data, function = self.actual(template_version)
            counter = FixtureCounter()
            context = await compile_counted_candidate(data, function, PROFILE, counter=counter)
            self.assertEqual(counter.texts[-1][:2], (context.system, context.input_json))
            self.assertTrue(before_send(PROFILE, context, function))
            with fixture.database.transaction(write=True) as connection:
                row = AuditRepository(connection).prepare(identity, function, PROFILE, context,
                    data['run']['created_at'], catalog=fixture.catalog)
                snapshot = json.loads(row['request_snapshot_json'])
                self.assertEqual(snapshot['request']['messages'][1]['content'], context.input_json)
                self.assertEqual(snapshot['protocol']['input_schema'], function.model_input_schema)

    async def test_history_trim_rebuilds_both_content_and_refs_and_replays_counts(self):
        fixture, identity, data, function = self.actual()
        # Explicit synthetic history tests the compiler only, not actual DB ownership.
        data = deepcopy(data)
        data['history'] = [{'id': 900, 'sequence_no': 1, 'role': 'USER', 'message_type': 'TEXT',
            'content': '早期历史', 'structured_content': None}]
        data['read_manifest']['message_ids'] = [900, data['user_input']['id']]
        counter = FixtureCounter(lambda texts: (1000, 5000, 100, 10, 100, 2049 if json.loads(texts[5]) else 10))
        context = await compile_counted_candidate(data, function, PROFILE, counter=counter)
        self.assertEqual(context.removed_history_ids, (900,))
        self.assertEqual(context.input['history'], [])
        self.assertEqual(context.input['request_metadata']['history_message_refs'], [])
        supplied = verify_counting_evidence(data, function, system=context.system,
            input_json=context.input_json, manifest_json=context.manifest_json,
            evidence=context.counting_evidence, profile=PROFILE)
        self.assertEqual(supplied['read_manifest']['message_ids'], [data['user_input']['id']])

    def test_manifest_content_tampering_never_falls_back_to_old_layout(self):
        with tempfile.TemporaryDirectory(prefix='walle-context-layout-') as directory:
            target = Path(directory) / 'v4'
            shutil.copytree(V4_ROOT, target)
            path = target / 'contexts/ASK_CONTEXT.v4.json'
            path.write_bytes(path.read_bytes() + b'changed')
            with self.assertRaises(ConfigInvalid): ResourceCatalog(layout_root=target)
