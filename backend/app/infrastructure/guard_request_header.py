"""Strict current-caller Guard header and optional old-scope selector.

The parsed input remains unvalidated action data. A registered action decoder,
original resource owners and Journal/Registry admission are still required.
"""

import re
from dataclasses import dataclass, field, replace

from .guard_controller_binding import GuardBindingError, GuardControllerBinding, owner_epoch
from .guard_pipe_frames import decode_guard_payload, encode_guard_frame
from .runtime_launch_journal import LaunchFenceError, LaunchScope, TestingLaunchScope

PROTOCOL = 'WIN20-ISOLATION-1'
TESTING_CHECK_PROTOCOL = 'WIN20-TESTING-CHECK-1'
ACTIONS = (
    'PREPARE',
    'CREATE_SUSPENDED',
    'RESUME',
    'OBSERVE',
    'STOP',
    'RELEASE',
    'VERIFY_MODEL_SOURCE',
)
FIELDS = frozenset(
    (
        'protocol_version',
        'action',
        'controller_ref',
        'owner_epoch',
        'operation_id',
        'step_no',
        'nonce',
        'binding_ref',
        'input',
    )
)
TESTING_FIELDS = FIELDS | {'owner_kind', 'owner_id', 'control_generation'}
REQUIRED_BINDING = frozenset(('CREATE_SUSPENDED', 'RESUME', 'RELEASE', 'VERIFY_MODEL_SOURCE'))


class GuardProtocolError(RuntimeError):
    pass


RECOVERY_ACTIONS = frozenset(('OBSERVE', 'STOP', 'RELEASE'))


@dataclass(frozen=True)
class GuardRecoverySelector:
    """Routing facts only; no permission, old-resource ownership or exit proof."""

    controller_ref: str
    owner_epoch: str

    def __post_init__(self):
        try:
            LaunchScope(self.controller_ref, 1, 1, 'recovery-selector-validation')
            owner_epoch(self.owner_epoch)
        except (GuardBindingError, LaunchFenceError) as error:
            raise GuardProtocolError('ORIGINAL_RECOVERY_SELECTOR_INVALID') from error


@dataclass(frozen=True)
class GuardRequestHeader:
    action: str
    owner_epoch: str
    scope: LaunchScope
    binding_ref: str | None
    unvalidated_input_json: str = field(repr=False)
    recovery: GuardRecoverySelector | None = None

    @property
    def target_scope(self):
        if self.recovery is None:
            return self.scope
        return replace(self.scope, controller_ref=self.recovery.controller_ref)

    @property
    def protocol(self):
        return TESTING_CHECK_PROTOCOL if type(self.scope) is TestingLaunchScope else PROTOCOL

    @property
    def input(self):
        return decode_guard_payload(self.unvalidated_input_json.encode('utf-8'))

    @property
    def wire(self):
        value = {
            'protocol_version': self.protocol,
            'action': self.action,
            'controller_ref': self.scope.controller_ref,
            'owner_epoch': self.owner_epoch,
            'operation_id': self.scope.operation_id,
            'step_no': self.scope.step_no,
            'nonce': self.scope.nonce,
            'binding_ref': self.binding_ref,
            'input': self.input,
        }
        if self.protocol == TESTING_CHECK_PROTOCOL:
            value.update(
                owner_kind=self.scope.owner_kind,
                owner_id=self.scope.owner_id,
                control_generation=self.scope.control_generation,
            )
        return value


