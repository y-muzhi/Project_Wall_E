"""TPL-001 future offline coverage; no live Provider or normal business DB."""
from pathlib import Path
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch

from backend.app.documents.markdown import parse_markdown
from backend.app.guide.counted_context import (
    counting_release_for_function, EXPANDED_RELEASE_SHA256, PRACTICAL_RELEASE_SHA256)
from backend.app.infrastructure.model_profile import ModelProfile, DEFAULT_PROFILE
from backend.app.infrastructure.practical_usage import validate_practical_usage
from backend.app.infrastructure.production_ai import before_count
from backend.app.infrastructure.resources import (
    ResourceCatalog, ConfigInvalid, DEFAULT_ROOT, V2_ROOT, V3_ROOT, V6_ROOT, V7_ROOT, V8_MANIFEST_SHA256, FUNCTIONS)
from backend.tests.requirements import test_create_requirement as creation

ROOT = Path(__file__).resolve().parents[3]
PROFILE = ModelProfile('offline-full-template-fixture', DEFAULT_PROFILE)


class FullTemplateResourceTests(unittest.TestCase):
    def test_source_bytes_heading_contract_and_creation_choices(self):
        catalog = ResourceCatalog()
        template = catalog.template('NEW', 'new-requirement', 'v4')
        self.assertEqual(template.markdown.encode('utf-8'), (ROOT / 'docs/templates/统一需求规格说明_完整模板_重构版.md').read_bytes())
        actual = [(block.heading_level, block.plain_text) for block in parse_markdown(template.markdown).blocks if block.block_type == 'heading']
        self.assertEqual(actual, [(heading.level, heading.text) for heading in template.locked_headings])
        self.assertEqual([(item['template_key'], item['template_version']) for item in catalog.frontend_catalog['templates']],
                         [('new-requirement', 'v4'), ('change-requirement', 'v1')])
        previous = catalog.template('NEW', 'new-requirement', 'v2')
        self.assertEqual(previous.markdown.encode('utf-8'), (V3_ROOT / 'templates/new-requirement.v2.md').read_bytes())
        self.assertEqual(actual, [(heading.level - 1, heading.text) for heading in previous.locked_headings[1:]])
        self.assertEqual(catalog.template('NEW', 'new-requirement', 'v3').markdown.encode('utf-8'), (V6_ROOT / 'templates/new-requirement.v3.md').read_bytes())
        legacy = ResourceCatalog(DEFAULT_ROOT)
        self.assertEqual(catalog.template('NEW', 'new-requirement', 'v1'), legacy.template('NEW', 'new-requirement', 'v1'))
        self.assertEqual(catalog.template('CHANGE', 'change-requirement', 'v1'), legacy.template('CHANGE', 'change-requirement', 'v1'))

    def test_all_full_template_actions_bind_new_budgets_and_old_runs_restore(self):
        catalog = ResourceCatalog()
        for template_version in ('v2', 'v3', 'v4'):
            for action, source in FUNCTIONS:
                old = catalog.restore(FUNCTIONS[(action, source)][0], 'v2')
                new = catalog.freeze(action, source, template_key='new-requirement', template_version=template_version)
                self.assertEqual(new.version, 'v9')
                self.assertEqual(new.manifest_sha256, V8_MANIFEST_SHA256)
                self.assertEqual(catalog.restore(new.function_type, 'v2'), old)
                self.assertEqual(new.output_schema_json, old.output_schema_json)
                self.assertIn('section_lookup', json.loads(new.input_schema_json)['properties'])
                self.assertEqual(new.context_policy['budget']['template_tokens'], 65536)
                self.assertEqual(new.context_policy['budget']['input_tokens'], 131072)
                self.assertEqual(new.context_policy['budget']['output_tokens'], 8192)
                old_release = counting_release_for_function(PROFILE, old)
                new_release = counting_release_for_function(PROFILE, new)
                self.assertEqual(new_release['budget'], new.context_policy['budget'])
                self.assertTrue(before_count(PROFILE, old, old_release))
                self.assertTrue(before_count(PROFILE, new, new_release))
                with self.assertRaises(ConfigInvalid): before_count(PROFILE, new, old_release)
                with self.assertRaises(ConfigInvalid): before_count(PROFILE, old, new_release)

    def test_modified_full_template_is_rejected_without_fallback(self):
        with tempfile.TemporaryDirectory(prefix='walle-full-template-') as directory:
            target = Path(directory) / 'v3'
            shutil.copytree(V3_ROOT, target)
            path = target / 'templates/new-requirement.v2.md'
            path.write_bytes(path.read_bytes() + b'\nchanged')
            with self.assertRaises(ConfigInvalid): ResourceCatalog(extended_root=target)
        with tempfile.TemporaryDirectory(prefix='walle-heading-template-') as directory:
            target = Path(directory) / 'v6'
            shutil.copytree(V6_ROOT, target)
            path = target / 'templates/new-requirement.v3.md'
            path.write_bytes(path.read_bytes() + b'\nchanged')
            with self.assertRaises(ConfigInvalid): ResourceCatalog(heading_root=target)
        with tempfile.TemporaryDirectory(prefix='walle-promoted-template-') as directory:
            target = Path(directory) / 'v7'
            shutil.copytree(V7_ROOT, target)
            path = target / 'templates/new-requirement.v4.md'
            path.write_bytes(path.read_bytes() + b'\nchanged')
            with self.assertRaises(ConfigInvalid): ResourceCatalog(promoted_heading_root=target)

    def test_actual_usage_uses_the_recorded_release_and_keeps_framing_gate(self):
        counts = [1000, 49000, 10, 0, 20000, 0]
        evidence = {'release_sha256': EXPANDED_RELEASE_SHA256, 'admission_mode': 'exact_text_empirical_framing_v1',
                    'compatibility_proved': False, 'input_tokens_candidate': 51024,
                    'count_attempts': [{'measurement': {'counts': counts}}]}
        raw = {'model': PROFILE.model_name, 'object': 'chat.completion',
               'usage': {'prompt_tokens': 50100, 'completion_tokens': 8192, 'total_tokens': 58292}}
        validate_practical_usage(raw, profile=PROFILE, counting=evidence, input_tokens=50100, output_tokens=8192)
        with self.assertRaises(ConfigInvalid):
            validate_practical_usage(raw, profile=PROFILE, counting={**evidence, 'release_sha256': PRACTICAL_RELEASE_SHA256}, input_tokens=50100, output_tokens=8192)
        raw['usage'] = {'prompt_tokens': 52000, 'completion_tokens': 8192, 'total_tokens': 60192}
        with self.assertRaises(ConfigInvalid):
            validate_practical_usage(raw, profile=PROFILE, counting=evidence, input_tokens=52000, output_tokens=8192)


