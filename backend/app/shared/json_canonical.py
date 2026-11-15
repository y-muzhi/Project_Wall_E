"""Shared exact finite JSON serialization; no database or application imports."""

import json
import math

from .validation import MAX_SAFE_INTEGER


def _json_value(value: object) -> None:
    if value is None or type(value) is bool:
        return
    if type(value) is str:
        value.encode('utf-8', errors='strict')
        return
    if type(value) is int:
        if abs(value) > MAX_SAFE_INTEGER:
            raise ValueError('JSON integer exceeds the shared exact range')
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _json_value(item)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for key, item in value.items():
            _json_value(key)
            _json_value(item)
        return
    raise ValueError('Only complete finite JSON values are accepted')


def canonical_input(value: dict) -> str:
    if type(value) is not dict:
        raise ValueError('Parsed business input must be an object')
    _json_value(value)
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':')
    )
