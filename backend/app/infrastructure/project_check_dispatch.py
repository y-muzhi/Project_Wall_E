"""Run one original project command over the authenticated Guard boundary."""

from contextlib import ExitStack
from dataclasses import asdict
from time import monotonic, sleep

from .check_input_transfer import SnapshotCheckSource, export_check_input, retire_check_input_export
from .check_runner_bundle import valid_sha256
from .content_package_publish import PublishedCandidate
from .guard_control_git_transport import exchange_guard_project_check
from .guard_request_header import build_guard_request_header
from .guard_task_launch_protocol import check_task_prepare_ack, task_launch_fence
from .owned_browser_relay import BrowserApplication
from .owned_check_http import (
    OwnedHttpEndpoint,
    OwnedHttpUnavailable,
    OwnedHttpUnknown,
    run_owned_http_case,
)
from .project_check_result import (
    ProjectCheckOutput,
    display_project_check_output,
    project_command_result,
    summarize_project_check_output,
)
from .runtime_launch_journal import LaunchOutcomeUnknown, TestingLaunchScope
from .windows_check_stdin import MAX_STDIN_BYTES, CheckStdinWriter
from .windows_guard_pipe_io import PipeIOError
from .windows_pipe_capture import BoundedOutputCapture
from .windows_process import NativeProcessIdentity
from .windows_stdio import BackendStandardIO
from .windows_task_directories import ProjectCheckInput


