"""Explicit fixed-resource native diagnostics; no product acceptance or network connect."""

import ctypes
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from ctypes import wintypes
import pytest
from backend.app.infrastructure.windows_native_process import ProcessInfo, StartupInfoEx, _api
from backend.app.infrastructure.windows_executable_pin import ExecutablePin
from backend.app.infrastructure.windows_lpac_profile import TaskLpacProfile
from backend.app.infrastructure.windows_lpac_token import LpacProcessToken
from backend.tests.infrastructure.test_v20_windows_lpac_profile import (
    controller,
    lpac_scope,
    ordinary_controller,
    tmp_path,
)
from backend.tests.infrastructure.v20_owned_debug_events import DiagnosticStdio
from tools.windows_browser_package import extract_archive, fixed_archive


def primary_probe(
    scope,
    kind,
    *,
    logon_token=None,
    private_gui=False,
    desktop_name=None,
    capability_names=('registryRead',),
    protected_files=(),
):
    directories, job, journal = scope
    runtime = directories.root / 'runtime'
    resources = Path(__file__).resolve().parents[2] / 'distributions/windows'
    if kind in ('headless-root', 'headless-pipe-root', 'headless-debug-root'):
        import shutil

        package = resources / 'check-browser-20261114-1312-headless'
        folder = 'chrome-headless-shell-win64'
        shutil.copytree(package / folder, runtime / folder)
        image = runtime / folder / 'chrome-headless-shell.exe'
        arguments = ['--version']
    elif kind in (
        'python',
        'python-sdk-pipe',
        'python-directory-modes',
        'python-pipe-namespace',
        'python-winstation',
        'python-headless-pipe',
        'python-sdk-browser',
        'python-boundaries',
    ):
        archive = resources / 'browser-sources-20261113/python-3.13.5-embed-amd64.zip'
        extract_archive(
            fixed_archive(
                archive, '7d2650fd9d1b9d002d4a315d5f354247fd6a44f30517c7ef577b08f57a0fb6d9'
            ),
            runtime,
        )
        image = runtime / 'python.exe'
        source = """import socket,json
result={}
for family in (socket.AF_INET,socket.AF_INET6):
 try:
  value=socket.socket(family,socket.SOCK_STREAM)
  value.close()
  result[str(family)]=0
 except OSError as error:result[str(family)]=error.winerror
try:
 import _overlapped
 result['overlapped']=0
except OSError as error:result['overlapped']=error.winerror
print(json.dumps(result))
"""
        if kind == 'python-winstation':
            source = "import ctypes,json\nfrom ctypes import wintypes\nu=ctypes.WinDLL('user32',use_last_error=True)\nk=ctypes.WinDLL('kernel32',use_last_error=True)\na=ctypes.WinDLL('advapi32',use_last_error=True)\nu.GetProcessWindowStation.restype=wintypes.HANDLE\nu.GetUserObjectSecurity.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD),wintypes.LPVOID,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]\nu.GetUserObjectSecurity.restype=wintypes.BOOL\nu.CreateWindowStationW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID]\nu.CreateWindowStationW.restype=wintypes.HANDLE\nu.CloseWindowStation.argtypes=[wintypes.HANDLE]\nu.CloseWindowStation.restype=wintypes.BOOL\nk.GetCurrentProcess.restype=wintypes.HANDLE\nk.CloseHandle.argtypes=[wintypes.HANDLE]\nk.LocalFree.argtypes=[wintypes.LPVOID]\na.OpenProcessToken.argtypes=[wintypes.HANDLE,wintypes.DWORD,ctypes.POINTER(wintypes.HANDLE)]\na.GetTokenInformation.argtypes=[wintypes.HANDLE,ctypes.c_int,wintypes.LPVOID,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]\na.ConvertSidToStringSidW.argtypes=[wintypes.LPVOID,ctypes.POINTER(wintypes.LPWSTR)]\na.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,ctypes.POINTER(wintypes.LPVOID),ctypes.POINTER(wintypes.DWORD)]\nclass SA(ctypes.Structure):\n _fields_=[('length',wintypes.DWORD),('descriptor',wintypes.LPVOID),('inherit',wintypes.BOOL)]\ndef sid_value(token,kind):\n needed=wintypes.DWORD()\n a.GetTokenInformation(token,kind,None,0,ctypes.byref(needed))\n value=ctypes.create_string_buffer(needed.value)\n if not a.GetTokenInformation(token,kind,value,len(value),ctypes.byref(needed)):raise ctypes.WinError(ctypes.get_last_error())\n sid=ctypes.c_void_p.from_buffer(value).value\n if not sid:return None\n text=wintypes.LPWSTR()\n if not a.ConvertSidToStringSidW(sid,ctypes.byref(text)):raise ctypes.WinError(ctypes.get_last_error())\n try:return text.value\n finally:k.LocalFree(text)\ntoken=wintypes.HANDLE()\nassert a.OpenProcessToken(k.GetCurrentProcess(),8,ctypes.byref(token))\ntry:user=sid_value(token,1);package=sid_value(token,31)\nfinally:assert k.CloseHandle(token)\nstation=u.GetProcessWindowStation()\ninfo=wintypes.DWORD(4);needed=wintypes.DWORD()\nu.GetUserObjectSecurity(station,ctypes.byref(info),None,0,ctypes.byref(needed))\nclone=ctypes.create_string_buffer(needed.value)\nclone_ok=bool(needed.value and u.GetUserObjectSecurity(station,ctypes.byref(info),clone,len(clone),ctypes.byref(needed)))\nresult={'package':bool(package),'clone_read':clone_ok,'attempts':{}}\nprivate=wintypes.LPVOID()\nsddl='D:P'+''.join('(A;OICI;GA;;;'+sid+')' for sid in {user,package} if sid)+'S:(ML;;NW;;;LW)'\nassert a.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl,1,ctypes.byref(private),None),ctypes.get_last_error()\ntry:\n for label,descriptor in [('clone',ctypes.cast(clone,wintypes.LPVOID) if clone_ok else None),('private',private)]:\n  if descriptor is None:continue\n  attributes=SA(ctypes.sizeof(SA),descriptor,False)\n  for mask in (0x80000008,0xA):\n   ctypes.set_last_error(0)\n   handle=u.CreateWindowStationW(None,0,mask,ctypes.byref(attributes))\n   error=ctypes.get_last_error()\n   result['attempts'][label+'-'+hex(mask)]={'created':bool(handle),'error':0 if handle else error}\n   if handle:assert u.CloseWindowStation(handle)\nfinally:k.LocalFree(private)\nprint(json.dumps(result),flush=True)\n"
        if kind == 'python-pipe-namespace':
            source = r"""import ctypes,json
from ctypes import wintypes
from uuid import uuid4
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
kernel.CreateNamedPipeW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID]
kernel.CreateNamedPipeW.restype=wintypes.HANDLE
kernel.CloseHandle.argtypes=[wintypes.HANDLE]
result={}
for label,prefix in (('global',r'\\?\pipe\uv'),('local',r'\\.\pipe\LOCAL')):
 handle=kernel.CreateNamedPipeW(prefix+'\\walle-'+uuid4().hex,3|0x80000|0x40000000|0x40000,0,1,65536,65536,0,None)
 if handle in (None,ctypes.c_void_p(-1).value):result[label]=ctypes.get_last_error()
 else:
  result[label]=0
  assert kernel.CloseHandle(handle)
print(json.dumps(result))
"""
        if kind == 'python-directory-modes':
            source = """import json,sys
from pathlib import Path
scratch=Path(sys.executable).parent.parent / 'scratch'
results={}
for mode in (0o700,0o777):
 path=scratch/('mode-'+str(mode))
 try:
  path.mkdir(mode=mode)
  with (path/'probe').open('xb') as output:output.write(b'private')
  (path/'probe').unlink();path.rmdir()
  results[str(mode)]=0
 except OSError as error:
  results[str(mode)]=error.winerror
print(json.dumps(results))
"""
        if kind == 'python-sdk-pipe':
            import shutil

            package = resources / 'check-browser-20261114-1231-pipe'
            for name in ('application.zip', 'pipe-worker.cjs'):
                shutil.copyfile(package / name, runtime / name)
            shutil.copytree(package / 'vendor', runtime / 'vendor')
            from tools.windows_backend_package import _replace_owned_build_file

            _replace_owned_build_file(
                runtime / 'python313._pth', b'python313.zip\r\n.\r\nvendor\r\napplication.zip\r\n'
            )
            source = """import json,sys
from pathlib import Path
from backend.app.infrastructure.check_driver_pipe_sdk import PipeChromium
from backend.app.infrastructure.check_case_evidence import CheckEvidenceUnknown
api = PipeChromium(Path(sys.executable).parent, private_temp=Path(sys.executable).parent.parent / 'scratch')
try:
 with api:
  try: api.rpc('UNSUPPORTED_PROBE', {}, timeout=3000)
  except CheckEvidenceUnknown as error:
   print(json.dumps({'error':str(error),'last':api._last_error,'diagnostic':bytes(api._diagnostic).decode('utf-8','replace')}),flush=True)
except BaseException as error:
 print(json.dumps({'outer':str(error),'diagnostic':bytes(api._diagnostic).decode('utf-8','replace')}),flush=True)
"""
        if kind in ('python-headless-pipe', 'python-sdk-browser'):
            import shutil
            from tools.windows_backend_package import _replace_owned_build_file

            package = resources / 'check-browser-20261114-1316-headless'
            shutil.copyfile(package / 'application.zip', runtime / 'application.zip')
            if kind == 'python-sdk-browser':
                for name in ('pipe-worker.cjs', 'browser-broker.cjs'):
                    shutil.copyfile(package / name, runtime / name)

            shutil.copytree(package / 'vendor', runtime / 'vendor')
            shutil.copytree(
                package / 'chrome-headless-shell-win64', runtime / 'chrome-headless-shell-win64'
            )
            _replace_owned_build_file(
                runtime / 'python313._pth', b'python313.zip\r\n.\r\nvendor\r\napplication.zip\r\n'
            )
            source = "import base64,json,os,sys\nfrom pathlib import Path\nfrom time import monotonic,sleep\nfrom uuid import uuid4\nfrom backend.app.infrastructure.check_driver_browser_process import BrowserPipeProcess\nruntime=Path(sys.executable).parent\nscratch=runtime.parent/'scratch'\nprofile=scratch/('browser-'+uuid4().hex)\nprofile.mkdir()\nmessages=[]\ndef received(op,value):messages.append((op,value))\nenv=dict(os.environ);env['TEMP']=env['TMP']=str(scratch)\napi=BrowserPipeProcess(runtime,profile,env,received)\nresult={}\ntry:\n executable=runtime/'chrome-headless-shell-win64/chrome-headless-shell.exe'\n args=['--headless','--no-first-run','--no-default-browser-check','--disable-background-networking',\n       '--disable-component-update','--disable-sync','--enable-logging=stderr',\n       '--remote-debugging-pipe','--user-data-dir='+str(profile),'about:blank']\n api.start(str(executable),args)\n api.write(base64.b64encode(b'{\"id\":1,\"method\":\"Browser.getVersion\"}\\0').decode('ascii'),sequence=1)\n deadline=monotonic()+6;wire=bytearray()\n while monotonic()<deadline:\n  api.poll()\n  while messages:\n   op,value=messages.pop(0)\n   if op=='BROWSER_DATA' and value['stream']=='cdp' and value['data'] is not None:\n    wire.extend(base64.b64decode(value['data']))\n  if b'\\0' in wire or api.process.poll() is not None:break\n  sleep(0.01)\n result={'exit':api.process.poll(),'cdp':b'\\0' in wire,'wire':bytes(wire[:1000]).decode('utf-8','replace'),'stderr':bytes(api.stderr[-2000:]).decode('utf-8','replace')}\nexcept BaseException as error:result={'outer':str(error),'stderr':bytes(api.stderr[-2000:]).decode('utf-8','replace')}\nfinally:\n process=api.process\n if process is not None:\n  import ctypes\n  from ctypes import wintypes\n  kernel=ctypes.WinDLL('kernel32',use_last_error=True)\n  kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4\n  kernel.GetProcessTimes.restype=wintypes.BOOL\n  times=[wintypes.FILETIME() for _ in range(4)]\n  if kernel.GetProcessTimes(process._handle,*[ctypes.byref(value) for value in times]):\n   result['cpu_ms']=sum((value.dwHighDateTime<<32)|value.dwLowDateTime for value in times[2:])/10000\n try:api.close()\n except BaseException as error:result['cleanup']=str(error)\nfor log in (profile/'chrome_debug.log',profile/'Default/chrome_debug.log'):\n if log.is_file():\n  try:result['debug_log']=log.read_bytes()[-1400:].decode('utf-8','replace')\n  except OSError as error:result['debug_log_error']=str(error)[:100]\nprint(json.dumps(result),flush=True)\n"
        if kind == 'python-boundaries':
            import shutil
            from tools.windows_backend_package import _replace_owned_build_file

            package = resources / 'check-browser-20261114-1543-assets'
            shutil.copyfile(package / 'application.zip', runtime / 'application.zip')
            shutil.copytree(package / 'vendor', runtime / 'vendor')
            _replace_owned_build_file(
                runtime / 'python313._pth', b'python313.zip\r\n.\r\nvendor\r\napplication.zip\r\n'
            )
            source = (
                'PROTECTED_FILES='
                + repr(tuple(str(p) for p in protected_files))
                + '\n'
                + "import ctypes,json,socket,sys\nfrom pathlib import Path\nfrom ctypes import wintypes\nfrom backend.app.infrastructure.windows_process import ObservedProcess\nfrom backend.app.infrastructure.windows_lpac_token import prove_current_lpac_opt_out\nruntime=Path(sys.executable).parent\nscratch=runtime.parent/'scratch'\nwith ObservedProcess(__import__('os').getpid()) as root:\n identity=root.identity\nproof=prove_current_lpac_opt_out(identity.user_sid,identity.appcontainer_sid)\nresult={'lpac':proof,'network':{},'protected':[]}\nfor family in (socket.AF_INET,socket.AF_INET6):\n try:\n  stream=socket.socket(family,socket.SOCK_STREAM);stream.close()\n  result['network'][str(family)]=0\n except OSError as error:result['network'][str(family)]=error.winerror\nkernel=ctypes.WinDLL('kernel32',use_last_error=True)\nkernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]\nkernel.CreateFileW.restype=wintypes.HANDLE\nkernel.CloseHandle.argtypes=[wintypes.HANDLE]\nfor name in PROTECTED_FILES:\n denied={}\n for label,access in (('read',0x80000000),('write',0x40000000),('dacl',0x40000)):\n  handle=kernel.CreateFileW(name,access,7,None,3,0x200000,None)\n  if handle in (None,ctypes.c_void_p(-1).value):\n   denied[label]=ctypes.get_last_error()\n  else:\n   denied[label]=0;assert kernel.CloseHandle(handle)\n result['protected'].append(denied)\nprobe=scratch/'owned-capability-file'\nwith probe.open('xb') as output:output.write(b'own fixture')\nassert probe.read_bytes()==b'own fixture'\nprobe.unlink();result['scratch']=True\nole=ctypes.WinDLL('ole32',use_last_error=True)\nole.StgOpenStorage.argtypes=[wintypes.LPCWSTR,wintypes.LPVOID,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,ctypes.POINTER(wintypes.LPVOID)]\nole.StgOpenStorage.restype=ctypes.c_long\nstorage=wintypes.LPVOID()\nresult['com_storage_hresult']=hex(ole.StgOpenStorage(PROTECTED_FILES[0],None,0x20,None,0,ctypes.byref(storage))&0xffffffff)\nassert not storage.value\nprint(json.dumps(result),flush=True)\n"
            )
        if kind == 'python-sdk-browser':
            source = "import json,os,sys\nfrom pathlib import Path\nfrom uuid import uuid4\nfrom backend.app.infrastructure.check_driver_pipe_sdk import PipeChromium\nruntime=Path(sys.executable).parent\nscratch=runtime.parent/'scratch'\nenv=dict(os.environ);env['TEMP']=env['TMP']=str(scratch)\nos.environ['TEMP']=os.environ['TMP']=str(scratch)\n# PRIVATE_GUI_READY\napi=PipeChromium(runtime,private_temp=scratch)\nresult={}\ntry:\n with api:\n  profile=scratch/('browser-'+uuid4().hex);profile.mkdir()\n  context=api.launch_persistent_context(str(profile),\n   executable_path=str(runtime/'chrome-headless-shell-win64/chrome-headless-shell.exe'),\n   chromium_sandbox=True,headless=True,service_workers='block',accept_downloads=False,\n   args=['--disable-background-networking','--disable-component-update','--disable-sync'],timeout=8000)\n  html='<meta charset=\"utf-8\"><input aria-label=\"名称\"><button>发送</button><output data-testid=\"result\">waiting</output><script>document.querySelector(\"button\").onclick=()=>{document.querySelector(\"output\").textContent=document.querySelector(\"input\").value;};</script>'\n  context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body=html))\n  context.route_web_socket('**/*',lambda route:route.close(code=1008))\n  page=context.pages[0] if context.pages else context.new_page()\n  page.goto('http://o1.localhost/app',wait_until='domcontentloaded',timeout=5000)\n  page.get_by_role('textbox',name='名称',exact=True).fill('你好',timeout=3000)\n  page.get_by_role('button',name='发送',exact=True).click(timeout=3000)\n  value=page.get_by_test_id('result').inner_text(timeout=3000)\n  result={'actual_text':value,'passed':value=='你好'}\n  context.close()\nexcept BaseException as error:\n result={'error':str(error),'sdk':api._last_error,'browser':getattr(api,'_last_browser_stderr',b'')[-1200:].decode('utf-8','replace')}\nprint(json.dumps(result),flush=True)\n"
        if private_gui:
            setup = "import ctypes\nfrom ctypes import wintypes\nfrom uuid import uuid4\nfrom backend.app.infrastructure.windows_process import ObservedProcess\nwith ObservedProcess(os.getpid()) as _owned:\n _identity=_owned.identity\nassert _identity.is_lpac is not False and _identity.is_appcontainer\n_u=ctypes.WinDLL('user32',use_last_error=True)\n_a=ctypes.WinDLL('advapi32',use_last_error=True)\n_k=ctypes.WinDLL('kernel32',use_last_error=True)\n_a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,ctypes.POINTER(wintypes.LPVOID),ctypes.POINTER(wintypes.DWORD)]\n_a.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype=wintypes.BOOL\n_k.LocalFree.argtypes=[wintypes.LPVOID]\n_u.CreateWindowStationW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID]\n_u.CreateWindowStationW.restype=wintypes.HANDLE\n_u.SetProcessWindowStation.argtypes=[wintypes.HANDLE]\n_u.SetProcessWindowStation.restype=wintypes.BOOL\n_u.CreateDesktopW.argtypes=[wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID]\n_u.CreateDesktopW.restype=wintypes.HANDLE\n_u.SetThreadDesktop.argtypes=[wintypes.HANDLE]\n_u.SetThreadDesktop.restype=wintypes.BOOL\nclass _SA(ctypes.Structure):\n _fields_=[('length',wintypes.DWORD),('descriptor',wintypes.LPVOID),('inherit',wintypes.BOOL)]\n_sd=wintypes.LPVOID()\n_sddl='D:P(A;OICI;GA;;;'+_identity.user_sid+')(A;OICI;GA;;;'+_identity.appcontainer_sid+')S:(ML;;NW;;;LW)'\nassert _a.ConvertStringSecurityDescriptorToSecurityDescriptorW(_sddl,1,ctypes.byref(_sd),None),ctypes.get_last_error()\ntry:\n _sa=_SA(ctypes.sizeof(_SA),_sd,False)\n _private_station=_u.CreateWindowStationW(None,1,0x37f|0x20000,ctypes.byref(_sa))\n assert _private_station,('create-station',ctypes.get_last_error())\n assert _u.SetProcessWindowStation(_private_station),('set-station',ctypes.get_last_error())\n _private_desktop=_u.CreateDesktopW('wallecheck-'+uuid4().hex,None,None,0,0x200c7,ctypes.byref(_sa))\n assert _private_desktop,('create-desktop',ctypes.get_last_error())\n assert _u.SetThreadDesktop(_private_desktop),('set-desktop',ctypes.get_last_error())\nfinally:\n assert not _k.LocalFree(_sd)\n"
            source = source.replace(
                'api=BrowserPipeProcess(runtime,profile,env,received)',
                setup + '\napi=BrowserPipeProcess(runtime,profile,env,received)',
            )
            source = source.replace('# PRIVATE_GUI_READY', setup)
        arguments = ['-I', '-B', '-c', source]
    else:
        from backend.app.infrastructure.windows_config_source import LockedFileSource

        origin = resources / 'check-browser-20261113-2341/vendor/playwright/driver/node.exe'
        image = runtime / 'node.exe'
        with LockedFileSource(origin, max_file_bytes=128 * 1024**2, capture_raw=False) as held:
            with image.open('xb') as output:
                held.consume_verified(output.write)
                output.flush()
                os.fsync(output.fileno())
        if kind == 'node-sdk':
            import shutil

            shutil.copytree(origin.parent / 'package', runtime / 'sdk')
            script = (
                'const sdk=require('
                + json.dumps(str(runtime / 'sdk'))
                + ");require('fs').writeSync(1,JSON.stringify({browser:sdk.chromium.name(),pipeOnly:true}));"
            )
        elif kind == 'node-spawn':
            script = r"""const cp=require('child_process');
let done=false;
function finish(value){if(done)return;done=true;require('fs').writeSync(1,JSON.stringify(value));process.exit();}
setTimeout(()=>finish({stage:'child-pipe',timeout:true}),2500);
require('fs').writeSync(1,JSON.stringify({stage:'before-spawn'}));
try {
 const child=cp.spawn(process.execPath,['-e',"require('fs').writeSync(1,'original-child')"],{stdio:['ignore','pipe','pipe']});
 let output='';child.stdout.on('data',chunk=>output+=chunk);
 child.on('error',error=>finish({stage:'child-pipe',error:error.code}));
 child.on('exit',(code,signal)=>finish({stage:'child-pipe',code,signal,output}));
} catch(error){finish({stage:'child-pipe',error:error.code});}"""
        elif kind == 'node-temp':
            script = (
                "const fs=require('fs');const prefix="
                + json.dumps(str(directories.root / 'scratch' / 'sdk-temp-'))
                + r""";let done=false;
function finish(value){if(done)return;done=true;fs.writeSync(1,JSON.stringify(value));process.exit();}
setTimeout(()=>finish({stage:'async-temp',timeout:true}),2500);
fs.promises.mkdtemp(prefix).then(value=>{fs.rmdirSync(value);finish({stage:'async-temp',created:true});},error=>finish({stage:'async-temp',error:error.code}));"""
            )
        else:
            script = (
                "require('fs').writeSync(1,JSON.stringify({node:process.version,pipeOnly:true}));"
            )
        arguments = [
            '--preserve-symlinks',
            '--preserve-symlinks-main',
            '--max-old-space-size=' + ('64' if kind == 'node-sdk' else '32'),
            '-e',
            script,
        ]
    raw = image.read_bytes()
    profile = TaskLpacProfile(directories, job)
    kernel, security = _api()
    kernel.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel.ResumeThread.restype = wintypes.DWORD
    info = ProcessInfo()
    created = False
    try:
        profile.prepare(lambda: False)
        with (
            ExecutablePin(
                image, expected_byte_count=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest()
            ) as pin,
            DiagnosticStdio() as streams,
        ):
            values = {
                'SystemRoot': os.environ['SystemRoot'],
                'SystemDrive': Path(os.environ['SystemRoot']).drive,
                'USERPROFILE': str(directories.root / 'scratch'),
                'APPDATA': str(directories.root / 'scratch'),
                'LOCALAPPDATA': str(directories.root / 'scratch'),
                'TEMP': str(directories.root / 'scratch'),
                'TMP': str(directories.root / 'scratch'),
            }
            block = ctypes.create_unicode_buffer(
                '\0'.join(k + '=' + values[k] for k in sorted(values)) + '\0\0'
            )
            with (
                directories._controller.creation_handle() as token,
                pin.creation_path() as application,
                job.process_creation_attributes(
                    lpac_profile=directories.profile,
                    stdio_handles=tuple(streams.child),
                    lpac_capability_names=capability_names,
                ) as attributes,
            ):
                startup = StartupInfoEx()
                startup.startup.cb = ctypes.sizeof(startup)
                startup.startup.desktop = desktop_name
                startup.startup.flags = 0x100
                startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = (
                    streams.child
                )
                startup.attributes = attributes
                if kind in ('headless-pipe-root', 'headless-debug-root'):
                    from uuid import uuid4

                    user_data = directories.root / 'scratch' / ('browser-' + uuid4().hex)
                    user_data.mkdir()
                    arguments = [
                        '--headless',
                        '--no-first-run',
                        '--no-default-browser-check',
                        '--disable-background-networking',
                        '--disable-component-update',
                        '--disable-sync',
                        '--remote-debugging-pipe',
                        '--remote-debugging-io-pipes='
                        + ','.join(str(value) for value in streams.child[:2]),
                        '--user-data-dir=' + str(user_data),
                        'about:blank',
                    ]
                command = ctypes.create_unicode_buffer(
                    subprocess.list2cmdline([application, *arguments])
                )
                kernel.SetErrorMode.argtypes = [wintypes.DWORD]
                kernel.SetErrorMode.restype = wintypes.DWORD
                previous_error_mode = (
                    kernel.SetErrorMode(3)
                    if kind in ('headless-pipe-root', 'headless-debug-root')
                    else None
                )
                try:
                    created_native = security.CreateProcessAsUserW(
                        token if logon_token is None else logon_token,
                        application,
                        command,
                        None,
                        None,
                        True,
                        0x4
                        | 0x80000
                        | 0x400
                        | 0x08000000
                        | (2 if kind == 'headless-debug-root' else 0),
                        block,
                        str(directories.root / 'workspace'),
                        ctypes.byref(startup),
                        ctypes.byref(info),
                    )
                    creation_error = ctypes.get_last_error()
                finally:
                    if previous_error_mode is not None:
                        kernel.SetErrorMode(previous_error_mode)
                assert created_native, creation_error
                created = True
                streams.close_child_ends()
            with_token = LpacProcessToken(
                info, job, profile, pin, capability_names=capability_names
            )
            try:
                with_token.verify()
                if kind == 'headless-debug-root':
                    from dataclasses import asdict
                    from backend.tests.infrastructure.v20_owned_debug_events import (
                        collect_owned_startup,
                    )

                    info._diagnostic_streams = streams
                    trace = asdict(collect_owned_startup(info, job))
                    print('PRIMARY_LPAC_HEADLESS_DEBUG', trace, flush=True)
                    return trace
                assert kernel.ResumeThread(info.thread) == 1
                if kind == 'headless-pipe-root':
                    from backend.tests.infrastructure.v20_owned_thread_sample import (
                        sample_owned_thread,
                    )
                    from backend.app.infrastructure.windows_pipe_capture import (
                        _read_api,
                        read_available_pipe,
                    )

                    request = b'{"id":1,"method":"Browser.getVersion"}\0'
                    write = streams.kernel.WriteFile
                    write.argtypes = [
                        wintypes.HANDLE,
                        wintypes.LPVOID,
                        wintypes.DWORD,
                        ctypes.POINTER(wintypes.DWORD),
                        wintypes.LPVOID,
                    ]
                    write.restype = wintypes.BOOL
                    sent = wintypes.DWORD()
                    buffer = ctypes.create_string_buffer(request)
                    assert write(
                        streams.parents[0], buffer, len(request), ctypes.byref(sent), None
                    ) and sent.value == len(request)
                    waiting = kernel.WaitForSingleObject(info.process, 5000)
                    sample = (
                        sample_owned_thread(info) if waiting == 258 else {'native_wait': waiting}
                    )
                    if waiting == 0:
                        code = wintypes.DWORD()
                        assert kernel.GetExitCodeProcess(info.process, ctypes.byref(code))
                        sample['exit_code'] = hex(code.value)
                    output = read_available_pipe(
                        _read_api(streams.kernel), streams.parents[1], 4096
                    )
                    sample['cdp'] = bool(output)
                    print('PRIMARY_LPAC_HEADLESS_OWNED_THREAD', sample, flush=True)
                    return sample
                waiting = kernel.WaitForSingleObject(
                    info.process, 4000 if kind == 'node-spawn' else 30000
                )
                if kind == 'node-spawn' and waiting == 258:
                    from backend.app.infrastructure.windows_pipe_capture import (
                        _read_api,
                        read_available_pipe,
                    )

                    output = read_available_pipe(
                        _read_api(streams.kernel), streams.parents[1], 4096
                    )
                    assert json.loads(output) == {'stage': 'before-spawn'}
                    print(
                        'PRIMARY_LPAC_RUNTIME node-spawn bounded native timeout after before-spawn',
                        flush=True,
                    )
                    return {'stage': 'before-spawn', 'native_timeout': True}
                assert waiting == 0
            finally:
                with_token.close()
            exit_code = wintypes.DWORD()
            assert kernel.GetExitCodeProcess(info.process, ctypes.byref(exit_code))
            from backend.app.infrastructure.windows_pipe_capture import (
                _read_api,
                read_available_pipe,
            )

            api = _read_api(streams.kernel)
            output = bytearray()
            while True:
                chunk = read_available_pipe(api, streams.parents[1], 4097 - len(output))
                if chunk is None:
                    break
                output.extend(chunk)
                assert len(output) <= 4096
            error = streams.stderr_bytes()
            print('PRIMARY_LPAC_RUNTIME', kind, exit_code.value, bytes(output), error, flush=True)
            assert exit_code.value == 0 and not error
            if kind == 'headless-root':
                return {'version': bytes(output).decode('utf-8').strip()}
            return json.loads(output)
    finally:
        if created:
            job.terminate_owned(0)
            assert kernel.WaitForSingleObject(info.process, 8000) == 0
            assert kernel.CloseHandle(info.thread)
            assert kernel.CloseHandle(info.process)
        journal.close_nonce(directories.scope)
        if profile._created:
            profile.release()
