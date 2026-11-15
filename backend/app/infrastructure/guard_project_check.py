"""Authenticate, prepare and retire an original TASK project check."""

from dataclasses import asdict
from time import monotonic

from .check_runner_bundle import CheckResourceError
from .guard_action_journal import GuardActionJournal
from .guard_project_check_protocol import decode_project_check_prepare, is_project_check_prepare
from .guard_recovery import recover_task_scope
from .guard_request_header import parse_guard_request_header
from .guard_task_files import _publish_original, _read_original
from .guard_task_launch import _dispatch, _observe
from .guard_task_launch_protocol import check_task_prepare_ack, decode_task_launch_action
from .guard_task_network import install_original_task_network, seal_original_task_network
from .runtime_launch_journal import LaunchOutcomeUnknown, _bytes
from .windows_check_driver_pipe import GuardDriverResultWriter
from .windows_check_driver_program import BrowserDriverProgram, browser_inspection_checkpoint
from .windows_job import OwnedJob
from .windows_lpac_profile import TaskLpacProfile
from .windows_project_check_command import ProjectCheckNetwork, ProjectCheckProgram
from .windows_stdio import GuardStandardIO
from .windows_task_check_input import CheckInputError, TaskCheckWorkspace
from .windows_task_directories import TaskLpacDirectories
from .windows_task_endpoints import require_private_http_port
from .windows_task_native_launch import TaskNativeLaunch
from .windows_task_runtime_environment import TaskRuntimeEnvironment

_LIMIT = 4096


def _marker(scope):
    return scope.key + '.project-check.json'


def has_original_project_check(actions, scope):
    return _read_original(actions._journal._package, _marker(scope), _LIMIT) is not None


