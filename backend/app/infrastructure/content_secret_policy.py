"""Pinned program secret checks; no regex supplied by clients or secret logging."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .content_paths import relative_content_path
from .git_object_graph import require_original_object
from .resources import ConfigInvalid

REFERENCE = 'CONTENT20-SECRETS-1'
RESOURCE_SHA256 = '9962434a0d9ef12497db9d3ee1984eec66f2321a5c6122ff85ad777b888d63a1'
RESOURCE = (
    Path(__file__).resolve().parents[2] / 'resources/code/secret-policies/content20-secrets-1.json'
)
CONTENT_VALUE = {'content_policy_version': 'CONTENT20-STORE-1', 'secret_policy_ref': REFERENCE}
CAPABILITIES = ['Q20-CONTENT', 'Q20-GIT', 'Q20-WINDOWS']


class SecretRestricted(ValueError):
    code = 'SOURCE_UNSUPPORTED'
    reason = 'SECRET_RESTRICTED'

    def __init__(self):
        super().__init__('SECRET_RESTRICTED')


@dataclass(frozen=True)
class SecretPolicy:
    reference: str
    sha256: str
    blocked_names: tuple[str, ...]
    blocked_prefixes: tuple[str, ...]
    blocked_suffixes: tuple[str, ...]
    markers: tuple[bytes, ...]

    def check_path(self, path):
        relative_content_path(path)
        folded = path.casefold()
        name = folded.rsplit('/', 1)[-1]
        if (
            name in self.blocked_names
            or any(name.startswith(prefix) for prefix in self.blocked_prefixes)
            or any(
                folded == suffix or folded.endswith('/' + suffix)
                for suffix in self.blocked_suffixes
            )
        ):
            raise SecretRestricted()

    def check_file(self, path, blob):
        self.check_path(path)
        original = require_original_object(blob, 'blob', max(1, blob.byte_count))
        self._check_bytes(original.raw)

    def check_bytes(self, path, raw):
        self.check_path(path)
        self._check_bytes(raw)

    def _check_bytes(self, raw):
        if type(raw) is not bytes:
            raise ValueError('Immutable source bytes are required')
        if any(marker in raw for marker in self.markers):
            raise SecretRestricted()


def load_secret_policy(reference):
    if type(reference) is not str or reference != REFERENCE:
        raise ConfigInvalid('Secret policy is not registered')
    try:
        with RESOURCE.open('rb') as stream:
            raw = stream.read(8193)
        if len(raw) > 8192 or hashlib.sha256(raw).hexdigest() != RESOURCE_SHA256:
            raise ConfigInvalid('Secret policy resource differs')
        from backend.app.shared.validation import strict_json_object

        data = strict_json_object(raw)
        return SecretPolicy(
            REFERENCE,
            RESOURCE_SHA256,
            tuple(data['blocked_names']),
            tuple(data['blocked_prefixes']),
            tuple(data['blocked_suffixes']),
            tuple(value.encode('ascii') for value in data['byte_markers']),
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ConfigInvalid('Secret policy cannot be verified') from error


def inspect_registered_fixed_tree(commit_oid, *, secret_policy_ref, **arguments):
    from .git_fixed_content import inspect_fixed_tree

    if 'check_file' in arguments or 'check_path' in arguments:
        raise ConfigInvalid('Caller cannot replace the registered secret policy')
    policy = load_secret_policy(secret_policy_ref)
    return inspect_fixed_tree(
        commit_oid, check_path=policy.check_path, check_file=policy.check_file, **arguments
    )
