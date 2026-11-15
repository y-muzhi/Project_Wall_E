"""Current authenticated controller actions on an original sealed TASK scope."""

from dataclasses import asdict, dataclass
from uuid import UUID

from .guard_action_journal import GuardActionJournal
from .guard_controller_owner import GuardControllerOwner
from .guard_request_header import GuardRequestHeader, parse_guard_request_header
from .guard_task_deployment import TaskRuntimeAdmission
from .guard_task_network import (
    WfpObservationError,
    _rules,
    _sealed_task_plan,
    _sid,
    _verify_owned_filters_absent,
    original_network_install_dispatched,
    read_owned_filters,
    release_unlaunched_task_network,
    task_network_unlaunched_after_stop,
)
from .runtime_launch_journal import LaunchOutcomeUnknown
from .windows_job import JobBoundaryError
from .windows_local_paths import PathBoundaryError
from .windows_private_package import PackageSecurityError
from .windows_private_record import PrivateRecordError


@dataclass(frozen=True)
class TaskNetworkDeployment:
    provider: UUID
    sublayer: UUID
    model_listener: tuple[str, int] | None = None
    forward_listeners: tuple[tuple[str, int], ...] = ()
    admission: TaskRuntimeAdmission | None = None

    def __post_init__(self):
        for reference in (self.provider, self.sublayer):
            if type(reference) is not UUID or reference.int == 0:
                raise ValueError('GUARD_TASK_NETWORK_DEPLOYMENT_REQUIRED')

        if self.admission is not None and (
            type(self.admission) is not TaskRuntimeAdmission or self.model_listener is None
        ):
            raise ValueError('GUARD_TASK_RUNTIME_ADMISSION_SOURCE_REQUIRED')
        model, forwards = self.model_listener, self.forward_listeners
        if type(forwards) is not tuple or (model is None and forwards):
            raise ValueError('GUARD_TASK_REGISTERED_LISTENERS_REQUIRED')
        if model is None:
            return
        if not _registered_endpoint(model, ('127.0.0.1',)):
            raise ValueError('GUARD_TASK_REGISTERED_LISTENERS_REQUIRED')
        if any(not _registered_endpoint(endpoint, ('127.0.0.1', '::1')) for endpoint in forwards):
            raise ValueError('GUARD_TASK_REGISTERED_LISTENERS_REQUIRED')
        if model in forwards or len(set(forwards)) != len(forwards):
            raise ValueError('GUARD_TASK_REGISTERED_LISTENERS_REQUIRED')
        object.__setattr__(self, 'forward_listeners', tuple(sorted(forwards)))


def _registered_endpoint(value, addresses):
    return (
        type(value) is tuple
        and len(value) == 2
        and value[0] in addresses
        and type(value[1]) is int
        and 1 <= value[1] <= 65535
    )


def _network_state(actions, scope, fence, original, marker, endpoints, deployment):
    rules = _rules(marker, _sid(original.directory_nonce), endpoints)
    provider, sublayer = deployment.provider, deployment.sublayer
    try:
        if (
            task_network_unlaunched_after_stop(actions, scope, fence)
            and actions.find(scope, 'RELEASE') is not None
        ):
            _verify_owned_filters_absent(rules, provider, sublayer, marker)
            return 'ABSENT'
        read_owned_filters(rules, provider, sublayer, marker)
        return 'PRESENT'
    except WfpObservationError as error:
        if getattr(error, 'retained_owner', None) is not None:
            raise
        return 'UNKNOWN'


def _observe(request, actions, deployment, original, marker, endpoints):
    scope = request.target_scope
    observed_action = request.input['observed_action']
    observed = actions.find(scope, observed_action)
    if observed is not None and observed.owner_epoch != request.owner_epoch:
        raise LaunchOutcomeUnknown('ORIGINAL_TASK_ACTION_EPOCH_DIFFERS')
    fence = actions._journal.inspect(scope)
    return {
        'observed_action': observed_action,
        'action_phase': 'UNKNOWN' if observed is None else observed.phase,
        'input_sha256': None if observed is None else observed.input_sha256,
        'binding_ref': original.allocated_binding_ref,
        'fence': None if fence is None else asdict(fence),
        'preparation': {
            'binding_ref': original.allocated_binding_ref,
            'run_kind': 'TASK',
            'network_state': _network_state(
                actions, scope, fence, original, marker, endpoints, deployment
            ),
        },
        'resource': None,
        'acknowledgement': (
            {'binding_ref': original.allocated_binding_ref}
            if observed is not None and observed.phase == 'ACKNOWLEDGED'
            else None
        ),
        'job_activity': None,
    }


