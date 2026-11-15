"""The authenticated Guard gives a CHECK_DRIVER its own true Windows LPAC Job."""

import hashlib
import json
from pathlib import Path
from time import monotonic
from uuid import uuid4

import pytest

from backend.app.infrastructure import guard_task_launch, guard_task_network
from backend.app.infrastructure.check_runner_bundle import (
    RegisteredCheckRunner,
    hold_check_runner_bundle,
)
from backend.app.infrastructure.guard_control_git_transport import GuardControlGitServer
from backend.app.infrastructure.guard_controller_records import GuardControllerRecords
from backend.app.infrastructure.guard_project_check import _ProjectCheckExecution
from backend.app.infrastructure.guard_project_check_deployment import GuardBrowserDriverDeployment
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal
from backend.app.infrastructure.windows_check_driver_program import RegisteredBrowserDriver
from backend.app.infrastructure.windows_local_paths import LocalDirectoryPin
from backend.app.infrastructure.windows_native_process import ExecutablePin
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.infrastructure.windows_task_directories import TaskRuntimeRoot
from backend.app.infrastructure.windows_task_runtime_environment import _windows_system_paths
from backend.tests.infrastructure.test_v20_guard_control_git_transport import (
    connected,
    program_port,
)
from backend.tests.infrastructure.v20_browser_driver_native_worker import NONCE, make_runner


