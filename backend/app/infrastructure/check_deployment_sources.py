"""Strict CHECK20 deployment composition, without business database or model imports."""

from dataclasses import dataclass
from time import monotonic
from uuid import UUID

from backend.app.shared.strict_objects import exact
from backend.app.shared.validation import strict_integer

from .check_case_pack import CaseBasis, CasePackLimits, RegisteredCasePack
from .check_case_values import relative_target
from .check_fixture import RegisteredCheckFixture, hold_check_fixture
from .check_runner_bundle import (
    RegisteredCheckRunner,
    hold_check_runner_bundle,
    reference,
    references,
)
from .content_manifest import ContentLimits
from .deployment_manifest import LocalDeploymentError, digest, file_identity
from .guard_project_check_deployment import (
    GuardBrowserDriverDeployment,
    GuardProjectCheckDeployment,
)
from .windows_check_driver_program import RegisteredBrowserDriver
from .windows_executable_pin import ExecutablePin
from .windows_job import MAX_JOB_PROCESSES
from .windows_project_check_command import ProjectCheckCommand, RegisteredCheckExecutable


@dataclass(frozen=True)
class ProjectCheckSource:
    deployment: GuardProjectCheckDeployment
    evidence_ref: str
    runtime_refs: tuple[str, ...]
    active_process_limit: int
    job_memory_limit_bytes: int


@dataclass(frozen=True)
class BrowserApplicationSource:
    role: str
    origin_ref: str
    prefix: str
    service_ref: str


@dataclass(frozen=True)
class BrowserCheckSource:
    deployment: GuardBrowserDriverDeployment
    target_ref: str
    evidence_ref: str
    runtime_refs: tuple[str, ...]
    command_id: str
    active_process_limit: int
    job_memory_limit_bytes: int
    applications: tuple[BrowserApplicationSource, ...]


@dataclass(frozen=True)
class CheckDeploymentSources:
    projects: tuple[ProjectCheckSource, ...]
    browsers: tuple[BrowserCheckSource, ...]
    case_packs: tuple[RegisteredCasePack, ...]

    @property
    def guard_deployments(self):
        unique = {}
        for source in (*self.projects, *self.browsers):
            item = source.deployment
            key = (
                type(item),
                item.runner_ref,
                (item.owner_kind, item.command.command_id)
                if type(item) is GuardProjectCheckDeployment
                else None,
            )
            if key in unique and unique[key] != item:
                raise LocalDeploymentError('CHECK_DEPLOYMENT_RESOURCE_CONFLICT')
            unique[key] = item
        return tuple(unique.values())


def _rows(value, maximum):
    if type(value) is not list or len(value) > maximum:
        raise LocalDeploymentError('CHECK_DEPLOYMENT_LIST_REQUIRED')
    return value


def _uuid(value):
    if type(value) is not str:
        raise LocalDeploymentError('CHECK_DEPLOYMENT_NETWORK_IDENTITY_REQUIRED')
    parsed = UUID(value)
    if str(parsed) != value or parsed.int == 0:
        raise LocalDeploymentError('CHECK_DEPLOYMENT_NETWORK_IDENTITY_REQUIRED')
    return parsed


def _runner(value):
    row = exact(value, ('directory', 'manifest_sha256', 'bundle_id', 'version'))
    return RegisteredCheckRunner(
        file_identity(row['directory'], directory=True),
        digest(row['manifest_sha256']),
        reference(row['bundle_id']),
        reference(row['version']),
    )


def _admission(value):
    row = exact(value, ('directory', 'evidence_sha256'))
    return file_identity(row['directory'], directory=True), digest(row['evidence_sha256'])


def _execution(row):
    return (
        references(row['runtime_refs']),
        strict_integer(
            row['active_process_limit'], 'active_process_limit', maximum=MAX_JOB_PROCESSES
        ),
        strict_integer(row['job_memory_limit_bytes'], 'job_memory_limit_bytes'),
    )


