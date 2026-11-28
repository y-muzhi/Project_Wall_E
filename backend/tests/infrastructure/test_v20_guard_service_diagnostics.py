"""Finite SCM failures and the Guard runtime journal probe."""

from types import SimpleNamespace

import pytest

from backend.app.infrastructure.guard_service_diagnostics import (
    GuardFailureReason,
    GuardFailureStage,
    GuardServiceDiagnostic,
    decode_service_diagnostic,
    diagnostic_for_failure,
)


@pytest.mark.parametrize('stage', list(GuardFailureStage))
def test_scm_round_trip_keeps_only_fixed_stage_and_native_number(stage):
    diagnostic = GuardServiceDiagnostic(stage, 5)
    assert decode_service_diagnostic(1066, diagnostic.service_exit_code) == diagnostic
    assert decode_service_diagnostic(0, diagnostic.service_exit_code) is None


@pytest.mark.parametrize('native', [None, 0, True, -1, 65536, '5', object()])
def test_unknown_or_untrusted_native_shape_is_not_encoded(native):
    failure = SimpleNamespace(native_error=native)
    diagnostic = diagnostic_for_failure(failure, GuardFailureStage.PRIVATE_JOURNAL)
    assert diagnostic.native_error is None
    assert decode_service_diagnostic(1066, diagnostic.service_exit_code) == diagnostic


@pytest.mark.parametrize(
    'win32,specific',
    [
        (1066, 1),
        (0, 0),
        (1066, -1),
        (1066, True),
        (1066, 0x57000000),
        (1066, 0x57FF0005),
        (1066, 0x157010005),
        (True, 0x57010005),
    ],
)
def test_legacy_and_unrecognized_service_codes_are_not_guessed(win32, specific):
    assert decode_service_diagnostic(win32, specific) is None


def test_native_winerror_is_used_without_errno_or_exception_text():
    error = OSError(13, 'private path and provider secret')
    error.winerror = 32
    diagnostic = diagnostic_for_failure(error, GuardFailureStage.BACKEND_SOURCE)
    assert diagnostic.native_error == 32
    assert 'private' not in repr(diagnostic)
    assert (
        diagnostic_for_failure(OSError(13, 'secret'), GuardFailureStage.BACKEND_SOURCE).native_error
        is None
    )


def test_original_failure_diagnostic_survives_outer_boundary():
    original = GuardServiceDiagnostic(GuardFailureStage.PRIVATE_JOURNAL, 5)
    error = RuntimeError('private exception')
    error.guard_diagnostic = original
    assert diagnostic_for_failure(error, GuardFailureStage.SERVICE_START) is original
    with pytest.raises(ValueError):
        GuardServiceDiagnostic(11, 5)
    with pytest.raises(ValueError):
        GuardServiceDiagnostic(GuardFailureStage.PRIVATE_JOURNAL, True)


@pytest.mark.parametrize('reason', list(GuardFailureReason))
def test_all_finite_reasons_round_trip_without_raw_text(reason):
    diagnostic = GuardServiceDiagnostic(GuardFailureStage.JOURNAL_LOCK_SECURITY, 5, reason)
    assert decode_service_diagnostic(1066, diagnostic.service_exit_code) == diagnostic
    if reason is not GuardFailureReason.UNSPECIFIED:
        failure = RuntimeError(reason.name)
        assert diagnostic_for_failure(failure, diagnostic.stage).reason is reason


@pytest.mark.parametrize('code', [0x570B0000, 0x570B0005])
def test_deployed_stage_only_codes_remain_readable_without_inventing_a_reason(code):
    expected = GuardServiceDiagnostic(GuardFailureStage.PRIVATE_JOURNAL, (code & 0xFFFF) or None)
    assert decode_service_diagnostic(1066, code) == expected


def test_reason_and_native_cause_are_bounded_and_never_parse_secret_messages():
    from backend.app.infrastructure.process_lock import ProcessAlreadyRunning

    native = OSError('private path must not be emitted')
    native.winerror = 32
    error = ProcessAlreadyRunning('arbitrary private message')
    error.__cause__ = native
    result = diagnostic_for_failure(error, GuardFailureStage.JOURNAL_LOCK_ACQUISITION)
    assert result.reason is GuardFailureReason.ORIGINAL_LOCK_OCCUPIED
    assert result.native_error == 32 and 'private' not in repr(result)
    error.__cause__ = error
    result = diagnostic_for_failure(error, GuardFailureStage.JOURNAL_LOCK_ACQUISITION)
    assert (
        result.reason is GuardFailureReason.ORIGINAL_LOCK_OCCUPIED and result.native_error is None
    )
    unknown = RuntimeError('PACKAGE_OWNER_OR_DACL_DIFFERS-secret')
    result = diagnostic_for_failure(unknown, GuardFailureStage.JOURNAL_DIRECTORY_SECURITY)
    assert result.reason is GuardFailureReason.UNKNOWN_INTERNAL_FAILURE
    with pytest.raises(ValueError):
        GuardServiceDiagnostic(GuardFailureStage.PRIVATE_JOURNAL, reason=1)
    invalid_stage = 0xD0000000 | (31 << 23)
    invalid_reason = 0xD0000000 | (11 << 23) | (127 << 16)
    assert decode_service_diagnostic(1066, invalid_stage) is None
    assert decode_service_diagnostic(1066, invalid_reason) is None


@pytest.mark.parametrize('fail_reopen', [False, True])
def test_real_private_journal_runtime_probe_closes_original_lock_and_temporary_root(
    tmp_path, monkeypatch, fail_reopen
):
    import tempfile

    from backend import frozen_guard_entry as entry
    from backend.app.infrastructure import runtime_launch_journal as launch

    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    original = launch.LaunchJournal
    observed = []

    def journal(root):
        observed.append(root)
        if fail_reopen and len(observed) == 2:
            raise RuntimeError('private path and provider secret')
        return original(root)

    monkeypatch.setattr(launch, 'LaunchJournal', journal)
    if fail_reopen:
        with pytest.raises(entry.GuardRuntimeProbeError) as failure:
            entry.verify_private_journal_runtime()
        assert 'private path' not in str(failure.value)
    else:
        entry.verify_private_journal_runtime()
    assert len(observed) == 2 and observed[0] == observed[1]
    assert not observed[0].parent.exists()
    assert not list(tmp_path.iterdir())
