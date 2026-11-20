"""Exact native count ownership, redaction and cancellation without external I/O."""

import asyncio
from copy import deepcopy

import httpx
import pytest

from backend.app.infrastructure.audit_data import counting_audit_json, sanitize_audit
from backend.app.infrastructure.model_profile import OPENAI_PROFILE, ModelProfile
from backend.app.infrastructure.openai_counting import OpenAIInputCounter, restore
from backend.app.infrastructure.openai_protocol import COUNT_ENDPOINT
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.infrastructure.tokenization import ExactCountUnavailable
from backend.tests.formation.test_openai_primitives import context

PROFILE = ModelProfile('offline-openai-count-only', OPENAI_PROFILE)


def receipt():
    ctx = context()
    seen = []

    def reply(request):
        seen.append(request)
        return httpx.Response(200, json={'object': 'response.input_tokens', 'input_tokens': 1234})

    counter = OpenAIInputCounter(transport_factory=lambda: httpx.MockTransport(reply))
    value = asyncio.run(counter.count_context(PROFILE, ctx))
    assert len(seen) == 1 and str(seen[0].url) == COUNT_ENDPOINT
    return ctx, value


def test_complete_request_receipt_has_no_fabricated_component_counts():
    ctx, value = receipt()
    assert value.request_tokens == 1234
    assert 'counts' not in value.evidence and 'created' not in value.evidence
    assert restore(value.evidence, ctx, PROFILE) == value
    for field in ('request_sha256', 'model_request_sha256'):
        changed = deepcopy(value.evidence)
        changed[field] = 'f' * 64
        with pytest.raises(ConfigInvalid):
            restore(changed, ctx, PROFILE)
    changed = deepcopy(value.evidence)
    changed['response']['input_tokens'] = 1235
    with pytest.raises(ConfigInvalid):
        restore(changed, ctx, PROFILE)
    changed = context()
    changed.input_json = '{"different":"scope"}'
    with pytest.raises(ConfigInvalid):
        restore(value.evidence, changed, PROFILE)


def test_count_failures_do_not_retry():
    for status in (400, 401, 429, 500):
        seen = []

        def reply(request, *, seen=seen, status=status):
            seen.append(request)
            return httpx.Response(status, json={'error': {'code': 'offline'}})

        counter = OpenAIInputCounter(transport_factory=lambda: httpx.MockTransport(reply))
        with pytest.raises(ExactCountUnavailable) as caught:
            asyncio.run(counter.count_context(PROFILE, context()))
        assert caught.value.reason == 'HTTP_STATUS'
        assert caught.value.http_status == status
        assert len(seen) == 1


def test_only_fixed_request_reasoning_configuration_survives_audit():
    import json

    body = PROFILE.request(context())
    value = {
        'request': body,
        'unrelated': {'reasoning': 'private', 'reasoning_content': 'private'},
        'api_key': PROFILE.api_key,
    }
    encoded = counting_audit_json(value, PROFILE)
    safe = json.loads(encoded)
    assert safe['request'] == body
    assert safe['unrelated'] == {}
    assert 'api_key' not in safe
    assert sanitize_audit({'reasoning': {'effort': 'medium'}}) == {}
    changed = deepcopy(value)
    changed['request']['reasoning'] = {'effort': 'high'}
    with pytest.raises(ValueError):
        counting_audit_json(changed, PROFILE)


def test_cancelling_count_closes_the_only_mock_request():
    async def exercise():
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        seen = []

        async def reply(request):
            seen.append(request)
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        counter = OpenAIInputCounter(transport_factory=lambda: httpx.MockTransport(reply))
        task = asyncio.create_task(counter.count_context(PROFILE, context()))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set() and len(seen) == 1

    asyncio.run(exercise())
