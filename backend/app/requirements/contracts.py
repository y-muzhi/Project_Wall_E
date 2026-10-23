"""APP-REQ-QUERY-C01/C02 inputs and exact read projections.

Stored values are checked, never normalized or repaired by a read. These checks
cover Requirement's own fields, not the cross-aggregate lifecycle guard.
"""
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Mapping, Any

from backend.app.shared.pagination import page_number, page_metadata
from backend.app.shared.time import utc_milliseconds
from backend.app.shared.validation import (
    MISSING, keyword, object_fields, reject, strict_enum, strict_integer, title,
)

STATUSES = ('PLANNING', 'READY', 'IMPLEMENTING', 'COMPLETED', 'CLOSED')
REQUIREMENT_TYPES = ('NEW', 'CHANGE')
READ_FIELDS = (
    'id', 'requirement_no', 'requirement_type', 'title', 'status',
    'metadata_version', 'initial_message_id', 'discussion_version',
    'document_work_state', 'active_operation_type', 'active_operation_id',
    'created_at', 'updated_at', 'completed_at', 'closed_at', 'state_started_at',
)
STORED_FIELDS = (*READ_FIELDS, 'discussion_state_json')
LIST_FIELDS = ('id', 'requirement_no', 'title', 'requirement_type', 'status', 'updated_at')


@dataclass(frozen=True)
class CreateRequirementInput:
    title: str
    requirement_type: str
    initial_idea: str
    idempotency_key: str

    def business_input(self) -> dict:
        return {field: getattr(self, field) for field in ('title', 'requirement_type', 'initial_idea')}


def create_requirement_input(payload: object) -> CreateRequirementInput:
    from backend.app.shared.validation import initial_idea
    from backend.app.infrastructure.idempotency import canonical_input, request_key
    fields = ('title', 'requirement_type', 'initial_idea', 'idempotency_key')
    data = object_fields(payload, 'body', fields, fields)
    request = CreateRequirementInput(title(data['title']), strict_enum(data['requirement_type'], 'requirement_type', REQUIREMENT_TYPES),
        initial_idea(data['initial_idea']), request_key(data['idempotency_key'], 'idempotency_key'))
    for field, value in request.business_input().items():
        try:
            value.encode('utf-8')
        except UnicodeEncodeError:
            reject(field, 'INVALID_FORMAT', '文本必须由有效Unicode码点组成')
    canonical_input(request.business_input())
    return request


def create_requirement_result(root: Mapping[str, Any], initial_message_id: int) -> dict:
    value = requirement_read_model(root)
    strict_integer(initial_message_id, 'initial_message_id')
    if value['status'] != 'PLANNING' or value['document_work_state'] != 'IDLE' or value['initial_message_id'] != initial_message_id:
        raise ValueError('Created requirement must be idle with its actual initial input')
    return {'requirement': value, 'initial_message_id': initial_message_id, 'documents': []}


@dataclass(frozen=True)
class ListRequirementsInput:
    keyword: str | None
    status: tuple[str, ...]
    requirement_type: tuple[str, ...]
    page: int


def _enum_array(value: object, field: str, choices: tuple[str, ...]) -> tuple[str, ...]:
    if type(value) is not list:
        reject(field, 'INVALID_TYPE', '必须是枚举数组且不能为null')
    result = tuple(dict.fromkeys(strict_enum(item, f'{field}[{index}]', choices)
                                 for index, item in enumerate(value)))
    return () if set(result) == set(choices) else result


def list_requirements_input(payload: object) -> ListRequirementsInput:
    data = object_fields(payload, 'query', ('keyword', 'status', 'requirement_type', 'page'))
    term = data.get('keyword')
    if term is not None:
        term = keyword(term) or None
        if term is not None:
            try:
                term.encode('utf-8')
            except UnicodeEncodeError:
                reject('keyword', 'INVALID_FORMAT', '文本必须由有效Unicode码点组成')
    return ListRequirementsInput(
        term, _enum_array(data.get('status', []), 'status', STATUSES),
        _enum_array(data.get('requirement_type', []), 'requirement_type', REQUIREMENT_TYPES),
        page_number(data.get('page', 1)),
    )


def requirement_id_input(value: object = MISSING) -> int:
    return strict_integer(value, 'requirement_id')


def get_requirement_input(value: object = MISSING) -> int:
    return requirement_id_input(value)


