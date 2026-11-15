"""Real read-only process handles and owned short-lived children, no Guard install."""

from dataclasses import replace
import os
import ctypes
from ctypes import wintypes
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

from backend.app.infrastructure import windows_process as native
from backend.tests.requirements.test_v15_foundation import tmp_path

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize('pid', [None, True, False, 0, -1, 1.5, '12', 0x100000000])
def test_invalid_pid_is_rejected_before_any_native_lookup(pid):
    with patch.object(native, '_api', side_effect=AssertionError('No lookup')):
        with pytest.raises(native.ProcessObservationError, match='PROCESS_ID_INVALID'):
            native.ObservedProcess(pid)


def test_current_real_handle_binds_creation_image_token_and_is_not_inherited_or_write_capable():
    with native.ObservedProcess(os.getpid()) as held:
        identity = held.identity
        assert identity.pid == os.getpid()
        assert len(identity.creation_time_hex) == 16 and int(identity.creation_time_hex, 16) > 0
        assert identity.image_path.lower().endswith('python.exe')
        assert identity.user_sid.startswith('S-1-')
        assert (identity.appcontainer_sid is not None) == identity.is_appcontainer
        assert identity.is_lpac in (True, False, None)
        assert identity.is_lpac is not True or identity.is_appcontainer
        flags = wintypes.DWORD()
        held._kernel.GetHandleInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        held._kernel.GetHandleInformation.restype = wintypes.BOOL
        assert held._kernel.GetHandleInformation(held._handle, ctypes.byref(flags))
        assert flags.value & 1 == 0
        observed = held.observe()
        assert (
            observed.identity == identity
            and observed.state == 'RUNNING'
            and observed.exit_code is None
        )
    with pytest.raises(native.ProcessObservationError, match='PROCESS_HANDLE_CLOSED'):
        held.observe()
    with pytest.raises(native.ProcessObservationError, match='PROCESS_HANDLE_CLOSED'):
        held.__enter__()


def test_reopen_requires_same_actual_creation_token_image_not_just_same_pid():
    with native.ObservedProcess(os.getpid()) as held:
        identity = held.identity
        with native.ObservedProcess(os.getpid(), expected=identity) as again:
            assert again.identity == identity
        for mismatch in (
            replace(identity, creation_time_hex='0' * 16),
            replace(identity, image_path='different executable'),
            replace(identity, user_sid='S-1-0-0'),
        ):
            with pytest.raises(
                native.ProcessObservationError, match='EXPECTED_PROCESS_IDENTITY_DIFFERS'
            ):
                native.ObservedProcess(os.getpid(), expected=mismatch)


def test_held_owned_child_reports_running_then_actual_signaled_exit_even_with_code_259(tmp_path):
    process = subprocess.Popen(
        [
            str(ROOT / '.venv/Scripts/python.exe'),
            '-u',
            '-B',
            '-c',
            'import sys; sys.stdin.buffer.read(1); raise SystemExit(259)',
        ],
        cwd=tmp_path,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with native.ObservedProcess(process.pid) as held:
            original = held.identity
            assert held.observe().state == 'RUNNING'
            process.communicate(input=b'x', timeout=15)
            assert process.returncode == 259
            result = held.observe()
            assert result.identity == original
            assert result.state == 'EXITED' and result.exit_code == 259
            # No old-PID reopen, path guess or STILL_ACTIVE loop after exit.
            with patch.object(native, '_api', side_effect=AssertionError('Never reopen')):
                assert held.observe().state == 'EXITED'
    finally:
        if process.poll() is None:
            process.terminate()
        process.communicate(timeout=15)


def test_unsupported_lpac_query_is_unknown_not_a_positive_or_negative_permission_fact():
    class Unsupported:
        def GetTokenInformation(self, token, kind, output, capacity, size):
            ctypes.set_last_error(87)
            return False

    assert native._token_flag(Unsupported(), None, 46, allow_unsupported=True) is None
    with pytest.raises(
        native.ProcessObservationError, match='PROCESS_TOKEN_INFORMATION_UNAVAILABLE'
    ):
        native._token_flag(Unsupported(), None, 29)
    with pytest.raises(
        native.ProcessObservationError, match='PROCESS_TOKEN_INFORMATION_UNAVAILABLE'
    ):
        native._token_flag(Unsupported(), None, 46)


def test_original_process_duplicate_survives_source_close_without_reopening_pid():
    with native.ObservedProcess(os.getpid()) as original:
        with patch.object(native, '_api', side_effect=AssertionError('No PID reopen')):
            copied = original.duplicate()
        assert copied._handle != original._handle
        assert copied.identity == original.identity
        flags = wintypes.DWORD()
        assert copied._kernel.GetHandleInformation(copied._handle, ctypes.byref(flags))
        assert flags.value & 1 == 0
    try:
        assert copied.observe().state == 'RUNNING'
        with pytest.raises(native.ProcessObservationError, match='CLOSED'):
            original.duplicate()
    finally:
        copied.close()


def test_failed_duplicate_is_read_only_and_keeps_original_usable():
    with native.ObservedProcess(os.getpid()) as original:
        with patch.object(original._kernel, 'DuplicateHandle', return_value=False) as duplicate:
            with pytest.raises(native.ProcessObservationError, match='DUPLICATE_FAILED'):
                original.duplicate()
        call = duplicate.call_args.args
        assert call[4] == 0 and call[5] is False and call[6] == 2
        assert original.observe().state == 'RUNNING'


def test_duplicate_validation_cleanup_failure_retains_exact_new_handle_for_retry():
    with native.ObservedProcess(os.getpid()) as original:
        kernel = original._kernel
        captured = []
        duplicate = kernel.DuplicateHandle

        def create(*args):
            ok = duplicate(*args)
            if ok:
                captured.append(
                    ctypes.cast(args[3], ctypes.POINTER(wintypes.HANDLE)).contents.value
                )
            return ok

        with patch.object(kernel, 'DuplicateHandle', create):
            with patch.object(kernel, 'GetHandleInformation', return_value=False):
                with patch.object(kernel, 'CloseHandle', return_value=False):
                    with pytest.raises(
                        native.ProcessObservationError, match='CLOSE_FAILED'
                    ) as caught:
                        original.duplicate()
        retained = caught.value.retained_owner
        assert retained._handle == captured[0]
        assert retained._handle != original._handle
        assert original.observe().state == 'RUNNING'
        retained.close()
        assert retained._handle is None


def test_original_process_close_failure_exposes_same_owner_until_exact_handle_retry():
    held = native.ObservedProcess(os.getpid())
    handle = held._handle
    with patch.object(held._kernel, 'CloseHandle', return_value=False):
        with pytest.raises(native.ProcessObservationError, match='CLOSE_FAILED') as caught:
            held.close()
    assert caught.value.retained_owner is held and held._handle == handle
    held.close()
    assert held._handle is None
