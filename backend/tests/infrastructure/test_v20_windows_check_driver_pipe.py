"""Native one-root browser result transport under the owned Windows test Job."""

import json
import sys
from ctypes import POINTER, byref, wintypes
from dataclasses import asdict, replace
from pathlib import Path
from time import monotonic, sleep

import pytest

from backend.app.infrastructure.runtime_launch_journal import TestingLaunchScope as Scope
from backend.app.infrastructure.windows_check_driver_pipe import DriverPipeOffer
from backend.app.infrastructure.windows_controller_token import ControllerPrimaryToken
from backend.app.infrastructure.windows_job import JobMembers, OwnedJob
from backend.app.infrastructure.windows_process import NativeProcessIdentity, ObservedProcess
from backend.app.infrastructure.windows_stdio import StdioBoundaryError
from backend.tests.infrastructure.test_v20_check_case_evidence import frame
from backend.tests.infrastructure.test_v20_check_case_pack import (
    BASIS,
    LIMITS,
    pack,
)
from backend.tests.infrastructure.test_v20_check_case_pack import (
    raw as pack_bytes,
)
from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot

ROOT = Path(__file__).resolve().parents[3]


def _wait_file(path):
    deadline = monotonic() + 20
    while not path.exists():
        error = path.with_name('backend-failure.txt')
        if error.exists():
            pytest.fail(error.read_text(encoding='utf-8'))
        if monotonic() >= deadline:
            raise AssertionError(f'Owned process did not publish {path.name}')
        sleep(0.02)
    return json.loads(path.read_bytes())


def _publish(path, data):
    staged = path.with_suffix('.tmp')
    staged.write_text(json.dumps(data), encoding='utf-8')
    staged.replace(path)


def _diagnostic(code, filename):
    return f"""from pathlib import Path
import traceback
try:
    exec({code!r})
except BaseException:
    Path({filename!r}).write_text(traceback.format_exc(), encoding='utf-8')
    raise
"""


def _backend_code(mode, scope, raw_pack):
    return f"""
import json, sys, time
from pathlib import Path
from dataclasses import asdict
sys.path.insert(0, {str(ROOT)!r})
from backend.app.infrastructure.check_case_evidence import CheckEvidenceUnknown, DriverFrameIdentity
from backend.app.infrastructure.runtime_launch_journal import TestingLaunchScope
from backend.app.infrastructure.windows_check_driver_pipe import BackendDriverResultPipe, DriverPipeBinding, DriverResultStream
from backend.app.infrastructure.windows_stdio import StdioBoundaryError
from backend.app.infrastructure.check_case_pack import CaseBasis, CasePackLimits, decode_case_pack
scope=TestingLaunchScope(**{asdict(scope)!r})
def publish(name,value):
    staged=Path(name+'.tmp')
    staged.write_text(json.dumps(value))
    staged.replace(name)
def wait(name):
    deadline=time.monotonic()+20
    while not Path(name).exists():
        if time.monotonic()>=deadline:
            raise RuntimeError(name)
        time.sleep(.02)
    return json.loads(Path(name).read_bytes())
with BackendDriverResultPipe(scope) as pipe:
    publish('offer.json',asdict(pipe.offer()))
    data=wait('binding.json')
    binding=DriverPipeBinding(scope,pipe.owner,data['nonce'],data['guard_io_ref'])
    try:
        pipe.acknowledge(DriverPipeBinding(scope,pipe.owner,'f'*32,data['guard_io_ref']))
    except StdioBoundaryError:
        pass
    else:
        raise AssertionError('Foreign result pipe nonce was accepted')
    pipe.acknowledge(binding)
    identity=DriverFrameIdentity(4,5,scope.nonce)
    cases=decode_case_pack({raw_pack!r}, limits=CasePackLimits(**{asdict(LIMITS)!r}),
        basis_refs=(CaseBasis(**{asdict(BASIS)!r}),), endpoint_refs=('app',))
    with DriverResultStream(pipe,identity,cases,max_bytes=4096) as reader:
        mode={mode!r}
        error=None
        try:
            while not reader.poll():
                time.sleep(.01)
        except CheckEvidenceUnknown as failure:
            error=str(failure)
        if error is not None:
            publish('result.json',{{'error':error}})
        else:
            assert mode=='good'
            try:
                reader.finish(authenticated_root=False,original_exit_code=0)
            except CheckEvidenceUnknown:
                pass
            else:
                raise AssertionError('Result was accepted without original root proof')
            exit=wait('exit.json')
            publish('result.json',list(reader.finish(authenticated_root=exit['verified'],original_exit_code=exit['code'])))
"""


