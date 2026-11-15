"""Fixed Git version-only native launch, never a business repository or service."""

from dataclasses import asdict, replace
import ctypes
import hashlib
import json
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.app.infrastructure import windows_native_process as native
from backend.app.infrastructure.git_bundle import BUNDLE_PARENT
from backend.app.infrastructure.runtime_launch_journal import (
    LaunchFence,
    LaunchScope,
    LaunchJournal,
)
from backend.app.infrastructure.windows_controller_token import ControllerPrimaryToken
from backend.app.infrastructure.windows_executable_pin import ExecutablePin
from backend.app.infrastructure.windows_job import OwnedJob
from backend.app.infrastructure.windows_local_paths import LocalPathGuard
from backend.app.infrastructure.windows_private_package import create_private_package
from backend.app.infrastructure.windows_stdio import GuardStandardIO
from backend.tests.infrastructure.test_v20_windows_stdio import peer, publish, wait_file


def scope():
    return LaunchScope('a' * 64, 1, 1, 'stdio-original-nonce-0001')


def fence(**changes):
    row = LaunchFence(
        1,
        scope(),
        'a' * 64,
        'MAY_HAVE_BEEN_SENT',
        'NONE',
        None,
        False,
        1,
        '2026-11-05T00:00:00.000Z',
    )
    return replace(row, **changes)


@pytest.mark.parametrize('run_kind', ['TASK', 'CHECK_DRIVER', '', None])
def test_unadmitted_task_or_driver_never_uses_control_git_identity(run_kind):
    with patch.object(native, '_api', side_effect=AssertionError('No fallback process')):
        with pytest.raises(native.NativeLaunchError, match='ADMITTED_LPAC'):
            native.SuspendedControlGit(
                None,
                None,
                None,
                None,
                None,
                scope=scope(),
                fence=fence(),
                arguments=('--version',),
                run_kind=run_kind,
            )


@pytest.mark.parametrize(
    'changes',
    [
        {'stop_closed': True},
        {'scope': replace(scope(), operation_id=2)},
        {'input_sha256': 'b' * 64},
        {'create_state': 'NONE'},
        {'create_state': 'RESOURCE_RECORDED', 'resource_ref': 'original-resource-01'},
        {'resume_state': 'MAY_HAVE_BEEN_SENT'},
    ],
)
def test_unprepared_closed_foreign_or_previously_created_dispatch_is_rejected(changes):
    with pytest.raises(native.NativeLaunchError):
        native._fence(fence(**changes), scope(), 'a' * 64, 'CREATE')


@pytest.mark.parametrize(
    'arguments', [('--help',), ('-c', 'alias.x=!cmd', 'x'), ['--version'], (), '--version']
)
def test_only_the_fixed_version_probe_is_registered(arguments):
    held = object.__new__(ExecutablePin)
    held._path = BUNDLE_PARENT / 'win-x64/cmd/git.exe'
    with pytest.raises(native.NativeLaunchError, match='NOT_REGISTERED'):
        native._command(held, arguments)


def test_other_program_is_rejected_even_if_it_has_a_valid_pin_type():
    held = object.__new__(ExecutablePin)
    held._path = BUNDLE_PARENT / 'win-x64/other.exe'
    with pytest.raises(native.NativeLaunchError, match='REGISTERED_CONTROL_GIT_PROGRAM'):
        native._command(held, ('--version',))


class ApiProxy:
    def __init__(self, original, **changes):
        self.original = original
        self.changes = changes

    def __getattr__(self, key):
        if key in self.changes:
            return self.changes[key]
        return getattr(self.original, key)


