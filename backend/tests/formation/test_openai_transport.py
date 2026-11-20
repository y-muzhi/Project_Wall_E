"""Explicit OpenAI proxy routing and secret-free diagnostics; no provider I/O."""

import asyncio

import httpx
import pytest

from backend.app.infrastructure.model_gateway import ModelGateway
from backend.app.infrastructure.model_profile import OPENAI_PROFILE, ModelProfile
from backend.app.infrastructure.openai_counting import OpenAIInputCounter
from backend.app.infrastructure.openai_protocol import COUNT_ENDPOINT, ENDPOINT
from backend.app.infrastructure.openai_transport import (
    configured_proxy,
    create_transport,
    report_transport_error,
    validate_proxy,
)
from backend.app.infrastructure.resources import ConfigInvalid
from backend.tests.formation.test_openai_primitives import context, native
from backend.tests.formation.test_openai_service import module


def test_only_explicit_proxy_is_used_and_unknown_configuration_fails_closed():
    assert configured_proxy({'HTTPS_PROXY': 'http://127.0.0.1:9999'}) is None
    assert (
        configured_proxy({'OPENAI_HTTP_PROXY': 'http://127.0.0.1:7897/'}) == 'http://127.0.0.1:7897'
    )
    assert validate_proxy('http://[::1]:7897') == 'http://[::1]:7897'
    for value in (
        '',
        None,
        'http://localhost:7897',
        'http://192.0.2.1:7897',
        'https://127.0.0.1:7897',
        'http://user:secret@127.0.0.1:7897',
        'http://127.0.0.1',
        'http://127.0.0.1:0',
        'http://127.0.0.1:65536',
        'http://127.0.0.1:7897/path',
        'http://127.0.0.1:7897?token=x',
        'http://127.0.0.1:7897#fragment',
    ):
        with pytest.raises(ConfigInvalid):
            validate_proxy(value)


def test_native_transport_keeps_tls_checks_and_zero_retries(monkeypatch):
    settings = []
    marker = object()
    monkeypatch.setenv('OPENAI_HTTP_PROXY', 'http://127.0.0.1:7897')

    def factory(**kwargs):
        settings.append(kwargs)
        return marker

    monkeypatch.setattr(
        'backend.app.infrastructure.openai_transport.httpx.AsyncHTTPTransport', factory
    )
    assert create_transport() is marker
    assert settings == [
        {'proxy': 'http://127.0.0.1:7897', 'retries': 0, 'trust_env': False, 'verify': True}
    ]


def test_count_and_model_use_same_explicit_route_and_original_official_urls(monkeypatch):
    seen = []
    transports = []
    monkeypatch.setenv('OPENAI_HTTP_PROXY', 'http://127.0.0.1:7897')
    profile = ModelProfile('offline-proxy-fixture', OPENAI_PROFILE)

    def reply(request):
        seen.append((str(request.url), request.headers['authorization']))
        if str(request.url) == COUNT_ENDPOINT:
            return httpx.Response(
                200, json={'object': 'response.input_tokens', 'input_tokens': 2000}
            )
        return httpx.Response(200, json=native())

    def factory(**kwargs):
        transports.append(kwargs)
        return httpx.MockTransport(reply)

    monkeypatch.setattr(
        'backend.app.infrastructure.openai_transport.httpx.AsyncHTTPTransport', factory
    )

    async def exercise():
        receipt = await OpenAIInputCounter().count_context(profile, context())
        result = await ModelGateway().send(profile, context())
        assert receipt.request_tokens == 2000 and result.succeeded

    asyncio.run(exercise())
    assert [url for url, _ in seen] == [COUNT_ENDPOINT, ENDPOINT]
    assert all(auth == 'Bearer ' + profile.api_key for _, auth in seen)
    assert len(transports) == 2 and all(
        item['proxy'] == 'http://127.0.0.1:7897' for item in transports
    )


def test_transport_diagnostics_never_include_free_text_or_credentials(caplog):
    inner = OSError('offline-sensitive-url?api_key=not-for-log')
    outer = httpx.ConnectError('offline-sensitive-key-and-body')
    outer.__cause__ = inner
    report_transport_error('input_count', outer)
    assert 'ConnectError,OSError' in caplog.text
    assert 'offline-sensitive' not in caplog.text and 'api_key' not in caplog.text


def test_readiness_accepts_explicit_proxy_without_http_or_key(monkeypatch, capsys):
    service = module()
    monkeypatch.delenv('OPENAI_HTTP_PROXY', raising=False)
    assert service.main(['--proxy', 'http://127.0.0.1:7897']) == 0
    assert 'transport=local_proxy' in capsys.readouterr().out
    assert configured_proxy() == 'http://127.0.0.1:7897'
    with pytest.raises(ConfigInvalid):
        service.main(['--proxy', 'http://user:secret@127.0.0.1:7897'])


def test_deepseek_transport_does_not_use_openai_proxy(monkeypatch):
    from types import SimpleNamespace

    from backend.app.infrastructure.model_profile import DEFAULT_PROFILE
    from backend.app.infrastructure.model_profile import ENDPOINT as ARK_ENDPOINT

    monkeypatch.setenv('OPENAI_HTTP_PROXY', 'http://127.0.0.1:7897')
    settings, seen = [], []
    profile = ModelProfile('offline-ark-proxy-isolation', DEFAULT_PROFILE)

    def reply(request):
        seen.append(str(request.url))
        return httpx.Response(
            200,
            json={
                'object': 'chat.completion',
                'model': profile.model_name,
                'choices': [
                    {
                        'finish_reason': 'stop',
                        'message': {'role': 'assistant', 'content': '{"message":"离线"}'},
                    }
                ],
                'usage': {'prompt_tokens': 2000, 'completion_tokens': 100},
            },
        )

    def factory(**kwargs):
        settings.append(kwargs)
        return httpx.MockTransport(reply)

    monkeypatch.setattr(
        'backend.app.infrastructure.model_gateway.httpx.AsyncHTTPTransport', factory
    )
    result = asyncio.run(
        ModelGateway().send(
            profile, SimpleNamespace(system='旧系统协议', input_json='{"old":true}')
        )
    )
    assert result.succeeded and seen == [ARK_ENDPOINT]
    assert settings == [{'retries': 0, 'trust_env': False}]
