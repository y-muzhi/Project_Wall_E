"""Apply the exact displayed INITIALIZE confirmation without a Provider call."""
import json

from backend.app.comments.commands import revalidate_anchors
from backend.app.documents.markdown import parse_markdown
from backend.app.documents.patch_application import apply_confirmed_facts, preview_patches
from backend.app.documents.patch_errors import PatchInvalid, TargetStale
from backend.app.documents.patch_validation import validate_patch, validate_bundle
from backend.app.documents.snapshot import validate_template_lock, create_snapshot, Provenance
from backend.app.documents.tables import table_model, select_row
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment, message_sequence
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.guide_repository import GuideRepository
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.shared.validation import normalize_text
from .output_evidence import fact_declaration


QUESTION_END = '\n是否确认以上事实和变更写入需求？'
OPERATIONS = {'替换区块': 'REPLACE_BLOCK', '在区块前插入': 'INSERT_BEFORE',
              '在区块后插入': 'INSERT_AFTER', '删除区块': 'DELETE_BLOCK', '替换表格行': 'REPLACE_TABLE_ROW'}


def confirmation_patch(card, snapshot, authority):
    """Decode two explicit historical display grammars; never infer prose edits."""
    if (card['card_type'] != 'CONFIRM' or card['custom_answer'] != {'enabled': False, 'max_length': 0}
            or card['selection_rule'] != {'min': 1, 'max': 1} or card['recommendation'] is not None
            or [(o['option_key'], o['label']) for o in card['options']] != [('confirm', '确认以上事实和变更'), ('defer', '尚未确认')]):
        raise PatchInvalid('确认卡片未声明唯一、明确的事实决定')
    text = normalize_text(card['question'])
    lines = text.split('\n', 4)
    if len(lines) != 5 or lines[0] != '确认事实变更' or not lines[1].startswith('目标区块：') or not lines[2].startswith('章节：') or not lines[3].startswith('操作：') or not text.endswith(QUESTION_END):
        raise PatchInvalid('确认卡片缺少完整变更声明')
    try:
        target_id = int(lines[1][len('目标区块：'):])
        block = snapshot.by_id[target_id][0]
        section = json.loads(lines[2][len('章节：'):])
        operation = OPERATIONS[lines[3][len('操作：'):]]
    except (ValueError, KeyError):
        raise TargetStale('确认目标不存在或操作不能识别') from None
    related = card['related_spec_context']
    if section != list(block.section_path) or len(related) != 1 or related[0]['block_id'] != target_id:
        raise TargetStale('确认章节或目标与当前正文不一致')
    displayed = related[0]['content_snapshot']
    if operation != 'REPLACE_TABLE_ROW' and displayed != block.markdown:
        raise TargetStale('确认原文与当前正文不一致')
    tail = lines[4][:-len(QUESTION_END)]
    value = {'title': '写入已确认事实', 'explanation': '用户在原事实变更卡片中明确确认', 'impact': None,
             'target_ref': {'block_id': target_id}, 'patch_operation': operation, 'selector_json': None,
             'original_content': block.markdown, 'proposed_markdown': None, 'proposed_data_json': None}
    compact = False
    if operation == 'REPLACE_TABLE_ROW':
        # Both the canonical full declaration and the already displayed compact
        # table declaration contain the complete actual table and exact selector.
        canonical_prefix = '原表格：\n' + displayed + '\n行选择：'
        compact_prefix = '原表格：' + displayed.rstrip('\n') + '\n行选择：'
        if tail.startswith(canonical_prefix): prefix = canonical_prefix
        elif tail.startswith(compact_prefix): prefix = compact_prefix
        else: raise TargetStale('确认原表格与当前正文不一致')
        try: selector, consumed = json.JSONDecoder().raw_decode(tail[len(prefix):])
        except ValueError: raise PatchInvalid('确认行选择不能识别') from None
        table = table_model(block)
        row = table.rows[select_row(table, selector)]
        shown = parse_markdown(displayed)
        if len(shown.blocks) != 1: raise PatchInvalid('确认原表格必须为完整单一区块')
        shown_table = table_model(shown.blocks[0])
        shown_row = shown_table.rows[select_row(shown_table, selector)]
        if shown_table.headers != table.headers or shown_row.markdown != row.markdown:
            raise TargetStale('确认表头或目标行原文与当前正文不一致')
        rest = tail[len(prefix) + consumed:]
        original_prefix = '\n原文：\n' + row.markdown + '\n确认的新正文：\n'
        if rest.startswith(original_prefix): proposed = rest[len(original_prefix):]
        elif rest.startswith('\n确认的新正文：'):
            compact = True; proposed = rest[len('\n确认的新正文：'):]
        else: raise PatchInvalid('确认行变更缺少明确新正文')
        try: cells = json.loads(proposed)
        except ValueError: raise PatchInvalid('确认新行必须为完整JSON数组') from None
        value.update(selector_json=selector, original_content=row.markdown, proposed_data_json={'cells': cells})
    else:
        prefix = '原文：\n' + block.markdown + '\n确认的新正文：\n'
        # Normalize only the complete prefix, leaving the new body intact.
        prefix = normalize_text(prefix) + '\n'
        if not tail.startswith(prefix): raise TargetStale('确认原文与当前正文不一致')
        proposed = tail[len(prefix):]
        if operation == 'DELETE_BLOCK':
            if proposed != '（删除，无新正文）': raise PatchInvalid('删除声明包含额外正文')
        else: value['proposed_markdown'] = proposed
    checked = validate_patch(snapshot, value, authority)
    expected = fact_declaration(snapshot, checked) + QUESTION_END
    if operation == 'REPLACE_TABLE_ROW':
        expected = expected.replace('\n原表格：\n' + block.markdown, '\n原表格：\n' + displayed, 1)
    if compact:
        expected = '\n'.join(lines[:4]) + '\n原表格：' + displayed.rstrip('\n') + '\n行选择：' + json.dumps(selector, ensure_ascii=False, separators=(',', ':')) + '\n确认的新正文：' + json.dumps(cells, ensure_ascii=False, separators=(',', ':')) + QUESTION_END
    if normalize_text(expected) != text: raise PatchInvalid('确认声明与实际变更不一致')
    return value