class _ProjectCheckExecution:
    def __init__(self, owner, directories, deployment, source_parent):
        self._owner, self._dirs, self._network = owner, directories, deployment
        self._source_parent = source_parent
        self._program = self._environment = self._job = self._profile = self._streams = None
        self._native = self._confirmation = self._directory_release = None
        self._driver_writer = None
        self._check_result = None

    def _verify_installation(self, deadline, cancelled):
        return self._network.verify(
            self._owner.binding.installation_ref,
            self._owner.registration.backend_program_ref,
            deadline=deadline,
            cancelled=cancelled,
        )

    def _allocate(self, program, cancelled):
        dirs, deployment = self._dirs, self._network
        self._program = program
        dirs.allocate(cancelled=cancelled)
        actions, request = dirs._actions, dirs._prepare_request
        seal_original_task_network(
            actions, request, provider=deployment.provider, sublayer=deployment.sublayer
        )
        self._job = OwnedJob(
            active_process_limit=program.plan.active_process_limit,
            job_memory_limit_bytes=program.plan.job_memory_limit_bytes,
        )
        self._profile = TaskLpacProfile(dirs, self._job)
        self._native = TaskNativeLaunch(dirs, self._job, self._profile, program)
        self._owner.registry.register_task_stop(dirs.scope, self.stop_native)

    def prepare(self, prepared, checkpoint, *, deadline, cancelled):
        dirs, deployment = self._dirs, self._network
        protected = (
            self._source_parent,
            deployment.admission_directory,
            deployment.runner.directory,
        )
        if dirs.is_browser_driver:
            self._allocate(
                BrowserDriverProgram(
                    dirs,
                    deployment.driver,
                    processes=prepared.active_process_limit,
                    memory=prepared.job_memory_limit_bytes,
                    case_pack_sha256=prepared.case_pack_sha256,
                ),
                cancelled,
            )
        else:
            if prepared.application_endpoint is not None:
                require_private_http_port(prepared.application_endpoint)
            protected += (deployment.executable.file,)
            if deployment.fixture is not None:
                protected += (deployment.fixture.directory,)
            self._allocate(
                ProjectCheckProgram(dirs, deployment.command, deployment.executable), cancelled
            )
            workspace = TaskCheckWorkspace(dirs)
            workspace.publish_transferred(
                prepared.capsule, self._source_parent, limits=prepared.limits, cancelled=cancelled
            )
            if deployment.fixture is not None:
                fixture = TaskCheckWorkspace(dirs, fixture=deployment.fixture)
                fixture.publish_fixture(cancelled=cancelled)
        self._program.prepare(deadline=deadline, cancelled=cancelled)
        self._environment = TaskRuntimeEnvironment(dirs, None)
        self._environment.prepare(checkpoint)
        self._profile.prepare(cancelled)
        self._streams = GuardStandardIO(dirs._controller, prepared.stdio, scope=dirs.scope)
        self._native.bind_project_streams(self._streams)
        if dirs.is_browser_driver:
            self._driver_writer = GuardDriverResultWriter(
                dirs._controller, dirs.scope, prepared.result_pipe
            )
            self._native.bind_driver_result(self._driver_writer)
        self._policy = ProjectCheckNetwork(dirs, deployment.provider, deployment.sublayer)
        self._protected = protected
        actions, request = dirs._actions, dirs._prepare_request
        installed = install_original_task_network(
            actions,
            request,
            provider=deployment.provider,
            sublayer=deployment.sublayer,
            cancelled=cancelled,
        )
        if installed != self._policy.filter_count:
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_NETWORK_UNVERIFIED')
        launch_input = (
            self._native.browser_launch_input
            if dirs.is_browser_driver
            else self._native.project_launch_input
        )
        inspection = (
            browser_inspection_checkpoint(checkpoint, deadline=deadline, cancelled=cancelled)
            if dirs.is_browser_driver
            else checkpoint
        )
        digest = launch_input(self._environment, self._policy, protected, inspection)
        with actions._journal._gate:
            checkpoint()
            fence = actions._journal.prepare(dirs.scope, digest)
            if fence.stop_closed or fence.create_state != 'NONE':
                raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_CONFIRMATION_CLOSED')
            result = {
                'binding_ref': dirs.binding_ref,
                'run_kind': dirs.run_kind,
                'launch_input_sha256': digest,
                'stdio_binding': asdict(self._streams.binding),
            }
            if self._driver_writer is not None:
                result['result_pipe_binding'] = asdict(self._driver_writer.binding)
            self._confirmation = actions.acknowledge(dirs._original, result)
        return self._confirmation

    def _close_child_ports(self):
        for port in (self._streams, self._driver_writer):
            if port is not None:
                port.close()

    def create_native(self, digest, checkpoint, cancelled):
        create = (
            self._native.create_browser_driver
            if self._dirs.is_browser_driver
            else self._native.create_project_check
        )
        if self._dirs.is_browser_driver:
            inspection = browser_inspection_checkpoint(
                checkpoint, deadline=float('inf'), cancelled=cancelled
            )
            result = create(
                digest,
                self._environment,
                self._policy,
                self._protected,
                checkpoint,
                inspection_checkpoint=inspection,
            )
        else:
            result = create(digest, self._environment, self._policy, self._protected, checkpoint)
        self._close_child_ports()
        return result

    def resume_native(self, digest, checkpoint, active):
        self._environment.verify(checkpoint)
        return self._native.resume(digest, active)

    def stop_native(self, checkpoint, deadline):
        result = self._native.stop(checkpoint, deadline=deadline)
        self._close_child_ports()
        return result

    def release_check_inputs(self, checkpoint):
        if self._check_result is None:
            self._native.stopped_evidence()
            observed = self._native.observe()
            publication = self._dirs._check_publication
            fixture = self._dirs._check_fixture
            integrity = 'NOT_CHECKED'
            if self._dirs.is_browser_driver and self._program._facts is not None:
                try:
                    self._program.verify(checkpoint)
                except CheckResourceError as error:
                    integrity = 'CHANGED' if str(error) == 'INPUT_CHANGED' else 'UNKNOWN'
                else:
                    integrity = 'VERIFIED'
            elif publication is not None and publication._facts is not None:
                try:
                    publication.verify(checkpoint)
                    if self._network.fixture is not None:
                        if fixture is None or fixture._facts is None:
                            raise CheckInputError('ORIGINAL_TESTING_FIXTURE_INCOMPLETE')
                        fixture.verify(checkpoint)
                except CheckInputError as error:
                    integrity = 'CHANGED' if str(error) == 'INPUT_CHANGED' else 'UNKNOWN'
                else:
                    integrity = 'VERIFIED'
            exit = (
                asdict(self._native.project_exit())
                if observed['process_state'] == 'EXITED'
                else None
            )
            self._check_result = {
                'check': asdict(self._dirs.check_input),
                'source_integrity': integrity,
                'exit': exit,
            }
        if self._program is not None:
            self._program.close()
        if self._environment is not None:
            self._environment.close()
        return self._check_result

    def close(self):
        if self._native is not None:
            self._native.close()
        for name in ('_driver_writer', '_streams', '_environment', '_program', '_job'):
            owned = getattr(self, name)
            if owned is not None:
                owned.close()
                setattr(self, name, None)


