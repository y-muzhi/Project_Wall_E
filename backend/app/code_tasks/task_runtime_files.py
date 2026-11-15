"""Backend's original TASK file preparation exchange and evidence binding."""

import hashlib

from backend.app.infrastructure.guard_action_records import mutation_input_sha256
from backend.app.infrastructure.guard_control_git_transport import exchange_guard_task_files
from backend.app.infrastructure.guard_request_header import (
    GuardRequestHeader,
    build_guard_request_header,
)
from backend.app.infrastructure.guard_task_execution_protocol import EXECUTION_PREPARATION_STATUS
from backend.app.infrastructure.guard_task_runtime_protocol import RUNTIME_FILES_STATUS
from backend.app.infrastructure.opencode_control import OpenCodeControlCredential
from backend.app.infrastructure.opencode_runtime_bundle import is_opencode_runtime_bundle_ref
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError, TaskExecutionPlan
from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.app.infrastructure.windows_task_basis_group import BasisGroupEvidence
from backend.app.infrastructure.windows_task_runtime_bundle import TaskRuntimeFilesError

from .task_runtime_workspace import RuntimeWorkspacePublication


class RuntimeFilesTransfer:
    def __init__(self, frames, controller, process_lock, original, binding_ref):
        if (
            type(original) is not GuardRequestHeader
            or original.action != 'PREPARE'
            or original.scope.step_no != 4
            or original.input.get('run_kind') != 'TASK'
            or original.input.get('reserve_files') is not True
        ):
            raise TaskRuntimeFilesError('ORIGINAL_TASK_FILE_RESERVATION_INPUT_REQUIRED')
        data = original.input
        self._frames, self._controller, self._lock = frames, controller, process_lock
        self._scope, self._reference = original.scope, binding_ref
        self._prepare_sha256 = mutation_input_sha256(original)
        self._basis_plan = data.get('basis_plan_sha256')
        self._workspace_manifest = data.get('workspace_manifest_sha256')
        self._bundle = data.get('runtime_bundle_ref')
        self._execution_input = data.get('execution'), data.get('network')
        if not is_opencode_runtime_bundle_ref(self._bundle):
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_STAGE_REFERENCE_DIFFERS')

    def _exchange(self, stage, basis, workspace, *, timeout_ms, cancelled):
        scope, reference = self._scope, self._reference
        if (
            type(basis) is not BasisGroupEvidence
            or basis.scope != scope
            or basis.binding_ref != reference
            or basis.plan_sha256 != self._basis_plan
            or type(workspace) is not RuntimeWorkspacePublication
            or workspace.destination.scope != scope
            or workspace.destination.binding_ref != reference
            or workspace.manifest_sha256 != self._workspace_manifest
        ):
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_STAGE_SOURCE_FILES_DIFFERS')
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
                'runtime_files_stage': stage,
                'runtime_binding_ref': reference,
                'prepare_input_sha256': self._prepare_sha256,
                'runtime_bundle_ref': self._bundle,
            },
        )
        if request.scope != scope:
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_STAGE_SCOPE_DIFFERS')
        reply = exchange_guard_task_files(
            self._frames,
            self._controller,
            self._lock,
            request,
            timeout_ms=timeout_ms,
            cancelled=cancelled,
        )
        if reply.status != RUNTIME_FILES_STATUS:
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_FILE_EVIDENCE_UNVERIFIED')
        result = reply.result
        if (
            result['basis_receipts_sha256'] != basis.receipts_sha256
            or result['workspace_tree_identity_sha256'] != workspace.tree_identity_sha256
        ):
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_STAGE_SOURCE_FILES_DIFFERS')
        return result

    def prepare(self, basis, workspace, *, timeout_ms, cancelled):
        return self._exchange(
            'PREPARE_FILES', basis, workspace, timeout_ms=timeout_ms, cancelled=cancelled
        )

    def verify(self, basis, workspace, *, timeout_ms, cancelled):
        return self._exchange(
            'VERIFY_FILES', basis, workspace, timeout_ms=timeout_ms, cancelled=cancelled
        )

    def _execution(self, stage, files, *, timeout_ms, cancelled, credential=None):
        if (
            type(files) is not dict
            or files.get('binding_ref') != self._reference
            or files.get('runtime_bundle_ref') != self._bundle
        ):
            raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_FILE_EVIDENCE_REQUIRED')
        scope = self._scope
        credential_facts = {}
        credential_payload = {}
        if credential is not None:
            plan = self._control_plan()
            credential_facts = credential.facts(scope, plan)
            if stage == 'BIND_CONTROL_CREDENTIAL':
                credential_payload['control_credential'] = credential.pipe_payload(scope, plan)
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
                'execution_stage': stage,
                'execution_binding_ref': self._reference,
                'prepare_input_sha256': self._prepare_sha256,
                **credential_payload,
            },
        )
        if request.scope != scope:
            raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_STAGE_DIFFERS')
        reply = exchange_guard_task_files(
            self._frames,
            self._controller,
            self._lock,
            request,
            timeout_ms=timeout_ms,
            cancelled=cancelled,
        )
        if reply.status != EXECUTION_PREPARATION_STATUS:
            raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_EVIDENCE_UNVERIFIED')
        result = reply.result
        if result['file_evidence_sha256'] != hashlib.sha256(_bytes(files)).hexdigest():
            raise TaskExecutionError('ORIGINAL_TASK_EXECUTION_FILE_EVIDENCE_DIFFERS')
        if any(result.get(key) != value for key, value in credential_facts.items()):
            raise TaskExecutionError('ORIGINAL_TASK_CONTROL_CREDENTIAL_UNVERIFIED')
        return result

    def _control_plan(self):
        return TaskExecutionPlan.parse(*self._execution_input, self._bundle)

    def issue_control_credential(self):
        return OpenCodeControlCredential.issue(self._scope, self._control_plan())

    def bind_control_credential(self, files, credential, *, timeout_ms, cancelled):
        if type(credential) is not OpenCodeControlCredential:
            raise TaskExecutionError('ORIGINAL_TASK_CONTROL_CREDENTIAL_REQUIRED')
        return self._execution(
            'BIND_CONTROL_CREDENTIAL',
            files,
            credential=credential,
            timeout_ms=timeout_ms,
            cancelled=cancelled,
        )

    def verify_control_credential(self, files, credential, *, timeout_ms, cancelled):
        if type(credential) is not OpenCodeControlCredential:
            raise TaskExecutionError('ORIGINAL_TASK_CONTROL_CREDENTIAL_REQUIRED')
        return self._execution(
            'VERIFY_CONTROL_CREDENTIAL',
            files,
            credential=credential,
            timeout_ms=timeout_ms,
            cancelled=cancelled,
        )

    def verify_network_policy(self, files, *, timeout_ms, cancelled):
        return self._execution(
            'VERIFY_NETWORK_POLICY', files, timeout_ms=timeout_ms, cancelled=cancelled
        )

    def verify_launch_input(self, files, *, timeout_ms, cancelled):
        return self._execution(
            'VERIFY_LAUNCH_INPUT', files, timeout_ms=timeout_ms, cancelled=cancelled
        )

    def prepare_execution(self, files, *, timeout_ms, cancelled):
        return self._execution(
            'PREPARE_EXECUTION', files, timeout_ms=timeout_ms, cancelled=cancelled
        )

    def verify_execution(self, files, *, timeout_ms, cancelled):
        return self._execution(
            'VERIFY_EXECUTION', files, timeout_ms=timeout_ms, cancelled=cancelled
        )

    def prepare_profile(self, files, *, timeout_ms, cancelled):
        return self._execution('PREPARE_PROFILE', files, timeout_ms=timeout_ms, cancelled=cancelled)

    def verify_profile(self, files, *, timeout_ms, cancelled):
        return self._execution('VERIFY_PROFILE', files, timeout_ms=timeout_ms, cancelled=cancelled)

    def verify_profile_network(self, files, *, timeout_ms, cancelled):
        return self._execution(
            'VERIFY_PROFILE_NETWORK', files, timeout_ms=timeout_ms, cancelled=cancelled
        )

    def install_network(self, files, *, timeout_ms, cancelled):
        return self._execution('INSTALL_NETWORK', files, timeout_ms=timeout_ms, cancelled=cancelled)
