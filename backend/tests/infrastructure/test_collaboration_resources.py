"""V1.5 offline resource identity, strict contracts and exact transport bytes."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory

import pytest
from jsonschema import Draft202012Validator

from backend.app.infrastructure.collaboration_resources import CollaborationResources, ROOT, OUTPUTS, GUIDE_FIELDS
from backend.app.infrastructure.model_profile import ModelProfile, DEFAULT_PROFILE, LONG_OUTPUT_PROFILE
from backend.app.infrastructure.resources import ResourceCatalog, ConfigInvalid, ProtocolInvalid
from backend.app.infrastructure.schema_transport import compact, declared_json, named_schema
from backend.app.shared.validation import strict_json_object, InvalidInput


@pytest.fixture(scope='module')
def resources():
    return ResourceCatalog().collaboration


def test_resources_match_the_complete_design_source(resources):
    # Current design publishes the opt-in long-output batch. The default v15
    # stays frozen until a separate live admission and service switch.
    historical = resources
    resources = ResourceCatalog().for_collaboration_profile(LONG_OUTPUT_PROFILE).collaboration
    design = Path('docs/design/v1.5/WALL-E.后端设计文档_V_1.5.md').read_text(encoding='utf-8')
    blocks = [json.loads(text) for text in re.findall(r'```json\s*\n(.*?)\n```', design, re.S)]
    assert resources.bundle == next(value for value in blocks if isinstance(value, dict) and value.get('$id') == 'urn:walle:collaboration-contract:v1')
    guides = next(value for value in blocks if isinstance(value, list) and len(value) == 4 and value[0].get('key') == 'collaboration.discovery')
    for guide in guides:
        assert resources.guide(guide['phase_kind']) == guide
    structures = next(value for value in blocks if isinstance(value, list) and len(value) == 3 and value[0].get('key') == 'structure.brief')
    for structure in structures:
        assert resources.structure(structure['document_kind']) == structure
    prompt_section = design.split('**Prompt正式定义**', 1)[1].split('| 当前阶段 |', 1)[0]
    paragraphs = [value.replace('\n> ', '\n') for value in re.findall(r'^> (.+(?:\n> .+)*)', prompt_section, re.M)]
    assert len(paragraphs) == 5
    assert resources.prompt == '\n\n'.join(paragraphs)
    assert len(resources.bundle['$defs']) == 89
    restored = deepcopy(resources.bundle)
    restored['$defs']['CountingDefinition']['properties']['output_limit']['const'] = 8192
    restored['$defs']['CountingDefinition']['properties']['total_limit']['const'] = 139264
    assert restored == historical.bundle
    assert resources.prompt == historical.prompt


def test_all_named_schema_closures_are_local_complete_and_minimal(resources):
    for name in resources.bundle['$defs']:
        schema = resources.schema(name)
        Draft202012Validator.check_schema(schema)
        assert list(schema['$defs']) == sorted(schema['$defs'])
        visited = set()

        def visit(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == '$ref':
                        assert value.startswith('#/$defs/')
                        target = value[8:]
                        assert target in schema['$defs']
                        if target not in visited:
                            visited.add(target)
                            visit(schema['$defs'][target])
                    elif key != '$defs':
                        visit(value)
            elif isinstance(node, list):
                for child in node:
                    visit(child)
        visit(schema)
        assert visited == set(schema['$defs'])


def test_system_has_exactly_one_current_guide_and_operation_closure(resources):
    for kind in ('DISCOVERY', 'SOLUTION', 'SPECIFICATION', 'REVIEW'):
        guide = resources.guide(kind)
        for operation in OUTPUTS:
            system = resources.system(kind, operation)
            assert system == (resources.prompt + '\n\n阶段指引 ' + guide['key'] + '@v1\n'
                + compact({key: guide[key] for key in GUIDE_FIELDS})
                + '\n\n任务输出协议 ' + operation + '\n' + resources.output_schema(operation))
            schema = json.loads(resources.output_schema(operation))
            assert schema['$ref'] == '#/$defs/' + OUTPUTS[operation]
            assert 'Canonical' not in schema['$defs']
            assert 'ContextBasis' not in schema['$defs']
            assert 'Wire' not in schema['$defs']
            assert system.count(resources.prompt) == 1


def test_outputs_are_operation_specific_nullable_and_strict(resources):
    base = {'schema_version': 1, 'response_type': 'ANALYSIS', 'message': '没有变化',
        'basis_ref': {'discussion_version': 3, 'phase_ref': 'p1', 'guide_key': 'collaboration.discovery', 'guide_version': 'v1'},
        'progress_delta': None, 'cards': None, 'document_result': None, 'suggestions': None,
        'analysis': {'conclusion': 'NO_CHANGE', 'summary': '原文未变', 'findings': [], 'covered_refs': [], 'unresolved': []}}
    resources.validate('OutputRevise', base)
    resources.validate('OutputPropose', base)
    for entry in ('OutputDiscuss', 'OutputGenerate', 'OutputCompare', 'OutputReview'):
        with pytest.raises(ProtocolInvalid):
            resources.validate(entry, base)
    for change in ({'schema_version': True}, {'unknown': 1}, {'message': '\ud800'}):
        with pytest.raises(ProtocolInvalid):
            resources.validate('OutputRevise', {**base, **change})
    missing = deepcopy(base)
    del missing['cards']
    with pytest.raises(ProtocolInvalid):
        resources.validate('OutputRevise', missing)


def test_serialization_uses_declared_order_and_preserves_unicode_and_arrays(resources):
    # Deliberately reverse all nested object key order.
    original = resources.guide('DISCOVERY')

    def reverse(value):
        if isinstance(value, dict):
            return {key: reverse(value[key]) for key in reversed(value)}
        if isinstance(value, list):
            return [reverse(child) for child in value]
        return value
    actual = resources.serialize('GuideDefinition', reverse(original))
    assert actual == compact(original)
    assert '目标' in actual
    assert '\\u' not in actual
    assert not actual.endswith('\n')
    assert actual.encode('utf-8')[:3] != b'\xef\xbb\xbf'
    value = {'scope_type': 'DOCUMENT', 'scope_ref': None}
    # Union branches must serialize the selected shape, not another branch.
    schema = {'$schema': 'https://json-schema.org/draft/2020-12/schema',
        'oneOf': [{'type': 'object', 'properties': {'scope_type': {'const': 'DOCUMENT'}, 'scope_ref': {'type': 'null'}},
            'required': ['scope_type', 'scope_ref'], 'additionalProperties': False}]}
    assert declared_json(schema, dict(reversed(list(value.items())))) == compact(value)


def test_resource_reads_are_detached_and_digest_bound(resources):
    guide = resources.guide('DISCOVERY')
    guide['mainlines'].clear()
    assert resources.guide('DISCOVERY')['mainlines']
    reference = resources.reference('collaboration.discovery')
    assert hashlib.sha256(resources.content(reference).encode('utf-8')).hexdigest() == reference['digest']
    with pytest.raises(ConfigInvalid):
        resources.content({**reference, 'digest': '0' * 64})
    for call in (lambda: resources.guide('unknown'), lambda: resources.output_schema('ASK'), lambda: resources.schema('absent')):
        with pytest.raises(ConfigInvalid):
            call()


def test_offline_ready_never_grants_live_dispatch(resources):
    profile = ModelProfile('offline-test', DEFAULT_PROFILE).snapshot
    assert resources.release['admission']['state'] == 'OFFLINE_READY'
    assert all(resources.release['admission'][key] is None for key in ('evidence_ref', 'actual_input_tokens', 'chat_request_sha256'))
    with pytest.raises(ConfigInvalid, match='no verified live admission'):
        resources.require_live(profile)
    with pytest.raises(ConfigInvalid, match='profile differs'):
        resources.require_live({**profile, 'max_tokens': 16384})


@pytest.mark.parametrize('target', ['manifest.json', 'collaboration.output.generate', 'collaboration.discovery'])
def test_corrupt_resource_fails_closed_and_temporary_output_is_removed(target):
    with TemporaryDirectory(prefix='walle-v15-resource-') as directory:
        copy = Path(directory) / 'v9'
        shutil.copytree(ROOT, copy)
        manifest = json.loads((copy/'manifest.json').read_text(encoding='utf-8'))
        relative = target if target == 'manifest.json' else next(item['path'] for item in manifest['files'] if item['resource_ref']['key'] == target)
        path = copy / relative
        path.write_bytes(path.read_bytes() + b' ')
        with pytest.raises(ConfigInvalid):
            CollaborationResources.load(copy)


def test_parser_does_not_repair_or_accept_duplicate_keys():
    for text in ('```json\n{}\n```', '{}{}', '{"a":1,"a":2}'):
        with pytest.raises(InvalidInput):
            strict_json_object(text)


@pytest.mark.parametrize('ref', ['m1', 'm2', 'new_t1', 'new_e0', 'e0', 'e1suffix', 'e1\n'])
def test_model_visible_progress_schema_rejects_message_or_malformed_evidence_refs(resources, ref):
    from backend.tests.guide.test_v15_progress import delta
    value = delta();value['topic_changes'][0]['evidence_refs'] = [ref]
    with pytest.raises(ProtocolInvalid):resources.validate('Progress', value)


def test_model_visible_progress_schema_keeps_valid_ref_formats_and_local_closure(resources):
    from backend.tests.guide.test_v15_progress import delta
    for refs in ([], ['e1'], ['new_e1'], ['e1', 'new_e2']):
        value = delta();value['topic_changes'][0]['evidence_refs'] = refs
        resources.validate('Progress', value)
    # Format validity is not existence or user authorization; C07 still has to
    # resolve actual same-round evidence and prove its carried message sources.
    for operation in OUTPUTS:
        schema = json.loads(resources.output_schema(operation))
        assert schema['$defs']['TopicChange'] == resources.bundle['$defs']['TopicChange']


@pytest.mark.parametrize('change', [
    {'applies_to': ['core_flow']}, {'applies_to': ['d1v2']}, {'topic_refs': ['m1']},
    {'supersedes': ['m1']}, {'supersedes': ['e1']},
    {'change': 'PROPOSE_SUPERSEDE', 'supersedes': []}, {'ref': 'e1'},
])
def test_evidence_schema_distinguishes_topic_source_and_supersession_namespaces(resources, change):
    from backend.tests.guide.test_v15_progress import evidence
    with pytest.raises(ProtocolInvalid):resources.validate('EvidenceChange', evidence(**change))


def test_model_visible_rules_explain_user_events_and_exact_row_original(resources):
    from backend.tests.guide.test_v15_progress import evidence
    resources.validate('EvidenceChange', evidence())
    resources.validate('EvidenceChange', evidence(change='PROPOSE_SUPERSEDE', supersedes=['e1']))
    schema = json.loads(resources.output_schema('GENERATE'))
    assert 'formal_answers' in schema['$defs']['EvidenceChange']['properties']['origin']['description']
    assert 'USER_STATEMENT' in resources.prompt and 'original_content' in resources.prompt
    assert '不是整张表' in resources.prompt
