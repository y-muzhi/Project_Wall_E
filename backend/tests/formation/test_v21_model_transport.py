"""Provider grammar binding and original authoritative validation, all offline."""

import asyncio
import json
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools'))
from formation_evaluation_fixture import prepare_sample
from formation_evaluation_spec import Sample

from backend.app.guide.collaboration_context import CollaborationContext
from backend.app.infrastructure.collaboration_format import (
    TRANSPORT,
    current_blocks,
    provider_schema,
    response_format,
)
from backend.app.infrastructure.collaboration_resources import ROOT, CollaborationResources
from backend.app.infrastructure.model_gateway import ModelGateway
from backend.app.infrastructure.model_profile import ModelProfile
from backend.app.infrastructure.resources import ConfigInvalid, ProtocolInvalid, ResourceCatalog
from backend.tests.formation.test_v21_live_fix_examples import task_output
from backend.tests.formation.test_v21_model_contracts import examples

PROFILE = ModelProfile('offline-only-schema-transport', 'deepseek-v2')


@pytest.fixture(scope='module')
def contexts(tmp_path_factory):
    catalog = ResourceCatalog().for_formation_profile(PROFILE.profile_id)
    values = {}
    for body in ('blank', 'fbase'):
        directory = tmp_path_factory.mktemp('schema-' + body)
        values[body], _ = prepare_sample(directory, catalog, Sample(body, 3, 'assess'))
        directory = tmp_path_factory.mktemp('schema-' + body + '-associate')
        values[body + '-associate'], _ = prepare_sample(
            directory, catalog, Sample(body, 3, 'associate')
        )
    return values


@pytest.mark.parametrize('body', ('blank', 'fbase'))
def test_schema_binds_only_sent_current_blocks_and_is_stable(contexts, body):
    context = contexts[body]
    body = PROFILE.request(context)
    format = body['response_format']
    assert format == PROFILE.request(context)['response_format']
    assert format['type'] == 'json_schema' and format['json_schema']['strict'] is True
    schema = format['json_schema']['schema']
    Draft202012Validator.check_schema(schema)
    definitions = schema['$defs']
    refs = current_blocks(context.input)
    alternatives = definitions['FormationChange']['anyOf']
    by_type = {value['properties']['type']['enum'][0]: value for value in alternatives}
    if refs:
        assert definitions['FormationBlockAliasRef'] == {'type': 'string', 'enum': refs}
        assert 'ASSOCIATE_CONTENT' in by_type
    else:
        assert 'FormationBlockAliasRef' not in definitions
        assert 'ASSOCIATE_CONTENT' not in by_type
        assert by_type['ASSESS_STEP']['properties']['document_refs']['const'] == []
    assert 'ContextBasis' not in definitions and 'Canonical' not in definitions
    assert 'model_transport' not in context.input_json
    assert len(context.texts) == 8  # No uncounted hidden message is introduced.


@pytest.mark.parametrize('body', ('blank', 'fbase'))
@pytest.mark.parametrize('task', ('discuss', 'write', 'path', 'associate', 'assess'))
def test_all_five_valid_task_shapes_fit_bound_grammar(contexts, body, task):
    context = contexts[body]
    if task == 'associate':
        context = contexts[body + '-associate']
    value = task_output(Sample(body, 3, task), context)
    schema = PROFILE.request(context)['response_format']['json_schema']['schema']
    Draft202012Validator(schema).validate(value)


def test_whole_document_and_unseen_block_never_fit_assessment(contexts):
    context = contexts['fbase']
    value = task_output(Sample('fbase', 3, 'assess'), context)
    schema = PROFILE.request(context)['response_format']['json_schema']['schema']
    validator = Draft202012Validator(schema)
    for reference in ('d42v2', 'd42v2.b12', 'd42v999b12', 'd999v2b12', 'd42v2b99999'):
        changed = deepcopy(value)
        changed['progress_delta']['formation_delta']['changes'][0]['document_refs'] = [reference]
        assert not validator.is_valid(changed)


