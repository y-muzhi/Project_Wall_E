"""The twelve ordinary model delta alternatives, distinct from manual PathChange authority."""

from backend.app.shared.json_canonical import canonical_input
from backend.app.shared.validation import (
    object_fields,
    reject,
    strict_boolean,
    strict_enum,
    strict_integer,
)

from .types import (
    MAX_CHANGE_BYTES,
    MAX_CHANGES,
    MAX_RESULTS,
    array,
    nullable,
    path_reference,
    reference,
    text,
)

FIELDS = {
    'INITIALIZE_PATH': ('goal', 'steps'),
    'ADD_STEP': (
        'temp_ref',
        'title',
        'expected_results',
        'dependencies',
        'topic_refs',
        'before_step_ref',
    ),
    'UPDATE_STEP': ('step_ref', 'title', 'add_results', 'dependencies', 'topic_refs'),
    'MOVE_STEP': ('step_ref', 'before_step_ref'),
    'ADD_ISSUE': ('temp_ref', 'step_ref', 'branch_ref', 'description', 'blocking', 'source_refs'),
    'UPDATE_ISSUE': ('issue_ref', 'description', 'blocking', 'resolution'),
    'ADD_BRANCH': (
        'temp_ref',
        'origin_step_ref',
        'return_step_ref',
        'question',
        'relevance',
        'topic_refs',
        'source_refs',
    ),
    'UPDATE_BRANCH': ('branch_ref', 'topic_refs', 'result'),
    'SET_BRANCH_FOCUS': ('branch_ref', 'reason'),
    'ASSESS_STEP': (
        'step_ref',
        'definition_version',
        'verdict',
        'reason',
        'document_refs',
        'source_refs',
    ),
    'RECOMMEND': ('step_ref', 'action', 'reason', 'target_step_ref', 'source_refs'),
    'ASSOCIATE_CONTENT': ('step_ref', 'result_refs', 'document_refs', 'source_refs', 'review_of'),
}

RECOMMENDATIONS = (
    'DISCUSS',
    'WRITE',
    'RESOLVE_BRANCH',
    'REVIEW_CONTENT',
    'COMPLETE_STEP',
    'SWITCH_STEP',
    'NEED_MATERIAL',
)


def alias(value, field):
    # Alias existence and coverage are checked against the frozen real Wire,
    # never inferred from a familiar-looking SQL/reference prefix.
    return text(value, field, 160)


def aliases(value, field, *, minimum=0):
    return array(value, field, alias, minimum=minimum, maximum=100, unique=True)


def topic(value, field):
    if type(value) is not str or not value.startswith('t'):
        reject(field, 'INVALID_FORMAT', '主题引用必须是同文档真实主题')
    reference('s' + value[1:], field, 'STEP')
    return value


def refs(value, field, kind, *, minimum=0, maximum=None):
    return array(
        value,
        field,
        lambda v, f: path_reference(v, f, kind),
        minimum=minimum,
        maximum=maximum,
        unique=True,
    )


def topics(value, field):
    return array(value, field, topic, maximum=None, unique=True)


def expected_result(value, field):
    fields = ('temp_ref', 'description', 'kind')
    item = object_fields(value, field, fields, fields)
    return {
        'temp_ref': reference(item['temp_ref'], field + '.temp_ref', 'TEMP_RESULT'),
        'description': text(item['description'], field + '.description'),
        'kind': strict_enum(item['kind'], field + '.kind', ('CONTENT', 'ANALYSIS')),
    }


def step_draft(value, field):
    fields = ('temp_ref', 'title', 'expected_results', 'dependencies', 'topic_refs')
    item = object_fields(value, field, fields, fields)
    return {
        'temp_ref': reference(item['temp_ref'], field + '.temp_ref', 'TEMP_STEP'),
        'title': text(item['title'], field + '.title', 120),
        'expected_results': array(
            item['expected_results'],
            field + '.expected_results',
            expected_result,
            minimum=1,
            maximum=MAX_RESULTS,
        ),
        'dependencies': refs(item['dependencies'], field + '.dependencies', 'STEP'),
        'topic_refs': topics(item['topic_refs'], field + '.topic_refs'),
    }


def goal(value, field):
    item = object_fields(value, field, ('text', 'source_refs'), ('text', 'source_refs'))
    return {
        'text': text(item['text'], field + '.text'),
        'source_refs': aliases(item['source_refs'], field + '.source_refs'),
    }


def resolution(value, field):
    item = object_fields(value, field, ('summary', 'source_refs'), ('summary', 'source_refs'))
    return {
        'summary': text(item['summary'], field + '.summary'),
        'source_refs': aliases(item['source_refs'], field + '.source_refs', minimum=1),
    }


def basis(value, field):
    fields = ('formation_version', 'goal_version', 'document_revision_id', 'content_version')
    item = object_fields(value, field, fields, fields)
    result = {}
    for name in fields:
        parsed = (
            nullable(item[name], field + '.' + name, strict_integer)
            if name in ('formation_version', 'goal_version')
            else strict_integer(item[name], field + '.' + name)
        )
        result[name] = parsed
    if (result['formation_version'] is None) != (result['goal_version'] is None):
        reject(field, 'INVALID_FORMAT', '未建主线时F与Goal版本必须同时为空')
    return result


