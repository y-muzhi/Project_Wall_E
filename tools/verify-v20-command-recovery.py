"""Bounded own browser checks, real kill-on-close Job and exact temporary cleanup."""

import argparse
from pathlib import Path
import shutil
import sys
import tempfile
from time import monotonic, sleep

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.infrastructure.windows_job import OwnedJob
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli-entry', type=Path, required=True)
    parser.add_argument(
        '--probe',
        choices=(
            'all',
            'configuration',
            'settings',
            'testing-settings',
            'testing-plan-editor',
            'testing-task-workspace',
            'tasks',
            'role-reconciliation',
            'role-creation-reconciliation',
            'repair-reconciliation',
            'repair-creation-reconciliation',
            'repair-settled-reconciliation',
            'coding-report-link',
            'coding-delivery',
            'coding-records',
            'coding-live-configuration',
        ),
        default='all',
    )
    args = parser.parse_args()
    entry = args.cli_entry.resolve(strict=True)
    if entry.name != 'playwright-cli.js':
        raise ValueError('Installed Playwright CLI entry required')
    base = ROOT / 'output/playwright'
    base.mkdir(parents=True, exist_ok=True)
    if base.resolve() != base.absolute() or not base.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError('Owned test parent must stay within the workspace')
    work = Path(tempfile.mkdtemp(prefix='v20-idb-', dir=base))
    worker = (
        'import subprocess,os; from pathlib import Path; '
        + 'work=Path('
        + repr(str(work))
        + '); '
        + "env=dict(os.environ); env['TEMP']=str(work); env['TMP']=str(work); "
        + "stream=(work/'runner.log').open('xb'); "
        + 'result=subprocess.run(['
        + repr(r'C:\Program Files\nodejs\node.exe')
        + ', '
        + repr(str(ROOT / 'tools/verify-v20-command-recovery.mjs'))
        + ', '
        + "'--work',"
        + repr(str(work))
        + ",'--cli-entry',"
        + repr(str(entry))
        + ",'--probe',"
        + repr(args.probe)
        + '],cwd='
        + repr(str(ROOT))
        + ',env=env,stdout=stream,stderr=subprocess.STDOUT); '
        + 'stream.flush();os.fsync(stream.fileno());stream.close();'
        + 'raise SystemExit(result.returncode)'
    )
    job = OwnedJob(active_process_limit=96, job_memory_limit_bytes=4 * 1024**3)
    child = None
    empty = False
    success = False
    try:
        child = TestSuspendedRoot(job, work, worker)
        child.resume()
        with ObservedProcess(child.pid) as process:
            deadline = monotonic() + (300 if args.probe == 'tasks' else 180)
            while process.observe().state == 'RUNNING' and monotonic() < deadline:
                sleep(0.05)
            final = process.observe()
            print('OWNED_BROWSER_WORKER', final.state, final.exit_code, flush=True)
            if final.state == 'EXITED' and final.exit_code == 0:
                success = True
        log = work / 'runner.log'
        if log.exists():
            print(log.read_text(encoding='utf-8', errors='replace')[-20000:], flush=True)
    finally:
        job.terminate_owned(1)
        deadline = monotonic() + 10
        while monotonic() < deadline:
            members = job.observe_members()
            if members.complete and not members.process_ids:
                empty = True
                break
            sleep(0.05)
        job.close()
        if child is not None:
            child.close()
        if empty:
            absolute = work.resolve(strict=True)
            if absolute.parent != base.resolve() or not absolute.name.startswith('v20-idb-'):
                raise ValueError('Refusing cleanup outside this exact owned test root')
            shutil.rmtree(absolute)
            print('OWNED_JOB_EMPTY_AND_BROWSER_OUTPUT_CLEANED', flush=True)
        else:
            print('OWNED_CLEANUP_UNVERIFIED', work, flush=True)
    if not success or not empty:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
