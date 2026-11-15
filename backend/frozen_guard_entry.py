"""Dedicated RuntimeGuard executable; ordinary probes never start a service."""

import argparse
import os
import sys
from pathlib import Path


class GuardRuntimeProbeError(RuntimeError):
    pass


def verify_private_journal_runtime():
    from tempfile import TemporaryDirectory

    from backend.app.infrastructure.guard_service_diagnostics import (
        GuardFailureStage,
        diagnostic_for_failure,
    )
    from backend.app.infrastructure.runtime_launch_journal import LaunchJournal, LaunchScope
    from backend.app.infrastructure.windows_private_package import create_private_package

    try:
        with TemporaryDirectory(prefix='we-guard-journal-runtime-') as temporary:
            root = Path(temporary) / 'journal'
            create_private_package(root)
            scope = LaunchScope('a' * 64, 1, 1, 'frozen-journal-probe-nonce-0001')
            with LaunchJournal(root) as journal:
                journal._owner.assert_owned()
                journal.prepare(scope, 'b' * 64)
            with LaunchJournal(root) as reopened:
                reopened._owner.assert_owned()
                restored = reopened.inspect(scope)
                if (
                    restored is None
                    or not restored.stop_closed
                    or restored.input_sha256 != 'b' * 64
                ):
                    raise GuardRuntimeProbeError('GUARD_JOURNAL_REOPEN_UNVERIFIED')
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        diagnostic = diagnostic_for_failure(error, GuardFailureStage.PRIVATE_JOURNAL)
        raise GuardRuntimeProbeError(
            f'GUARD_JOURNAL_RUNTIME_UNVERIFIED stage={diagnostic.stage.name} '
            f'reason={diagnostic.reason.name} native={diagnostic.native_error or 0}'
        ) from None


def verify_runtime():
    import ctypes

    from backend.app.infrastructure.content_secret_policy import REFERENCE, load_secret_policy
    from backend.app.infrastructure.git_bundle import VERSION, verify_bundle_bytes
    from backend.app.infrastructure.windows_check_logon import CheckLogonSession
    from backend.app.infrastructure.windows_guard_service_host import SERVICE_MAIN, GuardServiceHost
    from backend.app.infrastructure.windows_task_native_launch import TaskNativeLaunch
    from backend.runtime_guard.__main__ import main as run_service

    forbidden = (
        'backend.app.code_tasks',
        'backend.app.service',
        'backend.app.infrastructure.database',
        'sqlite3',
    )
    if (
        os.name != 'nt'
        or ctypes.sizeof(ctypes.c_void_p) != 8
        or not all(
            callable(item)
            for item in (
                run_service,
                CheckLogonSession,
                GuardServiceHost,
                TaskNativeLaunch,
                SERVICE_MAIN,
            )
        )
        or any(
            name == part or name.startswith(part + '.')
            for name in sys.modules
            for part in forbidden
        )
    ):
        raise RuntimeError('GUARD_RUNTIME_DEPENDENCIES_REJECTED')
    try:
        verify_bundle_bytes()
    except (OSError, ValueError, RuntimeError) as error:
        raise GuardRuntimeProbeError('GUARD_FIXED_GIT_UNVERIFIED') from error
    try:
        load_secret_policy(REFERENCE)
    except (OSError, ValueError, RuntimeError) as error:
        raise GuardRuntimeProbeError('GUARD_CONTENT_POLICY_UNVERIFIED') from error
    verify_private_journal_runtime()
    print(
        'GUARD_RUNTIME_VERIFIED protocol=WIN20-ISOLATION-1 no_service_started '
        f'git={VERSION} content_policy={REFERENCE}'
    )
    return 0


def main(arguments=None):
    sys.dont_write_bytecode = True
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if arguments == ['--verify-runtime']:
        return verify_runtime()
    parser = argparse.ArgumentParser(description='Run the fixed WALL-E RuntimeGuard package.')
    parser.add_argument('--program-sha256', required=True)
    parser.add_argument('--verify-package', action='store_true')
    parser.add_argument('--installation-ref')
    parser.add_argument('--manifest')
    parser.add_argument('--sha256')
    values = parser.parse_args(arguments)
    if values.verify_package:
        if any((values.installation_ref, values.manifest, values.sha256)):
            parser.error('Package inspection cannot start a service')
    elif not all((values.installation_ref, values.manifest, values.sha256)):
        parser.error('The fixed installation, manifest and deployment digest are required')
    if not getattr(sys, 'frozen', False):
        raise RuntimeError('DEDICATED_FROZEN_GUARD_EXECUTABLE_REQUIRED')
    from backend.app.infrastructure.deployment_manifest import digest
    from backend.app.infrastructure.program_manifest import GUARD_PROGRAM_POLICY
    from backend.app.infrastructure.program_package import ProgramPackageLease

    expected = digest(values.program_sha256)
    with ProgramPackageLease(
        Path(sys.executable).parent, expected_sha256=expected, policy=GUARD_PROGRAM_POLICY
    ) as package:
        package.verify_running_entry(sys.executable)
        if values.verify_package:
            print('GUARD_PACKAGE_VERIFIED no_service_started no_os_admission')
            return 0
        from backend.runtime_guard.__main__ import main as run_service

        code = run_service(
            [
                '--installation-ref',
                values.installation_ref,
                '--manifest',
                values.manifest,
                '--sha256',
                values.sha256,
            ]
        )
        package.verify()
        return code


if __name__ == '__main__':
    try:
        result = main()
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        if isinstance(error, GuardRuntimeProbeError):
            print(str(error), file=sys.stderr)
        else:
            print('GUARD_PROGRAM_REJECTED', file=sys.stderr)
        if getattr(error, 'retained_owner', None) is not None:
            os._exit(1)
        result = 1
    raise SystemExit(result)
