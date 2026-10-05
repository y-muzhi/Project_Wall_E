"""D-010 proof gates over original output and real same-snapshot sources.

These gates do not create trusted audit receipts, allocate persistent IDs, or
authorize C07. Its caller must bind the original Snapshot/authority/manifest to
actual C03/audit facts and recheck them in the final adoption transaction.
"""
import json

from backend.app.documents.markdown import parse_markdown
from backend.app.documents.patch_application import preview_patches
from backend.app.documents.patch_validation import validate_bundle
from backend.app.documents.snapshot import validate_template_lock
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.messages.cards import decode_cards, decode_responses, validate_cards, formal_answer_text
from backend.app.shared.validation import normalize_text


class OutputEvidenceInvalid(ValueError):
    code = 'OUTPUT_INVALID'


def _json(value):
    return json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))


def card_text(cards):
    """Exact approved display format for already structurally valid cards."""
    groups=[]
    for card in cards['cards']:
        lines=['卡片：'+_json(card['card_key'])]
        for field in ('question','context','card_type','required','selection_rule','custom_answer'):
            value=card[field]
            if field == 'selection_rule':value={key:value[key] for key in ('min','max')}
            elif field == 'custom_answer':value={key:value[key] for key in ('enabled','max_length')}
            lines.append(field+'：'+_json(value))
        lines.extend('选项：'+_json({key:option[key] for key in ('option_key','label','description','impact','risks')}) for option in card['options'])
        recommendation=card['recommendation']
        if recommendation is not None:recommendation={key:recommendation[key] for key in ('option_keys','reason')}
        lines.append('建议（尚未选择）：'+_json(recommendation))
        lines.extend('相关需求原文：'+_json({key:related[key] for key in ('block_id','content_snapshot')}) for related in card['related_spec_context'])
        if not card['related_spec_context']:lines.append('相关需求原文：[]')
        groups.append('\n'.join(lines))
    return '\n\n'.join(groups)


def validate_card_output(snapshot, manifest, output, protocol):
    if protocol.version != 'v2':raise OutputEvidenceInvalid('旧版卡片等价保证尚未闭合')
    cards=validate_cards(output['cards'],protocol)
    text=card_text(cards)
    if len(text)>100000 or output['message'] != text:
        raise OutputEvidenceInvalid('卡片原message必须与完整结构逐字等价')
    read=set(manifest['block_ids'])
    for card in cards['cards']:
        for related in card['related_spec_context']:
            target=snapshot.by_id.get(related['block_id'])
            if target is None or related['block_id'] not in read or related['content_snapshot'] != target[0].markdown:
                raise OutputEvidenceInvalid('卡片只能引用实际读取的完整原区块')
    return cards


def fact_declaration(snapshot, checked):
    """All fields come from one actual validated target and CheckedPatch."""
    value=checked.patch;block=snapshot.by_id[checked.target_id][0]
    names={'REPLACE_BLOCK':'替换区块','INSERT_BEFORE':'在区块前插入','INSERT_AFTER':'在区块后插入','DELETE_BLOCK':'删除区块','REPLACE_TABLE_ROW':'替换表格行'}
    lines=['确认事实变更','目标区块：'+str(checked.target_id),'章节：'+_json(list(block.section_path)),'操作：'+names[checked.operation]]
    if checked.operation == 'REPLACE_TABLE_ROW':
        selector=value['selector_json']
        lines+=['原表格：',block.markdown,'行选择：'+_json({key:selector[key] for key in ('key_column_index','key_value')})]
        proposed=_json(list(checked.row_cells))
    else:proposed='（删除，无新正文）' if checked.operation == 'DELETE_BLOCK' else checked.proposed_markdown
    lines+=['原文：',value['original_content'],'确认的新正文：',proposed]
    return '\n'.join(lines)


