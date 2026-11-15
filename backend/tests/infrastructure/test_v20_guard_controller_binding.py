"""Current actual caller binding and common header checks; no action dispatch."""

import hashlib
import os
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.infrastructure import guard_controller_binding as bindings
from backend.app.infrastructure import guard_request_header as headers
from backend.app.infrastructure.guard_pipe_frames import GuardFrameError, GuardPipeFrames
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.windows_executable_pin import ExecutablePin
from backend.app.infrastructure.windows_pipe_peer import NamedPipePeerLease
from backend.tests.infrastructure.test_v20_windows_pipe_peer import connection, peer
from backend.tests.infrastructure.test_v20_windows_guard_pipe_io import channel
from backend.tests.requirements.test_v15_foundation import tmp_path

INSTALLATION = 'a' * 64
NONCE = 'original-guard-request-nonce-0001'


def packet(binding, **changed):
    return {
        'protocol_version': headers.PROTOCOL,
        'action': 'OBSERVE',
        'controller_ref': binding.controller_ref,
        'owner_epoch': binding.owner_epoch,
        'operation_id': 7,
        'step_no': 2,
        'nonce': NONCE,
        'binding_ref': None,
        'input': {'observed_action': 'CREATE_SUSPENDED'},
        **changed,
    }


def test_actual_backend_lock_and_self_identity_are_stable_until_original_epoch_changes(tmp_path):
    lock = ProcessLock(tmp_path / 'actual-backend.lock')
    with lock:
        binding = bindings.bind_backend_controller(lock, INSTALLATION)
        assert binding.controller.pid == os.getpid()
        assert binding.owner_epoch == lock.owner_epoch
        assert binding == bindings.bind_backend_controller(lock, INSTALLATION)
        assert len(binding.controller_ref) == 64
        binding.assert_backend(lock)
        header = headers.build_guard_request_header(
            binding,
            lock,
            action='PREPARE',
            operation_id=7,
            step_no=2,
            nonce=NONCE,
            binding_ref=None,
            action_input={'registered_ref': 'PRIVATE_MATERIAL'},
        )
        assert header.scope == binding.scope(7, 2, NONCE)
        assert 'PRIVATE_MATERIAL' not in repr(header)
    with pytest.raises(RuntimeError, match='current OS process lock'):
        binding.assert_backend(lock)
    with lock:
        replacement = bindings.bind_backend_controller(lock, INSTALLATION)
        assert replacement.controller == binding.controller
        assert replacement.owner_epoch != binding.owner_epoch
        assert replacement.controller_ref != binding.controller_ref
        with pytest.raises(bindings.GuardBindingError, match='CHANGED'):
            binding.assert_backend(lock)


@pytest.mark.parametrize('value', [None, {}, 1, 'pid'])
def test_backend_identity_cannot_be_supplied_as_serialized_lock_claim(value):
    with pytest.raises(TypeError):
        bindings.bind_backend_controller(value, INSTALLATION)


@pytest.mark.parametrize(
    'value',
    [
        None,
        '',
        'not-a-uuid',
        'AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA',
        '00000000-0000-1000-8000-000000000001',
    ],
)
def test_only_canonical_original_uuid_v4_epoch_is_accepted(value):
    with pytest.raises(bindings.GuardBindingError):
        bindings.owner_epoch(value)


def test_backend_and_guard_actual_pipe_peer_compute_same_binding_without_reading_each_others_lock(
    channel,
):
    io, client, server = channel
    backend = client('BACKEND_BINDING')
    backend.start()
    io.connect(timeout_ms=3000, cancelled=lambda: False)
    actual = backend.ready()
    reported = GuardPipeFrames(io).read(timeout_ms=3000, cancelled=lambda: False)
    raw = Path(actual.identity.image_path).read_bytes()
    with ExecutablePin(
        actual.identity.image_path,
        expected_byte_count=len(raw),
        expected_sha256=hashlib.sha256(raw).hexdigest(),
    ) as program:
        with NamedPipePeerLease(
            server._handle,
            peer_kind='CLIENT',
            expected=actual.identity,
            program=program,
            expected_user_sid=server.backend_sid,
        ) as original:
            binding = bindings.bind_guard_controller(
                original, reported['owner_epoch'], server.name.rsplit('.', 1)[1]
            )
            assert binding.controller_ref == reported['controller_ref']
            header = headers.parse_guard_request_header(packet(binding), binding, peer=original)
            assert header.scope.controller_ref == reported['controller_ref']
            assert header.owner_epoch == reported['owner_epoch']


def test_real_guard_side_peer_role_cannot_masquerade_as_backend_controller(connection):
    data = connection
    with peer(data) as original:
        if data.role == 'SERVER':
            with pytest.raises(bindings.GuardBindingError, match='AUTHENTICATED_BACKEND'):
                bindings.bind_guard_controller(original, str(uuid4()), INSTALLATION)
        else:
            epoch = str(uuid4())
            binding = bindings.bind_guard_controller(original, epoch, INSTALLATION)
            assert binding.controller == data.process.identity
            assert binding == bindings.bind_guard_controller(original, epoch, INSTALLATION)
            binding.assert_peer(original)


