"""Select an independently admitted command for each sealed Testing case."""

from dataclasses import dataclass

from backend.app.infrastructure.check_case_pack import CasePack, CheckCase
from backend.app.infrastructure.check_case_values import relative_target
from backend.app.infrastructure.check_runner_bundle import (
    CheckResourceError,
    reference,
    valid_sha256,
)
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.guard_controller_binding import GuardControllerBinding
from backend.app.infrastructure.windows_check_stdin import MAX_STDIN_BYTES
from backend.app.infrastructure.windows_job import MAX_JOB_PROCESSES
from backend.app.infrastructure.windows_project_check_command import (
    ProjectCheckCommand,
    ProjectCheckLaunchError,
)
from backend.app.shared.validation import strict_integer, strict_json_loads, strict_json_object

from .pack_compile import digest, encoded
from .policy_content import PROFILE_FIELDS, parse_profile

_MAX_OUTPUT = 16 * 1024 * 1024


@dataclass(frozen=True)
class TestingCliAdmission:
    evidence_ref: str
    runner_ref: str
    runner_manifest_sha256: str
    runtime_refs: tuple[str, ...]
    command: ProjectCheckCommand
    active_process_limit: int
    job_memory_limit_bytes: int
    fixture_sha256: str | None = None

    def __post_init__(self):
        reference(self.evidence_ref)
        reference(self.runner_ref)
        if (
            not valid_sha256(self.runner_manifest_sha256)
            or type(self.runtime_refs) is not tuple
            or len(set(self.runtime_refs)) != len(self.runtime_refs)
            or type(self.command) is not ProjectCheckCommand
            or self.fixture_sha256 is not None
            and not valid_sha256(self.fixture_sha256)
        ):
            raise CheckResourceError('TESTING_CLI_ADMISSION_INVALID')
        for ref in self.runtime_refs:
            reference(ref)
        strict_integer(self.active_process_limit, 'active_process_limit', maximum=MAX_JOB_PROCESSES)
        strict_integer(self.job_memory_limit_bytes, 'job_memory_limit_bytes')

    def facts(self):
        return {
            'evidence_ref': self.evidence_ref,
            'runner_ref': self.runner_ref,
            'runner_manifest_sha256': self.runner_manifest_sha256,
            'runtime_refs': list(self.runtime_refs),
            'command_id': self.command.command_id,
            'command_sha256': self.command.definition_sha256,
            'active_process_limit': self.active_process_limit,
            'job_memory_limit_bytes': self.job_memory_limit_bytes,
            **({'fixture_sha256': self.fixture_sha256} if self.fixture_sha256 else {}),
        }


@dataclass(frozen=True)
class BrowserServiceAdmission:
    role: str
    origin_ref: str
    prefix: str
    service: TestingCliAdmission

    def __post_init__(self):
        reference(self.origin_ref)
        prefix = relative_target(self.prefix)
        if (
            self.role not in ('FRONTEND', 'BACKEND')
            or not prefix.endswith('/')
            or '?' in prefix
            or '%' in prefix
            or type(self.service) is not TestingCliAdmission
            or self.service.command.purpose != 'SERVICE'
            or self.service.command.network_scope_ref is None
        ):
            raise CheckResourceError('TESTING_BROWSER_APPLICATION_ADMISSION_REQUIRED')

    def facts(self):
        return {
            'role': self.role,
            'origin_ref': self.origin_ref,
            'prefix': self.prefix,
            'endpoint_ref': self.service.command.network_scope_ref,
            'admission': self.service.facts(),
        }


@dataclass(frozen=True)
class TestingBrowserAdmission:
    target_ref: str
    evidence_ref: str
    runner_ref: str
    runner_manifest_sha256: str
    runtime_refs: tuple[str, ...]
    command_id: str
    active_process_limit: int
    job_memory_limit_bytes: int
    applications: tuple[BrowserServiceAdmission, ...]

    def __post_init__(self):
        for item in (self.target_ref, self.evidence_ref, self.runner_ref, self.command_id):
            reference(item)
        if (
            not valid_sha256(self.runner_manifest_sha256)
            or type(self.runtime_refs) is not tuple
            or len(set(self.runtime_refs)) != len(self.runtime_refs)
            or type(self.applications) is not tuple
            or len(self.applications) != 2
            or any(type(item) is not BrowserServiceAdmission for item in self.applications)
            or {item.role for item in self.applications} != {'FRONTEND', 'BACKEND'}
            or len({item.service.command.command_id for item in self.applications}) != 2
            or len({item.service.command.network_scope_ref for item in self.applications}) != 2
            or len({(item.origin_ref, item.prefix) for item in self.applications}) != 2
        ):
            raise CheckResourceError('TESTING_BROWSER_ADMISSION_REQUIRED')
        for ref in self.runtime_refs:
            reference(ref)
        strict_integer(self.active_process_limit, 'active_process_limit', maximum=MAX_JOB_PROCESSES)
        strict_integer(self.job_memory_limit_bytes, 'job_memory_limit_bytes')

    def facts(self):
        return {
            'evidence_ref': self.evidence_ref,
            'runner_ref': self.runner_ref,
            'runner_manifest_sha256': self.runner_manifest_sha256,
            'runtime_refs': list(self.runtime_refs),
            'command_id': self.command_id,
            'active_process_limit': self.active_process_limit,
            'job_memory_limit_bytes': self.job_memory_limit_bytes,
        }


