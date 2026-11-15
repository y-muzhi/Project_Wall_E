"""Strict Testing drafts and immutable design ancestry; no candidate inputs."""

from backend.app.code_tasks.design_revisions import design_revision_choice
from backend.app.infrastructure.check_case_pack import CasePackLimits, validate_draft_operations
from backend.app.infrastructure.check_case_values import text_literal
from backend.app.infrastructure.check_runner_bundle import CheckResourceError, reference
from backend.app.shared.validation import (
    object_fields,
    ordinary_text,
    reject,
    strict_enum,
    strict_integer,
)

PLAN_FIELDS = (
    'requirement_id',
    'document_id',
    'design_revision_id',
    'material_refs',
    'behaviors',
    'cases',
    'unresolved_questions',
)
BASIS_FIELDS = PLAN_FIELDS[:4]
_STAGES = ('BACKEND', 'FRONTEND', 'INTEGRATION', 'ACCEPTANCE')
_BEHAVIOR = (
    'behavior_id',
    'name',
    'basis_refs',
    'stages',
    'importance',
    'mode',
    'case_ids',
    'explanation',
)
_CASE = (
    'case_id',
    'name',
    'behavior_ids',
    'visibility',
    'driver_kind',
    'steps',
    'assertions',
    'timeout_seconds',
)
_LIMITS = CasePackLimits(4096, 256, 1024 * 1024, 3600)


def _rows(value, field, *, maximum=4096, minimum=0):
    if type(value) is not list or not minimum <= len(value) <= maximum:
        reject(field, 'INVALID_TYPE', '列表长度或结构不符合限制')
    return value


def _distinct(values, field):
    if len(set(values)) != len(values):
        reject(field, 'DUPLICATE_PARAMETER', '固定标识不得重复')
    return values


def _identity(value, field):
    try:
        return reference(value)
    except CheckResourceError:
        reject(field, 'INVALID_FORMAT', '标识不符合受控用例协议')


def _ids(value, field, *, minimum=0):
    return _distinct(
        [_identity(item, field) for item in _rows(value, field, minimum=minimum)],
        field,
    )


def _reference(value, field, *, quote=False):
    fields = ('document_id', 'revision_id', 'quote') if quote else ('document_id', 'revision_id')
    value = object_fields(value, field, fields, fields)
    result = {key: strict_integer(value[key], field + '.' + key) for key in fields[:2]}
    if quote:
        try:
            result['quote'] = text_literal(value['quote'])
        except CheckResourceError:
            reject(field + '.quote', 'INVALID_FORMAT', '引用须保留有效原文字节')
    return result


def _behavior(value, field):
    item = object_fields(value, field, _BEHAVIOR, _BEHAVIOR)
    refs = [
        _reference(ref, f'{field}.basis_refs[{index}]', quote=True)
        for index, ref in enumerate(
            _rows(item['basis_refs'], field + '.basis_refs', maximum=256, minimum=1)
        )
    ]
    _distinct([tuple(ref.values()) for ref in refs], field + '.basis_refs')
    stages = _distinct(
        [
            strict_enum(stage, field + '.stages', _STAGES)
            for stage in _rows(item['stages'], field + '.stages', maximum=4, minimum=1)
        ],
        field + '.stages',
    )
    return {
        'behavior_id': _identity(item['behavior_id'], field + '.behavior_id'),
        'name': ordinary_text(item['name'], field + '.name', 1, 256),
        'basis_refs': refs,
        'stages': stages,
        'importance': strict_enum(
            item['importance'], field + '.importance', ('BLOCKER', 'CRITICAL', 'NORMAL')
        ),
        'mode': strict_enum(
            item['mode'], field + '.mode', ('AUTO', 'MANUAL', 'NOT_APPLICABLE', 'UNCOVERED')
        ),
        'case_ids': _ids(item['case_ids'], field + '.case_ids'),
        'explanation': ordinary_text(item['explanation'], field + '.explanation', 0, 2000),
    }


def _case(value, field):
    item = object_fields(value, field, _CASE, _CASE)
    driver = strict_enum(item['driver_kind'], field + '.driver_kind', ('CLI', 'HTTP', 'BROWSER'))
    try:
        validate_draft_operations(item, driver, _LIMITS)
    except (CheckResourceError, ValueError):
        reject(field, 'INVALID_FORMAT', '步骤或断言不符合受控用例协议')
    return {
        'case_id': _identity(item['case_id'], field + '.case_id'),
        'name': ordinary_text(item['name'], field + '.name', 1, 256),
        'behavior_ids': _ids(item['behavior_ids'], field + '.behavior_ids', minimum=1),
        'visibility': strict_enum(
            item['visibility'], field + '.visibility', ('PUBLIC', 'HELD_OUT')
        ),
        'driver_kind': driver,
        'steps': item['steps'],
        'assertions': item['assertions'],
        'timeout_seconds': strict_integer(
            item['timeout_seconds'], field + '.timeout_seconds', maximum=_LIMITS.max_timeout_seconds
        ),
    }


