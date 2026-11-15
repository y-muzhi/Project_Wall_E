"""Immutable AuthorizationScope input; approval never implies binding or execution."""

import json
from dataclasses import dataclass, field

from backend.app.infrastructure.idempotency import canonical_input
from backend.app.shared.validation import reject, strict_boolean, strict_integer

from .check_set_content import _record, _references
from .check_set_versions import _find
from .execution_profile_content import LIMITS

FIELDS = (
    'read_roots',
    'write_workspace_only',
    'allowed_command_ids',
    'network_targets',
    'model_profile_refs',
    'allow_local_delivery',
    'limits',
)
STATUSES = (
    'APPROVED_UNBOUND',
    'BOUND_PENDING_APPLY',
    'EFFECTIVE',
    'APPLY_FAILED',
    'APPLY_UNKNOWN',
    'RETIRED',
)


@dataclass(frozen=True)
class AuthorizationScope:
    _encoded: bytes = field(repr=False)

    def value(self):
        return json.loads(self._encoded)


def parse_authorization_scope(value, *, max_input_bytes):
    strict_integer(max_input_bytes, 'max_input_bytes')
    source = _record(value, 'scope', FIELDS)
    try:
        encoded = canonical_input(source).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, RecursionError):
        reject('scope', 'INVALID_FORMAT', '授权必须是有效有界JSON')
    if len(encoded) > max_input_bytes:
        reject('scope', 'TOO_LONG', '授权范围超过容量')
    result = {
        key: _references(source[key], 'scope.' + key, max_input_bytes)
        for key in ('read_roots', 'allowed_command_ids', 'network_targets', 'model_profile_refs')
    }
    workspace_only = strict_boolean(source['write_workspace_only'], 'scope.write_workspace_only')
    if not workspace_only:
        reject('scope.write_workspace_only', 'INVALID_FORMAT', '产品代码只能写本任务工作区')
    result['write_workspace_only'] = workspace_only
    result['allow_local_delivery'] = strict_boolean(
        source['allow_local_delivery'], 'scope.allow_local_delivery'
    )
    limits = _record(source['limits'], 'scope.limits', LIMITS)
    result['limits'] = {key: strict_integer(limits[key], 'scope.limits.' + key) for key in LIMITS}
    if result['limits']['max_delivery_window_seconds'] > 300:
        reject('scope.limits.max_delivery_window_seconds', 'OUT_OF_RANGE', '交付窗口不能超过300秒')
    return AuthorizationScope(canonical_input(result).encode('utf-8'))


def profile_scope_error(scope, profile):
    """No fallback, command substitution, budget widening or implicit delivery."""
    profiles = {
        profile['models']['primary_profile_ref'],
        *profile['models']['auxiliary_profile_refs'],
    }
    if not set(scope['model_profile_refs']).issubset(profiles):
        return 'scope.model_profile_refs'
    if not set(scope['allowed_command_ids']).issubset(
        {row['command_id'] for row in profile['commands']}
    ):
        return 'scope.allowed_command_ids'
    if any(scope['limits'][key] > profile['limits'][key] for key in LIMITS):
        return 'scope.limits'
    if scope['allow_local_delivery'] and profile['delivery'] is None:
        return 'scope.allow_local_delivery'
    return None


def resource_scope_error(scope, snapshot):
    for name, kind in (('read_roots', 'READ_ROOT'), ('network_targets', 'NETWORK_TARGET')):
        for ref in scope[name]:
            resource = _find(snapshot, 'SCOPE', 'scope_ref', ref)
            if resource is None or resource['value']['scope_kind'] != kind:
                return 'scope.' + name
    return None