class ProjectCheckDispatch:
    """Persist intent through the caller before every mutation; observe unknowns."""

    def __init__(
        self,
        binding,
        lock,
        scope,
        check,
        *,
        definition,
        runner_ref,
        active_process_limit,
        job_memory_limit_bytes,
        journal,
    ):
        binding.assert_backend(lock)
        if scope.controller_ref != binding.controller_ref or scope.step_no not in (3, 4):
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_DISPATCH_SCOPE_DIFFERS')
        check.require_scope(scope)
        self._binding, self._lock, self._scope, self._check = binding, lock, scope, check
        self._definition, self._runner = definition, runner_ref
        self._process_limit, self._memory_limit = active_process_limit, job_memory_limit_bytes
        self._journal = journal
        self._resources = ExitStack()
        self._streams = self._capsule = self._output = self._export_parent = None
        self._reference = self._io = self._prepared = self._created = None
        self._stopped = self._released = None
        self._started = False
        self._complete = False
        self._interruption = self._terminal = None
        self._input_complete = True

    def _send(self, frames, action, data, *, deadline, cancelled):
        self._binding.assert_backend(self._lock)
        remaining = min(30000, max(0, int((deadline - monotonic()) * 1000)))
        if remaining <= 0 or cancelled():
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_DISPATCH_INTERRUPTED')
        request = build_guard_request_header(
            self._binding,
            self._lock,
            action=action,
            operation_id=self._scope.operation_id,
            step_no=self._scope.step_no,
            nonce=self._scope.nonce,
            binding_ref=None if action == 'PREPARE' else self._reference,
            action_input=data,
            testing_scope=self._scope if type(self._scope) is TestingLaunchScope else None,
        )
        if action != 'OBSERVE':
            self._journal.before(request)
        if action == 'PREPARE':
            self._streams.begin_handoff()
            self._capsule.mark_offered()
        reply = exchange_guard_project_check(
            frames, self._binding, self._lock, request, timeout_ms=remaining, cancelled=cancelled
        )
        expected = 'OBSERVED' if action == 'OBSERVE' else 'ACKNOWLEDGED'
        if reply.status != expected:
            failure = LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_REPLY_UNVERIFIED')
            failure.guard_action = action
            raise failure
        if action != 'OBSERVE':
            self._journal.acknowledge(request, reply.result)
        return reply

    def _observe(self, frames, action, *, deadline, cancelled):
        return self._send(
            frames, 'OBSERVE', {'observed_action': action}, deadline=deadline, cancelled=cancelled
        )

    def _cleanup_action(self, frames, action, *, deadline, cancelled):
        if self._journal.intent_saved(action):
            observed = self._observe(frames, action, deadline=deadline, cancelled=cancelled).result
            if observed['action_phase'] != 'ACKNOWLEDGED':
                raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_CLEANUP_REQUIRES_OBSERVATION')
            self._journal.acknowledge_observed(action, observed)
            return observed['acknowledgement']
        return self._send(frames, action, {}, deadline=deadline, cancelled=cancelled).result

    def _acknowledge_prepare(self, result):
        self._reference = result['binding_ref']
        self._streams.acknowledge_copy(check_task_prepare_ack(self._scope, self._reference, result))
        self._prepared = result
        if self._capsule is not None:
            self._capsule.mark_received(self._scope, self._capsule.descriptor.sha256)

    def _prepare_data(self, capsule, stdio, limits, http_endpoint, fixture_sha256):
        application = (
            [] if http_endpoint is None else [{'address': '127.0.0.1', 'port': http_endpoint.port}]
        )
        descriptor = asdict(capsule.descriptor)
        return {
            'run_kind': 'TASK',
            'execution_purpose': 'CHECK',
            'check_input': asdict(self._check),
            'project_command': {
                'command_id': self._definition.command_id,
                'definition_sha256': self._definition.definition_sha256,
                'active_process_limit': self._process_limit,
                'job_memory_limit_bytes': self._memory_limit,
            },
            'runner_ref': self._runner,
            **({'fixture_sha256': fixture_sha256} if fixture_sha256 is not None else {}),
            'network': {'model': [], 'forward': [], 'control': [], 'application': application},
            'capsule': {key: descriptor[key] for key in ('file', 'sha256', 'byte_count', 'handle')},
            'limits': asdict(limits),
            'stdio': {
                key: getattr(stdio, key)
                for key in ('io_nonce', 'stdin_handle', 'stdout_handle', 'stderr_handle')
            },
        }

    def run(
        self,
        frames,
        parent,
        candidate,
        *,
        limits,
        git_limits,
        max_output_bytes,
        deadline,
        cleanup_seconds,
        active,
        cancelled,
        on_restored=None,
        on_prepared=None,
        stdin=b'',
        http=None,
        fixture_sha256=None,
    ):
        if (
            type(stdin) is not bytes
            or len(stdin) > MAX_STDIN_BYTES
            or (stdin and type(self._scope) is not TestingLaunchScope)
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_INPUT_BYTES_DIFFERS')
        if (
            (http is not None) != (self._definition.purpose == 'SERVICE')
            or http is not None
            and (type(self._scope) is not TestingLaunchScope or stdin)
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_MODE_DIFFERS')
        if fixture_sha256 is not None and (
            type(self._scope) is not TestingLaunchScope or not valid_sha256(fixture_sha256)
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_TESTING_FIXTURE_DIFFERS')
        self._start(
            frames,
            parent,
            candidate,
            limits=limits,
            git_limits=git_limits,
            max_output_bytes=max_output_bytes,
            deadline=deadline,
            active=active,
            cancelled=cancelled,
            on_restored=on_restored,
            on_prepared=on_prepared,
            stdin=stdin,
            endpoint=None if http is None else http[1],
            fixture_sha256=fixture_sha256,
        )
        try:
            if http is not None:
                self._run_http_case(frames, http, max_output_bytes, deadline, cancelled)
            elif self._input_complete:
                self._wait_exit(frames, deadline, cancelled)
            return self.reconcile(
                frames,
                maximum=max_output_bytes,
                deadline=monotonic() + cleanup_seconds,
                cancelled=lambda: False,
            )
        except BaseException as error:
            if self._journal.intent_saved('PREPARE') or self._reference is not None:
                error.retained_owner = self
            else:
                self._resources.close()
            raise

    def start_service(
        self,
        frames,
        parent,
        candidate,
        endpoint,
        *,
        limits,
        git_limits,
        max_output_bytes,
        deadline,
        active,
        cancelled,
        fixture_sha256=None,
    ):
        if (
            self._definition.purpose != 'SERVICE'
            or type(endpoint) is not OwnedHttpEndpoint
            or type(self._scope) is not TestingLaunchScope
            or fixture_sha256 is not None
            and not valid_sha256(fixture_sha256)
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_APPLICATION_START_REQUIRED')
        self._start(
            frames,
            parent,
            candidate,
            limits=limits,
            git_limits=git_limits,
            max_output_bytes=max_output_bytes,
            deadline=deadline,
            active=active,
            cancelled=cancelled,
            on_restored=None,
            on_prepared=None,
            stdin=b'',
            endpoint=endpoint,
            fixture_sha256=fixture_sha256,
        )
        created = self._created['native']
        return BrowserApplication(
            self._scope,
            endpoint,
            NativeProcessIdentity(**created['process_identity']),
            created['receipt_sha256'],
            lambda: self._verify_service_job(frames, deadline, cancelled),
        )

    def _start(
        self,
        frames,
        parent,
        candidate,
        *,
        limits,
        git_limits,
        max_output_bytes,
        deadline,
        active,
        cancelled,
        on_restored,
        on_prepared,
        stdin,
        endpoint,
        fixture_sha256,
    ):
        if self._started:
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_ALREADY_DISPATCHED')
        self._input_complete = not stdin
        if type(candidate) is SnapshotCheckSource:
            matches = candidate.target == self._check
        elif type(candidate) is PublishedCandidate and type(self._check) is ProjectCheckInput:
            seal = candidate.seal
            matches = (
                seal.binding.candidate_id == self._check.candidate_id
                and seal.manifest_sha256 == self._check.manifest_sha256
            )
        else:
            matches = False
        if not matches:
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_TARGET_DIFFERS')
        self._started = True
        self._export_parent = parent

        def copying():
            if cancelled() or monotonic() >= deadline or active() is not None:
                raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_COPY_FENCED')

        try:
            self._streams = self._resources.enter_context(
                BackendStandardIO(self._scope, bounded_input=bool(stdin))
            )
            with export_check_input(
                parent,
                self._scope,
                candidate,
                limits=limits,
                git_limits=git_limits,
                active=copying,
                on_allocate=self._journal.record_export,
            ) as capsule:
                self._capsule = capsule
                if on_restored is not None:
                    on_restored(capsule.descriptor)
                self._io = self._streams.descriptor()
                data = self._prepare_data(capsule, self._io, limits, endpoint, fixture_sha256)
                copying()
                prepared = self._send(
                    frames, 'PREPARE', data, deadline=deadline, cancelled=cancelled
                ).result
                self._acknowledge_prepare(prepared)
            self._capsule = None
            if on_prepared is not None:
                on_prepared()
            copying()
            self._created = self._send(
                frames,
                'CREATE_SUSPENDED',
                {'launch_input_sha256': prepared['launch_input_sha256']},
                deadline=deadline,
                cancelled=cancelled,
            ).result
            self._streams.release_child_copies()
            if not stdin:
                self._streams.close_input()
            self._output = self._resources.enter_context(
                BoundedOutputCapture(
                    self._streams, scope=self._scope, max_output_bytes=max_output_bytes
                )
            )
            copying()
            self._send(
                frames,
                'RESUME',
                {'receipt_sha256': self._created['native']['receipt_sha256']},
                deadline=deadline,
                cancelled=cancelled,
            )
            if stdin:
                self._deliver_input(stdin, deadline, cancelled)
        except BaseException as error:
            if self._journal.intent_saved('PREPARE') or self._reference is not None:
                error.retained_owner = self
            else:
                self._resources.close()
            raise

    def _run_http_case(self, frames, http, maximum, deadline, cancelled):
        case, endpoint, request_limit = http
        created = self._created['native']
        identity = NativeProcessIdentity(**created['process_identity'])
        native_receipt = created['receipt_sha256']
        journal = self._journal.http()
        intents = []

        def active():
            if cancelled():
                self._interruption = 'CANCELLED'
                raise LaunchOutcomeUnknown('ORIGINAL_TESTING_HTTP_FENCED')
            progress = self._output.poll()
            if progress.limit_exceeded or progress.failure_reason is not None:
                raise LaunchOutcomeUnknown('ORIGINAL_TESTING_HTTP_PROJECT_OUTPUT_UNVERIFIED')

        def before_send(step_id, request_sha256):
            journal.intent(len(intents) + 1, step_id, request_sha256, native_receipt)
            intents.append(step_id)

        outcome = None
        try:
            outcome = run_owned_http_case(
                case,
                endpoint,
                identity,
                output_limit=maximum,
                request_limit=request_limit,
                deadline=deadline,
                active=active,
                verify_job=lambda: self._verify_service_job(frames, deadline, cancelled),
                before_send=before_send,
            )
        except OwnedHttpUnavailable:
            status = 'UNAVAILABLE'
        except OwnedHttpUnknown:
            status = 'UNKNOWN'
        else:
            status = 'OBSERVED'
        journal.finish(native_receipt, status, tuple(intents), outcome)

    def _verify_service_job(self, frames, deadline, cancelled):
        progress = self._output.poll()
        if progress.limit_exceeded or progress.failure_reason is not None:
            raise LaunchOutcomeUnknown('ORIGINAL_TESTING_HTTP_PROJECT_OUTPUT_UNVERIFIED')
        created = self._created['native']
        observed = self._observe(frames, 'RESUME', deadline=deadline, cancelled=cancelled).result
        resource, activity = observed['resource'], observed['job_activity']
        if (
            observed['action_phase'] != 'ACKNOWLEDGED'
            or resource is None
            or resource['process_state'] != 'RUNNING'
            or resource['resource_ref'] != created['resource_ref']
            or resource['receipt_sha256'] != created['receipt_sha256']
            or resource['process_identity'] != created['process_identity']
            or resource['fence']['stop_closed']
            or resource['fence']['resume_state'] != 'ACKNOWLEDGED'
            or activity is None
            or not activity['complete']
            or created['process_identity']['pid'] not in activity['process_ids']
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_TESTING_HTTP_JOB_UNVERIFIED')

    def _deliver_input(self, raw, deadline, cancelled):
        def interrupted():
            if cancelled():
                self._interruption = 'CANCELLED'
                return True
            if monotonic() >= deadline:
                self._interruption = 'TIMEOUT'
                return True
            progress = self._output.poll()
            return progress.limit_exceeded or progress.failure_reason is not None

        writer = self._resources.enter_context(CheckStdinWriter(self._streams))
        try:
            writer.send(raw, deadline=deadline, cancelled=interrupted)
            self._input_complete = True
        except PipeIOError as error:
            if getattr(error, 'retained_owner', None) is not None:
                raise
            interrupted()
        writer.close()
        self._streams.close_input()

    def _wait_exit(self, frames, deadline, cancelled):
        while True:
            if cancelled():
                self._interruption = 'CANCELLED'
                return
            if monotonic() >= deadline:
                self._interruption = 'TIMEOUT'
                return
            progress = self._output.poll()
            if progress.limit_exceeded or progress.failure_reason is not None:
                return
            if progress.complete:
                observed = self._observe(
                    frames, 'RESUME', deadline=deadline, cancelled=cancelled
                ).result
                resource = observed.get('resource')
                if resource is None or resource['process_state'] not in ('RUNNING', 'EXITED'):
                    raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_EXIT_UNVERIFIED')
                if resource['process_state'] == 'EXITED':
                    return
            sleep(0.005)

    def reconcile(self, frames, *, maximum, deadline, cancelled):
        """Only observe original launch effects and stop/release the original scope."""
        if self._terminal is not None:
            return self._save_completion(maximum)
        if self._complete or not self._journal.intent_saved('PREPARE') or self._streams is None:
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_RECONCILIATION_SCOPE_REQUIRED')
        if self._reference is None:
            observed = self._observe(
                frames, 'PREPARE', deadline=deadline, cancelled=cancelled
            ).result
            if observed['action_phase'] == 'ACKNOWLEDGED':
                self._journal.acknowledge_observed('PREPARE', observed)
                self._acknowledge_prepare(observed['acknowledgement'])
            elif observed['action_phase'] == 'MAY_HAVE_BEEN_SENT':
                self._reference = observed['binding_ref']
            else:
                raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_PREPARE_UNVERIFIED')
        if self._created is None and self._journal.intent_saved('CREATE_SUSPENDED'):
            creation = self._observe(
                frames, 'CREATE_SUSPENDED', deadline=deadline, cancelled=cancelled
            ).result
            if creation['action_phase'] == 'ACKNOWLEDGED':
                self._journal.acknowledge_observed('CREATE_SUSPENDED', creation)
                self._created = creation['acknowledgement']
        self._stopped = self._cleanup_action(frames, 'STOP', deadline=deadline, cancelled=cancelled)
        fence = task_launch_fence(self._stopped['native']['fence'], self._scope)
        self._streams.acknowledge_closed_scope(fence)
        self._released = self._cleanup_action(
            frames, 'RELEASE', deadline=deadline, cancelled=cancelled
        )
        observed = self._observe(frames, 'RELEASE', deadline=deadline, cancelled=cancelled)
        if observed.result['acknowledgement'] != self._released:
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_RELEASE_DIFFERS')
        if self._output is not None:
            self._output.poll()
        captured = None if self._output is None else self._output.snapshot()
        output = summarize_project_check_output(
            captured,
            scope=self._scope,
            io_nonce=self._io.io_nonce,
            maximum=maximum,
        )
        if not self._input_complete and output.problem != 'OUTPUT_LIMIT':
            output = ProjectCheckOutput(None, None, 'EVIDENCE_INCOMPLETE')
        if self._capsule is not None:
            result = project_command_result(
                observed,
                self._scope,
                self._check,
                output,
                maximum=maximum,
                interruption=self._interruption,
            )
            retire_check_input_export(self._export_parent, self._capsule.descriptor, result)
            self._capsule = None
        display = (
            display_project_check_output(
                captured, output, scope=self._scope, io_nonce=self._io.io_nonce, maximum=maximum
            )
            if self._released['native']['process_state'] == 'EXITED'
            else ()
        )
        self._resources.close()
        self._terminal = (observed.result, output, self._interruption, display)
        return self._save_completion(maximum)

    def _save_completion(self, maximum):
        completion = self._journal.complete(self._check, maximum, *self._terminal)
        self._terminal = None
        self._complete = True
        return completion
