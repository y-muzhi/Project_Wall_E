"""Execute and close one admitted browser case and its original applications."""

from time import monotonic

from backend.app.infrastructure.browser_driver_dispatch import (
    BrowserDriverDispatch,
    closed_driver_failure,
)
from backend.app.infrastructure.check_case_pack import CasePackLimits
from backend.app.infrastructure.owned_browser_relay import BrowserRoute, OwnedBrowserRelay
from backend.app.infrastructure.owned_check_http import OwnedHttpUnavailable, allocate_http_endpoint
from backend.app.infrastructure.project_check_dispatch import ProjectCheckDispatch
from backend.app.infrastructure.project_check_recovery import ProjectCheckRecovery
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown

from .browser_journal import BrowserCaseJournal


class BrowserCaseRun:
    def __init__(self, binding, lock, parent, evidence, case, maximum):
        self._binding, self._lock, self._parent = binding, lock, parent
        self._evidence, self._case, self._maximum = evidence, case, maximum
        self._result = BrowserCaseJournal(evidence(case), case)
        self._driver = None
        self._applications = {}

    def _recovery(self, member):
        return ProjectCheckRecovery(
            self._binding, self._lock, member.scope, member.epoch, self._evidence(member)
        )

    def was_dispatched(self):
        return any(
            self._evidence(member).intent_saved('PREPARE')
            for member in (self._case, *self._case.applications)
        )

    def run(
        self,
        frames,
        selected,
        profile,
        candidate,
        *,
        limits,
        git_limits,
        deadline,
        active,
        cancelled,
        on_start,
        on_prepared,
        cleanup_seconds,
    ):
        case = self._case
        routes = []
        outcome = None
        problem = 'UNKNOWN'
        try:
            for original, admission in zip(
                case.applications, selected.admission.applications, strict=True
            ):
                on_start(original)
                service = admission.service
                dispatch = ProjectCheckDispatch(
                    self._binding,
                    self._lock,
                    original.scope,
                    case.check,
                    definition=service.command,
                    runner_ref=service.runner_ref,
                    active_process_limit=service.active_process_limit,
                    job_memory_limit_bytes=service.job_memory_limit_bytes,
                    journal=self._evidence(original),
                )
                self._applications[original.scope] = dispatch
                endpoint = allocate_http_endpoint(original.fixed['endpoint_ref'])
                app = dispatch.start_service(
                    frames,
                    self._parent,
                    candidate,
                    endpoint,
                    limits=limits,
                    git_limits=git_limits,
                    max_output_bytes=self._maximum,
                    deadline=deadline,
                    active=active,
                    cancelled=cancelled,
                    fixture_sha256=service.fixture_sha256,
                )
                routes.append(
                    BrowserRoute(admission.origin_ref, admission.prefix, admission.role, app)
                )
            on_prepared()
            relay = OwnedBrowserRelay(
                case.scope,
                tuple(routes),
                request_limit=selected.request_limit,
                output_limit=self._maximum,
                count_limit=128,
                before_send=self._result.intent,
            )
            self._driver = BrowserDriverDispatch(
                self._binding, self._lock, case.scope, case.check, self._evidence(case)
            )
            admission = selected.admission
            policy = profile['limits']
            pack_limits = CasePackLimits(
                1,
                min(256, policy['max_case_steps']),
                min(1024 * 1024, policy['max_case_payload_bytes']),
                selected.case.timeout_seconds,
            )
            outcome = self._driver.run(
                frames,
                selected.raw,
                selected.pack.basis_refs,
                pack_limits,
                relay,
                runner_ref=admission.runner_ref,
                runner_sha256=admission.runner_manifest_sha256,
                processes=admission.active_process_limit,
                memory=admission.job_memory_limit_bytes,
                maximum=self._maximum,
                deadline=deadline,
                cleanup_seconds=cleanup_seconds,
                cancelled=cancelled,
                execution_seconds=selected.timeout_seconds,
            )
        except OwnedHttpUnavailable:
            problem = 'UNAVAILABLE'
        if outcome is None and cancelled():
            problem = 'CANCELLED'
        result = (
            self._result.save(problem)
            if outcome is None
            else self._result.save(outcome.status, outcome.cases, outcome.traffic)
        )
        return result, self._close_applications(
            frames, deadline=monotonic() + cleanup_seconds, cancelled=lambda: False
        )

    def _close_applications(self, frames, *, deadline, cancelled):
        completed = []
        for member in reversed(self._case.applications):
            evidence = self._evidence(member)
            recovery = self._recovery(member)
            dispatch = self._applications.get(member.scope)
            complete = evidence.read_completion(self._case.check, self._maximum)
            if complete is None:
                if not evidence.intent_saved('PREPARE'):
                    complete = recovery.close_undispatched(self._parent, self._case.check)
                elif dispatch is not None:
                    complete = dispatch.reconcile(
                        frames, maximum=self._maximum, deadline=deadline, cancelled=cancelled
                    )
                else:
                    complete = recovery.close_original(
                        frames,
                        self._parent,
                        self._case.check,
                        self._maximum,
                        deadline=deadline,
                        cancelled=cancelled,
                    )
            self._applications.pop(member.scope, None)
            completed.append(complete)
        return tuple(reversed(completed))

    def close_undispatched(self, reason):
        if self.was_dispatched():
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_CLOSURE_REQUIRED')
        result = self._result.read() or self._result.save(
            'CANCELLED' if reason == 'CANCELLED' else 'UNKNOWN'
        )
        return result, self._close_applications(None, deadline=0, cancelled=lambda: False)

    def recover(self, frames, *, deadline, cancelled):
        result = self._result.read()
        if result is None:
            status = 'UNKNOWN'
            if self._evidence(self._case).intent_saved('PREPARE'):
                if self._driver is None:
                    released = self._recovery(self._case).close_driver(
                        frames, deadline=deadline, cancelled=cancelled
                    )
                else:
                    released = self._driver.release(frames, deadline=deadline, cancelled=cancelled)
                    self._driver.close_after_original_release()
                status = closed_driver_failure(released)
            elif self._driver is not None:
                self._driver.close_before_original_dispatch()
            result = self._result.save(status)
        return result, self._close_applications(frames, deadline=deadline, cancelled=cancelled)
