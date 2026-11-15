"""Actual controller-derived private CHECK_DRIVER logon state and cleanup."""

from backend.app.infrastructure.windows_check_logon import CheckLogonSession
from backend.tests.infrastructure.test_v20_windows_lpac_profile import (
    controller,
    ordinary_controller,
    tmp_path,
    lpac_scope,
)
import pytest


def test_check_logon_retains_local_identity_and_owns_new_noninheritable_session(
    lpac_scope, monkeypatch
):
    directories, _, _ = lpac_scope
    original = directories._controller
    from backend.app.infrastructure import windows_check_logon

    read = windows_check_logon._security_state
    states = []

    def observed_state(*args):
        value = read(*args)
        states.append(value)
        if len(states) == 2:
            print(
                'CHECK_LOGON_STATE_DIFFERENCES',
                [
                    {'source_only': set(left) - set(right), 'derived_only': set(right) - set(left)}
                    for left, right in zip(states[0], states[1])
                ],
                flush=True,
            )
        return value

    monkeypatch.setattr(windows_check_logon, '_security_state', observed_state)
    session = CheckLogonSession(original)
    try:
        observed = session.verify()
        assert observed.user_sid == original.identity.user_sid
        assert observed.session_id == original.identity.session_id
        assert observed.authentication_id_hex != original.identity.authentication_id_hex
        with session.creation_handle() as handle:
            assert handle and handle != original._handle
        assert session.verify() == observed
        second = CheckLogonSession(original)
        try:
            assert second.verify().authentication_id_hex != observed.authentication_id_hex
        finally:
            second.close()
    finally:
        session.close()
        session.close()
    from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown

    with pytest.raises(LaunchOutcomeUnknown, match='CHECK_LOGON_SOURCE_CLOSED'):
        session.verify()


def test_check_logon_rejects_unowned_controller_before_any_api_call():
    from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown

    with pytest.raises(LaunchOutcomeUnknown, match='ORIGINAL_CHECK_LOGON_CONTROLLER_REQUIRED'):
        CheckLogonSession(object())

def test_check_logon_derives_from_backend_when_host_primary_privileges_differ(
    tmp_path, ordinary_controller
):
    from backend.tests.infrastructure.v20_check_logon_source_affinity import probe_source_affinity

    process, _ = ordinary_controller
    probe_source_affinity(tmp_path, process)
