from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from backend.app.infrastructure.resources import ConfigInvalid, DEFAULT_ROOT, FrozenFunction, MANIFEST_SHA256, ProtocolInvalid, ResourceCatalog, TemplateInvalid

EXPECTED = [
    ('INITIALIZE_REQUIREMENT', 'INITIALIZE', 'USER_INSTRUCTION', 'INITIALIZE'),
    ('ANSWER_REQUIREMENT', 'ASK', 'USER_INSTRUCTION', 'ASK'),
    ('REVIEW_REQUIREMENT', 'REVIEW', 'USER_INSTRUCTION', 'REVIEW'),
    ('MODIFY_REQUIREMENT', 'MODIFY', 'USER_INSTRUCTION', 'MODIFY'),
    ('MODIFY_FROM_REVIEW', 'MODIFY', 'REVIEW_RESULT', 'MODIFY_FROM_REVIEW'),
    ('MODIFY_FROM_COMMENT', 'MODIFY', 'COMMENT', 'MODIFY_FROM_COMMENT'),
]


def structural_input(function_type, action, source_type, context):
    """Independent structural fixture; not a complete business context proof."""
    source = None
    source_id = None
    if source_type == 'REVIEW_RESULT':
        source_id = 500
        source = {'guide_run_id': 500, 'reviewed_content_version': 2, 'review_result': {'schema_version': 1, 'summary': '需补审批人', 'issues': []}}
    elif source_type == 'COMMENT':
        source_id = 901
        source = {'comment_id': 901, 'content': '请说明审批人', 'anchor_type': 'BLOCK', 'block_id': 2, 'anchor_ref': {'block_markdown_snapshot': '待确认。'}, 'current_location': None}
    return {
        'schema_version': 1, 'function_type': function_type, 'action_type': action, 'source_type': source_type,
        'requirement': {'id': 101, 'requirement_no': 'REQ000001', 'requirement_type': 'NEW', 'title': '需求甲', 'status': 'INITIALIZING' if action == 'INITIALIZE' else 'ACTIVE', 'initialization_mode': 'IDEATION'},
        'current_document': {'id': 201, 'content_version': 3, 'read_blocks': []},
        'template': {'template_key': 'new-requirement', 'template_version': 'v1', 'markdown_content': '# 需求新增规格\n', 'locked_heading_block_ids': []},
        'scope': {'scope_type': 'DOCUMENT', 'scope_ref': None}, 'allowed_targets': [],
        'user_input': {'message_id': 601, 'content': '整理需求', 'formal_responses': None}, 'history': [], 'source': source,
        'read_manifest': {'document_id': 201, 'content_version': 3, 'block_ids': [], 'message_ids': [601], 'template': {'key': 'new-requirement', 'version': 'v1'}, 'source': {'source_type': source_type, 'source_id': source_id}, 'context_template': {'key': context + '_CONTEXT', 'version': 'v1'}, 'prompt': {'key': function_type, 'version': 'v1'}, 'function_type': function_type},
    }


