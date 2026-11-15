"""One original Control Git exchange on an authenticated local pipe."""

from threading import get_ident

from .guard_action_journal import GuardActionJournal
from .guard_backend_program import ProtectedBackendProgram
from .guard_control_git_actions import run_guard_control_git_action
from .guard_control_git_input import decode_control_git_action
from .guard_control_git_reply import guard_control_git_reply, parse_guard_control_git_reply
from .guard_controller_binding import GuardControllerBinding, bind_guard_controller
from .guard_controller_owner import GuardControllerOwner, GuardControllerOwnerError
from .guard_controller_records import GuardControllerRecords
from .guard_pipe_frames import GuardPipeFrames, _remaining
from .guard_project_check import (
    has_original_project_check,
    recover_guard_project_check,
    run_guard_project_check,
)
from .guard_project_check_deployment import (
    GuardBrowserDriverDeployment,
    GuardProjectCheckDeployment,
)
from .guard_project_check_protocol import decode_project_check_prepare, is_project_check_prepare
from .guard_request_header import (
    TESTING_CHECK_PROTOCOL,
    GuardRequestHeader,
    _parse,
    parse_guard_request_header,
)
from .guard_task_actions import TaskNetworkDeployment, run_guard_sealed_task_action
from .guard_task_basis_protocol import decode_basis_stage, is_task_basis_request
from .guard_task_execution import run_guard_task_execution
from .guard_task_execution_protocol import decode_task_execution_stage, is_task_execution_request
from .guard_task_files import (
    find_task_file_reservation,
    reserve_task_files,
    run_guard_task_basis,
    run_guard_task_file_action,
)
from .guard_task_launch import run_guard_task_launch, run_guard_task_recovery
from .guard_task_launch_protocol import LAUNCH_ACTIONS, decode_task_launch_action
from .guard_task_model_source import VERIFY_MODEL_SOURCE, decode_model_source_request
from .guard_task_network import has_sealed_task_network
from .guard_task_runtime_files import run_guard_task_runtime_files
from .guard_task_runtime_protocol import decode_runtime_files_stage, is_task_runtime_request
from .guard_task_sources import validate_task_source_parent, verify_guard_task_source_request
from .guard_task_workspace import run_guard_task_workspace
from .guard_task_workspace_protocol import decode_workspace_stage, is_task_workspace_request
from .opencode_binary import OpenCodeBinarySource
from .opencode_runtime_bundle import TaskRuntimeBundleDeployment
from .runtime_launch_journal import LaunchFenceError, LaunchOutcomeUnknown
from .windows_guard_pipe import GuardPipeClient, GuardPipeServer, pipe_name
from .windows_guard_pipe_io import _deadline
from .windows_local_paths import local_absolute_path
from .windows_pipe_peer import NamedPipePeerLease
from .windows_task_directories import TaskRuntimeRoot

MAX_CONTROLLERS = 64


class GuardExchangeUnknown(LaunchOutcomeUnknown):
    def __init__(self, request):
        super().__init__('ORIGINAL_GUARD_EXCHANGE_OUTCOME_UNKNOWN')
        self.request = request


def _endpoint(frames, kind, installation_ref):
    if type(frames) is not GuardPipeFrames:
        raise TypeError('Original Guard pipe frames required')
    frames._check()
    io = frames._io
    endpoint = io._endpoint
    if (
        type(endpoint) is not kind
        or endpoint.name != pipe_name(installation_ref)
        or not io._connected
    ):
        raise LaunchOutcomeUnknown('ORIGINAL_GUARD_PIPE_ENDPOINT_DIFFERS')
    return endpoint


def exchange_guard_control_git(
    frames, binding, process_lock, request, *, timeout_ms, cancelled, content_parent=None
):
    """Send one frozen request. After an uncertain send, observe the original action."""
    if request.protocol == TESTING_CHECK_PROTOCOL:
        raise LaunchOutcomeUnknown('TESTING_GUARD_SCOPE_REQUIRES_PROJECT_CHECK')
    decode_control_git_action(request, binding, content_parent=content_parent)
    return _exchange_guard_request(frames, binding, process_lock, request, timeout_ms, cancelled)


