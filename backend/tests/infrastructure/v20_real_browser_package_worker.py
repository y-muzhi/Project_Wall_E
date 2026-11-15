"""Actual fixed Chromium and existing CHECK_DRIVER comparison code, owned Job only."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep

from backend.app.infrastructure.windows_job import OwnedJob
from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot


def browser_matrix():
    from backend.tests.infrastructure.test_v20_check_case_pack import pack

    case = pack('BROWSER', timeout_seconds=30)
    from copy import deepcopy
    from backend.app.infrastructure.check_case_pack import CasePackLimits

    limits = CasePackLimits(2, 16, 16384, 30)
    field = {'kind': 'ROLE', 'value': 'textbox', 'name': '名称'}
    select = {'kind': 'ROLE', 'value': 'combobox', 'name': '类型'}
    button = {'kind': 'ROLE', 'value': 'button', 'name': '发送'}
    status = {'kind': 'TEST_ID', 'value': 'result'}
    html = """<meta charset="utf-8">
<input aria-label="名称"><select aria-label="类型"><option value="A">A</option><option value="B">B</option></select>
<button>发送</button><output data-testid="result"></output><script>
const field=document.querySelector('input'),select=document.querySelector('select'),out=document.querySelector('output');
const fresh=localStorage.getItem('prior-case')===null?'fresh':'reused';
localStorage.setItem('prior-case','seen');out.textContent=fresh;
let pressed='none';
field.addEventListener('keydown',event=>{if(event.key==='Enter')pressed='Enter';});
document.querySelector('button').addEventListener('click',()=>{out.textContent=field.value+'·'+select.value+'·'+pressed+'·'+fresh;});
</script>"""
    first = case['cases'][0]
    first['steps'] = [
        {'step_id': 'navigate', 'op': 'NAVIGATE', 'endpoint_ref': 'app', 'path': '/app'},
        {'step_id': 'fill', 'op': 'FILL', 'locator': field, 'value': '你好'},
        {'step_id': 'select', 'op': 'SELECT', 'locator': select, 'value': 'B'},
        {'step_id': 'press', 'op': 'PRESS', 'locator': field, 'value': 'Enter'},
        {'step_id': 'click', 'op': 'CLICK', 'locator': button},
    ]
    first['assertions'] = [
        {
            'assertion_id': 'text',
            'op': 'TEXT',
            'locator': status,
            'expected': '你好·B·Enter·fresh',
        },
        {'assertion_id': 'count', 'op': 'COUNT', 'locator': button, 'expected': 1},
        {'assertion_id': 'visible', 'op': 'VISIBLE', 'locator': button, 'expected': True},
    ]
    second = deepcopy(first)
    second['case_id'] = 'fresh-context'
    second['steps'] = first['steps'][:1]
    second['assertions'] = [
        {'assertion_id': 'fresh', 'op': 'TEXT', 'locator': status, 'expected': 'fresh'},
        {
            'assertion_id': 'absent',
            'op': 'VISIBLE',
            'locator': {'kind': 'TEST_ID', 'value': 'missing'},
            'expected': False,
        },
        {
            'assertion_id': 'different',
            'op': 'TEXT',
            'locator': status,
            'expected': 'intentionally-different',
        },
    ]
    case['cases'].append(second)
    expected = [['PASSED'] * 3, ['PASSED', 'PASSED', 'FAILED']]
    return case, html, limits, expected


def application_case_pack():
    from backend.tests.infrastructure.test_v20_check_case_pack import pack
    from backend.app.infrastructure.check_case_pack import CasePackLimits

    case = pack('BROWSER', timeout_seconds=30)
    case['cases'][0]['steps'] = [
        {'step_id': 'navigate', 'op': 'NAVIGATE', 'endpoint_ref': 'app', 'path': '/'},
        {
            'step_id': 'coding',
            'op': 'CLICK',
            'locator': {'kind': 'ROLE', 'value': 'button', 'name': '代码开发'},
        },
        {
            'step_id': 'testing',
            'op': 'CLICK',
            'locator': {'kind': 'ROLE', 'value': 'button', 'name': '测试验收'},
        },
        {
            'step_id': 'plans',
            'op': 'CLICK',
            'locator': {'kind': 'ROLE', 'value': 'button', 'name': '测试计划与资源'},
        },
    ]
    heading = {'kind': 'ROLE', 'value': 'heading', 'name': '测试计划目录'}
    case['cases'][0]['assertions'] = [
        {'assertion_id': 'visible', 'op': 'VISIBLE', 'locator': heading, 'expected': True},
        {'assertion_id': 'count', 'op': 'COUNT', 'locator': heading, 'expected': 1},
    ]
    return case, CasePackLimits(2, 16, 16384, 30), [['PASSED', 'PASSED']]


def exercise(package, backend=None, *, matrix=False):
    from backend.app.infrastructure.check_driver_browser import browser_input
    from backend.tests.infrastructure.test_v20_check_case_pack import BASIS, LIMITS, pack, raw
    from backend.tests.infrastructure.v20_browser_driver_native_worker import IDENTITY
    from hashlib import sha256

    case = pack('BROWSER', timeout_seconds=30)
    if backend is not None:
        case['cases'][0]['steps'] = [
            {'step_id': 'navigate', 'op': 'NAVIGATE', 'endpoint_ref': 'app', 'path': '/'},
            {
                'step_id': 'testing',
                'op': 'CLICK',
                'locator': {'kind': 'ROLE', 'value': 'button', 'name': '测试验收'},
            },
            {
                'step_id': 'plans',
                'op': 'CLICK',
                'locator': {'kind': 'ROLE', 'value': 'button', 'name': '测试计划与资源'},
            },
        ]
        case['cases'][0]['assertions'] = [
            {
                'assertion_id': 'visible',
                'op': 'VISIBLE',
                'locator': {'kind': 'ROLE', 'value': 'heading', 'name': '测试计划目录'},
                'expected': True,
            },
        ]
    html = '<meta charset="utf-8"><button>发送</button>'
    expected = [['PASSED']]
    limits = LIMITS
    if matrix:
        if backend is not None:
            raise ValueError('Matrix and backend are separate checks')
        case, html, limits, expected = browser_matrix()
    payload = browser_input(IDENTITY, raw(case), (BASIS,), limits, ('app',))
    source = """import io,json,os,sys
