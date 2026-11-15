"""Owned fixture driver and backend peer for the native Guard joint check."""

from dataclasses import asdict
from hashlib import sha256
from os import environ
from pathlib import Path
from shutil import copyfile
from time import monotonic, sleep
from zipfile import ZipFile

from backend.app.infrastructure.browser_driver_dispatch import BrowserDriverDispatch
from backend.app.infrastructure.check_case_evidence import DriverFrameIdentity
from backend.app.infrastructure.check_runner_bundle import CHECK_PROTOCOL
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.project_check_journal import ProjectCheckJournal
from backend.app.infrastructure.runtime_launch_journal import (
    LaunchJournal,
    LaunchOutcomeUnknown,
    TestingLaunchScope,
)
from backend.app.infrastructure.windows_check_driver_pipe import DriverResultStream
from backend.app.infrastructure.windows_pipe_capture import _read_api, read_available_pipe
from backend.app.infrastructure.windows_private_package import create_private_package
from backend.app.infrastructure.windows_task_directories import ProjectCheckInput
from backend.tests.infrastructure.test_v20_check_case_evidence import frame
from backend.tests.infrastructure.test_v20_check_case_pack import decode, pack, raw
from backend.tests.infrastructure.test_v20_windows_lpac_profile import make_check_candidate

NONCE = '7' * 32
IDENTITY = DriverFrameIdentity(13, 14, NONCE)
CASE_PACK = pack('BROWSER')


def make_runner(root, browser_fixture, *, lpac_capability_names=()):
    import sys

    installed = environ.get('WALLE_TEST_BROWSER_PYTHON')
    if installed:
        exe = Path(installed).resolve(strict=True)
        if exe.name.lower() != 'python.exe':
            raise ValueError('Explicit fixture CPython executable required')
        base = exe.parent
        (library,) = sorted(base.glob('python3[0-9]*.dll'))
        suffix = library.stem.removeprefix('python')
    else:
        base = Path(sys.base_prefix)
        exe = Path(sys._base_executable)
        suffix = f'{sys.version_info.major}{sys.version_info.minor}'
    copyfile(exe, root / 'python.exe')
    for name in (f'python{suffix}.dll', 'python3.dll', 'vcruntime140.dll', 'vcruntime140_1.dll'):
        copyfile(base / name, root / name)
    # Conda CPython links zlib.dll directly. The guarded child inherits no
    # development search paths, so the fixed fixture must carry the DLL.
    zlib = base / 'zlib.dll'
    if zlib.is_file():
        copyfile(zlib, root / zlib.name)
    with ZipFile(root / 'stdlib.zip', 'x') as package:
        for encoding in sorted((base / 'Lib/encodings').glob('*.py')):
            package.write(encoding, 'encodings/' + encoding.name)
        # CPython 3.13's PyRun_SimpleStringFlags registers -c source with linecache.
        # This is needed even when the trusted fixture exits without a traceback.
        package.write(base / 'Lib/linecache.py', 'linecache.py')
    (root / f'python{suffix}._pth').write_bytes(b'.\r\nstdlib.zip\r\n')
    copyfile(browser_fixture, root / 'unlaunched-browser-fixture.exe')
    frames = (
        frame(IDENTITY, 1, 'BEGIN'),
        frame(
            IDENTITY,
            2,
            'CASE_RESULT',
            'check',
            ({'assertion_id': 'visible', 'result': 'PASSED', 'actual_value': True},),
        ),
        frame(IDENTITY, 3, 'END'),
    )
    wire = b''.join(len(row).to_bytes(4, 'big') + row for row in frames)
    source = f"""
import msvcrt, os, sys
handle = int(sys.argv[sys.argv.index('--result-handle')+1],16)
os.set_handle_inheritable(handle,False)
fd=msvcrt.open_osfhandle(handle,os.O_WRONLY|os.O_BINARY|os.O_NOINHERIT)
with os.fdopen(fd,'wb') as result:
    result.write({wire!r})
"""
    (root / 'driver.py').write_text(source, encoding='utf-8')
    if lpac_capability_names:
        from backend.app.infrastructure.browser_driver_lpac_policy import POLICY_FILE

        policy = {'schema_version': 1, 'capability_names': list(lpac_capability_names)}
        (root / POLICY_FILE).write_bytes(canonical_input(policy).encode('utf-8'))
    members = []
    for member in sorted(root.iterdir()):
        data = member.read_bytes()
        members.append(
            {'path': member.name, 'sha256': sha256(data).hexdigest(), 'byte_count': len(data)}
        )
    manifest = {
        'schema_version': 1,
        'protocol_version': CHECK_PROTOCOL,
        'bundle_id': 'native-browser-fixture',
        'version': '1.0.0',
        'entry_ref': 'python.exe',
        'runtime_refs': ['fixture:python'],
        'capabilities': ['CONTENT_INTEGRITY', 'BROWSER'],
        'platform_refs': ['windows:x64'],
        'admission_evidence_refs': ['fixture:windows-browser-driver'],
        'file_entries': members,
    }
    data = canonical_input(manifest).encode('utf-8')
    (root / 'manifest.json').write_bytes(data)
    return sha256(data).hexdigest()


