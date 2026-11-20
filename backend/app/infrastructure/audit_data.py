"""Private audit sanitization/capacity. Never a public response projection."""

import base64
import json
from urllib.parse import quote

from backend.app.shared.json_canonical import canonical_input

MAX_AUDIT_BYTES = 4 * 1024 * 1024
OMITTED_KEYS = frozenset(
    {
        'authorization',
        'proxy-authorization',
        'api_key',
        'api-key',
        'apikey',
        'x-api-key',
        'access_token',
        'secret_key',
        'reasoning',
        'reasoning_content',
        'encrypted_content',
    }
)


class AuditCapacityExceeded(ValueError):
    pass


def sanitize_audit(value, *, credentials=()):
    secrets = set()
    for credential in credentials:
        if type(credential) is not str or not credential:
            raise ValueError('Invalid redaction credential')
        secrets.update(
            (
                credential,
                quote(credential, safe=''),
                base64.b64encode(credential.encode('utf-8')).decode('ascii'),
            )
        )

    def visit(node):
        if type(node) is dict:
            return {
                key: visit(child)
                for key, child in node.items()
                if type(key) is str
                and key.lower() not in OMITTED_KEYS
                and not any(secret in key for secret in secrets)
            }
        if type(node) is list:
            return [visit(child) for child in node]
        if type(node) is str:
            for secret in sorted(secrets, key=len, reverse=True):
                node = node.replace(secret, '[REDACTED_CREDENTIAL]')
        return node

    # Reject non-JSON data/duplicate semantics instead of silently dropping it.
    canonical_input(value)
    sanitized = visit(value)
    encoded = canonical_input(sanitized)
    if len(encoded.encode('utf-8')) > MAX_AUDIT_BYTES:
        raise AuditCapacityExceeded('Audit item exceeds its approved capacity')
    return json.loads(encoded)


def audit_json(value, *, credentials=()):
    if type(value) is not dict:
        raise ValueError('Audit snapshots must be complete objects')
    return canonical_input(sanitize_audit(value, credentials=credentials))


def retain_openai_request_configuration(clean, original, profile):
    # 'reasoning' in a request is a fixed effort configuration, not private
    # model reasoning. Preserve only this typed path; the global scrubber still
    # removes arbitrary reasoning_content/encrypted_content everywhere.
    if profile.provider != 'openai':
        return clean
    request = original.get('request')
    if request is not None:
        expected = profile.snapshot['reasoning']
        if type(request) is not dict or request.get('reasoning') != expected:
            raise ValueError('OpenAI request configuration differs from its profile')
        approved = sanitize_audit({'configuration': expected}, credentials=(profile.api_key,))[
            'configuration'
        ]
        clean['request']['reasoning'] = approved
        if clean['request'] != request:
            raise ValueError('Exact OpenAI request cannot be safely retained')
    if 'profile' in original:
        if original['profile'] != profile.snapshot:
            raise ValueError('OpenAI profile differs from its fixed identity')
        clean['profile']['reasoning'] = profile.snapshot['reasoning']
    return clean


def counting_audit_json(value, profile):
    clean = sanitize_audit(value, credentials=(profile.api_key,))
    clean = retain_openai_request_configuration(clean, value, profile)
    encoded = canonical_input(clean)
    if len(encoded.encode('utf-8')) > MAX_AUDIT_BYTES:
        raise AuditCapacityExceeded('Counting audit exceeds capacity')
    return encoded


def collaboration_audit_json(value, resources, *, credentials=()):
    """Preserve only the Schema-validated private program grant at its exact
    ContextBasis path. HTTP authorization and arbitrary credentials still use
    the normal scrubber. If scrubbing changes the replayable request/basis,
    stop before I/O instead of saving misleading request evidence.
    """
    from .resources import ConfigInvalid

    basis = resources.validate('ContextBasis', value['context_basis'])
    grant = basis['canonical']['authorization']
    clean = sanitize_audit(value, credentials=credentials)
    if value.get('profile', {}).get('provider') == 'openai':
        from .model_profile import ModelProfile

        profile = ModelProfile.from_snapshot(
            value['profile'], api_key=credentials[0] if credentials else 'private-audit-validation'
        )
        clean = retain_openai_request_configuration(clean, value, profile)
    clean['context_basis']['canonical']['authorization'] = sanitize_audit(
        {'grant': grant}, credentials=credentials
    )['grant']
    if (
        canonical_input(clean['context_basis']) != canonical_input(value['context_basis'])
        or clean['request'] != value['request']
    ):
        raise ConfigInvalid('Exact collaboration request cannot be safely retained')
    encoded = canonical_input(clean)
    if len(encoded.encode('utf-8')) > MAX_AUDIT_BYTES:
        raise AuditCapacityExceeded('Collaboration audit exceeds its approved capacity')
    return encoded
