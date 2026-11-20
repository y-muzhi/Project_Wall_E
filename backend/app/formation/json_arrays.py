"""Canonical JSON arrays for relation storage; business root hashing remains object-only."""

import json

from backend.app.shared.json_canonical import canonical_input


def json_array(value):
    if type(value) is not list:
        raise ValueError('A relation source collection must be an array')
    canonical_input({'items': value})
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':')
    )