def change(value, field):
    header = object_fields(
        value, field, ('type', *(name for fields in FIELDS.values() for name in fields)), ('type',)
    )
    kind = strict_enum(header['type'], field + '.type', FIELDS)
    fields = ('type', *FIELDS[kind])
    item = object_fields(header, field, fields, fields)
    result = {'type': kind}
    for name in FIELDS[kind]:
        value, key = item[name], field + '.' + name
        if name == 'goal':
            parsed = goal(value, key)
        elif name == 'steps':
            parsed = array(value, key, step_draft, minimum=1, maximum=20)
        elif name == 'temp_ref':
            entity = {'ADD_STEP': 'STEP', 'ADD_ISSUE': 'ISSUE', 'ADD_BRANCH': 'BRANCH'}[kind]
            parsed = reference(value, key, 'TEMP_' + entity)
        elif name == 'title':
            parsed = (
                nullable(value, key, lambda v, f: text(v, f, 120))
                if kind == 'UPDATE_STEP'
                else text(value, key, 120)
            )
        elif name in ('expected_results', 'add_results'):
            parsed = array(
                value,
                key,
                expected_result,
                minimum=1 if name == 'expected_results' else 0,
                maximum=MAX_RESULTS,
            )
        elif name == 'dependencies':
            parsed = (
                nullable(value, key, lambda v, f: refs(v, f, 'STEP'))
                if kind == 'UPDATE_STEP'
                else refs(value, key, 'STEP')
            )
        elif name == 'topic_refs':
            parsed = (
                nullable(value, key, topics)
                if kind in ('UPDATE_STEP', 'UPDATE_BRANCH')
                else topics(value, key)
            )
        elif name in (
            'step_ref',
            'origin_step_ref',
            'return_step_ref',
            'target_step_ref',
            'before_step_ref',
        ):
            parser = lambda v, f: path_reference(v, f, 'STEP')
            parsed = (
                nullable(value, key, parser)
                if name in ('target_step_ref', 'before_step_ref')
                else parser(value, key)
            )
        elif name == 'branch_ref':
            parser = lambda v, f: path_reference(v, f, 'BRANCH')
            parsed = (
                nullable(value, key, parser)
                if kind in ('ADD_ISSUE', 'SET_BRANCH_FOCUS')
                else parser(value, key)
            )
        elif name == 'issue_ref':
            parsed = path_reference(value, key, 'ISSUE')
        elif name == 'description':
            parsed = nullable(value, key, text) if kind == 'UPDATE_ISSUE' else text(value, key)
        elif name == 'blocking':
            parsed = (
                nullable(value, key, strict_boolean)
                if kind == 'UPDATE_ISSUE'
                else strict_boolean(value, key)
            )
        elif name in ('resolution', 'result'):
            parsed = nullable(value, key, resolution)
        elif name in ('question', 'relevance', 'reason'):
            parsed = text(value, key)
        elif name == 'source_refs':
            parsed = aliases(value, key)
        elif name == 'document_refs':
            parsed = aliases(value, key, minimum=1 if kind == 'ASSOCIATE_CONTENT' else 0)
        elif name == 'definition_version':
            parsed = strict_integer(value, key)
        elif name == 'verdict':
            parsed = strict_enum(value, key, ('SUFFICIENT', 'GAPS_REMAIN', 'UNCERTAIN'))
        elif name == 'action':
            parsed = strict_enum(value, key, RECOMMENDATIONS)
        elif name == 'result_refs':
            parsed = refs(value, key, 'RESULT', minimum=1, maximum=MAX_RESULTS)
        elif name == 'review_of':
            parsed = nullable(value, key, lambda v, f: reference(v, f, 'ARTIFACT'))
        else:
            raise AssertionError('Unimplemented model delta field ' + name)
        result[name] = parsed
    if kind == 'UPDATE_STEP' and all(
        result[name] is None if name != 'add_results' else not result[name]
        for name in ('title', 'add_results', 'dependencies', 'topic_refs')
    ):
        reject(field, 'INVALID_FORMAT', '步骤维护必须指定至少一个实际更新项')
    return result


def formation_delta(value, field='formation_delta'):
    item = object_fields(value, field, ('basis', 'changes'), ('basis', 'changes'))
    result = {
        'basis': basis(item['basis'], field + '.basis'),
        'changes': array(
            item['changes'], field + '.changes', change, minimum=1, maximum=MAX_CHANGES
        ),
    }
    if sum(change['type'] == 'INITIALIZE_PATH' for change in result['changes']) > 1:
        reject(field, 'INVALID_FORMAT', '同一轮只能初始化一次主线')
    if len(canonical_input({'changes': result['changes']}).encode('utf-8')) > MAX_CHANGE_BYTES:
        reject(field, 'TOO_LONG', '本轮主线增量超过64KiB')
    return result
