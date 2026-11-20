"""Opaque, bounded, request-bound read cursors; no database identities are allocated."""

import base64
import binascii
import hashlib
import re

from backend.app.shared.json_canonical import canonical_input
from backend.app.shared.validation import object_fields, reject, strict_integer, strict_json_object

SCHEMA = 'formation_cursor_v21_1'


def filter_digest(value):
    return hashlib.sha256(canonical_input(value).encode('utf-8')).hexdigest()


def encode(document_id, kind, filters, anchor):
    data = {
        'schema': SCHEMA,
        'document_id': document_id,
        'kind': kind,
        'filters_digest': filter_digest(filters),
        'anchor': anchor,
    }
    return (
        base64.urlsafe_b64encode(canonical_input(data).encode('utf-8')).decode('ascii').rstrip('=')
    )


def decode(value, document_id, kind, filters):
    if (
        type(value) is not str
        or not 1 <= len(value) <= 4096
        or re.fullmatch(r'[A-Za-z0-9_-]+', value) is None
    ):
        reject('cursor', 'INVALID_FORMAT', '分页游标不合法')
    try:
        raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
        item = strict_json_object(raw, 'cursor')
        object_fields(
            item,
            'cursor',
            ('schema', 'document_id', 'kind', 'filters_digest', 'anchor'),
            ('schema', 'document_id', 'kind', 'filters_digest', 'anchor'),
        )
        strict_integer(item['document_id'], 'cursor.document_id')
        if (
            item['schema'] != SCHEMA
            or item['document_id'] != document_id
            or (item['kind'] != kind or item['filters_digest'] != filter_digest(filters))
            or type(item['anchor']) is not dict
        ):
            raise ValueError('Cursor belongs to another read')
        if encode(document_id, kind, filters, item['anchor']) != value:
            raise ValueError('Cursor encoding is not canonical')
        return item['anchor']
    except (ValueError, UnicodeError, binascii.Error):
        reject('cursor', 'INVALID_FORMAT', '分页游标与当前查询不匹配')