def _stop(request, actions, original):
    start = actions.begin(request)
    if not start.first_accepted:
        return start.record
    scope = original.scope
    fence = actions._journal.close_nonce(scope)
    if not task_network_unlaunched_after_stop(actions, scope, fence):
        return start.record
    return actions.acknowledge(
        start.record,
        {
            'binding_ref': original.allocated_binding_ref,
            'native': {'fence': asdict(fence), 'scope_unlaunched': True},
        },
    )


def run_guard_sealed_task_action(
    owner, request, deployment, *, peer, program, timeout_ms, cancelled
):
    """Only the original admitted caller can use the current TASK resource."""
    if type(owner) is not GuardControllerOwner or type(request) is not GuardRequestHeader:
        raise TypeError('Original Guard controller and parsed request required')
    if (
        type(deployment) is not TaskNetworkDeployment
        or request.recovery is not None
        or request.action not in ('OBSERVE', 'STOP', 'RELEASE')
    ):
        return None
    binding = owner.binding
    if parse_guard_request_header(request.wire, binding, peer=peer) != request:
        raise LaunchOutcomeUnknown('ORIGINAL_TASK_REQUEST_DIFFERS')
    with owner.current_registry(
        binding, peer=peer, program=program, timeout_ms=timeout_ms, cancelled=cancelled
    ) as registry:
        actions = GuardActionJournal(registry._journal)
        try:
            with _sealed_task_plan(
                actions,
                request.target_scope,
                request.owner_epoch,
                deployment.provider,
                deployment.sublayer,
            ) as (original, marker, endpoints, raw):
                if request.binding_ref not in (None, original.allocated_binding_ref):
                    raise LaunchOutcomeUnknown('ORIGINAL_TASK_RESOURCE_BINDING_DIFFERS')
                if cancelled():
                    raise LaunchOutcomeUnknown('ORIGINAL_TASK_ACTION_INTERRUPTED')
                if request.action == 'OBSERVE':
                    return _observe(request, actions, deployment, original, marker, endpoints)
                if request.action == 'STOP':
                    return _stop(request, actions, original)
                scope = original.scope
                execution = owner._task_profiles.get(scope.key)
                if execution is not None:
                    stopped = actions.find(scope, 'STOP')
                    if (
                        request.binding_ref != original.allocated_binding_ref
                        or request.input
                        or stopped is None
                        or stopped.phase != 'ACKNOWLEDGED'
                        or scope.key in owner._task_directories
                        or not task_network_unlaunched_after_stop(
                            actions, scope, actions._journal.inspect(scope)
                        )
                    ):
                        raise LaunchOutcomeUnknown('ORIGINAL_TASK_PROFILE_RELEASE_UNVERIFIED')
                if execution is None or original_network_install_dispatched(
                    actions, original, marker, raw
                ):
                    release_unlaunched_task_network(
                        actions,
                        request,
                        provider=deployment.provider,
                        sublayer=deployment.sublayer,
                        cancelled=cancelled,
                    )
                else:
                    actions.begin(request)
                if execution is not None:
                    if cancelled():
                        raise LaunchOutcomeUnknown('ORIGINAL_TASK_PROFILE_RELEASE_INTERRUPTED')
                    try:
                        execution.release_profile()
                    except (
                        JobBoundaryError,
                        OSError,
                        PackageSecurityError,
                        PathBoundaryError,
                        PrivateRecordError,
                    ) as error:
                        if getattr(error, 'retained_owner', None) is not None:
                            raise
                        raise LaunchOutcomeUnknown(
                            'ORIGINAL_TASK_PROFILE_RELEASE_UNVERIFIED'
                        ) from error
                    del owner._task_profiles[scope.key]
                # Other OS resources require their original owner before RELEASE ACK.
                return None
        except WfpObservationError as error:
            if getattr(error, 'retained_owner', None) is not None:
                raise
            return None