def exercise_driver(root, binding, lock, frames):
    real_browser = (root / 'real-browser-mode').exists()
    from backend.tests.infrastructure.test_v20_check_case_pack import LIMITS
    from backend.tests.infrastructure.v20_real_browser_package_worker import browser_matrix

    application = None
    if (root / 'real-application-mode').exists():
        import json

        application = json.loads((root / 'real-application-mode').read_bytes())
    if real_browser and application is not None:
        from backend.tests.infrastructure.v20_real_browser_package_worker import (
            application_case_pack,
        )

        case_pack, case_limits, expected = application_case_pack()
    elif real_browser:
        case_pack, _, case_limits, expected = browser_matrix()
    else:
        case_pack, case_limits, expected = CASE_PACK, LIMITS, [['PASSED']]
    candidate, _, _ = make_check_candidate(root)
    scope = TestingLaunchScope(binding.controller_ref, 17, 4, NONCE, 9, 2)
    target = ProjectCheckInput(
        'TESTING',
        9,
        2,
        IDENTITY.verification_id,
        IDENTITY.item_id,
        candidate.seal.binding.candidate_id,
        candidate.seal.manifest_sha256,
    )
    runner = (root / 'registered-browser-runner' / 'manifest.json').read_bytes()
    with LaunchJournal(create_private_package(root / 'driver-evidence')) as journal:
        evidence = ProjectCheckJournal(journal, scope, binding.owner_epoch, lambda: None)
        driver = BrowserDriverDispatch(binding, lock, scope, target, evidence)
        try:
            driver.start(
                frames,
                runner_ref='fixture:browser-driver',
                runner_sha256=sha256(runner).hexdigest(),
                case_sha256=sha256(raw(case_pack)).hexdigest(),
                processes=64 if real_browser else 4,
                memory=(2048 if real_browser else 128) * 1024 * 1024,
                deadline=monotonic() + (360 if real_browser else 140),
                cancelled=lambda: False,
            )
            assert driver._created['native']['process_identity']['is_appcontainer'] is True
            with DriverResultStream(
                driver._result_pipe, IDENTITY, decode(case_pack, limits=case_limits), max_bytes=8192
            ) as reader:
                deadline = monotonic() + (75 if real_browser else 25)
                if real_browser and (root / 'browser-cancel-mode').exists():
                    collect_real_browser_fixture(
                        driver, reader, case_pack, deadline, stop_after_request=True
                    )
                    released = driver.release(
                        frames, deadline=monotonic() + 30, cancelled=lambda: False
                    )
                    assert released['check']['source_integrity'] == 'VERIFIED'
                    native = released['check']['exit']
                    assert native['terminated'] is True and native['exit_code'] != 0
                    assert reader.poll()
                    from backend.app.infrastructure.check_case_evidence import CheckEvidenceUnknown

                    try:
                        reader.finish(
                            authenticated_root=True, original_exit_code=native['exit_code']
                        )
                    except CheckEvidenceUnknown:
                        pass
                    else:
                        raise AssertionError('Cancelled partial cases were accepted as complete')
                    return {
                        'result': 'CANCELLED',
                        'scope': asdict(scope),
                        'run_kind': 'CHECK_DRIVER',
                        'cleanup_verified': True,
                        'complete_result_rejected': True,
                    }
                if real_browser:
                    diagnostic = collect_real_browser_fixture(
                        driver, reader, case_pack, deadline, application=application
                    )
                else:
                    while not reader.poll():
                        if monotonic() >= deadline:
                            raise AssertionError('Original root result did not close')
                        sleep(0.01)
                # EOF proves the stream ended, and the Guard must separately prove exit.
                while True:
                    observed = driver._observe(
                        frames, 'RESUME', deadline=deadline, cancelled=lambda: False
                    )
                    driver._require_original_root(observed['resource'])
                    if observed['resource']['process_state'] == 'EXITED':
                        break
                    sleep(0.02)
                observe = driver._observe

                def ambiguous_release(*args, **kwargs):
                    actual = observe(*args, **kwargs)
                    assert args[1] == 'RELEASE'
                    return {**actual, 'job_activity': {**actual['job_activity'], 'complete': False}}

                driver._observe = ambiguous_release
                try:
                    driver.release(frames, deadline=monotonic() + 30, cancelled=lambda: False)
                except LaunchOutcomeUnknown as error:
                    assert str(error) == 'ORIGINAL_BROWSER_CLEANUP_UNVERIFIED'
                    assert evidence.original_ack('RELEASE') is not None
                else:
                    raise AssertionError('RELEASE ACK alone admitted local cleanup')
                finally:
                    driver._observe = observe
                try:
                    driver.close_after_original_release()
                except LaunchOutcomeUnknown as error:
                    assert str(error) == 'ORIGINAL_BROWSER_CLEANUP_REQUIRED'
                else:
                    raise AssertionError('Unverified final observation released original handles')
                released = driver.release(
                    frames, deadline=monotonic() + 30, cancelled=lambda: False
                )
                assert released['check']['source_integrity'] == 'VERIFIED'
                native = released['check']['exit']
                if not real_browser:
                    with driver._streams.output_endpoints() as (_, error):
                        diagnostic = read_available_pipe(
                            _read_api(driver._streams._kernel), error, 4096
                        )
                assert native['terminated'] is False
                if native['exit_code'] == 0xC0000022 and diagnostic is None and reader._seen == 0:
                    assert evidence.original_ack('RELEASE') == released
                    return {
                        'result': 'RUNTIME_ACCESS_DENIED',
                        'scope': asdict(scope),
                        'run_kind': 'CHECK_DRIVER',
                        'cleanup_observation_recovered': True,
                    }
                assert native['exit_code'] == 0, (native, diagnostic, reader._seen)
                outcomes = reader.finish(
                    authenticated_root=True, original_exit_code=native['exit_code']
                )
                assert [
                    [assertion['result'] for assertion in row['assertion_results']]
                    for row in outcomes
                ] == expected
                result = (
                    'FAILED' if any(row['result'] == 'FAILED' for row in outcomes) else 'PASSED'
                )
                assert evidence.original_ack('RELEASE') == released
        finally:
            if driver._released is not None:
                driver.close_after_original_release()
        return {
            'result': result,
            'case_results': [row['result'] for row in outcomes],
            'scope': asdict(scope),
            'run_kind': 'CHECK_DRIVER',
            'cleanup_observation_recovered': True,
        }


