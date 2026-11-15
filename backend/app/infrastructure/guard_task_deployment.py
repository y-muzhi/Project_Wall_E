"""Verify a fixed private installation-side task capability evidence index."""

import re
from dataclasses import dataclass, field

from backend.app.shared.validation import strict_json_object

from .opencode_binary import VERSION
from .runtime_launch_journal import LaunchOutcomeUnknown
from .windows_config_source import ConfigReadError, LockedFileSource
from .windows_local_paths import FileIdentity, PathBoundaryError
from .windows_private_package import PackageSecurityError, PrivatePackageGuard, current_operator_sid
from .windows_runtime_host_identity import windows_runtime_host_identity

_SYSTEM = 'S-1-5-18'
_EVIDENCE_NAME = 'task-runtime-admission.json'
_MAX_BYTES = 8192
_REQUIRED_CHECKS = frozenset(
    {
        'lpac_token_and_file_boundaries',
        'job_tree_and_owner_loss',
        'stop_create_resume_ordering',
        'network_allowed_ipv4',
        'network_allowed_ipv6',
        'network_denied_direct_and_other_tasks',
        'network_denied_dns_and_other_loopback',
        'network_proxy_redirect_boundaries',
        'opencode_version_config_and_basic_auth',
    }
)


def _sha256(value):
    return type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None


def _verify_deployment_record(raw, expected):
    value = strict_json_object(raw)
    if (
        set(value) != {'schema_version', 'deployment', 'checks'}
        or type(value['schema_version']) is not int
        or value['schema_version'] != 1
    ):
        raise LaunchOutcomeUnknown('TASK_DEPLOYMENT_EVIDENCE_SCHEMA_DIFFERS')
    deployment = value['deployment']
    if type(deployment) is not dict or set(deployment) != set(expected) or deployment != expected:
        raise LaunchOutcomeUnknown('TASK_DEPLOYMENT_EVIDENCE_BINDING_DIFFERS')
    version = deployment['host']['windows_version']
    if any(type(part) is not int for part in version):
        raise LaunchOutcomeUnknown('TASK_DEPLOYMENT_EVIDENCE_BINDING_DIFFERS')
    checks = value['checks']
    if (
        type(checks) is not dict
        or set(checks) != _REQUIRED_CHECKS
        or any(not _sha256(digest) or digest == '0' * 64 for digest in checks.values())
    ):
        raise LaunchOutcomeUnknown('TASK_DEPLOYMENT_NATIVE_EVIDENCE_REQUIRED')


@dataclass(frozen=True)
class TaskRuntimeAdmission:
    directory: FileIdentity = field(repr=False)
    evidence_sha256: str

    def __post_init__(self):
        if (
            type(self.directory) is not FileIdentity
            or not self.directory.is_directory
            or self.directory.filesystem != 'NTFS'
            or not _sha256(self.evidence_sha256)
        ):
            raise ValueError('TASK_DEPLOYMENT_FIXED_SOURCE_REQUIRED')

    def verify(
        self, *, installation_ref, backend_program_ref, plan, program_sha256, network, checkpoint
    ):
        checkpoint()
        if current_operator_sid() != _SYSTEM:
            raise LaunchOutcomeUnknown('TASK_DEPLOYMENT_SYSTEM_REQUIRED')
        expected = {
            'installation_ref': installation_ref,
            'backend_program_ref': backend_program_ref,
            'runtime_bundle_ref': plan.runtime_bundle_ref,
            'binary_ref': plan.binary_ref,
            'program_sha256': program_sha256,
            'opencode_version': VERSION,
            'host': windows_runtime_host_identity(),
            'wfp_provider': str(network.provider),
            'wfp_sublayer': str(network.sublayer),
            'model_listener': list(network.model_listener),
            'forward_listeners': [list(endpoint) for endpoint in network.forward_listeners],
        }
        try:
            with PrivatePackageGuard(self.directory.canonical_path) as package:
                if package.operator_sid != _SYSTEM or package.verify() != self.directory:
                    raise LaunchOutcomeUnknown('TASK_DEPLOYMENT_SOURCE_DIFFERS')
                identity = package.verify_member(_EVIDENCE_NAME, directory=False)
                with LockedFileSource(
                    package.path / _EVIDENCE_NAME, max_file_bytes=_MAX_BYTES, expected_file=identity
                ) as source:
                    if source.snapshot.sha256 != self.evidence_sha256:
                        raise LaunchOutcomeUnknown('TASK_DEPLOYMENT_EVIDENCE_BYTES_DIFFER')
                    _verify_deployment_record(source.snapshot.raw, expected)
                    checkpoint()
                    if package.verify() != self.directory:
                        raise LaunchOutcomeUnknown('TASK_DEPLOYMENT_SOURCE_DIFFERS')
        except (
            ConfigReadError,
            OSError,
            PackageSecurityError,
            PathBoundaryError,
            ValueError,
        ) as error:
            if getattr(error, 'retained_owner', None) is not None:
                raise
            raise LaunchOutcomeUnknown('TASK_DEPLOYMENT_EVIDENCE_UNVERIFIED') from error
        return self.evidence_sha256
