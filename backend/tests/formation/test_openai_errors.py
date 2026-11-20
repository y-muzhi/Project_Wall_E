"""Native count HTTP errors keep useful private evidence, without another call."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from backend.app.infrastructure.model_profile import OPENAI_PROFILE, ModelProfile
from backend.app.infrastructure.openai_counting import OpenAIInputCounter
from backend.app.infrastructure.tokenization import ExactCountUnavailable
from backend.tests.formation.test_openai_primitives import context
from backend.tests.formation.test_openai_service import module

PROFILE = ModelProfile('offline-http-error-key', OPENAI_PROFILE)


def test_count_error_keeps_exact_code_parameter_and_scrubbed_message():
    seen = []

    def reply(request):
        seen.append(request)
        return httpx.Response(
            400,
            json={
                'error': {
                    'code': 'invalid_json_schema',
                    'param': 'text.format.schema',
                    'message': 'Invalid schema ' + PROFILE.api_key,
                }
            },
            headers={'x-request-id': 'req_offline400'},
        )

    counter = OpenAIInputCounter(transport_factory=lambda: httpx.MockTransport(reply))
    with pytest.raises(ExactCountUnavailable) as caught:
        asyncio.run(counter.count_context(PROFILE, context()))
    error = caught.value
    assert error.reason == 'HTTP_STATUS' and error.http_status == 400
    assert error.provider_error['category'] == 'PARAMETER'
    assert error.provider_error['code'] == 'invalid_json_schema'
    assert error.provider_error['parameter'] == 'text.format.schema'
    assert error.provider_error['request_id'] == 'req_offline400'
    assert PROFILE.api_key not in json.dumps(error.provider_error)
    assert '[REDACTED_CREDENTIAL]' in error.provider_error['message']
    assert 'Invalid schema' not in str(error)
    assert len(seen) == 1


@pytest.mark.parametrize(
    'case,state',
    [('invalid', 'INVALID_JSON'), ('large', 'OVERSIZED'), ('broken', 'READ_UNAVAILABLE')],
)
def test_known_http_error_is_preserved_even_when_optional_error_body_is_unreadable(case, state):
    class Broken(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise httpx.ReadError('unlogged-private-body')
            yield b''

    seen = []

    def reply(request):
        seen.append(request)
        if case == 'broken':
            return httpx.Response(400, stream=Broken())
        return httpx.Response(400, content=b'x' * 17000 if case == 'large' else b'not-json')

    counter = OpenAIInputCounter(transport_factory=lambda: httpx.MockTransport(reply))
    with pytest.raises(ExactCountUnavailable) as caught:
        asyncio.run(counter.count_context(PROFILE, context()))
    assert caught.value.http_status == 400
    assert caught.value.provider_error['body_state'] == state
    assert caught.value.provider_error['message'] is None
    assert len(seen) == 1


def test_count_error_redacts_before_truncating_and_uses_native_quota_category():
    key = PROFILE.api_key
    message = 'x' * 2038 + key + 'y' * 3000
    reply = lambda request: httpx.Response(
        429, json={'error': {'code': 'insufficient_quota', 'message': message}}
    )
    counter = OpenAIInputCounter(transport_factory=lambda: httpx.MockTransport(reply))
    with pytest.raises(ExactCountUnavailable) as caught:
        asyncio.run(counter.count_context(PROFILE, context()))
    details = caught.value.provider_error
    assert details['category'] == 'QUOTA'
    assert details['message_truncated'] and len(details['message']) == 2048
    assert key not in details['message']
    assert details['message'].endswith('[REDACTED_')


def test_original_observation_stops_before_model_and_saves_error_in_normal_count_journal(
    tmp_path, monkeypatch
):
    service = module()
    root = tmp_path
    (root / 'data').mkdir()
    (root / 'docs/verification/v2.1').mkdir(parents=True)
    key = root / 'key.env'
    key.write_bytes(('OPENAI_API_KEY=' + PROFILE.api_key + '\n').encode())
    monkeypatch.setattr(service, 'ROOT', root)
    attempts = []

    def reply(request):
        attempts.append(request)
        return httpx.Response(
            400,
            json={
                'error': {
                    'code': 'invalid_json_schema',
                    'param': 'text.format.schema',
                    'message': 'Invalid native schema ' + PROFILE.api_key,
                }
            },
        )

    counter = OpenAIInputCounter(transport_factory=lambda: httpx.MockTransport(reply))
    monkeypatch.setattr(
        'backend.app.infrastructure.openai_counting.OpenAIInputCounter', lambda: counter
    )

    def forbidden():
        raise AssertionError('A failed count must not construct the model gateway')

    monkeypatch.setattr('backend.app.infrastructure.model_gateway.ModelGateway', forbidden)
    args = SimpleNamespace(
        slot=root / 'data/s', report=root / 'docs/verification/v2.1/live.md', credential_file=key
    )
    assert service.observe(args) == 1
    files = list(args.slot.glob('*.count-audit/*.finished.json'))
    assert len(files) == 1 and len(attempts) == 1
    value = json.loads(files[0].read_text(encoding='utf-8'))
    assert value['phase'] == 'FAILED' and value['http_status'] == 400
    assert value['provider_error']['parameter'] == 'text.format.schema'
    assert PROFILE.api_key not in files[0].read_text(encoding='utf-8')
    report = args.report.read_text(encoding='utf-8')
    assert '实际计数尝试=1；实际模型尝试=0' in report
    assert 'Invalid native schema' not in report