def test_path_result_temp_ref_mismatch_is_rejected(contexts):
    context = contexts['fbase']
    value = task_output(Sample('fbase', 3, 'path'), context)
    result = value['cards']['action_payload']['changes'][0]['expected_results'][0]
    result['temp_ref'] = result.pop('temp_result_ref')
    schema = PROFILE.request(context)['response_format']['json_schema']['schema']
    assert not Draft202012Validator(schema).is_valid(value)


def test_full_local_schema_still_enforces_patterns_and_lengths():
    resources = ResourceCatalog().for_formation_profile(PROFILE.profile_id).collaboration
    assert resources.release['model_transport'] == TRANSPORT
    valid = examples()[-1]
    resources.validate('FormationChange', valid)
    for reference in ('d1v1', 'd1v1.b1', 'm1'):
        with pytest.raises(ProtocolInvalid):
            resources.validate('FormationChange', {**valid, 'document_refs': [reference]})
    with pytest.raises(ProtocolInvalid):
        resources.validate('FormationChange', {**examples()[1], 'title': '长' * 121})
    # Source aliases remain their separate, broader material-reference type.
    resources.validate('FormationChange', {**valid, 'source_refs': ['m1']})


def test_projection_preserves_literals_and_refuses_unknown_schema_syntax():
    rule = {
        'type': 'object',
        'properties': {
            'pattern': {'const': {'$ref': 'literal-data', 'minimum': 7}},
            '$id': {'type': 'string', 'pattern': '^literal$', 'maxLength': 20},
        },
        'required': ['pattern', '$id'],
        'additionalProperties': False,
    }
    projected = provider_schema(rule)
    assert projected['properties']['pattern']['const'] == rule['properties']['pattern']['const']
    assert projected['properties']['$id'] == {'type': 'string'}
    assert projected['required'] == ['pattern', '$id']
    for keyword in ('unknownGrammar', 'not', '$dynamicRef', 'patternProperties'):
        with pytest.raises(ConfigInvalid):
            provider_schema({keyword: {}})


def test_exclusive_pattern_union_remains_satisfiable_after_projection():
    rule = {
        'oneOf': [
            {'type': 'string', 'pattern': '^s[1-9][0-9]*$'},
            {'type': 'string', 'pattern': '^new_step_[1-9][0-9]*$'},
        ]
    }
    projected = provider_schema(rule)
    assert 'oneOf' not in projected
    assert Draft202012Validator(projected).is_valid('s2')
    assert Draft202012Validator(projected).is_valid('new_step_1')


def test_frozen_digest_and_unknown_transport_fail_closed(contexts):
    context = contexts['fbase']
    original = context.canonical
    for defect in ('digest', 'mode'):
        canonical = deepcopy(original)
        release = next(
            item
            for item in canonical['resources']
            if item['resource_ref']['key'] == 'collaboration.release'
        )
        if defect == 'digest':
            release['content_text'] += ' '
        else:
            value = json.loads(release['content_text'])
            value['model_transport']['mode'] = 'text'
            release['content_text'] = json.dumps(value)
            from backend.app.infrastructure.collaboration_resources import sha256

            release['resource_ref']['digest'] = sha256(release['content_text'])
        with pytest.raises(ConfigInvalid):
            response_format(canonical, context.input)
    wire = context.input
    wire['documents'][0]['revision_id'] += 1
    with pytest.raises(ConfigInvalid):
        response_format(original, wire)


def test_non_discuss_keeps_original_transport(contexts):
    context = contexts['fbase']
    canonical, wire = context.canonical, context.input
    canonical['operation'] = wire['current_request']['operation'] = 'REVIEW'
    assert response_format(canonical, wire) is None


