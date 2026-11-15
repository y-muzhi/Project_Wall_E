"""Classify original project command facts without interpreting project output."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from backend.app.shared.time import utc_milliseconds

from .check_runner_bundle import valid_sha256
from .execution_display_text import UNAVAILABLE_EXECUTION_TEXT, execution_display_text
from .guard_control_git_reply import GuardReply
from .guard_project_check_protocol import check_project_release
from .guard_request_header import PROTOCOL, TESTING_CHECK_PROTOCOL
from .guard_task_launch_protocol import check_task_native_result
from backend.app.shared.json_canonical import canonical_input
from .runtime_launch_journal import LaunchOutcomeUnknown, LaunchScope, TestingLaunchScope
from .windows_pipe_capture import CapturedOutput, OutputCaptureError, verify_original_output
from .windows_task_directories import ProjectCheckInput, SnapshotCheckInput


class ProjectCheckEvidenceUnknown(LaunchOutcomeUnknown):
    pass


@dataclass(frozen=True)
class ProjectCheckStream:
    byte_count: int
    sha256: str


@dataclass(frozen=True)
class ProjectCheckOutput:
    stdout: ProjectCheckStream | None
    stderr: ProjectCheckStream | None
    problem: str | None

    def verify(self, maximum):
        if type(maximum) is not int or maximum <= 0:
            raise ProjectCheckEvidenceUnknown('ORIGINAL_PROJECT_CHECK_OUTPUT_LIMIT_DIFFERS')
        if self.problem is not None:
            if self.problem not in ('OUTPUT_LIMIT', 'EVIDENCE_INCOMPLETE') or (
                self.stdout is not None or self.stderr is not None
            ):
                raise ProjectCheckEvidenceUnknown('ORIGINAL_PROJECT_CHECK_OUTPUT_SUMMARY_DIFFERS')
            return
        streams = (self.stdout, self.stderr)
        if (
            any(
                type(stream) is not ProjectCheckStream
                or type(stream.byte_count) is not int
                or stream.byte_count < 0
                or not valid_sha256(stream.sha256)
                for stream in streams
            )
            or sum(stream.byte_count for stream in streams) > maximum
        ):
            raise ProjectCheckEvidenceUnknown('ORIGINAL_PROJECT_CHECK_OUTPUT_SUMMARY_DIFFERS')


@dataclass(frozen=True)
class ProjectCheckResult:
    scope: LaunchScope
    check: ProjectCheckInput | SnapshotCheckInput
    result: str
    reason_code: str | None
    exit_code: int | None
    source_integrity: str
    cleanup_ref: str | None
    stop_receipt_sha256: str | None
    stdout: ProjectCheckStream | None
    stderr: ProjectCheckStream | None


@dataclass(frozen=True)
class ProjectCheckUndispatched:
    scope: LaunchScope
    check: ProjectCheckInput | SnapshotCheckInput

    @property
    def result(self):
        return ProjectCheckResult(
            self.scope,
            self.check,
            'UNKNOWN',
            'EVIDENCE_INCOMPLETE',
            None,
            'NOT_CHECKED',
            None,
            None,
            None,
            None,
        )


@dataclass(frozen=True)
class ProjectCheckDisplay:
    stream: str
    text: str

    def __post_init__(self):
        try:
            byte_count = len(self.text.encode('utf-8')) if type(self.text) is str else 0
        except UnicodeError as error:
            raise ProjectCheckEvidenceUnknown('ORIGINAL_PROJECT_CHECK_DISPLAY_DIFFERS') from error
        if (
            self.stream not in ('STDOUT', 'STDERR', 'UNAVAILABLE')
            or type(self.text) is not str
            or not self.text.strip()
            or not 1 <= byte_count <= 2048
            or self.stream == 'UNAVAILABLE'
            and self.text != UNAVAILABLE_EXECUTION_TEXT
        ):
            raise ProjectCheckEvidenceUnknown('ORIGINAL_PROJECT_CHECK_DISPLAY_DIFFERS')


@dataclass(frozen=True)
class ProjectCheckDispatchResult:
    result: ProjectCheckResult
    prepared: dict | None
    created: dict | None
    stopped: dict
    released: dict
    http: dict | None = None
    display: tuple[ProjectCheckDisplay, ...] = ()


def _released(reply, scope, expected):
    if (
        type(reply) is not GuardReply
        or reply.status != 'OBSERVED'
        or not isinstance(scope, LaunchScope)
        or type(expected) not in (ProjectCheckInput, SnapshotCheckInput)
    ):
        raise ProjectCheckEvidenceUnknown('ORIGINAL_PROJECT_CHECK_RELEASE_REQUIRED')
    value = reply.result
    ack = value.get('acknowledgement')
    resource = value.get('resource')
    reference = value.get('binding_ref')
    if (
        value.get('observed_action') != 'RELEASE'
        or value.get('action_phase') != 'ACKNOWLEDGED'
        or value.get('preparation', {}).get('cleanup_state') != 'COMPLETE'
        or value.get('job_activity') != {'process_ids': [], 'assigned_count': 0, 'complete': True}
        or type(ack) is not dict
        or ack.get('native') != resource
        or type(resource) is not dict
        or value.get('fence') != resource.get('fence')
    ):
        raise ProjectCheckEvidenceUnknown('ORIGINAL_PROJECT_CHECK_CLEANUP_UNVERIFIED')
    fence = check_task_native_result(scope, reference, resource)
    check = ack.get('check')
    check_project_release(check, scope, reference)
    if (
        not fence.stop_closed
        or check['check'] != asdict(expected)
        or resource['process_state'] not in ('NOT_CREATED', 'EXITED')
        or (check['exit'] is None) != (resource['process_state'] == 'NOT_CREATED')
    ):
        raise ProjectCheckEvidenceUnknown('ORIGINAL_PROJECT_CHECK_RESULT_DIFFERS')
    return ack


def summarize_project_check_output(output, *, scope, io_nonce, maximum):
    if type(output) is CapturedOutput and (
        output.progress.scope != scope or output.progress.io_nonce != io_nonce
    ):
        raise ProjectCheckEvidenceUnknown('ORIGINAL_PROJECT_CHECK_OUTPUT_SCOPE_DIFFERS')
    if type(output) is CapturedOutput and output.progress.limit_exceeded is True:
        return ProjectCheckOutput(None, None, 'OUTPUT_LIMIT')
    try:
        verified = verify_original_output(
            output, scope=scope, io_nonce=io_nonce, max_output_bytes=maximum
        )
    except OutputCaptureError:
        return ProjectCheckOutput(None, None, 'EVIDENCE_INCOMPLETE')
    return ProjectCheckOutput(
        ProjectCheckStream(len(verified.stdout), sha256(verified.stdout).hexdigest()),
        ProjectCheckStream(len(verified.stderr), sha256(verified.stderr).hexdigest()),
        None,
    )


def display_project_check_output(output, summary, *, scope, io_nonce, maximum):
    if type(scope) is not LaunchScope:
        return ()
    if summary.problem is not None:
        return (ProjectCheckDisplay('UNAVAILABLE', UNAVAILABLE_EXECUTION_TEXT),)
    verified = verify_original_output(
        output, scope=scope, io_nonce=io_nonce, max_output_bytes=maximum
    )
    previews = []
    for stream, raw in (('STDOUT', verified.stdout), ('STDERR', verified.stderr)):
        if not raw:
            continue
        try:
            text = raw.decode('utf-8') if len(raw) <= 2048 else None
        except UnicodeError:
            text = None
        previews.append(ProjectCheckDisplay(stream, execution_display_text(text, max_bytes=2048)))
    return tuple(previews)


def project_command_result(reply, scope, expected, output, *, maximum, interruption=None):
    """Classify the original exit/cleanup and the bounded output evidence."""
    if interruption not in (None, 'TIMEOUT', 'CANCELLED'):
        raise ValueError('Original project check interruption differs')
    if type(output) is not ProjectCheckOutput:
        raise ProjectCheckEvidenceUnknown('ORIGINAL_PROJECT_CHECK_OUTPUT_SUMMARY_REQUIRED')
    output.verify(maximum)
    ack = _released(reply, scope, expected)
    check = ack['check']
    exit = check['exit']
    integrity = check['source_integrity']
    if integrity == 'CHANGED':
        status, reason = 'FAILED', 'INPUT_CHANGED'
    elif interruption == 'CANCELLED':
        status, reason = 'CANCELLED', None
    elif exit is None:
        status, reason = 'UNAVAILABLE', 'ISOLATION_UNAVAILABLE'
    elif interruption == 'TIMEOUT':
        status, reason = 'FAILED', 'TIMEOUT'
    elif output.problem == 'OUTPUT_LIMIT':
        status, reason = 'FAILED', 'OUTPUT_LIMIT'
    elif integrity != 'VERIFIED' or exit['terminated'] or output.problem is not None:
        status, reason = 'UNKNOWN', 'EVIDENCE_INCOMPLETE'
    elif exit['exit_code'] != 0:
        status, reason = 'FAILED', 'COMMAND_FAILED'
    else:
        status, reason = 'PASSED', None
    return ProjectCheckResult(
        scope,
        expected,
        status,
        reason,
        None if exit is None else exit['exit_code'],
        integrity,
        ack['cleanup_ref'],
        None if exit is None else exit['stop_receipt_sha256'],
        output.stdout,
        output.stderr,
    )


def project_process_facts(completion, runner_manifest_sha256):
    """Project only the original suspended root and its verified closure."""
    if type(completion) is ProjectCheckUndispatched:
        return None, None
    released = completion.released['native']
    if released['process_state'] == 'NOT_CREATED':
        if completion.created is not None or completion.result.exit_code is not None:
            raise ProjectCheckEvidenceUnknown('ORIGINAL_PROJECT_CHECK_PROCESS_UNVERIFIED')
        return None, None
    native = (
        completion.stopped['native'] if completion.created is None else completion.created['native']
    )
    process = native['process_identity']
    if (
        process != released['process_identity']
        or native['resource_ref'] != released['resource_ref']
        or native['job_ref'] != released['job_ref']
        or completion.result.exit_code is None
        or not valid_sha256(runner_manifest_sha256)
    ):
        raise ProjectCheckEvidenceUnknown('ORIGINAL_PROJECT_CHECK_PROCESS_DIFFERS')
    started = datetime(1601, 1, 1, tzinfo=UTC) + timedelta(
        microseconds=int(process['creation_time_hex'], 16) // 10
    )
    protocol = (
        TESTING_CHECK_PROTOCOL if type(completion.result.scope) is TestingLaunchScope else PROTOCOL
    )
    return canonical_input(
        {
            'pid': process['pid'],
            'created_at': utc_milliseconds(started),
            'ownership_ref': native['resource_ref'],
        }
    ), canonical_input(
        {
            'runtime_policy_version': protocol,
            'run_kind': 'TASK',
            'guard_run_ref': native['resource_ref'],
            'appcontainer_profile_ref': process['appcontainer_sid'],
            'job_refs': [native['job_ref']],
            'manifest_ref': runner_manifest_sha256,
        }
    )