from pathlib import Path
from hashlib import sha256
from backend.app.infrastructure.check_driver_browser import _driver_input,execute_browser
from backend.app.infrastructure.check_driver_pipe_sdk import PipeChromium
"""
    source += 'backend=' + repr(backend) + '\n'
    source += 'payload=' + repr(payload) + '\n'
    source += 'html=' + repr(html) + '\n'
    source += 'expected=' + repr(expected) + '\n'
    source += 'digest=' + repr(sha256(raw(case)).hexdigest()) + '\n'
    source += (
        'browser='
        + repr(str(package / 'chrome-headless-shell-win64/chrome-headless-shell.exe'))
        + '\n'
    )
    with TemporaryDirectory(prefix='we-chromium-comparison-') as temporary:
        state = Path(temporary)
        result = state / 'result.txt'
        source += 'result=' + repr(str(result)) + '\n'
        source += """
try:
 identity,pack,origins=_driver_input(payload,digest)
 class Relay:
  failed=False
  def forward(self,route):
   if backend is None:
    assert route.request.url=='http://o1.localhost/app'
    route.fulfill(status=200,content_type='text/html',body=html)
   else:
    import socket
    from urllib.parse import urlsplit
    from urllib.request import urlopen
    from backend.app.infrastructure.windows_task_endpoints import _listeners
    port,pid=backend
    owners={p for family in (socket.AF_INET,socket.AF_INET6) for _,n,p in _listeners(family) if n==port}
    assert owners=={pid}
    address=urlsplit(route.request.url)
    assert address.scheme=='http' and address.netloc=='o1.localhost'
    assert route.request.method=='GET'
    target=address.path+('?' + address.query if address.query else '')
    with urlopen('http://127.0.0.1:'+str(port)+target,timeout=10) as response:
     body=response.read(8*1024*1024)
     route.fulfill(status=response.status,content_type=response.headers.get('content-type','application/octet-stream'),body=body)
  def close_websocket(self,route):
   self.failed=True
   route.close(code=1008)
 relay=Relay()
 writer=io.BytesIO()
 errors=[]
 with PipeChromium(Path(browser).parent.parent) as api:
  execute_browser(api,browser,Path(os.environ['TEMP']),identity,pack,origins,relay,writer)
 stream=io.BytesIO(writer.getvalue());frames=[]
 while header:=stream.read(4):
  frames.append(json.loads(stream.read(int.from_bytes(header,'big'))))
 assert [x['type'] for x in frames]==['BEGIN']+['CASE_RESULT']*len(expected)+['END']
 assert [[a['result'] for a in row['assertion_results']] for row in frames[1:-1]]==expected
 outcome='ACTUAL_CHROMIUM_CASE_PASSED'
except BaseException:
 import traceback
 outcome=traceback.format_exc()+chr(10)+'PAGE_ERRORS '+repr(locals().get('errors',[]))+chr(10)+'SDK_ERROR '+repr(getattr(locals().get('api'),'_diagnostic',b''))+chr(10)+'SDK_LAST_ERROR '+repr(getattr(locals().get('api'),'_last_error',None))
with open(result,'x',encoding='utf-8') as output:
 output.write(outcome)
"""
        compile(source, '<owned-browser-worker>', 'exec')
        with OwnedJob(active_process_limit=64, job_memory_limit_bytes=2 * 1024**3) as job:
            root = TestSuspendedRoot(
                job,
                state,
                source,
                executable=str(package / 'python.exe'),
                environment_values={
                    'SystemDrive': Path(os.environ['SystemRoot']).drive,
                    'USERPROFILE': str(state),
                    'LOCALAPPDATA': str(state),
                    'APPDATA': str(state),
                    'PROGRAMDATA': str(state),
                },
            )
            try:
                root.resume()
                deadline = monotonic() + 75
                while not result.exists() and monotonic() < deadline:
                    sleep(0.1)
                assert result.exists(), 'Owned Chromium diagnostic timed out'
                outcome = result.read_text(encoding='utf-8')
                assert outcome == 'ACTUAL_CHROMIUM_CASE_PASSED', outcome
                print(outcome, flush=True)
            finally:
                job.terminate_owned(0)
                assert root.kernel.WaitForSingleObject(root.info.process, 8000) == 0
                stopped = monotonic() + 8
                while job.observe_members().assigned_count:
                    if monotonic() >= stopped:
                        raise AssertionError('Original browser Job did not become empty')
                    sleep(0.01)
                root.close()


if __name__ == '__main__':
    import sys

    exercise(Path(sys.argv[1]).resolve(strict=True), matrix='--matrix' in sys.argv[2:])
