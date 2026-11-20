"""Native OpenAI primitives and immutable Ark compatibility, never real HTTP."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from jsonschema import Draft202012Validator

from backend.app.infrastructure.collaboration_resources import sha256
from backend.app.infrastructure.model_gateway import ModelGateway
from backend.app.infrastructure.model_profile import OPENAI_PROFILE, ModelProfile
from backend.app.infrastructure.openai_protocol import (
    COUNT_ENDPOINT,
    ENDPOINT,
    MODEL,
    count_request,
    output_text,
    usage,
)
from backend.app.infrastructure.openai_schema import MODE, schema_for, validate_limits
from backend.app.infrastructure.resources import ConfigInvalid

ROOT = Path(__file__).resolve().parents[3]


def context():
    root = ROOT / 'backend/resources/v37'
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    entries = {item['resource_ref']['key']: item for item in manifest['files']}

    def resource(key):
        item = entries[key]
        text = (root / item['path']).read_text(encoding='utf-8')
        return {'resource_ref': dict(item['resource_ref']), 'content_text': text}

    release = resource('collaboration.release')
    value = json.loads(release['content_text'])
    value['model_transport'] = MODE
    release['content_text'] = json.dumps(value)
    release['resource_ref']['digest'] = sha256(release['content_text'])
    wire = {'current_request': {'operation': 'GENERATE'}}
    return SimpleNamespace(
        system='独立OpenAI离线协议',
        input_json=json.dumps(wire),
        texts=('独立OpenAI离线协议', json.dumps(wire), '', '', '', '', '', ''),
        input=wire,
        canonical={
            'operation': 'GENERATE',
            'resources': [release, resource('collaboration.output.generate')],
        },
    )


def native(**changes):
    value = {
        'object': 'response',
        'id': 'resp_offline',
        'model': MODEL,
        'status': 'completed',
        'output': [
            {'type': 'reasoning', 'summary': []},
            {
                'type': 'message',
                'role': 'assistant',
                'status': 'completed',
                'content': [
                    {'type': 'output_text', 'text': '{"message":"明确答复"}', 'annotations': []}
                ],
            },
        ],
        'usage': {
            'input_tokens': 2000,
            'output_tokens': 100,
            'total_tokens': 2100,
            'input_tokens_details': {'cached_tokens': 100},
            'output_tokens_details': {'reasoning_tokens': 60},
        },
    }
    return {**value, **changes}


def test_openai_profile_is_explicit_and_does_not_reuse_ark_credentials():
    profile = ModelProfile.from_environment(
        {'WALLE_MODEL_PROFILE': OPENAI_PROFILE, 'OPENAI_API_KEY': 'offline-openai-key'}
    )
    assert profile.provider == 'openai' and profile.model_name == MODEL
    assert profile.snapshot['model_identity'] == 'alias'
    assert profile.snapshot['endpoint'] == ENDPOINT
    assert 'offline-openai-key' not in json.dumps(profile.snapshot)
    assert ModelProfile.from_snapshot(profile.snapshot).profile_id == OPENAI_PROFILE
    assert ModelProfile.selected_profile({}) == 'deepseek-v2'
    with pytest.raises(ConfigInvalid):
        ModelProfile.from_environment(
            {'WALLE_MODEL_PROFILE': OPENAI_PROFILE, 'WALLE_MODEL_API_KEY': 'old-ark-only'}
        )
    for url in ('https://evil.invalid/v1', 'https://api.openai.com/v1?key=x', None):
        with pytest.raises(ConfigInvalid):
            ModelProfile.from_environment(
                {
                    'WALLE_MODEL_PROFILE': OPENAI_PROFILE,
                    'OPENAI_API_KEY': 'offline',
                    'WALLE_MODEL_BASE_URL': url,
                }
            )


@pytest.mark.parametrize('identity', ('doubao-v1', 'deepseek-v2', 'deepseek-long-v3'))
def test_old_profile_request_bytes_are_unchanged(identity):
    profile = ModelProfile('offline-ark', identity)
    ctx = SimpleNamespace(system='旧协议', input_json='{"value":"旧Wire"}')
    expected = {
        'model': profile.model_name,
        'messages': [
            {'role': 'system', 'content': ctx.system},
            {'role': 'user', 'content': ctx.input_json},
        ],
        'temperature': 0,
        'max_tokens': 32768 if identity == 'deepseek-long-v3' else 8192,
        'stream': False,
        'thinking': {'type': 'disabled'},
    }
    encode = lambda obj: json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode()
    assert encode(profile.request(ctx)) == encode(expected)
    assert ModelProfile.from_snapshot(profile.snapshot).profile_id == identity


def test_native_request_and_count_payload_have_the_same_semantic_input_and_format():
    profile = ModelProfile('offline-openai', OPENAI_PROFILE)
    ctx = context()
    body = profile.request(ctx)
    count = count_request(body)
    assert body['input'] == [
        {'role': 'developer', 'content': ctx.system},
        {'role': 'user', 'content': ctx.input_json},
    ]
    assert body['store'] is False and body['stream'] is False
    assert body['reasoning'] == {'effort': 'medium'}
    assert body['truncation'] == 'disabled'
    assert 'thinking' not in body and 'temperature' not in body
    for key in ('model', 'input', 'text', 'reasoning', 'truncation'):
        assert count[key] == body[key]
    assert body['text']['format']['strict'] is True
    assert COUNT_ENDPOINT == ENDPOINT + '/input_tokens'
    Draft202012Validator.check_schema(body['text']['format']['schema'])


@pytest.mark.parametrize(
    'file', sorted((ROOT / 'backend/resources/v37/schemas').glob('output-*.json'))
)
def test_all_six_full_output_grammars_have_supported_root_and_capacity(file):
    projected = schema_for(file.read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(projected)
    assert projected['type'] == 'object' and 'anyOf' not in projected
    assert len(projected['properties']) == 9
    assert projected['additionalProperties'] is False
    assert validate_limits(projected)['nesting'] <= 10


def test_native_output_and_usage_are_not_fabricated_as_ark():
    raw = native()
    assert output_text(raw) == '{"message":"明确答复"}'
    assert usage(raw) == (2000, 100, {'cached_tokens': 100})
    assert 'choices' not in raw
    with pytest.raises(ValueError):
        output_text(native(status='incomplete'))
    with pytest.raises(ValueError):
        output_text(native(output=[{'type': 'function_call'}]))
    bad = native()
    bad['output'].append(bad['output'][-1])
    with pytest.raises(ValueError):
        output_text(bad)
    bad = native()
    bad['output'][-1]['content'] = [{'type': 'refusal', 'refusal': 'refused'}]
    with pytest.raises(ValueError):
        output_text(bad)
    bad = native()
    bad['usage']['total_tokens'] = 2101
    with pytest.raises(ValueError):
        usage(bad)


@pytest.mark.parametrize('status', (200, 401, 429, 500))
def test_exact_native_gateway_has_no_retry_redirect_or_ark_envelope(status):
    profile = ModelProfile('offline-openai-secret', OPENAI_PROFILE)
    ctx = context()
    seen = []

    def response(req):
        seen.append(req)
        assert str(req.url) == ENDPOINT
        assert req.headers['authorization'] == 'Bearer ' + profile.api_key
        return httpx.Response(
            status, json=native() if status == 200 else {'error': {'code': 'rate_limit_exceeded'}}
        )

    with patch(
        'backend.app.infrastructure.openai_gateway.httpx.AsyncHTTPTransport',
        side_effect=AssertionError('No real transport'),
    ):
        result = asyncio.run(
            ModelGateway(transport_factory=lambda: httpx.MockTransport(response)).send(profile, ctx)
        )
    assert len(seen) == 1 and result.retryable is False
    assert (
        seen[0].content
        == json.dumps(profile.request(ctx), ensure_ascii=False, separators=(',', ':')).encode()
    )
    if status == 200:
        assert result.succeeded and result.input_tokens == 2000 and result.output_tokens == 100
        assert result.raw_response['object'] == 'response' and 'choices' not in result.raw_response
    else:
        assert not result.succeeded
        assert result.category in ('AUTHENTICATION', 'RATE_LIMIT', 'TEMPORARY_SERVICE')


def test_credential_echo_never_becomes_a_business_answer():
    profile = ModelProfile('offline-secret-echo', OPENAI_PROFILE)
    ctx = context()
    raw = native()
    raw['output'][-1]['content'][0]['text'] = profile.api_key
    gateway = ModelGateway(
        transport_factory=lambda: httpx.MockTransport(lambda req: httpx.Response(200, json=raw))
    )
    result = asyncio.run(gateway.send(profile, ctx))
    assert not result.succeeded and result.category == 'CREDENTIAL_ECHO'
    assert profile.api_key not in result.raw_response_json