@pytest.mark.parametrize('connection', ['CLIENT'], indirect=True)
def test_common_header_freezes_input_and_keeps_original_scope_without_action_execution(connection):
    with peer(connection) as original:
        binding = bindings.bind_guard_controller(original, str(uuid4()), INSTALLATION)
        value = packet(binding)
        header = headers.parse_guard_request_header(value, binding, peer=original)
        value['input']['observed_action'] = 'RESUME'
        detached = header.input
        detached['observed_action'] = 'STOP'
        assert header.input == {'observed_action': 'CREATE_SUSPENDED'}
        assert header.wire == packet(binding)
        assert (
            header.scope.operation_id == 7
            and header.scope.step_no == 2
            and header.scope.nonce == NONCE
        )


@pytest.mark.parametrize('connection', ['CLIENT'], indirect=True)
@pytest.mark.parametrize(
    'changed',
    [
        {'protocol_version': 'other'},
        {'action': 'SHELL'},
        {'controller_ref': 'b' * 64},
        {'owner_epoch': str(uuid4())},
        {'operation_id': True},
        {'step_no': 0},
        {'nonce': 'short'},
        {'binding_ref': r'C:\arbitrary'},
        {'input': []},
        {'input': {'observed_action': 'OBSERVE'}},
        {'input': {'observed_action': 'SHELL'}},
        {'input': {'observed_action': 'CREATE_SUSPENDED', 'recovery': {}}},
    ],
)
def test_wrong_scope_unknown_action_and_implicit_observation_are_rejected(connection, changed):
    with peer(connection) as original:
        binding = bindings.bind_guard_controller(original, str(uuid4()), INSTALLATION)
        with pytest.raises((headers.GuardProtocolError, GuardFrameError)):
            headers.parse_guard_request_header(packet(binding, **changed), binding, peer=original)


@pytest.mark.parametrize('connection', ['CLIENT'], indirect=True)
def test_all_common_header_fields_required_and_no_client_task_or_identity_can_be_injected(
    connection,
):
    with peer(connection) as original:
        binding = bindings.bind_guard_controller(original, str(uuid4()), INSTALLATION)
        for field in headers.FIELDS:
            value = packet(binding)
            del value[field]
            with pytest.raises(headers.GuardProtocolError):
                headers.parse_guard_request_header(value, binding, peer=original)
        with pytest.raises(headers.GuardProtocolError):
            headers.parse_guard_request_header(packet(binding, task_id=1), binding, peer=original)


@pytest.mark.parametrize('connection', ['CLIENT'], indirect=True)
def test_resource_reference_presence_is_tied_to_original_action(connection):
    with peer(connection) as original:
        binding = bindings.bind_guard_controller(original, str(uuid4()), INSTALLATION)
        for action in headers.REQUIRED_BINDING:
            with pytest.raises(headers.GuardProtocolError):
                headers.parse_guard_request_header(
                    packet(binding, action=action, input={}), binding, peer=original
                )
            parsed = headers.parse_guard_request_header(
                packet(binding, action=action, binding_ref='r' * 32, input={}),
                binding,
                peer=original,
            )
            assert parsed.binding_ref == 'r' * 32
        with pytest.raises(headers.GuardProtocolError):
            headers.parse_guard_request_header(
                packet(binding, action='PREPARE', binding_ref='r' * 32), binding, peer=original
            )


@pytest.mark.parametrize('connection', ['CLIENT'], indirect=True)
def test_matching_request_digest_cannot_substitute_another_actual_peer(connection, tmp_path):
    with ProcessLock(tmp_path / 'different-source.lock') as lock:
        binding = bindings.bind_backend_controller(lock, INSTALLATION)
        with peer(connection) as actual:
            with pytest.raises(bindings.GuardBindingError, match='PEER_DIFFERS'):
                headers.parse_guard_request_header(packet(binding), binding, peer=actual)


@pytest.mark.parametrize('connection', ['CLIENT'], indirect=True)
@pytest.mark.parametrize('action', ['OBSERVE', 'STOP', 'RELEASE'])
def test_recovery_selects_old_scope_without_changing_authenticated_current_caller(
    connection, action
):
    with peer(connection) as original:
        current = bindings.bind_guard_controller(original, str(uuid4()), INSTALLATION)
        old = bindings.GuardControllerBinding(INSTALLATION, str(uuid4()), current.controller)
        recovery = {'controller_ref': old.controller_ref, 'owner_epoch': old.owner_epoch}
        action_input = {'recovery': recovery}
        if action == 'OBSERVE':
            action_input['observed_action'] = 'RESUME'
        value = packet(current, action=action, binding_ref='r' * 32, input=action_input)
        header = headers.parse_guard_request_header(value, current, peer=original)
        assert header.scope == current.scope(7, 2, NONCE)
        assert header.owner_epoch == current.owner_epoch
        assert header.target_scope == old.scope(7, 2, NONCE)
        assert header.recovery == headers.GuardRecoverySelector(**recovery)
        assert header.wire == value
        recovery['controller_ref'] = 'b' * 64
        detached = header.input
        detached['recovery']['owner_epoch'] = str(uuid4())
        assert header.target_scope == old.scope(7, 2, NONCE)
        assert header.input['recovery']['owner_epoch'] == old.owner_epoch
        # Header parsing has no registration/program/closure evidence and grants
        # no permission to use even an otherwise well-formed old selector.