def _project(value):
    row = exact(
        value,
        (
            'runner_ref',
            'runner',
            'command',
            'executable',
            'provider',
            'sublayer',
            'maximum',
            'admission',
            'owner_kind',
            'fixture',
            'evidence_ref',
            'runtime_refs',
            'active_process_limit',
            'job_memory_limit_bytes',
        ),
    )
    executable = exact(row['executable'], ('reference', 'file', 'sha256', 'byte_count'))
    executable = RegisteredCheckExecutable(
        reference(executable['reference']),
        file_identity(executable['file'], directory=False),
        digest(executable['sha256']),
        strict_integer(executable['byte_count'], 'byte_count'),
    )
    fixture = row['fixture']
    if fixture is not None:
        fixture = exact(fixture, ('reference', 'sha256', 'directory'))
        fixture = RegisteredCheckFixture(
            reference(fixture['reference']),
            digest(fixture['sha256']),
            file_identity(fixture['directory'], directory=True),
        )
    maximum = exact(row['maximum'], ContentLimits.__dataclass_fields__)
    admission_root, evidence = _admission(row['admission'])
    deployment = GuardProjectCheckDeployment(
        reference(row['runner_ref']),
        _runner(row['runner']),
        ProjectCheckCommand.decode(row['command']),
        executable,
        _uuid(row['provider']),
        _uuid(row['sublayer']),
        ContentLimits(**maximum),
        admission_root,
        evidence,
        row['owner_kind'],
        fixture,
    )
    return ProjectCheckSource(deployment, reference(row['evidence_ref']), *_execution(row))


def _browser(value):
    row = exact(
        value,
        (
            'runner_ref',
            'driver',
            'provider',
            'sublayer',
            'admission',
            'target_ref',
            'evidence_ref',
            'runtime_refs',
            'command_id',
            'active_process_limit',
            'job_memory_limit_bytes',
            'applications',
        ),
    )
    driver = exact(row['driver'], ('runner', 'bootstrap_ref', 'chromium_ref'))
    driver = RegisteredBrowserDriver(
        _runner(driver['runner']), driver['bootstrap_ref'], driver['chromium_ref']
    )
    admission_root, evidence = _admission(row['admission'])
    deployment = GuardBrowserDriverDeployment(
        reference(row['runner_ref']),
        driver,
        _uuid(row['provider']),
        _uuid(row['sublayer']),
        admission_root,
        evidence,
    )
    applications = []
    for application_value in _rows(row['applications'], 2):
        application = exact(application_value, ('role', 'origin_ref', 'prefix', 'service_ref'))
        if application['role'] not in ('FRONTEND', 'BACKEND'):
            raise LocalDeploymentError('CHECK_DEPLOYMENT_APPLICATION_ROLE_REQUIRED')
        prefix = relative_target(application['prefix'])
        if not prefix.endswith('/') or '?' in prefix or '%' in prefix:
            raise LocalDeploymentError('CHECK_DEPLOYMENT_APPLICATION_PREFIX_REQUIRED')
        applications.append(
            BrowserApplicationSource(
                application['role'],
                reference(application['origin_ref']),
                prefix,
                reference(application['service_ref']),
            )
        )
    if (
        len(applications) != 2
        or {item.role for item in applications} != {'FRONTEND', 'BACKEND'}
        or len({(item.origin_ref, item.prefix) for item in applications}) != 2
        or len({item.service_ref for item in applications}) != 2
    ):
        raise LocalDeploymentError('CHECK_DEPLOYMENT_APPLICATION_GROUP_REQUIRED')
    runtime_refs, processes, memory = _execution(row)
    return BrowserCheckSource(
        deployment,
        reference(row['target_ref']),
        reference(row['evidence_ref']),
        runtime_refs,
        reference(row['command_id']),
        processes,
        memory,
        tuple(applications),
    )