@pytest.fixture
def resources(peer):
    source, descriptor, _, directory = peer
    root = BUNDLE_PARENT / 'win-x64'
    inventory = json.loads((root / 'manifest.json').read_bytes())
    member = next(row for row in inventory['members'] if row['path'] == 'cmd/git.exe')
    job = OwnedJob(active_process_limit=16, job_memory_limit_bytes=512 * 1024 * 1024)
    roots = []
    try:
        with ControllerPrimaryToken(source, expected=source.identity) as token:
            with ExecutablePin(
                root / 'cmd/git.exe',
                expected_byte_count=member['byte_count'],
                expected_sha256=member['sha256'],
            ) as image:
                with LocalPathGuard(directory, directory=True) as cwd:
                    with GuardStandardIO(token, descriptor, scope=scope()) as streams:
                        publish(directory / 'copy-ack.json', asdict(streams.binding))
                        wait_file(directory / 'copy-released.json')
                        package = create_private_package(directory / 'native-journal')
                        with LaunchJournal(package) as journal:
                            arguments = ('--version',)
                            digest = native.control_git_input_sha256(
                                token,
                                image,
                                job,
                                streams,
                                cwd,
                                scope(),
                                arguments,
                            )
                            journal.prepare(scope(), digest)
                            data = SimpleNamespace(
                                token=token,
                                image=image,
                                job=job,
                                streams=streams,
                                cwd=cwd,
                                journal=journal,
                                digest=digest,
                                roots=roots,
                            )
                            try:
                                yield data
                            finally:
                                journal.close_nonce(scope())
                                job.terminate_owned(1)
                                for owned in roots:
                                    assert (
                                        job._kernel.WaitForSingleObject(owned._info.process, 8000)
                                        == 0
                                    )
                                    assert owned.observe().state == 'EXITED'
                                    owned.close()
    finally:
        job.terminate_owned(1)
        deadline = monotonic() + 8
        while job.observe_members().process_ids and monotonic() < deadline:
            sleep(0.01)
        assert job.observe_members().complete and not job.observe_members().process_ids
        job.close()


def create(resources):
    def dispatch():
        current = resources.journal.inspect(scope())
        try:
            held = native.SuspendedControlGit(
                resources.token,
                resources.image,
                resources.job,
                resources.streams,
                resources.cwd,
                scope=scope(),
                fence=current,
                arguments=('--version',),
            )
        except native.NativeLaunchError as error:
            retained = getattr(error, 'retained_owner', None)
            if retained is not None:
                resources.roots.append(retained)
            raise
        resources.roots.append(held)
        return held.resource_ref

    resources.journal.dispatch_create(scope(), resources.digest, dispatch)
    return resources.roots[-1]


def resume(resources, root):
    def dispatch():
        root.resume_once(resources.journal.inspect(scope()))

    return resources.journal.dispatch_resume(scope(), root.resource_ref, dispatch)


def test_real_as_user_is_suspended_in_original_job_and_only_resumes_after_durable_step(resources):
    held = create(resources)
    original = held.identity
    assert original.image_path.lower() == str(resources.image.path).lower()
    assert original.user_sid == resources.token.identity.user_sid
    assert not original.is_elevated and not original.is_appcontainer
    assert held.observe().state == 'RUNNING' and held.resume_state == 'NONE'
    assert original.pid in resources.job.observe_members().process_ids
    with pytest.raises(native.NativeLaunchError, match='STILL_ACTIVE'):
        held.close()
    with pytest.raises(native.NativeLaunchError, match='PERSISTED_RESUME'):
        held.resume_once(resources.journal.inspect(scope()))
    observed = resume(resources, held)
    assert observed.resume_state == held.resume_state == 'ACKNOWLEDGED'
    assert held._kernel.WaitForSingleObject(held._info.process, 8000) == 0
    assert held.observe().state == 'EXITED' and held.observe().exit_code == 0
    assert held.identity == original
    with pytest.raises(native.NativeLaunchError, match='REQUIRES_OBSERVATION'):
        held.resume_once(replace(observed, resume_state='MAY_HAVE_BEEN_SENT'))
    # This is a native identity/version probe, not output/configuration or full
    # runtime admission; stdout remains exclusively in the original backend.


