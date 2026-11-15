"""Narrow original-scope recovery authorization under the actual current caller.

Use the original held EXITED controller or a verified durable controller-domain
seal. A registry boolean alone is not closure evidence. Missing original owners remain
unknown, including after a Guard restart; this module never reopens old PIDs.
The caller still performs the selected action and its complete cleanup.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field

from .guard_backend_program import (
    POLICY_VERSION,
    BackendProgramAdmission,
    ProtectedBackendProgram,
)
from .guard_controller_binding import GuardControllerBinding
from .guard_controller_records import GuardControllerRecords, GuardControllerRegistration
from .guard_request_header import (
    RECOVERY_ACTIONS,
    GuardRequestHeader,
    parse_guard_request_header,
)
from .runtime_control_git import ControlGitRegistry
from .runtime_launch_journal import LaunchOutcomeUnknown, LaunchScope
from .windows_task_directories import TaskLpacDirectories


class GuardRecoveryUnknown(LaunchOutcomeUnknown):
    pass


@dataclass(frozen=True)
class OriginalRecoveryScope:
    registry: ControlGitRegistry = field(repr=False)
    scope: LaunchScope
    action: str
    binding_ref: str


def require_recovery_program_provenance(current, old, binding, admission):
    """Check Guard-private facts, not RPC claims or a client-supplied ready flag."""
    if (
        type(current) is not GuardControllerRegistration
        or type(old) is not GuardControllerRegistration
        or type(binding) is not GuardControllerBinding
        or type(admission) is not BackendProgramAdmission
    ):
        raise GuardRecoveryUnknown('ORIGINAL_RECOVERY_REGISTRATION_REQUIRED')
    if (
        current.binding != binding
        or old.binding.controller_ref == binding.controller_ref
        or current.binding.installation_ref != old.binding.installation_ref
        or current.binding.controller.user_sid != old.binding.controller.user_sid
    ):
        raise GuardRecoveryUnknown('ORIGINAL_RECOVERY_INSTALLATION_OR_USER_DIFFERS')
    if (
        type(current.backend_admission) is not BackendProgramAdmission
        or type(old.backend_admission) is not BackendProgramAdmission
        or current.backend_admission != admission
        or old.backend_admission.policy_version != POLICY_VERSION
        or admission.policy_version != POLICY_VERSION
    ):
        raise GuardRecoveryUnknown('ORIGINAL_ADMITTED_BACKEND_PROGRAM_EVIDENCE_REQUIRED')
    if (
        current.backend_program_ref != old.backend_program_ref
        or current.backend_package_sha256 != old.backend_package_sha256
        or current.backend_program_ref != admission.program_ref
        or current.backend_package_sha256 != admission.manifest_sha256
        or old.backend_admission.program_ref != admission.program_ref
        or old.backend_admission.manifest_sha256 != admission.manifest_sha256
        or current.image.sha256 != old.image.sha256
        or current.image.byte_count != old.image.byte_count
        or current.image.architecture != old.image.architecture
    ):
        raise GuardRecoveryUnknown('ORIGINAL_RECOVERY_BACKEND_PROGRAM_DIFFERS')


@contextmanager
def _recovery_admission(request, binding, peer, program, records, timeout_ms, cancelled):
    if type(request) is not GuardRequestHeader or type(binding) is not GuardControllerBinding:
        raise GuardRecoveryUnknown('ORIGINAL_RECOVERY_REQUEST_REQUIRED')
    parsed = parse_guard_request_header(request.wire, binding, peer=peer)
    if parsed != request or parsed.recovery is None or parsed.action not in RECOVERY_ACTIONS:
        raise GuardRecoveryUnknown('ORIGINAL_NARROW_RECOVERY_SELECTOR_REQUIRED')
    if type(program) is not ProtectedBackendProgram or program.peer is not peer:
        raise GuardRecoveryUnknown('ACTUAL_PROTECTED_BACKEND_PROGRAM_REQUIRED')
    if type(records) is not GuardControllerRecords:
        raise GuardRecoveryUnknown('ORIGINAL_GUARD_RESOURCE_OWNERS_REQUIRED')
    with program.admission(timeout_ms=timeout_ms, cancelled=cancelled) as admission:
        current = records.read(binding.controller_ref, binding.owner_epoch)
        old = records.read(parsed.recovery.controller_ref, parsed.recovery.owner_epoch)
        require_recovery_program_provenance(current, old, binding, admission)
        if current.image != peer._program.verify():
            raise GuardRecoveryUnknown('ORIGINAL_CURRENT_BACKEND_IMAGE_DIFFERS')
        yield parsed, old


def _require_registry(records, registry, old):
    if type(registry) is not ControlGitRegistry:
        raise GuardRecoveryUnknown('ORIGINAL_GUARD_RESOURCE_OWNERS_REQUIRED')
    if registry._journal is not records._journal:
        raise GuardRecoveryUnknown('ORIGINAL_GUARD_JOURNAL_OWNER_DIFFERS')
    if (
        registry._controller_ref != old.binding.controller_ref
        or registry._controller._expected != old.binding.controller
    ):
        raise GuardRecoveryUnknown('ORIGINAL_OLD_CONTROLLER_OWNER_DIFFERS')


def _require_retired(records, registry, old, fence):
    observation = None
    try:
        observer = registry._watch_source
        if observer is not None:
            observation = observer.observe()
    except (RuntimeError, OSError):
        pass
    if observation is not None and observation.identity != old.binding.controller:
        raise GuardRecoveryUnknown('ORIGINAL_OLD_CONTROLLER_IDENTITY_DIFFERS')
    if observation is not None and observation.state == 'EXITED':
        return
    try:
        seal = records.read_seal(old.binding.controller_ref, old.binding.owner_epoch)
        actual = records._journal.verify_controller_closure(old.binding.controller_ref)
        if actual != seal or not fence.stop_closed:
            raise GuardRecoveryUnknown('ORIGINAL_CONTROLLER_SEAL_UNVERIFIED')
    except (RuntimeError, OSError, ValueError) as error:
        raise GuardRecoveryUnknown('OLD_CONTROLLER_EXIT_OR_RELIABLE_CLOSURE_REQUIRED') from error


@contextmanager
def recover_control_git_scope(
    request, binding, *, peer, program, records, registry, timeout_ms, cancelled
):
    """Hold current admission and the original Control Git entry through one action."""
    with _recovery_admission(request, binding, peer, program, records, timeout_ms, cancelled) as (
        parsed,
        old,
    ):
        _require_registry(records, registry, old)
        target = parsed.target_scope
        entry = registry._entry(target)
        if not entry.gate.acquire(blocking=False):
            raise GuardRecoveryUnknown('ORIGINAL_RECOVERY_SCOPE_STILL_IN_FLIGHT')
        try:
            with records._journal._gate:
                active = records._journal._scope_gates.get(target.key)
                if active is not None and active.users:
                    raise GuardRecoveryUnknown('ORIGINAL_RECOVERY_SCOPE_STILL_IN_FLIGHT')
                fence = records._journal.inspect(target)
            if fence is None or fence.scope != target or entry.scope != target:
                raise GuardRecoveryUnknown('ORIGINAL_RECOVERY_SCOPE_RECORD_MISSING')
            if parsed.binding_ref is not None and parsed.binding_ref != entry.job_ref:
                raise GuardRecoveryUnknown('ORIGINAL_RECOVERY_RESOURCE_BINDING_DIFFERS')
            _require_retired(records, registry, old, fence)
            yield OriginalRecoveryScope(registry, target, parsed.action, entry.job_ref)
        finally:
            entry.gate.release()


@contextmanager
def recover_task_scope(
    request,
    binding,
    *,
    peer,
    program,
    records,
    registry,
    directories,
    timeout_ms,
    cancelled,
):
    """Use the held original TASK directories/Job only after narrow recovery admission."""
    with _recovery_admission(request, binding, peer, program, records, timeout_ms, cancelled) as (
        parsed,
        old,
    ):
        _require_registry(records, registry, old)
        target = parsed.target_scope
        if (
            type(directories) is not TaskLpacDirectories
            or directories.scope != target
            or directories._actions._journal is not records._journal
            or directories._controller._expected != old.binding.controller
            or (parsed.binding_ref is not None and parsed.binding_ref != directories.binding_ref)
        ):
            raise GuardRecoveryUnknown('ORIGINAL_TASK_RECOVERY_OWNER_REQUIRED')
        with records._journal._scope(target, blocking=False) as acquired:
            if not acquired or cancelled():
                raise GuardRecoveryUnknown('ORIGINAL_RECOVERY_SCOPE_STILL_IN_FLIGHT')
            fence = records._journal.inspect(target)
            if fence is None or fence.scope != target:
                raise GuardRecoveryUnknown('ORIGINAL_RECOVERY_SCOPE_RECORD_MISSING')
            _require_retired(records, registry, old, fence)
            yield OriginalRecoveryScope(registry, target, parsed.action, directories.binding_ref)
