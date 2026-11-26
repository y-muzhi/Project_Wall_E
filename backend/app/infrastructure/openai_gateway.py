"""One native OpenAI Responses attempt; cancellation closes its own client."""

import asyncio
import json
from time import monotonic

import httpx

from backend.app.shared.validation import strict_json_object

from .audit_data import MAX_AUDIT_BYTES, AuditCapacityExceeded, audit_json
from .model_gateway import TransportResult
from .model_profile import OPENAI_DOCUMENT_PROFILE
from .openai_protocol import ENDPOINT, MODEL, output_text, usage
from .openai_transport import create_transport, report_transport_error


def category(status, code):
    if status == 401:
        return 'AUTHENTICATION'
    if status == 403:
        return 'PERMISSION'
    if status == 429:
        return (
            'QUOTA'
            if code in ('insufficient_quota', 'billing_hard_limit_reached')
            else 'RATE_LIMIT'
        )
    if status in (408, 500, 502, 503, 504):
        return 'TEMPORARY_SERVICE'
    if status == 400:
        return 'PARAMETER'
    if status == 404:
        return 'MODEL_CONFIGURATION'
    return 'HTTP_ERROR'


class OpenAIGateway:
    def __init__(self, *, transport_factory=None):
        self.transport_factory = transport_factory

    async def send(self, profile, context):
        if profile.provider != 'openai':
            raise ValueError('An OpenAI profile is required')
        body = profile.request(context)
        read_timeout = 1800 if profile.profile_id == OPENAI_DOCUMENT_PROFILE else 180
        started = monotonic()
        status = None
        raw = trace = finish = code = cache = None
        incoming = outgoing = None

        def result(ok, kind=None):
            return TransportResult(
                ok,
                kind,
                False,
                status,
                code,
                max(0, round((monotonic() - started) * 1000)),
                raw,
                incoming,
                outgoing,
                cache,
                trace,
                finish,
            )

        transport = (
            create_transport() if self.transport_factory is None else self.transport_factory()
        )
        try:
            async with httpx.AsyncClient(
                transport=transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(connect=10, read=read_timeout, write=10, pool=10),
            ) as client:
                async with client.stream(
                    'POST',
                    ENDPOINT,
                    headers={
                        'Authorization': 'Bearer ' + profile.api_key,
                        'Content-Type': 'application/json',
                    },
                    content=json.dumps(
                        body, ensure_ascii=False, separators=(',', ':'), allow_nan=False
                    ).encode('utf-8'),
                ) as response:
                    status = response.status_code
                    parts, size = [], 0
                    async for part in response.aiter_bytes():
                        size += len(part)
                        if size > MAX_AUDIT_BYTES:
                            return result(False, 'RESPONSE_CAPACITY')
                        parts.append(part)
                    original = strict_json_object(b''.join(parts))
                    raw = audit_json(original, credentials=(profile.api_key,))
            safe = strict_json_object(raw)
            error = safe.get('error')
            if type(error) is dict:
                candidate = error.get('code')
                code = candidate if type(candidate) is str and len(candidate) <= 256 else None
            if not 200 <= status < 300:
                return result(False, category(status, code))
            if original.get('model') != MODEL or original.get('object') != 'response':
                return result(False, 'RESPONSE_PROTOCOL')
            candidate = safe.get('id')
            if (
                type(candidate) is str
                and candidate
                and len(candidate) <= 1024
                and candidate == original.get('id')
            ):
                trace = candidate
            else:
                return result(False, 'RESPONSE_PROTOCOL')
            incoming, outgoing, details = usage(original)
            cache = (
                None
                if details is None
                else audit_json(safe.get('usage', {}).get('input_tokens_details'))
            )
            state = original.get('status')
            finish = (
                'stop'
                if state == 'completed'
                else 'length'
                if (
                    state == 'incomplete'
                    and type(original.get('incomplete_details')) is dict
                    and original['incomplete_details'].get('reason') == 'max_output_tokens'
                )
                else str(state)
            )
            try:
                content = output_text(original)
                if content != output_text(safe):
                    return result(False, 'CREDENTIAL_ECHO')
            except (ValueError, KeyError, TypeError):
                return result(True, 'OUTPUT_LIMIT' if finish == 'length' else 'RESPONSE_PROTOCOL')
            return result(True)
        except asyncio.CancelledError:
            raise
        except AuditCapacityExceeded:
            return result(False, 'RESPONSE_CAPACITY')
        except (ValueError, KeyError, TypeError, UnicodeError, RecursionError):
            return result(False, 'RESPONSE_PROTOCOL')
        except httpx.HTTPError as error:
            report_transport_error('responses', error)
            failure = 'READ_TIMEOUT' if isinstance(error, httpx.ReadTimeout) else 'TRANSPORT_ERROR'
            return result(False, failure)
