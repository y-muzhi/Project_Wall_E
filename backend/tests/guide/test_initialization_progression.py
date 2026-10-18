"""FLOW-002 resources and FLOW-003 direct display; no provider I/O."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from uuid import uuid4

from backend.app.guide import commands
from backend.app.guide.context_builder import assemble_input, build_context
from backend.app.guide.trusted_output import validate_business_output
from backend.app.guide.model_context import get_model_context
from backend.app.guide.orchestrator import execute_guide_run
from backend.app.guide.output_evidence import card_text, fact_declaration
from backend.app.documents.patch_validation import validate_patch
from backend.app.documents.scopes import resolve_scope
from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.guide.counted_context import counting_release_for_function, compile_counted_candidate
from backend.app.infrastructure.model_gateway import TransportResult
from backend.app.infrastructure.model_profile import ModelProfile, DEFAULT_PROFILE
from backend.app.infrastructure.production_ai import before_count, before_send
from backend.app.infrastructure.resources import ResourceCatalog, ConfigInvalid, FUNCTIONS, DEFAULT_ROOT, V2_ROOT, V3_ROOT, V4_ROOT, V5_ROOT
from backend.tests.guide import test_trusted_output as proof
from backend.tests.guide.test_result_persistence import patch
from backend.tests.infrastructure.test_context_layout import FixtureCounter
from backend.tests.messages.test_queries import cards_fixture
from backend.tests.requirements import test_create_requirement as creation


class ProgressionResourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_initialization_budgets_wire_counts_and_all_historical_versions(self):
        catalog = ResourceCatalog(DEFAULT_ROOT, versioned_root=V2_ROOT, extended_root=V3_ROOT, layout_root=V4_ROOT, progression_root=V5_ROOT)
        profile = ModelProfile('offline-flow-fixture', DEFAULT_PROFILE)
        for template_version, version, previous in (('v1', 'v6', 'v4'), ('v2', 'v7', 'v5')):
            function = catalog.freeze('INITIALIZE', 'USER_INSTRUCTION', template_key='new-requirement', template_version=template_version)
            old = catalog.restore(function.function_type, previous)
            self.assertEqual(function.version, version)
            self.assertEqual(function.context_policy['budget'], old.context_policy['budget'])
            self.assertEqual(function.input_schema_json, old.input_schema_json)
            self.assertEqual(function.output_schema_json, old.output_schema_json)
            self.assertLess(len(function.prompt.encode('utf-8')), len(old.prompt.encode('utf-8')))
            for historical in ('v1', 'v2', 'v3', 'v4', 'v5'):
                self.assertNotIn('initialization_progression', catalog.restore(function.function_type, historical).context_policy)
            self.assertTrue(before_count(profile, function, counting_release_for_function(profile, function)))
            with self.assertRaises(ConfigInvalid):
                before_count(profile, old, counting_release_for_function(profile, function))
            fixture = creation.CreateRequirementTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
            fixture.catalog = catalog
            created = fixture.create(template_version=template_version)
            self.assertEqual(created['code'], 'CREATED', created)
            context = get_model_context(fixture.database, created['data']['guide_run_id'], catalog=catalog)['data']
            counter = FixtureCounter()
            counted = await compile_counted_candidate(context, function, profile, counter=counter)
            self.assertEqual(counter.texts[-1][:2], (counted.system, counted.input_json))
            self.assertTrue(before_send(profile, counted, function))
        for action, source in FUNCTIONS:
            if action != 'INITIALIZE':
                self.assertEqual(catalog.freeze(action, source).version, 'v4')
                self.assertEqual(catalog.freeze(action, source, template_key='new-requirement', template_version='v2').version, 'v5')

    def test_changed_progression_resource_refuses_without_fallback(self):
        with tempfile.TemporaryDirectory(prefix='walle-flow-resource-') as directory:
            target = Path(directory) / 'v5'
            shutil.copytree(V5_ROOT, target)
            path = target / 'prompts/INITIALIZE_REQUIREMENT.v7.md'
            path.write_bytes(path.read_bytes() + b'changed')
            with self.assertRaises(ConfigInvalid):
                ResourceCatalog(progression_root=target)


class ProgressionFixture:
    def setUp(self):
        self.helper = proof.TrustedOutputTests(); self.helper.setUp(); self.addCleanup(self.helper.doCleanups)
        self.fixture = self.helper.fixture
        f = self.fixture
        outcome = commands.cancel_guide_run(f.executor, {'guide_run_id': f.run, 'idempotency_key': str(uuid4())}, clock=lambda: creation.INSTANT)
        self.assertEqual(outcome['code'], 'GUIDE_CANCELLED', outcome)
        f.catalog = ResourceCatalog()
        accepted = commands.create_guide_run(f.executor, {'requirement_id': f.req, 'expected_content_version': 1,
            'action_type': 'INITIALIZE', 'instruction': '目标是需求澄清，仓库是单一固定仓库', 'scope_type': 'DOCUMENT',
            'source_type': 'USER_INSTRUCTION', 'idempotency_key': str(uuid4())}, catalog=f.catalog, clock=lambda: creation.INSTANT)
        self.assertEqual(accepted['code'], 'GUIDE_ACCEPTED', accepted)
        f.run = accepted['data']['guide_run']['id']; self.helper.compile(); self.seconds = 0

    def cards(self, question='仓库范围是什么？', *, required=True):
        value = cards_fixture(); card = value['cards'][0]
        card.update(question=question, required=required, related_spec_context=[])
        return value

    def output(self, cards):
        return {'schema_version': 1, 'response_type': 'INITIALIZE_CARDS', 'message': card_text(cards),
            'cards': cards, 'confirmed_fact_patches': []}

    def persist(self, output):
        base = self.seconds; self.seconds += 6
        identity = self.helper.candidate(output, base=base)
        receipt = self.helper.produce(identity, seconds=base+4)
        self.assertIsNotNone(receipt)
        result = commands.persist_ai_result(self.fixture.database, {'guide_run_id': self.fixture.run,
            'llm_use_id': identity, 'trusted_output': receipt}, process_lock=self.fixture.lock,
            profile=self.fixture.profile, catalog=self.fixture.catalog, clock=lambda: creation.INSTANT+timedelta(seconds=base+5))
        self.assertEqual(result['code'], 'AI_RESULT_PERSISTED', result)
        return result['data']['assistant_message_id']

    def answer(self, message_id, *, selection='b', skipped=False):
        f = self.fixture
        parent = json.loads(f.row('conversation_messages', message_id)['structured_content_json'])
        result = commands.submit_card_responses(f.executor, {'message_id': message_id, 'schema_version': 1,
            'responses': [{'card_key': parent['cards'][0]['card_key'], 'selected_option_keys': [] if skipped else [selection],
                'custom_answer': None, 'skipped': skipped}], 'idempotency_key': str(uuid4())},
            catalog=f.catalog, clock=lambda: creation.INSTANT+timedelta(seconds=self.seconds))
        self.assertEqual(result['code'], 'CARDS_ACCEPTED', result)
        f.run = result['data']['guide_run']['id']
        if result['data']['guide_run']['status'] == 'RUNNING': self.helper.compile()
        return result['data']['response_message']

    def actual(self):
        data = get_model_context(self.fixture.database, self.fixture.run, catalog=self.fixture.catalog)['data']
        return data, assemble_input(data, self.fixture.function)

    def check(self, output, *, supplied=None, function=None):
        actual, value = self.actual()
        with self.fixture.database.transaction() as connection:
            validate_business_output(connection, output=output, function=function or self.fixture.function,
                actual=actual, supplied=value if supplied is None else supplied, catalog=self.fixture.catalog)


class ProgressionGateTests(ProgressionFixture, unittest.TestCase):
    def test_answered_question_is_accepted_even_with_changed_key_or_display_whitespace(self):
        message = self.persist(self.output(self.cards()))
        answer = self.answer(message)
        self.assertIn('仓库范围是什么？\nb', answer['content'])
        repeat = self.cards(' 仓库 范围 是什么? ')
        repeat['cards'][0]['card_key'] = 'changed_key'
        self.check(self.output(repeat))
        identity = self.helper.candidate(self.output(repeat), base=self.seconds)
        self.assertIsNotNone(self.helper.produce(identity, seconds=self.seconds+4))
        row = self.fixture.row('llm_uses', identity)
        self.assertIsNone(row['validation_error'])
        self.assertIsNotNone(row['trusted_output_json'])

    def test_new_question_same_key_allowed_and_ordinary_choice_never_writes_fact(self):
        message = self.persist(self.output(self.cards())); self.answer(message)
        self.check(self.output(self.cards('仓库采用什么语言？')))
        self.persist(self.output(self.cards('仓库采用什么语言？')))
        self.assertEqual(self.fixture.row('requirement_documents', self.fixture.created['current_document_id'])['content_version'], 1)

    def test_skipped_and_unsent_answers_do_not_block_and_historical_protocol_unchanged(self):
        message = self.persist(self.output(self.cards(required=False))); self.answer(message, skipped=True)
        self.check(self.output(self.cards()))
        # Display no longer depends on answered-question history being sent.
        self.persist(self.output(self.cards()))
        with self.fixture.database.transaction() as c:
            parent_id = c.execute("SELECT max(id) FROM conversation_messages WHERE message_type='INTERACTION_CARDS'").fetchone()[0]
        self.answer(parent_id)
        actual, supplied = self.actual()
        supplied['read_manifest']['message_ids'] = []
        self.check(self.output(self.cards()), supplied=supplied)
        self.check(self.output(self.cards()), function=self.fixture.catalog.restore('INITIALIZE_REQUIREMENT', 'v5'))

    def test_choice_then_full_confirmation_is_adopted_directly_without_extra_model_attempt(self):
        message = self.persist(self.output(self.cards())); self.answer(message)
        f = self.fixture; actual, value = self.actual()
        with f.database.transaction() as c:
            current = actual['current_document']
            snapshot = validate_snapshot(current['markdown_content'], current['block_state_json'], DocumentSources(c, f.req, f.catalog))
            authority = resolve_scope(snapshot, 'INITIALIZE', 'DOCUMENT')
            candidate = patch(snapshot, 3, proposed='仓库范围为单一固定仓库。\n')
            declaration = fact_declaration(snapshot, validate_patch(snapshot, candidate, authority))
        cards = self.cards(); card = cards['cards'][0]
        card.update(card_type='CONFIRM', question=declaration+'\n是否确认以上事实和变更写入需求？',
            options=[{'option_key': key, 'label': label, 'description': '', 'impact': '', 'risks': ''}
                for key, label in (('confirm', '确认以上事实和变更'), ('defer', '尚未确认'))],
            custom_answer={'enabled': False, 'max_length': 0}, recommendation=None,
            related_spec_context=[{'block_id': 3, 'content_snapshot': snapshot.by_id[3][0].markdown}])
        confirm_id = self.persist(self.output(cards))
        with f.database.transaction() as connection:
            calls_before = connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0]
        self.answer(confirm_id, selection='confirm')
        self.assertEqual(f.row('guide_runs', f.run)['status'], 'COMPLETED')
        with f.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0], calls_before)
        updated = f.row('requirement_documents', f.created['current_document_id'])
        self.assertEqual(updated['content_version'], 2)
        self.assertIn('仓库范围为单一固定仓库', updated['markdown_content'])


class ProgressionOrchestratorTests(ProgressionFixture, unittest.IsolatedAsyncioTestCase):
    async def test_repeated_question_is_displayed_after_one_attempt_without_body_write(self):
        message = self.persist(self.output(self.cards())); self.answer(message)
        f = self.fixture; calls = []; delays = []
        raw = f.response(json.dumps(self.output(self.cards()), ensure_ascii=False))
        class Gateway:
            async def send(self, profile, context):
                calls.append(context)
                return TransportResult(True, None, False, 200, None, 1, json.dumps(raw), finish_reason='stop')
        def compile_context(actual, function):
            policy = function.context_policy; policy['budget'].update(prompt_tokens=100000, input_tokens=100000, total_tokens=120000)
            return build_context(actual, replace(function, context_json=json.dumps(policy)))
        async def sleep(seconds): delays.append(seconds)
        result = await execute_guide_run(f.database, {'guide_run_id': f.run}, process_lock=f.lock,
            profile=f.profile, catalog=f.catalog, gateway=Gateway(), context_compiler=compile_context,
            compatibility_check=lambda *args: True, clock=lambda: creation.INSTANT+timedelta(seconds=self.seconds+10), sleep=sleep)
        self.assertEqual(result['code'], 'AI_FINISHED', result)
        self.assertEqual(len(calls), 1); self.assertEqual(delays, [])
        self.assertIsNone(f.row('guide_runs', f.run)['error_message'])
        self.assertEqual(f.row('requirement_documents', f.created['current_document_id'])['content_version'], 1)
        with f.database.transaction() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM llm_uses WHERE guide_run_id=?', (f.run,)).fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT count(*) FROM conversation_messages WHERE guide_run_id=? AND role='ASSISTANT'", (f.run,)).fetchone()[0], 1)
