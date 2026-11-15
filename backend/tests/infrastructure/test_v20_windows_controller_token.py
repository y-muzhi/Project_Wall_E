"""Real controller primary tokens; no process is launched with a copied token."""

from dataclasses import replace
import ctypes
from ctypes import wintypes
import os
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.app.infrastructure import windows_controller_token as token
from backend.app.infrastructure.windows_job import OwnedJob
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot
from backend.tests.requirements.test_v15_foundation import tmp_path


@pytest.fixture
def controller(tmp_path):
    job = OwnedJob(active_process_limit=16, job_memory_limit_bytes=512 * 1024 * 1024)
    root = None
    retained = {}
    try:
        code = """import os
import time
from pathlib import Path
with Path('controller-ready.tmp').open('x', encoding='ascii') as stream:
    stream.write(str(os.getpid()))
    stream.flush()
    os.fsync(stream.fileno())
os.replace('controller-ready.tmp', 'controller-ready')
time.sleep(60)
"""
        root = TestSuspendedRoot(job, tmp_path, code)
        root.resume()
        deadline = monotonic() + 10
        marker = tmp_path / 'controller-ready'
        while not marker.exists() and monotonic() < deadline:
            sleep(0.01)
        # This is the actual Python worker, never the .venv launcher PID.
        pid = int(marker.read_text(encoding='ascii'))
        held = ObservedProcess(pid)
        retained[pid] = held
        assert job.contains_process(held)
        members = job.observe_members()
        assert members.complete
        for member in members.process_ids:
            if member not in retained:
                observed = ObservedProcess(member)
                assert job.contains_process(observed)
                retained[member] = observed
        yield held, job
    finally:
        job.terminate_owned(1)
        # Assigned=0 can precede final process teardown. Wait on ORIGINAL handles
        # before NTFS temporary cleanup; no PID reopen or guessed sleep.
        for observed in retained.values():
            assert observed._kernel.WaitForSingleObject(observed._handle, 8000) == 0
            assert observed.observe().state == 'EXITED'
        if root is not None:
            assert job._kernel.WaitForSingleObject(root.info.process, 8000) == 0
        deadline = monotonic() + 8
        empty = False
        while monotonic() < deadline:
            members = job.observe_members()
            if members.complete and not members.process_ids:
                empty = True
                break
            sleep(0.01)
        for observed in retained.values():
            observed.close()
        if root is not None:
            root.close()
        job.close()
        assert empty, 'Owned controller fixture did not drain'


@pytest.fixture
def ordinary_controller(controller):
    source, job = controller
    if os.environ.get('WALLE_TEST_CONTROLLER_POSITIVE') == '1':
        assert not source.identity.is_appcontainer and not source.identity.is_elevated
    elif source.identity.is_appcontainer or source.identity.is_elevated:
        pytest.skip(
            'Positive primary-token fixture requires an approved ordinary non-AppContainer process'
        )
    return source, job


@pytest.mark.parametrize('value', [None, False, 1, 'pid', {}])
def test_no_serialized_pid_handle_or_user_claim_can_replace_a_held_process(value):
    with patch.object(token, '_api', side_effect=AssertionError('No token API')):
        with pytest.raises(token.ControllerTokenError, match='HELD_CONTROLLER_IDENTITY_REQUIRED'):
            token.ControllerPrimaryToken(value, expected=value)


def test_guard_current_process_is_never_a_fallback_creation_token():
    with ObservedProcess(os.getpid()) as current:
        with patch.object(token, '_api', side_effect=AssertionError('No own service token')):
            with pytest.raises(token.ControllerTokenError, match='GUARD_SELF_TOKEN_REJECTED'):
                token.ControllerPrimaryToken(current, expected=current.identity)


def test_actual_appcontainer_source_is_rejected_and_ordinary_source_remains_explicit(controller):
    source, _ = controller
    if source.identity.is_appcontainer:
        with patch.object(
            token, '_api', side_effect=AssertionError('No AppContainer token duplicate')
        ):
            with pytest.raises(token.ControllerTokenError, match='APPCONTAINER_REJECTED'):
                token.ControllerPrimaryToken(source, expected=source.identity)
    else:
        with token.ControllerPrimaryToken(source, expected=source.identity) as copy:
            assert copy.identity.user_sid == source.identity.user_sid


