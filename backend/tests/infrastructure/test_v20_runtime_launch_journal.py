"""Private persisted launch fences; native callbacks are explicitly offline doubles."""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import patch

import pytest

from backend.app.infrastructure import runtime_launch_journal as launch
from backend.app.infrastructure.process_lock import ProcessAlreadyRunning
from backend.app.infrastructure.windows_local_paths import LocalPathGuard, local_absolute_path
from backend.app.infrastructure.windows_private_package import (
    PackageSecurityError,
    create_private_package,
)
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.tests.requirements import test_v15_foundation as foundation

tmp_path = foundation.tmp_path

FP = 'b' * 64
REF = 'original-resource-000001'


def scope(number=1):
    return launch.LaunchScope('a' * 64, number, 1, 'original-nonce-' + str(number).zfill(12))


def forbidden():
    raise AssertionError('No duplicate or closed native dispatch')


class OrdinaryOwnedTestRoot:
    # IO/concurrency unit port only: deliberately does NOT attest DACL/operator
    # privacy. The actual production guard is separately tested below.
    def __init__(self, root):
        self.path = local_absolute_path(root)
        self._guard = None

    def __enter__(self):
        self._guard = LocalPathGuard(self.path, directory=True)
        self._guard.__enter__()
        return self

    def verify(self):
        return self._guard.verify()

    def verify_member(self, name, *, directory):
        assert '/' not in name and '\\' not in name and name not in ('.', '..')
        with LocalPathGuard(self.path / name, directory=directory) as member:
            return member.verify()

    def publish_new_file(self, name, raw, *, max_file_bytes):
        # IO-only port; production creation uses an explicit native descriptor.
        self.verify()
        assert 0 < len(raw) <= max_file_bytes
        target = self.path / name
        created = False
        try:
            with target.open('xb') as stream:
                created = True
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            if created:
                target.unlink()
            raise

    def __exit__(self, kind, error, traceback):
        self._guard.close()


@pytest.fixture
def journal(tmp_path, monkeypatch):
    root = tmp_path / 'guard-state-private'
    if os.environ.get('WALLE_TEST_GUARD_PRIVATE_ROOT') == '1':
        create_private_package(root)
    else:
        root.mkdir()
        monkeypatch.setattr(launch, 'PrivatePackageGuard', OrdinaryOwnedTestRoot)
    with launch.LaunchJournal(root) as store:
        yield store


def test_actual_private_guard_rejects_appcontainer_before_metadata_or_lock_writes(tmp_path):
    root = tmp_path / 'actual-guard-boundary'
    with ObservedProcess(os.getpid()) as process:
        container = process.identity.is_appcontainer
    if container:
        root.mkdir()
        with (
            pytest.raises(PackageSecurityError, match='APPCONTAINER_OPERATOR_REJECTED'),
            launch.LaunchJournal(root),
        ):
            pytest.fail('An AppContainer may not own the Guard state')
        assert list(root.iterdir()) == []
    else:
        create_private_package(root)
        with launch.LaunchJournal(root) as store:
            assert store.close_nonce(scope()).stop_closed


def test_prepare_same_input_and_actual_dispatch_intent_are_persisted_before_callback(journal):
    target = scope()
    assert journal.inspect(target) is None
    with pytest.raises(launch.LaunchOutcomeUnknown):
        journal.dispatch_create(target, FP, forbidden)
    prepared = journal.prepare(target, FP)
    assert journal.prepare(target, FP) == prepared
    with pytest.raises(launch.LaunchFenceError, match='ORIGINAL_INPUT_CONFLICT'):
        journal.prepare(target, 'c' * 64)
    calls = []

    def create():
        assert journal.inspect(target).create_state == 'MAY_HAVE_BEEN_SENT'
        calls.append('create')
        return REF

    created = journal.dispatch_create(target, FP, create)
    assert created.create_state == 'RESOURCE_RECORDED' and created.resource_ref == REF
    assert journal.dispatch_create(target, FP, forbidden) == created

    def resume():
        assert journal.inspect(target).resume_state == 'MAY_HAVE_BEEN_SENT'
        calls.append('resume')

    acknowledged = journal.dispatch_resume(target, REF, resume)
    assert acknowledged.resume_state == 'ACKNOWLEDGED'
    assert journal.dispatch_resume(target, REF, forbidden) == acknowledged
    assert calls == ['create', 'resume']


