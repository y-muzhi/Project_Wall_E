"""Validate and render one original Coding questionnaire without model assistance."""

from backend.app.infrastructure.command_receipts import Rejection
from backend.app.shared.validation import (
    UNICODE_WHITESPACE,
    object_fields,
    raw_text,
    reject,
    strict_enum,
    strict_integer,
    text_value,
)

from .task_basis import TaskBasisUnavailable, read_task_basis

ACTIONS = ('CITE_FIXED_BASIS', 'USE_FIXED_BASIS', 'CLARIFY_FACTS')
FACT_KINDS = {'OBSERVATION': '现象', 'REPRODUCTION': '复现结果', 'EXISTING_BEHAVIOR': '既有行为'}
BASIS_FIELDS = ('document_id', 'revision_id', 'quote')
EVIDENCE_FIELDS = ('kind', 'id')
ANSWER_FIELDS = ('index', 'action', 'basis_refs', 'clarification')
FACT_FIELDS = ('kind', 'text', 'option_indices', 'evidence_refs')
EVIDENCE = {
    'VERIFICATION_ITEM': """SELECT i.result FROM code_verification_items i JOIN code_verifications v
                            ON v.id=i.verification_id WHERE v.task_id=? AND i.id=?""",
    'QUESTION': 'SELECT status FROM code_questions WHERE task_id=? AND id=?',
    'OPERATION': 'SELECT status FROM code_operations WHERE task_id=? AND id=?',
    'COMMAND': 'SELECT status FROM code_commands WHERE task_id=? AND id=?',
    'LLM_USE': """SELECT u.call_status FROM llm_uses u JOIN code_sessions s ON s.id=u.execution_session_id
                  WHERE s.task_id=? AND u.id=?""",
}
USE_BASIS = '请按本任务已有固定设计和授权自行处理，不增加业务规则'
FACT_HEADER = '【用户补充事实：未经程序验证，不构成设计或授权变更】'
FACT_FOOTER = '仅用于定位原设计内的实现。涉及新规则或与固定设计冲突时，记录未解决事项并移交文档；不得改变固定设计、权限、预算或目标。'


def _array(value, field):
    if type(value) is not list:
        reject(field, 'INVALID_TYPE', '必须为数组')
    return value


def _refs(value, field, fields):
    return [
        object_fields(row, f'{field}[{i}]', fields, fields)
        for i, row in enumerate(_array(value, field))
    ]


def _nonblank(value, field, maximum=None):
    result = raw_text(value, field, 1, maximum)
    if not result.strip(UNICODE_WHITESPACE):
        reject(field, 'TOO_SHORT', '必须包含非空白内容')
    return result


def _parse_facts(value, field):
    fact = object_fields(value, field, FACT_FIELDS, FACT_FIELDS)
    kind = strict_enum(fact['kind'], field + '.kind', FACT_KINDS)
    raw = text_value(fact['text'], field + '.text')
    normalized = raw.replace('\r\n', '\n').replace('\r', '\n')
    _nonblank(normalized, field + '.text', 2000)
    option_field = field + '.option_indices'
    indices = [
        strict_integer(item, option_field, minimum=0)
        for item in _array(fact['option_indices'], option_field)
    ]
    if len(indices) != len(set(indices)):
        reject(option_field, 'DUPLICATE_PARAMETER', '原题选项不得重复')
    for evidence in _refs(fact['evidence_refs'], field + '.evidence_refs', EVIDENCE_FIELDS):
        strict_enum(evidence['kind'], field + '.evidence_refs.kind', EVIDENCE)
        strict_integer(evidence['id'], field + '.evidence_refs.id')
    return kind


