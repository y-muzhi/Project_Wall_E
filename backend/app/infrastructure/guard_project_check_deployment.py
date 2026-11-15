"""Install-time authority for one CHECK20 command or loopback SERVICE and runner."""

from dataclasses import dataclass, field
from time import monotonic
from uuid import UUID

from backend.app.shared.validation import strict_json_object

from .browser_driver_lpac_policy import runner_lpac_capability_names
from .check_fixture import RegisteredCheckFixture
from .check_runner_bundle import (
    CheckResourceError,
    RegisteredCheckRunner,
    hold_check_runner_bundle,
    reference,
    valid_sha256,
)
from .content_manifest import ContentLimits
from .guard_project_check_protocol import (
    BrowserDriverPreparationInput,
    ProjectCheckPreparationInput,
)
from .windows_check_driver_program import RegisteredBrowserDriver
from .windows_config_source import LockedFileSource
from .windows_local_paths import FileIdentity
from .windows_private_package import PrivatePackageGuard, current_operator_sid
from .windows_project_check_command import ProjectCheckCommand, RegisteredCheckExecutable
from .windows_runtime_host_identity import windows_runtime_host_identity

_EVIDENCE_NAME = 'check-runtime-admission.json'
_REQUIRED_CHECKS = frozenset(
    {
        'original_task_read_only_input_and_separate_output',
        'offline_ipv4_ipv6_ale_policy',
        'original_job_and_pipe_isolation',
        'original_stop_and_private_cleanup',
        'registered_program_and_clean_environment',
    }
)


_HTTP_REQUIRED_CHECKS = _REQUIRED_CHECKS | {
    'loopback_application_ipv4_only',
    'original_job_verified_http_dispatch',
}


@dataclass(frozen=True)
class GuardProjectCheckDeployment:
    runner_ref: str
    runner: RegisteredCheckRunner
    command: ProjectCheckCommand
    executable: RegisteredCheckExecutable
    provider: UUID
    sublayer: UUID
    maximum: ContentLimits
    admission_directory: FileIdentity = field(repr=False)
    admission_sha256: str
    owner_kind: str = 'CODING'
    fixture: RegisteredCheckFixture | None = None

    def __post_init__(self):
        reference(self.runner_ref)
        if (
            self.owner_kind not in ('CODING', 'TESTING')
            or type(self.runner) is not RegisteredCheckRunner
            or type(self.command) is not ProjectCheckCommand
            or type(self.executable) is not RegisteredCheckExecutable
            or self.command.executable_ref != self.executable.reference
            or (self.command.purpose == 'SERVICE' and self.owner_kind != 'TESTING')
            or self.fixture is not None
            and (type(self.fixture) is not RegisteredCheckFixture or self.owner_kind != 'TESTING')
            or type(self.provider) is not UUID
            or type(self.sublayer) is not UUID
            or self.provider.int == 0
            or self.sublayer.int == 0
            or type(self.maximum) is not ContentLimits
            or type(self.admission_directory) is not FileIdentity
            or not self.admission_directory.is_directory
            or self.admission_directory.filesystem != 'NTFS'
            or not valid_sha256(self.admission_sha256)
        ):
            raise CheckResourceError('PROJECT_CHECK_DEPLOYMENT_REQUIRED')

    def matches(self, prepared):
        return (
            type(prepared) is ProjectCheckPreparationInput
            and prepared.check.owner_kind == self.owner_kind
            and prepared.runner_ref == self.runner_ref
            and prepared.command_id == self.command.command_id
            and prepared.command_sha256 == self.command.definition_sha256
            and (prepared.application_endpoint is not None) == (self.command.purpose == 'SERVICE')
            and prepared.fixture_sha256 == (None if self.fixture is None else self.fixture.sha256)
            and all(
                getattr(prepared.limits, key) <= getattr(self.maximum, key)
                for key in ContentLimits.__dataclass_fields__
            )
        )

    def verify(self, installation_ref, backend_program_ref, *, deadline, cancelled):
        if current_operator_sid() != 'S-1-5-18':
            raise CheckResourceError('PROJECT_CHECK_DEPLOYMENT_SYSTEM_REQUIRED')

        def checkpoint():
            if cancelled() or monotonic() >= deadline:
                raise CheckResourceError('PROJECT_CHECK_DEPLOYMENT_INTERRUPTED')

        checkpoint()
        expected = {
            'installation_ref': installation_ref,
            'backend_program_ref': backend_program_ref,
            'host': windows_runtime_host_identity(),
            'runner_ref': self.runner_ref,
            'runner_manifest_sha256': self.runner.manifest_sha256,
            'command_definition_sha256': self.command.definition_sha256,
            'executable_sha256': self.executable.sha256,
            'wfp_provider': str(self.provider),
            'wfp_sublayer': str(self.sublayer),
        }
        if self.owner_kind == 'TESTING':
            expected['owner_kind'] = self.owner_kind
        http = self.command.purpose == 'SERVICE'
        capability = 'HTTP' if http else 'CLI'
        if http:
            expected['application_mode'] = 'OWNED_LOOPBACK_HTTP'
        if self.fixture is not None:
            expected['fixture_ref'] = self.fixture.reference
            expected['fixture_sha256'] = self.fixture.sha256
        with (
            hold_check_runner_bundle(self.runner, deadline=deadline, cancelled=cancelled) as runner,
            PrivatePackageGuard(self.admission_directory.canonical_path) as package,
        ):
            if (
                capability not in runner.manifest.capabilities
                or package.verify() != self.admission_directory
            ):
                raise CheckResourceError('PROJECT_CHECK_DEPLOYMENT_SOURCE_DIFFERS')
            identity = package.verify_member(_EVIDENCE_NAME, directory=False)
            with LockedFileSource(
                package.path / _EVIDENCE_NAME,
                max_file_bytes=8192,
                expected_file=identity,
                checkpoint=checkpoint,
            ) as source:
                raw = source.snapshot.raw
                if source.snapshot.sha256 != self.admission_sha256:
                    raise CheckResourceError('PROJECT_CHECK_DEPLOYMENT_DIGEST_DIFFERS')
                verify_project_check_admission(raw, expected, http=http)
                checkpoint()
        return self.admission_sha256


