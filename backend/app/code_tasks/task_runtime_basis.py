"""Backend side of the original Guard TASK basis transfer."""

from dataclasses import asdict

from backend.app.infrastructure.guard_action_records import mutation_input_sha256
from backend.app.infrastructure.guard_control_git_transport import exchange_guard_task_files
from backend.app.infrastructure.guard_pipe_frames import _remaining
from backend.app.infrastructure.guard_request_header import (
    GuardRequestHeader,
    build_guard_request_header,
)
from backend.app.infrastructure.guard_task_basis_protocol import (
    BASIS_PLAN_PART_MEMBERS,
    BASIS_STAGE_STATUS,
    basis_file_identity,
    basis_plan_header,
    basis_plan_members,
)
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown
from backend.app.infrastructure.windows_guard_pipe_io import _deadline
from backend.app.infrastructure.windows_task_basis import (
    BasisCopyReceipt,
    BasisWriteOffer,
    TaskBasisTransferError,
)
from backend.app.infrastructure.windows_task_basis_group import (
    BasisGroupEvidence,
    basis_group_evidence,
)

from .task_basis_package import runtime_basis_plan, verify_runtime_basis_copy, write_runtime_basis


class TaskBasisCompletionUnknown(TaskBasisTransferError):
    def __init__(self, expected):
        super().__init__('ORIGINAL_BASIS_STAGE_COMPLETION_UNKNOWN')
        self.expected = expected


class RuntimeBasisTransfer:
    def __init__(self, frames, controller, process_lock, original, binding_ref):
        if (
            type(original) is not GuardRequestHeader
            or original.action != 'PREPARE'
            or original.recovery is not None
            or original.scope.step_no != 4
            or original.input.get('run_kind') != 'TASK'
            or original.input.get('reserve_files') is not True
        ):
            raise TaskBasisTransferError('ORIGINAL_TASK_FILE_RESERVATION_INPUT_REQUIRED')
        self._frames, self._controller, self._lock = frames, controller, process_lock
        self._scope, self._binding_ref = original.scope, binding_ref
        self._prepare_sha256 = mutation_input_sha256(original)
        self._plan_sha256 = original.input.get('basis_plan_sha256')

    def _stage(self, stage, payload, *, deadline, cancelled):
        scope = self._scope
        request = build_guard_request_header(
            self._controller,
            self._lock,
            action='PREPARE',
            operation_id=scope.operation_id,
            step_no=scope.step_no,
            nonce=scope.nonce,
            binding_ref=None,
            action_input={
                'run_kind': 'TASK',
                'basis_stage': stage,
                'basis_binding_ref': self._binding_ref,
                'prepare_input_sha256': self._prepare_sha256,
                'payload': payload,
            },
        )
        if request.scope != scope:
            raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_SCOPE_DIFFERS')
        reply = exchange_guard_task_files(
            self._frames,
            self._controller,
            self._lock,
            request,
            timeout_ms=_remaining(deadline),
            cancelled=cancelled,
        )
        if reply.status != BASIS_STAGE_STATUS:
            raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_UNVERIFIED')
        return reply.result

    def publish(self, parent, basis_binding, seal, check_active, *, timeout_ms, cancelled):
        deadline = _deadline(timeout_ms)

        def checkpoint():
            check_active()
            if cancelled():
                raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_INTERRUPTED')
            _remaining(deadline)

        def send(stage, payload):
            checkpoint()
            return self._stage(stage, payload, deadline=deadline, cancelled=cancelled)

        plan = runtime_basis_plan(parent, basis_binding, seal, checkpoint)
        if plan.operation_id != self._scope.operation_id or plan.sha256 != self._plan_sha256:
            raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_PLAN_DIFFERS')
        accepted = send('BEGIN', {'plan': basis_plan_header(plan)})
        if accepted['plan_sha256'] != plan.sha256:
            raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_PLAN_DIFFERS')
        for index in range(0, len(plan.members), BASIS_PLAN_PART_MEMBERS):
            part = plan.members[index : index + BASIS_PLAN_PART_MEMBERS]
            send('PLAN', {'members': basis_plan_members(part)})
        receipts = []
        for spec in plan.members:
            member = {'number': spec.number}
            offered = send('OFFER', member)
            receipt = BasisCopyReceipt(
                self._scope, self._binding_ref, spec, basis_file_identity(offered['file'])
            )
            offer = BasisWriteOffer(self._controller.controller, receipt, offered['writer'])
            write_runtime_basis(
                parent, basis_binding, seal, offer, self._scope, self._binding_ref, checkpoint
            )
            send('PIN', member)
            verified = verify_runtime_basis_copy(offer, self._scope, self._binding_ref, checkpoint)
            send('CONFIRM', {**member, 'file': asdict(verified.file)})
            receipts.append(verified)

        expected = basis_group_evidence(plan, self._scope, self._binding_ref, tuple(receipts))
        checkpoint()
        try:
            result = self._stage('FINISH', {}, deadline=deadline, cancelled=cancelled)
        except LaunchOutcomeUnknown as error:
            unknown = TaskBasisCompletionUnknown(expected)
            if getattr(error, 'retained_owner', None) is not None:
                unknown.retained_owner = error.retained_owner
            raise unknown from error
        return self._verify_result(expected, result)

    def _verify_result(self, expected, result):
        if (
            type(expected) is not BasisGroupEvidence
            or expected.scope != self._scope
            or expected.binding_ref != self._binding_ref
            or expected.plan_sha256 != self._plan_sha256
            or BasisGroupEvidence(self._scope, **result) != expected
        ):
            raise TaskBasisTransferError('ORIGINAL_BASIS_STAGE_EVIDENCE_DIFFERS')
        return expected

    def verify(self, expected, *, timeout_ms, cancelled):
        result = self._stage('VERIFY', {}, deadline=_deadline(timeout_ms), cancelled=cancelled)
        return self._verify_result(expected, result)
