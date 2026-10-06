"""D-011 one exact Ark text-count request. No Chat request or retry.

This adapter proves response ownership and records returned counts; it cannot
prove Chat framing, approve a counting strategy, or enable paid application
execution. No production caller uses it until the new release passes that gate.
"""
from dataclasses import dataclass, field
import hashlib
import json

import httpx

from .audit_data import audit_json, MAX_AUDIT_BYTES
from .model_profile import ModelProfile, MODEL_ID, BASE_URL
from .resources import ConfigInvalid
from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_json_object

ENDPOINT = BASE_URL + '/tokenization'
STRATEGY = 'ark_exact_text_counts_v1_pending_chat_framing_proof'


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

    @property
    def evidence(self):
        return {'strategy': STRATEGY, 'endpoint': ENDPOINT, 'model': self.model,
                'request_id': self.request_id, 'created': self.created,
                'counts': list(self.counts), 'text_sha256': list(self.text_sha256),
                'request_sha256': self.request_sha256,
                'response': strict_json_object(self.response_json)}


class TokenizationGateway:
    def __init__(self, *, transport_factory=None):
        # Private loopback test injection; no endpoint/environment override.
        self._transport_factory = transport_factory

    async def count(self, profile: ModelProfile, texts: tuple[str, ...]) -> TokenCounts:
        if type(profile) is not ModelProfile or type(texts) is not tuple or not texts or any(type(text) is not str for text in texts):
            raise ConfigInvalid('Frozen model and immutable text batch required')
        try:
            body = {'model': MODEL_ID, 'text': list(texts)}
            request = json.dumps(body, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
            if len(request) > MAX_AUDIT_BYTES: raise ValueError('Counting request capacity')
            text_hashes = tuple(hashlib.sha256(text.encode('utf-8')).hexdigest() for text in texts)
            transport = httpx.AsyncHTTPTransport(retries=0, trust_env=False) if self._transport_factory is None else self._transport_factory()
            async with httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False,
                                        timeout=httpx.Timeout(connect=10, read=180, write=10, pool=10)) as client:
                async with client.stream('POST', ENDPOINT, headers={'Authorization': 'Bearer ' + profile.api_key,
                        'Content-Type': 'application/json'}, content=request) as response:
                    if response.status_code != 200: raise ValueError('Counting response status')
                    parts, size = [], 0
                    async for part in response.aiter_bytes():
                        size += len(part)
                        if size > MAX_AUDIT_BYTES: raise ValueError('Counting response capacity')
                        parts.append(part)
                    raw = strict_json_object(b''.join(parts).decode('utf-8'))
            if raw.get('object') != 'list' or raw.get('model') != MODEL_ID:
                raise ValueError('Counting response belongs to another model')
            identity = raw.get('id')
            if type(identity) is not str or not identity or len(identity) > 1024 or any(ord(char) < 32 or ord(char) == 127 for char in identity):
                raise ValueError('Counting request identity missing')
            created = integer(raw.get('created'))
            rows = raw.get('data')
            if type(rows) is not list or len(rows) != len(texts): raise ValueError('Incomplete text counts')
            counts = []
            for index, row in enumerate(rows):
                if type(row) is not dict or row.get('object') != 'tokenization' or type(row.get('index')) is not int or row['index'] != index:
                    raise ValueError('Text count order/identity mismatch')
                count = integer(row.get('total_tokens')); ids, offsets = row.get('token_ids'), row.get('offset_mapping')
                if type(ids) is not list or type(offsets) is not list or len(ids) != count or len(offsets) != count:
                    raise ValueError('Token count/arrays disagree')
                for token in ids: integer(token)
                for offset in offsets:
                    if type(offset) is not list or len(offset) != 2 or integer(offset[0]) > integer(offset[1]):
                        raise ValueError('Token offset structure invalid')
                counts.append(count)
            sanitized = audit_json(raw, credentials=(profile.api_key,))
            if strict_json_object(sanitized).get('id') != identity:
                raise ValueError('Counting trace echoed a credential')
            return TokenCounts(MODEL_ID, identity, created, tuple(counts), text_hashes,
                               hashlib.sha256(request).hexdigest(), sanitized)
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, httpx.HTTPError) as error:
            # Never expose Provider bodies, input text or credentials in errors.
            raise ConfigInvalid('Exact model text counts are unavailable; Chat must not be sent') from error
