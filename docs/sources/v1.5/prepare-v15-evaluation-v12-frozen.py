"""Prepare the formal 13 EV inputs in two domains, entirely offline.

Normal creation/manual-edit/discussion commands build fresh temporary databases.
No credentials, counter, gateway, service, admission bypass or retained database.
This is input preparation, not a model evaluator or an EV pass declaration.
"""
import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@dataclass(frozen=True)
class Domain:
    key: str
    title: str
    idea: str
    preference: str
    correction: str
    row_name: str
    old_rule: str
    new_rule: str


DOMAINS = (
    Domain('movie', '电影记录推荐', '记录、评分并推荐电影，优先解决看什么的问题',
        '我选择只推荐未观看的电影，评分用五星制；不做社交，不引入付费片源。',
        '纠正目标：最重要的是决定下一部看什么，记录只是形成偏好的手段；不要把目标改成片单统计。',
        '推荐候选', '候选允许包含已观看电影。', '候选只包含未观看电影。'),
    Domain('laboratory', '实验耗材补货', '记录实验耗材的入库与领用，优先解决库存不足的问题',
        '我选择按实验室独立维护库存，低于安全库存提示补货；不做自动采购，不混用不同实验室库存。',
        '纠正目标：最重要的是避免实验中途缺料，记录只是形成库存的手段；不要把目标改成采购财务统计。',
        '补货提醒', '只有库存为零才提示补货。', '低于安全库存就提示补货。'),
)
CASES = ('discuss-initial', 'discuss-long-preference', 'discuss-correction', 'discuss-decline',
    'document-generate', 'document-local-revise', 'document-long-specification',
    'proposals-table-row', 'proposals-user-edit', 'proposals-stale-original',
    'analysis-local-impact', 'analysis-old-new', 'analysis-required-over-budget')


def checked(result, code):
    if result['code'] != code:
        raise RuntimeError('Input preparation failed: expected '+code+', got '+str(result['code']))
    return result['data']