def exchange_guard_task_files(frames, binding, process_lock, request, *, timeout_ms, cancelled):
    """Reserve or observe the original file roles without admitting the runtime."""
    if type(request) is not GuardRequestHeader or request.protocol == TESTING_CHECK_PROTOCOL:
        raise LaunchOutcomeUnknown('ORIGINAL_TASK_FILE_REQUEST_DIFFERS')
    if request.recovery is not None:
        decode_task_launch_action(request)
    elif request.action == 'PREPARE':
        data = request.input
        if is_task_basis_request(request):
            decode_basis_stage(request)
        elif is_task_workspace_request(request):
            decode_workspace_stage(request)
        elif is_task_runtime_request(request):
            decode_runtime_files_stage(request)
        elif is_task_execution_request(request):
            decode_task_execution_stage(request)
        elif data.get('run_kind') != 'TASK' or data.get('reserve_files') is not True:
            raise LaunchOutcomeUnknown('ORIGINAL_TASK_FILE_REQUEST_DIFFERS')
    elif request.action == VERIFY_MODEL_SOURCE:
        decode_model_source_request(request)
    elif request.action in LAUNCH_ACTIONS:
        decode_task_launch_action(request)
    elif request.action not in ('OBSERVE', 'STOP', 'RELEASE'):
        raise LaunchOutcomeUnknown('ORIGINAL_TASK_FILE_REQUEST_DIFFERS')
    return _exchange_guard_request(frames, binding, process_lock, request, timeout_ms, cancelled)


def exchange_guard_project_check(frames, binding, process_lock, request, *, timeout_ms, cancelled):
    if is_project_check_prepare(request):
        decode_project_check_prepare(request, binding)
    else:
        decode_task_launch_action(request, project_check=True)
    return _exchange_guard_request(frames, binding, process_lock, request, timeout_ms, cancelled)


def _exchange_guard_request(frames, binding, process_lock, request, timeout_ms, cancelled):
    deadline = _deadline(timeout_ms)
    if type(binding) is not GuardControllerBinding or type(request) is not GuardRequestHeader:
        raise TypeError('Original backend binding and request required')
    if _parse(request.wire, binding) != request:
        raise LaunchOutcomeUnknown('ORIGINAL_GUARD_REQUEST_DIFFERS')
    endpoint = _endpoint(frames, GuardPipeClient, binding.installation_ref)
    binding.assert_backend(process_lock)
    try:
        frames.write(request.wire, timeout_ms=_remaining(deadline), cancelled=cancelled)
        wire = frames.read(timeout_ms=_remaining(deadline), cancelled=cancelled)
        endpoint.verify()
        binding.assert_backend(process_lock)
        return parse_guard_control_git_reply(request, wire)
    except Exception as error:
        frames.invalidate()
        unknown = GuardExchangeUnknown(request)
        if getattr(error, 'retained_owner', None) is not None:
            unknown.retained_owner = frames
        raise unknown from error