def _prepare(
    owner, actions, request, binding, parent, source_parent, deployments, deadline, cancelled
):
    prepared = decode_project_check_prepare(request, binding)
    matches = [deployment for deployment in deployments if deployment.matches(prepared)]
    if len(matches) != 1 or parent is None or source_parent is None:
        raise CheckResourceError('ORIGINAL_PROJECT_CHECK_DEPLOYMENT_UNAVAILABLE')
    deployment = matches[0]
    parent.require_disjoint(source_parent)
    parent.require_disjoint(deployment.runner.directory)
    parent.require_disjoint(deployment.admission_directory)
    fixture = getattr(deployment, 'fixture', None)
    if fixture is not None:
        parent.require_disjoint(fixture.directory)
    deployment.verify(
        binding.installation_ref,
        owner.registration.backend_program_ref,
        deadline=deadline,
        cancelled=cancelled,
    )
    started = actions.begin(request)
    if not started.first_accepted:
        return started.record if started.record.phase == 'ACKNOWLEDGED' else None
    scope = request.scope
    record = started.record
    _publish_original(
        actions._journal._package,
        _marker(scope),
        _bytes({'scope': scope.key, 'input_sha256': record.input_sha256}),
        _LIMIT,
    )
    dirs = TaskLpacDirectories(parent, actions, started, request, binding, owner._token)
    owner._task_directories[scope.key] = dirs
    execution = _ProjectCheckExecution(owner, dirs, deployment, source_parent)
    dirs._execution_preparation = execution

    def checkpoint():
        dirs._require_open(cancelled)

    try:
        return execution.prepare(prepared, checkpoint, deadline=deadline, cancelled=cancelled)
    except (RuntimeError, OSError, ValueError) as error:
        retained = getattr(error, 'retained_owner', None)
        if retained is not None and all(
            retained is not known
            for known in (
                dirs,
                dirs._check_publication,
                dirs._check_fixture,
                execution,
                execution._program,
                execution._native,
                execution._driver_writer,
            )
        ):
            owner._orphans.append(retained)
        return None


def _original_prepare(actions, scope, epoch):
    record = actions.find(scope, 'PREPARE')
    if record is None or record.owner_epoch != epoch:
        return None
    expected = _bytes({'scope': scope.key, 'input_sha256': record.input_sha256})
    marker = _read_original(actions._journal._package, _marker(scope), _LIMIT)
    return record if marker == expected else None


def recover_guard_project_check(
    current, original, request, *, peer, program, timeout_ms, cancelled
):
    """Read or close a held old project CHECK under the existing recovery admission."""
    if request.recovery is None or original is None:
        return None
    decode_task_launch_action(request, project_check=True)
    directories = original._task_directories.get(request.target_scope.key)
    deadline = monotonic() + timeout_ms / 1000

    def interrupted():
        return cancelled() or monotonic() >= deadline

    def active():
        if interrupted():
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_RECOVERY_INTERRUPTED')

    with recover_task_scope(
        request,
        current.binding,
        peer=peer,
        program=program,
        records=current._records,
        registry=original.registry,
        directories=directories,
        timeout_ms=timeout_ms,
        cancelled=interrupted,
    ) as authorized:
        actions = GuardActionJournal(authorized.registry._journal)
        scope = authorized.scope
        prepared = _original_prepare(actions, scope, request.recovery.owner_epoch)
        execution = directories._execution_preparation
        if (
            prepared is None
            or not directories.is_project_check
            or type(execution) is not _ProjectCheckExecution
            or execution._native is None
            or prepared.allocated_binding_ref != authorized.binding_ref
        ):
            return None
        if request.action == 'OBSERVE':
            return _observe(actions, request, authorized.binding_ref, execution, project_check=True)
        return _dispatch(
            actions,
            request,
            prepared,
            execution,
            None,
            interrupted,
            active,
            deadline,
            recovery_controller=current._token,
        )


def run_guard_project_check(
    owner, request, parent, source_parent, deployments, *, peer, program, timeout_ms, cancelled
):
    binding = owner.binding
    if parse_guard_request_header(request.wire, binding, peer=peer) != request:
        raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_REQUEST_DIFFERS')
    deadline = monotonic() + timeout_ms / 1000

    def interrupted():
        return cancelled() or monotonic() >= deadline

    def active():
        if interrupted():
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_ACTION_INTERRUPTED')

    with owner.current_registry(
        binding, peer=peer, program=program, timeout_ms=timeout_ms, cancelled=interrupted
    ) as registry:
        scope = request.target_scope
        actions = GuardActionJournal(registry._journal)
        with registry._journal._scope(scope):
            active()
            if is_project_check_prepare(request):
                return _prepare(
                    owner,
                    actions,
                    request,
                    binding,
                    parent,
                    source_parent,
                    deployments,
                    deadline,
                    interrupted,
                )
            if request.recovery is not None:
                return None
            original = _original_prepare(actions, scope, request.owner_epoch)
            if original is None:
                return None
            reference = original.allocated_binding_ref
            if request.binding_ref != reference and not (
                request.action == 'OBSERVE' and request.binding_ref is None
            ):
                return None
            digest = decode_task_launch_action(request, project_check=True)
            directories = owner._task_directories.get(scope.key)
            execution = None if directories is None else directories._execution_preparation
            if request.action == 'OBSERVE':
                return _observe(actions, request, reference, execution, project_check=True)
            if execution is None or execution._native is None:
                return None
            if request.action in ('CREATE_SUSPENDED', 'RESUME'):
                if execution._confirmation != original:
                    return None
                check_task_prepare_ack(
                    scope, reference, original.result, run_kind=directories.run_kind
                )
                execution._verify_installation(deadline, interrupted)
            return _dispatch(
                actions, request, original, execution, digest, interrupted, active, deadline
            )