def parse_fixed_basis(source):
    materials = [
        _reference(row, f'material_refs[{index}]')
        for index, row in enumerate(_rows(source['material_refs'], 'material_refs', maximum=256))
    ]
    _distinct([ref['document_id'] for ref in materials], 'material_refs')
    return {
        **{key: strict_integer(source[key], key) for key in BASIS_FIELDS[:3]},
        'material_refs': sorted(materials, key=lambda ref: ref['document_id']),
    }


def parse_plan_content(value):
    source = object_fields(value, 'plan_content', PLAN_FIELDS, PLAN_FIELDS)
    basis = parse_fixed_basis(source)
    behaviors = [
        _behavior(row, f'behaviors[{index}]')
        for index, row in enumerate(_rows(source['behaviors'], 'behaviors'))
    ]
    _distinct([row['behavior_id'] for row in behaviors], 'behaviors')
    cases = [
        _case(row, f'cases[{index}]')
        for index, row in enumerate(
            _rows(source['cases'], 'cases', maximum=_LIMITS.max_check_cases)
        )
    ]
    _distinct([row['case_id'] for row in cases], 'cases')
    return {
        **basis,
        'behaviors': behaviors,
        'cases': cases,
        'unresolved_questions': [
            ordinary_text(item, 'unresolved_questions', 1, 2000)
            for item in _rows(source['unresolved_questions'], 'unresolved_questions', maximum=256)
        ],
    }


def _read_basis(connection, content, require_confirmed):
    document = content['document_id']
    main = design_revision_choice(
        connection,
        document,
        content['design_revision_id'],
        usage='MAIN',
        include_markdown=True,
    )
    if (
        main is None
        or main['requirement_id'] != content['requirement_id']
        or (require_confirmed and not main['eligible'])
    ):
        return 'design_revision_id', None
    refs = {(document, main['revision_id']): main['markdown_snapshot']}
    for index, ref in enumerate(content['material_refs']):
        if ref['document_id'] == document:
            return f'material_refs[{index}].document_id', None
        choice = design_revision_choice(
            connection,
            ref['document_id'],
            ref['revision_id'],
            usage='MATERIAL',
            include_markdown=True,
        )
        if (
            choice is None
            or choice['requirement_id'] != content['requirement_id']
            or (require_confirmed and not choice['eligible'])
        ):
            return f'material_refs[{index}].revision_id', None
        refs[(ref['document_id'], ref['revision_id'])] = choice['markdown_snapshot']
    return None, refs


def invalid_fixed_basis(connection, content, *, require_confirmed):
    field, _ = _read_basis(connection, content, require_confirmed)
    return field


def invalid_basis(connection, content, *, require_confirmed=False):
    field, refs = _read_basis(connection, content, require_confirmed)
    if field is not None:
        return field
    for index, behavior in enumerate(content['behaviors']):
        for position, ref in enumerate(behavior['basis_refs']):
            markdown = refs.get((ref['document_id'], ref['revision_id']))
            if markdown is None or ref['quote'] not in markdown:
                return f'behaviors[{index}].basis_refs[{position}]'
    return None


def publication_gap(content):
    behaviors = content['behaviors']
    cases = content['cases']
    cases_by_id = {case['case_id']: case for case in cases}
    behaviors_by_id = {item['behavior_id']: item for item in behaviors}
    for index, item in enumerate(behaviors):
        field = f'behaviors[{index}]'
        if item['mode'] == 'AUTO':
            if not item['case_ids'] or any(
                case_id not in cases_by_id
                or item['behavior_id'] not in cases_by_id[case_id]['behavior_ids']
                for case_id in item['case_ids']
            ):
                return field + '.case_ids'
        elif item['case_ids'] or not item['explanation']:
            return field + ('.case_ids' if item['case_ids'] else '.explanation')
        elif item['mode'] == 'UNCOVERED' and item['importance'] in ('BLOCKER', 'CRITICAL'):
            return field + '.mode'
    for index, case in enumerate(cases):
        field = f'cases[{index}]'
        for behavior_id in case['behavior_ids']:
            behavior = behaviors_by_id.get(behavior_id)
            if (
                behavior is None
                or behavior['mode'] != 'AUTO'
                or case['case_id'] not in behavior['case_ids']
            ):
                return field + '.behavior_ids'
        if not case['steps']:
            return field + '.steps'
        if not case['assertions']:
            return field + '.assertions'
    return None
