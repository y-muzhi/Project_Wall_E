"""Launch admitted ordinary or recovery-only applications, or manage start intents."""

import argparse
import json
import os
import runpy
import signal
import socket
import stat
import subprocess
import sys
from contextlib import ExitStack, contextmanager
from pathlib import Path


def prebind(scope, resources, *, name='walle.sock', private=False):
    path = scope.installation.path('runtime') / name
    listener = resources.enter_context(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM))
    listener.bind(str(path))  # Never unlink an unknown socket to make a bind succeed.
    socket_identity = path.lstat()

    def remove_our_socket():
        listener.close()
        try:
            current = path.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISSOCK(current.st_mode) and (current.st_dev, current.st_ino) == (
            socket_identity.st_dev,
            socket_identity.st_ino,
        ):
            path.unlink()

    resources.callback(remove_our_socket)
    os.chmod(path, 0o600 if private or scope.installation.ingress_group is None else 0o660)
    return listener


def serve_application(app, listener):
    from uvicorn import Config, Server

    from backend.app.infrastructure.owned_server import run_owned_server

    class OrdinaryServer(Server):
        @contextmanager
        def capture_signals(self):
            def shutdown(_number, _frame):
                self.should_exit = True

            signals = (signal.SIGINT, signal.SIGTERM)
            previous = {event: signal.signal(event, shutdown) for event in signals}
            try:
                yield
            finally:
                for event, handler in previous.items():
                    signal.signal(event, handler)

    server = OrdinaryServer(
        Config(
            app,
            proxy_headers=False,
            lifespan='on',
            access_log=False,
            timeout_graceful_shutdown=10,
        )
    )
    return run_owned_server(server, listener)


