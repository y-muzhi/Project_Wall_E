"""Suspended CONTROL_GIT creation with the original ordinary controller token.

Registered commands are the fixed version probe, private config parser and typed repository reads.
This is the native launch adapter, not a privileged Pipe endpoint, deployed Guard,
Git configuration admission or a TASK/CHECK_DRIVER/LPAC fallback.
"""

import ctypes
import hashlib
import json
import ntpath
import subprocess
from ctypes import wintypes
from dataclasses import asdict
from threading import RLock
from uuid import uuid4

from .git_bundle import BUNDLE_PARENT, verify_bundle_bytes
from .git_content_command import GuardContentGitCommand
from .git_config_command import ConfigParseCommand
from .git_metadata_command import GuardRepositoryCommand, RepositoryMetadataCommand
from .git_object_read import RepositoryObjectCommand
from .runtime_launch_journal import LaunchFence, LaunchScope
from .windows_controller_token import ControllerPrimaryToken, _read_token
from .windows_executable_pin import ExecutablePin
from .windows_job import OwnedJob
from .windows_local_paths import LocalPathGuard
from .windows_process import NativeProcessObservation, _creation_time, _identity
from .windows_process import _api as process_api
from .windows_stdio import GuardStandardIO

METADATA_COMMAND_TYPES = (RepositoryMetadataCommand, GuardRepositoryCommand)
TYPED_COMMANDS = (
    ConfigParseCommand,
    *METADATA_COMMAND_TYPES,
    RepositoryObjectCommand,
    GuardContentGitCommand,
)


class NativeLaunchError(RuntimeError):
    def __init__(self, code, native_error=None):
        self.code = code
        self.native_error = native_error
        super().__init__(code)


class StartupInfo(ctypes.Structure):
    _fields_ = [
        ('cb', wintypes.DWORD),
        ('reserved', wintypes.LPWSTR),
        ('desktop', wintypes.LPWSTR),
        ('title', wintypes.LPWSTR),
        ('x', wintypes.DWORD),
        ('y', wintypes.DWORD),
        ('x_size', wintypes.DWORD),
        ('y_size', wintypes.DWORD),
        ('x_count', wintypes.DWORD),
        ('y_count', wintypes.DWORD),
        ('fill', wintypes.DWORD),
        ('flags', wintypes.DWORD),
        ('show', wintypes.WORD),
        ('reserved_size', wintypes.WORD),
        ('reserved_bytes', wintypes.LPVOID),
        ('stdin', wintypes.HANDLE),
        ('stdout', wintypes.HANDLE),
        ('stderr', wintypes.HANDLE),
    ]


class StartupInfoEx(ctypes.Structure):
    _fields_ = [('startup', StartupInfo), ('attributes', wintypes.LPVOID)]


class ProcessInfo(ctypes.Structure):
    _fields_ = [
        ('process', wintypes.HANDLE),
        ('thread', wintypes.HANDLE),
        ('pid', wintypes.DWORD),
        ('tid', wintypes.DWORD),
    ]


def _failure(code):
    return NativeLaunchError(code, ctypes.get_last_error())


def _api():
    kernel, security = process_api()
    if (ctypes.sizeof(StartupInfo), ctypes.sizeof(StartupInfoEx), ctypes.sizeof(ProcessInfo)) != (
        104,
        112,
        24,
    ):
        raise NativeLaunchError('NATIVE_STARTUP_LAYOUT_UNSUPPORTED')
    security.CreateProcessAsUserW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPCWSTR,
        wintypes.LPVOID,
        ctypes.POINTER(ProcessInfo),
    ]
    security.CreateProcessAsUserW.restype = wintypes.BOOL
    kernel.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel.ResumeThread.restype = wintypes.DWORD
    kernel.GetProcessIdOfThread.argtypes = [wintypes.HANDLE]
    kernel.GetProcessIdOfThread.restype = wintypes.DWORD
    kernel.GetThreadId.argtypes = [wintypes.HANDLE]
    kernel.GetThreadId.restype = wintypes.DWORD
    kernel.GetHandleInformation.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetHandleInformation.restype = wintypes.BOOL
    kernel.GetWindowsDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    kernel.GetWindowsDirectoryW.restype = wintypes.UINT
    return kernel, security