class FullTemplateCreationTests(unittest.TestCase):
    def test_rejected_old_catalog_request_succeeds_with_same_key_after_catalog_update(self):
        from backend.app.requirements.commands import create_requirement
        fixture = creation.CreateRequirementTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        payload = fixture.payload(template_version='v2')
        old = ResourceCatalog(DEFAULT_ROOT, versioned_root=V2_ROOT)
        with patch('socket.socket.connect', side_effect=AssertionError('No Provider I/O')):
            rejected = create_requirement(fixture.executor, payload, catalog=old, clock=lambda: creation.INSTANT)
            self.assertEqual(rejected['code'], 'TEMPLATE_INVALID')
            accepted = create_requirement(fixture.executor, payload, catalog=ResourceCatalog(), clock=lambda: creation.INSTANT)
        self.assertEqual(accepted['code'], 'CREATED', accepted)
        with fixture.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM requirements').fetchone()[0], 1)
            self.assertEqual(connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0], 0)

    def test_full_template_creation_freezes_expanded_protocol_without_provider_io(self):
        catalog = ResourceCatalog()
        from backend.app.requirements.commands import create_requirement
        from backend.app.documents.queries import get_current_document
        fixture = creation.CreateRequirementTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with patch('socket.socket.connect', side_effect=AssertionError('No Provider I/O')):
            result = create_requirement(fixture.executor, fixture.payload(template_version='v4'), catalog=catalog, clock=lambda: creation.INSTANT)
        self.assertEqual(result['code'], 'CREATED', result)
        current = get_current_document(fixture.database, result['data']['requirement']['id'], catalog=catalog)['data']
        self.assertEqual(current['markdown_content'], catalog.template('NEW', 'new-requirement', 'v4').markdown)
        with fixture.database.transaction() as connection:
            run = connection.execute('SELECT prompt_version,context_template_version FROM guide_runs').fetchone()
            self.assertEqual(tuple(run), ('v9', 'v9'))
            self.assertEqual(connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0], 0)