@pytest.mark.parametrize('batch', ('v27', 'v29'))
def test_historical_request_bytes_keep_original_body(tmp_path, batch):
    previous = CollaborationResources.load(ROOT.parent / batch)
    catalog = ResourceCatalog().for_collaboration_release(
        previous.reference('collaboration.release')
    )
    context, _ = prepare_sample(tmp_path, catalog, Sample('fbase', 3, 'assess'))
    expected = {
        'model': PROFILE.model_name,
        'messages': [
            {'role': 'system', 'content': context.system},
            {'role': 'user', 'content': context.input_json},
        ],
        'temperature': 0,
        'max_tokens': 8192,
        'stream': False,
        'thinking': {'type': 'disabled'},
    }
    assert context.response_format is None
    encode = lambda value: json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
    assert encode(PROFILE.request(context)) == encode(expected)
    # A context restored from saved basis requires no current catalog or DB.
    restored = CollaborationContext(
        context.system, context.input_json, context.basis_json, context.manifest_json
    )
    assert encode(PROFILE.request(restored)) == encode(expected)


def test_actual_gateway_sends_exact_frozen_schema_without_retry(contexts):
    context = contexts['fbase']
    seen = []

    def returned(request):
        seen.append(request.content)
        return httpx.Response(
            200,
            json={
                'id': 'offline-schema-output',
                'model': PROFILE.model_name,
                'choices': [
                    {
                        'index': 0,
                        'finish_reason': 'stop',
                        'message': {
                            'role': 'assistant',
                            'content': '{}',
                        },
                    }
                ],
                'usage': {'prompt_tokens': 20, 'completion_tokens': 4, 'total_tokens': 24},
            },
        )

    with patch(
        'backend.app.infrastructure.model_gateway.httpx.AsyncHTTPTransport',
        side_effect=AssertionError('No real transport'),
    ):
        result = asyncio.run(
            ModelGateway(transport_factory=lambda: httpx.MockTransport(returned)).send(
                PROFILE, context
            )
        )
    assert result.succeeded and len(seen) == 1
    expected = json.dumps(
        PROFILE.request(context), ensure_ascii=False, separators=(',', ':')
    ).encode()
    assert seen == [expected]
    assert json.loads(seen[0])['response_format'] == context.response_format


def test_first_count_text_includes_exact_sdk_schema_but_does_not_add_message(contexts):
    from backend.app.infrastructure.schema_transport import compact

    context = contexts['fbase']
    body = PROFILE.request(context)
    assert context.texts[0] == (
        context.system + '\n' + compact(body['response_format']['json_schema']['schema'])
    )
    assert context.texts[1] == context.input_json
    assert len(context.texts) == 8
    assert [message['content'] for message in body['messages']] == [
        context.system,
        context.input_json,
    ]


def test_unknown_count_text_strategy_or_changed_frozen_counting_fails_closed(contexts):
    from backend.app.infrastructure.collaboration_format import counting_system_text
    from backend.app.infrastructure.collaboration_resources import sha256

    context = contexts['fbase']
    canonical = context.canonical
    frozen = next(
        item
        for item in canonical['resources']
        if item['resource_ref']['key'] == 'collaboration.counting'
    )
    frozen['content_text'] += ' '
    with pytest.raises(ConfigInvalid):
        counting_system_text(canonical, context.system, context.response_format)
    definition = json.loads(frozen['content_text'])
    definition['system_text'] = 'unapproved-estimate'
    frozen['content_text'] = json.dumps(definition)
    frozen['resource_ref']['digest'] = sha256(frozen['content_text'])
    with pytest.raises(ConfigInvalid):
        counting_system_text(canonical, context.system, context.response_format)


def test_new_count_text_preserves_sdk_bytes_and_historical_v31_receipt(tmp_path, contexts):
    previous = CollaborationResources.load(ROOT.parent / 'v31')
    catalog = ResourceCatalog().for_collaboration_release(
        previous.reference('collaboration.release')
    )
    historical, _ = prepare_sample(tmp_path, catalog, Sample('fbase', 3, 'assess'))
    assert historical.texts[0] == historical.system
    current = contexts['fbase']
    assert PROFILE.request(current) == PROFILE.request(historical)
    assert current.texts[0] != historical.texts[0]