def _canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
        allow_nan=False,
    ).encode('utf-8')


def _command(pin, arguments):
    if type(pin) is not ExecutablePin:
        raise NativeLaunchError('ORIGINAL_EXECUTABLE_PIN_REQUIRED')
    if pin.path != BUNDLE_PARENT / 'win-x64/cmd/git.exe':
        raise NativeLaunchError('REGISTERED_CONTROL_GIT_PROGRAM_REQUIRED')
    # No arbitrary Git switches, aliases, -c, shell, helper or script entry.
    if type(arguments) in TYPED_COMMANDS:
        argv = arguments.arguments()
    elif type(arguments) is tuple and arguments == ('--version',):
        argv = arguments
    else:
        raise NativeLaunchError('CONTROL_GIT_COMMAND_NOT_REGISTERED')
    command = subprocess.list2cmdline([str(pin.path), *argv])
    if len(command.encode('utf-16-le')) // 2 + 1 > 32767:
        raise NativeLaunchError('NATIVE_COMMAND_LINE_TOO_LONG')
    return command


def _objects(controller, pin, job, streams, directory, scope, arguments):
    _command(pin, arguments)
    if (
        type(controller) is not ControllerPrimaryToken
        or type(job) is not OwnedJob
        or type(streams) is not GuardStandardIO
        or type(directory) is not LocalPathGuard
        or not isinstance(scope, LaunchScope)
    ):
        raise NativeLaunchError('ORIGINAL_NATIVE_RESOURCES_REQUIRED')
    if (
        streams._controller_token is not controller
        or streams.binding.owner != controller._expected
        or streams.binding.scope != scope
    ):
        raise NativeLaunchError('NATIVE_ORIGINAL_OWNER_OR_SCOPE_DIFFERS')
    if not directory.directory:
        raise NativeLaunchError('NATIVE_WORKING_DIRECTORY_REQUIRED')
    facts = {
        'protocol': 'WIN20-ISOLATION-1',
        'run_kind': 'CONTROL_GIT',
        'scope': asdict(scope),
        'controller': asdict(controller._expected),
        'token': asdict(controller.identity),
        'image': asdict(pin.verify()),
        'directory': asdict(directory.verify()),
        'arguments': list(
            arguments.arguments() if type(arguments) in TYPED_COMMANDS else arguments
        ),
        'stdio': asdict(streams.binding),
        'process_limit': job._process_limit,
        'job_memory_limit_bytes': job._memory_limit,
        'environment_policy': 'FIXED_GIT_VERSION_PROBE_1',
    }
    if type(arguments) is ConfigParseCommand:
        facts['environment_policy'] = 'FIXED_PRIVATE_CONFIG_PARSE_1'
        facts['config_command'] = arguments.facts(directory)
    elif type(arguments) in METADATA_COMMAND_TYPES:
        facts['environment_policy'] = 'FIXED_REPOSITORY_METADATA_1'
        facts['metadata_command'] = arguments.facts(directory)
    elif type(arguments) is RepositoryObjectCommand:
        facts['environment_policy'] = 'FIXED_REPOSITORY_OBJECT_1'
        facts['object_command'] = arguments.facts(directory)
    elif type(arguments) is GuardContentGitCommand:
        facts['environment_policy'] = 'FIXED_CONTENT_PACKAGE_GIT_1'
        facts['content_command'] = arguments.facts(directory)
    return facts


def control_git_input_sha256(controller, pin, job, streams, directory, scope, arguments):
    """Used BEFORE journal.prepare; native creation recalculates the same input."""
    return hashlib.sha256(
        _canonical(_objects(controller, pin, job, streams, directory, scope, arguments))
    ).hexdigest()


