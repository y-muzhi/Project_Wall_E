"""Observe and close an original CHECK after its backend lost the dispatch state."""

from time import monotonic

from .check_input_transfer import retire_allocated_check_input
from .guard_control_git_transport import exchange_guard_project_check
from .guard_request_header import build_guard_request_header
from .project_check_result import (
    ProjectCheckOutput,
    ProjectCheckUndispatched,
    project_command_result,
)
from .runtime_launch_journal import LaunchOutcomeUnknown, TestingLaunchScope


class ProjectCheckRecovery:
    def __init__(self, binding, lock, scope, original_epoch, journal):
        binding.assert_backend(lock)
        self._binding, self._lock, self._scope = binding, lock, scope
        self._journal = journal
        self._reference = None
        self._selector = (
            None
            if binding.controller_ref == scope.controller_ref
            else {'controller_ref': scope.controller_ref, 'owner_epoch': original_epoch}
        )
        if self._selector is None and binding.owner_epoch != original_epoch:
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_RECOVERY_CONTROLLER_DIFFERS')

    def _request(self, action, **data):
        if self._selector is not None:
            data['recovery'] = self._selector
        return build_guard_request_header(
            self._binding,
            self._lock,
            action=action,
            operation_id=self._scope.operation_id,
            step_no=self._scope.step_no,
            nonce=self._scope.nonce,
            binding_ref=self._reference,
            action_input=data,
            testing_scope=self._scope if type(self._scope) is TestingLaunchScope else None,
        )

    def _exchange(self, frames, request, deadline, cancelled):
        remaining = min(30000, max(0, int((deadline - monotonic()) * 1000)))
        if remaining <= 0 or cancelled():
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_RECOVERY_INTERRUPTED')
        return exchange_guard_project_check(
            frames, self._binding, self._lock, request, timeout_ms=remaining, cancelled=cancelled
        )

    def _observe(self, frames, action, deadline, cancelled):
        reply = self._exchange(
            frames, self._request('OBSERVE', observed_action=action), deadline, cancelled
        )
        if reply.status != 'OBSERVED':
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_RECOVERY_OWNER_UNAVAILABLE')
        result = reply.result
        if result['action_phase'] != 'UNKNOWN':
            self._journal.verify_observed_intent(action, result)
            if result['action_phase'] == 'ACKNOWLEDGED':
                self._journal.acknowledge_observed(action, result)
        elif self._journal.original_ack(action) is not None:
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_RECOVERY_ACK_MISSING')
        return reply

    def observe_latest(self, frames, *, deadline, cancelled):
        """Read the most recent originally dispatched step without changing the Job."""
        for action in ('RELEASE', 'STOP', 'RESUME', 'CREATE_SUSPENDED', 'PREPARE'):
            if self._journal.intent_saved(action):
                return self._observe(frames, action, deadline, cancelled).result
        return None

    def _close(self, frames, action, deadline, cancelled):
        observed = self._observe(frames, action, deadline, cancelled)
        if observed.result['action_phase'] == 'ACKNOWLEDGED':
            return
        request = self._request(action)
        if self._journal.intent_saved(action):
            self._journal.verify_existing_intent(request)
        else:
            self._journal.before(request)
        reply = self._exchange(frames, request, deadline, cancelled)
        if reply.status != 'ACKNOWLEDGED':
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_RECOVERY_CLOSURE_UNVERIFIED')
        self._journal.acknowledge(request, reply.result)

    def close_undispatched(self, parent, check):
        # The DB process lock serializes this thread against the original
        # writer. Every Guard transfer requires a durable PREPARE intent.
        self._binding.assert_backend(self._lock)
        self._journal.require_no_dispatch()
        retire_allocated_check_input(parent, self._scope, self._journal.read_export())
        self._binding.assert_backend(self._lock)
        self._journal.require_no_dispatch()
        return ProjectCheckUndispatched(self._scope, check)

    def _close_native(self, frames, *, deadline, cancelled, run_kind):
        if not self._journal.intent_saved('PREPARE'):
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_RECOVERY_PREPARE_REQUIRED')
        original = self._observe(frames, 'PREPARE', deadline, cancelled).result
        if (
            original['action_phase'] == 'UNKNOWN'
            or original['binding_ref'] is None
            or (original['preparation'] or {}).get('run_kind') != run_kind
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_RECOVERY_PREPARE_UNVERIFIED')
        self._reference = original['binding_ref']
        if self._journal.intent_saved('CREATE_SUSPENDED'):
            self._observe(frames, 'CREATE_SUSPENDED', deadline, cancelled)
        self._close(frames, 'STOP', deadline, cancelled)
        self._close(frames, 'RELEASE', deadline, cancelled)
        released = self._observe(frames, 'RELEASE', deadline, cancelled)
        if (released.result.get('preparation') or {}).get('run_kind') != run_kind:
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_RECOVERY_KIND_DIFFERS')
        return released

    def close_driver(self, frames, *, deadline, cancelled):
        return self._close_native(
            frames, deadline=deadline, cancelled=cancelled, run_kind='CHECK_DRIVER'
        ).result

    def close_original(self, frames, parent, check, maximum, *, deadline, cancelled):
        released = self._close_native(
            frames, deadline=deadline, cancelled=cancelled, run_kind='TASK'
        )
        output = ProjectCheckOutput(None, None, 'EVIDENCE_INCOMPLETE')
        # Prove the original guard scope closed before deleting a local export.
        project_command_result(released, self._scope, check, output, maximum=maximum)
        retire_allocated_check_input(parent, self._scope, self._journal.read_export())
        return self._journal.complete(check, maximum, released.result, output, None)