def get_requirement_result(row: Mapping[str, Any]) -> dict[str, Any]:
    return requirement_read_model(row)


@dataclass(frozen=True)
class UpdateRequirementInput:
    requirement_id: int
    expected_metadata_version: int
    changes: dict[str, str]
    idempotency_key: str

    def business_input(self) -> dict:
        return {'requirement_id': self.requirement_id, 'expected_metadata_version': self.expected_metadata_version, 'changes': self.changes}


def update_requirement_input(payload: object) -> UpdateRequirementInput:
    from backend.app.infrastructure.idempotency import canonical_input, request_key
    fields = ('requirement_id', 'expected_metadata_version', 'changes', 'idempotency_key')
    data = object_fields(payload, 'body', fields, fields)
    submitted = object_fields(data['changes'], 'changes', ('title', 'status'))
    if not submitted:
        reject('changes', 'REQUIRED', '至少提供一项属性')
    changes = {}
    if 'title' in submitted:
        changes['title'] = title(submitted['title'])
        try:
            changes['title'].encode('utf-8')
        except UnicodeEncodeError:
            reject('changes.title', 'INVALID_FORMAT', '文本必须由有效Unicode码点组成')
    if 'status' in submitted:
        changes['status'] = strict_enum(submitted['status'], 'changes.status', STATUSES)
    request = UpdateRequirementInput(requirement_id_input(data['requirement_id']),
        strict_integer(data['expected_metadata_version'], 'expected_metadata_version'), changes,
        request_key(data['idempotency_key'], 'idempotency_key'))
    canonical_input(request.business_input())
    return request


def update_requirement_result(row: Mapping[str, Any]) -> dict[str, Any]:
    return requirement_read_model(row)


@dataclass(frozen=True)
class DiscussionCommandInput:
    requirement_id: int
    expected_discussion_version: int
    discussion_command: dict
    idempotency_key: str

    def business_input(self):
        return {key: getattr(self, key) for key in ('requirement_id', 'expected_discussion_version', 'discussion_command')}


def discussion_command_input(payload):
    from backend.app.infrastructure.idempotency import request_key, canonical_input
    from backend.app.shared.validation import ordinary_text
    from .discussion import discussion_resources
    fields = ('requirement_id', 'expected_discussion_version', 'discussion_command', 'idempotency_key')
    data = object_fields(payload, 'body', fields, fields)
    command = object_fields(data['discussion_command'], 'discussion_command',
        ('type', 'target_document_id', 'source_refs', 'scope', 'topic_ref', 'phase_kind', 'closure_message', 'unresolved_refs', 'subject_ref', 'decision', 'description'), ('type',))
    kind = strict_enum(command['type'], 'discussion_command.type', ('SET_BINDING', 'SET_FOCUS', 'CHANGE_PHASE', 'SET_DISPOSITION'))
    fields = {'SET_BINDING': ('target_document_id', 'source_refs', 'scope'), 'SET_FOCUS': ('topic_ref',),
        'CHANGE_PHASE': ('phase_kind', 'closure_message', 'unresolved_refs'), 'SET_DISPOSITION': ('subject_ref', 'decision', 'description')}[kind]
    command = object_fields(command, 'discussion_command', ('type', *fields), ('type', *fields))
    resources = discussion_resources()
    def named(name, value):
        if name == 'PhaseKind':
            return strict_enum(value, 'phase_kind', ('DISCOVERY', 'SOLUTION', 'SPECIFICATION', 'REVIEW'))
        if name == 'Ref':
            from backend.app.shared.validation import raw_text
            return raw_text(value, 'discussion_command', 1, 100)
        try:
            return resources.validate(name, value)
        except ValueError:
            reject('discussion_command', 'INVALID_FORMAT', '讨论命令的字段结构不合法')
    if kind == 'SET_BINDING':
        if command['target_document_id'] is not None:
            strict_integer(command['target_document_id'], 'target_document_id')
        if type(command['source_refs']) is not list or len(command['source_refs']) > 1000:
            reject('source_refs', 'INVALID_FORMAT', '来源必须是有界数组')
        for source in command['source_refs']:
            named('SourceRef', source)
        if command['scope'] is not None:
            named('legacy_scope', command['scope'])
    elif kind == 'SET_FOCUS':
        named('Ref', command['topic_ref'])
    elif kind == 'CHANGE_PHASE':
        named('PhaseKind', command['phase_kind'])
        if command['closure_message'] is not None:
            command['closure_message'] = ordinary_text(command['closure_message'], 'closure_message', 1, 1000)
        if type(command['unresolved_refs']) is not list or len(command['unresolved_refs']) > 1000:
            reject('unresolved_refs', 'INVALID_FORMAT', '未决引用必须是有界数组')
        for ref in command['unresolved_refs']:
            named('Ref', ref)
        if len(set(command['unresolved_refs'])) != len(command['unresolved_refs']):
            reject('unresolved_refs', 'INVALID_FORMAT', '未决引用不能重复')
    else:
        named('Ref', command['subject_ref'])
        strict_enum(command['decision'], 'decision', ('DEFER', 'NOT_APPLICABLE', 'DECLINE_DRAFT'))
        command['description'] = ordinary_text(command['description'], 'description', 1, 1000)
    request = DiscussionCommandInput(requirement_id_input(data['requirement_id']),
        strict_integer(data['expected_discussion_version'], 'expected_discussion_version'), command,
        request_key(data['idempotency_key'], 'idempotency_key'))
    try:
        canonical_input(request.business_input()).encode('utf-8')
    except UnicodeEncodeError:
        reject('discussion_command', 'INVALID_FORMAT', '文本必须由有效Unicode码点组成')
    return request