def collect_real_browser_fixture(
    driver, reader, case_pack, deadline, *, stop_after_request=False, application=None
):
    # A fixed HTML fixture tests real renderer/IPC. It is not a TASK HTTP endpoint.
    from base64 import b64encode
    from backend.app.infrastructure.browser_driver_control import DriverControlReader, send_control
    from backend.app.infrastructure.check_driver_browser import browser_input
    from backend.app.infrastructure.windows_check_stdin import CheckStdinWriter
    from backend.tests.infrastructure.test_v20_check_case_pack import BASIS
    from backend.tests.infrastructure.v20_real_browser_package_worker import browser_matrix

    _, html, limits, _ = browser_matrix()
    if application is not None:
        from backend.tests.infrastructure.v20_real_browser_package_worker import (
            application_case_pack,
        )

        _, limits, _ = application_case_pack()

    from backend.app.infrastructure import browser_driver_control as controls

    payload = browser_input(IDENTITY, raw(case_pack), (BASIS,), limits, ('app',))
    diagnostic = bytearray()
    with (
        DriverControlReader(driver._streams, maximum=1024 * 1024) as control,
        CheckStdinWriter(driver._streams) as writer,
    ):
        original_read = controls.read_available_pipe

        def observed_read(kernel, handle, maximum):
            value = original_read(kernel, handle, maximum)
            if handle == control._error and value:
                diagnostic.extend(value[: max(0, 4096 - len(diagnostic))])
            return value

        controls.read_available_pipe = observed_read
        try:
            return _collect_real_browser_frames(
                control,
                writer,
                reader,
                payload,
                diagnostic,
                deadline,
                html,
                stop_after_request,
                application,
            )
        finally:
            controls.read_available_pipe = original_read


