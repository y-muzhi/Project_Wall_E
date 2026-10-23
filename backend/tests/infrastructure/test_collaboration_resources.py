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
from backend.app.infrastructure.model_profile import ModelProfile, DEFAULT_PROFILE
from backend.app.infrastructure.resources import ResourceCatalog, ConfigInvalid, ProtocolInvalid
from backend.app.infrastructure.schema_transport import compact, declared_json, named_schema
from backend.app.shared.validation import strict_json_object, InvalidInput


@pytest.fixture(scope='module')
def resources():
    return ResourceCatalog().collaboration


def test_resources_match_the_complete_design_source(resources):
    design = Path('docs/design/v1.5/WALL-E.后端设计文档_V_1.5.md').read_text(encoding='utf-8')
    blocks = [json.loads(text) for text in re.findall(r'```json\s*\n(.*?)\n```', design, re.S)]
    assert resources.bundle == next(value for value in blocks if isinstance(value, dict) and value.get('$id') == 'urn:walle:collaboration-contract:v1')
    guides = next(value for value in blocks if isinstance(value, list) and len(value) == 4 and value[0].get('key') == 'collaboration.discovery')
    for guide in guides:
        assert resources.guide(guide['phase_kind']) == guide
    structures = next(value for value in blocks if isinstance(value, list) and len(value) == 3 and value[0].get('key') == 'structure.brief')
    for structure in structures:
        assert resources.structure(structure['document_kind']) == structure
    assert len(resources.bundle['$defs']) == 89


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


@pytest.mark.parametrize('target', ['manifest.json', 'schemas/output-generate.v1.json', 'guides/collaboration.discovery.v1.json'])
def test_corrupt_resource_fails_closed_and_temporary_output_is_removed(target):
    with TemporaryDirectory(prefix='walle-v15-resource-') as directory:
        copy = Path(directory) / 'v9'
        shutil.copytree(ROOT, copy)
        path = copy / target
        path.write_bytes(path.read_bytes() + b' ')
        with pytest.raises(ConfigInvalid):
            CollaborationResources.load(copy)


def test_parser_does_not_repair_or_accept_duplicate_keys():
    for text in ('```json\n{}\n```', '{}{}', '{"a":1,"a":2}'):
        with pytest.raises(InvalidInput):
            strict_json_object(text)
