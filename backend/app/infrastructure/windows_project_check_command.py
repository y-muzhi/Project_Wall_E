"""Pin and prepare an admitted project CHECK command or loopback SERVICE."""

import os
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from time import monotonic
from uuid import UUID

from backend.app.shared.validation import strict_integer

from .check_runner_bundle import exact_record, reference, valid_sha256
from .content_paths import relative_content_path
from .guard_task_network import decode_check_network, verify_installed_task_network
from .runtime_launch_journal import LaunchOutcomeUnknown, _bytes
from .windows_config_source import LockedFileSource
from .windows_executable_pin import ExecutablePin
from .windows_job import MAX_JOB_PROCESSES
from .windows_local_paths import FileIdentity, LocalPathGuard, local_absolute_path
from .windows_task_directories import TaskLpacDirectories

_MAX_EXECUTABLE_BYTES = 256 * 1024**2
_MAX_ARGUMENTS = 128


class ProjectCheckLaunchError(LaunchOutcomeUnknown):
    pass


@dataclass(frozen=True)
class ProjectCheckCommand:
    command_id: str
    executable_ref: str
    argument_template: tuple[str, ...]
    working_directory: str
    purpose: str
    timeout_seconds: int
    network_scope_ref: str | None

    @classmethod
    def decode(cls, value):
        row = exact_record(value, cls.__dataclass_fields__)
        reference(row['command_id'])
        reference(row['executable_ref'])
        strict_integer(row['timeout_seconds'], 'timeout_seconds')
        if row['purpose'] == 'SERVICE':
            reference(row['network_scope_ref'])
        elif row['purpose'] != 'CHECK' or row['network_scope_ref'] is not None:
            raise ProjectCheckLaunchError('ORIGINAL_PROJECT_CHECK_COMMAND_REQUIRED')
        if row['working_directory'] != '.':
            relative_content_path(row['working_directory'])
        arguments = row['argument_template']
        if type(arguments) is not list or len(arguments) > _MAX_ARGUMENTS:
            raise ProjectCheckLaunchError('OFFLINE_PROJECT_CHECK_ARGUMENTS_INVALID')
        for argument in arguments:
            if (
                type(argument) is not str
                or len(argument) > 8192
                or any(ord(char) < 32 or ord(char) == 127 for char in argument)
            ):
                raise ProjectCheckLaunchError('OFFLINE_PROJECT_CHECK_ARGUMENTS_INVALID')
            argument.encode('utf-16-le', errors='strict')
        application_arguments = ('{CHECK_HOST}', '{CHECK_PORT}')
        counts = [arguments.count(value) for value in application_arguments]
        if counts != [int(row['purpose'] == 'SERVICE')] * len(application_arguments):
            raise ProjectCheckLaunchError('ORIGINAL_PROJECT_CHECK_APPLICATION_ARGUMENTS_DIFFER')
        return cls(**{**row, 'argument_template': tuple(arguments)})

    @property
    def definition_sha256(self):
        return sha256(_bytes(asdict(self))).hexdigest()


@dataclass(frozen=True)
class RegisteredCheckExecutable:
    reference: str
    file: FileIdentity = field(repr=False)
    sha256: str
    byte_count: int

    def __post_init__(self):
        reference(self.reference)
        if (
            type(self.file) is not FileIdentity
            or self.file.is_directory
            or self.file.filesystem != 'NTFS'
            or not valid_sha256(self.sha256)
            or type(self.byte_count) is not int
            or not 1 <= self.byte_count <= _MAX_EXECUTABLE_BYTES
        ):
            raise ProjectCheckLaunchError('REGISTERED_PROJECT_CHECK_EXECUTABLE_REQUIRED')


@dataclass(frozen=True)
class _NativeCheckPlan:
    arguments: tuple[str, ...]
    active_process_limit: int
    job_memory_limit_bytes: int