def test_stop_without_pid_or_prepare_closes_original_nonce_and_late_create_resume_never_runs(
    journal,
):
    target = scope()
    closed = journal.close_nonce(target)
    assert closed.stop_closed and closed.input_sha256 is None and closed.resource_ref is None
    assert journal.prepare(target, FP) == closed
    assert journal.dispatch_create(target, FP, forbidden) == closed
    assert journal.dispatch_resume(target, REF, forbidden) == closed
    assert journal.close_nonce(target) == closed
    assert not hasattr(closed, 'stopped')  # A dispatch fence is not OS-stop evidence.


def test_native_create_first_then_stop_keeps_original_resource_and_blocks_resume(journal):
    target = scope()
    journal.prepare(target, FP)
    journal.dispatch_create(target, FP, lambda: REF)
    stopped = journal.close_nonce(target)
    assert stopped.stop_closed and stopped.resource_ref == REF
    assert stopped.create_state == 'RESOURCE_RECORDED'
    assert journal.dispatch_resume(target, REF, forbidden) == stopped


def test_lost_native_create_or_resume_ack_stays_may_have_been_sent_and_cannot_retry(journal):
    target = scope()
    journal.prepare(target, FP)
    calls = []

    def lost_create():
        calls.append('create')
        raise OSError('Injected native reply lost')

    with pytest.raises(launch.LaunchOutcomeUnknown):
        journal.dispatch_create(target, FP, lost_create)
    with pytest.raises(launch.LaunchOutcomeUnknown, match='REQUIRES_OBSERVATION'):
        journal.dispatch_create(target, FP, forbidden)
    assert journal.inspect(target).create_state == 'MAY_HAVE_BEEN_SENT'
    other = scope(2)
    journal.prepare(other, FP)
    journal.dispatch_create(other, FP, lambda: REF)

    def lost_resume():
        calls.append('resume')
        raise OSError('Injected native reply lost')

    with pytest.raises(launch.LaunchOutcomeUnknown):
        journal.dispatch_resume(other, REF, lost_resume)
    with pytest.raises(launch.LaunchOutcomeUnknown, match='REQUIRES_OBSERVATION'):
        journal.dispatch_resume(other, REF, forbidden)
    assert journal.inspect(other).resume_state == 'MAY_HAVE_BEEN_SENT'
    assert calls == ['create', 'resume']


def test_failed_dispatch_persistence_never_calls_native_and_failed_stop_is_volatile_closed(journal):
    target = scope()
    journal.prepare(target, FP)
    with patch.object(launch.os, 'replace', side_effect=OSError('Injected disk failure')):
        with pytest.raises(launch.LaunchOutcomeUnknown):
            journal.dispatch_create(target, FP, forbidden)
        with pytest.raises(launch.LaunchOutcomeUnknown):
            journal.close_nonce(target)
        absent = scope(2)
        with pytest.raises(launch.LaunchOutcomeUnknown):
            journal.close_nonce(absent)
    assert journal.inspect(target).create_state == 'NONE'
    for key in (target, absent):
        with pytest.raises(launch.LaunchOutcomeUnknown, match='STOP_CLOSURE_UNVERIFIED'):
            journal.prepare(key, FP)
    with pytest.raises(launch.LaunchOutcomeUnknown):
        journal.dispatch_create(target, FP, forbidden)
    assert list(journal.root.glob('.launch-*.tmp')) == []
    assert journal.close_nonce(target).stop_closed


def test_lost_stop_file_ack_is_reconciled_from_same_durable_fence_not_reopened(journal):
    target = scope()
    journal.prepare(target, FP)
    original = launch.os.replace

    def lost(source, destination):
        original(source, destination)
        raise OSError('Injected after atomic publication')

    with patch.object(launch.os, 'replace', lost), pytest.raises(launch.LaunchOutcomeUnknown):
        journal.close_nonce(target)
    assert journal.inspect(target).stop_closed
    assert journal.dispatch_create(target, FP, forbidden).stop_closed


