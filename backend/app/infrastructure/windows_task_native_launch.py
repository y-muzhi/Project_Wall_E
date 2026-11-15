"""Own one original suspended TASK root and its durable native lifecycle."""

import ctypes
import hashlib
import subprocess
from contextlib import nullcontext
from ctypes import wintypes
from dataclasses import asdict, dataclass
from time import monotonic, sleep
from uuid import uuid4

from .guard_task_files import _publish_original, _read_original
from .opencode_control import OpenCodeControlCredential
from .opencode_task_launch import TaskProgramOwner
from .runtime_launch_journal import LaunchOutcomeUnknown, LaunchScope, _bytes
from .windows_check_driver_pipe import GuardDriverResultWriter
from .windows_check_driver_program import BrowserDriverProgram
from .windows_check_logon import CheckLogonSession
from .windows_job import JobMembers, OwnedJob
from .windows_local_paths import local_absolute_path
from .windows_lpac_access import verify_lpac_task_access
from .windows_lpac_profile import TaskLpacProfile
from .windows_lpac_token import LpacProcessToken
from .windows_native_process import ProcessInfo, StartupInfoEx, _api, _failure, _fence
from .windows_process import _creation_time
from .windows_project_check_command import ProjectCheckNetwork, ProjectCheckProgram
from .windows_stdio import GuardStandardIO
from .windows_task_directories import TaskLpacDirectories
from .windows_task_runtime_environment import TaskRuntimeEnvironment
from .windows_task_workspace_tree import hold_task_workspace_tree

_EMPTY_JOB = JobMembers((), 0, True)
_RECORD_BYTES = 16384
_CREATE_FLAGS = 0x4 | 0x80000 | 0x400 | 0x08000000


