"""D-011 one exact Ark text-count request. No Chat request or retry.

This adapter proves response ownership and records returned counts; it cannot
prove Chat framing, approve a counting strategy, or enable paid application
execution. No production caller uses it until the new release passes that gate.
"""

from dataclasses import dataclass, field
import hashlib
import json
import re

import httpx

from .audit_data import audit_json, MAX_AUDIT_BYTES, AuditCapacityExceeded
from .model_profile import ModelProfile, MODEL_ID, DEEPSEEK_MODEL_ID, BASE_URL
from .resources import ConfigInvalid
from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_json_object

ENDPOINT = BASE_URL + '/tokenization'
STRATEGY = 'ark_exact_text_counts_v1_pending_chat_framing_proof'
DEEPSEEK_STRATEGY = 'ark_exact_text_counts_deepseek_v2_pending_chat_framing_proof'

COUNT_FAILURE_REASONS = frozenset(
    {
        'HTTP_STATUS',
        'REQUEST_CAPACITY',
        'RESPONSE_CAPACITY',
        'AUDIT_CAPACITY',
        'INVALID_RESPONSE',
        'TRANSPORT_ERROR',
        'PROVIDER_INPUT_LIMIT',
    }
)
COUNT_ERROR_BODY_BYTES = 16 * 1024
COUNT_RESPONSE_BYTES = 8 * 1024 * 1024
# Observed on the fixed Beijing endpoint/exact DeepSeek model, 2026-10-24.
# This is the sum of UTF-8 text bytes, not JSON size or a Chat token budget.
DEEPSEEK_TEXT_BYTES = 800000
ERROR_BODY_STATES = frozenset(
    {'JSON_ERROR', 'NO_ERROR_OBJECT', 'INVALID_JSON', 'OVERSIZED', 'READ_UNAVAILABLE'}
)