class GuardControlGitServer:
    """Retain admitted controller owners independently of individual connections."""

    def __init__(
        self,
        records,
        installation_ref,
        *,
        package_root,
        manifest_sha256,
        task_network=None,
        task_source_parent=None,
        task_runtime_root=None,
        task_runtime_bundle=None,
        task_program=None,
        project_checks=(),
    ):
        if type(records) is not GuardControllerRecords:
            raise TypeError('Original Guard controller records required')
        if task_network is not None and type(task_network) is not TaskNetworkDeployment:
            raise TypeError('Trusted Guard task network deployment required')
        pipe_name(installation_ref)
        self._task_network = task_network
        if task_source_parent is not None:
            validate_task_source_parent(task_source_parent)
        self._task_source_parent = task_source_parent
        if task_runtime_root is not None:
            if type(task_runtime_root) is not TaskRuntimeRoot or task_source_parent is None:
                raise TypeError('Original Task runtime root and source parent required')
            task_runtime_root.require_disjoint(records._journal._package.verify())
            task_runtime_root.require_disjoint(task_source_parent)
        if task_runtime_bundle is not None and (
            type(task_runtime_bundle) is not TaskRuntimeBundleDeployment
            or task_runtime_root is None
        ):
            raise TypeError('Trusted TASK runtime bundle and root required')
        self._task_runtime_root = task_runtime_root
        if task_program is not None and (
            type(task_program) is not OpenCodeBinarySource
            or task_runtime_bundle is None
            or task_program.runtime_bundle_ref != task_runtime_bundle.reference
        ):
            raise TypeError('Trusted TASK program and matching runtime bundle required')
        if task_network is not None and task_network.admission is not None:
            if task_program is None:
                raise TypeError('Trusted TASK admission requires its registered program')
            admission_root = task_network.admission.directory
            task_runtime_root.require_disjoint(admission_root)
            admission_path = local_absolute_path(admission_root.canonical_path)
            for identity in (task_source_parent, records._journal._package.verify()):
                original_path = local_absolute_path(identity.canonical_path)
                if admission_path.is_relative_to(original_path) or original_path.is_relative_to(
                    admission_path
                ):
                    raise LaunchOutcomeUnknown('TASK_DEPLOYMENT_SOURCE_NOT_DISJOINT')
        if (
            type(project_checks) is not tuple
            or len(project_checks) > 32
            or any(
                type(item) not in (GuardProjectCheckDeployment, GuardBrowserDriverDeployment)
                for item in project_checks
            )
            or project_checks
            and task_runtime_root is None
        ):
            raise TypeError('Trusted project CHECK deployment and runtime root required')
        self._project_checks = project_checks
        self._task_runtime_bundle = task_runtime_bundle
        self._task_program = task_program
        self._thread = get_ident()
        self._records = records
        self._installation_ref = installation_ref
        self._package_root = package_root
        self._manifest_sha256 = manifest_sha256
        self._owners = {}
        self._retained = []
        self._closed = False

    def _check(self):
        if get_ident() != self._thread:
            raise LaunchOutcomeUnknown('ORIGINAL_GUARD_SERVER_THREAD_DIFFERS')

    def _owner(self, binding, peer, program, deadline, cancelled):
        existing = self._owners.get(binding.controller_ref)
        if existing is not None:
            if existing.binding != binding:
                raise LaunchOutcomeUnknown('ORIGINAL_GUARD_CONTROLLER_DIFFERS')
            return existing
        if len(self._owners) >= MAX_CONTROLLERS:
            raise LaunchOutcomeUnknown('GUARD_CONTROLLER_CAPACITY_EXHAUSTED')
        owner = GuardControllerOwner(
            self._records,
            binding,
            peer=peer,
            program=program,
            timeout_ms=_remaining(deadline),
            cancelled=cancelled,
        )
        owner._task_source_parent = self._task_source_parent
        self._owners[binding.controller_ref] = owner
        return owner

    def serve(self, frames, *, expected_backend, backend_image, timeout_ms, cancelled):
        """Process one request; the caller owns the connected original endpoint."""
        self._check()
        if self._closed or self._retained:
            raise LaunchOutcomeUnknown('ORIGINAL_GUARD_SERVER_UNAVAILABLE')
        deadline = _deadline(timeout_ms)
        endpoint = _endpoint(frames, GuardPipeServer, self._installation_ref)
        try:
            with (
                NamedPipePeerLease(
                    frames._io._handle,
                    peer_kind='CLIENT',
                    expected=expected_backend,
                    program=backend_image,
                    expected_user_sid=endpoint.backend_sid,
                ) as peer,
                ProtectedBackendProgram(
                    peer,
                    self._package_root,
                    expected_manifest_sha256=self._manifest_sha256,
                    timeout_ms=_remaining(deadline),
                    cancelled=cancelled,
                ) as program,
            ):
                wire = frames.read(timeout_ms=_remaining(deadline), cancelled=cancelled)
                binding = bind_guard_controller(
                    peer, wire.get('owner_epoch'), self._installation_ref
                )
                request = parse_guard_request_header(wire, binding, peer=peer)
                outcome = self._dispatch(request, binding, peer, program, deadline, cancelled)
                peer.verify()
                frames.write(
                    guard_control_git_reply(request, outcome),
                    timeout_ms=_remaining(deadline),
                    cancelled=cancelled,
                )
        except BaseException as error:
            frames.invalidate()
            retained = getattr(error, 'retained_owner', None)
            if retained is not None:
                self._retained.append(retained)
            raise

    def _dispatch(self, request, binding, peer, program, deadline, cancelled):
        actions = GuardActionJournal(self._records._journal)
        scope = request.target_scope
        if is_project_check_prepare(request) or has_original_project_check(actions, scope):
            if request.recovery is not None:
                original = self._owners.get(request.recovery.controller_ref)
                if original is None:
                    return None
                current = self._owner(binding, peer, program, deadline, cancelled)
                try:
                    return recover_guard_project_check(
                        current,
                        original,
                        request,
                        peer=peer,
                        program=program,
                        timeout_ms=_remaining(deadline),
                        cancelled=cancelled,
                    )
                except LaunchOutcomeUnknown as error:
                    if getattr(error, 'retained_owner', None) is not None:
                        raise
                    return None
            if not self._project_checks:
                return None
            owner = self._owner(binding, peer, program, deadline, cancelled)
            return run_guard_project_check(
                owner,
                request,
                self._task_runtime_root,
                self._task_source_parent,
                self._project_checks,
                peer=peer,
                program=program,
                timeout_ms=_remaining(deadline),
                cancelled=cancelled,
            )
        if request.protocol == TESTING_CHECK_PROTOCOL:
            return None
        sealed_task = has_sealed_task_network(actions, scope)
        task_files = find_task_file_reservation(actions, scope)
        basis_stage = is_task_basis_request(request)
        workspace_stage = is_task_workspace_request(request)
        runtime_stage = is_task_runtime_request(request)
        execution_stage = is_task_execution_request(request)
        file_stage = basis_stage or workspace_stage or runtime_stage
        task_stage = file_stage or execution_stage
        if task_files is not None and request.recovery is not None:
            if (
                not sealed_task
                or task_stage
                or request.action not in ('OBSERVE', 'STOP', 'RELEASE')
            ):
                return None
            original = self._owners.get(request.recovery.controller_ref)
            if original is None:
                return None
            current = self._owner(binding, peer, program, deadline, cancelled)
            try:
                return run_guard_task_recovery(
                    current,
                    original,
                    request,
                    peer=peer,
                    program=program,
                    timeout_ms=_remaining(deadline),
                    cancelled=cancelled,
                )
            except LaunchOutcomeUnknown as error:
                if getattr(error, 'retained_owner', None) is not None:
                    raise
                return None
        task_launch_action = (
            sealed_task
            and task_files is not None
            and task_files[0].phase == 'ACKNOWLEDGED'
            and request.action
            in (*LAUNCH_ACTIONS, 'OBSERVE', 'STOP', 'RELEASE', VERIFY_MODEL_SOURCE)
            and request.recovery is None
        )
        if task_stage and task_files is None:
            return None
        if sealed_task and file_stage:
            data = request.input
            if not (
                (basis_stage and data['basis_stage'] == 'VERIFY')
                or (workspace_stage and data['workspace_stage'] == 'VERIFY')
                or (runtime_stage and data['runtime_files_stage'] == 'VERIFY_FILES')
            ):
                return None
        if (
            not task_stage
            and request.action == 'PREPARE'
            and request.input.get('run_kind') == 'TASK'
        ):
            if not sealed_task and task_files is None and self._task_source_parent is not None:
                self._prepare_task_files(request, binding, peer, program, deadline, cancelled)
            return None
        if (
            sealed_task
            and not task_stage
            and (
                self._task_network is None
                or request.recovery is not None
                or (not task_launch_action and request.action not in ('OBSERVE', 'STOP', 'RELEASE'))
            )
        ):
            return None
        if (
            task_files is not None
            and not sealed_task
            and not task_stage
            and (request.recovery is not None or request.action not in ('OBSERVE', 'STOP'))
        ):
            return None
        if sealed_task and task_files is not None and request.action == 'RELEASE':
            stopped = actions.find(scope, 'STOP')
            if stopped is None or stopped.phase != 'ACKNOWLEDGED':
                return None
        if not task_launch_action and (task_files is None or (sealed_task and not task_stage)):
            decode_control_git_action(request, binding, content_parent=self._task_source_parent)
        owner = self._owner(binding, peer, program, deadline, cancelled)
        try:
            if task_launch_action:
                return run_guard_task_launch(
                    owner,
                    request,
                    peer=peer,
                    program=program,
                    timeout_ms=_remaining(deadline),
                    cancelled=cancelled,
                )
            if execution_stage:
                return run_guard_task_execution(
                    owner,
                    request,
                    self._task_program,
                    self._task_network,
                    peer=peer,
                    program=program,
                    timeout_ms=_remaining(deadline),
                    cancelled=cancelled,
                )
            if sealed_task and not task_stage and (task_files is None or request.action != 'STOP'):
                return run_guard_sealed_task_action(
                    owner,
                    request,
                    self._task_network,
                    peer=peer,
                    program=program,
                    timeout_ms=_remaining(deadline),
                    cancelled=cancelled,
                )
            if basis_stage:
                return run_guard_task_basis(
                    owner,
                    request,
                    peer=peer,
                    program=program,
                    timeout_ms=_remaining(deadline),
                    cancelled=cancelled,
                )
            if workspace_stage:
                return run_guard_task_workspace(
                    owner,
                    request,
                    peer=peer,
                    program=program,
                    timeout_ms=_remaining(deadline),
                    cancelled=cancelled,
                )
            if runtime_stage:
                return run_guard_task_runtime_files(
                    owner,
                    request,
                    self._task_runtime_bundle,
                    peer=peer,
                    program=program,
                    timeout_ms=_remaining(deadline),
                    cancelled=cancelled,
                )
            if task_files is not None:
                return run_guard_task_file_action(
                    owner,
                    request,
                    peer=peer,
                    program=program,
                    timeout_ms=_remaining(deadline),
                    cancelled=cancelled,
                )
            original = None
            if request.recovery is not None:
                original = self._owners.get(request.recovery.controller_ref)
            return run_guard_control_git_action(
                owner,
                request,
                peer=peer,
                program=program,
                timeout_ms=_remaining(deadline),
                cancelled=cancelled,
                original_owner=original,
            )
        except GuardControllerOwnerError:
            raise
        except LaunchOutcomeUnknown as error:
            if getattr(error, 'retained_owner', None) is not None:
                raise
            return None

    def _prepare_task_files(self, request, binding, peer, program, deadline, cancelled):
        owner = self._owner(binding, peer, program, deadline, cancelled)
        try:
            if 'reserve_files' in request.input:
                if self._task_runtime_root is not None:
                    reserve_task_files(
                        owner,
                        request,
                        self._task_source_parent,
                        self._task_runtime_root,
                        peer=peer,
                        program=program,
                        timeout_ms=_remaining(deadline),
                        cancelled=cancelled,
                    )
            else:
                verify_guard_task_source_request(
                    owner,
                    request,
                    self._task_source_parent,
                    peer=peer,
                    program=program,
                    timeout_ms=_remaining(deadline),
                    cancelled=cancelled,
                    runtime_root=self._task_runtime_root,
                )
        except GuardControllerOwnerError:
            raise
        except LaunchFenceError as error:
            if getattr(error, 'retained_owner', None) is not None:
                raise

    def stop_owned(self, *, timeout_ms):
        """Bounded local-service shutdown, retaining every uncertain original owner."""
        self._check()
        deadline = _deadline(timeout_ms)
        failures = []
        for owner in tuple(self._owners.values()):
            try:
                owner.stop_owned_for_shutdown(deadline=deadline)
            except (RuntimeError, OSError) as error:
                failures.append(error)
        if failures:
            error = LaunchOutcomeUnknown('ORIGINAL_GUARD_SHUTDOWN_UNVERIFIED')
            error.retained_owner = self
            raise error from failures[0]

    def close(self):
        self._check()
        for owner in self._owners.values():
            if any(
                not preparation.handles_released
                for preparation in owner.registry._preparations.values()
            ):
                raise LaunchOutcomeUnknown('ORIGINAL_GUARD_SCOPE_RELEASE_REQUIRED')
        self._closed = True
        for reference, owner in tuple(self._owners.items()):
            owner.close()
            del self._owners[reference]
        for retained in tuple(self._retained):
            retained.close()
            self._retained.remove(retained)