@pytest.mark.parametrize('require_frames', [False, True], ids=['cleanup-proof', 'trusted-frames'])
def test_native_browser_driver_runs_with_separate_lpac_and_result_pipe(
    tmp_path, program_port, monkeypatch, require_frames, real_package=None
):
    # Explicit ordinary test role: no SYSTEM token-assignment privilege is installed.
    # Real browser cases run this original controller in the owned private-logon worker.
    # Kernel LPAC, Job, image and result-pipe validation below remain unmodified.
    from backend.app.infrastructure.windows_task_native_launch import TaskNativeLaunch

    monkeypatch.setattr(TaskNativeLaunch, '_launch_source', lambda self: self._dirs._controller)
    source = create_private_package(tmp_path / 'task-source')
    runner = create_private_package(tmp_path / 'registered-browser-runner')
    evidence = create_private_package(tmp_path / 'registered-browser-admission')
    _, system = _windows_system_paths()
    if real_package is None:
        manifest = make_runner(
            runner,
            Path(system.canonical_path) / 'findstr.exe',
            lpac_capability_names=('registryRead',) if require_frames else (),
        )
        bundle_id = 'native-browser-fixture'
        browser_entry = 'unlaunched-browser-fixture.exe'
    else:
        import shutil
        from backend.app.infrastructure.check_runner_bundle import decode_runner_manifest

        shutil.copytree(real_package, runner, dirs_exist_ok=True)
        raw = (runner / 'manifest.json').read_bytes()
        import os

        if os.environ.get('WALLE_TEST_BROWSER_STACKS') == '1':
            from tools.windows_backend_package import _replace_owned_build_file
            from backend.app.shared.json_canonical import canonical_input

            original = (runner / 'driver.py').read_bytes()
            diagnostic = (
                b"""import faulthandler,sys
faulthandler.dump_traceback_later(40)
from backend.app.infrastructure.check_driver_pipe_sdk import PipeChromium
original_exit=PipeChromium.__exit__
def observed_exit(self,kind,error,traceback):
 if error is not None:
  print('SDK_PRIVATE_FAILURE',repr(self._last_error),repr(bytes(self._diagnostic)[:1500]),file=sys.stderr,flush=True)
 return original_exit(self,kind,error,traceback)
PipeChromium.__exit__=observed_exit
"""
                + original
            )
            _replace_owned_build_file(runner / 'driver.py', diagnostic)
            worker_path = runner / 'pipe-worker.cjs'
            worker = worker_path.read_bytes().replace(
                b"'use strict';", b"'use strict';\nprocess.env.DEBUG='pw:browser';", 1
            )
            _replace_owned_build_file(worker_path, worker)
            value = json.loads(raw)
            for member in value['file_entries']:
                if member['path'] == 'driver.py':
                    member.update(
                        byte_count=len(diagnostic), sha256=hashlib.sha256(diagnostic).hexdigest()
                    )
                if member['path'] == 'pipe-worker.cjs':
                    member.update(byte_count=len(worker), sha256=hashlib.sha256(worker).hexdigest())
            value['admission_evidence_refs'].append('fixture:bounded-stack-diagnostic')
            raw = canonical_input(value).encode('utf-8')
            _replace_owned_build_file(runner / 'manifest.json', raw)
        manifest = hashlib.sha256(raw).hexdigest()
        bundle_id = decode_runner_manifest(raw).bundle_id
        browser_entry = 'chrome-headless-shell-win64/chrome-headless-shell.exe'
        (tmp_path / 'real-browser-mode').touch(exist_ok=False)
        application = os.environ.get('WALLE_TEST_BROWSER_APPLICATION')
        if os.environ.get('WALLE_TEST_BROWSER_SCENARIO') == 'application':
            from backend.app.shared.json_canonical import canonical_input

            value = json.loads(application)
            assert set(value) == {'port', 'process'}
            with (tmp_path / 'real-application-mode').open('xb') as stream:
                stream.write(canonical_input(value).encode('utf-8'))

        if os.environ.get('WALLE_TEST_BROWSER_SCENARIO') == 'cancel':
            (tmp_path / 'browser-cancel-mode').touch(exist_ok=False)
    provider, sublayer = uuid4(), uuid4()
    active = {}
    native_failures = []

    def diagnosed(action, native):
        def invoke(*args, **kwargs):
            try:
                return native(*args, **kwargs)
            except Exception as error:
                native_failures.append((action, type(error).__name__, str(error)))
                raise

        return invoke

    for action in (
        'prepare',
        'create_native',
        'resume_native',
        'stop_native',
        'release_check_inputs',
    ):
        original = getattr(_ProjectCheckExecution, action)
        monkeypatch.setattr(_ProjectCheckExecution, action, diagnosed(action, original))

    def admitted(self, installation, program, *, deadline, cancelled):
        assert len(installation) == 64 and program
        if real_package is not None:
            # Explicit OS-admission fixture only. BrowserDriverProgram still holds and
            # verifies the full original closure while copying the actual runtime.
            return self.admission_sha256
        with hold_check_runner_bundle(
            self.runner, deadline=deadline, cancelled=cancelled
        ) as bundle:
            self.driver.verify_closure(bundle)
        return self.admission_sha256

    def install(rules, actual_provider, actual_sublayer, marker, *, sid_pointer, cancelled):
        assert (actual_provider, actual_sublayer) == (provider, sublayer)
        assert not cancelled() and sid_pointer and len(rules) == 6
        assert all(rule.action == guard_task_network.BLOCK for rule in rules)
        assert not active
        active[marker] = rules

    def read(rules, actual_provider, actual_sublayer, marker, **_):
        assert (actual_provider, actual_sublayer) == (provider, sublayer)
        assert active[marker] == rules
        return len(rules)

    def release(rules, actual_provider, actual_sublayer, marker, *, cancelled):
        assert (actual_provider, actual_sublayer) == (provider, sublayer)
        assert not cancelled() and active.pop(marker) == rules

    def absent(rules, actual_provider, actual_sublayer, marker):
        assert (actual_provider, actual_sublayer) == (provider, sublayer)
        assert len(rules) == 6 and marker not in active

    monkeypatch.setattr(GuardBrowserDriverDeployment, 'verify', admitted)
    monkeypatch.setattr(guard_task_network, 'current_operator_sid', lambda: 'S-1-5-18')
    monkeypatch.setattr(guard_task_network, '_install_owned_filters', install)
    monkeypatch.setattr(guard_task_network, 'read_owned_filters', read)
    monkeypatch.setattr(guard_task_network, '_release_owned_filters', release)
    monkeypatch.setattr(guard_task_network, '_verify_owned_filters_absent', absent)
    monkeypatch.setattr(guard_task_launch, '_verify_owned_filters_absent', absent)

    with (
        PrivatePackageGuard(source) as sources,
        PrivatePackageGuard(runner) as protected,
        PrivatePackageGuard(evidence) as approval,
        connected(tmp_path, 'TESTING_BROWSER_DRIVER') as (frames, backend, reference),
    ):
        registration = RegisteredCheckRunner(protected.verify(), manifest, bundle_id, '1.0.0')
        deployment = GuardBrowserDriverDeployment(
            'fixture:browser-driver',
            RegisteredBrowserDriver(registration, 'driver.py', browser_entry),
            provider,
            sublayer,
            approval.verify(),
            'c' * 64,
        )
        executable = Path(backend.identity.image_path)
        image = executable.read_bytes()
        with (
            ExecutablePin(
                executable,
                expected_byte_count=len(image),
                expected_sha256=hashlib.sha256(image).hexdigest(),
            ) as pin,
            LaunchJournal(create_private_package(tmp_path / 'guard-driver-state')) as journal,
            GuardControllerRecords(journal) as original_records,
            LocalDirectoryPin(tmp_path) as base,
            TaskRuntimeRoot.create(base, backend.identity.user_sid) as runtime,
        ):
            server = GuardControlGitServer(
                original_records,
                reference,
                package_root=tmp_path,
                manifest_sha256='a' * 64,
                task_source_parent=sources.verify(),
                task_runtime_root=runtime,
                project_checks=(deployment,),
            )
            result = tmp_path / 'control-git-pipe-result.json'
            failure = tmp_path / 'control-git-pipe-failure.json'
            deadline = monotonic() + (600 if real_package is not None else 220)
            try:
                while not result.exists() and monotonic() < deadline:
                    try:
                        server.serve(
                            frames,
                            expected_backend=backend.identity,
                            backend_image=pin,
                            timeout_ms=90000,
                            cancelled=lambda: result.exists() or failure.exists(),
                        )
                    except (RuntimeError, OSError) as error:
                        backend._kernel.WaitForSingleObject(backend._handle, 2500)
                        if result.exists():
                            break
                        reports = (failure, tmp_path / 'owned-guard-worker-error.txt')
                        diagnostic = [
                            report.read_text(encoding='utf-8')
                            for report in reports
                            if report.exists()
                        ]
                        raise AssertionError((diagnostic, native_failures, repr(error))) from error
                actual = json.loads(result.read_bytes())
                assert actual['run_kind'] == 'CHECK_DRIVER'
                assert actual['scope']['nonce'] == NONCE
                if (
                    real_package is not None
                    and os.environ.get('WALLE_TEST_BROWSER_SCENARIO') == 'cancel'
                ):
                    assert actual['cleanup_verified'] is True
                else:
                    assert actual['cleanup_observation_recovered'] is True
                assert not active and not list(runtime.path.iterdir())
                (tmp_path / 'stop').touch(exist_ok=False)
                assert backend._kernel.WaitForSingleObject(backend._handle, 8000) == 0
                if actual['result'] == 'RUNTIME_ACCESS_DENIED' and not require_frames:
                    return
                if real_package is None:
                    assert actual['result'] == 'PASSED'
                elif os.environ.get('WALLE_TEST_BROWSER_SCENARIO') == 'application':
                    assert actual['result'] == 'PASSED' and actual['case_results'] == ['PASSED']
                    print('ACTUAL_ISOLATED_BROWSER_APPLICATION_CHECKED', flush=True)
                elif os.environ.get('WALLE_TEST_BROWSER_SCENARIO') == 'cancel':
                    assert actual['result'] == 'CANCELLED'
                    assert actual['complete_result_rejected'] is True
                    print('ACTUAL_ISOLATED_BROWSER_CANCEL_CLEANUP_CHECKED', flush=True)
                else:
                    assert actual['result'] == 'FAILED'
                    assert actual['case_results'] == ['PASSED', 'FAILED']
                    print('ACTUAL_ISOLATED_BROWSER_MATRIX_CHECKED', flush=True)
            finally:
                server.close()