def test_native_resource_created_but_metadata_failed_remains_unknown_without_second_create(journal):
    target = scope()
    journal.prepare(target, FP)
    real = journal._save
    calls = []

    def save(current, old):
        if current.create_state == 'RESOURCE_RECORDED':
            raise OSError('Injected after native create')
        return real(current, old)

    with patch.object(journal, '_save', save), pytest.raises(launch.LaunchOutcomeUnknown):
        journal.dispatch_create(target, FP, lambda: calls.append(True) or REF)
    assert calls == [True]
    assert journal.inspect(target).create_state == 'MAY_HAVE_BEEN_SENT'
    with pytest.raises(launch.LaunchOutcomeUnknown):
        journal.dispatch_create(target, FP, forbidden)


def test_reentrant_stop_during_native_callback_is_never_overwritten_by_late_resource(journal):
    target = scope()
    journal.prepare(target, FP)

    def create():
        journal.close_nonce(target)
        return REF

    result = journal.dispatch_create(target, FP, create)
    assert result.stop_closed and result.resource_ref == REF
    assert journal.dispatch_resume(target, REF, forbidden) == result


def test_blocked_create_cannot_block_another_scope_stop_or_release_store_owner(journal):
    first, other = scope(), scope(2)
    journal.prepare(first, FP)
    journal.prepare(other, FP)
    entered, release = Event(), Event()

    def create():
        entered.set()
        assert release.wait(5)
        return REF

    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(journal.dispatch_create, first, FP, create)
        try:
            assert entered.wait(5)
            closed = pool.submit(journal.close_nonce, other).result(timeout=2)
            assert closed.stop_closed and closed.resource_ref is None
            with pytest.raises(launch.LaunchFenceError, match='ACTIVE_REQUESTS'):
                journal.close()
        finally:
            release.set()
        assert future.result(timeout=5).resource_ref == REF


def test_same_scope_stop_waits_for_created_resource_and_then_keeps_it(journal):
    target = scope()
    journal.prepare(target, FP)
    entered, release = Event(), Event()

    def create():
        entered.set()
        assert release.wait(5)
        return REF

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(journal.dispatch_create, target, FP, create)
        try:
            assert entered.wait(5)
            second = pool.submit(journal.close_nonce, target)
        finally:
            release.set()
        assert first.result(timeout=5).resource_ref == REF
        closed = second.result(timeout=5)
        assert closed.stop_closed and closed.resource_ref == REF


def test_reopen_seals_old_nonce_but_preserves_original_inputs_and_historical_resource(journal):
    target = scope()
    journal.prepare(target, FP)
    created = journal.dispatch_create(target, FP, lambda: REF)
    root = journal.root
    journal.close()
    with launch.LaunchJournal(root) as recovered:
        current = recovered.inspect(target)
        assert current.stop_closed and current.input_sha256 == FP and current.resource_ref == REF
        assert current.record_revision > created.record_revision
        assert recovered.dispatch_create(target, FP, forbidden) == current
        assert recovered.dispatch_resume(target, REF, forbidden) == current
        assert recovered.inspect(scope(99)) is None


def test_real_os_owner_capacity_and_no_reopen_or_rebind(journal):
    target = scope()
    with pytest.raises(ProcessAlreadyRunning), launch.LaunchJournal(journal.root):
        pytest.fail('Another owner cannot run the journal')
    journal.prepare(target, FP)
    with patch.object(launch, 'MAX_LAUNCH_RECORDS', 1):
        with pytest.raises(launch.LaunchFenceError, match='CAPACITY'):
            journal.prepare(scope(2), FP)
        with pytest.raises(launch.LaunchOutcomeUnknown, match='CAPACITY'):
            journal.close_nonce(scope(2))
        assert journal.close_nonce(target).stop_closed
    old, raw = journal._read(target)
    with pytest.raises(launch.LaunchFenceError, match='CANNOT_REOPEN_OR_REBIND'):
        journal._save(replace(old, stop_closed=False, record_revision=old.record_revision + 1), raw)
    assert journal.inspect(target).stop_closed


def test_corrupt_persisted_state_is_not_repaired_or_replaced_during_reopen(journal):
    target = scope()
    journal.prepare(target, FP)
    path = journal._path(target)
    with path.open('ab') as stream:
        stream.write(b' ')
    original = path.read_bytes()
    root = journal.root
    journal.close()
    with (
        pytest.raises(launch.LaunchFenceError, match='NOT_CANONICAL'),
        launch.LaunchJournal(root),
    ):
        pytest.fail('Corrupt metadata cannot become an accepting Guard')
    assert path.read_bytes() == original


