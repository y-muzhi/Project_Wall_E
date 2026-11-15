"""Real original Guard ownership/private records/watch, no installed service."""

from dataclasses import replace
import ctypes
from ctypes import wintypes
from time import monotonic, sleep
from unittest.mock import patch

import pytest

from backend.app.infrastructure import runtime_control_git as registry
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown
from backend.app.infrastructure.windows_process import _identity
from backend.tests.infrastructure.test_v20_windows_native_process import resources, scope, peer
from backend.tests.requirements.test_v15_foundation import tmp_path


@pytest.fixture
def owner(resources):
    guard = registry.ControlGitRegistry(
        resources.journal,
        resources.token,
        controller_ref=scope().controller_ref,
    )
    guard.register(scope(), resources.image, resources.job, resources.streams, resources.cwd)
    try:
        yield guard, resources
    finally:
        guard.stop(scope())
        entry = guard._entry(scope())
        if entry.root is not None:
            assert entry.root._kernel.WaitForSingleObject(entry.root._info.process, 8000) == 0
        deadline = monotonic() + 8
        while entry.job.observe_members().process_ids and monotonic() < deadline:
            sleep(0.01)
        guard.release_native_handles(scope())
        guard.close_watch()


def test_register_and_create_reuse_original_binding_and_durable_private_identity(owner):
    guard, resource = owner
    entry = guard._entry(scope())
    receipt = entry.receipt
    assert (
        guard.register(
            scope(),
            resource.image,
            resource.job,
            resource.streams,
            resource.cwd,
        )
        == receipt
    )
    facts = guard.create(scope())
    root = entry.root
    assert facts['resource_ref'] == root.resource_ref
    assert facts['fence']['create_state'] == 'RESOURCE_RECORDED'
    saved = guard.read_receipt(scope(), entry.receipt)
    assert saved['phase'] == 'CREATED'
    assert saved['resource_ref'] == root.resource_ref
    assert saved['fence']['create_state'] == 'MAY_HAVE_BEEN_SENT'
    assert saved['original_process_identity']['pid'] == root.identity.pid
    assert set(saved['stdio_binding']) == {'owner', 'scope', 'io_nonce', 'guard_io_ref'}
    with patch.object(
        registry, 'SuspendedControlGit', side_effect=AssertionError('No second root')
    ):
        assert guard.create(scope())['resource_ref'] == root.resource_ref
    guard.resume(scope())
    assert root._kernel.WaitForSingleObject(root._info.process, 8000) == 0
    assert guard.observe(scope())['observation']['exit_code'] == 0
    # These are private OS facts, with no business Task status or HTTP DTO.
    assert 'task_status' not in saved and 'process_handle' not in saved


def test_post_create_record_failure_keeps_original_root_and_does_not_recreate(owner):
    guard, _ = owner
    writer = guard._record

    def fail(entry, phase):
        if phase == 'CREATED':
            raise OSError('Owned record fault')
        return writer(entry, phase)

    with patch.object(guard, '_record', side_effect=fail):
        with pytest.raises(LaunchOutcomeUnknown, match='CREATE_OUTCOME_UNVERIFIED'):
            guard.create(scope())
    entry = guard._entry(scope())
    assert entry.root is not None and entry.root.observe().state == 'RUNNING'
    with patch.object(registry, 'SuspendedControlGit', side_effect=AssertionError('No replay')):
        with pytest.raises(LaunchOutcomeUnknown, match='REQUIRES_OBSERVATION'):
            guard.create(scope())
    facts = guard.observe(scope())
    assert facts['resource_ref'] == entry.root.resource_ref
    assert facts['fence']['create_state'] == 'MAY_HAVE_BEEN_SENT'


