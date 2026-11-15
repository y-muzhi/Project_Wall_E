"""Data-only literals and operands for the protected CHECK20 CasePack."""

import re
from base64 import b64decode, b64encode
from binascii import Error as Base64Error
from math import isfinite
from urllib.parse import unquote_to_bytes, urlsplit

from backend.app.shared.validation import strict_integer

from .check_runner_bundle import CheckResourceError, exact_record, reference

_MAX_TEXT = 4096
_SAFE_PATH = re.compile(r'[/A-Za-z0-9._~!$&()*+,;=:@?%\-]*')
_BAD_PERCENT = re.compile(r'%(?![A-Fa-f0-9]{2})')
_POINTER_ESCAPE = re.compile(r'~(?![01])')
_HEADERS = frozenset({'accept', 'content-type', 'content-language', 'if-match', 'if-none-match'})
_RESPONSE_HEADERS = _HEADERS | {'cache-control', 'etag', 'vary', 'content-encoding'}
_METHODS = frozenset({'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'})
_KEYS = frozenset(
    {'Enter', 'Escape', 'Tab', 'Space', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'}
)
_ROLES = frozenset(
    {
        'alert',
        'button',
        'cell',
        'checkbox',
        'combobox',
        'dialog',
        'form',
        'heading',
        'img',
        'link',
        'list',
        'listbox',
        'listitem',
        'main',
        'menu',
        'menuitem',
        'navigation',
        'option',
        'progressbar',
        'radio',
        'region',
        'row',
        'searchbox',
        'slider',
        'spinbutton',
        'status',
        'switch',
        'tab',
        'table',
        'tabpanel',
        'textbox',
        'tree',
        'treeitem',
    }
)


def text_literal(value, *, empty=False, limit=_MAX_TEXT):
    if type(value) is not str or len(value) > limit or not empty and not value.strip():
        raise CheckResourceError('CASE_PACK_TEXT_INVALID')
    if any(ord(char) < 32 and char not in '\r\n\t' or ord(char) == 127 for char in value):
        raise CheckResourceError('CASE_PACK_TEXT_INVALID')
    value.encode('utf-8', errors='strict')
    return value


def byte_literal(value, limit):
    if type(value) is not str or len(value) > (limit + 2) // 3 * 4:
        raise CheckResourceError('CASE_PACK_BYTES_INVALID')
    try:
        decoded = b64decode(value, validate=True)
    except (Base64Error, ValueError) as error:
        raise CheckResourceError('CASE_PACK_BYTES_INVALID') from error
    if len(decoded) > limit or b64encode(decoded).decode('ascii') != value:
        raise CheckResourceError('CASE_PACK_BYTES_INVALID')
    return decoded


def json_pointer(value):
    value = text_literal(value, empty=True, limit=1024)
    if value and not value.startswith('/') or _POINTER_ESCAPE.search(value):
        raise CheckResourceError('CASE_PACK_JSON_POINTER_INVALID')
    tokens = value[1:].split('/') if value else ()
    if len(tokens) > 32:
        raise CheckResourceError('CASE_PACK_JSON_POINTER_INVALID')
    return tuple(token.replace('~1', '/').replace('~0', '~') for token in tokens)


def json_literal(value, *, depth=0):
    if depth > 16:
        raise CheckResourceError('CASE_PACK_JSON_LITERAL_INVALID')
    if value is None or type(value) is bool:
        return value
    if type(value) is str:
        return text_literal(value, empty=True)
    if type(value) is int and abs(value) <= (1 << 53) - 1:
        return value
    if type(value) is float and isfinite(value):
        return value
    if type(value) is list and len(value) <= 256:
        return [json_literal(item, depth=depth + 1) for item in value]
    if type(value) is dict and len(value) <= 256:
        return {
            text_literal(key, empty=True): json_literal(item, depth=depth + 1)
            for key, item in value.items()
        }
    raise CheckResourceError('CASE_PACK_JSON_LITERAL_INVALID')


def relative_target(value):
    if (
        type(value) is not str
        or len(value) > 2048
        or not value.startswith('/')
        or value.startswith('//')
        or not _SAFE_PATH.fullmatch(value)
        or _BAD_PERCENT.search(value)
    ):
        raise CheckResourceError('CASE_PACK_RELATIVE_TARGET_INVALID')
    url = urlsplit(value)
    if url.scheme or url.netloc or url.fragment:
        raise CheckResourceError('CASE_PACK_RELATIVE_TARGET_INVALID')
    for part in url.path.split('/'):
        decoded = unquote_to_bytes(part)
        if decoded in (b'.', b'..') or any(
            byte in decoded for byte in (b'/', b'\\', b'%', b'?', b'#')
        ):
            raise CheckResourceError('CASE_PACK_RELATIVE_TARGET_INVALID')
    if any(byte < 32 or byte == 127 for byte in unquote_to_bytes(value)):
        raise CheckResourceError('CASE_PACK_RELATIVE_TARGET_INVALID')
    return value


def endpoint_target(row, allowed):
    endpoint = reference(row['endpoint_ref'])
    if endpoint not in allowed:
        raise CheckResourceError('CASE_PACK_ENDPOINT_NOT_DECLARED')
    return endpoint, relative_target(row['path'])


def header_value(value):
    value = text_literal(value, empty=True, limit=1024)
    if any(not 32 <= ord(character) <= 126 for character in value):
        raise CheckResourceError('CASE_PACK_HEADER_VALUE_INVALID')
    return value


def request_headers(values):
    if type(values) is not dict or not values.keys() <= _HEADERS:
        raise CheckResourceError('CASE_PACK_REQUEST_HEADERS_INVALID')
    return tuple(sorted((name, header_value(value)) for name, value in values.items()))


def response_header(name):
    if type(name) is not str or name not in _RESPONSE_HEADERS:
        raise CheckResourceError('CASE_PACK_RESPONSE_HEADER_INVALID')
    return name


def request_method(method):
    if type(method) is not str or method not in _METHODS:
        raise CheckResourceError('CASE_PACK_HTTP_METHOD_INVALID')
    return method


def browser_locator(value):
    if type(value) is not dict:
        raise CheckResourceError('CASE_PACK_BROWSER_LOCATOR_INVALID')
    kind = value.get('kind')
    if kind == 'TEST_ID':
        exact_record(value, ('kind', 'value'))
        return kind, reference(value['value']), None
    if kind == 'ROLE':
        exact_record(value, ('kind', 'value', 'name'))
        role = value['value']
        name = value['name']
        if type(role) is str and role in _ROLES:
            return kind, role, None if name is None else text_literal(name, limit=256)
    raise CheckResourceError('CASE_PACK_BROWSER_LOCATOR_INVALID')


def browser_key(value):
    if type(value) is not str or value not in _KEYS:
        raise CheckResourceError('CASE_PACK_BROWSER_KEY_INVALID')
    return value


def bounded_count(value):
    return strict_integer(value, 'expected', minimum=0, maximum=100_000)
