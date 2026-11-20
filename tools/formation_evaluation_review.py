"""Offline EV60 review templates and strict two-person result aggregation.

This tool cannot execute a provider or change resource admission. Human documents
are evidence assertions; their independent authorship is verified by the release owner.
"""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

from formation_evaluation import digest, manifest_rows, new_markdown, stable
from formation_evaluation_spec import TASKS, samples

REVIEW_COLUMNS = (
    'Sample',
    'Rights',
    'Protocol',
    'Critical',
    'Usable',
    'Decision',
    'Reason',
    'Evidence',
)
ATTEMPT_COLUMNS = (
    'Sample',
    'Status',
    'Chat attempts',
    'Count batches',
    'Counted input',
    'Usage input',
    'Usage output',
    'Request SHA256',
    'Evidence',
)
RESULTS = {
    'NOT_RUN',
    'PREFLIGHT_REJECTED',
    'TRANSPORT_ERROR',
    'STRUCTURED_REJECTED',
    'LIVE_RETURNED',
}
IDENTITIES = tuple(sample.sample_id for sample in samples())


def field(content, name):
    values = re.findall(r'^' + re.escape(name) + r': ([^\r\n]+)$', content, re.MULTILINE)
    if len(values) != 1:
        raise ValueError('Missing or duplicate ' + name)
    return values[0].strip()


def table(content, columns):
    result = {}
    for line in content.splitlines():
        if not line.startswith('| EV21-'):
            continue
        row = tuple(value.strip() for value in line.strip('|').split('|'))
        if len(row) != len(columns) or row[0] not in IDENTITIES or row[0] in result:
            raise ValueError('Unexpected, duplicate or malformed EV row')
        result[row[0]] = dict(zip(columns, row, strict=True))
    if set(result) != set(IDENTITIES):
        raise ValueError('All 60 samples must remain in the denominator')
    return result


def frozen_manifest(content):
    rows = manifest_rows(content)
    identities = {row[0] for row in rows}
    if identities != set(IDENTITIES) or field(content, 'Samples') != '60':
        raise ValueError('A complete frozen manifest is required')
    if field(content, 'Cohort-SHA256') != digest(stable(rows)):
        raise ValueError('Frozen cohort digest differs')
    if field(content, 'Candidates') != str(len(rows)):
        raise ValueError('Frozen candidate count differs')
    for identity in IDENTITIES:
        candidates = [row for row in rows if row[0] == identity]
        if candidates[0][1] != 'full' or any(
            row[1] not in ('full', 'no-history', 'required') for row in candidates
        ):
            raise ValueError('Frozen candidate order/variant differs')
        for row in candidates:
            if any(
                re.fullmatch(r'[0-9a-f]{64}', row[index]) is None
                for index in (4, 5, 6, 7, 8, 9, 11)
            ):
                raise ValueError('Malformed frozen input digest')
    if '状态：INPUTS_FROZEN' not in content:
        raise ValueError('Partial or superseded inputs cannot be reviewed')
    return {identity: {row[9] for row in rows if row[0] == identity} for identity in IDENTITIES}


def binding(content, manifest):
    if any(
        field(content, name) != field(manifest, name)
        for name in ('Cohort-SHA256', 'Profile', 'Release-SHA256')
    ):
        raise ValueError('Review/attempt cohort Profile or release differs')
    if field(content, 'Manifest-SHA256') != digest(manifest):
        raise ValueError('Review/attempt evidence uses different frozen input bytes')


