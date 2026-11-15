"""Backend owner for one isolated CHECK_DRIVER with authenticated Guard lifecycle."""

from base64 import b64encode
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from hashlib import sha256
from time import monotonic, sleep

from .browser_driver_control import DriverControlReader, send_control
from .check_case_evidence import CheckEvidenceUnknown, DriverFrameIdentity
from .check_driver_browser import _driver_input, browser_input
from .check_runner_bundle import valid_sha256
from .guard_control_git_transport import exchange_guard_project_check
from .guard_request_header import build_guard_request_header
from .guard_task_launch_protocol import (
    check_driver_pipe_binding,
    check_task_prepare_ack,
    task_launch_fence,
)
from .owned_browser_relay import OwnedBrowserRelay
from .owned_check_http import OwnedHttpUnavailable, OwnedHttpUnknown
from .runtime_launch_journal import LaunchOutcomeUnknown, TestingLaunchScope
from .windows_check_driver_pipe import BackendDriverResultPipe, DriverResultStream
from .windows_check_stdin import CheckStdinWriter
from .windows_guard_pipe_io import PipeIOError
from .windows_pipe_capture import OutputCaptureError
from .windows_stdio import BackendStandardIO, StdioBoundaryError


@dataclass(frozen=True)
class BrowserDriverOutcome:
    status: str
    cases: tuple
    traffic: tuple
    prepared: dict
    created: dict | None
    stopped: dict
    released: dict


def closed_driver_failure(released):
    check = released.get('check')
    if check is None:
        return 'UNKNOWN'
    if check['source_integrity'] == 'CHANGED':
        return 'INPUT_CHANGED'
    observed = check['exit']
    if (
        check['source_integrity'] == 'VERIFIED'
        and observed is not None
        and observed['terminated'] is False
        and type(observed['exit_code']) is int
        and observed['exit_code'] != 0
    ):
        return 'UNAVAILABLE'
    return 'UNKNOWN'