def test_post_resume_record_failure_keeps_original_ack_and_only_observes(owner):
    guard, _ = owner
    guard.create(scope())
    writer = guard._record

    def fail(entry, phase):
        if phase == 'RESUME_ACK':
            raise OSError('Owned resume receipt fault')
        return writer(entry, phase)

    with patch.object(guard, '_record', side_effect=fail):
        with pytest.raises(LaunchOutcomeUnknown, match='RESUME_OUTCOME_UNVERIFIED'):
            guard.resume(scope())
    entry = guard._entry(scope())
    assert entry.root.resume_state == 'ACKNOWLEDGED'
    with pytest.raises(LaunchOutcomeUnknown, match='REQUIRES_OBSERVATION'):
        guard.resume(scope())
    assert entry.root._kernel.WaitForSingleObject(entry.root._info.process, 8000) == 0
    facts = guard.observe(scope())
    assert facts['observation']['state'] == 'EXITED'
    assert facts['fence']['resume_state'] == 'MAY_HAVE_BEEN_SENT'


def test_stop_without_pid_closes_original_nonce_and_late_create_never_runs(owner):
    guard, _ = owner
    facts = guard.stop(scope())
    assert facts['fence']['stop_closed'] and facts['resource_ref'] is None
    with patch.object(
        registry, 'SuspendedControlGit', side_effect=AssertionError('No late create')
    ):
        assert guard.create(scope())['fence']['stop_closed']
    with pytest.raises(LaunchOutcomeUnknown):
        guard.resume(scope())
    assert guard._entry(scope()).root is None


def test_private_receipts_are_immutable_and_wrong_owner_or_bytes_are_not_repaired(owner):
    guard, resource = owner
    receipt = guard._entry(scope()).receipt
    with pytest.raises(LaunchOutcomeUnknown, match='NOT_REGISTERED'):
        guard.read_receipt(replace(scope(), operation_id=2), receipt)
    with pytest.raises(registry.NativeRegistryError):
        guard.read_receipt(replace(scope(), controller_ref='b' * 64), receipt)
    with pytest.raises(registry.NativeRegistryError):
        guard.read_receipt(
            scope(), registry.NativeReceipt('../outside.native.json', receipt.sha256)
        )
    path = resource.journal.root / receipt.filename
    with path.open('ab') as stream:
        stream.write(b'\n')
    with pytest.raises(LaunchOutcomeUnknown, match='BYTES_UNVERIFIED'):
        guard.register(scope(), resource.image, resource.job, resource.streams, resource.cwd)
    assert path.read_bytes().endswith(b'\n\n')


def test_failed_create_receipt_capacity_preserves_original_created_process(owner):
    guard, _ = owner
    with patch.object(registry, 'MAX_RESOURCE_RECORDS', 0):
        with pytest.raises(LaunchOutcomeUnknown, match='CREATE_OUTCOME_UNVERIFIED'):
            guard.create(scope())
    entry = guard._entry(scope())
    assert entry.root is not None and entry.root.observe().state == 'RUNNING'
    assert entry.root.identity.pid in entry.job.observe_members().process_ids


def test_controller_observation_failure_seals_then_terminates_only_owned_job(owner):
    guard, resource = owner
    guard.create(scope())
    root = guard._entry(scope()).root
    source = resource.token._controller
    with patch.object(guard._watch_source, 'observe', side_effect=OSError('Owned observer fault')):
        assert guard.sweep_controller() == 'CONTROLLER_OBSERVATION_UNKNOWN'
    assert root._kernel.WaitForSingleObject(root._info.process, 8000) == 0
    assert root.observe().exit_code == 1
    assert resource.journal.inspect(scope()).stop_closed
    assert guard._admission_closed
    with patch.object(
        registry, 'SuspendedControlGit', side_effect=AssertionError('No new process')
    ):
        closed = guard.create(scope())
        assert closed['fence']['stop_closed']
        assert closed['resource_ref'] == root.resource_ref
    assert source.observe().state == 'RUNNING'