def _case_pack(value):
    row = exact(
        value,
        (
            'case_pack_ref',
            'directory',
            'manifest_sha256',
            'bundle_id',
            'version',
            'limits',
            'basis_refs',
            'command_ids',
            'endpoint_refs',
        ),
    )
    limits = exact(row['limits'], CasePackLimits.__dataclass_fields__)
    basis = tuple(
        CaseBasis(**exact(item, CaseBasis.__dataclass_fields__))
        for item in _rows(row['basis_refs'], 256)
    )
    return RegisteredCasePack(
        reference(row['case_pack_ref']),
        file_identity(row['directory'], directory=True),
        digest(row['manifest_sha256']),
        reference(row['bundle_id']),
        reference(row['version']),
        CasePackLimits(**limits),
        basis,
        references(row['command_ids']),
        references(row['endpoint_refs']),
    )


def decode_check_deployment_sources(value):
    row = exact(value, ('projects', 'browsers', 'case_packs'))
    result = CheckDeploymentSources(
        tuple(_project(item) for item in _rows(row['projects'], 32)),
        tuple(_browser(item) for item in _rows(row['browsers'], 32)),
        tuple(_case_pack(item) for item in _rows(row['case_packs'], 256)),
    )
    projects = {item.evidence_ref: item for item in result.projects}
    if (
        len(projects) != len(result.projects)
        or set(projects) & {item.evidence_ref for item in result.browsers}
        or len({item.evidence_ref for item in result.browsers}) != len(result.browsers)
        or len({item.target_ref for item in result.browsers}) != len(result.browsers)
        or len({(item.case_pack_ref, item.manifest_sha256) for item in result.case_packs})
        != len(result.case_packs)
        or len(result.guard_deployments) > 32
    ):
        raise LocalDeploymentError('CHECK_DEPLOYMENT_IDENTITIES_DUPLICATED')
    for browser in result.browsers:
        services = []
        for application in browser.applications:
            service = projects.get(application.service_ref)
            if service is None or (
                service.deployment.owner_kind != 'TESTING'
                or service.deployment.command.purpose != 'SERVICE'
            ):
                raise LocalDeploymentError('CHECK_DEPLOYMENT_ORIGINAL_SERVICE_REQUIRED')
            services.append(service.deployment.command.network_scope_ref)
        if len(set(services)) != 2:
            raise LocalDeploymentError('CHECK_DEPLOYMENT_APPLICATION_ENDPOINTS_DUPLICATED')
    return result


def verify_guard_check_deployments(
    group, installation_ref, backend_program_ref, *, deadline, cancelled
):
    for source in (*group.projects, *group.browsers):
        deployment = source.deployment
        with hold_check_runner_bundle(
            deployment.runner, deadline=deadline, cancelled=cancelled
        ) as closure:
            if set(closure.manifest.runtime_refs) != set(source.runtime_refs):
                raise LocalDeploymentError('CHECK_DEPLOYMENT_RUNTIME_REFERENCES_DIFFER')

    def checkpoint():
        if cancelled() or monotonic() >= deadline:
            raise LocalDeploymentError('CHECK_DEPLOYMENT_PREPARATION_INTERRUPTED')

    for deployment in group.guard_deployments:
        checkpoint()
        if type(deployment) is GuardProjectCheckDeployment:
            executable = deployment.executable
            with ExecutablePin(
                executable.file.canonical_path,
                expected_byte_count=executable.byte_count,
                expected_sha256=executable.sha256,
            ) as program:
                if program.verify().file != executable.file:
                    raise LocalDeploymentError('CHECK_DEPLOYMENT_EXECUTABLE_IDENTITY_DIFFERS')
            if deployment.fixture is not None:
                with hold_check_fixture(deployment.fixture, checkpoint):
                    checkpoint()
        deployment.verify(
            installation_ref, backend_program_ref, deadline=deadline, cancelled=cancelled
        )