@dataclass(frozen=True)
class TestingCliRuntime:
    owner: GuardControllerBinding
    admissions: tuple[TestingCliAdmission, ...]
    snapshots: bool = False
    browser_admissions: tuple[TestingBrowserAdmission, ...] = ()


@dataclass(frozen=True)
class SelectedCliCase:
    check_id: str
    case: CheckCase
    admission: TestingCliAdmission
    timeout_seconds: int
    endpoint_ref: str | None = None
    request_limit: int | None = None

    def facts(self):
        result = {
            'check_id': self.check_id,
            'case_id': self.case.case_id,
            'timeout_seconds': self.timeout_seconds,
            'admission': self.admission.facts(),
        }
        if self.endpoint_ref is not None:
            result.update(endpoint_ref=self.endpoint_ref, request_limit=self.request_limit)
        return result


@dataclass(frozen=True)
class SelectedBrowserCase:
    check_id: str
    case: CheckCase
    admission: TestingBrowserAdmission
    raw: bytes
    pack: CasePack
    timeout_seconds: int
    request_limit: int

    def facts(self):
        return {
            'kind': 'BROWSER',
            'check_id': self.check_id,
            'case_id': self.case.case_id,
            'case_pack_sha256': digest(self.raw),
            'timeout_seconds': self.timeout_seconds,
            'request_limit': self.request_limit,
            'admission': self.admission.facts(),
            'applications': [item.facts() for item in self.admission.applications],
        }


@dataclass(frozen=True)
class TestingCliPlan:
    cases: tuple[SelectedCliCase | SelectedBrowserCase, ...]
    max_active_seconds: int
    max_output_bytes: int

    def facts(self):
        return {
            'runtime': 'WIN20-TESTING-CHECK-1',
            'max_active_seconds': self.max_active_seconds,
            'max_output_bytes': self.max_output_bytes,
            'cases': [entry.facts() for entry in self.cases],
        }


def read_fixed_profile(connection, profile_id):
    row = connection.execute(
        'SELECT * FROM testing_profile_versions WHERE id=?', (profile_id,)
    ).fetchone()
    if row is None:
        raise StorageUnavailable('Original Testing execution profile is missing')
    data = {
        key: row[key]
        if key == 'name' or (key == 'model_binding' and row[key] is None)
        else strict_json_loads(row[key], key)
        for key in PROFILE_FIELDS
    }
    if parse_profile(data) != data:
        raise StorageUnavailable('Original Testing execution profile is not canonical')
    return data


def _fixed_fixture(target):
    fixed = {key: value for key, value in target.wire().items() if key != 'fixture_sha256'}
    empty = digest(encoded({'schema_version': 1, 'target': fixed, 'file_entries': []}))
    return None if target.fixture_sha256 == empty else target.fixture_sha256


def _command_for(profile, target, command_id, admissions):
    declared = [row for row in profile['commands'] if row['command_id'] == command_id]
    if len(declared) != 1:
        return None
    row = declared[0]
    if target.driver_kind == 'CLI':
        if row['purpose'] != 'CHECK' or row['network_scope_ref'] is not None:
            return None
    elif row['purpose'] != 'SERVICE' or target.endpoint_refs != (row['network_scope_ref'],):
        return None
    try:
        command = ProjectCheckCommand.decode(row)
    except (CheckResourceError, ProjectCheckLaunchError, ValueError):
        return None
    fixture = _fixed_fixture(target)
    uses_fixture = any(
        argument == '{CHECK_FIXTURE}' or argument.startswith('{CHECK_FIXTURE}/')
        for argument in command.argument_template
    )
    if uses_fixture != (fixture is not None):
        return None
    matching = [
        entry
        for entry in admissions
        if entry.command == command
        and entry.fixture_sha256 == fixture
        and entry.runner_ref == target.runner_ref
        and entry.runner_manifest_sha256 == target.runner_sha256
        and entry.evidence_ref in profile['admission_refs']
        and set(target.environment_refs).issubset(entry.runtime_refs)
        and set(entry.runtime_refs).issubset(profile['environment_refs'])
    ]
    return matching[0] if len(matching) == 1 else None