def provider_error_value(value):
    """Detached, strictly bounded private diagnostic; no arbitrary envelope."""
    if value is None:
        return None
    fields = {
        'body_state',
        'category',
        'code',
        'parameter',
        'message',
        'message_truncated',
        'request_id',
    }
    if (
        type(value) is not dict
        or set(value) not in (fields, fields | {'body_keys'})
        or type(value['body_state']) is not str
        or value['body_state'] not in ERROR_BODY_STATES
    ):
        raise ValueError('Invalid count error details')
    if 'body_keys' in value and (
        type(value['body_keys']) is not list
        or len(value['body_keys']) > 20
        or any(
            type(key) is not str or re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', key) is None
            for key in value['body_keys']
        )
    ):
        raise ValueError('Invalid count error field names')
    if (
        type(value['category']) is not str
        or re.fullmatch(r'[A-Z_]{1,64}', value['category']) is None
        or type(value['message_truncated']) is not bool
    ):
        raise ValueError('Invalid count error category')
    for key, pattern in (
        ('code', r'[A-Za-z0-9_.-]{1,256}'),
        ('parameter', r'[A-Za-z0-9_.\[\]-]{1,128}'),
        ('request_id', r'[A-Za-z0-9_.:-]{1,256}'),
    ):
        if value[key] is not None and (
            type(value[key]) is not str or re.fullmatch(pattern, value[key]) is None
        ):
            raise ValueError('Invalid count error identity')
    if value['message'] is not None:
        if type(value['message']) is not str or len(value['message']) > 2048:
            raise ValueError('Invalid count error message capacity')
        value['message'].encode('utf-8', errors='strict')
    return strict_json_object(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _error_fields(value):
    """Select explanation fields from common HTTP error envelopes only.

    Never fall back to serializing arbitrary input/response bodies as a message.
    The same projection runs before/after redaction to prove identity values.
    """

    def first(row, keys):
        return next((row[key] for key in keys if type(row.get(key)) is str), None)

    rows = [value.get('error'), value.get('Error')]
    for name in ('ResponseMetadata', 'response_metadata'):
        metadata = value.get(name)
        if type(metadata) is dict:
            rows.extend((metadata.get('Error'), metadata.get('error')))
    rows.append(value.get('detail'))
    for row in rows:
        if type(row) is dict:
            return {
                'code': first(row, ('code', 'Code', 'type')),
                'param': first(row, ('param', 'parameter', 'Param')),
                'message': first(row, ('message', 'Message', 'msg', 'description')),
            }
    message = first(value, ('message', 'Message', 'msg', 'error_description', 'detail', 'error'))
    if message is not None:
        return {
            'code': first(value, ('code', 'Code', 'type')),
            'param': first(value, ('param', 'parameter', 'Param')),
            'message': message,
        }
    detail = value.get('detail')
    if type(detail) is list:
        explanations = []
        location = None
        code = None
        for item in detail[:5]:
            if type(item) is str:
                explanations.append(item)
            elif type(item) is dict:
                part = first(item, ('msg', 'message', 'Message'))
                if part is not None:
                    explanations.append(part)
                if len(detail) == 1:
                    code = first(item, ('code', 'type'))
                    loc = item.get('loc')
                    if (
                        type(loc) is list
                        and len(loc) <= 8
                        and all(type(x) in (str, int) for x in loc)
                    ):
                        location = '.'.join(str(x) for x in loc)
        if explanations:
            return {'code': code, 'param': location, 'message': '; '.join(explanations)}
    return None


async def _http_error(response, profile):
    """Read one bounded error response, scrub before truncating any field.

    The provider message belongs only in the normal private journal, never an
    exception message, console, ordinary task response or verification log.
    Reading a failed response never sends another request.
    """
    from .model_gateway import classify_error

    value = {
        'body_state': 'INVALID_JSON',
        'category': classify_error(response.status_code, None)[0],
        'code': None,
        'parameter': None,
        'message': None,
        'message_truncated': False,
        'request_id': None,
    }
    chunks = []
    size = 0
    try:
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > COUNT_ERROR_BODY_BYTES:
                value['body_state'] = 'OVERSIZED'
                break
            chunks.append(chunk)
        else:
            try:
                original = strict_json_object(b''.join(chunks))
                # Redact the complete bounded body before slicing, including
                # credentials crossing the eventual 2048-character boundary.
                safe = strict_json_object(audit_json(original, credentials=(profile.api_key,)))
                value['body_keys'] = sorted(
                    key for key in safe if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', key)
                )[:20]
                error = _error_fields(safe)
                value['body_state'] = 'JSON_ERROR' if type(error) is dict else 'NO_ERROR_OBJECT'
                if type(error) is dict:
                    code = error.get('code')
                    parameter = error.get('param')
                    original_error = _error_fields(original) or {}
                    if (
                        type(code) is str
                        and code == original_error.get('code')
                        and re.fullmatch(r'[A-Za-z0-9_.-]{1,256}', code)
                    ):
                        value['code'] = code
                    if (
                        type(parameter) is str
                        and parameter == original_error.get('param')
                        and re.fullmatch(r'[A-Za-z0-9_.\[\]-]{1,128}', parameter)
                    ):
                        value['parameter'] = parameter
                    message = error.get('message')
                    if type(message) is str:
                        value['message'] = message[:2048]
                        value['message_truncated'] = len(message) > 2048
                    value['category'] = classify_error(response.status_code, value['code'])[0]
            except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
                value['body_state'] = 'INVALID_JSON'
    except httpx.HTTPError:
        # HTTP status was already received. Preserve that known fact even if
        # its optional diagnostic body cannot be read; do not retry.
        value['body_state'] = 'READ_UNAVAILABLE'
    trace = response.headers.get('x-request-id') or response.headers.get('x-tt-logid')
    if type(trace) is str and len(trace) <= 1024:
        safe_trace = strict_json_object(
            audit_json({'value': trace}, credentials=(profile.api_key,))
        )['value']
        if safe_trace == trace and re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}', safe_trace):
            value['request_id'] = safe_trace
    try:
        return provider_error_value(value)
    except (ValueError, TypeError, UnicodeError):
        return provider_error_value(
            {
                **value,
                'code': None,
                'parameter': None,
                'message': None,
                'message_truncated': False,
                'body_state': 'INVALID_JSON',
            }
        )