def _formal_proves(connection, row, declaration, checked, snapshot, manifest, catalog):
    messages=MessageRepository(connection);parent=messages.get(row['reply_to_message_id'])
    if parent is None or parent['id'] not in manifest['message_ids'] or parent['requirement_id'] != row['requirement_id'] or parent['role'] != 'ASSISTANT' or parent['message_type'] != 'INTERACTION_CARDS':
        return False
    run=connection.execute('SELECT * FROM guide_runs WHERE id=?',(parent['guide_run_id'],)).fetchone()
    if run is None or run['requirement_id'] != row['requirement_id']:return False
    protocol=catalog.restore(run['function_type'],run['prompt_version'],prompt_version=run['prompt_version'],context_template=run['context_template_key']+'@'+run['context_template_version'])
    cards=decode_cards(parent['structured_content_json'],protocol)
    answers=decode_responses(row['structured_content_json'],cards,protocol)
    if row['content'] != formal_answer_text(cards,answers):return False
    by_key={answer['card_key']:answer for answer in answers['responses']}
    related=[{'block_id':checked.target_id,'content_snapshot':snapshot.by_id[checked.target_id][0].markdown}]
    for card in cards['cards']:
        answer=by_key[card['card_key']]
        if (card['card_type']=='CONFIRM' and normalize_text(card['question'])==normalize_text(declaration+'\n是否确认以上事实和变更写入需求？')
            and [(option['option_key'],option['label']) for option in card['options']]==[('confirm','确认以上事实和变更'),('defer','尚未确认')]
            and card['custom_answer']=={'enabled':False,'max_length':0} and card['recommendation'] is None
            and card['selection_rule']=={'min':1,'max':1} and card['related_spec_context']==related
            and answer['selected_option_keys']==['confirm'] and answer['custom_answer'] is None and not answer['skipped']):
            return True
    return False


def validate_fact_patches(connection, *, requirement_id, snapshot, authority, output, manifest, protocol, catalog, template, locked_heading_ids):
    """Return a structural preview only after every fact has complete proof.

    No partial acceptance, semantic entailment guess, evidence truncation,
    source substitution, or manufacturing of a future persisted provenance.
    """
    # Frozen original-output Schema and full Manifest are prerequisites even
    # when called independently of the future trusted-result producer.
    output=protocol.parse_output(_json(output));manifest=protocol.validate_read_manifest(manifest)
    if protocol.action_type != 'INITIALIZE':raise OutputEvidenceInvalid('事实采用仅限INITIALIZE')
    facts=output['confirmed_fact_patches']
    if not facts:return None
    if protocol.version != 'v2':raise OutputEvidenceInvalid('旧版非空事实采用证明尚未闭合')
    checked=validate_bundle(snapshot,[item['patch'] for item in facts],authority)
    validate_template_lock(snapshot,template,tuple(locked_heading_ids))
    messages=MessageRepository(connection)
    for fact,patch in zip(facts,checked):
        if patch.target_id not in manifest['block_ids']:raise OutputEvidenceInvalid('事实目标未实际读取')
        evidence=fact['evidence'];identity=evidence[0]['message_id']
        if identity not in manifest['message_ids'] or any(item['message_id'] != identity for item in evidence):
            raise OutputEvidenceInvalid('事实须引用实际读取的同一完整用户来源')
        row=messages.get(identity)
        if row is None or row['requirement_id'] != requirement_id or row['role'] != 'USER':
            raise OutputEvidenceInvalid('事实证据必须来自同需求实际USER')
        declaration=fact_declaration(snapshot,patch)
        if row['message_type']=='TEXT':
            valid=(len(evidence)==1 and evidence[0]['quoted_text']==row['content'] and normalize_text(row['content'])==normalize_text(declaration))
        elif row['message_type']=='CARD_RESPONSE':
            content=row['content'];chunks=[content[index:index+10000] for index in range(0,len(content),10000)]
            valid=([item['quoted_text'] for item in evidence]==chunks and _formal_proves(connection,row,declaration,patch,snapshot,manifest,catalog))
        else:valid=False
        if not valid:raise OutputEvidenceInvalid('候选缺少完整逐字用户确认')
    preview=preview_patches(snapshot,[item['patch'] for item in facts],authority)
    actual=[(identity,block.heading_level,block.plain_text) for identity,block in zip(preview.block_ids,parse_markdown(preview.markdown).blocks) if identity in locked_heading_ids]
    expected=[(identity,heading.level,heading.text) for identity,heading in zip(locked_heading_ids,template.locked_headings)]
    if actual != expected:raise OutputEvidenceInvalid('初始化事实不得改变锁定标题及身份')
    return preview
