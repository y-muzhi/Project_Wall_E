"""APP-REQ-QUERY-C01/C02 inputs and exact read projections.

Stored values are checked, never normalized or repaired by a read. These checks
cover Requirement's own fields, not the cross-aggregate lifecycle guard.
"""
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Mapping, Any

from backend.app.shared.pagination import page_number, page_metadata
from backend.app.shared.command_execution import ExpectedCurrentInput, RequirementActionInput
from backend.app.shared.time import utc_milliseconds
from backend.app.shared.validation import (
    MISSING, keyword, object_fields, reject, strict_enum, strict_integer, title,
)

STATUSES = ('INITIALIZING', 'ACTIVE', 'COMPLETED')
REQUIREMENT_TYPES = ('NEW', 'CHANGE')
READ_FIELDS = (
    'id', 'requirement_no', 'requirement_type', 'initialization_mode', 'title',
    'template_key', 'template_version', 'status', 'document_work_state',
    'active_operation_type', 'active_operation_id', 'created_at', 'updated_at',
    'completed_at', 'state_started_at',
)
LIST_FIELDS = ('id', 'requirement_no', 'title', 'requirement_type', 'status', 'updated_at')


@dataclass(frozen=True)
class CreateRequirementInput:
    title: str
    requirement_type: str
    template_key: str
    template_version: str
    initial_idea: str
    initialization_mode: str
    idempotency_key: str

    def business_input(self) -> dict:
        return {field: getattr(self, field) for field in ('title', 'requirement_type', 'template_key', 'template_version', 'initial_idea', 'initialization_mode')}


def create_requirement_input(payload: object) -> CreateRequirementInput:
    from backend.app.shared.validation import initial_idea, raw_text
    from backend.app.infrastructure.idempotency import canonical_input, request_key
    fields = ('title', 'requirement_type', 'template_key', 'template_version', 'initial_idea', 'initialization_mode', 'idempotency_key')
    data = object_fields(payload, 'body', fields, fields)
    request = CreateRequirementInput(title(data['title']), strict_enum(data['requirement_type'], 'requirement_type', REQUIREMENT_TYPES),
        raw_text(data['template_key'], 'template_key', 1, 128), raw_text(data['template_version'], 'template_version', 1, 64),
        initial_idea(data['initial_idea']), strict_enum(data['initialization_mode'], 'initialization_mode', ('IDEATION', 'DESIGN')),
        request_key(data['idempotency_key'], 'idempotency_key'))
    for field, value in request.business_input().items():
        try:
            value.encode('utf-8')
        except UnicodeEncodeError:
            reject(field, 'INVALID_FORMAT', '文本必须由有效Unicode码点组成')
    canonical_input(request.business_input())
    return request


def create_requirement_result(root: Mapping[str, Any], current_document_id: int, guide_run_id: int) -> dict:
    value = requirement_read_model(root)
    strict_integer(current_document_id, 'current_document_id')
    strict_integer(guide_run_id, 'guide_run_id')
    if value['status'] != 'INITIALIZING' or value['document_work_state'] != 'GUIDE_ACTIVE' or value['active_operation_type'] != 'GUIDE_RUN' or value['active_operation_id'] != guide_run_id:
        raise ValueError('Created resource must reference its accepted initialization run')
    return {'requirement': value, 'current_document_id': current_document_id, 'guide_run_id': guide_run_id}


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
    changes: dict[str, str]


def update_requirement_input(payload: object) -> UpdateRequirementInput:
    data = object_fields(payload, 'body', ('requirement_id', 'title'), ('requirement_id', 'title'))
    identity = requirement_id_input(data['requirement_id'])
    changes = {}
    if 'title' in data:
        changes['title'] = title(data['title'])
        try:
            changes['title'].encode('utf-8')
        except UnicodeEncodeError:
            reject('title', 'INVALID_FORMAT', '文本必须由有效Unicode码点组成')
    return UpdateRequirementInput(identity, changes)


def update_requirement_result(row: Mapping[str, Any]) -> dict[str, Any]:
    return requirement_read_model(row)


def complete_initialization_input(payload: object) -> ExpectedCurrentInput:
    fields = ('requirement_id', 'expected_content_version', 'idempotency_key')
    return ExpectedCurrentInput.from_fields(object_fields(payload, 'body', fields, fields))


def complete_initialization_result(root: Mapping[str, Any], revision: Mapping[str, Any], document: Mapping[str, Any]) -> dict:
    from backend.app.revisions.contracts import revision_summary
    return {'requirement': requirement_read_model(root), 'baseline_revision': revision_summary(revision),
            'current_document': {'id': strict_integer(document['id'], 'id'),
                                 'content_version': strict_integer(document['content_version'], 'content_version')}}


def complete_requirement_input(payload: object) -> ExpectedCurrentInput:
    fields = ('requirement_id', 'expected_content_version', 'idempotency_key')
    return ExpectedCurrentInput.from_fields(object_fields(payload, 'body', fields, fields))


def complete_requirement_result(row: Mapping[str, Any]) -> dict:
    return requirement_read_model(row)


def reactivate_requirement_input(payload: object) -> RequirementActionInput:
    fields = ('requirement_id', 'idempotency_key')
    return RequirementActionInput.from_fields(object_fields(payload, 'body', fields, fields))


def reactivate_requirement_result(row: Mapping[str, Any]) -> dict:
    return requirement_read_model(row)


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
    strict_enum(data['initialization_mode'], 'initialization_mode', ('IDEATION', 'DESIGN'))
    strict_enum(data['status'], 'status', STATUSES)
    if title(data['title']) != data['title']:
        raise ValueError('Persisted title is not normalized')
    data['title'].encode('utf-8')
    for field, maximum in (('template_key', 128), ('template_version', 64)):
        if type(data[field]) is not str or not 1 <= len(data[field]) <= maximum:
            raise ValueError('Invalid persisted template reference')
        data[field].encode('utf-8')
    for field in ('created_at', 'updated_at'):
        _stored_time(data[field])
    for field in ('completed_at', 'state_started_at'):
        if data[field] is not None:
            _stored_time(data[field])
    if (data['status'] == 'COMPLETED') != (data['completed_at'] is not None):
        raise ValueError('Invalid completion state')
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