class ProjectCheckProgram:
    """An actual installed program and exact frozen CommandDefinition for one scope."""

    def __init__(self, directories, definition, executable):
        if (
            type(directories) is not TaskLpacDirectories
            or not directories.is_project_check
            or type(definition) is not ProjectCheckCommand
            or type(executable) is not RegisteredCheckExecutable
            or executable.reference != definition.executable_ref
        ):
            raise ProjectCheckLaunchError('REGISTERED_PROJECT_CHECK_COMMAND_REQUIRED')
        request = directories._prepare_request
        pinned = exact_record(
            request.input.get('project_command'),
            ('command_id', 'definition_sha256', 'active_process_limit', 'job_memory_limit_bytes'),
        )
        if (
            pinned['command_id'] != definition.command_id
            or pinned['definition_sha256'] != definition.definition_sha256
        ):
            raise ProjectCheckLaunchError('ORIGINAL_PROJECT_CHECK_COMMAND_DIFFERS')
        processes = strict_integer(
            pinned['active_process_limit'], 'active_process_limit', maximum=MAX_JOB_PROCESSES
        )
        memory = strict_integer(pinned['job_memory_limit_bytes'], 'job_memory_limit_bytes')
        inputs = directories.root / 'workspace'
        variables = {
            '{CHECK_INPUT}': str(inputs),
            '{CHECK_OUTPUT}': str(directories.root / 'scratch' / 'output'),
        }
        network, mode = decode_check_network(request.input['network'], request.scope)
        if (mode == 'HTTP') != (definition.purpose == 'SERVICE'):
            raise ProjectCheckLaunchError('ORIGINAL_PROJECT_CHECK_APPLICATION_MODE_DIFFERS')
        if mode == 'HTTP':
            ((address, port),) = network['application']
            variables.update({'{CHECK_HOST}': address, '{CHECK_PORT}': str(port)})
        fixed_fixture = request.input.get('fixture_sha256')
        fixture_root = directories.root / 'basis'
        args = []
        for argument in definition.argument_template:
            if argument in variables:
                argument = variables[argument]
            elif argument == '{CHECK_FIXTURE}' or argument.startswith('{CHECK_FIXTURE}/'):
                if not valid_sha256(fixed_fixture):
                    raise ProjectCheckLaunchError('ORIGINAL_TESTING_FIXTURE_REQUIRED')
                suffix = argument.removeprefix('{CHECK_FIXTURE}')
                if suffix:
                    relative_content_path(suffix[1:])
                argument = str(fixture_root / suffix.removeprefix('/'))
            elif '{' in argument or '}' in argument:
                raise ProjectCheckLaunchError('UNREGISTERED_PROJECT_CHECK_ARGUMENT_VARIABLE')
            args.append(argument)
        if local_absolute_path(executable.file.canonical_path).is_relative_to(directories.root):
            raise ProjectCheckLaunchError('PROJECT_CHECK_EXECUTABLE_MUST_BE_EXTERNAL')
        self._dirs = directories
        self.definition = definition
        self._registered = executable
        self.plan = _NativeCheckPlan(tuple(args), processes, memory)
        self.working_directory = (
            inputs if definition.working_directory == '.' else inputs / definition.working_directory
        )
        self._image = None
        self._started = False

    def prepare(self, *, deadline, cancelled):
        if self._started:
            raise ProjectCheckLaunchError('ORIGINAL_PROJECT_CHECK_PROGRAM_ALREADY_RESERVED')
        self._started = True

        def interrupted():
            return cancelled() or monotonic() >= deadline

        next_full_check = 0.0

        def checkpoint():
            nonlocal next_full_check
            if interrupted():
                raise ProjectCheckLaunchError('ORIGINAL_PROJECT_CHECK_PROGRAM_INTERRUPTED')
            now = monotonic()
            if now >= next_full_check:
                self._dirs._require_open(interrupted)
                next_full_check = now + 0.1

        self._dirs._require_open(interrupted)
        runtime = self._dirs._directories['runtime']
        runtime.verify()
        registered = self._registered
        destination = runtime.path / 'project.exe'
        if any(runtime.path.iterdir()):
            raise ProjectCheckLaunchError('ORIGINAL_PROJECT_CHECK_RUNTIME_NOT_EMPTY')
        try:
            with LockedFileSource(
                registered.file.canonical_path,
                max_file_bytes=registered.byte_count,
                expected_file=registered.file,
                checkpoint=checkpoint,
                capture_raw=False,
            ) as source:
                blob = source.snapshot
                if (blob.byte_count, blob.sha256) != (registered.byte_count, registered.sha256):
                    raise ProjectCheckLaunchError('REGISTERED_PROJECT_CHECK_BYTES_DIFFER')
                with destination.open('xb') as stream:
                    source.consume_verified(stream.write)
                    stream.flush()
                    os.fsync(stream.fileno())
                self._dirs._require_open(interrupted)
            image = ExecutablePin(
                destination,
                expected_byte_count=registered.byte_count,
                expected_sha256=registered.sha256,
            )
            self._image = image
            image.__enter__()
            self._dirs._require_open(interrupted)
            return self.verify()
        except BaseException as error:
            error.retained_owner = self
            raise

    def verify(self):
        if self._image is None:
            raise ProjectCheckLaunchError('ORIGINAL_PROJECT_CHECK_IMAGE_REQUIRED')
        runtime = self._dirs._directories['runtime']
        runtime.verify()
        actual = self._image.verify()
        if actual.file.canonical_path != str(runtime.path / 'project.exe') or {
            entry.name for entry in runtime.path.iterdir()
        } != {'project.exe'}:
            raise ProjectCheckLaunchError('ORIGINAL_PROJECT_CHECK_RUNTIME_DIFFERS')
        return actual

    def check_working_directory(self, facts):
        matching = [facts.directory, *(value for value in facts.members if value.is_directory)]
        with LocalPathGuard(self.working_directory, directory=True) as guard:
            if guard.verify() not in matching:
                raise ProjectCheckLaunchError('ORIGINAL_PROJECT_CHECK_WORKDIR_DIFFERS')
        return self.working_directory

    def close(self):
        if self._image is not None:
            self._image.close()
            self._image = None


class ProjectCheckNetwork:
    def __init__(self, directories, provider, sublayer):
        if (
            type(directories) is not TaskLpacDirectories
            or not directories.is_project_check
            or type(provider) is not UUID
            or type(sublayer) is not UUID
            or provider.int == 0
            or sublayer.int == 0
        ):
            raise ProjectCheckLaunchError('OFFLINE_PROJECT_CHECK_NETWORK_REQUIRED')
        self._dirs, self._provider, self._sublayer = directories, provider, sublayer
        request = directories._prepare_request
        _, self._mode = decode_check_network(request.input['network'], request.scope)

    @property
    def filter_count(self):
        return 8 if self._mode == 'HTTP' else 6

    def verify(self, checkpoint):
        original = self._dirs._original
        count = verify_installed_task_network(
            self._dirs._actions,
            original.scope,
            original.owner_epoch,
            provider=self._provider,
            sublayer=self._sublayer,
            policy_checkpoint=checkpoint,
            check_mode=self._mode,
        )
        if type(count) is not int or count != self.filter_count:
            raise ProjectCheckLaunchError('OFFLINE_PROJECT_CHECK_NETWORK_UNVERIFIED')