def output(response_type, **fields):
    return {'schema_version': 1, 'response_type': response_type, 'message': '已处理', **fields}


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.catalog = ResourceCatalog(DEFAULT_ROOT)  # exact historical v1 release

    def test_all_six_mappings_freeze_and_restore_without_version_fallback(self):
        for name, action, source, context in EXPECTED:
            with self.subTest(name=name):
                function = self.catalog.freeze(action, source)
                self.assertIsInstance(function, FrozenFunction)
                self.assertEqual(function.function_type, name)
                self.assertEqual(function.prompt_reference, name + '@v1')
                self.assertEqual(function.context_template, context + '_CONTEXT@v1')
                self.assertEqual(function.manifest_sha256, MANIFEST_SHA256)
                self.assertEqual(function, self.catalog.restore(name, 'v1', prompt_version='v1', context_template=context + '_CONTEXT@v1'))
                with self.assertRaises(ConfigInvalid):
                    self.catalog.restore(name, 'v2')
                with self.assertRaises(ConfigInvalid):
                    self.catalog.restore(name, 'v1', prompt_version='v2')
        for action, source in (('ASK', 'COMMENT'), ('INITIALIZE', 'REVIEW_RESULT'), ('NEW', 'USER_INSTRUCTION')):
            with self.assertRaises(ConfigInvalid):
                self.catalog.freeze(action, source)

    def test_templates_complete_type_bound_and_immutable(self):
        for type_, key, expected_headings in (('NEW', 'new-requirement', 13), ('CHANGE', 'change-requirement', 15)):
            template = self.catalog.template(type_, key, 'v1')
            self.assertEqual(len(template.locked_headings), expected_headings)
            self.assertEqual(template.markdown.count('待确认。'), expected_headings - 1)
            for heading in template.locked_headings:
                self.assertIn('#' * heading.level + ' ' + heading.text + '\n', template.markdown)
            with self.assertRaises(FrozenInstanceError):
                template.markdown = 'replaced'
        for args in (('CHANGE', 'new-requirement', 'v1'), ('NEW', 'new-requirement', 'v2'), ('NEW', 'missing', 'v1')):
            with self.assertRaises(TemplateInvalid):
                self.catalog.template(*args)
        detached = self.catalog.frontend_catalog
        detached['templates'].clear()
        self.assertEqual(len(self.catalog.frontend_catalog['templates']), 2)

    def test_missing_tampered_file_or_manifest_refuses_startup(self):
        with tempfile.TemporaryDirectory(prefix='walle-resources-test-') as directory:
            target = Path(directory) / 'resources'
            shutil.copytree(DEFAULT_ROOT, target)
            self.assertEqual(ResourceCatalog(target).freeze('ASK', 'USER_INSTRUCTION').function_type, 'ANSWER_REQUIREMENT')
            prompt = target / 'prompts' / 'ANSWER_REQUIREMENT.v1.md'
            original = prompt.read_bytes()
            prompt.write_bytes(original + b'\nchanged')
            with self.assertRaises(ConfigInvalid):
                ResourceCatalog(target)
            prompt.write_bytes(original)
            prompt.unlink()
            with self.assertRaises(ConfigInvalid):
                ResourceCatalog(target)
            prompt.write_bytes(original)
            manifest = target / 'manifest.json'
            manifest.write_text('{}', encoding='utf-8')
            with self.assertRaises(ConfigInvalid):
                ResourceCatalog(target)

    def test_all_inputs_strict_integer_nested_fields_and_source_branches(self):
        for name, action, source, context in EXPECTED:
            with self.subTest(name=name):
                function = self.catalog.freeze(action, source)
                value = structural_input(name, action, source, context)
                self.assertEqual(function.validate_input(value), value)
                for version in (True, 1.0, '1'):
                    with self.assertRaises(ProtocolInvalid):
                        function.validate_input({**value, 'schema_version': version})
                invalid = deepcopy(value)
                invalid['requirement']['id'] = 101.0
                with self.assertRaises(ProtocolInvalid):
                    function.validate_input(invalid)
                invalid = deepcopy(value)
                invalid['user_input']['extra'] = 'must reject'
                with self.assertRaises(ProtocolInvalid):
                    function.validate_input(invalid)
                with self.assertRaises(ProtocolInvalid):
                    function.validate_input({**value, 'source': {} if source == 'USER_INSTRUCTION' else None})
                policy = function.context_policy
                policy['budget']['input_tokens'] = 1
                self.assertEqual(function.context_policy['budget']['input_tokens'], 24576)

    def test_independent_output_branches_for_all_tasks_and_safe_errors(self):
        patch = {'title': '明确审批人', 'explanation': '用户明确补充', 'impact': None, 'target_ref': {'block_id': 2}, 'original_content': '待确认。', 'patch_operation': 'REPLACE_BLOCK', 'selector_json': None, 'proposed_markdown': '审批人为部门经理。', 'proposed_data_json': None}
        option = {'option_key': 'yes', 'label': '是', 'description': '', 'impact': '', 'risks': ''}
        card = {'card_key': 'c1', 'card_type': 'CONFIRM', 'question': '是否已确定？', 'context': '', 'required': True, 'options': [option, {**option, 'option_key': 'no', 'label': '否'}], 'selection_rule': {'min': 1, 'max': 1}, 'custom_answer': {'enabled': False, 'max_length': 0}, 'recommendation': None, 'related_spec_context': []}
        cards = {'schema_version': 1, 'intro': '请确认', 'cards': [card]}
        for name, action, source, _ in EXPECTED:
            function = self.catalog.freeze(action, source)
            examples = {
                'INITIALIZE': [output('INITIALIZE_TEXT', confirmed_fact_patches=[]), output('INITIALIZE_CARDS', cards=cards, confirmed_fact_patches=[{'patch': patch, 'evidence': [{'message_id': 601, 'quoted_text': '审批人为部门经理'}]}])],
                'ASK': [output('ANSWER'), output('CLARIFY_TEXT'), output('CLARIFY_CARDS', cards=cards)],
                'REVIEW': [output('REVIEW_RESULT', review_result={'schema_version': 1, 'summary': '未发现问题', 'issues': []}), output('CLARIFY_TEXT'), output('CLARIFY_CARDS', cards=cards)],
                'MODIFY': [output('NO_CHANGE'), output('SUGGESTIONS', title='明确审批人', summary='补充明确规则', suggestions=[patch]), output('CLARIFY_TEXT'), output('CLARIFY_CARDS', cards=cards)],
            }[action]
            for value in examples:
                with self.subTest(name=name, response_type=value['response_type']):
                    self.assertEqual(function.parse_output(json.dumps(value, ensure_ascii=False)), value)
                    for invalid in ({**value, 'schema_version': 1.0}, {**value, 'unknown': 'secret-marker'}, {**value, 'response_type': 'UNREGISTERED'}):
                        with self.assertRaises(ProtocolInvalid) as caught:
                            function.parse_output(json.dumps(invalid))
                        self.assertNotIn('secret-marker', str(caught.exception))
                        self.assertNotIn('secret-marker', repr(caught.exception.issues))
            if action == 'MODIFY':
                with self.assertRaises(ProtocolInvalid):
                    function.parse_output(json.dumps(output('SUGGESTIONS', title='空', summary='空', suggestions=[])))

    def test_output_no_fence_repair_duplicate_key_repair_or_capacity_truncation(self):
        function = self.catalog.freeze('ASK', 'USER_INSTRUCTION')
        valid = json.dumps(output('ANSWER'))
        for content in ('```json\n' + valid + '\n```', valid + valid, '[{}]', '{"schema_version":1,"schema_version":1}', '{"x":{"a":1,"a":2}}', '{"message":"\\ud800"}', b'\xff', None, 'x' * (1024 * 1024 + 1)):
            with self.subTest(type=type(content).__name__), self.assertRaises(ProtocolInvalid):
                function.parse_output(content)
