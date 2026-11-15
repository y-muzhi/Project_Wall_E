"""Project existing trusted CHECK sources into the original backend runtime types."""

from dataclasses import replace
from time import monotonic

from backend.app.infrastructure.check_case_pack import hold_case_pack
from backend.app.infrastructure.check_deployment_sources import decode_check_deployment_sources
from backend.app.infrastructure.deployment_manifest import LocalDeploymentError
from backend.app.infrastructure.windows_config_source import LockedFileSource
from backend.app.infrastructure.windows_local_paths import LocalPathGuard
from backend.app.testing.cli_plan import (
    BrowserServiceAdmission,
    TestingBrowserAdmission,
    TestingCliAdmission,
)

from .coding_project_check_scope import CodingProjectCheckAdmission


def _testing(source):
    deployed = source.deployment
    return TestingCliAdmission(
        source.evidence_ref,
        deployed.runner_ref,
        deployed.runner.manifest_sha256,
        source.runtime_refs,
        deployed.command,
        source.active_process_limit,
        source.job_memory_limit_bytes,
        None if deployed.fixture is None else deployed.fixture.sha256,
    )


def decode_check_deployment(value, installation):
    group = decode_check_deployment_sources(value)
    projects = []
    testing = {}
    for source in group.projects:
        deployed = source.deployment
        if deployed.owner_kind == 'CODING':
            projects.append(
                CodingProjectCheckAdmission(
                    deployed.runner_ref,
                    deployed.runner.manifest_sha256,
                    source.runtime_refs,
                    deployed.command,
                    source.active_process_limit,
                    source.job_memory_limit_bytes,
                )
            )
        else:
            testing[source.evidence_ref] = _testing(source)
    browsers = []
    for source in group.browsers:
        applications = tuple(
            BrowserServiceAdmission(
                application.role,
                application.origin_ref,
                application.prefix,
                testing[application.service_ref],
            )
            for application in source.applications
        )
        browsers.append(
            TestingBrowserAdmission(
                source.target_ref,
                source.evidence_ref,
                source.deployment.runner_ref,
                source.deployment.runner.manifest_sha256,
                source.runtime_refs,
                source.command_id,
                source.active_process_limit,
                source.job_memory_limit_bytes,
                applications,
            )
        )
    if (
        projects or testing or browsers or group.case_packs
    ) and installation.workspace_root is None:
        raise LocalDeploymentError('CHECK_DEPLOYMENT_WORKSPACE_REQUIRED')
    return replace(
        installation,
        project_checks=tuple(projects),
        case_packs=group.case_packs,
        testing_cli=tuple(item for item in testing.values() if item.command.purpose == 'CHECK'),
        testing_browser=tuple(browsers),
    )


def hold_backend_check_sources(held, installation, *, deadline):
    for registration in installation.case_packs:

        def checkpoint():
            if monotonic() >= deadline:
                raise LocalDeploymentError('CHECK_DEPLOYMENT_PREPARATION_EXPIRED')

        checkpoint()
        directory = held.enter_context(
            LocalPathGuard(registration.directory.canonical_path, directory=True)
        )
        if directory.verify() != registration.directory:
            raise LocalDeploymentError('CHECK_DEPLOYMENT_CASE_DIRECTORY_DIFFERS')
        held.enter_context(
            LockedFileSource(
                registration.directory.canonical_path + '/manifest.json',
                max_file_bytes=16 * 1024 * 1024,
                checkpoint=checkpoint,
            )
        )
        # Guard's SYSTEM-owned runner and OS evidence are deliberately not read
        # by the backend. Only its own data-only CasePack closure is preflighted.
        with hold_case_pack(registration, deadline=deadline, cancelled=lambda: False):
            checkpoint()
