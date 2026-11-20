"""Strict V2.1 value types; parsing never allocates database identities."""

import re
from copy import deepcopy

from backend.app.shared.json_canonical import canonical_input
from backend.app.shared.validation import (
    MAX_SAFE_INTEGER,
    object_fields,
    raw_text,
    reject,
    strict_enum,
    strict_integer,
)

PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MAX_CHANGES = 20
MAX_CHANGE_BYTES = 64 * 1024
MAX_RESULTS = 20
MAX_RELATED = 100
STEP_STATUSES = ('PLANNED', 'IN_PROGRESS', 'PAUSED', 'COMPLETED', 'CANCELLED')
BRANCH_STATUSES = ('OPEN', 'RESOLVED', 'DEFERRED', 'DROPPED')
ISSUE_STATUSES = BRANCH_STATUSES
RESULT_KINDS = ('CONTENT', 'ANALYSIS')

REFERENCE_PATTERNS = {
    'STEP': r's([1-9][0-9]*)',
    'BRANCH': r'b([1-9][0-9]*)',
    'ISSUE': r'i([1-9][0-9]*)',
    'ARTIFACT': r'a([1-9][0-9]*)',
    'RESULT': r's([1-9][0-9]*)\.o([1-9][0-9]*)',
    'TEMP_STEP': r'new_step_([1-9][0-9]*)',
    'TEMP_RESULT': r'new_result_([1-9][0-9]*)',
    'TEMP_BRANCH': r'new_branch_([1-9][0-9]*)',
    'TEMP_ISSUE': r'new_issue_([1-9][0-9]*)',
}


def reference(value, field, kind):
    if type(value) is not str:
        reject(field, 'INVALID_TYPE', '必须是指定种类的引用文本')
    match = re.fullmatch(REFERENCE_PATTERNS[kind], value)
    if match is None:
        reject(field, 'INVALID_FORMAT', '引用种类或格式不合法')
    bound = str(MAX_SAFE_INTEGER)
    for number in match.groups():
        if len(number) > len(bound) or len(number) == len(bound) and number > bound:
            reject(field, 'OUT_OF_RANGE', '引用编号超出安全整数范围')
    return value


def path_reference(value, field, kind):
    temporary = type(value) is str and value.startswith('new_')
    return reference(value, field, 'TEMP_' + kind if temporary else kind)


def nullable(value, field, parser):
    return None if value is None else parser(value, field)


def text(value, field, maximum=1000):
    result = raw_text(value, field, 1, maximum).replace('\r\n', '\n').replace('\r', '\n')
    try:
        result.encode('utf-8')
    except UnicodeEncodeError:
        reject(field, 'INVALID_FORMAT', '文本必须由有效Unicode码点组成')
    return result


def array(value, field, parser, *, minimum=0, maximum=MAX_RELATED, unique=False):
    if type(value) is not list:
        reject(field, 'INVALID_TYPE', '必须是数组')
    if len(value) < minimum or maximum is not None and len(value) > maximum:
        reject(field, 'OUT_OF_RANGE', '数组项数超出本次操作范围')
    result = []
    seen = set()
    for index, item in enumerate(value):
        parsed = parser(item, f'{field}[{index}]')
        if unique:
            key = canonical_input({'value': parsed})
            if key in seen:
                continue
            seen.add(key)
        result.append(parsed)
    return result


def source(value, field):
    from backend.app.requirements.discussion import discussion_resources

    try:
        result = discussion_resources().validate('SourceRef', value)
        canonical_input({'source': result})
    except (ValueError, UnicodeError, TypeError):
        reject(field, 'INVALID_FORMAT', '来源结构不合法')
    return deepcopy(result)


def sources(value, field):
    return array(value, field, source, unique=True)


def proposal(value, field):
    fields = ('message_id', 'card_key')
    item = object_fields(value, field, fields, fields)
    card_key = raw_text(item['card_key'], field + '.card_key', 1, 100)
    try:
        card_key.encode('utf-8')
    except UnicodeEncodeError:
        reject(field + '.card_key', 'INVALID_FORMAT', '卡片键必须由有效Unicode码点组成')
    return {
        'message_id': strict_integer(item['message_id'], field + '.message_id'),
        'card_key': card_key,
    }


def resume_basis(value, field):
    fields = ('expected_branch_status', 'expected_branch_event_id')
    item = object_fields(value, field, fields, fields)
    return {
        'expected_branch_status': strict_enum(
            item['expected_branch_status'],
            field + '.expected_branch_status',
            ('DEFERRED', 'RESOLVED'),
        ),
        'expected_branch_event_id': strict_integer(
            item['expected_branch_event_id'], field + '.expected_branch_event_id'
        ),
    }


def target_selection(value, field='target'):
    fields = (
        'discussion_step_ref',
        'discussion_branch_ref',
        'branch_intent',
        'branch_resume_basis',
    )
    item = object_fields(value, field, fields, fields)
    step = nullable(
        item['discussion_step_ref'],
        field + '.discussion_step_ref',
        lambda v, f: reference(v, f, 'STEP'),
    )
    branch = nullable(
        item['discussion_branch_ref'],
        field + '.discussion_branch_ref',
        lambda v, f: reference(v, f, 'BRANCH'),
    )
    intent = nullable(
        item['branch_intent'],
        field + '.branch_intent',
        lambda v, f: strict_enum(v, f, ('ENTER', 'RESUME')),
    )
    basis = nullable(item['branch_resume_basis'], field + '.branch_resume_basis', resume_basis)
    if branch is None:
        if intent is not None or basis is not None:
            reject(field, 'INVALID_FORMAT', '无支线时意图与恢复依据必须为空')
    elif step is None or intent is None or (intent == 'RESUME') != (basis is not None):
        reject(field, 'INVALID_FORMAT', '支线目标必须包含步骤及匹配的进入或恢复意图')
    return dict(zip(fields, (step, branch, intent, basis), strict=True))