def test_invalid_native_reference_and_resume_resource_mismatch_never_authorize_replay(journal):
    target = scope()
    journal.prepare(target, FP)
    with pytest.raises(launch.LaunchOutcomeUnknown):
        journal.dispatch_create(target, FP, lambda: 'invalid')
    assert journal.inspect(target).create_state == 'MAY_HAVE_BEEN_SENT'
    other = scope(2)
    journal.prepare(other, FP)
    journal.dispatch_create(other, FP, lambda: REF)
    with pytest.raises(launch.LaunchFenceError, match='RESOURCE_DIFFERS'):
        journal.dispatch_resume(other, 'another-resource-00002', forbidden)
    assert journal.inspect(other).resume_state == 'NONE'


@pytest.mark.parametrize(
    'boundary,stage,reason',
    [
        ('directory', 'JOURNAL_DIRECTORY_SECURITY', 'PACKAGE_OWNER_OR_DACL_DIFFERS'),
        ('creation', 'JOURNAL_LOCK_CREATION', 'NATIVE_FILE_ERROR'),
        ('lock-security', 'JOURNAL_LOCK_SECURITY', 'PACKAGE_OWNER_OR_DACL_DIFFERS'),
        ('lock-acquire', 'JOURNAL_LOCK_ACQUISITION', 'ORIGINAL_LOCK_OCCUPIED'),
        ('ownership', 'JOURNAL_OWNERSHIP_CHECK', 'GUARD_JOURNAL_NOT_OPEN'),
        ('prior', 'JOURNAL_PRIOR_NONCES', 'GUARD_STATE_FILENAME_INVALID'),
    ],
)
def test_actual_journal_failure_keeps_finite_phase_reason_and_releases_known_owner(
    tmp_path, monkeypatch, boundary, stage, reason
):
    from backend.app.infrastructure.guard_service_diagnostics import (
        GuardFailureReason,
        GuardFailureStage,
    )

    root = tmp_path / 'diagnostic-private-journal'
    create_private_package(root)
    with monkeypatch.context() as patcher:
        if boundary == 'directory':

            def failed_root(*args, **kwargs):
                raise PackageSecurityError('PACKAGE_OWNER_OR_DACL_DIFFERS')

            patcher.setattr(launch, 'PrivatePackageGuard', failed_root)
        elif boundary == 'creation':
            original = Path.lstat

            def failed_creation(path, *args, **kwargs):
                if path == root / 'runtime-guard.lock':
                    error = OSError('private path and provider secret')
                    error.winerror = 5
                    raise error
                return original(path, *args, **kwargs)

            patcher.setattr(Path, 'lstat', failed_creation)
        elif boundary == 'lock-security':

            def failed_member(*args, **kwargs):
                raise PackageSecurityError('PACKAGE_OWNER_OR_DACL_DIFFERS')

            patcher.setattr(launch.PrivatePackageGuard, 'verify_member', failed_member)
        elif boundary == 'lock-acquire':

            def failed_acquire(*args, **kwargs):
                raise ProcessAlreadyRunning('private path and provider secret')

            patcher.setattr(launch.ProcessLock, 'acquire', failed_acquire)
        elif boundary == 'ownership':

            def failed_ownership(*args, **kwargs):
                raise launch.LaunchFenceError('GUARD_JOURNAL_NOT_OPEN')

            patcher.setattr(launch.LaunchJournal, '_verify', failed_ownership)
        else:

            def failed_prior(*args, **kwargs):
                raise launch.LaunchFenceError('GUARD_STATE_FILENAME_INVALID')

            patcher.setattr(launch.LaunchJournal, '_seal_prior_nonces', failed_prior)
        with (
            pytest.raises(RuntimeError if boundary != 'creation' else OSError) as failure,
            launch.LaunchJournal(root),
        ):
            pytest.fail('Faulted initialization must not accept work')
    diagnostic = failure.value.guard_diagnostic
    assert diagnostic.stage is GuardFailureStage[stage]
    assert diagnostic.reason is GuardFailureReason[reason]
    assert diagnostic.native_error == (5 if boundary == 'creation' else None)
    assert 'private path' not in repr(diagnostic)
    # The actual NTFS paths and original OS lock are available after this failed owner.
    with launch.LaunchJournal(root) as reopened:
        assert reopened.inspect(scope()) is None