class BrowserDriverDispatch:
    """Keep the original native resources through acknowledgement loss."""

    def __init__(self, binding, lock, scope, check, journal):
        binding.assert_backend(lock)
        if type(scope) is not TestingLaunchScope or scope.controller_ref != binding.controller_ref:
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_DISPATCH_SCOPE_REQUIRED')
        check.require_scope(scope)
        self._binding, self._lock, self.scope = binding, lock, scope
        self._check, self._journal = check, journal
        self._resources = ExitStack()
        self._streams = self._result_pipe = None
        self._reference = self._prepared = self._created = self._resumed = None
        self._stopped = self._released = None

    def _send(self, frames, action, data, *, deadline, cancelled):
        self._binding.assert_backend(self._lock)
        timeout = min(90000, int((deadline - monotonic()) * 1000))
        if timeout <= 0 or cancelled():
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_DISPATCH_INTERRUPTED')
        scope = self.scope
        request = build_guard_request_header(
            self._binding,
            self._lock,
            action=action,
            operation_id=scope.operation_id,
            step_no=scope.step_no,
            nonce=scope.nonce,
            binding_ref=None if action == 'PREPARE' else self._reference,
            action_input=data,
            testing_scope=scope,
        )
        if action != 'OBSERVE':
            self._journal.before(request)
        if action == 'PREPARE':
            self._streams.begin_handoff()
            self._result_pipe.offer()
        reply = exchange_guard_project_check(
            frames, self._binding, self._lock, request, timeout_ms=timeout, cancelled=cancelled
        )
        expected = 'OBSERVED' if action == 'OBSERVE' else 'ACKNOWLEDGED'
        if reply.status != expected:
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_GUARD_REPLY_UNVERIFIED')
        result = reply.result
        kind = result.get('run_kind')
        if action == 'OBSERVE':
            kind = (result.get('preparation') or {}).get('run_kind')
        elif action != 'PREPARE':
            kind = (result.get('native') or {}).get('run_kind')
        if kind != 'CHECK_DRIVER':
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_GUARD_RUN_KIND_DIFFERS')
        if action != 'OBSERVE':
            self._journal.acknowledge(request, result)
        return result

    def _observe(self, frames, action, *, deadline, cancelled):
        return self._send(
            frames,
            'OBSERVE',
            {'observed_action': action},
            deadline=deadline,
            cancelled=cancelled,
        )

    def _accept_prepare(self, result):
        self._reference = result['binding_ref']
        self._streams.acknowledge_copy(
            check_task_prepare_ack(self.scope, self._reference, result, run_kind='CHECK_DRIVER')
        )
        self._result_pipe.acknowledge(
            check_driver_pipe_binding(result['result_pipe_binding'], self.scope)
        )
        self._prepared = result

    def start(
        self,
        frames,
        *,
        runner_ref,
        runner_sha256,
        case_sha256,
        processes,
        memory,
        deadline,
        cancelled,
    ):
        if self._streams is not None or not all(
            valid_sha256(value) for value in (runner_sha256, case_sha256)
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_DISPATCH_ALREADY_STARTED_OR_INVALID')
        self._streams = self._resources.enter_context(
            BackendStandardIO(self.scope, bounded_input=True)
        )
        self._result_pipe = self._resources.enter_context(BackendDriverResultPipe(self.scope))
        stdio, result = self._streams.descriptor(), self._result_pipe.descriptor()
        self._accept_prepare(
            self._send(
                frames,
                'PREPARE',
                {
                    'run_kind': 'CHECK_DRIVER',
                    'execution_purpose': 'CHECK',
                    'check_input': asdict(self._check),
                    'runner_ref': runner_ref,
                    'runner_manifest_sha256': runner_sha256,
                    'case_pack_sha256': case_sha256,
                    'active_process_limit': processes,
                    'job_memory_limit_bytes': memory,
                    'network': {key: [] for key in ('model', 'forward', 'control', 'application')},
                    'stdio': {
                        key: getattr(stdio, key)
                        for key in ('io_nonce', 'stdin_handle', 'stdout_handle', 'stderr_handle')
                    },
                    'result_pipe': {'nonce': result.nonce, 'write_handle': result.write_handle},
                },
                deadline=deadline,
                cancelled=cancelled,
            )
        )
        self._created = self._send(
            frames,
            'CREATE_SUSPENDED',
            {'launch_input_sha256': self._prepared['launch_input_sha256']},
            deadline=deadline,
            cancelled=cancelled,
        )
        self._streams.release_child_copies()
        self._resumed = self._send(
            frames,
            'RESUME',
            {'receipt_sha256': self._created['native']['receipt_sha256']},
            deadline=deadline,
            cancelled=cancelled,
        )
        self._require_original_root(self._resumed['native'])

    def _require_original_root(self, native):
        original = self._created['native']
        if (
            native is None
            or native['run_kind'] != 'CHECK_DRIVER'
            or native['process_identity'] != original['process_identity']
            or native['receipt_sha256'] != original['receipt_sha256']
            or native['resource_ref'] != original['resource_ref']
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_DRIVER_ROOT_DIFFERS')

    def _cleanup_action(self, frames, action, *, deadline, cancelled):
        existing = self._journal.original_ack(action)
        if existing is not None:
            return existing
        if not self._journal.intent_saved(action):
            return self._send(frames, action, {}, deadline=deadline, cancelled=cancelled)
        observed = self._observe(frames, action, deadline=deadline, cancelled=cancelled)
        if observed['action_phase'] != 'ACKNOWLEDGED':
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_CLEANUP_REQUIRES_OBSERVATION')
        self._journal.acknowledge_observed(action, observed)
        return observed['acknowledgement']

    def release(self, frames, *, deadline, cancelled):
        if self._released is not None:
            return self._released
        if not self._journal.intent_saved('PREPARE'):
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_RELEASE_WITHOUT_PREPARE')
        if self._reference is None:
            observed = self._observe(frames, 'PREPARE', deadline=deadline, cancelled=cancelled)
            if observed['action_phase'] == 'ACKNOWLEDGED':
                self._journal.acknowledge_observed('PREPARE', observed)
                self._accept_prepare(observed['acknowledgement'])
            elif observed['action_phase'] == 'MAY_HAVE_BEEN_SENT':
                self._reference = observed['binding_ref']
            else:
                raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_PREPARE_REQUIRES_OBSERVATION')
        self._stopped = self._cleanup_action(frames, 'STOP', deadline=deadline, cancelled=cancelled)
        fence = task_launch_fence(self._stopped['native']['fence'], self.scope)
        self._streams.acknowledge_closed_scope(fence)
        self._result_pipe.close_offer(fence)
        released = self._cleanup_action(frames, 'RELEASE', deadline=deadline, cancelled=cancelled)
        observed = self._observe(frames, 'RELEASE', deadline=deadline, cancelled=cancelled)
        if (
            observed['acknowledgement'] != released
            or observed['preparation']['cleanup_state'] != 'COMPLETE'
            or observed['job_activity']
            != {'assigned_count': 0, 'complete': True, 'process_ids': []}
            or self._stopped['native'] != released['native']
            or released['native'] != observed['resource']
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_CLEANUP_UNVERIFIED')
        if self._created is not None:
            self._require_original_root(released['native'])
        self._released = released
        return released

    def collect(self, frames, payload, pack, identity, relay, *, maximum, deadline, cancelled):
        if (
            self._resumed is None
            or type(relay) is not OwnedBrowserRelay
            or relay.scope != self.scope
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_RELAY_REQUIRED')
        reader = self._resources.enter_context(
            DriverResultStream(self._result_pipe, identity, pack, max_bytes=maximum)
        )
        with (
            DriverControlReader(self._streams, maximum=maximum) as control,
            CheckStdinWriter(self._streams) as writer,
        ):
            send_control(writer, payload, deadline=deadline, cancelled=cancelled)

            def active():
                if cancelled() or monotonic() >= deadline:
                    raise CheckEvidenceUnknown('ORIGINAL_BROWSER_CASE_INTERRUPTED')

            while True:
                active()
                for request in control.poll():
                    reply = relay.send(request, deadline=deadline, active=active)
                    send_control(
                        writer,
                        {
                            'seq': request['seq'],
                            'status': reply.status,
                            'headers': dict(reply.headers),
                            'body': b64encode(reply.body).decode('ascii'),
                        },
                        deadline=deadline,
                        cancelled=cancelled,
                    )
                if reader.poll() and control.complete:
                    observed = self._observe(
                        frames, 'RESUME', deadline=deadline, cancelled=cancelled
                    )
                    self._require_original_root(observed['resource'])
                    if observed['resource']['process_state'] == 'EXITED':
                        return reader
                sleep(0.005)

    def run(
        self,
        frames,
        raw_pack,
        basis,
        limits,
        relay,
        *,
        runner_ref,
        runner_sha256,
        processes,
        memory,
        maximum,
        deadline,
        cleanup_seconds,
        cancelled,
        execution_seconds=None,
    ):
        if type(relay) is not OwnedBrowserRelay or relay.scope != self.scope:
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_RELAY_REQUIRED')
        identity = DriverFrameIdentity(
            self._check.verification_id, self._check.item_id, self.scope.nonce
        )
        digest = sha256(raw_pack).hexdigest()
        payload = browser_input(identity, raw_pack, basis, limits, relay.origins)
        _, pack, _ = _driver_input(payload, digest)
        reader = None
        status = 'UNKNOWN'
        try:
            self.start(
                frames,
                runner_ref=runner_ref,
                runner_sha256=runner_sha256,
                case_sha256=digest,
                processes=processes,
                memory=memory,
                deadline=deadline,
                cancelled=cancelled,
            )
            reader = self.collect(
                frames,
                payload,
                pack,
                identity,
                relay,
                maximum=maximum,
                deadline=deadline
                if execution_seconds is None
                else min(deadline, monotonic() + execution_seconds),
                cancelled=cancelled,
            )
        except OwnedHttpUnavailable:
            status = 'UNAVAILABLE'
        except (CheckEvidenceUnknown, OwnedHttpUnknown, PipeIOError, OutputCaptureError):
            status = 'CANCELLED' if cancelled() else 'UNKNOWN'
        except (LaunchOutcomeUnknown, StdioBoundaryError, OSError) as error:
            if not self._journal.intent_saved('PREPARE'):
                self.close_before_original_dispatch()
            else:
                error.retained_owner = self
            raise
        try:
            released = self.release(
                frames, deadline=monotonic() + cleanup_seconds, cancelled=lambda: False
            )
            cases = ()
            original = released.get('check')
            if status == 'UNKNOWN':
                status = closed_driver_failure(released)
            if reader is not None and original is not None:
                exit = original['exit']
                if (
                    original['source_integrity'] == 'VERIFIED'
                    and exit is not None
                    and not exit['terminated']
                ):
                    try:
                        cases = reader.finish(
                            authenticated_root=True, original_exit_code=exit['exit_code']
                        )
                    except CheckEvidenceUnknown:
                        pass
                    else:
                        status = (
                            'FAILED'
                            if any(case['result'] == 'FAILED' for case in cases)
                            else 'PASSED'
                        )
            return BrowserDriverOutcome(
                status, cases, relay.traffic, self._prepared, self._created, self._stopped, released
            )
        except (LaunchOutcomeUnknown, StdioBoundaryError, OSError) as error:
            error.retained_owner = self
            raise
        finally:
            if self._released is not None:
                self._resources.close()

    def close_before_original_dispatch(self):
        if self._journal.intent_saved('PREPARE') or self._reference is not None:
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_CLEANUP_REQUIRED')
        self._resources.close()

    def close_after_original_release(self):
        if self._released is None:
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_CLEANUP_REQUIRED')
        self._resources.close()