class ExactCountUnavailable(ConfigInvalid):
    """Bounded diagnostic facts only; never retain provider error bodies."""

    def __init__(self, reason, http_status=None, *, provider_error=None):
        if reason not in COUNT_FAILURE_REASONS or (
            http_status is not None
            and (
                reason != 'HTTP_STATUS'
                or type(http_status) is not int
                or not 100 <= http_status <= 599
            )
        ):
            raise ValueError('Invalid counting failure summary')
        self.reason, self.http_status = reason, http_status
        if provider_error is not None and (reason != 'HTTP_STATUS' or http_status is None):
            raise ValueError('Provider details require a known failed HTTP status')
        self._provider_error_json = (
            None
            if provider_error is None
            else json.dumps(provider_error_value(provider_error), ensure_ascii=False)
        )
        super().__init__('Exact model text counts are unavailable; Chat must not be sent')

    @property
    def provider_error(self):
        return (
            None
            if self._provider_error_json is None
            else strict_json_object(self._provider_error_json)
        )


def strategy_for(model):
    if model == MODEL_ID:
        return STRATEGY
    if model == DEEPSEEK_MODEL_ID:
        return DEEPSEEK_STRATEGY
    raise ConfigInvalid('Exact counting model is not approved')


def check_text_capacity(profile, texts):
    """Pure preflight, also used before bounded delegates consume IO grants."""
    if (
        type(profile) is not ModelProfile
        or type(texts) is not tuple
        or not texts
        or any(type(text) is not str for text in texts)
    ):
        raise ConfigInvalid('Frozen model and immutable text batch required')
    size = sum(len(text.encode('utf-8')) for text in texts)
    if profile.model_name == DEEPSEEK_MODEL_ID and size > DEEPSEEK_TEXT_BYTES:
        raise ExactCountUnavailable('PROVIDER_INPUT_LIMIT')
    return size


def integer(value):
    if type(value) is not int or not 0 <= value <= MAX_SAFE_INTEGER:
        raise ValueError('Count must be an exact nonnegative integer')
    return value


@dataclass(frozen=True)
class TokenCounts:
    model: str
    request_id: str
    created: int
    counts: tuple[int, ...]
    text_sha256: tuple[str, ...]
    request_sha256: str
    response_json: str = field(repr=False)
    journal_id: str | None = None
    response_digest: str | None = None

    @property
    def evidence(self):
        return (
            {
                'strategy': strategy_for(self.model),
                'endpoint': ENDPOINT,
                'model': self.model,
                'request_id': self.request_id,
                'created': self.created,
                'counts': list(self.counts),
                'text_sha256': list(self.text_sha256),
                'request_sha256': self.request_sha256,
            }
            | (
                {'response': strict_json_object(self.response_json)}
                if self.response_digest is None
                else {'response_sha256': self.response_digest}
            )
            | ({} if self.journal_id is None else {'journal_id': self.journal_id})
        )


