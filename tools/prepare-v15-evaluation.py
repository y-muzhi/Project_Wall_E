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


def specification_instruction(domain):
    """Concrete, fixed business facts for the long-output boundary fixture.

    These are synthetic user instructions, not facts from an existing user
    workspace or a request to reduce the model's output limit.
    """
    if domain.key == 'movie':
        facts = ('单人本地电影记录；M001《星际旅程》2020年、科幻、未看、无评分，'
            'M002《月夜》2018年、剧情、已看、4星；当前记录版本7。标题非空，年份为1888至2100整数，'
            '评分为1至5整数星，未看记录不能评分。推荐仅筛选未看项，选中类型优先、同组按标题排序；'
            '无候选时显示空结果，不抓取外部片源。删除需确认，导出为UTF-8 CSV。')
        operations = (
            ('新增电影', '标题', '标题=海岸，年份=2024，类型=剧情，状态=未看', '创建新记录，评分为空'),
            ('编辑信息', '记录编号', '编号=M001，标题=星际旅程修订，年份=2021', '仅改标题和年份，保留未看状态'),
            ('删除电影', '记录编号', '编号=M001，确认=是', '只删除M001，保留M002'),
            ('标记已看', '记录编号', '编号=M001，状态=已看', 'M001改为已看，评分仍为空'),
            ('恢复未看', '记录编号', '编号=M002，状态=未看', 'M002改为未看并清除原评分'),
            ('设置评分', '评分', '编号=M002，评分=5', '已看记录更新为5星，不接受小数或范围外值'),
            ('清除评分', '记录编号', '编号=M002', '仅清空评分，保留已看状态及其他字段'),
            ('搜索标题', '关键词', '关键词=星际', '按标题包含匹配，仅返回M001，不改记录'),
            ('筛选未看', '状态', '状态=未看', '仅显示M001，不改变观看状态'),
            ('推荐下一部', '偏好类型', '偏好类型=科幻', '返回未看M001，绝不推荐已看M002'),
            ('查看详情', '记录编号', '编号=M002', '显示2018年、剧情、已看、4星，不改记录'),
            ('导出记录', '导出范围', '范围=全部，格式=CSV', '导出两条记录及标题、年份、类型、状态、评分，不改记录'),
        )
    else:
        facts = ('实验室L01和L02库存独立；L01有Q001试管12盒、安全库存5盒，Q002手套4盒、安全库存10盒；'
            'L02的同编号试管为30盒，不能混入L01结果。当前记录版本7。数量和安全库存为非负整数，'
            '入库及领用数量必须正整数，领用不得超过本实验室库存；低于而非等于阈值时提示补货。'
            '仅生成补货建议，不执行采购；建议量为安全库存减当前库存的正差。归档需确认且库存为0，导出为UTF-8 CSV。')
        operations = (
            ('新增耗材', '名称', '实验室=L01，编号=Q003，名称=离心管，单位=盒，初始库存=0，安全库存=3', '只在L01创建Q003'),
            ('编辑耗材', '耗材编号', '实验室=L01，编号=Q001，名称=标准试管', '只改名称，保留库存12盒'),
            ('记录入库', '数量', '实验室=L01，编号=Q001，数量=3', 'L01库存变15盒，L02保持30盒'),
            ('记录领用', '数量', '实验室=L01，编号=Q001，数量=2', 'L01库存变10盒并保存领用记录'),
            ('撤销登记', '登记编号', '实验室=L01，登记=E001入库3盒，登记后Q001为15盒', '只撤销E001并恢复12盒，重复撤销不重复扣减'),
            ('调整安全库存', '安全库存', '实验室=L01，编号=Q001，安全库存=15', '库存仍12盒，出现低库存提示'),
            ('查询库存', '耗材编号', '实验室=L01，编号=Q001', '返回12盒及5盒安全库存，不改数据'),
            ('查看低库存', '实验室编号', '实验室=L01', '仅列Q002，4小于10，Q001不出现'),
            ('生成补货建议', '实验室编号', '实验室=L01', '仅建议Q002补6盒，不生成采购或改库存'),
            ('切换实验室筛选', '实验室编号', '实验室=L02，编号=Q001', '仅显示L02的30盒，不合并L01数量'),
            ('归档耗材', '耗材编号', '实验室=L01，编号=Q004，现有库存=0，确认=是', '仅归档该零库存耗材，保留历史记录'),
            ('导出库存', '实验室编号', '实验室=L01，格式=CSV', '仅导出L01的耗材、库存、安全库存与单位，不包含L02'),
        )
    variants = (
        ('正常提交', '所有必填已给出，版本7，保存正常；按本操作正常结果处理'),
        ('缺少必填', '本例移除下述必填字段；明确该字段缺失，保留输入供修改，无业务变更'),
        ('版本变化', '提交版本7，权威记录已为版本8；显示数据变化，重读前不覆盖；查询仅显示实际读取版本'),
        ('用户取消', '在确认／等待结束前取消；没有提交成功回执，不写业务变更、不生成导出文件'),
        ('存储失败', '读取或保存明确失败；给出失败反馈，不显示成功、不写部分数据，允许用户手动重试'),
    )
    cases = []
    for name, required, values, result in operations:
        for boundary, condition in variants:
            cases.append('用例'+str(len(cases)+1)+'【'+name+'／'+boundary+'】：必填='+required+'；固定输入：'
                +values+'；正常业务规则：'+result+'；本例前置：'+condition+'。')
    return ('明确生成完整规格。以下是本次验收样本固定的用户业务事实：'+domain.preference+facts
        +' 每个用例独立从给定初始状态开始；写操作成功才保存一次新版本，读取不写，取消或失败不部分保存。'
        +'请按提供的完整模板逐项展开下列60项用例，每项明确输入、成功步骤、失败与取消处理、输出、验收；'
        +'不要只写目录或省略用例。未指定技术实现标待定，不编造外部接口或真实用户信息。'
        +''.join(cases)+' 输出不完整时明确说明，不声称完整或已保存。')


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
                instruction = specification_instruction(domain)
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
            # Revised after the observed 800000-byte aggregate text cap.
            # Preserve the old 8000-line generator in docs/sources/v1.5.
            # Real token counts still decide whether this input is over budget.
            markdown = '# 必须完整检查的来源\n\n'+'\n'.join(hashlib.sha256(('v15-ev-'+str(i)).encode()).hexdigest() for i in range(4000))+'\n'
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
                    text_bytes = sum(len(text.encode('utf-8')) for text in context.texts)
                    rows.append((domain.key,case,len(context.input_json.encode('utf-8')),digest,text_bytes))
            print(domain.key+'/'+case+' prepared; provider_calls=0', flush=True)
    if report:
        date = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d')
        content = ('# V1.5 EV fixed input preparation\n\n'+date+' (Asia/Hong_Kong). Command: `'+Path(__file__).name+'`; '
            'fresh temporary SQLite, normal create/edit/discussion/accept/cancel commands, compile only. '
            'No credential, admission override, Tokenization, Chat or service. Temporary databases removed. '
            'This verifies inputs and scope, not provider counts or semantic EV results.\n\n'
            'Release: '+catalog.collaboration.release_sha256+'; source SHA256: '+hashlib.sha256(Path(__file__).read_bytes()).hexdigest()+'\n\n'
            'Aggregate text-byte capacity is checked separately from exact token counts. '
            'Required-input fixture now has 4000 deterministic lines; its token-limit result is unverified. '
            'Original 8000-line generator remains byte-identical in docs/sources/v1.5/prepare-v15-evaluation-v12-frozen.py.\n\n'
            '| Domain | Case | Actual user UTF-8 bytes | User SHA256 | Eight-text UTF-8 bytes |\n| --- | --- | --- | --- | --- |\n'
            +''.join('| '+' | '.join(map(str,row))+' |\n' for row in rows))
        with report.open('x',encoding='utf-8',newline='\n') as handle:handle.write(content)
    print('prepared='+str(len(rows))+'; Tokenization=0; Chat=0')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