@pytest.mark.parametrize('connection', ['CLIENT'], indirect=True)
@pytest.mark.parametrize('action', ['PREPARE', 'CREATE_SUSPENDED', 'RESUME', 'VERIFY_MODEL_SOURCE'])
def test_recovery_never_routes_execution_or_source_verification_under_old_identity(
    connection, action
):
    with peer(connection) as original:
        current = bindings.bind_guard_controller(original, str(uuid4()), INSTALLATION)
        value = packet(
            current,
            action=action,
            binding_ref=None if action == 'PREPARE' else 'r' * 32,
            input={'recovery': {'controller_ref': 'b' * 64, 'owner_epoch': str(uuid4())}},
        )
        with pytest.raises(headers.GuardProtocolError, match='RECOVERY_ACTION_FORBIDDEN'):
            headers.parse_guard_request_header(value, current, peer=original)


@pytest.mark.parametrize('connection', ['CLIENT'], indirect=True)
@pytest.mark.parametrize(
    'selector',
    [
        None,
        [],
        {},
        {'controller_ref': 'b' * 64},
        {'controller_ref': 'b' * 64, 'owner_epoch': 'old'},
        {'controller_ref': '../old', 'owner_epoch': '00000000-0000-4000-8000-000000000001'},
        {
            'controller_ref': 'b' * 64,
            'owner_epoch': '00000000-0000-4000-8000-000000000001',
            'pid': 7,
        },
    ],
)
def test_recovery_selector_cannot_carry_pid_paths_missing_fields_or_noncanonical_epoch(
    connection, selector
):
    with peer(connection) as original:
        current = bindings.bind_guard_controller(original, str(uuid4()), INSTALLATION)
        with pytest.raises(headers.GuardProtocolError):
            headers.parse_guard_request_header(
                packet(current, input={'observed_action': 'STOP', 'recovery': selector}),
                current,
                peer=original,
            )


@pytest.mark.parametrize('connection', ['CLIENT'], indirect=True)
def test_recovery_rejects_current_controller_and_new_action_input_under_old_scope(connection):
    with peer(connection) as original:
        current = bindings.bind_guard_controller(original, str(uuid4()), INSTALLATION)
        with pytest.raises(headers.GuardProtocolError, match='DISTINCT_OLD_CONTROLLER'):
            headers.parse_guard_request_header(
                packet(
                    current,
                    input={
                        'observed_action': 'STOP',
                        'recovery': {
                            'controller_ref': current.controller_ref,
                            'owner_epoch': current.owner_epoch,
                        },
                    },
                ),
                current,
                peer=original,
            )
        for action in headers.RECOVERY_ACTIONS:
            action_input = {
                'recovery': {'controller_ref': 'b' * 64, 'owner_epoch': str(uuid4())},
                'replacement_input': {'nonce': 'new'},
            }
            if action == 'OBSERVE':
                action_input['observed_action'] = 'STOP'
            with pytest.raises(headers.GuardProtocolError, match='RECOVERY_ACTION_INPUT'):
                headers.parse_guard_request_header(
                    packet(current, action=action, binding_ref='r' * 32, input=action_input),
                    current,
                    peer=original,
                )


def test_backend_recovery_packet_still_requires_current_original_lock_and_wire_identity(tmp_path):
    lock = ProcessLock(tmp_path / 'recovery-caller.lock')
    with lock:
        current = bindings.bind_backend_controller(lock, INSTALLATION)
        old = bindings.GuardControllerBinding(INSTALLATION, str(uuid4()), current.controller)
        header = headers.build_guard_request_header(
            current,
            lock,
            action='STOP',
            operation_id=7,
            step_no=2,
            nonce=NONCE,
            binding_ref=None,
            action_input={
                'recovery': {'controller_ref': old.controller_ref, 'owner_epoch': old.owner_epoch}
            },
        )
        assert header.wire['controller_ref'] == current.controller_ref
        assert header.wire['owner_epoch'] == current.owner_epoch
        assert header.target_scope == old.scope(7, 2, NONCE)
    with pytest.raises(RuntimeError, match='current OS process lock'):
        headers.build_guard_request_header(
            current,
            lock,
            action='STOP',
            operation_id=7,
            step_no=2,
            nonce=NONCE,
            binding_ref=None,
            action_input=header.input,
        )
