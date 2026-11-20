"""Canonical JSON array hashes with constant-memory streaming, including empty arrays."""

import hashlib

from backend.app.shared.json_canonical import canonical_input


class ArrayDigest:
    def __init__(self):
        self._digest = hashlib.sha256(b'[')
        self.count = 0

    def append(self, value):
        if self.count:
            self._digest.update(b',')
        self._digest.update(canonical_input(value).encode('utf-8'))
        self.count += 1

    def hexdigest(self):
        result = self._digest.copy()
        result.update(b']')
        return result.hexdigest()


def measured(rows):
    result = ArrayDigest()
    for item in rows:
        result.append(item)
    return result.count, result.hexdigest()


def digest_rows(rows):
    return measured(rows)[1]