def parse_answers(value):
    answers = _refs(value, 'answers', ANSWER_FIELDS)
    if not answers:
        reject('answers', 'TOO_SHORT', '必须完整答复所有原题')
    for index, row in enumerate(answers):
        field = f'answers[{index}]'
        if strict_integer(row['index'], field + '.index', minimum=0) != index:
            reject(field + '.index', 'OUT_OF_RANGE', '必须按原题顺序逐题答复')
        action = strict_enum(row['action'], field + '.action', ACTIONS)
        bases = _refs(row['basis_refs'], field + '.basis_refs', BASIS_FIELDS)
        for basis in bases:
            for name in ('document_id', 'revision_id'):
                strict_integer(basis[name], field + '.basis_refs.' + name)
            _nonblank(basis['quote'], field + '.basis_refs.quote')
        if action == 'CLARIFY_FACTS':
            if (
                _parse_facts(row['clarification'], field + '.clarification') == 'EXISTING_BEHAVIOR'
                and not bases
            ):
                reject(field + '.basis_refs', 'TOO_SHORT', '既有行为需提供固定依据')
        elif row['clarification'] is not None:
            reject(field + '.clarification', 'INVALID_TYPE', '该答复方式不接受事实补充')
        if (action == 'USE_FIXED_BASIS' and bases) or (action == 'CITE_FIXED_BASIS' and not bases):
            reject(field + '.basis_refs', 'OUT_OF_RANGE', '固定依据数量与答复方式不符')
    return answers


def _reject(code, field):
    return Rejection(code, {'field_errors': [{'field': field, 'reason': 'RANGE'}]})


def render_answers(connection, task, original, answers):
    if len(answers) != len(original):
        return _reject('INVALID_INPUT', 'answers')
    basis_text = {}
    if any(answer['basis_refs'] for answer in answers):
        try:
            _, design = read_task_basis(connection, task, include_originals=True)
        except TaskBasisUnavailable:
            return _reject('BASIS_REF_INVALID', 'answers')
        basis_text = {
            (doc.document_id, doc.revision_id): doc.utf8.decode() for doc in design.originals
        }
    payload = []
    for index, (question, answer) in enumerate(zip(original, answers, strict=True)):
        field = f'answers[{index}]'
        if question['index'] != index:
            raise ValueError('Original question order differs')
        if answer['action'] == 'USE_FIXED_BASIS':
            payload.append([USE_BASIS])
            continue
        citations = []
        for ref in answer['basis_refs']:
            original_text = basis_text.get((ref['document_id'], ref['revision_id']))
            if original_text is None or ref['quote'] not in original_text:
                return _reject('BASIS_REF_INVALID', field + '.basis_refs')
            citations.append(
                f'文档 #{ref["document_id"]}，固定版本 #{ref["revision_id"]}\n{ref["quote"]}'
            )
        if answer['action'] == 'CITE_FIXED_BASIS':
            payload.append(['【固定依据】\n' + '\n'.join(citations) + '\n' + USE_BASIS])
            continue
        fact = answer['clarification']
        indices = sorted(fact['option_indices'])
        if any(item >= len(question['options']) for item in indices) or (
            not question['multiple'] and len(indices) > 1
        ):
            return _reject('INVALID_INPUT', field + '.clarification.option_indices')
        labels = [question['options'][item]['label'] for item in indices]
        evidence_labels = []
        for ref in fact['evidence_refs']:
            evidence = connection.execute(EVIDENCE[ref['kind']], (task['id'], ref['id'])).fetchone()
            if evidence is None:
                return _reject('INVALID_INPUT', field + '.clarification.evidence_refs')
            evidence_labels.append(f'{ref["kind"]} #{ref["id"]} · {evidence[0]}')
        payload.append(
            [
                '\n'.join(
                    (
                        FACT_HEADER,
                        FACT_KINDS[fact['kind']],
                        fact['text'].replace('\r\n', '\n').replace('\r', '\n'),
                        '原题选项：' + ('、'.join(labels) or '无'),
                        '证据：' + ('\n'.join(evidence_labels) or '无'),
                        '固定依据：' + ('\n'.join(citations) or '无'),
                        FACT_FOOTER,
                    )
                )
            ]
        )
    return payload