def _parse(value, binding):
    if type(binding) is not GuardControllerBinding:
        raise TypeError('Original controller binding required')
    if type(value) is not dict:
        raise GuardProtocolError('ORIGINAL_GUARD_REQUEST_FIELDS_DIFFER')
    testing = value.get('protocol_version') == TESTING_CHECK_PROTOCOL
    if set(value) != (TESTING_FIELDS if testing else FIELDS):
        raise GuardProtocolError('ORIGINAL_GUARD_REQUEST_FIELDS_DIFFER')
    # Capacity, safe exact JSON facts and a detached immutable snapshot first.
    value = decode_guard_payload(encode_guard_frame(value)[4:])
    if value['protocol_version'] not in (PROTOCOL, TESTING_CHECK_PROTOCOL) or (
        value['action'] not in ACTIONS or (testing and value['action'] == 'VERIFY_MODEL_SOURCE')
    ):
        raise GuardProtocolError('REGISTERED_GUARD_PROTOCOL_ACTION_REQUIRED')
    try:
        if (
            owner_epoch(value['owner_epoch']) != binding.owner_epoch
            or value['controller_ref'] != binding.controller_ref
        ):
            raise GuardProtocolError('ORIGINAL_GUARD_CONTROLLER_BINDING_DIFFERS')
        scope = binding.scope(value['operation_id'], value['step_no'], value['nonce'])
        if testing:
            scope = TestingLaunchScope(
                scope.controller_ref,
                scope.operation_id,
                scope.step_no,
                scope.nonce,
                value['owner_id'],
                value['control_generation'],
                value['owner_kind'],
            )
    except (GuardBindingError, LaunchFenceError) as error:
        raise GuardProtocolError('ORIGINAL_GUARD_SCOPE_INVALID') from error
    resource = value['binding_ref']
    if resource is not None and (
        type(resource) is not str or re.fullmatch('[a-zA-Z0-9_-]{16,128}', resource) is None
    ):
        raise GuardProtocolError('ORIGINAL_GUARD_RESOURCE_REFERENCE_INVALID')
    action = value['action']
    if (action == 'PREPARE' and resource is not None) or (
        action in REQUIRED_BINDING and resource is None
    ):
        raise GuardProtocolError('ORIGINAL_GUARD_RESOURCE_REFERENCE_REQUIRED')
    unvalidated = decode_guard_payload(encode_guard_frame(value['input'])[4:])
    recovery = None
    if 'recovery' in unvalidated:
        if action not in RECOVERY_ACTIONS:
            raise GuardProtocolError('RECOVERY_ACTION_FORBIDDEN')
        selector = unvalidated['recovery']
        if type(selector) is not dict or set(selector) != {'controller_ref', 'owner_epoch'}:
            raise GuardProtocolError('ORIGINAL_RECOVERY_SELECTOR_FIELDS_REQUIRED')
        recovery = GuardRecoverySelector(**selector)
        if recovery.controller_ref == binding.controller_ref:
            raise GuardProtocolError('DISTINCT_OLD_CONTROLLER_REQUIRED')
        required = {'recovery', 'observed_action'} if action == 'OBSERVE' else {'recovery'}
        if set(unvalidated) != required:
            raise GuardProtocolError('ORIGINAL_RECOVERY_ACTION_INPUT_REQUIRED')
    observation_fields = (
        {'observed_action'} if recovery is None else {'observed_action', 'recovery'}
    )
    if action == 'OBSERVE' and (
        set(unvalidated) != observation_fields
        or unvalidated['observed_action'] not in ACTIONS
        or unvalidated['observed_action'] == 'OBSERVE'
    ):
        raise GuardProtocolError('ORIGINAL_OBSERVED_GUARD_ACTION_REQUIRED')
    return GuardRequestHeader(
        action,
        binding.owner_epoch,
        scope,
        resource,
        encode_guard_frame(unvalidated)[4:].decode('utf-8'),
        recovery,
    )


def parse_guard_request_header(value, binding, *, peer):
    """Use one existing connection binding and reverify its actual original peer."""
    if type(binding) is not GuardControllerBinding:
        raise TypeError('Original controller binding required')
    binding.assert_peer(peer)
    return _parse(value, binding)


def build_guard_request_header(
    binding,
    process_lock,
    *,
    action,
    operation_id,
    step_no,
    nonce,
    binding_ref,
    action_input,
    testing_scope=None,
):
    """Freeze a request only while the real backend still owns its original lock."""
    if type(binding) is not GuardControllerBinding:
        raise TypeError('Original controller binding required')
    binding.assert_backend(process_lock)
    value = {
        'protocol_version': PROTOCOL,
        'action': action,
        'controller_ref': binding.controller_ref,
        'owner_epoch': binding.owner_epoch,
        'operation_id': operation_id,
        'step_no': step_no,
        'nonce': nonce,
        'binding_ref': binding_ref,
        'input': action_input,
    }
    if testing_scope is not None:
        if type(testing_scope) is not TestingLaunchScope or (
            testing_scope.operation_id,
            testing_scope.step_no,
            testing_scope.nonce,
        ) != (operation_id, step_no, nonce):
            raise GuardProtocolError('ORIGINAL_TESTING_GUARD_SCOPE_DIFFERS')
        value.update(
            protocol_version=TESTING_CHECK_PROTOCOL,
            owner_kind=testing_scope.owner_kind,
            owner_id=testing_scope.owner_id,
            control_generation=testing_scope.control_generation,
        )
    request = _parse(value, binding)
    if testing_scope is not None and request.target_scope != testing_scope:
        raise GuardProtocolError('ORIGINAL_TESTING_GUARD_SCOPE_DIFFERS')
    return request
