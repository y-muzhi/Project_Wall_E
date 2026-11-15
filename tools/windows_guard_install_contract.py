"""Pinned install intent for one new Guard service; no system operations."""

import hashlib

from backend.app.infrastructure.deployment_manifest import digest
from backend.app.infrastructure.program_manifest import ProgramPolicy
from backend.app.infrastructure.runtime_launch_journal import _bytes

INSTALLER_POLICY = ProgramPolicy(
    'INSTALLER', 'GUARD20-INSTALLER-1', 'installer-program.v1.json', 'walle-guard-installer.exe'
)
REQUEST_POLICY = 'GUARD20-BOOTSTRAP-INSTALL-1'
REQUEST_NAME = 'guard-installation.v1.json'
INTENT_NAME = 'installation-intent.v1.json'
SYSTEM = 'S-1-5-18'
ADMINISTRATORS = 'S-1-5-32-544'
FULL_FILE_ACCESS = 0x1F01FF
BACKEND_FILE_ACCESS = 0x1200A9
FULL_SERVICE_ACCESS = 0xF01FF
BACKEND_SERVICE_ACCESS = 0x20005
SERVICE_PRIVILEGES = (
    'SeAssignPrimaryTokenPrivilege',
    'SeChangeNotifyPrivilege',
    'SeImpersonatePrivilege',
    'SeIncreaseQuotaPrivilege',
)


class GuardInstallationError(RuntimeError):
    pass


def program_rights(backend_sid):
    return {
        SYSTEM: FULL_FILE_ACCESS,
        ADMINISTRATORS: FULL_FILE_ACCESS,
        backend_sid: BACKEND_FILE_ACCESS,
    }


def service_rights(backend_sid):
    return {
        SYSTEM: FULL_SERVICE_ACCESS,
        ADMINISTRATORS: FULL_SERVICE_ACCESS,
        backend_sid: BACKEND_SERVICE_ACCESS,
    }


def permission_sddl(owner, rights, *, directory):
    flags = 'OICI' if directory else ''
    return (
        'O:'
        + owner
        + 'G:BA'
        + 'D:P'
        + ''.join(f'(A;{flags};0x{mask:08x};;;{sid})' for sid, mask in sorted(rights.items()))
    )


def make_installation_request(inputs, installer_program_sha256):
    plan = inputs.verify()
    service = dict(plan['service'])
    service.update(
        service_type='OWN_PROCESS',
        error_control='NORMAL',
        required_privileges=list(SERVICE_PRIVILEGES),
        failure_actions='NONE',
    )
    return {
        'schema_version': 1,
        'policy_version': REQUEST_POLICY,
        'bootstrap': {'root': str(inputs.root), 'plan_sha256': inputs.expected_sha256},
        'installer_program_sha256': digest(installer_program_sha256),
        'installation_ref': plan['installation_ref'],
        'installation_root': plan['installation_root'],
        'backend_sid': plan['backend_sid'],
        'programs': {name: dict(plan['sources'][name]) for name in ('guard', 'backend')},
        'deployment_sha256': plan['deployment_sha256'],
        'service': service,
        'permissions': {
            'program_owner': ADMINISTRATORS,
            'program_access': program_rights(plan['backend_sid']),
            'journal_owner': SYSTEM,
            'journal_access': {SYSTEM: FULL_FILE_ACCESS},
            'service_owner': ADMINISTRATORS,
            'service_access': service_rights(plan['backend_sid']),
            'installer_own_temporary_privileges': ['SeRestorePrivilege'],
        },
        'limits_ms': {'start': 180000, 'probe_hold': 90000, 'stop': 150000},
        'scope': 'NEW_GUARD_BOOTSTRAP_ONLY_NO_WFP_TASK_MODEL_OR_EXISTING_SERVICE_UPDATE',
    }


def verify_installation_request(raw, expected_sha256, inputs, installer_program_sha256):
    if (
        type(raw) is not bytes
        or not 1 <= len(raw) <= 256 * 1024
        or hashlib.sha256(raw).hexdigest() != digest(expected_sha256)
    ):
        raise GuardInstallationError('INSTALLATION_ORIGINAL_REQUEST_BINDING_DIFFERS')
    expected = make_installation_request(inputs, installer_program_sha256)
    if _bytes(expected) != raw:
        raise GuardInstallationError('INSTALLATION_ORIGINAL_REQUEST_BINDING_DIFFERS')
    return expected