def _collect_real_browser_frames(
    control, writer, reader, payload, diagnostic, deadline, html, stop_after_request, application
):
    from base64 import b64encode
    from backend.app.infrastructure.browser_driver_control import send_control

    send_control(writer, payload, deadline=deadline, cancelled=lambda: False)
    while True:
        if monotonic() >= deadline:
            raise AssertionError(
                (
                    'Actual Chromium result did not close',
                    bytes(diagnostic),
                    reader._seen,
                    control._seen,
                    control.complete,
                )
            )
        for request in control.poll():
            assert request['origin_ref'] == 'app'
            assert (
                request['path'] == '/app'
                if application is None
                else (
                    request['path'] == '/' or request['path'].startswith(('/assets/', '/api/v1/'))
                )
            )
            assert request['method'] == 'GET'
            if stop_after_request:
                reader.poll()
                assert reader._seen > 0
                return bytes(diagnostic)
            body = html.encode()
            headers = {'content-type': 'text/html; charset=utf-8'}
            status = 200
            if application is not None:
                from urllib.request import urlopen
                import socket
                from backend.app.infrastructure.windows_process import (
                    NativeProcessIdentity,
                    ObservedProcess,
                )
                from backend.app.infrastructure.windows_task_endpoints import _listeners

                port = application['port']
                identity = NativeProcessIdentity(**application['process'])
                with ObservedProcess(identity.pid, expected=identity) as original:
                    assert original.observe().state == 'RUNNING'
                    owners = {
                        pid
                        for family in (socket.AF_INET, socket.AF_INET6)
                        for _, number, pid in _listeners(family)
                        if number == port
                    }
                    assert owners == {identity.pid}
                    with urlopen(
                        'http://127.0.0.1:' + str(port) + request['path'], timeout=10
                    ) as response:
                        status = response.status
                        headers = {
                            'content-type': response.headers.get(
                                'content-type', 'application/octet-stream'
                            )
                        }
                        body = response.read(4 * 1024 * 1024 + 1)
                    assert len(body) <= 4 * 1024 * 1024 and original.observe().state == 'RUNNING'
            send_control(
                writer,
                {
                    'seq': request['seq'],
                    'status': status,
                    'headers': headers,
                    'body': b64encode(body).decode('ascii'),
                },
                deadline=deadline,
                cancelled=lambda: False,
            )
        if reader.poll() and control.complete:
            return bytes(diagnostic)
        sleep(0.01)
