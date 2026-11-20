"""Bounded EV60 execution through normal C01/C07, never a user service.

Default CLI mode only checks immutable metadata. --execute requires the exact
current grant, a new durable slot and all frozen candidates reconstructed before
credentials or I/O. A claimed slot cannot resume or refund an uncertain request.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path

from formation_evaluation import (
    DESIGN,
    DESIGN_SHA256,
    VARIANTS,
    digest,
    manifest_rows,
    new_markdown,
    recipe_digest,
    row_for,
    stable,
    transport_json,
)
from formation_evaluation_review import field, frozen_manifest, template
from formation_evaluation_spec import samples
from quality_gate import ROOT

MANIFEST = ROOT / 'docs/verification/v2.1/evaluation-inputs-default-2026-11-19-v6.md'
MANIFEST_SHA256 = '65c2e9133ee7d1cf2a6481673114a23838650cfbeb1e5e14e4b678113bb3eaba'
CHAT_LIMIT = 60
COUNT_LIMIT = 120
PER_CHAT_LIMIT = 139264
TOTAL_LIMIT = 8355840


def append(path, text):
    with Path(path).open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())


def runner_digest():
    paths = [
        Path(__file__),
        ROOT / 'tools/run-v21-evaluation.py',
        ROOT / 'tools/formation_evaluation_review.py',
    ]
    return digest(stable([(path.name, digest(path.read_bytes())) for path in paths]))


def verify_metadata():
    content = MANIFEST.read_text(encoding='utf-8')
    if digest(MANIFEST.read_bytes()) != MANIFEST_SHA256:
        raise ValueError('Current default manifest bytes changed')
    frozen_manifest(content)
    if (
        field(content, 'Recipe-SHA256') != recipe_digest()
        or field(content, 'Design-SHA256') != digest(DESIGN.read_bytes())
        or digest(DESIGN.read_bytes()) != DESIGN_SHA256
        or field(content, 'Profile') != 'deepseek-v2'
        or field(content, 'Candidates') != '120'
    ):
        raise ValueError('Current frozen design or recipe changed')
    return content


class Allowance:
    """Claim each paid attempt durably before delegating; never refund."""

    def __init__(
        self,
        profile,
        event,
        guard,
        *,
        chat_limit=CHAT_LIMIT,
        count_limit=COUNT_LIMIT,
        token_limit=TOTAL_LIMIT,
    ):
        if (chat_limit, count_limit, token_limit) not in (
            (1, 2, PER_CHAT_LIMIT),
            (CHAT_LIMIT, COUNT_LIMIT, TOTAL_LIMIT),
        ) or any(type(value) is not int for value in (chat_limit, count_limit, token_limit)):
            raise ValueError('Exact observation or EV60 allowance required')
        self.chat_limit = chat_limit
        self.count_limit = count_limit
        self.token_limit = token_limit
        self.profile = profile.snapshot
        self.event = event
        self.guard = guard
        self.counts = 0
        self.chats = 0
        self.reserved_tokens = 0
        self.stopped = False

    def check(self, profile):
        try:
            self.guard()
        except BaseException:
            self.stopped = True
            raise
        if self.stopped or profile.snapshot != self.profile:
            raise ValueError('EV stopped or Profile changed')

    def observe_outcome(self, result_code, data):
        # A known invalid output already prevents whole-cohort acceptance.
        # Keep remaining rows NOT_RUN rather than spending on a failed batch.
        if (
            result_code != 'AI_FINISHED'
            or data['status'] != 'LIVE_RETURNED'
            or not data['protected']
        ):
            self.stopped = True

    def case(self, sample, expected, facts):
        return CaseAllowance(self, sample, expected, facts)


class CaseAllowance:
    def __init__(self, owner, sample, expected, facts):
        self.owner = owner
        self.sample = sample
        self.expected = expected
        self.facts = facts
        self.count_calls = self.chat_calls = 0
        self.last_texts = None
        self.request_hash = None

    def counter(self, delegate):
        case = self
        owner = self.owner

        class Counter:
            async def count(self, profile, texts):
                owner.check(profile)
                if (
                    case.count_calls >= len(case.expected)
                    or owner.counts >= owner.count_limit
                    or len(texts) != 8
                ):
                    raise ValueError('EV count allowance exhausted')
                row = case.expected[case.count_calls]
                # The full eight-text digest binds first-text system + SDK schema;
                # row[5] separately identifies the unchanged actual system message.
                if (
                    digest(texts[1]) != row[6]
                    or digest(stable([digest(text) for text in texts])) != row[8]
                ):
                    raise ValueError('EV candidate changed or reordered')
                from backend.app.infrastructure.tokenization import check_text_capacity

                check_text_capacity(profile, texts)
                owner.event(case.sample.sample_id, 'COUNT_INTENT', row[9])
                case.count_calls += 1
                owner.counts += 1
                case.last_texts = None
                try:
                    receipt = await delegate.count(profile, texts)
                except BaseException:
                    owner.stopped = True
                    owner.event(case.sample.sample_id, 'COUNT_UNCERTAIN_OR_FAILED', row[9])
                    raise
                case.last_texts = texts
                owner.event(case.sample.sample_id, 'COUNT_RETURNED', row[9])
                return receipt

        return Counter()

    def gateway(self, delegate):
        case = self
        owner = self.owner

        class Gateway:
            async def send(self, profile, context):
                owner.check(profile)
                if (
                    case.chat_calls != 0
                    or owner.chats >= owner.chat_limit
                    or owner.reserved_tokens + PER_CHAT_LIMIT > owner.token_limit
                    or case.last_texts is None
                    or context.texts != case.last_texts
                ):
                    raise ValueError('EV Chat allowance exhausted or count missing')
                row = case.expected[case.count_calls - 1]
                if row_for(case.sample, row[1], context, case.facts, profile) != row:
                    raise ValueError('EV final request or private basis changed')
                request_hash = digest(transport_json(profile.request(context)))
                owner.event(case.sample.sample_id, 'CHAT_INTENT', request_hash)
                case.chat_calls += 1
                owner.chats += 1
                owner.reserved_tokens += PER_CHAT_LIMIT
                case.request_hash = request_hash
                try:
                    response = await delegate.send(profile, context)
                except BaseException:
                    owner.stopped = True
                    owner.event(case.sample.sample_id, 'CHAT_UNCERTAIN', request_hash)
                    raise
                from backend.app.infrastructure.practical_usage import (
                    validate_collaboration_usage,
                )

                try:
                    if response.succeeded is not True:
                        raise ValueError('Transport did not succeed')
                    validate_collaboration_usage(
                        response.raw_response,
                        profile=profile,
                        context=context,
                        catalog=case.catalog,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                    )
                except Exception:
                    # Return to C07 so its ordinary audit records the response.
                    # Stop before any subsequent sample, even if C07 returns.
                    owner.stopped = True
                owner.event(
                    case.sample.sample_id,
                    'CHAT_RETURNED_STOPPED' if owner.stopped else 'CHAT_RETURNED',
                    request_hash,
                )
                return response

        return Gateway()


def prepare_all(output, catalog, profile, content, event):
    from formation_evaluation_fixture import prepare_sample

    from backend.app.guide.collaboration_context import compile_context
    from backend.app.infrastructure.tokenization import check_text_capacity

    actual = []
    cases = []
    for sample in samples():
        directory = output / sample.sample_id
        directory.mkdir(exist_ok=False)
        original, facts = prepare_sample(directory, catalog, sample)
        expected = []
        seen = set()
        for index, (history, background) in enumerate(VARIANTS):
            context = (
                original
                if index == 0
                else compile_context(
                    original.canonical, catalog, omit_history=history, omit_background=background
                )
            )
            wire_hash = digest(context.input_json)
            if wire_hash in seen:
                continue
            seen.add(wire_hash)
            check_text_capacity(profile, context.texts)
            row = row_for(
                sample, ('full', 'no-history', 'required')[index], context, facts, profile
            )
            actual.append(row)
            expected.append(row)
        cases.append((sample, directory / 'input.sqlite', expected, facts))
        event(sample.sample_id, 'PREPARED', expected[0][9])
        print(sample.sample_id + ' preflight; provider_calls=0', flush=True)
    if tuple(actual) != manifest_rows(content):
        raise ValueError('Complete EV60 reconstruction differs from frozen inputs')
    return cases


def protected_facts(database):
    with database.transaction() as connection:
        document = tuple(
            connection.execute(
                'SELECT content_version,markdown_content,block_state_json FROM requirement_documents WHERE id=42'
            ).fetchone()
        )
        revisions = [
            tuple(row) for row in connection.execute('SELECT * FROM revisions ORDER BY id')
        ]
        # Model may associate or assess, but cannot end/reopen a user step.
        states = [
            tuple(row)
            for row in connection.execute(
                'SELECT step_ref,status FROM formation_steps ORDER BY step_ref'
            )
        ]
        closures = [
            tuple(row)
            for row in connection.execute('SELECT * FROM formation_closures ORDER BY rowid')
        ]
    return digest(stable((document, revisions, states, closures)))


def outcome(database, case):
    with database.transaction() as connection:
        run = dict(connection.execute('SELECT * FROM guide_runs WHERE id=1').fetchone())
        row = connection.execute('SELECT * FROM llm_uses ORDER BY id DESC LIMIT 1').fetchone()
    row = None if row is None else dict(row)
    result = json.loads(run['final_result_json']) if run['final_result_json'] else {}
    status = 'PREFLIGHT_REJECTED'
    counted = '—'
    incoming = outgoing = 'UNKNOWN' if case.chat_calls else '—'
    if row is not None:
        snapshot = json.loads(row['request_snapshot_json'])
        counted = str(snapshot.get('counting', {}).get('input_tokens_candidate', 'UNKNOWN'))
        incoming = str(row['input_tokens']) if type(row['input_tokens']) is int else 'UNKNOWN'
        outgoing = str(row['output_tokens']) if type(row['output_tokens']) is int else 'UNKNOWN'
        status = (
            'TRANSPORT_ERROR'
            if row['call_status'] != 'SUCCEEDED'
            else 'LIVE_RETURNED'
            if row['validation_status'] == 'SUCCEEDED'
            else 'STRUCTURED_REJECTED'
        )
    return {
        'sample': case.sample.sample_id,
        'status': status,
        'chat': str(case.chat_calls),
        'count': str(case.count_calls),
        'counted': counted,
        'incoming': incoming,
        'outgoing': outgoing,
        'request': case.request_hash or '—',
        'row': row,
        'run': run,
        'result': result,
    }


def cell(value):
    return str(value).replace('|', '\\|').replace('\r', '').replace('\n', '<br>')


def summaries(report, data, profile):
    row = data['row']
    append(
        report,
        '\n### '
        + data['sample']
        + '\n\n'
        + '程序结果：'
        + data['status']
        + '；Run状态：'
        + data['run']['status']
        + '；请求次数：'
        + data['chat']
        + '；计数批次：'
        + data['count']
        + '；输入/输出Token：'
        + data['incoming']
        + '/'
        + data['outgoing']
        + '；发送前输入（含预留）：'
        + data['counted']
        + '。\n\n',
    )
    append(
        report,
        '正文/Revision/步骤生命周期/原Closure保护：'
        + ('PASS' if data['protected'] else 'FAIL')
        + '。\n\n',
    )
    if row is None:
        append(report, '没有模型调用审计；不声明模型成功。\n')
        return
    append(
        report,
        '正常证据：'
        + str(Path(data['database']).relative_to(ROOT))
        + '，Run1／LLMUse'
        + str(row['id'])
        + '。\n\n',
    )
    append(
        report,
        '解析/校验：'
        + str(row['parse_status'])
        + '/'
        + str(row['validation_status'])
        + '；finish_reason：'
        + cell(row['finish_reason'])
        + '。\n\n',
    )
    raw = json.loads(row['raw_response_json']) if row['raw_response_json'] else None
    try:
        body = json.loads(raw['choices'][0]['message']['content'])
    except (ValueError, TypeError, KeyError, IndexError):
        append(report, '模型内容无法作为严格对象读取；原结果保留在正常审计。\n')
        return
    # Derived Markdown facts, never paste a raw JSON response or API credential.
    lines = ['| 模型输出字段 | 值 |', '| --- | --- |']

    def visit(value, name):
        if len(lines) >= 302:
            return
        if type(value) is dict:
            for key, item in value.items():
                visit(item, name + '.' + key if name else key)
        elif type(value) is list:
            if not value:
                lines.append('| ' + cell(name) + ' | 空列表 |')
            for index, item in enumerate(value):
                visit(item, name + '[' + str(index) + ']')
        else:
            text = 'null' if value is None else str(value)
            text = text.replace(profile.api_key, '[REDACTED]')
            if len(text) > 1800:
                text = text[:1800] + '〔截断；完整内容见正常审计〕'
            lines.append('| ' + cell(name) + ' | ' + cell(text) + ' |')

    visit(body, '')
    if len(lines) >= 302:
        lines.append('| 摘要 | 字段超限，完整内容见正常审计 |')
    append(report, '\n'.join(lines) + '\n')


def attempt_markdown(content, results, report):
    text = template(content, 'attempts')
    text = text.replace(
        '状态：NOT_RUN。本表没有真实调用或人工评价结果。',
        '状态：已登记本次实际尝试；未运行及失败仍计入60分母。人工评价尚未执行。',
        1,
    )
    for item in results:
        original = (
            '| ' + ' | '.join((item['sample'], 'NOT_RUN', '0', '0', '—', '—', '—', '—', '—')) + ' |'
        )
        values = [
            item['sample'],
            item['status'],
            item['chat'],
            item['count'],
            item['counted'],
            item['incoming'],
            item['outgoing'],
            item['request'],
            '[' + report.name + '](' + report.name + ')',
        ]
        if original not in text:
            raise ValueError('Attempt template changed')
        text = text.replace(original, '| ' + ' | '.join(values) + ' |', 1)
    return text


def execute(args, *, profile=None, gateway=None, counter=None, selection=None):
    from backend.app.guide.orchestrator import execute_guide_run
    from backend.app.infrastructure.collaboration_admission import CollaborationAdmission
    from backend.app.infrastructure.collaboration_observation import CollaborationObservation
    from backend.app.infrastructure.formation_database import FormationDatabase
    from backend.app.infrastructure.formation_schema_release import load_release
    from backend.app.infrastructure.local_credentials import read_local_credential
    from backend.app.infrastructure.model_gateway import ModelGateway
    from backend.app.infrastructure.model_profile import ModelProfile
    from backend.app.infrastructure.process_lock import ProcessLock
    from backend.app.infrastructure.resources import ResourceCatalog
    from backend.app.infrastructure.tokenization import TokenizationGateway
    from backend.app.shared.command_execution import operation_time

    if (
        (args.allow_chat_calls, args.allow_count_batches, args.max_total_tokens)
        not in ((1, 2, PER_CHAT_LIMIT), (CHAT_LIMIT, COUNT_LIMIT, TOTAL_LIMIT))
        or type(args.allow_chat_calls) is not int
        or type(args.allow_count_batches) is not int
        or type(args.max_total_tokens) is not int
    ):
        raise ValueError('Exact current explicit observation or EV60 grant required')
    content = verify_metadata()
    catalog = ResourceCatalog().for_formation_profile('deepseek-v2')
    offline = ModelProfile('ev21-preflight-placeholder-never-sent', 'deepseek-v2')
    if (
        field(content, 'Release-SHA256') != catalog.collaboration.release_sha256
        or field(content, 'Profile-SHA256') != digest(transport_json(offline.snapshot))
        or catalog.collaboration.counting['total_limit'] != PER_CHAT_LIMIT
    ):
        raise ValueError('Frozen default release or budget differs')
    output, report = args.output_dir, args.report
    if (
        not output.is_absolute()
        or output.parent.resolve() != (ROOT / 'data').resolve()
        or output.exists()
        or output.is_symlink()
        or not report.is_absolute()
        or report.parent.resolve() != (ROOT / 'docs/verification/v2.1').resolve()
        or report.suffix != '.md'
        or report.exists()
    ):
        raise ValueError('A new explicit isolated data slot and verification Markdown are required')
    outputs = [
        report,
        report.with_name(report.stem + '-attempts.md'),
        report.with_name(report.stem + '-reviewer-a.md'),
        report.with_name(report.stem + '-reviewer-b.md'),
    ]
    if any(path.exists() or path.is_symlink() for path in outputs):
        raise ValueError('Execution evidence output already exists')
    source_digest = runner_digest()
    recipe = recipe_digest()

    def guard():
        if (
            runner_digest() != source_digest
            or recipe_digest() != recipe
            or digest(MANIFEST.read_bytes()) != MANIFEST_SHA256
        ):
            raise ValueError('EV execution sources changed; stop without replay')

    def event(sample, phase, request_hash):
        append(report, '\n- ' + sample + ' ' + phase + ' ' + request_hash + '\n')

    output.mkdir(exist_ok=False)
    new_markdown(
        report,
        '# V2.1默认模型真实准入执行\n\n'
        + 'Run-slot: '
        + str(output.relative_to(ROOT))
        + '\n'
        + 'Manifest-SHA256: '
        + MANIFEST_SHA256
        + '\n'
        + 'Runner-SHA256: '
        + source_digest
        + '\n'
        + 'Recipe-SHA256: '
        + recipe
        + '\n\n'
        + '当前授权：'
        + str(args.allow_chat_calls)
        + ' Chat/'
        + str(args.allow_count_batches)
        + '必要八项计数批次，Chat合计最多'
        + str(args.max_total_tokens)
        + ' Token；'
        + '每次输入131072/输出8192/总139264。0自动重试；结果未知或首个明确拒绝立即停止，不退款补发。'
        + '正常隔离数据库/计数审计保留以核对不确定结果；不使用正常用户库或用户服务，'
        + '不改变全局release准入，不代填两名人工评价。\n',
    )
    results = []
    budget = Allowance(
        offline,
        event,
        guard,
        chat_limit=args.allow_chat_calls,
        count_limit=args.allow_count_batches,
        token_limit=args.max_total_tokens,
    )
    try:
        cases = prepare_all(output, catalog, offline, content, event)
        guard()
        actual_profile = profile
        if actual_profile is None:
            actual_profile = ModelProfile(
                read_local_credential(args.credential_file), 'deepseek-v2'
            )
        if actual_profile.snapshot != offline.snapshot:
            raise ValueError('Actual credential Profile differs from frozen input')
        source = None
        for sample, path, expected, facts in cases:
            if budget.chats >= budget.chat_limit:
                break
            if selection is not None and sample.sample_id not in selection:
                break  # private offline tests only; CLI never supplies selection
            case = budget.case(sample, expected, facts)
            case.catalog = catalog
            database = FormationDatabase(path, formation_release=load_release())
            with ProcessLock.for_database(database.path) as lock:
                before = protected_facts(database)
                admission = CollaborationAdmission(database, lock, catalog)
                observation = None
                if source is None:
                    observation = CollaborationObservation(
                        database,
                        1,
                        catalog,
                        actual_profile,
                        count_batches=len(expected),
                        chat_calls=1,
                        total_tokens=PER_CHAT_LIMIT,
                    )
                else:
                    admission.approve_saved_call(source, 1, operation_time(None))
                result = asyncio.run(
                    execute_guide_run(
                        database,
                        {'guide_run_id': 1},
                        process_lock=lock,
                        catalog=catalog,
                        profile=actual_profile,
                        gateway=case.gateway(ModelGateway() if gateway is None else gateway),
                        counting_counter=case.counter(
                            TokenizationGateway() if counter is None else counter
                        ),
                        observation=observation,
                    )
                )
                data = outcome(database, case)
                data.update(database=path, protected=before == protected_facts(database))
                results.append(data)
                summaries(report, data, actual_profile)
                budget.observe_outcome(result['code'], data)
                if source is None:
                    if (
                        data['status'] != 'LIVE_RETURNED'
                        or budget.stopped
                        or result['code'] != 'AI_FINISHED'
                    ):
                        budget.stopped = True
                    else:
                        admission.approve_saved_call(database.path, 1, operation_time(None))
                        source = database.path
                if source is not None:
                    proof = admission.current(actual_profile.snapshot)
                    catalog.collaboration.require_live(actual_profile.snapshot, admission=proof)
            print(
                sample.sample_id
                + ' '
                + data['status']
                + '; chats='
                + str(budget.chats)
                + '; counts='
                + str(budget.counts),
                flush=True,
            )
            if budget.stopped:
                break
    except BaseException as error:
        budget.stopped = True
        # Only the exception class is safe for the public Markdown/console.
        append(
            report,
            '\n执行已停止：'
            + type(error).__name__
            + '。未自动重试；'
            + '请先核对已认领槽、正常调用/计数审计，不能重新运行该目录。\n',
        )
        raise
    finally:
        new_markdown(outputs[1], attempt_markdown(content, results, report))
        new_markdown(outputs[2], template(content, 'review'))
        new_markdown(outputs[3], template(content, 'review'))
        append(
            report,
            '\n## 执行汇总\n\n'
            + '登记样本：'
            + str(len(results))
            + '/60；Chat尝试：'
            + str(budget.chats)
            + '/'
            + str(budget.chat_limit)
            + '；计数批次：'
            + str(budget.counts)
            + '/'
            + str(budget.count_limit)
            + '；Chat预算已占用：'
            + str(budget.reserved_tokens)
            + '/'
            + str(budget.token_limit)
            + ' Token。\n\n'
            + '状态：'
            + (
                'STOPPED'
                if budget.stopped
                else 'OBSERVATION_FINISHED'
                if budget.chat_limit == 1
                else 'EXECUTION_FINISHED'
            )
            + '；人工评价PENDING；正式AI尚未启用。\n',
        )
    return 1 if budget.stopped else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--credential-file', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--allow-chat-calls', type=int)
    parser.add_argument('--allow-count-batches', type=int)
    parser.add_argument('--max-total-tokens', type=int)
    args = parser.parse_args(argv)
    supplied = (
        args.credential_file,
        args.output_dir,
        args.report,
        args.allow_chat_calls,
        args.allow_count_batches,
        args.max_total_tokens,
    )
    if not args.execute:
        if any(item is not None for item in supplied):
            parser.error('Execution inputs require --execute')
        verify_metadata()
        print('DEFAULT_EV60_METADATA_MATCH; credentials_read=0; provider_calls=0')
        return 0
    if any(item is None for item in supplied) or not args.credential_file.is_absolute():
        parser.error('Explicit absolute credential/data/report paths and all allowances required')
    from backend.app.infrastructure.sqlite_runtime import activate

    activate()
    return execute(args)
