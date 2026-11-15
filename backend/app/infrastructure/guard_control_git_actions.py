"""Execute registered Control Git actions under the actual Guard actor."""

from dataclasses import asdict

from .guard_action_journal import GuardActionJournal
from .guard_control_git_input import (
    ObserveControlGit,
    PrepareControlGit,
    decode_control_git_action,
)
from .guard_control_git_prepare import prepare_control_git
from .guard_controller_owner import GuardControllerOwner
from .guard_recovery import recover_control_git_scope
from .guard_request_header import GuardRequestHeader, parse_guard_request_header
from .runtime_control_git import ControlGitRegistry
from .runtime_launch_journal import LaunchOutcomeUnknown


def _original_preparation(registry, request):
    scope = request.target_scope
    with registry._gate:
        owner = registry._preparations.get(scope.key)
        entry = registry._entries.get(scope.key)
    if entry is not None and (owner is None or entry.preparation is not owner):
        raise LaunchOutcomeUnknown('ORIGINAL_CONTROL_GIT_PREPARATION_OWNER_REQUIRED')
    if request.binding_ref is not None and (
        owner is None or owner.binding_ref != request.binding_ref
    ):
        raise LaunchOutcomeUnknown('ORIGINAL_CONTROL_GIT_BINDING_UNVERIFIED')
    return owner, entry


def _observe(request, decoded, actions, registry):
    scope = request.target_scope
    owner, entry = _original_preparation(registry, request)
    original = actions.find(scope, decoded.observed_action)
    expected_epoch = (
        request.owner_epoch if request.recovery is None else request.recovery.owner_epoch
    )
    if original is not None and original.owner_epoch != expected_epoch:
        raise LaunchOutcomeUnknown('ORIGINAL_CONTROL_GIT_ACTION_EPOCH_DIFFERS')
    fence = registry._journal.inspect(scope)
    preparation = None if owner is None else owner.describe()
    resource = None
    job_activity = None
    if entry is not None:
        with entry.gate:
            resource = registry._facts(entry, 'OBSERVED')
            if not entry.released:
                members = entry.job.observe_members()
                job_activity = {
                    'process_ids': list(members.process_ids),
                    'assigned_count': members.assigned_count,
                    'complete': members.complete,
                }
    return {
        'observed_action': decoded.observed_action,
        'action_phase': 'UNKNOWN' if original is None else original.phase,
        'input_sha256': None if original is None else original.input_sha256,
        'binding_ref': None if owner is None else owner.binding_ref,
        'fence': None if fence is None else asdict(fence),
        'preparation': preparation,
        'resource': resource,
        'acknowledgement': None if original is None else original.result,
        'job_activity': job_activity,
    }


def _stop(request, actions, registry, owner):
    scope = request.target_scope
    if owner is not None:
        if owner.handles_released:
            fence = registry._journal.inspect(scope)
            if fence is None or not fence.stop_closed:
                raise LaunchOutcomeUnknown('ORIGINAL_CONTROL_GIT_STOP_UNVERIFIED')
            return {'stop_closed': True, 'preparation': owner.describe()}
        return registry.stop(scope)
    fence = registry._journal.close_nonce(scope)
    if actions.find(scope, 'PREPARE') is not None or fence.create_state != 'NONE':
        raise LaunchOutcomeUnknown('ORIGINAL_CONTROL_GIT_STOP_OWNER_UNVERIFIED')
    return {'stop_closed': True, 'fence': asdict(fence)}


def _require_release_ready(owner):
    if owner is None:
        raise LaunchOutcomeUnknown('ORIGINAL_CONTROL_GIT_RELEASE_OWNER_UNVERIFIED')
    owner.verify_release_ready()


def _release(registry, scope, owner, entry):
    if entry is not None and not entry.released:
        registry.release_native_handles(scope)
    owner.close_stopped_handles()
    return {'cleanup_verified': True, 'preparation': owner.describe()}


def _run_control_git_action(request, binding, registry, *, content_parent=None):
    """Called only inside one current or narrowly recovered Guard admission."""
    if type(registry) is not ControlGitRegistry:
        raise TypeError('Original Control Git Registry required')
    scope = request.target_scope
    if registry._controller_ref != scope.controller_ref:
        raise LaunchOutcomeUnknown('ORIGINAL_CONTROL_GIT_CONTROLLER_DIFFERS')
    decoded = decode_control_git_action(request, binding, content_parent=content_parent)
    actions = GuardActionJournal(registry._journal)
    if type(decoded) is PrepareControlGit:
        return prepare_control_git(
            request, binding, actions, registry, content_parent=content_parent
        )
    if type(decoded) is ObserveControlGit:
        return _observe(request, decoded, actions, registry)
    original = actions.find(scope, request.action)
    if original is not None:
        # Exact replay still verifies the original digest and never dispatches.
        return actions.begin(request).record
    owner, entry = _original_preparation(registry, request)
    if request.action == 'RELEASE':
        _require_release_ready(owner)
    start = actions.begin(request)
    if not start.first_accepted:
        return start.record
    if request.action == 'CREATE_SUSPENDED':
        result = registry.create(scope)
        if result['fence']['create_state'] != 'RESOURCE_RECORDED':
            raise LaunchOutcomeUnknown('ORIGINAL_CONTROL_GIT_CREATE_UNVERIFIED')
    elif request.action == 'RESUME':
        result = registry.resume(scope)
        if result['fence']['resume_state'] != 'ACKNOWLEDGED':
            raise LaunchOutcomeUnknown('ORIGINAL_CONTROL_GIT_RESUME_UNVERIFIED')
    elif request.action == 'STOP':
        result = _stop(request, actions, registry, owner)
    else:
        result = _release(registry, scope, owner, entry)
    return actions.acknowledge(
        start.record,
        {'binding_ref': None if owner is None else owner.binding_ref, 'native': result},
    )


def run_guard_control_git_action(
    owner, request, *, peer, program, timeout_ms, cancelled, original_owner=None
):
    if type(owner) is not GuardControllerOwner or type(request) is not GuardRequestHeader:
        raise TypeError('Original Guard controller and parsed request required')
    binding = owner.binding
    if parse_guard_request_header(request.wire, binding, peer=peer) != request:
        raise LaunchOutcomeUnknown('ORIGINAL_CONTROL_GIT_REQUEST_DIFFERS')
    if request.recovery is None:
        if original_owner is not None:
            raise LaunchOutcomeUnknown('ORIGINAL_CONTROL_GIT_RECOVERY_SELECTOR_REQUIRED')
        with owner.current_registry(
            binding, peer=peer, program=program, timeout_ms=timeout_ms, cancelled=cancelled
        ) as registry:
            return _run_control_git_action(
                request,
                binding,
                registry,
                content_parent=getattr(owner, '_task_source_parent', None),
            )
    if (
        type(original_owner) is not GuardControllerOwner
        or original_owner._records is not owner._records
        or original_owner.binding.controller_ref != request.recovery.controller_ref
        or original_owner.binding.owner_epoch != request.recovery.owner_epoch
    ):
        raise LaunchOutcomeUnknown('ORIGINAL_CONTROL_GIT_RECOVERY_OWNER_UNVERIFIED')
    owner._check_thread()
    with recover_control_git_scope(
        request,
        binding,
        peer=peer,
        program=program,
        records=owner._records,
        registry=original_owner.registry,
        timeout_ms=timeout_ms,
        cancelled=cancelled,
    ) as original:
        return _run_control_git_action(request, binding, original.registry)