@pytest.mark.parametrize('mode', ['good', 'truncated', 'wrong-nonce', 'over-limit'])
def test_actual_driver_channel_inherits_only_one_root_and_rejects_incomplete_frames(tmp_path, mode):
    from backend.app.infrastructure.check_case_evidence import DriverFrameIdentity
    from backend.app.infrastructure.windows_check_driver_pipe import GuardDriverResultWriter

    scope = Scope('a' * 64, 1, 4, 'b' * 32, 3, 1)
    identity = DriverFrameIdentity(4, 5, scope.nonce)
    frames = [
        frame(identity, 1, 'BEGIN'),
        frame(
            identity,
            2,
            'CASE_RESULT',
            'check',
            ({'assertion_id': 'visible', 'result': 'PASSED', 'actual_value': True},),
        ),
        frame(identity, 3, 'END'),
    ]
    if mode == 'wrong-nonce':
        frames[1] = frame(identity, 2, 'CASE_RESULT', nonce='c' * 32)
    data = b''.join(len(row).to_bytes(4, 'big') + row for row in frames)
    if mode == 'truncated':
        data = data[:-4]
    if mode == 'over-limit':
        data = (5000).to_bytes(4, 'big')
    limit = 512 * 1024 * 1024
    with (
        OwnedJob(active_process_limit=4, job_memory_limit_bytes=limit) as backend_job,
        OwnedJob(active_process_limit=4, job_memory_limit_bytes=limit) as driver_job,
    ):
        backend = TestSuspendedRoot(
            backend_job,
            tmp_path,
            _diagnostic(
                _backend_code(mode, scope, pack_bytes(pack('BROWSER'))), 'backend-failure.txt'
            ),
            executable=sys._base_executable,
        )
        driver = None
        try:
            backend.resume()
            raw = _wait_file(tmp_path / 'offer.json')
            with ObservedProcess(raw['owner']['pid']) as owner:
                assert owner.identity == NativeProcessIdentity(**raw['owner'])
                assert backend_job.contains_process(owner)
                offer = DriverPipeOffer(
                    Scope(**raw['scope']),
                    owner.identity,
                    raw['nonce'],
                    raw['write_handle'],
                )
                with ControllerPrimaryToken(owner, expected=owner.identity) as controller:
                    with pytest.raises(StdioBoundaryError, match='CONTROLLER_DIFFERS'):
                        GuardDriverResultWriter(
                            controller, replace(scope, control_generation=2), offer
                        )
                    with GuardDriverResultWriter(controller, scope, offer) as guard:
                        _publish(tmp_path / 'binding.json', asdict(guard.binding))
                        with guard.creation_handle(scope) as handle:
                            code = f"""
import os, subprocess, sys
sys.path.insert(0, {str(ROOT)!r})
from backend.app.infrastructure.check_driver_bootstrap import original_result_writer
with original_result_writer({f'{handle:016x}'!r}) as writer:
    assert not os.get_handle_inheritable({handle})
    child='import os; os.get_handle_inheritable({handle})'
    result=subprocess.run([sys.executable,'-I','-B','-c',child],close_fds=False,capture_output=True,check=False)
    assert result.returncode!=0
    writer.write({data!r})
"""
                            driver = TestSuspendedRoot(
                                driver_job,
                                tmp_path,
                                _diagnostic(code, 'driver-failure.txt'),
                                driver_result_handle=handle,
                                executable=sys._base_executable,
                            )
                        with pytest.raises(StdioBoundaryError, match='CREATION_DIFFERS'):
                            with guard.creation_handle(scope):
                                pytest.fail('Second native launch was offered the original writer')
                    with ObservedProcess(driver.pid) as root:
                        assert driver_job.contains_process(root)
                        assert not backend_job.contains_process(root)
                        driver.resume()
                        kernel = driver_job._kernel
                        assert kernel.WaitForSingleObject(driver.info.process, 10000) == 0
                        code = wintypes.DWORD()
                        kernel.GetExitCodeProcess.argtypes = [
                            wintypes.HANDLE,
                            POINTER(wintypes.DWORD),
                        ]
                        kernel.GetExitCodeProcess.restype = wintypes.BOOL
                        assert kernel.GetExitCodeProcess(
                            wintypes.HANDLE(driver.info.process), byref(code)
                        )
                        failure = tmp_path / 'driver-failure.txt'
                        assert code.value == 0, (
                            failure.read_text('utf-8') if failure.exists() else code.value
                        )
                        _publish(tmp_path / 'exit.json', {'verified': True, 'code': code.value})
            result = _wait_file(tmp_path / 'result.json')
            assert backend_job._kernel.WaitForSingleObject(backend.info.process, 10000) == 0
            if mode == 'good':
                assert [(row['case_id'], row['result']) for row in result] == [('check', 'PASSED')]
            else:
                assert 'error' in result
        finally:
            for job, process in ((driver_job, driver), (backend_job, backend)):
                if process is not None:
                    job.terminate_owned(1)
                    assert job._kernel.WaitForSingleObject(process.info.process, 10000) == 0
                    process.close()
                deadline = monotonic() + 8
                while job.observe_members().process_ids and monotonic() < deadline:
                    sleep(0.02)
                assert job.observe_members() == JobMembers((), 0, True)
