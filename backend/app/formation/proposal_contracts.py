"""Exact canonical proposals; neither client-selected payloads nor write authority."""

import json
from copy import deepcopy

from backend.app.infrastructure.resources import _validate
from backend.app.shared.validation import (
    object_fields,
    raw_text,
    reject,
    strict_enum,
    strict_integer,
)

from .path_contracts import route_batch
from .types import MAX_RESULTS, array, reference, sources, text

PURPOSES = ('STAGED_WRITE', 'FORMATION_PATH_CHANGE')


def original_text(value, field):
    result = raw_text(value, field, 1, 1000000)
    try:
        result.encode('utf-8')
    except UnicodeEncodeError:
        reject(field, 'INVALID_FORMAT', '正文必须由有效Unicode码点组成')
    return result


def basis(value, field):
    fields = ('formation_version', 'goal_version', 'document_revision_id', 'content_version')
    item = object_fields(value, field, fields, fields)
    return {key: strict_integer(item[key], field + '.' + key) for key in fields}


def write_payload(value, resources, field='action_payload'):
    fields = (
        'step_ref',
        'result_refs',
        'write_mode',
        'document_revision_id',
        'content_version',
        'goal_version',
        'definition_version',
        'scope',
        'markdown_content',
        'patches',
        'change_summary',
        'source_refs',
    )
    item = object_fields(value, field, fields, fields)
    parsed = {
        'step_ref': reference(item['step_ref'], field + '.step_ref', 'STEP'),
        'result_refs': array(
            item['result_refs'],
            field + '.result_refs',
            lambda v, f: reference(v, f, 'RESULT'),
            minimum=1,
            maximum=MAX_RESULTS,
            unique=True,
        ),
        'write_mode': strict_enum(
            item['write_mode'], field + '.write_mode', ('FILL_EMPTY', 'PATCH_EXISTING')
        ),
        **{
            key: strict_integer(item[key], field + '.' + key)
            for key in (
                'document_revision_id',
                'content_version',
                'goal_version',
                'definition_version',
            )
        },
        'scope': resources.validate('legacy_scope', item['scope']),
        'markdown_content': None
        if item['markdown_content'] is None
        else original_text(item['markdown_content'], field + '.markdown_content'),
        'patches': array(
            item['patches'], field + '.patches', lambda v, f: resources.validate_patch(v)
        ),
        'change_summary': text(item['change_summary'], field + '.change_summary'),
        'source_refs': sources(item['source_refs'], field + '.source_refs'),
    }
    if any(ref.split('.o')[0] != parsed['step_ref'] for ref in parsed['result_refs']):
        reject(field + '.result_refs', 'INVALID_FORMAT', '成果必须属于写入目标步骤')
    if parsed['write_mode'] == 'FILL_EMPTY':
        if parsed['scope'] != {'scope_type': 'DOCUMENT', 'scope_ref': None} or (
            parsed['markdown_content'] is None or parsed['patches']
        ):
            reject(field, 'INVALID_FORMAT', '空文档填充必须提供全文，不得携带补丁')
    elif parsed['markdown_content'] is not None or not parsed['patches']:
        reject(field, 'INVALID_FORMAT', '已有内容只能按精确补丁更新')
    return parsed


def path_payload(value, field='action_payload'):
    fields = ('basis', 'changes', 'result_routes', 'change_summary', 'source_refs')
    item = object_fields(value, field, fields, fields)
    changes, routes = route_batch(item['changes'], item['result_routes'], field)
    return {
        'basis': basis(item['basis'], field + '.basis'),
        'changes': changes,
        'result_routes': routes,
        'change_summary': text(item['change_summary'], field + '.change_summary'),
        'source_refs': sources(item['source_refs'], field + '.source_refs'),
    }


def proposal_group(value, resources, *, stored=False):
    fields = ('schema_version', 'intro', 'purpose', 'cards', 'action_payload')
    if stored:
        fields += ('program_binding',)
    item = object_fields(value, 'cards', fields, fields)
    if type(item['schema_version']) is not int or item['schema_version'] != 1:
        reject('cards.schema_version', 'INVALID_FORMAT', '卡片版本必须为1')
    purpose = strict_enum(item['purpose'], 'cards.purpose', PURPOSES)
    # The established card has two-option minimums. The new single explicit
    # apply action changes only this constraint, under this new-purpose boundary.
    definitions = deepcopy(resources.bundle['$defs'])
    definitions['legacy_card']['properties']['options']['minItems'] = 1
    card_schema = {'$ref': '#/$defs/legacy_card', '$defs': definitions}
    cards = array(
        item['cards'],
        'cards.cards',
        lambda v, f: _validate(json.dumps(card_schema), v),
        minimum=1,
        maximum=1,
    )
    card = cards[0]
    if (
        card['card_type'] != 'SINGLE_SELECT'
        or card['required'] is not True
        or len(card['options']) != 1
        or card['options'][0]['option_key'] != 'apply'
        or card['selection_rule'] != {'min': 1, 'max': 1}
        or card['custom_answer'] != {'enabled': False, 'max_length': 0}
        or card['recommendation'] is not None
        and card['recommendation']['option_keys'] != ['apply']
    ):
        reject('cards.cards', 'INVALID_FORMAT', '提案只允许明确的单项采用')
    result = {
        'schema_version': 1,
        'intro': raw_text(item['intro'], 'cards.intro', 0, 10000),
        'purpose': purpose,
        'cards': cards,
        'action_payload': write_payload(item['action_payload'], resources)
        if purpose == 'STAGED_WRITE'
        else path_payload(item['action_payload']),
    }
    if stored:
        result['program_binding'] = resources.validate('ProgramBinding', item['program_binding'])
    return result