def restore_measurement(value, texts, *, raw_required=True, expected_model=MODEL_ID):
    """Recheck persisted count ownership; summaries never assert raw retention."""
    from .idempotency import canonical_input

    try:
        strategy = strategy_for(expected_model)
        fields = {
            'strategy',
            'endpoint',
            'model',
            'request_id',
            'created',
            'counts',
            'text_sha256',
            'request_sha256',
        }
        optional = {'journal_id'} if type(value) is dict and 'journal_id' in value else set()
        if (
            type(value) is not dict
            or set(value)
            != fields | ({'response'} if raw_required else {'response_sha256'}) | optional
        ):
            raise ValueError('Count evidence fields')
        hashes = [hashlib.sha256(text.encode('utf-8')).hexdigest() for text in texts]
        request = json.dumps(
            {'model': expected_model, 'text': list(texts)},
            ensure_ascii=False,
            separators=(',', ':'),
            allow_nan=False,
        ).encode('utf-8')
        if (
            value['strategy'] != strategy
            or value['endpoint'] != ENDPOINT
            or value['model'] != expected_model
            or value['text_sha256'] != hashes
            or value['request_sha256'] != hashlib.sha256(request).hexdigest()
        ):
            raise ValueError('Count evidence ownership')
        identity = value['request_id']
        if (
            type(identity) is not str
            or not identity
            or len(identity) > 1024
            or any(ord(char) < 32 or ord(char) == 127 for char in identity)
        ):
            raise ValueError('Count identity')
        created = integer(value['created'])
        if type(value['counts']) is not list or len(value['counts']) != len(texts):
            raise ValueError('Count dimensions')
        counts = tuple(integer(count) for count in value['counts'])
        journal_id = value.get('journal_id')
        if optional and (
            type(journal_id) is not str
            or len(journal_id) != 32
            or any(char not in '0123456789abcdef' for char in journal_id)
        ):
            raise ValueError('Counting journal identity')
        if raw_required:
            raw = value['response']
            if (
                type(raw) is not dict
                or raw.get('object') != 'list'
                or raw.get('model') != expected_model
                or raw.get('id') != identity
                or type(raw.get('created')) is not int
                or raw['created'] != created
            ):
                raise ValueError('Count response')
            rows = raw.get('data')
            if type(rows) is not list or len(rows) != len(texts):
                raise ValueError('Count response rows')
            for index, (row, count) in enumerate(zip(rows, counts)):
                if (
                    type(row) is not dict
                    or row.get('object') != 'tokenization'
                    or type(row.get('index')) is not int
                    or row['index'] != index
                    or integer(row.get('total_tokens')) != count
                ):
                    raise ValueError('Count row')
                ids, offsets = row.get('token_ids'), row.get('offset_mapping')
                if (
                    type(ids) is not list
                    or type(offsets) is not list
                    or len(ids) != count
                    or len(offsets) != count
                ):
                    raise ValueError('Count arrays')
                for token in ids:
                    integer(token)
                for offset in offsets:
                    if (
                        type(offset) is not list
                        or len(offset) != 2
                        or integer(offset[0]) > integer(offset[1])
                    ):
                        raise ValueError('Count offsets')
            response_json = canonical_input(raw)
        else:
            digest = value['response_sha256']
            if (
                type(digest) is not str
                or len(digest) != 64
                or any(char not in '0123456789abcdef' for char in digest)
            ):
                raise ValueError('Count response digest')
            response_json = '{}'
        return TokenCounts(
            expected_model,
            identity,
            created,
            counts,
            tuple(hashes),
            value['request_sha256'],
            response_json,
            journal_id,
            None if raw_required else value['response_sha256'],
        )
    except (ValueError, TypeError, KeyError, UnicodeError) as error:
        raise ConfigInvalid('Persisted exact count evidence is invalid') from error


def measurement_summary(value):
    """Keep returned counts/identity; raw token arrays have separate retention."""
    from .idempotency import canonical_input

    return {key: child for key, child in value.items() if key != 'response'} | {
        'response_sha256': hashlib.sha256(
            canonical_input(value['response']).encode('utf-8')
        ).hexdigest()
    }