def test_false_cached_image_cannot_replace_actual_kernel_controller_identity(controller):
    source, _ = controller
    actual = source.identity
    false = replace(
        actual,
        image_path='not-the-original-image',
        is_appcontainer=False,
        appcontainer_sid=None,
        is_lpac=False,
        is_elevated=False,
    )
    source.identity = false
    try:
        with pytest.raises(
            token.ControllerTokenError, match='ORIGINAL_CONTROLLER_IDENTITY_DIFFERS'
        ):
            token.ControllerPrimaryToken(source, expected=false)
    finally:
        source.identity = actual


def test_authenticated_identity_cannot_be_changed_before_duplication(controller):
    source, _ = controller
    with patch.object(token, '_api', side_effect=AssertionError('No new token')):
        with pytest.raises(
            token.ControllerTokenError, match='ORIGINAL_CONTROLLER_IDENTITY_DIFFERS'
        ):
            token.ControllerPrimaryToken(
                source, expected=replace(source.identity, creation_time_hex='0' * 16)
            )


def test_real_duplicate_primary_token_binds_user_logon_session_and_noninherited_handle(
    ordinary_controller,
):
    source, _ = ordinary_controller
    with token.ControllerPrimaryToken(source, expected=source.identity) as copy:
        original = copy.identity
        assert original.user_sid == source.identity.user_sid
        assert len(original.authentication_id_hex) == len(original.token_id_hex) == 16
        with copy.creation_handle() as handle:
            assert token._read_token(copy._kernel, copy._security, handle) == original
            flags = wintypes.DWORD()
            assert copy._kernel.GetHandleInformation(handle, ctypes.byref(flags))
            assert not flags.value & 1
        assert copy._source_handle is None
        assert token.CREATION_TOKEN_ACCESS == 0xB
    assert source.observe().state == 'RUNNING'
    with pytest.raises(token.ControllerTokenError, match='CONTROLLER_TOKEN_CLOSED'):
        with copy.creation_handle():
            pytest.fail('No closed duplicate token')


def test_original_controller_exit_keeps_held_identity_and_never_reopens_a_pid(ordinary_controller):
    source, job = ordinary_controller
    with token.ControllerPrimaryToken(source, expected=source.identity) as copy:
        job.terminate_owned(25)
        deadline = monotonic() + 5
        while source.observe().state == 'RUNNING' and monotonic() < deadline:
            sleep(0.01)
        assert source.observe().state == 'EXITED'
        with patch.object(
            token, 'process_api', side_effect=AssertionError('No PID reopen or fallback')
        ):
            with pytest.raises(token.ControllerTokenError, match='ORIGINAL_CONTROLLER_EXITED'):
                with copy.creation_handle():
                    pytest.fail('Dead controller cannot create')


def test_inheritable_duplicate_is_rejected_without_silent_repair(ordinary_controller):
    source, _ = ordinary_controller
    with token.ControllerPrimaryToken(source, expected=source.identity) as copy:
        assert copy._kernel.SetHandleInformation(copy._handle, 1, 1)
        try:
            with pytest.raises(token.ControllerTokenError, match='INHERITANCE_UNVERIFIED'):
                with copy.creation_handle():
                    pytest.fail('No inherited token')
        finally:
            assert copy._kernel.SetHandleInformation(copy._handle, 1, 0)


def test_impersonating_guard_thread_must_revert_before_any_token_creation(ordinary_controller):
    source, _ = ordinary_controller
    _, security = token._api()
    security.ImpersonateSelf.argtypes = [ctypes.c_int]
    security.ImpersonateSelf.restype = wintypes.BOOL
    security.RevertToSelf.argtypes = []
    security.RevertToSelf.restype = wintypes.BOOL
    assert security.ImpersonateSelf(2)
    try:
        with pytest.raises(token.ControllerTokenError, match='IMPERSONATING_THREAD_REJECTED'):
            token.ControllerPrimaryToken(source, expected=source.identity)
    finally:
        assert security.RevertToSelf()


def test_failed_close_retains_exact_owned_handle_until_cleanup_succeeds(ordinary_controller):
    source, _ = ordinary_controller
    copy = token.ControllerPrimaryToken(source, expected=source.identity)
    kernel, handle = copy._kernel, copy._handle

    def refuse(_handle):
        ctypes.set_last_error(5)
        return False

    copy._kernel = SimpleNamespace(CloseHandle=refuse)
    try:
        with pytest.raises(token.ControllerTokenError) as caught:
            copy.close()
        assert caught.value.retained_owner is copy
        assert copy._handle == handle and caught.value.native_error == 5
    finally:
        copy._kernel = kernel
        copy.close()
    assert copy._handle is None and source.observe().state == 'RUNNING'
