"""One canonical bootstrap plan shared by preparation and original-source inspection."""

import hashlib
import subprocess

from backend.app.infrastructure.guard_deployment_configuration import decode_guard_deployment
from backend.app.infrastructure.program_manifest import GUARD_PROGRAM_POLICY, ProgramSpec
from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.app.infrastructure.windows_guard_service import guard_service_name
from backend.app.infrastructure.windows_local_paths import local_absolute_path

PLAN_POLICY = 'GUARD20-BOOTSTRAP-PREPARE-1'
PLAN_NAME = 'install-plan.v1.json'
DEPLOYMENT_NAME = 'guard-deployment.json'
PLAN_SCOPE = 'BOOTSTRAP_ONLY_NO_TASK_CHECK_OR_MODEL'
REQUIRED_STEPS = (
    'REVERIFY_SOURCE_PACKAGES_AND_NEW_DESTINATION',
    'CREATE_NEW_PROTECTED_INSTALLATION_WITH_SYSTEM_ADMIN_OWNER',
    'COPY_EXACT_PACKAGES_AND_VERIFY_ALL_BYTES',
    'MAKE_PROGRAMS_AND_DEPLOYMENT_READ_ONLY_TO_BACKEND',
    'CREATE_SYSTEM_PRIVATE_JOURNAL',
    'VERIFY_EFFECTIVE_BACKEND_ANCESTOR_AND_PROGRAM_RIGHTS',
    'REGISTER_ONLY_THE_NEW_PINNED_SERVICE_WITH_MINIMUM_REQUIRED_PRIVILEGES',
    'VERIFY_SCM_IMAGE_ARGUMENTS_AND_ORIGINAL_SYSTEM_PROCESS',
    'TEST_EXPLICITLY_AUTHORIZED_START_STOP_AND_OWNED_CLEANUP',
)


class GuardBootstrapPlanError(RuntimeError):
    pass


def make_bootstrap_plan(deployment_raw, guard_root, guard_program, backend_root, backend_program):
    deployment = decode_guard_deployment(deployment_raw)
    if type(guard_program) is not ProgramSpec or type(backend_program) is not ProgramSpec:
        raise GuardBootstrapPlanError('BOOTSTRAP_ORIGINAL_PROGRAM_SPECS_REQUIRED')
    installation_root = deployment.backend_program_root.parent
    if (
        deployment.task is not None
        or deployment.runtime is not None
        or deployment.checks is not None
        or deployment.backend_program_root != installation_root / 'backend'
        or deployment.journal_root != installation_root / 'journal'
        or deployment.backend_manifest_sha256 != backend_program.manifest_sha256
        or guard_program.entry != GUARD_PROGRAM_POLICY.entry_name
    ):
        raise GuardBootstrapPlanError('BOOTSTRAP_MINIMUM_FIXED_LAYOUT_REQUIRED')
    deployment_sha256 = hashlib.sha256(deployment_raw).hexdigest()
    arguments = [
        str(installation_root / 'guard' / GUARD_PROGRAM_POLICY.entry_name),
        '--program-sha256',
        guard_program.manifest_sha256,
        '--installation-ref',
        deployment.installation_ref,
        '--manifest',
        str(installation_root / DEPLOYMENT_NAME),
        '--sha256',
        deployment_sha256,
    ]
    sources = {}
    for kind, root, program in (
        ('guard', guard_root, guard_program),
        ('backend', backend_root, backend_program),
    ):
        sources[kind] = {
            'root': str(local_absolute_path(root)),
            'program_ref': program.program_ref,
            'manifest_sha256': program.manifest_sha256,
            'member_count': len(program.files),
        }
    return {
        'schema_version': 1,
        'policy_version': PLAN_POLICY,
        'installation_ref': deployment.installation_ref,
        'backend_sid': deployment.backend_sid,
        'installation_root': str(installation_root),
        'sources': sources,
        'deployment_sha256': deployment_sha256,
        'service': {
            'name': guard_service_name(deployment.installation_ref),
            'arguments': arguments,
            'image_path': subprocess.list2cmdline(arguments),
            'account': 'LocalSystem',
            'start_type': 'DEMAND_START',
        },
        'scope': PLAN_SCOPE,
        'required_steps': list(REQUIRED_STEPS),
    }


def require_exact_bootstrap_plan(raw, deployment_raw, guard, backend):
    expected = make_bootstrap_plan(
        deployment_raw, guard.root, guard.spec, backend.root, backend.spec
    )
    if type(raw) is not bytes or _bytes(expected) != raw:
        raise GuardBootstrapPlanError('BOOTSTRAP_PLAN_ORIGINAL_BINDING_DIFFERS')
    return expected