def test_real_controller_exit_watch_closes_fence_and_kills_suspended_original_git(owner):
    guard, resource = owner
    guard.create(scope())
    root = guard._entry(scope()).root
    guard.start_controller_watch()
    with pytest.raises(registry.NativeRegistryError, match='WATCH_REQUIRED'):
        guard.close_watch()
    source = resource.token._controller
    kernel, security = root._kernel, root._security
    # Test-only termination of the actual owned STDIO fixture, proved against the
    # retained original process identity before obtaining TERMINATE access.
    handle = kernel.OpenProcess(0x1 | 0x1000 | 0x100000, False, source.identity.pid)
    assert handle
    try:
        assert _identity(kernel, security, handle, source.identity.pid) == source.identity
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateProcess.restype = wintypes.BOOL
        assert kernel.TerminateProcess(handle, 17)
        assert kernel.WaitForSingleObject(handle, 8000) == 0
    finally:
        assert kernel.CloseHandle(handle)
    assert root._kernel.WaitForSingleObject(root._info.process, 8000) == 0
    assert root.observe().state == 'EXITED' and root.observe().exit_code == 1
    assert resource.journal.inspect(scope()).stop_closed
    assert guard._watch_reason == 'CONTROLLER_EXITED'
    assert root.resume_state == 'NONE'


def test_observation_deduplicates_identical_private_facts_and_not_an_execution_retry(owner):
    guard, resource = owner
    first = guard.observe(scope())
    receipt = guard._entry(scope()).receipt
    count = len(list(resource.journal.root.glob('*.native.json')))
    second = guard.observe(scope())
    assert first == second
    assert guard._entry(scope()).receipt == receipt
    assert len(list(resource.journal.root.glob('*.native.json'))) == count


def test_restarted_registry_cannot_reconstruct_original_objects_or_reopen_pid(owner):
    guard, resource = owner
    guard.create(scope())
    other = registry.ControlGitRegistry(
        resource.journal,
        resource.token,
        controller_ref=scope().controller_ref,
    )
    try:
        with pytest.raises(LaunchOutcomeUnknown, match='NOT_REGISTERED'):
            other.observe(scope())
        with pytest.raises(LaunchOutcomeUnknown, match='NOT_PREPARED'):
            other.register(
                scope(),
                resource.image,
                resource.job,
                resource.streams,
                resource.cwd,
            )
    finally:
        other.close_watch()


def test_failed_durable_stop_still_seals_volatile_creation_and_resume_admission(owner):
    guard, resource = owner
    original = resource.journal.close_nonce
    with patch.object(
        resource.journal, 'close_nonce', side_effect=OSError('Owned closure IO fault')
    ):
        with pytest.raises(LaunchOutcomeUnknown, match='STOP_CLOSURE_UNVERIFIED'):
            guard.stop(scope())
    assert not resource.journal.inspect(scope()).stop_closed
    assert guard._entry(scope()).stop_requested
    with patch.object(
        registry, 'SuspendedControlGit', side_effect=AssertionError('No late create')
    ):
        with pytest.raises(LaunchOutcomeUnknown, match='STOP_CLOSURE_UNVERIFIED'):
            guard.create(scope())
    with pytest.raises(LaunchOutcomeUnknown, match='STOP_REQUESTED'):
        guard.resume(scope())
    assert original(scope()).stop_closed


def test_busy_original_scope_does_not_block_controller_sweep_or_other_stop_domains(owner):
    from threading import Event, Thread

    guard, resource = owner
    entry = guard._entry(scope())
    held, release, finished = Event(), Event(), Event()

    def hold():
        with entry.gate:
            held.set()
            assert release.wait(5)

    def sweep():
        try:
            guard.sweep_controller()
        finally:
            finished.set()

    blocker = Thread(target=hold)
    sweeper = Thread(target=sweep)
    blocker.start()
    assert held.wait(2)
    try:
        with patch.object(guard._watch_source, 'observe', side_effect=OSError('Owned fault')):
            sweeper.start()
            assert finished.wait(2), 'Sweep must not wait on an unrelated busy scope'
            assert guard._admission_closed
            assert not resource.journal.inspect(scope()).stop_closed
    finally:
        release.set()
        blocker.join(5)
        if sweeper.ident is not None:
            sweeper.join(5)
    assert not blocker.is_alive() and not sweeper.is_alive()
    guard.stop(scope())


