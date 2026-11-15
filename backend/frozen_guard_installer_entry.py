"""Dedicated installer executable. Runtime inspection performs no system changes."""

import os
import sys


def main():
    sys.dont_write_bytecode = True
    if sys.argv[1:] == ['--verify-runtime']:
        from tools.windows_guard_install_contract import INSTALLER_POLICY
        from tools.windows_guard_installation import require_installer_runtime

        if not callable(require_installer_runtime):
            raise RuntimeError('INSTALLER_ENTRY_UNAVAILABLE')
        forbidden = ('backend.app.service', 'backend.app.infrastructure.database', 'sqlite3')
        if any(
            name == prefix or name.startswith(prefix + '.')
            for name in sys.modules
            for prefix in forbidden
        ):
            raise RuntimeError('INSTALLER_RUNTIME_BUSINESS_IMPORT_REJECTED')
        print(
            f'GUARD_INSTALLER_RUNTIME_VERIFIED policy={INSTALLER_POLICY.version} no_system_changes'
        )
        return 0
    from tools.windows_guard_installation import main as install

    return install(sys.argv[1:])


if __name__ == '__main__':
    try:
        result = main()
    except (OSError, RuntimeError, ValueError, TypeError, KeyError) as error:
        from backend.app.infrastructure.deployment_manifest import LocalDeploymentError
        from tools.windows_guard_install_contract import GuardInstallationError

        public = {
            'CODE_DEPLOYMENT_ABSOLUTE_PATH_REQUIRED',
            'NEW_PRIVATE_PROBE_CHANNEL_REQUIRED',
            'ORIGINAL_PRIVATE_PROBE_CHANNEL_DIFFERS',
            'ORIGINAL_GUARD_NEVER_STARTED_STATE_REQUIRED',
            'ORIGINAL_GUARD_SERVICE_START_FAILED',
            'ORIGINAL_GUARD_START_NOT_RUNNING',
            'ORIGINAL_GUARD_START_DEADLINE_EXCEEDED',
            'ORIGINAL_GUARD_STOP_NOT_VERIFIED',
            'ORIGINAL_GUARD_STOP_DEADLINE_EXCEEDED',
            'INSTALLED_RECEIPT_BINDING_DIFFERS',
            'INSTALLED_ORIGINAL_ROOT_DIFFERS',
            'INSTALLED_SERVICE_CONFIGURATION_DIFFERS',
            'INSTALLER_TRUSTED_DEFAULT_OWNER_REQUIRED',
            'ORIGINAL_FIXED_BACKEND_READER_REQUIRED',
        }
        code = str(error) if type(error) in (GuardInstallationError, LocalDeploymentError) else ''
        diagnostic = code if code in public else 'UNCLASSIFIED_INSTALLATION_FAILURE'
        print('GUARD_INSTALLATION_REJECTED code=' + diagnostic, file=sys.stderr)
        if getattr(error, 'retained_owner', None) is not None:
            os._exit(1)
        result = 1
    raise SystemExit(result)
