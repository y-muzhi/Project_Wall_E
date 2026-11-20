"""Version 2.1 offline inventory and execution over the existing isolation/process gates."""

import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from quality_gate import ROOT, commands, environment, fingerprint, run_stage

GROUPS = ('frontend', 'core', 'programs', 'ai', 'load')
STANDARD = GROUPS[:-1]
CORE = frozenset(
    {
        'contracts',
        'schema',
        'startup',
        'copy_upgrade',
        'resource_release',
        'workflow_wire',
        'frontend_reads',
        'frontend_preview',
        'read_boundaries',
        'http_errors',
    }
)
LONG = frozenset({'load_continuation', 'combined_growth_performance'})
AI = frozenset(
    {
        'complete_journey',
        'resume_terminal_matrix',
        'target_boundaries',
        'withdraw_revalidation',
        'message_read_protocol',
        'independent_operations',
        'legacy_write_integration',
        'revision_scope_maintenance',
        'staged_scope_maintenance',
    }
)


def group_for(path):
    name = path.stem.removeprefix('test_v21_')
    if name in LONG:
        return 'load'
    if name in CORE:
        return 'core'
    if name.startswith(('model_', 'discuss_', 'card_', 'proposal_')) or name in AI:
        return 'ai'
    return 'programs'


def inventory(root=ROOT):
    paths = sorted((root / 'backend/tests/formation').glob('test_v21_*.py'))
    result = {group: [] for group in GROUPS if group != 'frontend'}
    for path in paths:
        result[group_for(path)].append(path)
    if not paths or any(not files for files in result.values()):
        raise RuntimeError('V2.1 inventory must contain every required nonempty group')
    return result


def stage_commands(temporary, selected, root=ROOT):
    original = commands(temporary)
    files = inventory(root)
    result = []
    if 'frontend' in selected:
        for stage in ('frontend', 'typecheck', 'format', 'python-format', 'build'):
            result.append((stage, *original[stage]))
    for group in selected:
        if group == 'frontend':
            continue
        command = [
            sys.executable,
            '-B',
            str(root / 'tools/python-v20.py'),
            str(root / 'tools/quality_python.py'),
            *[str(path) for path in files[group]],
            '-q',
            '-p',
            'no:cacheprovider',
            '--tb=short',
            '--basetemp',
            str(temporary / ('pytest-' + group)),
        ]
        result.append(('backend-' + group, command, root))
    return result


def save_report(selected, expected, results, before, after, cleanup, started, head, root=ROOT):
    passed = (
        bool(expected)
        and len(results) == len(expected)
        and [row['stage'] for row in results] == list(expected)
        and all(row['status'] == 'PASSED' for row in results)
        and before == after
        and cleanup
    )
    status = 'PASSED' if passed else 'FAILED'
    if any(row['status'] == 'CANCELLED' for row in results):
        status = 'CANCELLED'
    scope = '含长负载的完整入口范围' if tuple(selected) == GROUPS else '明确分组（非整版验收）'
    lines = [
        '# V2.1离线检查入口结果',
        '',
        f'日期：{started.isoformat()}；Git HEAD：{head}；范围：{scope}。',
        '分组：' + ', '.join(selected) + '；结果：' + status + '。',
        f'源码/资源摘要：{before}；运行期间保持：{before == after}；临时清理：{cleanup}。',
        '',
        '| 阶段 | 状态 | 秒 | 摘要 |',
        '| --- | --- | ---: | --- |',
    ]
    for row in results:
        summary = row['summary'].replace('|', '／').replace('\n', ' ')
        lines.append(f'| {row["stage"]} | {row["status"]} | {row["seconds"]} | {summary} |')
    for stage in expected:
        if stage not in {row['stage'] for row in results}:
            lines.append(f'| {stage} | NOT_RUN | — | 未执行 |')
    if 'load' not in selected:
        lines += ['', '本次未执行load的两项长负载；已有独立历史证据按原日期保留。']
    lines += [
        '',
        '固定Windows x64 SQLite；Python禁止外网/正常库及本地凭据，前端复用原离线预载。',
        '原始输出仅在内存，临时目录在完成/失败/取消后清理；仅留本Markdown。',
        '没有真实模型/计数、用户服务修改、正常库迁移、供应方效果或GitHub执行通过声明。',
        '',
    ]
    folder = root / 'docs/verification/v2.1'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (
        'offline-gate-' + started.strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8] + '.md'
    )
    temporary = target.with_name('.' + target.name + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write('\n'.join(lines))
            stream.flush()
            os.fsync(stream.fileno())
        if target.exists():
            raise RuntimeError('Unique verification report unexpectedly exists')
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target, 0 if passed else 1


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group', choices=('standard', 'all', *GROUPS), default='standard')
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--timeout', type=int, default=5400)
    args = parser.parse_args(argv)
    if args.timeout < 1:
        parser.error('--timeout must be positive')
    selected = (
        STANDARD if args.group == 'standard' else GROUPS if args.group == 'all' else (args.group,)
    )
    files = inventory()
    if args.list:
        print('V2.1 groups: ' + ', '.join(selected))
        for group in selected:
            if group == 'frontend':
                print('frontend: original complete Node/type/format/backend-format/temporary build')
            else:
                print(group + ': ' + str(len(files[group])) + ' files')
                for path in files[group]:
                    print(path.relative_to(ROOT).as_posix())
        if 'load' not in selected:
            print('NOT_SELECTED: load; use --group load or --group all')
        return 0
    started = datetime.now(timezone(timedelta(hours=8)))
    before = fingerprint()
    results = []
    cleanup = False
    expected = ()
    try:
        head = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.SubprocessError):
        head = 'unavailable'
    try:
        with TemporaryDirectory(prefix='w21q-') as directory:
            temporary = Path(directory)
            stages = stage_commands(temporary, selected)
            expected = tuple(stage for stage, _command, _cwd in stages)
            env = environment(temporary)
            for stage, command, cwd in stages:
                result = run_stage(stage, command, cwd, env, args.timeout)
                results.append(result)
                print(stage + ': ' + result['status'] + '; ' + result['summary'], flush=True)
                if result['status'] == 'CANCELLED':
                    break
        cleanup = not temporary.exists()
    except (OSError, RuntimeError) as error:
        print('Preparation/cleanup failed: ' + type(error).__name__, flush=True)
    if not expected:
        expected = ('PREPARATION',)
    path, code = save_report(
        selected, expected, results, before, fingerprint(), cleanup, started, head
    )
    print('Report: ' + path.relative_to(ROOT).as_posix(), flush=True)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with Path(summary).open('a', encoding='utf-8') as stream:
            stream.write(path.read_text(encoding='utf-8'))
    return code
