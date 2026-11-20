"""Native OpenAI whole-request count receipts, never fabricated Ark text counts."""

import asyncio
from dataclasses import dataclass, field

import httpx

from backend.app.shared.validation import strict_json_object

from .audit_data import MAX_AUDIT_BYTES, audit_json
from .collaboration_resources import sha256
from .openai_protocol import COUNT_ENDPOINT, MODEL, count_request, digest
from .openai_transport import create_transport, report_transport_error
from .resources import ConfigInvalid
from .schema_transport import compact
from .tokenization import ExactCountUnavailable, _http_error

STRATEGY = 'openai_responses_whole_request_v1'


@dataclass(frozen=True)
class OpenAIInputCount:
    model: str
    request_tokens: int
    request_sha256: str
    model_request_sha256: str
    text_sha256: tuple[str, ...]
    response_json: str = field(repr=False)
    provider_request_id: str | None = None
    journal_id: str | None = None
    response_digest: str | None = None

    @property
    def evidence(self):
        value = {
            'strategy': STRATEGY,
            'endpoint': COUNT_ENDPOINT,
            'model': self.model,
            'request_tokens': self.request_tokens,
            'request_sha256': self.request_sha256,
            'model_request_sha256': self.model_request_sha256,
            'text_sha256': list(self.text_sha256),
            'provider_request_id': self.provider_request_id,
        }
        if self.response_digest is None:
            value['response'] = strict_json_object(self.response_json)
        else:
            value['response_sha256'] = self.response_digest
        if self.journal_id is not None:
            value['journal_id'] = self.journal_id
        return value


def restore(value, context, profile, *, raw_required=True):
    try:
        if profile.provider != 'openai':
            raise ValueError('Wrong counting provider')
        body = profile.request(context)
        fixed = {
            'strategy',
            'endpoint',
            'model',
            'request_tokens',
            'request_sha256',
            'model_request_sha256',
            'text_sha256',
            'provider_request_id',
        }
        optional = {'journal_id'} if 'journal_id' in value else set()
        if set(value) != fixed | optional | ({'response'} if raw_required else {'response_sha256'}):
            raise ValueError('OpenAI count receipt fields differ')
        hashes = tuple(sha256(text) for text in context.texts)
        if (
            value['strategy'] != STRATEGY
            or value['endpoint'] != COUNT_ENDPOINT
            or value['model'] != MODEL
            or profile.model_name != MODEL
            or value['request_sha256'] != digest(count_request(body))
            or value['model_request_sha256'] != digest(body)
            or value['text_sha256'] != list(hashes)
        ):
            raise ValueError('OpenAI count request ownership differs')
        count = value['request_tokens']
        if type(count) is not int or not 0 < count <= 9007199254740991:
            raise ValueError('Invalid OpenAI input count')
        trace = value['provider_request_id']
        if trace is not None and (
            type(trace) is not str or not trace or len(trace) > 1024 or profile.api_key in trace
        ):
            raise ValueError('Invalid OpenAI count trace')
        journal = value.get('journal_id')
        if journal is not None and (
            type(journal) is not str
            or len(journal) != 32
            or any(character not in '0123456789abcdef' for character in journal)
        ):
            raise ValueError('Invalid OpenAI count journal')
        if raw_required:
            raw = value['response']
            if (
                type(raw) is not dict
                or raw.get('object') != 'response.input_tokens'
                or type(raw.get('input_tokens')) is not int
                or raw['input_tokens'] != count
            ):
                raise ValueError('Invalid native OpenAI count response')
            response_json, response_digest = compact(raw), None
        else:
            response_digest = value['response_sha256']
            if (
                type(response_digest) is not str
                or len(response_digest) != 64
                or any(c not in '0123456789abcdef' for c in response_digest)
            ):
                raise ValueError('Invalid OpenAI count response digest')
            response_json = '{}'
        return OpenAIInputCount(
            MODEL,
            count,
            value['request_sha256'],
            value['model_request_sha256'],
            hashes,
            response_json,
            trace,
            journal,
            response_digest,
        )
    except (ValueError, KeyError, TypeError, RecursionError) as error:
        raise ConfigInvalid('OpenAI exact count receipt is invalid') from error


class OpenAIInputCounter:
    def __init__(self, *, transport_factory=None):
        self.transport_factory = transport_factory

    async def count_context(self, profile, context):
        if profile.provider != 'openai':
            raise ConfigInvalid('OpenAI counting requires its own profile')
        body = profile.request(context)
        request = count_request(body)
        if len(compact(request).encode('utf-8')) > MAX_AUDIT_BYTES:
            raise ExactCountUnavailable('REQUEST_CAPACITY')
        transport = (
            create_transport() if self.transport_factory is None else self.transport_factory()
        )
        try:
            async with httpx.AsyncClient(
                transport=transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(connect=10, read=180, write=10, pool=10),
            ) as client:
                async with client.stream(
                    'POST',
                    COUNT_ENDPOINT,
                    headers={
                        'Authorization': 'Bearer ' + profile.api_key,
                        'Content-Type': 'application/json',
                    },
                    content=compact(request).encode('utf-8'),
                ) as response:
                    status = response.status_code
                    if not 200 <= status < 300:
                        from .openai_gateway import category

                        details = await _http_error(response, profile)
                        details['category'] = category(status, details['code'])
                        raise ExactCountUnavailable(
                            'HTTP_STATUS', http_status=status, provider_error=details
                        )
                    parts, size = [], 0
                    async for part in response.aiter_bytes():
                        size += len(part)
                        if size > MAX_AUDIT_BYTES:
                            raise ExactCountUnavailable('RESPONSE_CAPACITY')
                        parts.append(part)
                    raw = strict_json_object(b''.join(parts))
                    safe = audit_json(raw, credentials=(profile.api_key,))
                    trace = response.headers.get('x-request-id')
            value = {
                'strategy': STRATEGY,
                'endpoint': COUNT_ENDPOINT,
                'model': MODEL,
                'request_tokens': raw.get('input_tokens'),
                'request_sha256': digest(request),
                'model_request_sha256': digest(body),
                'text_sha256': [sha256(text) for text in context.texts],
                'provider_request_id': trace,
                'response': strict_json_object(safe),
            }
            return restore(value, context, profile)
        except asyncio.CancelledError:
            raise
        except ExactCountUnavailable:
            raise
        except httpx.HTTPError as error:
            report_transport_error('input_count', error)
            raise ExactCountUnavailable('TRANSPORT_ERROR') from error
        except (ValueError, KeyError, TypeError, UnicodeError, RecursionError) as error:
            raise ExactCountUnavailable('INVALID_RESPONSE') from error