def test_create_false_has_no_undefined_handle_ownership_and_never_falls_back(resources):
    kernel, security = native._api()
    closed = []

    def failure(*args):
        output = ctypes.cast(args[-1], ctypes.POINTER(native.ProcessInfo)).contents
        output.process = 0x12345678
        output.thread = 0x22345678
        ctypes.set_last_error(1314)
        return False

    wrapped = ApiProxy(kernel, CloseHandle=lambda handle: closed.append(handle))
    with patch.object(
        native,
        '_api',
        return_value=(
            wrapped,
            ApiProxy(security, CreateProcessAsUserW=failure),
        ),
    ):
        with pytest.raises(Exception, match='CREATE_OUTCOME_UNVERIFIED') as caught:
            create(resources)
    assert caught.value.__cause__.code == 'CREATE_PROCESS_AS_USER_UNAVAILABLE'
    assert caught.value.__cause__.native_error == 1314
    assert not resources.roots and not closed
    assert not resources.job.observe_members().process_ids
    assert resources.journal.inspect(scope()).create_state == 'MAY_HAVE_BEEN_SENT'
    with pytest.raises(Exception, match='REQUIRES_OBSERVATION'):
        create(resources)


def test_post_creation_validation_failure_retains_suspended_original_owner(resources):
    with patch.object(
        native.SuspendedControlGit,
        '_verify_created',
        side_effect=native.NativeLaunchError('INJECTED_VALIDATION_UNKNOWN'),
    ):
        with pytest.raises(Exception, match='CREATE_OUTCOME_UNVERIFIED') as caught:
            create(resources)
    held = resources.roots[-1]
    assert caught.value.__cause__.retained_owner is held
    assert held.observe().state == 'RUNNING' and held.resume_state == 'NONE'
    assert held._info.pid in resources.job.observe_members().process_ids
    assert not held._validated
    assert resources.journal.inspect(scope()).create_state == 'MAY_HAVE_BEEN_SENT'


@pytest.mark.parametrize('ack', [0, 2, 0xFFFFFFFF])
def test_unverified_resume_never_decrements_original_thread_again(resources, ack):
    held = create(resources)
    kernel = held._kernel
    calls = []
    held._kernel = ApiProxy(kernel, ResumeThread=lambda handle: calls.append(handle) or ack)
    try:
        with pytest.raises(Exception, match='RESUME_OUTCOME_UNVERIFIED'):
            resume(resources, held)
        assert held.resume_state == 'MAY_HAVE_BEEN_SENT'
        assert resources.journal.inspect(scope()).resume_state == 'MAY_HAVE_BEEN_SENT'
        with pytest.raises(Exception, match='REQUIRES_OBSERVATION'):
            resume(resources, held)
        assert calls == [held._info.thread]
        assert held.observe().state == 'RUNNING'
    finally:
        held._kernel = kernel


def test_stop_closes_original_fence_before_late_resume_and_never_calls_native_resume(resources):
    held = create(resources)
    closed = resources.journal.close_nonce(scope())
    with patch.object(native, '_api', side_effect=AssertionError('No second creation')):
        assert (
            resources.journal.dispatch_create(
                scope(),
                resources.digest,
                lambda: pytest.fail('No late create'),
            )
            == closed
        )
    assert resume(resources, held) == closed
    assert held.resume_state == 'NONE'
    assert held.observe().state == 'RUNNING'
    # Fixture terminates this original Job and waits on the actual held process.


def test_partial_native_close_keeps_failed_original_handle_for_cleanup(resources):
    held = create(resources)
    resources.job.terminate_owned(7)
    assert held._kernel.WaitForSingleObject(held._info.process, 8000) == 0
    assert held.observe().exit_code == 7
    kernel = held._kernel
    target = held._info.thread

    def close(handle):
        if handle == target:
            ctypes.set_last_error(6)
            return False
        return kernel.CloseHandle(handle)

    held._kernel = ApiProxy(kernel, CloseHandle=close)
    try:
        with pytest.raises(native.NativeLaunchError, match='CLOSE_UNVERIFIED') as caught:
            held.close()
        assert caught.value.retained_owner is held
        assert held._info.thread == target and held._info.process is None
    finally:
        held._kernel = kernel
        held.close()
        resources.roots.remove(held)
