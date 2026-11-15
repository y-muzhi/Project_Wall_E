"""Private authenticated project-CHECK inputs and release facts."""

from dataclasses import asdict, dataclass

from backend.app.shared.validation import strict_integer

from .check_input_transfer import CheckInputReadDescriptor
from .check_runner_bundle import exact_record, reference, valid_sha256
from .content_manifest import ContentLimits
from .guard_task_launch_protocol import launch_stdio_descriptor
from .guard_task_network import decode_check_network
from .runtime_launch_journal import LaunchOutcomeUnknown, TestingLaunchScope
from .windows_check_driver_pipe import DriverPipeOffer
from .windows_job import MAX_JOB_PROCESSES
from .windows_local_paths import FileIdentity
from .windows_task_directories import (
    CHECK_DRIVER_KIND,
    PROJECT_CHECK_PURPOSE,
    ProjectCheckInput,
    SnapshotCheckInput,
    decode_project_check_input,
)


class ProjectCheckProtocolError(LaunchOutcomeUnknown):
    pass


def is_project_check_prepare(request):
    return (
        request.action == 'PREPARE'
        and request.input.get('run_kind') in ('TASK', CHECK_DRIVER_KIND)
        and request.input.get('execution_purpose') == PROJECT_CHECK_PURPOSE
    )


@dataclass(frozen=True)
class ProjectCheckPreparationInput:
    check: ProjectCheckInput | SnapshotCheckInput
    runner_ref: str
    command_id: str
    command_sha256: str
    capsule: CheckInputReadDescriptor
    limits: ContentLimits
    stdio: object
    application_endpoint: tuple[str, int] | None
    fixture_sha256: str | None


@dataclass(frozen=True)
class BrowserDriverPreparationInput:
    check: ProjectCheckInput | SnapshotCheckInput
    runner_ref: str
    runner_manifest_sha256: str
    case_pack_sha256: str
    active_process_limit: int
    job_memory_limit_bytes: int
    stdio: object
    result_pipe: DriverPipeOffer


def _browser_prepare(request, binding):
    if type(request.scope) is not TestingLaunchScope:
        raise ProjectCheckProtocolError('ORIGINAL_DRIVER_TESTING_SCOPE_REQUIRED')
    value = exact_record(
        request.input,
        (
            'run_kind',
            'execution_purpose',
            'check_input',
            'runner_ref',
            'runner_manifest_sha256',
            'case_pack_sha256',
            'network',
            'stdio',
            'active_process_limit',
            'job_memory_limit_bytes',
            'result_pipe',
        ),
    )
    _, mode = decode_check_network(value['network'], request.scope)
    if mode != 'CLI' or not all(
        valid_sha256(value[name]) for name in ('runner_manifest_sha256', 'case_pack_sha256')
    ):
        raise ProjectCheckProtocolError('ORIGINAL_BROWSER_DRIVER_PREPARE_DIFFERS')
    return BrowserDriverPreparationInput(
        decode_project_check_input(value['check_input'], request.scope),
        reference(value['runner_ref']),
        value['runner_manifest_sha256'],
        value['case_pack_sha256'],
        strict_integer(
            value['active_process_limit'], 'active_process_limit', maximum=MAX_JOB_PROCESSES
        ),
        strict_integer(value['job_memory_limit_bytes'], 'job_memory_limit_bytes'),
        launch_stdio_descriptor(request, binding),
        DriverPipeOffer(
            request.scope,
            binding.controller,
            **exact_record(value['result_pipe'], ('nonce', 'write_handle')),
        ),
    )


def decode_project_check_prepare(request, binding):
    if (
        not is_project_check_prepare(request)
        or request.recovery is not None
        or request.binding_ref is not None
        or request.scope.step_no not in (3, 4)
    ):
        raise ProjectCheckProtocolError('ORIGINAL_PROJECT_CHECK_PREPARE_REQUIRED')
    original = request.input
    if original['run_kind'] == CHECK_DRIVER_KIND:
        return _browser_prepare(request, binding)
    fixed_fixture = original.get('fixture_sha256')
    optional = ('fixture_sha256',) if 'fixture_sha256' in original else ()
    value = exact_record(
        original,
        (
            'run_kind',
            'execution_purpose',
            'check_input',
            'project_command',
            'runner_ref',
            'network',
            'capsule',
            'limits',
            'stdio',
            *optional,
        ),
    )
    check = decode_project_check_input(value['check_input'], request.scope)
    command = exact_record(
        value['project_command'],
        ('command_id', 'definition_sha256', 'active_process_limit', 'job_memory_limit_bytes'),
    )
    network, mode = decode_check_network(value['network'], request.scope)
    if (
        not valid_sha256(command['definition_sha256'])
        or optional
        and (check.owner_kind != 'TESTING' or not valid_sha256(fixed_fixture))
    ):
        raise ProjectCheckProtocolError('ORIGINAL_PROJECT_CHECK_PREPARE_DIFFERS')
    data = exact_record(value['capsule'], ('file', 'sha256', 'byte_count', 'handle'))
    return ProjectCheckPreparationInput(
        check,
        reference(value['runner_ref']),
        reference(command['command_id']),
        command['definition_sha256'],
        CheckInputReadDescriptor(
            binding.controller,
            request.scope,
            FileIdentity(**exact_record(data['file'], FileIdentity.__dataclass_fields__)),
            data['sha256'],
            data['byte_count'],
            data['handle'],
        ),
        ContentLimits(**exact_record(value['limits'], ContentLimits.__dataclass_fields__)),
        launch_stdio_descriptor(request, binding),
        network['application'][0] if mode == 'HTTP' else None,
        fixed_fixture,
    )


def check_project_release(value, scope, reference):
    row = exact_record(value, ('check', 'source_integrity', 'exit'))
    decode_project_check_input(row['check'], scope)
    if row['source_integrity'] not in ('VERIFIED', 'CHANGED', 'UNKNOWN', 'NOT_CHECKED'):
        raise ProjectCheckProtocolError('ORIGINAL_PROJECT_CHECK_INTEGRITY_DIFFERS')
    exit = row['exit']
    if exit is None:
        return
    exit = exact_record(
        exit, ('scope', 'binding_ref', 'stop_receipt_sha256', 'exit_code', 'terminated')
    )
    if (
        exit['scope'] != asdict(scope)
        or exit['binding_ref'] != reference
        or not valid_sha256(exit['stop_receipt_sha256'])
        or type(exit['exit_code']) is not int
        or not 0 <= exit['exit_code'] <= 0xFFFFFFFF
        or type(exit['terminated']) is not bool
    ):
        raise ProjectCheckProtocolError('ORIGINAL_PROJECT_CHECK_EXIT_DIFFERS')