def template(manifest, kind):
    frozen_manifest(manifest)
    lines = [
        '# V2.1 EV60' + ('实际尝试登记' if kind == 'attempts' else '独立人工评价'),
        '',
        '状态：NOT_RUN。本表没有真实调用或人工评价结果。',
        'Manifest-SHA256: ' + digest(manifest),
        'Cohort-SHA256: ' + field(manifest, 'Cohort-SHA256'),
        'Profile: ' + field(manifest, 'Profile'),
        'Release-SHA256: ' + field(manifest, 'Release-SHA256'),
    ]
    if kind == 'review':
        lines += [
            'Reviewer-ID: UNASSIGNED',
            '',
            '由一名实际评审者独立填写；不得复制另一人的结论。'
            '各项用PASS/FAIL/PENDING，Reason简述判据与缺口，Evidence指向批准的Markdown证据/真实来源。'
            '普通讨论Decision用DISCUSS/REUSE/NEW；其他任务NA。分歧记未通过，不删样本。',
        ]
        columns = REVIEW_COLUMNS
        rows = [
            (
                identity,
                'PENDING',
                'PENDING',
                'PENDING',
                'PENDING',
                'PENDING' if identity.endswith('-DISCUSS') else 'NA',
                '待独立评价',
                '—',
            )
            for identity in IDENTITIES
        ]
    else:
        lines += [
            '',
            '每个固定样本最多1次Chat，无自动重试。NOT_RUN不是失败或成功；'
            '已执行的拒绝/失败计入60分母，不替换样本。真实计数批次沿冻结候选顺序，最多3批；'
            '实际Request SHA必须匹配本样本冻结候选，不能在失败后修改请求再标同一尝试。'
            '未知供应方usage填UNKNOWN，未执行填—；Counted input为真实发送前计数(含预留)，禁止按字符估算。'
            'Evidence提供真实Run/LLMUse/计数/结果的批准Markdown引用，不粘贴原始JSON或凭据。',
        ]
        columns = ATTEMPT_COLUMNS
        rows = [(identity, 'NOT_RUN', '0', '0', '—', '—', '—', '—', '—') for identity in IDENTITIES]
    lines += [
        '',
        '| ' + ' | '.join(columns) + ' |',
        '| ' + ' | '.join('---' for _ in columns) + ' |',
    ]
    lines.extend('| ' + ' | '.join(row) + ' |' for row in rows)
    lines += ['', '判据与阈值见固定输入清单及后端8.3；该文档自身不会授予LIVE准入。', '']
    return '\n'.join(lines)


def evidence(value):
    return value not in ('', '—', '-', 'PENDING', 'UNKNOWN', '待评价') and len(value) >= 3


def natural(value):
    if re.fullmatch(r'0|[1-9][0-9]*', value) is None:
        raise ValueError('Expected a nonnegative decimal counter')
    return int(value)


def aggregate(manifest, attempt_text, left_text, right_text):
    hashes = frozen_manifest(manifest)
    for content in (attempt_text, left_text, right_text):
        binding(content, manifest)
    reviewers = [field(content, 'Reviewer-ID') for content in (left_text, right_text)]
    if reviewers[0] == reviewers[1] or any(
        name.upper() in ('UNASSIGNED', 'PENDING', 'TBD') or name.startswith('待')
        for name in reviewers
    ):
        raise ValueError('Two different assigned independent human reviewers are required')
    attempts = table(attempt_text, ATTEMPT_COLUMNS)
    left, right = (table(content, REVIEW_COLUMNS) for content in (left_text, right_text))
    usable = Counter()
    critical_failures = []
    pending = []
    failed = []
    for sample in samples():
        identity = sample.sample_id
        attempt = attempts[identity]
        status = attempt['Status']
        chats, counts = natural(attempt['Chat attempts']), natural(attempt['Count batches'])
        if status not in RESULTS or chats > 1 or counts > len(hashes[identity]):
            raise ValueError('Invalid status or unauthorized retry in ' + identity)
        if status == 'NOT_RUN':
            if (
                chats != 0
                or counts != 0
                or any(
                    attempt[name] != '—'
                    for name in (
                        'Counted input',
                        'Usage input',
                        'Usage output',
                        'Request SHA256',
                        'Evidence',
                    )
                )
            ):
                raise ValueError('NOT_RUN has contradictory attempt evidence')
            pending.append(identity)
        elif not evidence(attempt['Evidence']):
            raise ValueError('An executed sample must retain evidence: ' + identity)
        budget_violation = False
        if chats == 1:
            if counts < 1 or attempt['Request SHA256'] not in hashes[identity]:
                raise ValueError('Actual request differs from frozen one-attempt input')
            counted = natural(attempt['Counted input'])
            if counted < 1:
                raise ValueError('Sent input requires an actual positive preflight count')
            budget_violation = counted > natural(field(manifest, 'Input-limit'))
            if counted + natural(field(manifest, 'Output-limit')) > natural(
                field(manifest, 'Total-limit')
            ):
                budget_violation = True
            for name in ('Usage input', 'Usage output'):
                if attempt[name] != 'UNKNOWN':
                    actual = natural(attempt[name])
                    limit = natural(
                        field(manifest, 'Output-limit' if name == 'Usage output' else 'Input-limit')
                    )
                    if actual > limit or name == 'Usage input' and actual > counted:
                        budget_violation = True
        if status != 'NOT_RUN' and (
            (status == 'PREFLIGHT_REJECTED' and chats != 0)
            or (
                status in ('TRANSPORT_ERROR', 'STRUCTURED_REJECTED', 'LIVE_RETURNED') and chats != 1
            )
        ):
            raise ValueError('Attempt status contradicts sent Chat count')
        pair = [left[identity], right[identity]]
        for row in pair:
            if any(
                row[name] not in ('PASS', 'FAIL', 'PENDING')
                for name in ('Rights', 'Protocol', 'Critical', 'Usable')
            ):
                raise ValueError('Human verdict must be PASS, FAIL or PENDING')
            allowed = (
                ('DISCUSS', 'REUSE', 'NEW', 'PENDING') if sample.task == 'discuss' else ('NA',)
            )
            if row['Decision'] not in allowed:
                raise ValueError('Invalid human decision label')
            if any(row[name] != 'PENDING' for name in ('Rights', 'Protocol', 'Critical', 'Usable')):
                if not evidence(row['Reason']) or not evidence(row['Evidence']):
                    raise ValueError('Human conclusions require reason and evidence')
        critical = (
            status == 'LIVE_RETURNED'
            and not budget_violation
            and all(
                row[name] == 'PASS' for row in pair for name in ('Rights', 'Protocol', 'Critical')
            )
        )
        if not critical:
            critical_failures.append(identity)
        agreed = all(row['Usable'] == 'PASS' for row in pair)
        if sample.task == 'discuss':
            agreed = (
                agreed
                and pair[0]['Decision'] == pair[1]['Decision']
                and pair[0]['Decision'] != 'PENDING'
            )
            if sample.related_branch and pair[0]['Decision'] != 'REUSE':
                critical = False
                if identity not in critical_failures:
                    critical_failures.append(identity)
            if sample.input_no == 1 and pair[0]['Decision'] != 'DISCUSS':
                agreed = False
        if critical and agreed:
            usable[sample.task] += 1
        else:
            failed.append(identity)
    passed = not critical_failures and all(usable[task] >= 10 for task, _, _ in TASKS)
    return {
        'passed': passed,
        'reviewers': tuple(reviewers),
        'usable': dict(usable),
        'critical_failures': tuple(critical_failures),
        'not_run': tuple(pending),
        'failed': tuple(failed),
        'denominator': 60,
    }