def _fence(fence, scope, digest, phase, resource_ref=None):
    if type(fence) is not LaunchFence or fence.scope != scope or fence.stop_closed:
        raise NativeLaunchError('ORIGINAL_OPEN_LAUNCH_FENCE_REQUIRED')
    if fence.input_sha256 != digest:
        raise NativeLaunchError('ORIGINAL_NATIVE_INPUT_DIFFERS')
    if phase == 'CREATE':
        if fence.create_state != 'MAY_HAVE_BEEN_SENT' or fence.resource_ref is not None:
            raise NativeLaunchError('PERSISTED_CREATE_DISPATCH_REQUIRED')
        if fence.resume_state != 'NONE':
            raise NativeLaunchError('ORIGINAL_RESUME_PHASE_INVALID')
    elif (
        fence.create_state != 'RESOURCE_RECORDED'
        or fence.resource_ref != resource_ref
        or fence.resume_state != 'MAY_HAVE_BEEN_SENT'
    ):
        raise NativeLaunchError('PERSISTED_RESUME_DISPATCH_REQUIRED')


class SuspendedControlGit:
    """Own original process/thread handles; never open another PID to recover."""

    def __init__(
        self,
        controller,
        pin,
        job,
        streams,
        directory,
        *,
        scope,
        fence,
        arguments,
        run_kind='CONTROL_GIT',
    ):
        if run_kind != 'CONTROL_GIT':
            raise NativeLaunchError('TASK_REQUIRES_ADMITTED_LPAC')
        digest = control_git_input_sha256(
            controller,
            pin,
            job,
            streams,
            directory,
            scope,
            arguments,
        )
        _fence(fence, scope, digest, 'CREATE')
        # Verify the complete source ZIP authority/inventory, not local manifest claims.
        _, _, bundle_sha256 = verify_bundle_bytes()
        self._gate = RLock()
        self._controller, self._pin, self._job = controller, pin, job
        self._streams, self._directory = streams, directory
        self.scope, self.input_sha256 = scope, digest
        self.resource_ref = uuid4().hex
        self.bundle_manifest_sha256 = bundle_sha256
        self._kernel, self._security = _api()
        self._info = ProcessInfo()
        self._created = False
        self._validated = False
        self._closing = False
        self._exit_observed = False
        self._identity = None
        self._validation_token = None
        self._resume_state = 'NONE'
        self._arguments = arguments
        self._argument_context = None
        try:
            if type(arguments) in TYPED_COMMANDS:
                self._argument_context = arguments.hold(directory)
                self._argument_context.__enter__()
            self._create(arguments)
        except BaseException as error:
            if self._created:
                # This owner MUST be registered by the caller even if no reply can
                # be sent. Keep the suspended/unknown original in its original Job.
                unknown = NativeLaunchError('CREATED_NATIVE_RESOURCE_REQUIRES_OBSERVATION')
                unknown.retained_owner = self
                raise unknown from error
            try:
                self._release_argument_context()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from error
            raise

    def _release_argument_context(self):
        if self._argument_context is not None:
            context, self._argument_context = self._argument_context, None
            # Typed owners recheck on exit but must release their borrow even
            # when a read-only observation detects source changes.
            context.__exit__(None, None, None)

    @property
    def identity(self):
        return self._identity

    @property
    def resume_state(self):
        return self._resume_state

    def _environment(self):
        directory = str(self._directory.path)
        windows = ctypes.create_unicode_buffer(32768)
        count = self._kernel.GetWindowsDirectoryW(windows, len(windows))
        if not 1 <= count < len(windows):
            raise _failure('NATIVE_WINDOWS_DIRECTORY_UNAVAILABLE')
        # No inherited PATH, provider secrets or personal Git environment. NUL is
        # a program-fixed Windows empty stream for this version-only command.
        values = {
            'SystemRoot': windows.value,
            'WINDIR': windows.value,
            'TEMP': directory,
            'TMP': directory,
            'HOME': directory,
            'XDG_CONFIG_HOME': directory,
            'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_SYSTEM': 'NUL',
            'GIT_CONFIG_GLOBAL': 'NUL',
            'GIT_ATTR_NOSYSTEM': '1',
            'GIT_TERMINAL_PROMPT': '0',
            'GIT_NO_REPLACE_OBJECTS': '1',
        }
        if type(self._arguments) in TYPED_COMMANDS:
            values = self._arguments.environment(windows.value)
        raw = '\0'.join(f'{key}={values[key]}' for key in sorted(values, key=str.upper)) + '\0\0'
        if len(raw.encode('utf-16-le')) // 2 > 32767:
            raise NativeLaunchError('NATIVE_ENVIRONMENT_TOO_LONG')
        return ctypes.create_unicode_buffer(raw)

    def _create(self, arguments):
        with self._controller.creation_handle() as token, self._pin.creation_path() as application:
            self._directory.verify()
            with (
                self._streams.creation_handles() as handles,
                self._job.process_creation_attributes(stdio_handles=handles) as attrs,
            ):
                startup = StartupInfoEx()
                startup.startup.cb = ctypes.sizeof(startup)
                startup.startup.flags = 0x1 | 0x100
                startup.startup.show = 0
                startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = handles
                startup.attributes = attrs
                command = ctypes.create_unicode_buffer(_command(self._pin, arguments))
                environment = self._environment()
                if not self._security.CreateProcessAsUserW(
                    token,
                    application,
                    command,
                    None,
                    None,
                    True,
                    0x4 | 0x80000 | 0x400 | 0x08000000,
                    environment,
                    str(self._directory.path),
                    ctypes.byref(startup),
                    ctypes.byref(self._info),
                ):
                    failure = _failure('CREATE_PROCESS_AS_USER_UNAVAILABLE')
                    # FALSE output fields are undefined, never native ownership.
                    self._info = ProcessInfo()
                    raise failure
                self._created = True
                self._identity = _identity(
                    self._kernel,
                    self._security,
                    self._info.process,
                    self._info.pid,
                )
                self._verify_created()
                self._validated = True

    def _verify_created(self):
        if self._closing or not self._info.process or not self._info.thread:
            raise NativeLaunchError('ORIGINAL_NATIVE_RESOURCE_CLOSED')
        actual = _identity(self._kernel, self._security, self._info.process, self._info.pid)
        if (
            actual != self._identity
            or actual.is_appcontainer
            or actual.is_lpac is not False
            or actual.is_elevated
            or actual.user_sid != self._controller.identity.user_sid
            or ntpath.normcase(actual.image_path) != ntpath.normcase(str(self._pin.path))
        ):
            raise NativeLaunchError('CREATED_CONTROL_GIT_IDENTITY_DIFFERS')
        for handle in (self._info.process, self._info.thread):
            flags = wintypes.DWORD()
            if (
                not self._kernel.GetHandleInformation(handle, ctypes.byref(flags))
                or flags.value & 1
            ):
                raise _failure('CREATED_NATIVE_HANDLE_INHERITANCE_UNVERIFIED')
        if (
            self._kernel.GetProcessIdOfThread(self._info.thread) != self._info.pid
            or self._kernel.GetThreadId(self._info.thread) != self._info.tid
        ):
            raise NativeLaunchError('CREATED_PRIMARY_THREAD_IDENTITY_DIFFERS')
        inside = wintypes.BOOL()
        with self._job._gate:
            self._job.verify_limits()
            if (
                not self._job._kernel.IsProcessInJob(
                    self._info.process,
                    self._job._require_handle(),
                    ctypes.byref(inside),
                )
                or inside.value != 1
            ):
                raise _failure('CREATED_NATIVE_JOB_UNVERIFIED')
        if self._validation_token is None:
            token = wintypes.HANDLE()
            if not self._security.OpenProcessToken(self._info.process, 0x8, ctypes.byref(token)):
                raise _failure('CREATED_NATIVE_TOKEN_UNAVAILABLE')
            self._validation_token = token.value
        created = _read_token(self._kernel, self._security, self._validation_token)
        original = self._controller.identity
        if (
            created.user_sid != original.user_sid
            or created.authentication_id_hex != original.authentication_id_hex
            or created.session_id != original.session_id
        ):
            raise NativeLaunchError('CREATED_NATIVE_LOGON_IDENTITY_DIFFERS')
        if self._kernel.WaitForSingleObject(self._info.process, 0) != 258:
            raise NativeLaunchError('CREATED_NATIVE_NOT_RUNNING')

    def resume_once(self, fence):
        with self._gate:
            _fence(fence, self.scope, self.input_sha256, 'RESUME', self.resource_ref)
            if not self._validated or self._resume_state != 'NONE':
                raise NativeLaunchError('ORIGINAL_RESUME_REQUIRES_OBSERVATION')
            with self._controller.creation_handle(), self._pin.creation_path():
                self._directory.verify()
                if type(self._arguments) in TYPED_COMMANDS:
                    self._arguments.facts(self._directory)
                self._verify_created()
                # The journal has already durably recorded MAY. Never decrement a
                # second time if the API result or the following postcheck is lost.
                self._resume_state = 'MAY_HAVE_BEEN_SENT'
                previous = self._kernel.ResumeThread(self._info.thread)
                if previous != 1:
                    unknown = _failure('ORIGINAL_RESUME_ACK_UNVERIFIED')
                    unknown.retained_owner = self
                    raise unknown
                self._resume_state = 'ACKNOWLEDGED'

    def observe(self):
        with self._gate:
            if not self._created or not self._info.process:
                raise NativeLaunchError('ORIGINAL_NATIVE_PROCESS_HANDLE_REQUIRED')
            if self.identity is None:
                raise NativeLaunchError('CREATED_IDENTITY_UNVERIFIED')
            if (
                self._kernel.GetProcessId(self._info.process) != self.identity.pid
                or _creation_time(self._kernel, self._info.process)
                != self.identity.creation_time_hex
            ):
                raise NativeLaunchError('ORIGINAL_NATIVE_PROCESS_IDENTITY_DIFFERS')
            actual = self.identity
            state = self._kernel.WaitForSingleObject(self._info.process, 0)
            if state == 258:
                return NativeProcessObservation(actual, 'RUNNING', None)
            if state != 0:
                raise _failure('ORIGINAL_NATIVE_WAIT_UNVERIFIED')
            code = wintypes.DWORD()
            if not self._kernel.GetExitCodeProcess(self._info.process, ctypes.byref(code)):
                raise _failure('ORIGINAL_NATIVE_EXIT_UNVERIFIED')
            self._exit_observed = True
            return NativeProcessObservation(actual, 'EXITED', code.value)

    def close(self):
        with self._gate:
            if self._created and not self._exit_observed:
                state = self._kernel.WaitForSingleObject(self._info.process, 0)
                if state != 0:
                    error = NativeLaunchError('ORIGINAL_NATIVE_PROCESS_STILL_ACTIVE_OR_UNKNOWN')
                    error.retained_owner = self
                    raise error
                # Even a partially validated creation retains the exact original
                # handle. Signaled permits handle cleanup, never Task STOP.
                self._exit_observed = True
            if self._argument_context is not None and self._created:
                members = self._job.observe_members()
                if not members.complete or members.process_ids or members.assigned_count:
                    error = NativeLaunchError('ORIGINAL_COMMAND_JOB_STILL_ACTIVE_OR_UNKNOWN')
                    error.retained_owner = self
                    raise error
            self._closing = True
            failures = []
            for owner, name in (
                (self, '_validation_token'),
                (self._info, 'thread'),
                (self._info, 'process'),
            ):
                handle = getattr(owner, name)
                if handle is not None:
                    if self._kernel.CloseHandle(handle):
                        setattr(owner, name, None)
                    else:
                        failures.append(ctypes.get_last_error())
            if failures:
                error = NativeLaunchError('ORIGINAL_NATIVE_CLOSE_UNVERIFIED', failures[0])
                error.retained_owner = self
                raise error
            try:
                self._release_argument_context()
            except BaseException as error:
                error.retained_owner = self
                raise
            # Job, token, program pin, STDIO and directory are BORROWED resources.
            # Their original registry owners release them after original facts.