def _environment_block(values):
    if type(values) is not dict or not values:
        raise LaunchOutcomeUnknown('ORIGINAL_TASK_NATIVE_ENVIRONMENT_REQUIRED')
    names = set()
    for name, value in values.items():
        if (
            type(name) is not str
            or not name
            or '=' in name
            or '\0' in name
            or name.upper() in names
            or type(value) is not str
            or '\0' in value
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_TASK_NATIVE_ENVIRONMENT_INVALID')
        names.add(name.upper())
    raw = '\0'.join(f'{name}={values[name]}' for name in sorted(values, key=str.upper)) + '\0\0'
    if len(raw.encode('utf-16-le')) // 2 > 32767:
        raise LaunchOutcomeUnknown('ORIGINAL_TASK_NATIVE_ENVIRONMENT_TOO_LONG')
    return ctypes.create_unicode_buffer(raw)


@dataclass(frozen=True)
class ProjectCheckExit:
    scope: LaunchScope
    binding_ref: str
    stop_receipt_sha256: str
    exit_code: int
    terminated: bool


class TaskNativeLaunch:
    def __init__(self, directories, job, profile, program, *, streams=None):
        if (
            type(directories) is not TaskLpacDirectories
            or type(job) is not OwnedJob
            or type(profile) is not TaskLpacProfile
            or profile._dirs is not directories
            or profile._job is not job
            or (
                directories.is_project_check
                and (
                    type(program)
                    is not (
                        BrowserDriverProgram
                        if directories.is_browser_driver
                        else ProjectCheckProgram
                    )
                    or program._dirs is not directories
                )
            )
            or (not directories.is_project_check and type(program) is not TaskProgramOwner)
            or program.plan.active_process_limit != job._process_limit
            or program.plan.job_memory_limit_bytes != job._memory_limit
            or streams is not None
            and (
                type(streams) is not GuardStandardIO
                or streams._controller_token is not directories._controller
                or streams.binding.scope != directories.scope
            )
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_TASK_NATIVE_OWNERS_REQUIRED')
        self._dirs, self._job, self._profile, self._program = directories, job, profile, program
        self._streams = streams
        self._driver_result = None
        self._journal = directories._actions._journal
        self._scope = directories.scope
        self._kernel, self._security = _api()
        self._info = ProcessInfo()
        self._resource_ref = uuid4().hex
        self._record_name = self._scope.key + '.task-native-suspended.json'
        self._stop_name = self._scope.key + '.task-native-stopped.json'
        self._created = self._resume_may = self._resumed = False
        self._input = self._token = self._identity = None
        self._receipt = self._receipt_candidate = None
        self._access = self._access_inputs = None
        self._project_network = self._project_facts = None
        self._project_terminated = False
        self._check_session = None

    def bind_project_streams(self, streams):
        if (
            not self._dirs.is_project_check
            or self._input is not None
            or self._streams is not None
            or type(streams) is not GuardStandardIO
            or streams._controller_token is not self._dirs._controller
            or streams.binding.scope != self._scope
        ):
            raise LaunchOutcomeUnknown('PROJECT_CHECK_ORIGINAL_STDIO_REQUIRED')
        self._streams = streams

    def bind_driver_result(self, result):
        if (
            not self._dirs.is_browser_driver
            or self._input is not None
            or self._driver_result is not None
            or type(result) is not GuardDriverResultWriter
            or result._controller is not self._dirs._controller
            or result.binding.scope != self._scope
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_DRIVER_RESULT_REQUIRED')
        self._driver_result = result

    def _require_open(self, checkpoint):
        checkpoint()
        self._journal._require_controller_open(self._scope)
        fence = self._journal.inspect(self._scope)
        if (
            self._scope.key in self._journal._volatile_closed
            or fence is not None
            and fence.stop_closed
            or self._dirs._actions.find(self._scope, 'STOP') is not None
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_TASK_NATIVE_LAUNCH_CLOSED')
        return fence

    def _lpac_capability_names(self):
        if not self._dirs.is_browser_driver:
            return ()
        if self._program._facts is None:
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_DRIVER_NOT_PREPARED')
        return self._program._facts.lpac_capability_names

    def _launch_source(self):
        if not self._dirs.is_browser_driver:
            return self._dirs._controller
        if self._check_session is None:
            try:
                self._check_session = CheckLogonSession(self._dirs._controller)
            except BaseException as error:
                retained = getattr(error, 'retained_owner', None)
                if type(retained) is CheckLogonSession:
                    self._check_session = retained
                raise
        return self._check_session

    def _native_create(self, environment, working_directory, checkpoint):
        fence = self._require_open(checkpoint)
        _fence(fence, self._scope, self._input, 'CREATE')
        pin = self._program._image
        self._profile.verify_identity()
        if self._job.observe_members() != _EMPTY_JOB:
            raise LaunchOutcomeUnknown('ORIGINAL_TASK_NATIVE_JOB_NOT_EMPTY')
        borrowed = nullcontext(()) if self._streams is None else self._streams.creation_handles()
        if self._dirs.is_browser_driver and self._driver_result is None:
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_DRIVER_RESULT_REQUIRED')
        result_handle = (
            nullcontext(None)
            if self._driver_result is None
            else self._driver_result.creation_handle(self._scope)
        )
        source = self._launch_source()
        with (
            source.creation_handle() as token,
            pin.creation_path() as application,
            borrowed as handles,
            result_handle as result,
            self._job.process_creation_attributes(
                stdio_handles=handles,
                lpac_profile=self._dirs.profile,
                driver_result_handle=result,
                lpac_capability_names=self._lpac_capability_names(),
            ) as attributes,
        ):
            startup = StartupInfoEx()
            startup.startup.cb = ctypes.sizeof(startup)
            startup.startup.flags = 1
            if handles:
                startup.startup.flags |= 0x100
                startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = handles
            startup.attributes = attributes
            argv = [application, *self._program.plan.arguments]
            if result is not None:
                argv.extend(('--result-handle', f'{result:016x}'))
            command = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
            with self._journal._gate:
                self._require_open(checkpoint)
                if not self._security.CreateProcessAsUserW(
                    token,
                    application,
                    command,
                    None,
                    None,
                    bool(handles or result is not None),
                    _CREATE_FLAGS,
                    environment,
                    str(working_directory),
                    ctypes.byref(startup),
                    ctypes.byref(self._info),
                ):
                    self._info = ProcessInfo()
                    raise _failure('ORIGINAL_TASK_CREATE_AS_USER_UNAVAILABLE')
                self._created = True
            self._identity = (self._info.pid, _creation_time(self._kernel, self._info.process))
            try:
                self._token = LpacProcessToken(
                    self._info,
                    self._job,
                    self._profile,
                    pin,
                    capability_names=self._lpac_capability_names(),
                    launch_source=source,
                )
            except BaseException as error:
                retained = getattr(error, 'retained_owner', None)
                if type(retained) is LpacProcessToken:
                    self._token = retained
                raise
            self._access = verify_lpac_task_access(
                self._token, self._dirs, *self._access_inputs, checkpoint
            )
            return self._resource_ref

    def _receipt_data(self, fence, token, access):
        return {
            'schema_version': 1,
            'scope': self._scope.key,
            'launch_input_sha256': self._input,
            'binding_ref': self._dirs.binding_ref,
            'resource_ref': fence.resource_ref,
            'pid': token.process.pid,
            'creation_time_hex': token.process.creation_time_hex,
            'thread_id': self._info.tid,
            'token_sha256': hashlib.sha256(_bytes(asdict(token))).hexdigest(),
            'access_sha256': access.checks_sha256,
            **(
                {
                    'driver_result_binding': asdict(self._driver_result.binding),
                    'driver_logon_source': asdict(self._token._launch_source.identity),
                }
                if self._dirs.is_browser_driver
                else {}
            ),
        }

    def create(
        self,
        launch_input_sha256,
        environment,
        credential,
        read_only_members,
        protected,
        checkpoint,
        *,
        workspace_tree_sha256,
    ):
        if self._dirs.is_project_check:
            raise LaunchOutcomeUnknown('PROJECT_CHECK_LAUNCH_INPUT_REQUIRED')
        with self._journal._scope(self._scope):
            self._verify_first_create(launch_input_sha256, checkpoint)
            if (
                type(environment) is not TaskRuntimeEnvironment
                or environment._dirs is not self._dirs
                or type(credential) is not OpenCodeControlCredential
            ):
                raise LaunchOutcomeUnknown('ORIGINAL_TASK_NATIVE_ENVIRONMENT_OWNER_REQUIRED')
            block = _environment_block(
                environment.launch_values(credential, self._program.plan, checkpoint)
            )
            destination = self._dirs.workspace_destination().directory
            return self._create_original(
                launch_input_sha256,
                block,
                local_absolute_path(destination.canonical_path),
                destination,
                workspace_tree_sha256,
                read_only_members,
                protected,
                checkpoint,
            )

    def _verify_first_create(self, launch_input_sha256, checkpoint, *, inspection_checkpoint=None):
        if self._input is not None:
            raise LaunchOutcomeUnknown('ORIGINAL_TASK_NATIVE_CREATE_REQUIRES_OBSERVATION')
        fence = self._require_open(checkpoint)
        if fence is not None and (
            fence.input_sha256 != launch_input_sha256
            or fence.create_state != 'NONE'
            or self._dirs._launch_read_ack is None
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_TASK_NATIVE_LAUNCH_ALREADY_EXISTS')
        self._dirs._require_open(lambda: False)
        if self._dirs.is_browser_driver:
            self._program.verify(
                checkpoint if inspection_checkpoint is None else inspection_checkpoint
            )
        else:
            self._program.verify()
        self._profile.verify_identity()

    def _create_original(
        self,
        digest,
        environment,
        working_directory,
        destination,
        tree_sha256,
        read_only_members,
        protected,
        checkpoint,
        *,
        inspection_checkpoint=None,
        launch_handle_limit=None,
    ):
        self._access_inputs = dict(read_only_members), protected
        try:
            with hold_task_workspace_tree(
                local_absolute_path(destination.canonical_path),
                destination,
                tree_sha256,
                checkpoint if inspection_checkpoint is None else inspection_checkpoint,
                launch_handle_limit=launch_handle_limit,
            ):
                self._input = digest
                self._journal.prepare(self._scope, digest)
                fence = self._journal.dispatch_create(
                    self._scope,
                    digest,
                    lambda: self._native_create(environment, working_directory, checkpoint),
                )
            if fence.stop_closed or fence.resource_ref != self._resource_ref:
                raise LaunchOutcomeUnknown('ORIGINAL_TASK_NATIVE_CREATE_UNVERIFIED')
            raw = _bytes(self._receipt_data(fence, self._token.verify(), self._access))
            self._receipt_candidate = raw
            _publish_original(self._journal._package, self._record_name, raw, _RECORD_BYTES)
            checkpoint()
            result = self.observe()
            if result['receipt_sha256'] is None:
                raise LaunchOutcomeUnknown('ORIGINAL_TASK_NATIVE_RECEIPT_UNVERIFIED')
            return result
        except BaseException as error:
            error.retained_owner = self
            raise

    def project_launch_input(self, environment, network, protected, checkpoint):
        if (
            not self._dirs.is_project_check
            or self._dirs.is_browser_driver
            or type(environment) is not TaskRuntimeEnvironment
            or environment._dirs is not self._dirs
            or type(network) is not ProjectCheckNetwork
            or network._dirs is not self._dirs
            or type(protected) is not tuple
            or not protected
            or self._dirs._check_publication is None
        ):
            raise LaunchOutcomeUnknown('PROJECT_CHECK_LAUNCH_RESOURCES_REQUIRED')
        self._require_open(checkpoint)
        facts = self._dirs._check_publication.verify(checkpoint)
        self._program.check_working_directory(facts)
        image = self._program.verify()
        network.verify(checkpoint)
        evidence = environment.verify(checkpoint)
        fixture = self._project_fixture_facts(checkpoint)
        return hashlib.sha256(
            _bytes(
                {
                    'scope': self._scope.key,
                    'binding_ref': self._dirs.binding_ref,
                    'check': asdict(facts.check),
                    'tree_identity_sha256': facts.tree_identity_sha256,
                    **({'fixture_tree_sha256': fixture.tree_identity_sha256} if fixture else {}),
                    'program': asdict(image),
                    'definition_sha256': self._program.definition.definition_sha256,
                    'arguments': self._program.plan.arguments,
                    'environment': evidence.environment_sha256,
                    'provider': str(network._provider),
                    'sublayer': str(network._sublayer),
                    'protected': [asdict(value) for value in protected],
                    'stdio': None if self._streams is None else asdict(self._streams.binding),
                }
            )
        ).hexdigest()

    def _project_fixture_facts(self, checkpoint):
        source = self._dirs._check_fixture
        expected = self._dirs._prepare_request.input.get('fixture_sha256')
        if (source is None) != (expected is None):
            raise LaunchOutcomeUnknown('ORIGINAL_TESTING_FIXTURE_REQUIRED')
        if source is None:
            return None
        if source._fixture.sha256 != expected:
            raise LaunchOutcomeUnknown('ORIGINAL_TESTING_FIXTURE_DIFFERS')
        return source.verify(checkpoint)

    def create_project_check(self, digest, environment, network, protected, checkpoint):
        with self._journal._scope(self._scope):
            self._verify_first_create(digest, checkpoint)
            if digest != self.project_launch_input(environment, network, protected, checkpoint):
                raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_LAUNCH_INPUT_DIFFERS')
            facts = self._dirs._check_publication.verify(checkpoint)
            directory = self._program.check_working_directory(facts)
            image = self._program.verify()
            fixture = self._project_fixture_facts(checkpoint)
            self._project_network, self._project_facts = network, facts
            return self._create_original(
                digest,
                _environment_block(environment.values(checkpoint)),
                directory,
                facts.directory,
                facts.tree_identity_sha256,
                {
                    'workspace': facts.members,
                    'runtime': (image.file,),
                    'basis': () if fixture is None else fixture.members,
                    'config': (),
                },
                protected,
                checkpoint,
            )

    def browser_launch_input(self, environment, network, protected, checkpoint):
        if (
            not self._dirs.is_browser_driver
            or self._driver_result is None
            or self._streams is None
            or type(environment) is not TaskRuntimeEnvironment
            or environment._dirs is not self._dirs
            or type(network) is not ProjectCheckNetwork
            or network._dirs is not self._dirs
            or type(protected) is not tuple
            or not protected
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_DRIVER_LAUNCH_REQUIRED')
        self._require_open(checkpoint)
        image, files = self._program.verify(checkpoint)
        network.verify(checkpoint)
        facts = environment.verify(checkpoint)
        return hashlib.sha256(
            _bytes(
                {
                    'run_kind': self._dirs.run_kind,
                    'scope': self._scope.key,
                    'binding_ref': self._dirs.binding_ref,
                    'check': asdict(self._dirs.check_input),
                    'runner_manifest_sha256': self._program.driver.runner.manifest_sha256,
                    'lpac_capability_names': files.lpac_capability_names,
                    'case_pack_sha256': self._dirs._prepare_request.input['case_pack_sha256'],
                    'tree_identity_sha256': files.tree_identity_sha256,
                    'program': asdict(image),
                    'arguments': self._program.plan.arguments,
                    'environment': facts.environment_sha256,
                    'provider': str(network._provider),
                    'sublayer': str(network._sublayer),
                    'protected': [asdict(value) for value in protected],
                    'stdio': asdict(self._streams.binding),
                    'driver_result_binding': asdict(self._driver_result.binding),
                }
            )
        ).hexdigest()

    def create_browser_driver(
        self, digest, environment, network, protected, checkpoint, *, inspection_checkpoint=None
    ):
        with self._journal._scope(self._scope):
            inspection = checkpoint if inspection_checkpoint is None else inspection_checkpoint
            self._verify_first_create(digest, checkpoint, inspection_checkpoint=inspection)
            if digest != self.browser_launch_input(environment, network, protected, inspection):
                raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_DRIVER_INPUT_DIFFERS')
            _, facts = self._program.verify(inspection)
            workspace = self._dirs._directories['workspace']
            workspace.verify()
            if any(workspace.path.iterdir()):
                raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_DRIVER_WORKSPACE_NOT_EMPTY')
            self._project_network, self._project_facts = network, facts
            return self._create_original(
                digest,
                _environment_block(environment.values(checkpoint)),
                workspace.path,
                facts.directory,
                facts.tree_identity_sha256,
                {'workspace': (), 'runtime': facts.members, 'basis': (), 'config': ()},
                protected,
                checkpoint,
                inspection_checkpoint=inspection,
                launch_handle_limit=32768,
            )

    def observe(self):
        with self._journal._scope(self._scope):
            fence = self._journal.inspect(self._scope)
            members = self._job.observe_members()
            receipt = None
            if self._receipt_candidate is not None:
                actual = _read_original(self._journal._package, self._record_name, _RECORD_BYTES)
                if actual == self._receipt_candidate:
                    self._receipt = actual
                    receipt = hashlib.sha256(actual).hexdigest()
                elif actual is not None or self._receipt is not None:
                    raise LaunchOutcomeUnknown('ORIGINAL_TASK_NATIVE_RECEIPT_UNVERIFIED')
            state = self._root_state()
            if state == 'NOT_CREATED' and fence is not None and fence.create_state != 'NONE':
                state = 'UNKNOWN'
            return {
                'run_kind': self._dirs.run_kind,
                'resource_ref': self._resource_ref if self._created else None,
                'receipt_sha256': receipt,
                'process_identity': (
                    None
                    if self._token is None or self._token._evidence is None
                    else self._token._evidence.process
                ),
                'process_state': state,
                'job': members,
                'fence': fence,
            }

    def _root_state(self):
        if not self._created:
            return 'UNKNOWN' if self._input is not None else 'NOT_CREATED'
        handle = self._info.process
        if (
            self._identity is None
            or self._kernel.GetProcessId(handle) != self._identity[0]
            or _creation_time(self._kernel, handle) != self._identity[1]
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_TASK_NATIVE_ROOT_IDENTITY_UNVERIFIED')
        wait = self._kernel.WaitForSingleObject(handle, 0)
        if wait == 0:
            return 'EXITED'
        if wait != 258:
            raise _failure('ORIGINAL_TASK_NATIVE_ROOT_STATE_UNVERIFIED')
        if self._resumed:
            return 'RUNNING'
        return 'UNKNOWN' if self._resume_may or self._receipt is None else 'SUSPENDED'

    def resume(self, receipt_sha256, checkpoint):
        with self._journal._scope(self._scope):
            self._require_open(checkpoint)
            observed = self.observe()
            if (
                observed['process_state'] != 'SUSPENDED'
                or observed['receipt_sha256'] is None
                or observed['receipt_sha256'] != receipt_sha256
            ):
                raise LaunchOutcomeUnknown('ORIGINAL_TASK_NATIVE_RESUME_RECEIPT_REQUIRED')
            if self._dirs.is_browser_driver:
                self._project_network.verify(checkpoint)
                _, driver = self._program.verify(checkpoint)
                if driver != self._project_facts:
                    raise LaunchOutcomeUnknown('ORIGINAL_BROWSER_DRIVER_INPUT_DIFFERS')
            elif self._dirs.is_project_check:
                self._project_network.verify(checkpoint)
                facts = self._dirs._check_publication.verify(checkpoint)
                self._project_fixture_facts(checkpoint)
                if facts != self._project_facts:
                    raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_INPUT_DIFFERS')
                self._program.check_working_directory(facts)
                self._program.verify()
            token = self._token.verify()
            access = verify_lpac_task_access(
                self._token, self._dirs, *self._access_inputs, checkpoint
            )
            if _bytes(self._receipt_data(observed['fence'], token, access)) != self._receipt:
                raise LaunchOutcomeUnknown('ORIGINAL_TASK_NATIVE_RESUME_EVIDENCE_DIFFERS')

            def resume_once():
                with self._dirs._controller.creation_handle(), self._journal._gate:
                    self._token.verify()
                    fence = self._require_open(checkpoint)
                    _fence(fence, self._scope, self._input, 'RESUME', self._resource_ref)
                    self._resume_may = True
                    if self._kernel.ResumeThread(self._info.thread) != 1:
                        raise _failure('ORIGINAL_TASK_NATIVE_RESUME_UNVERIFIED')
                    self._resumed = True

            self._journal.dispatch_resume(self._scope, self._resource_ref, resume_once)
            return self.observe()

    def verify_model_root(self, checkpoint):
        if self._dirs.is_project_check:
            raise LaunchOutcomeUnknown('PROJECT_CHECK_MODEL_SOURCE_DENIED')
        with self._journal._scope(self._scope):
            fence = self._require_open(checkpoint)
            observed = self.observe()
            if (
                fence is None
                or fence.resume_state != 'ACKNOWLEDGED'
                or observed['process_state'] != 'RUNNING'
                or observed['receipt_sha256'] is None
                or self._token is None
            ):
                raise LaunchOutcomeUnknown('ORIGINAL_TASK_MODEL_ROOT_UNVERIFIED')
            identity = self._token.verify_running().process
            members = observed['job']
            if not members.complete or identity.pid not in members.process_ids:
                raise LaunchOutcomeUnknown('ORIGINAL_TASK_MODEL_ROOT_JOB_UNVERIFIED')
            self._profile.verify_identity()
            self._require_open(checkpoint)
            return identity, observed['resource_ref']

    def stop(self, checkpoint, *, deadline):
        with self._journal._scope(self._scope):
            fence = self._journal.close_nonce(self._scope)
            if not fence.stop_closed:
                raise LaunchOutcomeUnknown('ORIGINAL_TASK_NATIVE_STOP_FENCE_UNVERIFIED')
            checkpoint()
            if self._created and (
                self._kernel.WaitForSingleObject(self._info.process, 0) != 0
                or self._job.observe_members() != _EMPTY_JOB
            ):
                if self._dirs.is_project_check:
                    self._project_terminated = True
                self._job.terminate_owned(1)
            while True:
                checkpoint()
                observed = self.observe()
                if observed['job'] == _EMPTY_JOB and observed['process_state'] in (
                    'NOT_CREATED',
                    'EXITED',
                ):
                    break
                remaining = deadline - monotonic()
                if remaining <= 0 or not self._created:
                    raise LaunchOutcomeUnknown('ORIGINAL_TASK_NATIVE_STOP_UNVERIFIED')
                sleep(min(remaining, 0.02))
            raw = self._stop_record(observed)
            package = self._journal._package
            if _read_original(package, self._stop_name, _RECORD_BYTES) is None:
                _publish_original(package, self._stop_name, raw, _RECORD_BYTES)
            if _read_original(package, self._stop_name, _RECORD_BYTES) != raw:
                raise LaunchOutcomeUnknown('ORIGINAL_TASK_NATIVE_STOP_RECEIPT_UNVERIFIED')
            return observed

    def _exit_code(self):
        if self._root_state() != 'EXITED':
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_EXIT_NOT_OBSERVED')
        code = wintypes.DWORD()
        if not self._kernel.GetExitCodeProcess(self._info.process, ctypes.byref(code)):
            raise _failure('ORIGINAL_PROJECT_CHECK_EXIT_UNVERIFIED')
        return code.value

    def _stop_record(self, observed):
        facts = {
            'schema_version': 1,
            'scope': self._scope.key,
            'binding_ref': self._dirs.binding_ref,
            'fence': asdict(observed['fence']),
            'resource_ref': observed['resource_ref'],
            'root': self._identity,
            'root_state': observed['process_state'],
            'job': asdict(observed['job']),
        }
        if self._dirs.is_project_check:
            facts['exit_code'] = self._exit_code() if self._created else None
            facts['terminated'] = self._project_terminated
        return _bytes(facts)

    def project_exit(self):
        if not self._dirs.is_project_check:
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_EXIT_REQUIRED')
        with self._journal._scope(self._scope):
            digest = self.stopped_evidence()
            return ProjectCheckExit(
                self._scope,
                self._dirs.binding_ref,
                digest,
                self._exit_code(),
                self._project_terminated,
            )

    def stopped_evidence(self):
        with self._journal._scope(self._scope):
            observed = self.observe()
            fence = observed['fence']
            if (
                fence is None
                or not fence.stop_closed
                or observed['process_state'] not in ('NOT_CREATED', 'EXITED')
                or observed['job'] != _EMPTY_JOB
                or _read_original(self._journal._package, self._stop_name, _RECORD_BYTES)
                != self._stop_record(observed)
            ):
                raise LaunchOutcomeUnknown('ORIGINAL_TASK_NATIVE_STOP_RECEIPT_UNVERIFIED')
            return hashlib.sha256(self._stop_record(observed)).hexdigest()

    def close(self):
        with self._journal._scope(self._scope):
            if self._created:
                fence = self._journal.inspect(self._scope)
                if (
                    fence is None
                    or not fence.stop_closed
                    or self._root_state() != 'EXITED'
                    or self._job.observe_members() != _EMPTY_JOB
                ):
                    raise LaunchOutcomeUnknown('ORIGINAL_TASK_NATIVE_CLOSE_REQUIRES_STOP')
            if self._token is not None:
                self._token.close()
                self._token = None
            for attribute in ('thread', 'process'):
                handle = getattr(self._info, attribute)
                if handle:
                    if not self._kernel.CloseHandle(handle):
                        error = _failure('ORIGINAL_TASK_NATIVE_HANDLE_CLOSE_UNVERIFIED')
                        error.retained_owner = self
                        raise error
                    setattr(self._info, attribute, None)
            if self._check_session is not None:
                self._check_session.close()
                self._check_session = None
            self._created = False
