"""Freeze reproducible EV60 Canonical/Wire candidates offline, retaining Markdown only."""

import argparse
import json
import os
import re
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory, mkstemp

from formation_evaluation_spec import FIXED_TIME, FIXTURE_VERSION, TASKS, samples
from quality_gate import ROOT, environment

DESIGN = ROOT / 'docs/iterations/pending/v2.1/WALL-E.后端设计文档_V_2.1.md'
DESIGN_SHA256 = '4049f8d3b5d01bd704dd0439b8c0730155cec813f3f5ef8ef7ad8c5ba5b5b197'
HEADERS = (
    'Sample',
    'Variant',
    'V',
    'Revision',
    'Canonical SHA256',
    'System SHA256',
    'Wire SHA256',
    'Output SHA256',
    'Eight texts SHA256',
    'Request SHA256',
    'UTF8 bytes',
    'Coverage SHA256',
)
VARIANTS = ((False, False), (True, False), (True, True))


def digest(value):
    return sha256(value if isinstance(value, bytes) else value.encode('utf-8')).hexdigest()


def stable(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def transport_json(value):
    # Match ModelGateway.send HTTP UTF-8 bytes and the release Profile digest.
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def input_sources():
    paths = set((ROOT / 'backend/app').rglob('*.py'))
    paths.update(path for path in (ROOT / 'backend/resources').rglob('*') if path.is_file())
    paths.update(
        path
        for path in (ROOT / 'backend/app').rglob('*')
        if path.is_file() and path.suffix in ('.json', '.sql', '.md', '.txt')
    )
    paths.update(
        ROOT / 'tools' / name
        for name in (
            'formation_evaluation_spec.py',
            'formation_evaluation_fixture.py',
            'formation_evaluation.py',
            'prepare-v21-evaluation.py',
            'build-formation-resources.py',
        )
    )
    return tuple(sorted(paths))


def recipe_digest():
    hashes = [
        (path.relative_to(ROOT).as_posix(), digest(path.read_bytes())) for path in input_sources()
    ]
    return digest(stable(hashes))


def row_for(sample, variant, context, facts, profile):
    basis = context.basis
    texts = [digest(text) for text in context.texts]
    return (
        sample.sample_id,
        variant,
        str(facts['content_version']),
        str(facts['revision_id']),
        basis['canonical_sha256'],
        digest(context.system),
        digest(context.input_json),
        basis['output_schema_sha256'],
        digest(stable(texts)),
        digest(transport_json(profile.request(context))),
        str(len(context.input_json.encode('utf-8'))),
        digest(stable(context.input['project_position']['formation']['coverage'])),
    )


def collect(catalog, profile, selection, temporary):
    from formation_evaluation_fixture import prepare_sample

    from backend.app.guide.collaboration_context import compile_context
    from backend.app.infrastructure.tokenization import check_text_capacity

    rows, details = [], []
    for sample in selection:
        with TemporaryDirectory(prefix=sample.sample_id + '-', dir=temporary) as directory:
            original, facts = prepare_sample(directory, catalog, sample)
            seen = set()
            for index, (history, background) in enumerate(VARIANTS):
                context = (
                    original
                    if index == 0
                    else compile_context(
                        original.canonical,
                        catalog,
                        omit_history=history,
                        omit_background=background,
                    )
                )
                wire_hash = digest(context.input_json)
                if wire_hash in seen:
                    continue
                seen.add(wire_hash)
                text_bytes = check_text_capacity(profile, context.texts)
                if len(context.texts) != 8:
                    raise RuntimeError('EV must bind the eight actual count texts')
                if any(
                    field in context.input_json
                    for field in ('protected_semantic_digest', 'publication_binding', 'api_key')
                ):
                    raise RuntimeError('Private authority leaked into EV Wire')
                if context.input['current_request']['content'] != sample.instruction:
                    raise RuntimeError('EV instruction changed during projection')
                variant = ('full', 'no-history', 'required')[index]
                rows.append(row_for(sample, variant, context, facts, profile))
                details.append(
                    (
                        sample.sample_id,
                        variant,
                        tuple(digest(text) for text in context.texts),
                        stable(context.input['project_position']['formation']['coverage']),
                        text_bytes,
                    )
                )
        print(sample.sample_id + ' prepared; provider_calls=0', flush=True)
    return tuple(rows), tuple(details)


def manifest_rows(content):
    rows = []
    for line in content.splitlines():
        if line.startswith('| EV21-'):
            values = tuple(value.strip() for value in line.strip('|').split('|'))
            if len(values) != len(HEADERS):
                raise ValueError('EV manifest row has an invalid shape')
            rows.append(values)
    if not rows or len({(row[0], row[1]) for row in rows}) != len(rows):
        raise ValueError('EV manifest rows missing or duplicated')
    return tuple(rows)


def new_markdown(path, content):
    path = Path(path).resolve()
    if (
        path.parent != (ROOT / 'docs/verification/v2.1').resolve()
        or path.suffix != '.md'
        or path.exists()
    ):
        raise ValueError('Use a new Markdown directly under docs/verification/v2.1')
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content.encode('utf-8'))
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            raise FileExistsError(path)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def render(rows, details, catalog, profile, before, complete):
    cohort_hash = digest(stable(rows))
    lines = [
        '# V2.1 EV60离线输入冻结清单',
        '',
        '状态：INPUTS_FROZEN（仅完整60样本时）；实际模型效果NOT_RUN。'
        if complete
        else '状态：PARTIAL_INPUT_CHECK；未形成60样本冻结。',
        f'Fixture: {FIXTURE_VERSION}',
        f'Recipe-SHA256: {before}',
        f'Cohort-SHA256: {cohort_hash}',
        f'Design-SHA256: {DESIGN_SHA256}',
        f'Profile: {profile.profile_id}',
        f'Profile-SHA256: {digest(transport_json(profile.snapshot))}',
        f'Release-SHA256: {catalog.collaboration.release_sha256}',
        f'Frozen-time: {FIXED_TIME}',
        f'Samples: {len(set(row[0] for row in rows))}',
        f'Candidates: {len(rows)}',
        f'Input-limit: {catalog.collaboration.counting["input_limit"]}',
        f'Output-limit: {catalog.collaboration.counting["output_limit"]}',
        f'Total-limit: {catalog.collaboration.counting["total_limit"]}',
        '',
        '## 范围与重建',
        '',
        '本清单冻结实际C01接受后Canonical、确定编译的system/Wire、严格Output及固定Profile请求体摘要。'
        '完整输入由仓库固定配方、声明种子及下列指令重建，以全部候选字节摘要复核；不保存原始JSON或数据库。'
        'Request SHA为ModelGateway实际HTTP content序列（保留字段顺序），Profile SHA沿生产release规则；'
        '只对集合/配方等管理摘要采用排序JSON，二者不混用。'
        '计数选材沿生产full→no-history→required并按Wire去重；最终发送候选只能由获授权真实八项计数确定。'
        '本次没有Tokenization/Chat、没有计数模拟结果、没有LIVE准入、没有用户库/服务变更。',
        '',
        '命令：.venv/Scripts/python.exe -B tools/prepare-v21-evaluation.py --manifest <新Markdown>；'
        '复核：同入口 --verify <本清单>。复核必须重建全部行；样本/Profile/release/源码/指令变化即拒绝，不能只比较样本数量。',
        '',
        '隔离数据：需求7/文档42；空白V1/Revision101；FBASE两中文块V4/Revision401、IDs12/13；'
        'Goal1、D30/F12、s1 COMPLETED/s2 IN_PROGRESS/s3 PLANNED、s2.o1 CONTENT/s2.o2 ANALYSIS。'
        '输入3具有同问题OPEN b4(origin s1/return s2)及i1，其他输入i1为推荐异常问题且无该支线。'
        'i2为s2暂缓的跨设备同步，实际用户来源m1明示该决定；实体未选入时仍如实记录coverage缺失，不能冒充已读定义。'
        '非空a1关联block12；空白无伪造成果。输入6与全部关联复核任务走真实人工编辑：空白V2、非空V5；'
        '其余样本保持原正文。关联复核奇数输入及充分性输入6先走真实用户COMPLETE_STEP，'
        '共8样本在已结束s2上改稿/讨论；原Closure摘要与COMPLETED状态在C01后复核保持。',
        '',
        '这些是8.3评测所需的FBASE正文/路径派生夹具，并非8.1所有共享验收完整FBASE。'
        '历史状态/关系由明确SQL种子创建；正文创建/三次编辑、改稿、Artifact校验和C01采用生产入口。'
        '没有编造m210/m211既有提案，没有伪称历史AI调用或用户结束已发生；设置过程的成功幂等回执依法保留，评测新key尚未使用。',
        '',
        '## SDK输出结构约束',
        '',
        '新release的DISCUSS通过response_format.json_schema/strict绑定供应方语法投影；区块枚举仅取本轮Wire的当前目标Revision，空文档不关联内容。'
        '完整本地Schema/来源/权限/事务校验不变；不支持的模式/长度/范围/条件仍由程序严格校验，投影中的oneOf按语法联合anyOf处理，避免去除互斥模式后变成不可满足。'
        'Request SHA256包含完整实际SDK字段，Output SHA256仍指本地权威Schema。旧release请求体保持原格式。',
        '',
        '新计数资源system_text=system_plus_output_schema_v1：第1项为实际system、一个换行及SDK response_format.json_schema.schema的compact JSON；没有SDK Schema时仅system，其余7项不变。v33实测额外序列化开销1641，新候选framing_reserve=2048；输入/输出/总硬上限不变，文本可用空间更小。该候选仍须新单次兼容证明，不是所有Schema的统一上界；失败继续停止，不降级或补发。',
        '',
        '## 固定Profile（不含凭据）',
        '',
        '| 参数 | 冻结值 |',
        '| --- | --- |',
    ]
    for name, value in profile.snapshot.items():
        lines.append('| ' + name + ' | ' + str(value).replace('|', '／') + ' |')
    lines += ['', '## 五项任务与人工判据', '']
    for task, title, directive in TASKS:
        exemplar = next(sample for sample in samples() if sample.task == task)
        lines += [f'### {task}：{title}', '', directive, '', exemplar.criteria, '']
    lines += ['## 完整本轮指令（12输入基元×5任务）', '']
    for sample in samples():
        lines += ['### ' + sample.sample_id, '', sample.instruction, '']
    lines += [
        '## 实际输入摘要',
        '',
        '| ' + ' | '.join(HEADERS) + ' |',
        '| ' + ' | '.join('---' for _ in HEADERS) + ' |',
    ]
    lines.extend('| ' + ' | '.join(row) + ' |' for row in rows)
    lines += [
        '',
        '## 八项实际文本摘要与覆盖',
        '',
        '每个候选均通过原check_text_capacity纯字节上限检查；这不是Token测量或准入通过。八项依次为按冻结system_text定义的系统规则及SDK输出Schema合计、Wire、current_request、structure、documents、recent_history、'
        'goal_and_decisions、project_position/current_topic。覆盖仅为结构摘要，实际值由固定配方重建。',
        '',
    ]
    for identity, variant, texts, coverage, text_bytes in details:
        # Coverage is a small business summary, never a raw request/log dump.
        value = json.loads(coverage)
        omitted = (
            ','.join(
                f'{item["kind"]}:{item["count"]}:{item["reason"]}' for item in value['omitted']
            )
            or '无'
        )
        lines += [
            f'- {identity}/{variant}：八文本UTF8字节={text_bytes}；included={len(value["included"])}；omitted={omitted}；'
            '八项SHA256=' + ','.join(texts)
        ]
    lines += [
        '',
        '## 未执行与下一步',
        '',
        '真实60次Chat及必要计数需另获当轮总次数/预算/重试边界；每样本1次，无自动重试，'
        '失败及预算拒绝保留在60分母。两名独立人工尚未评价，不能将本清单当效果通过。'
        '更换Profile/release后重新冻结并完整重评。临时数据库/锁及原始内容已清理。',
        '',
    ]
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--list', action='store_true')
    action.add_argument('--manifest', type=Path)
    action.add_argument('--verify', type=Path)
    parser.add_argument('--sample', choices=[sample.sample_id for sample in samples()])
    parser.add_argument('--profile', choices=('deepseek-v2', 'deepseek-long-v3'))
    args = parser.parse_args(argv)
    if args.list:
        print('\n'.join(sample.sample_id for sample in samples()))
        return 0
    if args.verify and args.sample:
        parser.error('--verify always rebuilds the complete 60-sample set')
    if args.verify and (
        args.verify.resolve().parent != (ROOT / 'docs/verification/v2.1').resolve()
        or args.verify.suffix != '.md'
    ):
        parser.error('--verify requires a frozen verification Markdown')
    if digest(DESIGN.read_bytes()) != DESIGN_SHA256:
        parser.error('Design changed: review the affected EV inputs before refreezing')
    if args.manifest and (
        args.manifest.resolve().parent != (ROOT / 'docs/verification/v2.1').resolve()
        or args.manifest.suffix != '.md'
        or args.manifest.exists()
    ):
        parser.error('Use a new Markdown under docs/verification/v2.1')
    before = recipe_digest()
    expected = args.verify.read_text(encoding='utf-8') if args.verify else None
    if expected is not None and f'Recipe-SHA256: {before}\n' not in expected:
        parser.error('Recipe differs from the frozen manifest')
    profile_id = args.profile or 'deepseek-v2'
    if expected is not None:
        profiles = re.findall(r'^Profile: ([^\r\n]+)$', expected, re.MULTILINE)
        if len(profiles) != 1 or profiles[0] not in ('deepseek-v2', 'deepseek-long-v3'):
            parser.error('Frozen Profile is missing or unsupported')
        if args.profile and args.profile != profiles[0]:
            parser.error('Explicit Profile differs from the frozen manifest')
        profile_id = profiles[0]
    selection = tuple(
        sample for sample in samples() if not args.sample or args.sample == sample.sample_id
    )
    with TemporaryDirectory(prefix='walle-v21-ev60-') as directory:
        temporary = Path(directory)
        values = environment(temporary)
        os.environ.clear()
        os.environ.update(values)
        from quality_python import install_guards

        install_guards(ROOT, temporary)
        from backend.app.infrastructure.sqlite_runtime import activate

        activate()
        from backend.app.infrastructure.model_profile import ModelProfile
        from backend.app.infrastructure.resources import ResourceCatalog

        profile = ModelProfile('offline-placeholder-never-sent', profile_id)
        catalog = ResourceCatalog().for_formation_profile(profile.profile_id)
        if (
            digest(transport_json(profile.snapshot))
            != catalog.collaboration.release['model_profile_sha256']
        ):
            raise RuntimeError('EV Profile digest differs from the actual release')
        rows, details = collect(catalog, profile, selection, temporary)
        if recipe_digest() != before:
            raise RuntimeError('EV source changed during preparation')
        content = render(rows, details, catalog, profile, before, len(selection) == 60)
        if expected is not None:
            if manifest_rows(expected) != rows or expected != content:
                raise RuntimeError('Frozen EV input differs; do not reuse this evaluation baseline')
        temporary_path = temporary
    if temporary_path.exists():
        raise RuntimeError('EV temporary cleanup failed')
    if args.manifest:
        new_markdown(args.manifest, content)
    print(
        f'prepared={len(selection)}; candidates={len(rows)}; Tokenization=0; Chat=0; cleanup=True'
    )
    return 0
