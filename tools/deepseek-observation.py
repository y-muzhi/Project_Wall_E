"""Offline preparation by default; one explicitly authorized bounded AI run.

Reuses frozen synthetic inputs, never opens the application database or a test
fixture database. Raw responses stay in memory; only a Markdown summary remains.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.infrastructure.audit_data import MAX_AUDIT_BYTES
from backend.app.infrastructure.framing_probe import (
    build_plan, validate_plan, digest, collect_observations, MemoryProbeJournal)
from backend.app.infrastructure.local_credentials import read_local_credential
from backend.app.infrastructure.model_profile import ModelProfile, DEFAULT_PROFILE
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.shared.validation import strict_json_object

PLAN = ROOT / 'docs/proposals/deepseek-observation-plan-v2.json'
SOURCE = ROOT / 'docs/proposals/framing-observation-plan-v1.json'


def read_plan(path):
    with path.open('rb') as handle:
        encoded = handle.read(MAX_AUDIT_BYTES + 1)
    if len(encoded) > MAX_AUDIT_BYTES:
        raise ConfigInvalid('Plan exceeds capacity')
    return validate_plan(strict_json_object(encoded))


def summary(plan, journal, outcome):
    records = journal.records
    report = records.get('report', {})
    counts = sum(name.endswith('count-prepared') for name in records)
    chats = sum(name.endswith('chat-prepared') for name in records)
    lines = [f'\n结束时间：{datetime.now(timezone.utc).isoformat()}。',
             f'\n执行状态：{outcome}。计数适配器进入次数 {counts}/6；Chat 适配器进入次数 {chats}/6。',
             '\n次数是本进程进入适配器的记录，不推断远端实际请求、计费或中断时的计算状态。',
             '\n| Function | 文本计数 | 实际输入 | 实际输出 | 封装差值 | Schema |',
             '| --- | ---: | ---: | ---: | ---: | --- |']
    observations = report.get('observations', [])
    # Cancellation may precede the final report: preserve only safely verified
    # observations already returned, never guess usage from a partial envelope.
    for item in observations:
        schema = {True:'通过', False:'未通过'}.get(item.get('output_schema_valid'), '未执行')
        lines.append(f"| {item['function_type']} | {item['counted_system_tokens'] + item['counted_user_tokens']} | {item['actual_prompt_tokens']} | {item['actual_completion_tokens']} | {item['observed_framing_delta']} | {schema} |")
    reason = report.get('stopped_reason')
    if reason in ('CONFIG_INVALID', 'OUTPUT_INVALID'):
        lines.append(f'\n停止原因：{reason}。')
    for index, case in enumerate(plan['cases'], 1):
        record = records.get(f'{index:02d}-chat-finished', {})
        category = record.get('category')
        # Only adapter-owned enum text is recorded, never provider messages.
        if type(category) is str and 0 < len(category) <= 64 and all('A' <= char <= 'Z' or char == '_' for char in category):
            status = record.get('http_status')
            safe_status = str(status) if type(status) is int and 100 <= status <= 599 else '未知'
            lines.append(f'\n{case["function_type"]} 传输失败：{category}，HTTP {safe_status}。')
    lines += ['\n有限样本不证明全输入封装上界；未做业务采用、效果验收或生产启用。',
              '\n原始请求、响应与密钥未写入本记录；没有生成测试 JSON、截图或原始日志。',
              '\n此计划的执行名额已使用，不自动补跑、重试或恢复。\n']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--authorized-plan-sha256')
    parser.add_argument('--credential-file', type=Path)
    args = parser.parse_args()
    if args.prepare and (args.execute or args.authorized_plan_sha256 or args.credential_file):
        parser.error('preparation cannot execute or read credentials')
    if not args.execute and (args.authorized_plan_sha256 or args.credential_file):
        parser.error('credentials and authorization require explicit execution')
    if args.prepare:
        source = read_plan(SOURCE)
        inputs = [{'function_type':case['function_type'], 'version':case['version'],
                   'input':strict_json_object(case['input_json'])} for case in source['cases']]
        plan = build_plan(inputs, profile=ModelProfile('offline-plan-no-credential', DEFAULT_PROFILE))
        encoded = (json.dumps(plan, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        if PLAN.exists():
            if PLAN.read_bytes() != encoded:
                raise ConfigInvalid('Existing candidate plan differs; no overwrite')
        else:
            with PLAN.open('xb') as handle:
                handle.write(encoded)
    else:
        plan = read_plan(PLAN)
    plan_hash = digest(plan)
    print(f'模型：{plan["profile"]["model_name"]}\n计划 SHA-256：{plan_hash}')
    print('上限：6 次 Tokenization＋6 次 Chat；无重试；请求输出上限合计 49152 token。')
    if not args.execute:
        print('离线准备；真实请求 0；未读取密钥；生产门禁保持关闭。')
        return
    if args.authorized_plan_sha256 != plan_hash:
        raise ConfigInvalid('Human authorization must bind this exact plan')
    # Explicit file argument wins. Otherwise use the child environment, then
    # the ignored project-local file. Nothing is exported or echoed to a shell.
    key = read_local_credential(args.credential_file) if args.credential_file else os.environ.get('WALLE_MODEL_API_KEY')
    if not key:
        key = read_local_credential(ROOT / '.env.local')
    profile = ModelProfile(key, DEFAULT_PROFILE)
    if profile.snapshot != plan['profile']:
        raise ConfigInvalid('Plan profile differs')
    note = ROOT / 'docs/verification' / ('deepseek-observation-' + plan_hash + '.md')
    # A durable exclusive Markdown claim prevents repeating this one-round
    # license, including after failure, interruption or a process restart.
    with note.open('x', encoding='utf-8', newline='\n') as handle:
        handle.write('# DeepSeek 有界调用记录\n\n')
        handle.write(f'计划 SHA-256：{plan_hash}。\n\n')
        handle.write(f'开始时间：{datetime.now(timezone.utc).isoformat()}。\n\n')
        handle.write('执行名额已占用；若记录未结束则按中断或未知处理，禁止自动重放。\n')
        handle.flush()
        os.fsync(handle.fileno())
    journal = MemoryProbeJournal()
    outcome = '中断或异常，远端结果可能未知'
    complete = False
    try:
        report = asyncio.run(collect_observations(plan, profile, None,
            authorized_plan_sha256=plan_hash, journal_factory=lambda _: journal))
        complete = report['complete_observations']
        outcome = '六项观测完成' if complete else '首次失败后停止'
    finally:
        with note.open('a', encoding='utf-8', newline='\n') as handle:
            handle.write(summary(plan, journal, outcome))
            handle.flush()
            os.fsync(handle.fileno())
        journal.records.clear()
    print(f'仅保留 Markdown：{note}')
    if not complete:
        raise SystemExit(1)


if __name__ == '__main__':
    try:
        main()
    except (ConfigInvalid, ValueError, OSError, KeyboardInterrupt):
        print('准备或调用已停止；不自动重试。若已占用执行名额，请查看 Markdown 记录。', file=sys.stderr)
        raise SystemExit(1)
