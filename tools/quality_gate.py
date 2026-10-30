"""Shared local/CI runner. Captures raw output in memory and keeps Markdown only."""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
STAGES = ('runner', 'format', 'python-format', 'frontend', 'typecheck', 'build', 'backend')
LABELS = dict(zip(STAGES,('检查程序自检','前端格式','后端格式','前端测试','前端类型','临时生产构建','V1.5后端测试')))


def backend_files(root=ROOT):
    return sorted({*root.glob('backend/tests/**/test_v15*.py'),
        root/'backend/tests/infrastructure/test_collaboration_resources.py',
        root/'backend/tests/infrastructure/test_model_profile_audit_data.py'})


def environment(temporary, source=None):
    source = os.environ if source is None else source
    values = {key:value for key,value in source.items() if not (
        key.upper().startswith(('WALLE_', 'PYTHON', 'NODE_OPTIONS', 'NODE_PATH'))
        or any(word in key.upper() for word in ('TOKEN','SECRET','PASSWORD','API_KEY'))
        or key.upper() in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY'))}
    values.update(PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8', PYTHONUTF8='1',
        PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', WALLE_CHECK_TEMP=str(temporary),
        TMP=str(temporary), TEMP=str(temporary), TMPDIR=str(temporary), NO_COLOR='1', CI='true')
    return values


def fingerprint(root=ROOT):
    digest=hashlib.sha256()
    files={root/'frontend/package.json',root/'frontend/package-lock.json',root/'backend/requirements.lock',root/'backend/requirements-dev.lock',root/'ruff.toml',root/'frontend/.prettierrc.json'}
    files.update((root/'frontend').glob('*config*'))
    files.update((root/'.github/workflows').glob('*.yml'))
    for area in ('backend/app','backend/tests','backend/resources','frontend/src','frontend/tests','tools'):
        files.update(p for p in (root/area).rglob('*') if p.is_file() and not any(part in ('__pycache__','node_modules','.pytest_cache') for part in p.parts))
    for path in sorted(files):
        digest.update(path.relative_to(root).as_posix().encode());digest.update(b'\0');digest.update(path.read_bytes())
    return digest.hexdigest()


def commands(temporary):
    preload=[shutil.which('node') or 'node','--require',str(ROOT/'tools/quality_node.cjs')]
    tests=sorted((ROOT/'frontend/tests').glob('*.test.mjs'));backend=backend_files()
    if not (ROOT/'tools/tests/test_quality_gate.py').is_file() or not tests or not backend or any(not p.is_file() for p in backend):
        raise RuntimeError('Test inventory is empty or incomplete')
    return {
        'runner':([sys.executable,'-B','-m','unittest','discover','-s','tools/tests','-p','test_quality_gate.py','-q'],ROOT),
        'python-format':([sys.executable,'-m','ruff','format','--no-cache','--check','backend/app'],ROOT),
        'format':([*preload,'node_modules/prettier/bin/prettier.cjs','--check','src/**/*.{ts,tsx,css}'],ROOT/'frontend'),
        'frontend':([*preload,'--test','--test-isolation=none','--test-reporter=tap',*[str(p) for p in tests]],ROOT/'frontend'),
        'typecheck':([*preload,'node_modules/typescript/bin/tsc','--noEmit'],ROOT/'frontend'),
        'build':([*preload,'node_modules/vite/bin/vite.js','build','--outDir',str(temporary/'frontend-build')],ROOT/'frontend'),
        'backend':([sys.executable,'-B',str(ROOT/'tools/quality_python.py'),*[str(p) for p in backend],
            '-q','-p','no:cacheprovider','--tb=short','--basetemp',str(temporary/'pytest')],ROOT),
    }


def stop_owned(process):
    if process.poll() is not None: return
    if os.name == 'nt':
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=15)
    else: os.killpg(process.pid,signal.SIGKILL)
    process.wait(timeout=15)


def summarize(output, code):
    lines=output.splitlines()
    summaries=[line.strip() for line in lines if (re.search(r'\d+ (passed|failed|errors?|skipped)',line)
        and not line.startswith(('E ','> '))) or re.match(r'^# (tests|pass|fail|cancelled|skipped) \d+$',line)]
    failures=[line.strip()[:300] for line in lines if line.startswith(('FAILED ','ERROR ','not ok '))]
    if not summaries:
        summaries=[next((line.strip()[:250] for line in lines if re.match(r'Ran \d+ tests?',line)),
            '命令正常退出' if code == 0 else '命令失败；请按记录中的范围单独诊断')]
    return '; '.join(summaries[-6:]), failures[:20]


def run_stage(name, command, cwd, env, timeout):
    started=monotonic();process=None
    result={'stage':name,'status':'FAILED','seconds':0,'code':None,'summary':'','failures':[]}
    try:
        process=subprocess.Popen(command,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            text=True,encoding='utf-8',errors='replace',
            **({'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=='nt' else {'start_new_session':True}))
        heartbeat=started
        while True:
            try:
                output,_=process.communicate(timeout=min(5,max(.1,timeout-(monotonic()-started))))
                result['code']=process.returncode
                result['status']='PASSED' if process.returncode==0 else 'FAILED'
                result['summary'],result['failures']=summarize(output,process.returncode)
                if name in ('runner','frontend') and re.search(r'(?:Ran 0 tests|^# tests 0$)',output,re.M):
                    result.update(status='FAILED',summary='没有实际执行测试')
                break
            except subprocess.TimeoutExpired:
                elapsed=monotonic()-started
                if elapsed>=timeout:
                    stop_owned(process);process.communicate()
                    result.update(status='TIMEOUT',summary=f'超过本步骤{timeout}秒限额，已停止所属子进程');break
                if monotonic()-heartbeat>=30:
                    print(f'[{name}] running: {int(elapsed)}s',flush=True);heartbeat=monotonic()
    except KeyboardInterrupt:
        if process is not None: stop_owned(process);process.communicate()
        result.update(status='CANCELLED',summary='用户中断，已停止所属子进程')
    except (OSError, subprocess.SubprocessError) as error:
        if process is not None: stop_owned(process)
        result.update(summary='无法完成命令：'+type(error).__name__)
    result['seconds']=round(monotonic()-started,2)
    return result


def write_report(results, selected, before, after, temporary, cleanup, started, head):
    complete=tuple(selected)==STAGES
    passed=len(results)==len(selected) and all(item['status']=='PASSED' for item in results) and cleanup and before==after
    status='PASSED' if passed else 'FAILED'
    if any(row['status']=='CANCELLED' for row in results): status='CANCELLED'
    lines=['# V1.5离线检查结果','',f'开始：{started.isoformat()}；范围：'+('完整检查' if complete else '部分检查（不代表完整门禁通过）'),
        f'结果：**{status}**；Git HEAD：`{head}`；检查实际保存的工作区（含未提交变更）。',
        f'源码／测试／资源摘要：`{before}`；运行期间是否保持：`{before==after}`。','',
        '## 分项结果','', '| 步骤 | 状态 | 秒 | 退出码 | 摘要 |','| --- | --- | --- | --- | --- |']
    for row in results:
        summary=row['summary'].replace('|','／').replace('\n',' ')
        lines.append(f"| {LABELS[row['stage']]} | {row['status']} | {row['seconds']} | {row['code']} | {summary} |")
    for name in selected:
        if not any(row['stage']==name for row in results):lines.append(f'| {LABELS[name]} | NOT_RUN | — | — | 前序中断／准备失败 |')
    lines+=['','## 执行范围','',f'Python：{sys.version.split()[0]}；平台：{sys.platform}；每步命令参数见`tools/quality_gate.py`。',
        '后端选择所有backend/tests/**/test_v15*.py及资源／模型快照审计专项；前端选择tests/*.test.mjs。',
        '临时工作目录：`'+str(temporary)+'`；清理成功：`'+str(cleanup)+'`。',
        'Python外部网络与正常data访问被拒绝、SQLite限定临时根；Node检查拒绝真实连接。原始输出仅在内存，未保留日志／JSON／截图。',
        '不会安装依赖、使用用户服务、加载本地凭据或部署dist；模拟结果不代表真实模型效果或浏览器验收。','']
    for row in results:
        if row['failures']:
            lines += ['### '+LABELS[row['stage']]+'失败定位','']+['- `'+value.replace('`','')+'`' for value in row['failures']]+['']
    if before!=after:lines+=['检查期间源码发生变化，本次不能作为同一代码状态的完整通过依据。','']
    path=ROOT/'docs/verification/v1.5'/('quality-gate-'+started.strftime('%Y-%m-%d-%H%M%S-%f')+'.md')
    with path.open('x',encoding='utf-8',newline='\n') as handle:handle.write('\n'.join(lines))
    return path, 0 if passed else 130 if status=='CANCELLED' else 1


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list',action='store_true',help='只列出范围，不运行')
    parser.add_argument('--only',choices=STAGES,action='append',help='只运行指定步骤；报告标记部分检查')
    parser.add_argument('--timeout',type=int,default=1800,help='每步骤最大秒数，默认1800')
    args=parser.parse_args(argv)
    if args.timeout<1:parser.error('--timeout必须为正整数')
    selected=tuple(stage for stage in STAGES if not args.only or stage in args.only)
    if args.list:
        print('Steps: '+', '.join(selected));print('Backend files: '+str(len(backend_files())))
        print('Frontend files: '+str(len(list((ROOT/'frontend/tests').glob('*.test.mjs')))))
        for path in backend_files():print(path.relative_to(ROOT).as_posix())
        return 0
    started=datetime.now(timezone(timedelta(hours=8)));before=fingerprint();results=[]
    try:head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,stderr=subprocess.DEVNULL).strip()
    except (OSError,subprocess.SubprocessError):head='unavailable'
    temporary=None;cleanup=False
    try:
        # EV fixtures contain deep audit paths; reserve Windows MAX_PATH space.
        with TemporaryDirectory(prefix='wq-') as directory:
            temporary=Path(directory);command_map=commands(temporary);env=environment(temporary)
            for index,name in enumerate(selected,1):
                print(f'[{index}/{len(selected)}] {name}',flush=True)
                command,cwd=command_map[name];row=run_stage(name,command,cwd,env,args.timeout);results.append(row)
                print(f"[{name}] {row['status']} ({row['seconds']}s): {row['summary']}",flush=True)
                if row['status']=='CANCELLED':break
        cleanup=not temporary.exists()
    except (OSError,RuntimeError) as error:print('Preparation/cleanup failed: '+type(error).__name__,flush=True)
    path,code=write_report(results,selected,before,fingerprint(),temporary,cleanup,started,head)
    print('Report: '+str(path.relative_to(ROOT)),flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as handle:
            handle.write(path.read_text(encoding='utf-8'))
    return code