def prepare_case(database, lock, catalog, domain, case):
    """Return a real accepted run and fixed source facts, without dispatching it."""
    from backend.app.infrastructure.idempotency import Idempotency
    from backend.app.requirements.commands import create_requirement, update_discussion
    from backend.app.guide.commands import create_guide_run, cancel_guide_run
    from backend.app.documents.commands import (create_document, start_manual_draft,
        save_manual_draft, complete_manual_draft)
    from backend.app.documents.queries import get_current_document
    from backend.app.documents.snapshot import validate_snapshot, assign_identities, Provenance
    from backend.app.documents.markdown import parse_markdown
    from backend.app.documents.sources import DocumentSources
    from backend.app.guide.collaboration_context import read_canonical, compile_context
    executor = Idempotency(database, lock)
    checked(create_requirement(executor, {'title': domain.title, 'requirement_type': 'NEW',
        'initial_idea': domain.idea, 'idempotency_key': str(uuid4())}, catalog=catalog), 'CREATED')

    def version():
        with database.transaction() as connection:
            return connection.execute('SELECT discussion_version FROM requirements WHERE id=1').fetchone()[0]

    def accept(instruction, operation='DISCUSS', target=None, scope=None, refs=()):
        return checked(create_guide_run(executor, {'requirement_id': 1, 'expected_discussion_version': version(),
            'operation': operation, 'instruction': instruction, 'target': target, 'scope': scope,
            'source_refs': list(refs), 'proposal_ref': None, 'acknowledge_source_changes': False,
            'idempotency_key': str(uuid4())}, catalog=catalog), 'GUIDE_ACCEPTED')['guide_run_id']

    def pending(instruction):
        identity = accept(instruction)
        checked(cancel_guide_run(executor, {'guide_run_id': identity, 'idempotency_key': str(uuid4())}), 'GUIDE_CANCELLED')

    def edit(identity, markdown):
        current = checked(get_current_document(database, 1, identity, catalog=catalog), 'READ_OK')
        draft = checked(start_manual_draft(executor, {'requirement_id': 1, 'document_id': identity,
            'expected_version': current['content_version'], 'idempotency_key': str(uuid4())}, catalog=catalog), 'DRAFT_STARTED')['manual_draft']
        with database.transaction() as connection:
            sources = DocumentSources(connection, 1, catalog, document_id=identity)
            previous = validate_snapshot(draft['markdown_content'], draft['block_state_json'], sources)
            ids = list(range(previous.next_block_id, previous.next_block_id+len(parse_markdown(markdown).blocks)))
            snapshot = assign_identities(markdown, ids, previous.next_block_id+len(ids), previous,
                Provenance('USER', 'MANUAL_EDIT', draft['id']), draft['updated_at'], sources)
        saved = checked(save_manual_draft(executor, {'requirement_id': 1, 'document_id': identity,
            'draft_id': draft['id'], 'expected_version': draft['content_version'],
            'markdown_content': markdown, 'block_state_json': snapshot.state,
            'idempotency_key': str(uuid4())}, catalog=catalog), 'DRAFT_SAVED')
        checked(complete_manual_draft(executor, {'requirement_id': 1, 'document_id': identity,
            'draft_id': draft['id'], 'expected_version': saved['content_version'],
            'idempotency_key': str(uuid4())}, catalog=catalog), 'DRAFT_COMPLETED')
        return checked(get_current_document(database, 1, identity, catalog=catalog), 'READ_OK')

    def document(name, markdown):
        created = checked(create_document(executor, {'requirement_id': 1, 'name': name,
            'document_kind': 'REQUIREMENT_BRIEF', 'template_ref': None,
            'idempotency_key': str(uuid4())}, catalog=catalog), 'CREATED')
        return edit(created['document']['id'], markdown)

    def ref(doc):
        return {'kind': 'REVISION', 'document_id': doc['id'], 'revision_id': doc['current_revision_id'], 'block_ids': None}

    def target(doc):
        return {'kind': 'EXISTING', 'document_id': doc['id'], 'expected_content_version': doc['content_version']}

    if case == 'discuss-long-preference':
        pending(domain.preference)
        for index in range(12):
            pending('补充历史事项'+str(index+1)+'：本条没有改变既定偏好及首版边界。')
    if case == 'discuss-decline':
        checked(update_discussion(executor, {'requirement_id': 1, 'expected_discussion_version': version(),
            'discussion_command': {'type': 'SET_DISPOSITION', 'subject_ref': 'p1', 'decision': 'DECLINE_DRAFT',
                'description': '当前不生成文档，继续讨论推荐主流程；没有新依据不要重复建议出稿。'},
            'idempotency_key': str(uuid4())}, catalog=catalog), 'UPDATED')

    instruction = '请先给出首版目标和推荐主流程，再说明关键取舍，只讨论，不生成文档。'
    operation, destination, scope, refs = 'DISCUSS', None, None, []
    facts = {'postcondition': '只读讨论；不得创建正文或候选', 'setup_provider_calls': 0}
    if case == 'discuss-long-preference':
        instruction = '沿用我已经选定的偏好，给出主流程；不要重问已知答案，不写稿。'
    elif case == 'discuss-correction':
        instruction = domain.correction+' 请据此重述目标和推荐主流程，不生成文档。'
    elif case == 'discuss-decline':
        instruction = '继续说明主流程中的失败和反馈路径；当前仍不出稿。'
    elif case.startswith('document-'):
        if case == 'document-local-revise':
            doc = document('首版说明', '# 目标\n\n'+domain.idea+'。\n\n# 主流程\n\n'+domain.old_rule+'\n\n# 边界\n\n不做社交、不自动采购，保留本段原文。\n')
            heading = next(metadata['block_id'] for block, metadata in zip(parse_markdown(doc['markdown_content']).blocks, doc['block_state_json']['blocks']) if block.block_type=='heading' and block.plain_text=='主流程')
            operation, destination = 'REVISE', target(doc)
            scope = {'scope_type': 'SECTION', 'scope_ref': {'heading_block_id': heading}}
            instruction = '明确只修订主流程章节：'+domain.new_rule+' 其余章节保持原样。'
            facts['postcondition'] = '只保存一个新CONTENT；主流程范围外字节保持'
        else:
            operation = 'GENERATE';long = case == 'document-long-specification'
            destination = {'kind': 'NEW', 'name': domain.title+'说明', 'document_kind': 'specification' if long else 'brief',
                'template_ref': {'key': 'structure.specification', 'version': 'v1'} if long else None}
            instruction = '明确生成完整需求说明：'+domain.preference+' 未确认的内容标待定。'
            if long:
                instruction = '明确生成完整规格，按提供的模板逐项展开以下60项用例；每项给出输入、成功步骤、失败与取消处理、输出、验收，不能省略或只写目录。'+''.join('用例'+str(i)+'：记录第'+str(i)+'类数据并按已确认规则给出结果。' for i in range(1,61))+' 输出不完整时明确说明，不声称完整或已保存。'
            facts['postcondition'] = '完整返回直接保存；自然截断必须不半写，不自动补调用'
    elif case.startswith('proposals-'):
        source = document('来源A', '| 规则 | 说明 |\n| --- | --- |\n| '+domain.row_name+' | '+domain.new_rule+' |\n')
        doc = document('目标B', '| 规则 | 说明 |\n| --- | --- |\n| '+domain.row_name+' | '+domain.old_rule+' |\n| 保留项 | 本行不能修改。 |\n')
        operation, destination, refs = 'PROPOSE_CHANGES', target(doc), [ref(source)]
        scope = {'scope_type': 'DOCUMENT', 'scope_ref': None}
        instruction = '只将来源A中“'+domain.row_name+'”这一行合入目标B；给出精确表格行候选，保留非目标行，不直接写稿。'
        facts.update(postcondition='候选只作用于B的目标行；完成前不写正文', target_row=domain.row_name)
        if case == 'proposals-user-edit':
            facts['after_response'] = '以正常EDITED命令改候选说明为“'+domain.new_rule+' 由用户确认后处理。”，再完成批次；检查采用的是编辑值及非目标行不变'
        if case == 'proposals-stale-original':
            facts['after_response'] = '在隔离竞态注入中改变目标行原文；正常完成须明确拒绝且保留新原文，不能称已合入。注入不是用户正常操作或额外模型轮次'
    elif case.startswith('analysis-'):
        markdown = '# 目标\n\n'+domain.idea+'。\n\n# 主流程\n\n'+domain.old_rule+'\n\n# 边界\n\n不引入额外外部服务。\n'
        if case == 'analysis-required-over-budget':
            # Fixed high-entropy mandatory input, not a fabricated token count.
            markdown = '# 必须完整检查的来源\n\n'+'\n'.join(hashlib.sha256(('v15-ev-'+str(i)).encode()).hexdigest() for i in range(8000))+'\n'
        doc = document('分析来源', markdown)
        operation = 'REVIEW';destination = target(doc)
        if case == 'analysis-old-new':
            prior = ref(doc);doc = edit(doc['id'], markdown.replace(domain.old_rule, domain.new_rule))
            operation, destination, refs = 'COMPARE', None, [prior,ref(doc)]
            instruction = '比较来源的这两个固定版本，说明变化、影响及未覆盖范围；不修改任何正文。'
        elif case == 'analysis-local-impact':
            heading = next(metadata['block_id'] for block, metadata in zip(parse_markdown(doc['markdown_content']).blocks, doc['block_state_json']['blocks']) if block.block_type=='heading' and block.plain_text=='主流程')
            scope = {'scope_type': 'SECTION', 'scope_ref': {'heading_block_id': heading}}
            instruction = '仅检查主流程章节的影响及缺口，明确实际覆盖和未读范围，不修改正文。'
        else:
            refs = [ref(doc)];scope = {'scope_type': 'DOCUMENT', 'scope_ref': None}
            instruction = '必须完整检查所选来源，不能删减必要正文或以摘要代替；若超过准入预算，程序应停止，不发送Chat。'
        facts['postcondition'] = '只给分析，不同步正文；必要材料实测超限时Chat=0'

    identity = accept(instruction, operation, destination, scope, refs)
    with database.transaction() as connection:
        canonical = read_canonical(connection, identity, catalog)
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
    context = compile_context(canonical, catalog)
    if case == 'discuss-long-preference':
        assert context.input_json.count(domain.preference) == 1
        assert len(canonical['discussion']['pending_user_message_ids']) > 10
    if case == 'discuss-decline':
        assert context.input['project_position']['dispositions']
    return identity, context, facts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=CASES)
    parser.add_argument('--domain', choices=[domain.key for domain in DOMAINS])
    parser.add_argument('--report', type=Path, help='New Markdown under docs/verification/v1.5 only')
    args = parser.parse_args(argv)
    report = args.report.resolve() if args.report else None
    if report and (report.parent != (ROOT/'docs/verification/v1.5').resolve() or report.suffix != '.md' or report.exists()):
        parser.error('Report must be a new verification Markdown')
    from backend.app.infrastructure.database import Database
    from backend.app.infrastructure.process_lock import ProcessLock
    from backend.app.infrastructure.resources import ResourceCatalog
    catalog = ResourceCatalog();rows = []
    for domain in DOMAINS:
        if args.domain and args.domain != domain.key: continue
        for case in CASES:
            if args.case and args.case != case: continue
            with TemporaryDirectory(prefix='walle-v15-ev-input-') as directory:
                database = Database(Path(directory)/'input.sqlite');database.initialize()
                with ProcessLock.for_database(database.path) as lock:
                    _, context, facts = prepare_case(database, lock, catalog, domain, case)
                    digest = hashlib.sha256(context.input_json.encode('utf-8')).hexdigest()
                    rows.append((domain.key,case,len(context.input_json.encode('utf-8')),digest))
            print(domain.key+'/'+case+' prepared; provider_calls=0', flush=True)
    if report:
        date = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d')
        content = ('# V1.5 EV fixed input preparation\n\n'+date+' (Asia/Hong_Kong). Command: `'+Path(__file__).name+'`; '
            'fresh temporary SQLite, normal create/edit/discussion/accept/cancel commands, compile only. '
            'No credential, admission override, Tokenization, Chat or service. Temporary databases removed. '
            'This verifies inputs and scope, not provider counts or semantic EV results.\n\n'
            'Release: '+catalog.collaboration.release_sha256+'; source SHA256: '+hashlib.sha256(Path(__file__).read_bytes()).hexdigest()+'\n\n'
            '| Domain | Case | Actual user UTF-8 bytes | User SHA256 |\n| --- | --- | --- | --- |\n'
            +''.join('| '+' | '.join(map(str,row))+' |\n' for row in rows))
        with report.open('x',encoding='utf-8',newline='\n') as handle:handle.write(content)
    print('prepared='+str(len(rows))+'; Tokenization=0; Chat=0')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