def discussion_command_result(root):
    from .discussion import validate_discussion
    return {'requirement_id': root['id'], 'discussion_version': root['discussion_version'],
        'discussion': validate_discussion(root['discussion_state_json'])}


def _stored_time(value: object) -> None:
    if type(value) is not str or re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z', value) is None:
        raise ValueError('Invalid persisted UTC time')
    if utc_milliseconds(datetime.fromisoformat(value[:-1] + '+00:00')) != value:
        raise ValueError('Invalid persisted UTC time')


def requirement_read_model(row: Mapping[str, Any]) -> dict[str, Any]:
    data = {field: row[field] for field in READ_FIELDS}
    strict_integer(data['id'], 'id')
    if type(data['requirement_no']) is not str or re.fullmatch(r'REQ[0-9]{6}', data['requirement_no']) is None:
        raise ValueError('Invalid persisted requirement number')
    strict_enum(data['requirement_type'], 'requirement_type', REQUIREMENT_TYPES)
    strict_enum(data['status'], 'status', STATUSES)
    if title(data['title']) != data['title']:
        raise ValueError('Persisted title is not normalized')
    data['title'].encode('utf-8')
    for field in ('metadata_version', 'initial_message_id', 'discussion_version'):
        strict_integer(data[field], field)
    for field in ('created_at', 'updated_at'):
        _stored_time(data[field])
    for field in ('completed_at', 'closed_at', 'state_started_at'):
        if data[field] is not None:
            _stored_time(data[field])
    if (data['status'] == 'COMPLETED') != (data['completed_at'] is not None):
        raise ValueError('Invalid completion state')
    if (data['status'] == 'CLOSED') != (data['closed_at'] is not None):
        raise ValueError('Invalid closed state')
    if data['updated_at'] < data['created_at']:
        raise ValueError('Invalid requirement chronology')
    occupancy = {'IDLE': None, 'MANUAL_EDITING': 'MANUAL_DRAFT',
                 'GUIDE_ACTIVE': 'GUIDE_RUN', 'SUGGESTION_REVIEWING': 'SUGGESTION_BATCH'}
    strict_enum(data['document_work_state'], 'document_work_state', occupancy)
    expected = occupancy[data['document_work_state']]
    if data['active_operation_type'] != expected:
        raise ValueError('Invalid active operation type')
    if expected is None:
        if data['active_operation_id'] is not None or data['state_started_at'] is not None:
            raise ValueError('Invalid idle state')
    else:
        strict_integer(data['active_operation_id'], 'active_operation_id')
        if data['state_started_at'] is None:
            raise ValueError('Missing occupancy time')
    return data


def list_requirements_result(rows: list[Mapping[str, Any]], page: int, total: int) -> dict[str, Any]:
    items = []
    for row in rows:
        model = requirement_read_model(row)
        items.append({field: model[field] for field in LIST_FIELDS})
    return {'items': items, **page_metadata(page, total)}
