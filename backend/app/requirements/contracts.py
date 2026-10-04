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
    data = object_fields(payload, 'body', ('requirement_id', 'title', 'initialization_mode'), ('requirement_id',))
    identity = requirement_id_input(data['requirement_id'])
    if 'title' not in data and 'initialization_mode' not in data:
        reject('body', 'REQUIRED', '至少提供title或initialization_mode一项')
    changes = {}
    if 'title' in data:
        changes['title'] = title(data['title'])
        try:
            changes['title'].encode('utf-8')
        except UnicodeEncodeError:
            reject('title', 'INVALID_FORMAT', '文本必须由有效Unicode码点组成')
    if 'initialization_mode' in data:
        changes['initialization_mode'] = strict_enum(data['initialization_mode'], 'initialization_mode', ('IDEATION', 'DESIGN'))
    return UpdateRequirementInput(identity, changes)


def update_requirement_result(row: Mapping[str, Any]) -> dict[str, Any]:
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