def complete_confirmed_response(connection, *, cards, answers, snapshot, scope, template, sources, current, root, run, at, catalog):
    """Return None for ordinary questions; confirmations finish in this transaction."""
    declarations = [card for card in cards['cards'] if card['card_type'] == 'CONFIRM' and card['question'].startswith('确认事实变更')]
    if not declarations: return None
    selected = {answer['card_key']: answer for answer in answers['responses']}
    patches = []
    error = None
    initial = create_snapshot(template.markdown, Provenance('SYSTEM', 'TEMPLATE', None), current['created_at'], sources)
    locked = tuple(identity for identity, (block, _) in initial.by_id.items() if block.block_type == 'heading')
    try:
        for card in declarations:
            answer = selected[card['card_key']]
            if not answer['skipped'] and answer['selected_option_keys'] == ['confirm']:
                patches.append(confirmation_patch(card, snapshot, scope))
        if patches:
            validate_bundle(snapshot, patches, scope)
            preview = preview_patches(snapshot, patches, scope)
            # Existing application performs provenance and template checks on the adopted snapshot.
            actual = [(identity, block.heading_level, block.plain_text) for identity, block in zip(preview.block_ids, parse_markdown(preview.markdown).blocks) if identity in locked]
            expected = [(identity, heading.level, heading.text) for identity, heading in zip(locked, template.locked_headings)]
            if actual != expected:
                raise PatchInvalid('已确认变更不能改变模板标题身份')
    except (ValueError, TypeError, KeyError) as failure:
        error = str(failure); patches = []
    if patches:
        adopted = apply_confirmed_facts(snapshot, patches, scope, run['id'], at, sources)
        validate_template_lock(adopted, template, locked)
        if adopted is not snapshot:
            current = DocumentRepository(connection).replace_current(current, adopted, increment(current['content_version']), at)
            revalidate_anchors(connection, {'requirement_id': root['id'], 'new_document': {'markdown_content': adopted.parsed.markdown, 'block_state_json': adopted.state}}, catalog=catalog)
        content = f'程序已将 {len(patches)} 项确认变更写入文档，当前正文 v{current["content_version"]}。本次未调用 AI。需要继续澄清时，请发送下一条消息。'
    elif error:
        content = '程序已保存回答，但未写入文档：' + error + '。本次未调用 AI；原确认卡片与回答保留在对话中。'
    else:
        content = '程序已保存回答；本轮未确认事实写入，文档保持原样。本次未调用 AI。'
    assistant = entity_id(connection, EntityKind.MESSAGE)
    connection.execute("INSERT INTO conversation_messages VALUES (?,?,?,?,'ASSISTANT',?,'TEXT',NULL,NULL,NULL,?)", (assistant, root['id'], run['id'], message_sequence(connection, root['id']), content, at))
    effects = {'guide_run_id': run['id'], 'status': 'COMPLETED', 'assistant_message_id': assistant,
               'current_document': {'id': current['id'], 'content_version': current['content_version']}, 'suggestion_batch_id': None}
    connection.execute("UPDATE guide_runs SET status='COMPLETED',current_step='FINISHED',final_result_json=?,started_at=?,ended_at=?,updated_at=? WHERE id=? AND status='RUNNING' AND current_step='PREPARING'", (canonical_input(effects), at, at, at, run['id']))
    RequirementRepository(connection).recover_occupancy(root, None, None, at)
    return GuideRepository(connection).get(run['id'])