def _selected_case(item, target, case, profile, admissions):
    limits = profile['limits']
    if len(case.steps) > limits['max_case_steps']:
        return None
    payload = limits['max_case_payload_bytes']
    endpoint = None
    if target.driver_kind == 'CLI':
        command_id, stdin = case.steps[0].operands
        if len(stdin) > min(MAX_STDIN_BYTES, payload):
            return None
        if any(
            assertion.op == 'STDOUT_BYTES' and len(assertion.operands[0]) > payload
            for assertion in case.assertions
        ):
            return None
    else:
        if len(target.command_ids) != 1 or len(target.endpoint_refs) != 1:
            return None
        (command_id,), (endpoint,) = target.command_ids, target.endpoint_refs
        if any(
            step.operands[0] != endpoint or len(step.operands[4]) > payload for step in case.steps
        ):
            return None
        if any(
            assertion.op == 'BODY_BYTES' and len(assertion.operands[1]) > payload
            for assertion in case.assertions
        ):
            return None
    command = _command_for(profile, target, command_id, admissions)
    if command is None:
        return None
    return SelectedCliCase(
        item['check_id'],
        case,
        command,
        min(case.timeout_seconds, command.command.timeout_seconds, item['timeout_seconds']),
        endpoint,
        min(payload, _MAX_OUTPUT) if endpoint is not None else None,
    )


def _browser_matches(admission, target, profile):
    if (
        type(admission) is not TestingBrowserAdmission
        or (admission.target_ref, admission.runner_ref, admission.runner_manifest_sha256)
        != (target.target_ref, target.runner_ref, target.runner_sha256)
        or admission.evidence_ref not in profile['admission_refs']
    ):
        return False
    runtime = set(admission.runtime_refs)
    ids = set()
    fixture = _fixed_fixture(target)
    for entry in admission.applications:
        installed = entry.service
        command = installed.command
        declared = [row for row in profile['commands'] if row['command_id'] == command.command_id]
        if (
            len(declared) != 1
            or ProjectCheckCommand.decode(declared[0]) != command
            or entry.origin_ref not in target.endpoint_refs
            or command.network_scope_ref not in target.endpoint_refs
            or installed.runner_ref not in profile['runner_refs']
            or installed.evidence_ref not in profile['admission_refs']
            or installed.fixture_sha256 != fixture
        ):
            return False
        uses_fixture = any(
            argument == '{CHECK_FIXTURE}' or argument.startswith('{CHECK_FIXTURE}/')
            for argument in command.argument_template
        )
        if uses_fixture != (fixture is not None):
            return False
        ids.add(command.command_id)
        runtime.update(installed.runtime_refs)
    return ids == set(target.command_ids) and (
        set(target.environment_refs) <= runtime <= set(profile['environment_refs'])
    )


def _select_browser_cases(compiled, member, group, item, target, profile, admissions):
    try:
        matching = [entry for entry in admissions if _browser_matches(entry, target, profile)]
    except (CheckResourceError, ProjectCheckLaunchError, ValueError):
        return None
    if len(matching) != 1:
        return None
    admission = matching[0]
    origins = {entry.origin_ref for entry in admission.applications}
    raw = dict(compiled.files)[group['path']]
    if digest(raw) != group['sha256']:
        raise StorageUnavailable('Original sealed browser CasePack differs')
    packet = strict_json_object(raw)
    limits = profile['limits']
    selected = []
    for case, original in zip(member.cases, packet['cases'], strict=True):
        if (
            original['case_id'] != case.case_id
            or len(case.steps) > limits['max_case_steps']
            or len(case.assertions) > limits['max_case_steps']
            or len(encoded(original)) > limits['max_case_payload_bytes']
            or any(step.op == 'NAVIGATE' and step.operands[0] not in origins for step in case.steps)
        ):
            return None
        timeout = min(case.timeout_seconds, item['timeout_seconds'])
        selected.append(
            SelectedBrowserCase(
                item['check_id'],
                case,
                admission,
                encoded({**packet, 'cases': [original]}),
                member,
                timeout,
                min(limits['max_case_payload_bytes'], 1024 * 1024),
            )
        )
    return selected


def select_cli_plan(compiled, profile, admissions, browser_admissions=()):
    """Return no plan if any required scope has no genuine executable path."""
    if not admissions and not browser_admissions:
        return None
    manifest = strict_json_object(dict(compiled.files)['manifest.json'])
    targets = {entry.target_ref: entry for entry in compiled.targets}
    limits = profile['limits']
    items = compiled.check_set.value()['items']
    cases = []
    for member, group, item in zip(
        compiled.case_packs, manifest['case_packs'], items[1:], strict=True
    ):
        target = targets[group['target_ref']]
        if (
            target.external_dependency_mode != 'NONE'
            or target.protected_input_refs not in ((), (target.fixture_ref,))
            or target.runner_ref not in profile['runner_refs']
        ):
            return None
        if target.driver_kind == 'BROWSER':
            browser = _select_browser_cases(
                compiled, member, group, item, target, profile, browser_admissions
            )
            if browser is None:
                return None
            cases.extend(browser)
            continue
        for case in member.cases:
            selected = _selected_case(item, target, case, profile, admissions)
            if selected is None:
                return None
            cases.append(selected)
    if not 1 <= len(cases) <= limits['max_check_cases']:
        return None
    return TestingCliPlan(
        tuple(cases),
        limits['max_active_seconds'],
        min(_MAX_OUTPUT, limits['max_check_output_bytes']),
    )
