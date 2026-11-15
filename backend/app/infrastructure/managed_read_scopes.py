"""Pinned managed read-root meanings, never client paths or runtime admission."""

import hashlib
from pathlib import Path

from backend.app.shared.validation import strict_json_object

from .resources import ConfigInvalid

WORKSPACE = 'READ20-WORKSPACE-1'
BASIS = 'READ20-BASIS-1'
REFERENCES = (WORKSPACE, BASIS)
CAPABILITIES = ['Q20-CONFIG', 'Q20-WINDOWS']
RESOURCE_SHA256 = '893ed2a7a4276d843df97041e201f6fa5e64c3841eaea877e927b0baa34bd097'
RESOURCE = Path(__file__).resolve().parents[2] / 'resources/code/managed-scopes/managed-read-1.json'


def load_managed_read_scopes():
    try:
        raw = RESOURCE.read_bytes()
        if hashlib.sha256(raw).hexdigest() != RESOURCE_SHA256:
            raise ConfigInvalid('Managed read-scope source digest differs')
        value = strict_json_object(raw)
        expected = {
            'protocol_version': 'READ20-MANAGED-1',
            'source_commit': '810c0eba1a7348036f8bdf61e6632d0c36c6876c',
            'scopes': [
                {'scope_ref': WORKSPACE, 'binding': 'TASK_WORKSPACE', 'label': '任务工作区'},
                {'scope_ref': BASIS, 'binding': 'TASK_BASIS', 'label': '任务固定依据'},
            ],
        }
        if value != expected:
            raise ConfigInvalid('Managed read-scope semantics differ')
        return value
    except ConfigInvalid:
        raise
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise ConfigInvalid('Managed read-scope source unavailable') from error


def scope_options():
    return [
        {
            'option_id': 'scope:' + row['scope_ref'],
            'kind': 'SCOPE',
            'label': row['label'],
            'ready': False,
            'unresolved_capability_codes': list(CAPABILITIES),
            'value': {'scope_kind': 'READ_ROOT', 'scope_ref': row['scope_ref']},
        }
        for row in load_managed_read_scopes()['scopes']
    ]
