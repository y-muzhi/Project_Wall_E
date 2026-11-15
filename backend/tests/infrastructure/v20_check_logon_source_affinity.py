"""An owned reduced-privilege host must derive from the retained backend token."""

from pathlib import Path

from backend.app.infrastructure.windows_job import JobMembers, OwnedJob
from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot
from backend.tests.infrastructure.v20_owned_debug_events import DiagnosticStdio
from tools.quality_gate import environment


def probe_source_affinity(directory, original):
    root = Path(__file__).resolve().parents[3]
    source = """
import ctypes,sys
from ctypes import wintypes
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.app.infrastructure.windows_controller_token import ControllerPrimaryToken,Luid
from backend.app.infrastructure.windows_check_logon import CheckLogonSession,_security_state
from backend.app.infrastructure.windows_native_process import _api
kernel,security=_api()
security.AdjustTokenPrivileges.argtypes=[
 wintypes.HANDLE,wintypes.BOOL,wintypes.LPVOID,wintypes.DWORD,wintypes.LPVOID,wintypes.LPVOID]
security.AdjustTokenPrivileges.restype=wintypes.BOOL
current=wintypes.HANDLE()
assert security.OpenProcessToken(kernel.GetCurrentProcess(),0x28,ctypes.byref(current))
try:
 state=_security_state(kernel,security,current)
 class Privilege(ctypes.Structure):
  _fields_=[("luid",Luid),("attributes",wintypes.DWORD)]
 class Privileges(ctypes.Structure):
  _fields_=[("count",wintypes.DWORD),("members",Privilege*len(state[1]))]
 removal=Privileges()
 removal.count=len(state[1])
 for entry,(luid,attributes) in zip(removal.members,state[1],strict=True):
  value=int(luid,16)
  entry.luid.low=value&0xffffffff
  entry.luid.high=value>>32
  entry.attributes=4
 ctypes.set_last_error(0)
 assert security.AdjustTokenPrivileges(current,False,ctypes.byref(removal),0,None,None)
 assert ctypes.get_last_error()==0
 host_state=_security_state(kernel,security,current)
finally:assert kernel.CloseHandle(current)
with ObservedProcess(SOURCE_PID) as process:
 assert process.identity.creation_time_hex==SOURCE_CREATED
 with ControllerPrimaryToken(process,expected=process.identity) as controller:
  with controller.creation_handle() as token:
   backend_state=_security_state(kernel,security,token)
  assert host_state[1]!=backend_state[1],"The host must actually have different privileges"
  assert not host_state[1] and backend_state[1]
  session=CheckLogonSession(controller)
  try:
   with session.creation_handle() as token:
    derived_state=_security_state(kernel,security,token)
   assert derived_state[1]==backend_state[1]
   assert session.identity.user_sid==controller.identity.user_sid
   assert session.identity.authentication_id_hex!=controller.identity.authentication_id_hex
  finally:session.close()
  thread=wintypes.HANDLE()
  assert not security.OpenThreadToken(kernel.GetCurrentThread(),8,True,ctypes.byref(thread))
  assert ctypes.get_last_error()==1008
  assert security.OpenProcessToken(kernel.GetCurrentProcess(),8,ctypes.byref(current))
  try:assert _security_state(kernel,security,current)==host_state
  finally:assert kernel.CloseHandle(current)
  print("CHECK_LOGON_SOURCE_AFFINITY_VERIFIED",len(host_state[1]),len(backend_state[1]),file=sys.stderr,flush=True)
"""
    source = (
        'import sys\nsys.path.insert(0,'
        + repr(str(root))
        + ')\n'
        + f'SOURCE_PID={original.identity.pid}\n'
        + f'SOURCE_CREATED={original.identity.creation_time_hex!r}\n'
        + source
    )
    with (
        OwnedJob(active_process_limit=16, job_memory_limit_bytes=1024 * 1024**2) as job,
        DiagnosticStdio() as streams,
    ):
        child = TestSuspendedRoot(
            job,
            directory,
            source,
            stdio_handles=tuple(streams.child),
            environment_values=environment(str(directory)),
        )
        try:
            streams.close_child_ends()
            child.resume()
            assert child.kernel.WaitForSingleObject(child.info.process, 30000) == 0
            from ctypes import byref, wintypes

            code = wintypes.DWORD()
            assert child.kernel.GetExitCodeProcess(child.info.process, byref(code))
            output = streams.stderr_bytes().decode('utf-8', 'replace')
            print(output, flush=True)
            assert code.value == 0, output
            assert 'CHECK_LOGON_SOURCE_AFFINITY_VERIFIED' in output
        finally:
            job.terminate_owned(1)
            assert child.kernel.WaitForSingleObject(child.info.process, 8000) == 0
            from time import monotonic, sleep

            deadline = monotonic() + 8
            while monotonic() < deadline and job.observe_members() != JobMembers((), 0, True):
                sleep(0.01)
            assert job.observe_members() == JobMembers((), 0, True)
            child.close()