class TokenizationGateway:
    def __init__(self, *, transport_factory=None):
        # Private loopback test injection; no endpoint/environment override.
        self._transport_factory = transport_factory

    async def count(self, profile: ModelProfile, texts: tuple[str, ...]) -> TokenCounts:
        try:
            check_text_capacity(profile, texts)
            body = {'model': profile.model_name, 'text': list(texts)}
            request = json.dumps(
                body, ensure_ascii=False, separators=(',', ':'), allow_nan=False
            ).encode('utf-8')
            if len(request) > MAX_AUDIT_BYTES:
                raise ExactCountUnavailable('REQUEST_CAPACITY')
            text_hashes = tuple(hashlib.sha256(text.encode('utf-8')).hexdigest() for text in texts)
            transport = (
                httpx.AsyncHTTPTransport(retries=0, trust_env=False)
                if self._transport_factory is None
                else self._transport_factory()
            )
            async with httpx.AsyncClient(
                transport=transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(connect=10, read=180, write=10, pool=10),
            ) as client:
                async with client.stream(
                    'POST',
                    ENDPOINT,
                    headers={
                        'Authorization': 'Bearer ' + profile.api_key,
                        'Content-Type': 'application/json',
                    },
                    content=request,
                ) as response:
                    if response.status_code != 200:
                        raise ExactCountUnavailable(
                            'HTTP_STATUS',
                            response.status_code,
                            provider_error=await _http_error(response, profile),
                        )
                    parts, size = [], 0
                    async for part in response.aiter_bytes():
                        size += len(part)
                        if size > COUNT_RESPONSE_BYTES:
                            raise ExactCountUnavailable('RESPONSE_CAPACITY')
                        parts.append(part)
                    raw = strict_json_object(b''.join(parts).decode('utf-8'))
            if raw.get('object') != 'list' or raw.get('model') != profile.model_name:
                raise ValueError('Counting response belongs to another model')
            identity = raw.get('id')
            if (
                type(identity) is not str
                or not identity
                or len(identity) > 1024
                or any(ord(char) < 32 or ord(char) == 127 for char in identity)
            ):
                raise ValueError('Counting request identity missing')
            created = integer(raw.get('created'))
            rows = raw.get('data')
            if type(rows) is not list or len(rows) != len(texts):
                raise ValueError('Incomplete text counts')
            counts = []
            for index, row in enumerate(rows):
                if (
                    type(row) is not dict
                    or row.get('object') != 'tokenization'
                    or type(row.get('index')) is not int
                    or row['index'] != index
                ):
                    raise ValueError('Text count order/identity mismatch')
                count = integer(row.get('total_tokens'))
                ids, offsets = row.get('token_ids'), row.get('offset_mapping')
                if (
                    type(ids) is not list
                    or type(offsets) is not list
                    or len(ids) != count
                    or len(offsets) != count
                ):
                    raise ValueError('Token count/arrays disagree')
                for token in ids:
                    integer(token)
                for offset in offsets:
                    if (
                        type(offset) is not list
                        or len(offset) != 2
                        or integer(offset[0]) > integer(offset[1])
                    ):
                        raise ValueError('Token offset structure invalid')
                counts.append(count)
            if (
                strict_json_object(
                    audit_json({'id': identity}, credentials=(profile.api_key,))
                ).get('id')
                != identity
            ):
                raise ValueError('Counting trace echoed a credential')
            try:
                sanitized = audit_json(raw, credentials=(profile.api_key,))
                response_digest = None
            except AuditCapacityExceeded:
                # Arrays were fully validated above. Retain only bounded facts
                # and a canonical response digest. This cannot approve Chat:
                # callers require raw evidence for every accepted candidate.
                from .idempotency import canonical_input

                sanitized = '{}'
                response_digest = hashlib.sha256(canonical_input(raw).encode('utf-8')).hexdigest()
            return TokenCounts(
                profile.model_name,
                identity,
                created,
                tuple(counts),
                text_hashes,
                hashlib.sha256(request).hexdigest(),
                sanitized,
                response_digest=response_digest,
            )
        except ExactCountUnavailable:
            raise
        except AuditCapacityExceeded as error:
            raise ExactCountUnavailable('AUDIT_CAPACITY') from error
        except httpx.HTTPError as error:
            raise ExactCountUnavailable('TRANSPORT_ERROR') from error
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as error:
            # Never expose Provider bodies, input text or credentials in errors.
            raise ExactCountUnavailable('INVALID_RESPONSE') from error