def summary(result, manifest, attempts, left, right):
    lines = [
        '# V2.1 EV60人工评价汇总',
        '',
        '结果：' + ('CRITERIA_MET' if result['passed'] else 'NOT_PASSED') + '；固定分母60。',
        'Manifest-SHA256: ' + digest(manifest),
        'Attempts-SHA256: ' + digest(attempts),
        'Review-A-SHA256: ' + digest(left),
        'Review-B-SHA256: ' + digest(right),
        '',
        '评审者：'
        + ' / '.join(result['reviewers'])
        + '。实际独立评价由发布负责人核实；工具只校对显式记录。'
        '关键项未全通过或任一任务不足10/12均不通过；人工分歧按未通过。',
        '',
        '| 任务 | 双人一致可用 | 分母 |',
        '| --- | ---: | ---: |',
    ]
    lines.extend(f'| {title} | {result["usable"].get(task, 0)} | 12 |' for task, title, _ in TASKS)
    lines += [
        '',
        f'未执行：{len(result["not_run"])}；关键项未通过：{len(result["critical_failures"])}。',
        '未通过样本：' + (', '.join(result['failed']) or '无') + '。',
        '',
        '这是一份证据登记汇总，不调用模型、不验证评审者真实身份、不修改OFFLINE_READY/LIVE准入。'
        '供应方协议/预算/计数真伪及实际运行证据仍由既有发布准入流程核实。',
        '',
    ]
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--template', choices=('attempts', 'review'))
    parser.add_argument('--attempts', type=Path)
    parser.add_argument('--review-a', type=Path)
    parser.add_argument('--review-b', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    manifest = args.manifest.read_text(encoding='utf-8')
    if args.template:
        if args.attempts or args.review_a or args.review_b:
            parser.error('Template mode does not accept existing evaluations')
        content = template(manifest, args.template)
        code = 0
    else:
        if not all((args.attempts, args.review_a, args.review_b)):
            parser.error('Aggregation needs attempts and two independent reviews')
        attempts, left, right = (
            path.read_text(encoding='utf-8')
            for path in (args.attempts, args.review_a, args.review_b)
        )
        result = aggregate(manifest, attempts, left, right)
        content = summary(result, manifest, attempts, left, right)
        code = 0 if result['passed'] else 1
    new_markdown(args.output, content)
    print('Markdown saved; provider_calls=0; resource admission unchanged')
    return code


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        print('Evaluation evidence rejected: ' + str(error), file=sys.stderr)
        raise SystemExit(2) from None
