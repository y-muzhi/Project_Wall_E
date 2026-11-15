"""Recover the original TASK scope using its backend-private Guard handoff record."""

import re
from dataclasses import asdict, dataclass

from backend.app.infrastructure.guard_action_records import mutation_input_sha256
from backend.app.infrastructure.guard_control_git_transport import exchange_guard_task_files
from backend.app.infrastructure.guard_controller_binding import owner_epoch
from backend.app.infrastructure.guard_request_header import (
    GuardRequestHeader,
    build_guard_request_header,
)
from backend.app.infrastructure.guard_task_basis_protocol import _hex
from backend.app.infrastructure.guard_task_files import _publish_original, _read_original
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import LaunchScope, _bytes
from backend.app.infrastructure.windows_private_package import PrivatePackageGuard
from backend.app.shared.validation import strict_json_object

_LIMIT = 4096
_NONCE = re.compile(r'[0-9a-f]{32}')


@dataclass(frozen=True)
class OriginalTaskOwner:
    scope: LaunchScope
    owner_epoch: str
    prepare_sha256: str

    def encoded(self):
        return _bytes({'schema_version': 1, **asdict(self)})


class TaskRecoveryReceipt:
    def __init__(self, package, operation_id, nonce):
        if (
            type(package) is not PrivatePackageGuard
            or package.is_control_git_read_package
            or type(nonce) is not str
            or not _NONCE.fullmatch(nonce)
        ):
            raise TaskExecutionError('ORIGINAL_TASK_RECOVERY_RECEIPT_SCOPE_REQUIRED')
        self._package, self._directory = package, package.verify()
        self._operation, self._nonce = operation_id, nonce

    def _name(self, suffix):
        return self._nonce + '.task-guard-' + suffix + '.json'

    def _read(self, suffix):
        if self._package.verify() != self._directory:
            raise TaskExecutionError('ORIGINAL_TASK_RECOVERY_PACKAGE_DIFFERS')
        return _read_original(self._package, self._name(suffix), _LIMIT)

    def _append(self, suffix, value):
        previous = self._read(suffix)
        if previous is None:
            _publish_original(self._package, self._name(suffix), value, _LIMIT)
        if self._read(suffix) != value:
            raise TaskExecutionError('ORIGINAL_TASK_RECOVERY_RECEIPT_DIFFERS')

    def remember(self, request):
        if (
            type(request) is not GuardRequestHeader
            or request.action != 'PREPARE'
            or request.recovery is not None
            or request.scope.step_no != 4
            or request.scope.operation_id != self._operation
            or request.scope.nonce != self._nonce
            or request.input.get('run_kind') != 'TASK'
            or request.input.get('reserve_files') is not True
        ):
            raise TaskExecutionError('ORIGINAL_TASK_RECOVERY_PREPARE_REQUIRED')
        self._append(
            'owner',
            OriginalTaskOwner(
                request.scope,
                request.owner_epoch,
                mutation_input_sha256(request),
            ).encoded(),
        )

    def owner(self):
        raw = self._read('owner')
        if raw is None:
            return None
        saved = strict_json_object(raw)
        if set(saved) != {'schema_version', 'scope', 'owner_epoch', 'prepare_sha256'}:
            raise TaskExecutionError('ORIGINAL_TASK_RECOVERY_RECEIPT_DIFFERS')
        original = OriginalTaskOwner(
            LaunchScope(**saved['scope']),
            owner_epoch(saved['owner_epoch']),
            saved['prepare_sha256'],
        )
        if (
            original.scope.step_no != 4
            or original.scope.operation_id != self._operation
            or original.scope.nonce != self._nonce
            or not _hex(original.prepare_sha256, 64)
            or raw != original.encoded()
        ):
            raise TaskExecutionError('ORIGINAL_TASK_RECOVERY_RECEIPT_DIFFERS')
        return original

    def _binding_record(self, owner, reference):
        if owner is None or not _hex(reference, 32):
            raise TaskExecutionError('ORIGINAL_TASK_RECOVERY_BINDING_DIFFERS')
        return _bytes(
            {
                'schema_version': 1,
                'scope': owner.scope.key,
                'owner_epoch': owner.owner_epoch,
                'prepare_sha256': owner.prepare_sha256,
                'binding_ref': reference,
            }
        )

    def remember_binding(self, reference):
        self._append('binding', self._binding_record(self.owner(), reference))

    def binding(self, owner):
        raw = self._read('binding')
        if raw is None:
            return None
        saved = strict_json_object(raw)
        reference = saved.get('binding_ref')
        if raw != self._binding_record(owner, reference):
            raise TaskExecutionError('ORIGINAL_TASK_RECOVERY_BINDING_DIFFERS')
        return reference


class RuntimeTaskRecovery:
    """Original observation and OS cleanup using current authenticated frames."""

    def __init__(self, frames, controller, process_lock, receipt):
        original = receipt.owner()
        if original is None:
            raise TaskExecutionError('ORIGINAL_TASK_RECOVERY_OWNER_UNKNOWN')
        self._frames, self._controller, self._lock = frames, controller, process_lock
        self._original = original
        self._reference = receipt.binding(original)

    def _request(self, action, input_value, *, timeout_ms, cancelled):
        if action not in ('OBSERVE', 'STOP', 'RELEASE'):
            raise TaskExecutionError('ORIGINAL_TASK_RECOVERY_ACTION_FORBIDDEN')
        original = self._original
        if action != 'OBSERVE' and self._reference is None:
            raise TaskExecutionError('ORIGINAL_TASK_RECOVERY_BINDING_UNKNOWN')
        input_value = input_value.copy()
        if self._controller.controller_ref != original.scope.controller_ref:
            input_value['recovery'] = {
                'controller_ref': original.scope.controller_ref,
                'owner_epoch': original.owner_epoch,
            }
        elif self._controller.owner_epoch != original.owner_epoch:
            raise TaskExecutionError('ORIGINAL_TASK_RECOVERY_OWNER_DIFFERS')
        request = build_guard_request_header(
            self._controller,
            self._lock,
            action=action,
            operation_id=original.scope.operation_id,
            step_no=original.scope.step_no,
            nonce=original.scope.nonce,
            binding_ref=self._reference,
            action_input=input_value,
        )
        if request.target_scope != original.scope:
            raise TaskExecutionError('ORIGINAL_TASK_RECOVERY_TARGET_DIFFERS')
        return exchange_guard_task_files(
            self._frames,
            self._controller,
            self._lock,
            request,
            timeout_ms=timeout_ms,
            cancelled=cancelled,
        )

    def observe(self, action, *, timeout_ms, cancelled):
        reply = self._request(
            'OBSERVE', {'observed_action': action}, timeout_ms=timeout_ms, cancelled=cancelled
        )
        if reply.status != 'OBSERVED':
            raise TaskExecutionError('ORIGINAL_TASK_RECOVERY_OBSERVATION_UNKNOWN')
        result = reply.result
        if action == 'PREPARE':
            if result['input_sha256'] != self._original.prepare_sha256 or not _hex(
                result['binding_ref'], 32
            ):
                raise TaskExecutionError('ORIGINAL_TASK_RECOVERY_PREPARE_DIFFERS')
            self._reference = result['binding_ref']
        return result

    def stop(self, *, timeout_ms, cancelled):
        return self._request('STOP', {}, timeout_ms=timeout_ms, cancelled=cancelled)

    def release(self, *, timeout_ms, cancelled):
        return self._request('RELEASE', {}, timeout_ms=timeout_ms, cancelled=cancelled)