def target(args, entry, environment):
    entry['demand'](dict(os.environ) == environment, 'Invalid target environment')
    manifest, libraries, paths = entry['admit_target'](args.root, args.sha256, args.temporary)
    entry['verify_target_imports'](args.root, manifest)
    program_sha = entry['verify_program'](args.project)
    sys.path.append(str(args.project))
    from backend.app.infrastructure.environment_admission import (
        OrdinaryScope,
        prepared_start,
        retire_preparation,
    )
    from backend.app.infrastructure.environment_command import admission_inputs
    from backend.app.infrastructure.environment_lock import NativeEnvironmentFiles
    from backend.app.infrastructure.environment_retained_data import (
        require_retained_data_inaccessible,
    )
    from backend.app.infrastructure.sqlite_runtime import bind_linux_runtime

    bind_linux_runtime(entry['require_active'])
    active = entry['require_active']()
    installation, release = admission_inputs(
        args, active, program_sha, offline=args.action == '_serve-release-check'
    )
    native = NativeEnvironmentFiles(args.root)
    entry['validate_mappings'](
        args.root, (*paths, args.root / 'lib/walle_environment_lock.so'), libraries
    )
    os.umask(0o007)
    if args.action == '_prepare-start':
        print(
            json.dumps(
                prepared_start(
                    installation, native, release, args.operation_id, args.before_control_sha256
                ),
                sort_keys=True,
            )
        )
        return 0
    if args.action == '_retire-start':
        print(
            json.dumps(
                retire_preparation(
                    installation,
                    native,
                    args.operation_id,
                    args.before_operation_id,
                    args.before_revision,
                    args.before_control_sha256,
                ),
                sort_keys=True,
            )
        )
        return 0

    if args.action in ('_serve', '_serve-release-open'):
        require_retained_data_inaccessible(installation)

    from backend.app.service import create_app

    with ExitStack() as resources:
        if args.action == '_serve-release-open':
            from backend.app.infrastructure.environment_release_open import ReleaseOpenScope

            scope = ReleaseOpenScope(
                installation,
                native,
                release,
                resources,
                args.operation_id,
                args.release_open_policy,
                args.release_open_policy_sha256,
            )
            app = create_app(ordinary=scope, frontend_directory=installation.path('frontend'))
            listener = prebind(scope, resources)
        elif args.action == '_serve-release-check':
            from backend.app.infrastructure.environment_release_check import (
                CHECK_SOCKET,
                ReleaseCheckScope,
            )

            scope = ReleaseCheckScope(
                installation,
                native,
                release,
                resources,
                args.operation_id,
                args.release_check_policy,
                args.release_check_policy_sha256,
            )
            app = create_app(recovery=scope, frontend_directory=installation.path('frontend'))
            listener = prebind(scope, resources, name=CHECK_SOCKET, private=True)
        elif args.action == '_serve-recovery':
            from backend.app.infrastructure.environment_recovery_read import RecoveryScope

            scope = RecoveryScope(
                installation,
                native,
                release,
                resources,
                args.operation_id,
                args.recovery_read_policy,
                args.recovery_read_policy_sha256,
            )
            app = create_app(recovery=scope, frontend_directory=installation.path('frontend'))
            listener = prebind(scope, resources)
        else:
            scope = OrdinaryScope(
                installation, native, release, resources, args.operation_id, args.start_sha256
            )
            app = create_app(ordinary=scope, frontend_directory=installation.path('frontend'))
            listener = prebind(scope, resources)
        return serve_application(app, listener)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'action',
        choices=(
            'prepare-start',
            'retire-start',
            'serve',
            'serve-recovery',
            'serve-release-check',
            'serve-release-open',
            '_prepare-start',
            '_retire-start',
            '_serve',
            '_serve-recovery',
            '_serve-release-check',
            '_serve-release-open',
        ),
    )
    for path in ('root', 'home', 'temporary', 'project', 'anchor', 'runtime-entry'):
        parser.add_argument(f'--{path}', required=True, type=Path)
    for text in ('sha256', 'anchor-sha256', 'operation-id'):
        parser.add_argument(f'--{text}', required=True)
    parser.add_argument('--start-sha256')
    parser.add_argument('--before-control-sha256')
    parser.add_argument('--before-operation-id')
    parser.add_argument('--before-revision', type=int)
    parser.add_argument('--recovery-read-policy', type=Path)
    parser.add_argument('--recovery-read-policy-sha256')
    parser.add_argument('--release-check-policy', type=Path)
    parser.add_argument('--release-check-policy-sha256')
    parser.add_argument('--release-open-policy', type=Path)
    parser.add_argument('--release-open-policy-sha256')
    args = parser.parse_args()
    if args.action.endswith('retire-start'):
        if None in (args.before_control_sha256, args.before_operation_id, args.before_revision):
            parser.error('Retirement requires the original control identity')
    elif args.before_operation_id is not None or args.before_revision is not None:
        parser.error('The original control identity is accepted only for retirement')
    elif args.before_control_sha256 is not None and not args.action.endswith('prepare-start'):
        parser.error('The original control digest is accepted only for preparation and retirement')
    if bool(args.start_sha256) != args.action.endswith('serve'):
        parser.error('--start-sha256 is required only for serve')
    recovery_policy = (args.recovery_read_policy, args.recovery_read_policy_sha256)
    recovery = args.action.endswith('serve-recovery')
    if not (all(recovery_policy) if recovery else not any(recovery_policy)):
        parser.error('Only serve-recovery accepts and requires a pinned recovery read policy')
    release_policy = (args.release_check_policy, args.release_check_policy_sha256)
    release_check = args.action.endswith('serve-release-check')
    if not (all(release_policy) if release_check else not any(release_policy)):
        parser.error('Only serve-release-check accepts and requires a pinned release check policy')
    open_policy = (args.release_open_policy, args.release_open_policy_sha256)
    release_open = args.action.endswith('serve-release-open')
    if not (all(open_policy) if release_open else not any(open_policy)):
        parser.error('Only serve-release-open accepts and requires a pinned release open policy')
    try:
        if os.geteuid() == 0 or not (
            sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
        ):
            raise ValueError('Unprivileged -I -B -S is required')
        for script in (Path(__file__), args.runtime_entry):
            meta = script.lstat()
            if (
                script.resolve(strict=True) != script
                or meta.st_uid != 0
                or not stat.S_ISREG(meta.st_mode)
                or meta.st_nlink != 1
                or stat.S_IMODE(meta.st_mode) & 0o222
                or any(
                    item.is_symlink()
                    or item.stat().st_uid != 0
                    or stat.S_IMODE(item.stat().st_mode) & 0o022
                    for item in script.parents
                )
            ):
                raise ValueError('Launch entry is not trusted')
        entry = runpy.run_path(str(args.runtime_entry))
        env = entry['minimum_environment'](args.home, args.temporary)
        if args.action.startswith('_'):
            return target(args, entry, env)
        entry['demand'](
            all(
                not (name.startswith(('LD_', 'PYTHON', 'PIP_')) or name.lower().endswith('_proxy'))
                for name in os.environ
            ),
            'Untrusted loader or proxy variable',
        )
        manifest, _ = entry['verify_runtime'](args.root, args.sha256)
        result = subprocess.run(
            [
                str(args.root / manifest['python']['executable_ref']),
                *entry['FLAGS'],
                str(Path(__file__)),
                '_' + args.action,
                *sys.argv[2:],
            ],
            env=env,
            cwd=args.temporary,
            check=False,
        )
        return result.returncode if result.returncode in (0, 2, 3) else 3
    except (ValueError, OSError, RuntimeError, ImportError, KeyError, TypeError) as error:
        reason = getattr(error, 'code', 'STARTUP_NOT_ADMITTED')
        print(json.dumps({'status': 'BLOCKED', 'reason_code': reason}), file=sys.stderr)
        return 3 if getattr(error, 'uncertain', False) else 2


if __name__ == '__main__':
    raise SystemExit(main())