def test_unknown_native_receipt_publish_reconciles_same_file_without_recreating_root(owner):
    from backend.app.infrastructure import windows_private_record as records

    guard, _ = owner
    kernel = records.record_api()
    calls = []

    class Proxy:
        def __getattr__(self, name):
            if name == 'FlushFileBuffers':

                def flush(handle):
                    calls.append(handle)
                    return kernel.FlushFileBuffers(handle) if len(calls) == 1 else False

                return flush
            return getattr(kernel, name)

    with patch.object(records, 'record_api', return_value=Proxy()):
        with pytest.raises(LaunchOutcomeUnknown, match='CREATE_OUTCOME_UNVERIFIED'):
            guard.create(scope())
    entry = guard._entry(scope())
    original_root, pending = entry.root, entry.pending_record
    assert original_root is not None and pending is not None
    assert pending._rename_may and pending._target.exists()
    assert guard._journal.inspect(scope()).create_state == 'MAY_HAVE_BEEN_SENT'
    original_publish = records.PrivateRecordAppend.publish

    def publish(writer):
        assert writer is not pending, 'Original uncertain publication must never be renamed twice'
        return original_publish(writer)

    with (
        patch.object(records.PrivateRecordAppend, 'publish', side_effect=publish, autospec=True),
        patch.object(registry, 'SuspendedControlGit', side_effect=AssertionError('No second root')),
    ):
        observation = guard.observe(scope())
    assert entry.root is original_root and entry.pending_record is None
    assert observation['resource_ref'] == original_root.resource_ref
    assert observation['fence']['create_state'] == 'MAY_HAVE_BEEN_SENT'
    assert pending._handle is None and pending._target.exists()
    # Recovered private evidence does not fill a lost dispatch acknowledgment.
    with pytest.raises(LaunchOutcomeUnknown, match='REQUIRES_OBSERVATION'):
        guard.create(scope())


def test_creation_pipe_close_failure_prevents_resume_and_retries_only_original_owner(owner):
    from types import SimpleNamespace
    from backend.app.infrastructure.windows_stdio import StdioBoundaryError

    guard, resource = owner
    guard.create(scope())
    entry = guard._entry(scope())
    root = entry.root
    identity = root.identity
    original = entry.streams._kernel
    held = next(iter(entry.streams._ends.values()))

    def close(handle):
        if handle == held:
            ctypes.set_last_error(5)
            return False
        return original.CloseHandle(handle)

    entry.streams._kernel = SimpleNamespace(CloseHandle=close)
    try:
        with pytest.raises(StdioBoundaryError, match='CLOSE_UNVERIFIED'):
            guard.resume(scope())
        assert root.resume_state == 'NONE' and not entry.creation_stdio_closed
        assert resource.journal.inspect(scope()).resume_state == 'NONE'
        assert entry.streams._ends and root.identity == identity
    finally:
        entry.streams._kernel = original
    resumed = guard.resume(scope())
    assert resumed['creation_stdio_closed'] and not entry.streams._ends
    assert root.identity == identity and root.resume_state == 'ACKNOWLEDGED'
    assert root._kernel.WaitForSingleObject(root._info.process, 8000) == 0


@pytest.mark.parametrize('expired', [False, True])
def test_shutdown_requests_each_original_task_even_after_a_peer_failure_or_deadline(owner, expired):
    guard, resource = owner
    scopes = [replace(scope(), operation_id=index) for index in (21, 22, 23)]
    calls = []
    deadline = monotonic() + (-1 if expired else 5)

    def callback(original):
        def stop(checkpoint, expires):
            checkpoint()
            calls.append((original, expires))
            assert expires <= deadline
            if original == scopes[0]:
                raise OSError('Owned first TASK stop fault')

        return stop

    for original in scopes:
        guard.register_task_stop(original, callback(original))
    with pytest.raises(LaunchOutcomeUnknown, match='CLEANUP_UNVERIFIED') as failure:
        guard._sweep_task_stops(closing=True, deadline=deadline)
    assert failure.value.retained_owner is guard
    assert [original for original, _ in calls] == scopes
    assert guard._settled_task_stops == set(scopes[1:])
    # Cleanup only this fixture's failed callback after proving the others were
    # already settled. No unknown native close is retried by product shutdown.
    guard._task_stops[scopes[0]] = lambda checkpoint, expires: None
    guard._sweep_task_stops(closing=True)
    assert guard._settled_task_stops == set(scopes)