def verify_project_check_admission(raw, expected, *, http=False):
    required = _HTTP_REQUIRED_CHECKS if http else _REQUIRED_CHECKS
    _verify_admission(raw, expected, required)


def _verify_admission(raw, expected, required):
    value = strict_json_object(raw)
    if (
        set(value) != {'schema_version', 'deployment', 'checks'}
        or type(value['schema_version']) is not int
        or value['schema_version'] != 1
        or value['deployment'] != expected
        or any(type(part) is not int for part in value['deployment']['host']['windows_version'])
        or type(value['checks']) is not dict
        or set(value['checks']) != required
        or any(
            not valid_sha256(digest) or digest == '0' * 64 for digest in value['checks'].values()
        )
    ):
        raise CheckResourceError('PROJECT_CHECK_DEPLOYMENT_NATIVE_EVIDENCE_REQUIRED')


_BROWSER_REQUIRED_CHECKS = _REQUIRED_CHECKS | {
    'original_driver_result_write_end_only',
    'original_controller_private_logon_source',
    'private_gui_namespace_and_owned_cleanup',
    'browser_child_cannot_inherit_result_or_control',
    'separate_driver_and_target_identities_and_jobs',
    'chromium_sandbox_enabled_with_fresh_profile',
    'offline_browser_and_verified_target_forwarding',
}


@dataclass(frozen=True)
class GuardBrowserDriverDeployment:
    runner_ref: str
    driver: RegisteredBrowserDriver
    provider: UUID
    sublayer: UUID
    admission_directory: FileIdentity = field(repr=False)
    admission_sha256: str

    def __post_init__(self):
        reference(self.runner_ref)
        if (
            type(self.driver) is not RegisteredBrowserDriver
            or type(self.provider) is not UUID
            or type(self.sublayer) is not UUID
            or not self.provider.int
            or not self.sublayer.int
            or type(self.admission_directory) is not FileIdentity
            or not self.admission_directory.is_directory
            or self.admission_directory.filesystem != 'NTFS'
            or not valid_sha256(self.admission_sha256)
        ):
            raise CheckResourceError('ORIGINAL_BROWSER_DRIVER_DEPLOYMENT_REQUIRED')

    @property
    def runner(self):
        return self.driver.runner

    def matches(self, prepared):
        return (
            type(prepared) is BrowserDriverPreparationInput
            and prepared.runner_ref == self.runner_ref
            and prepared.runner_manifest_sha256 == self.runner.manifest_sha256
        )

    def verify(self, installation_ref, backend_program_ref, *, deadline, cancelled):
        if current_operator_sid() != 'S-1-5-18':
            raise CheckResourceError('ORIGINAL_BROWSER_DRIVER_SYSTEM_REQUIRED')

        def checkpoint():
            if cancelled() or monotonic() >= deadline:
                raise CheckResourceError('ORIGINAL_BROWSER_DRIVER_ADMISSION_INTERRUPTED')

        checkpoint()
        with (
            hold_check_runner_bundle(self.runner, deadline=deadline, cancelled=cancelled) as bundle,
            PrivatePackageGuard(self.admission_directory.canonical_path) as package,
        ):
            if package.verify() != self.admission_directory:
                raise CheckResourceError('ORIGINAL_BROWSER_DRIVER_ADMISSION_SOURCE_DIFFERS')
            files = self.driver.verify_closure(bundle)
            capability_names = runner_lpac_capability_names(bundle, checkpoint)
            expected = {
                'installation_ref': installation_ref,
                'backend_program_ref': backend_program_ref,
                'host': windows_runtime_host_identity(),
                'owner_kind': 'TESTING',
                'run_kind': 'CHECK_DRIVER',
                'runner_ref': self.runner_ref,
                'runner_manifest_sha256': self.runner.manifest_sha256,
                'executable_sha256': files[bundle.manifest.entry_ref].sha256,
                'bootstrap_sha256': files[self.driver.bootstrap_ref].sha256,
                'chromium_sha256': files[self.driver.chromium_ref].sha256,
                'wfp_provider': str(self.provider),
                'wfp_sublayer': str(self.sublayer),
            }
            required_checks = _BROWSER_REQUIRED_CHECKS
            if capability_names:
                expected['lpac_capability_names'] = list(capability_names)
                required_checks = required_checks | {
                    'lpac_capability_identity_and_denied_boundaries'
                }
            identity = package.verify_member('browser-runtime-admission.json', directory=False)
            with LockedFileSource(
                package.path / 'browser-runtime-admission.json',
                max_file_bytes=8192,
                expected_file=identity,
                checkpoint=checkpoint,
            ) as source:
                if source.snapshot.sha256 != self.admission_sha256:
                    raise CheckResourceError('ORIGINAL_BROWSER_DRIVER_ADMISSION_DIGEST_DIFFERS')
                _verify_admission(source.snapshot.raw, expected, required_checks)
                checkpoint()
        return self.admission_sha256
