"""New kernel-only Guard pipe endpoint checks, without a service installation."""

from unittest.mock import patch
from uuid import uuid4

import pytest

from backend.app.infrastructure import windows_guard_pipe as module
from backend.app.infrastructure.windows_private_package import current_operator_sid


def reference():
    return uuid4().hex + uuid4().hex


@pytest.mark.parametrize(
    'value', [None, True, 'a', 'A' * 64, 'a' * 63 + '/', r'\\remote\pipe\service']
)
def test_only_registered_installation_reference_selects_local_namespace(value):
    with patch.object(module, '_api', side_effect=AssertionError('No kernel object')):
        with pytest.raises(module.GuardPipeError, match='INSTALLATION_REFERENCE_REQUIRED'):
            module.GuardPipeServer(value, backend_sid='S-1-0-0')


def test_new_original_endpoint_is_first_instance_protected_and_not_inherited():
    sid = current_operator_sid()
    original = reference()
    with module.GuardPipeServer(original, backend_sid=sid) as server:
        assert server.name == r'\\.\pipe\WALLE.RuntimeGuard.' + original
        server.verify()
        with server.endpoint() as handle:
            assert handle == server._handle
            with pytest.raises(module.GuardPipeError, match='IN_USE'):
                server.close()
        with pytest.raises(module.GuardPipeError, match='NEW_GUARD_PIPE_INSTANCE_REQUIRED'):
            module.GuardPipeServer(original, backend_sid=sid)
        server.verify()
    with pytest.raises(module.GuardPipeError, match='CLOSED'):
        server.verify()
    # Only this just-closed kernel endpoint is recreated; no other instance is replaced.
    with module.GuardPipeServer(original, backend_sid=sid):
        pass


def test_explicit_other_backend_ace_has_only_data_and_control_rights():
    # An unassigned fixture SID tests exact two-ACE shape, not cross-user access admission.
    sid = current_operator_sid()
    parts = sid.rsplit('-', 1)
    other = parts[0] + '-' + str((int(parts[1]) + 12345) % 0xFFFFFFFF)
    assert other != sid
    with module.GuardPipeServer(reference(), backend_sid=other) as server:
        server.verify()
        assert module.CLIENT_ACCESS & 0x4 == 0
        with pytest.raises(module.GuardPipeError, match='EXACT_DACL_REQUIRED'):
            module.verify_pipe_security(
                server._kernel, server._security, server._handle, server_sid=sid, backend_sid=sid
            )
        server.verify()


@pytest.mark.parametrize('value', [None, False, '', 'BA', 'S-not-a-sid', 'S-1-05-21-1-2-3-4'])
def test_noncanonical_or_invalid_backend_sid_never_creates_endpoint(value):
    with pytest.raises(module.GuardPipeError):
        module.GuardPipeServer(reference(), backend_sid=value)
