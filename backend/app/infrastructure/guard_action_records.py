"""Bounded original Guard mutation facts, separate from current caller authority.

No decoder/hash here authorizes Native execution. Callers first validate the
registered action input and hold current program/owner or narrow-recovery gates.
"""

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from uuid import UUID

from backend.app.shared.validation import strict_json_object

from .guard_controller_binding import owner_epoch
from .guard_pipe_frames import decode_guard_payload, encode_guard_frame
from .guard_request_header import GuardRequestHeader
from .runtime_launch_journal import (
    LaunchOutcomeUnknown,
    LaunchScope,
    _bytes,
    _hex,
    _resource,
    decode_launch_scope,
)

MUTATIONS = frozenset(('PREPARE', 'CREATE_SUSPENDED', 'RESUME', 'STOP', 'RELEASE'))
MAX_ACTION_BYTES = 65536
MAX_RESULT_BYTES = 16384


class GuardActionError(LaunchOutcomeUnknown):
    pass


def mutation_action(value):
    if type(value) is not str or value not in MUTATIONS:
        raise GuardActionError('REGISTERED_GUARD_MUTATION_REQUIRED')
    return value


def mutation_input_sha256(request):
    if type(request) is not GuardRequestHeader:
        raise TypeError('Original parsed Guard request required')
    mutation_action(request.action)
    data = request.input
    if request.recovery is not None:
        if request.action not in ('STOP', 'RELEASE') or data.pop('recovery', None) != asdict(
            request.recovery
        ):
            raise GuardActionError('ORIGINAL_MUTATION_RECOVERY_SELECTOR_DIFFERS')
    elif 'recovery' in data:
        raise GuardActionError('ORIGINAL_MUTATION_RECOVERY_SELECTOR_DIFFERS')
    epoch = request.owner_epoch if request.recovery is None else request.recovery.owner_epoch
    owner_epoch(epoch)
    return hashlib.sha256(
        _bytes(
            {
                'protocol_version': request.protocol,
                'action': request.action,
                'scope': asdict(request.target_scope),
                'owner_epoch': epoch,
                'binding_ref': request.binding_ref,
                'input': data,
            }
        )
    ).hexdigest()


def action_result_json(value):
    raw = encode_guard_frame(value)[4:]
    if len(raw) > MAX_RESULT_BYTES:
        raise GuardActionError('GUARD_ACTION_RESULT_CAPACITY_EXHAUSTED')
    return raw.decode('utf-8')


def _time(value):
    if (
        type(value) is not str
        or re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z', value)
        is None
    ):
        raise GuardActionError('GUARD_ACTION_TIME_INVALID')
    try:
        datetime.fromisoformat(value)
    except ValueError as error:
        raise GuardActionError('GUARD_ACTION_TIME_INVALID') from error


def _nonce(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{32}', value) is None:
        raise GuardActionError('GUARD_ACTION_ALLOCATION_NONCE_INVALID')
    parsed = UUID(hex=value)
    if parsed.version != 4 or parsed.hex != value:
        raise GuardActionError('GUARD_ACTION_ALLOCATION_NONCE_INVALID')


@dataclass(frozen=True)
class GuardActionRecord:
    schema_version: int
    scope: LaunchScope
    owner_epoch: str
    action: str
    input_sha256: str
    binding_ref: str | None
    allocated_binding_ref: str | None
    directory_nonce: str | None
    requested_by_controller_ref: str
    requested_by_owner_epoch: str
    phase: str
    result_json: str | None = field(repr=False)
    revision: int
    created_at: str
    updated_at: str

    @property
    def result(self):
        return (
            None
            if self.result_json is None
            else decode_guard_payload(self.result_json.encode('utf-8'))
        )


@dataclass(frozen=True)
class GuardActionStart:
    record: GuardActionRecord
    first_accepted: bool


def decode_action_record(raw, scope, action):
    mutation_action(action)
    if (
        not isinstance(scope, LaunchScope)
        or type(raw) is not bytes
        or not 1 <= len(raw) <= MAX_ACTION_BYTES
    ):
        raise GuardActionError('ORIGINAL_GUARD_ACTION_RECORD_REQUIRED')
    value = strict_json_object(raw)
    if set(value) != set(GuardActionRecord.__dataclass_fields__):
        raise GuardActionError('GUARD_ACTION_FIELDS_DIFFER')
    actual_scope = decode_launch_scope(value['scope'])
    if actual_scope != scope or value['action'] != action:
        raise GuardActionError('ORIGINAL_GUARD_ACTION_DOMAIN_DIFFERS')
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise GuardActionError('GUARD_ACTION_SCHEMA_INVALID')
    owner_epoch(value['owner_epoch'])
    owner_epoch(value['requested_by_owner_epoch'])
    _hex(value['requested_by_controller_ref'])
    _hex(value['input_sha256'])
    if value['binding_ref'] is not None:
        _resource(value['binding_ref'])
    if action == 'PREPARE':
        if value['binding_ref'] is not None:
            raise GuardActionError('PREPARE_CANNOT_REBIND_RESOURCE')
        _nonce(value['allocated_binding_ref'])
        _nonce(value['directory_nonce'])
    elif value['allocated_binding_ref'] is not None or value['directory_nonce'] is not None:
        raise GuardActionError('ONLY_PREPARE_ALLOCATES_REFERENCES')
    elif action in ('CREATE_SUSPENDED', 'RESUME', 'RELEASE') and value['binding_ref'] is None:
        raise GuardActionError('ORIGINAL_GUARD_ACTION_BINDING_REQUIRED')
    if value['phase'] == 'MAY_HAVE_BEEN_SENT':
        if (
            value['result_json'] is not None
            or type(value['revision']) is not int
            or value['revision'] != 1
        ):
            raise GuardActionError('GUARD_ACTION_PENDING_STATE_INVALID')
        if value['created_at'] != value['updated_at']:
            raise GuardActionError('GUARD_ACTION_PENDING_TIME_DIFFERS')
    elif value['phase'] == 'ACKNOWLEDGED':
        if (
            type(value['result_json']) is not str
            or type(value['revision']) is not int
            or value['revision'] != 2
        ):
            raise GuardActionError('GUARD_ACTION_ACK_STATE_INVALID')
        decoded = decode_guard_payload(value['result_json'].encode('utf-8'))
        if action_result_json(decoded) != value['result_json']:
            raise GuardActionError('GUARD_ACTION_RESULT_NOT_CANONICAL')
        expected = value['allocated_binding_ref'] if action == 'PREPARE' else value['binding_ref']
        if expected is not None and decoded.get('binding_ref') != expected:
            raise GuardActionError('GUARD_ACTION_RESULT_BINDING_DIFFERS')
    else:
        raise GuardActionError('GUARD_ACTION_PHASE_INVALID')
    _time(value['created_at'])
    _time(value['updated_at'])
    if value['updated_at'] < value['created_at']:
        raise GuardActionError('GUARD_ACTION_CHRONOLOGY_INVALID')
    record = GuardActionRecord(**{**value, 'scope': actual_scope})
    if _bytes(asdict(record)) != raw:
        raise GuardActionError('GUARD_ACTION_RECORD_NOT_CANONICAL')
    return record
