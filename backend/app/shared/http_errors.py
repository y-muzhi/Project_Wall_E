"""API-COM-ERROR projection only; endpoint reachability remains explicit.

Never accepts a provider exception or an arbitrary root error message. This is
not an HTTP server or a substitute for the 36 endpoint adapters.
"""
from dataclasses import dataclass
from typing import Any, Collection
from uuid import UUID, uuid4

from .validation import MAX_SAFE_INTEGER, REASONS

ERRORS = {
    'INVALID_INPUT': (422, 'VALIDATION_FAILED', '请求参数不合法'),
    'NOT_FOUND': (404, 'NOT_FOUND', '资源不存在'),
    'MANUAL_DRAFT_NOT_FOUND': (404, 'MANUAL_DRAFT_NOT_FOUND', '人工草稿不存在'),
    'STATE_CONFLICT': (409, 'STATE_CONFLICT', '当前状态不允许此操作'),
    'WORK_STATE_CONFLICT': (409, 'WORK_STATE_CONFLICT', '当前已有其他操作占用正文'),
    'WORK_STATE_INCONSISTENT': (409, 'WORK_STATE_INCONSISTENT', '工作状态与活动对象不一致'),
    'CONTENT_VERSION_CONFLICT': (409, 'CONTENT_VERSION_CONFLICT', '内容已更新，请刷新后重试'),
    'TEMPLATE_INVALID': (422, 'TEMPLATE_INVALID', '模板不存在、不适用或结构不符合要求'),
    'DOCUMENT_INVALID': (422, 'DOCUMENT_INVALID', '正文与区块快照不合法'),
    'ANCHOR_INVALID': (422, 'ANCHOR_INVALID', '评论锚点无法唯一定位'),
    'SCOPE_INVALID': (422, 'SCOPE_INVALID', '指定范围无法确定或已失效'),
    'SOURCE_INVALID': (422, 'SOURCE_INVALID', '来源对象无效'),
    'PATCH_INVALID': (422, 'PATCH_INVALID', '修改建议结构不合法或不能组合应用'),
    'TARGET_STALE': (409, 'TARGET_STALE', '修改目标或原内容已变化'),
    'BATCH_PENDING': (422, 'BATCH_PENDING', '仍有未决定的建议'),
    'COMMENT_ORPHANED': (409, 'COMMENT_ORPHANED', '评论锚点已失效'),
    'CARD_ALREADY_ANSWERED': (409, 'CARD_ALREADY_ANSWERED', '该组卡片已提交回答'),
    'CARD_EXPIRED': (409, 'CARD_EXPIRED', '该组卡片已失效'),
    'CONFIG_INVALID': (503, 'CONFIG_INVALID', '所需协议或模板资源不可用'),
    'STORAGE_UNAVAILABLE': (503, 'STORAGE_UNAVAILABLE', '数据暂时无法访问，请稍后重试'),
    'CAPACITY_EXHAUSTED': (503, 'CAPACITY_EXHAUSTED', '编号或版本容量已用尽'),
    'IDEMPOTENCY_CONFLICT': (409, 'IDEMPOTENCY_CONFLICT', '同一幂等键对应了不同请求'),
    'REQUEST_IN_PROGRESS': (409, 'REQUEST_IN_PROGRESS', '同一请求仍在处理中'),
    'INTERNAL_ERROR': (500, 'INTERNAL_ERROR', '系统处理失败，请稍后重试'),
}


@dataclass(frozen=True)
class HttpError:
    status: int
    body: dict[str, Any]


def new_request_id() -> str:
    return str(uuid4())


def _request_id(value: str) -> str:
    if type(value) is not str:
        raise ValueError('Request context must provide a lowercase UUID v4')
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as error:
        raise ValueError('Request context must provide a lowercase UUID v4') from error
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError('Request context must provide a lowercase UUID v4')
    return value


def _details(code: str, value: object) -> dict[str, Any] | None:
    if code in ('PATCH_INVALID', 'TARGET_STALE') and value is not None:
        if type(value) is not dict or set(value) != {'suggestion_errors'} or type(value['suggestion_errors']) is not list or not 1 <= len(value['suggestion_errors']) <= 100:
            raise ValueError('Invalid approved suggestion errors')
        projected = []
        for item in value['suggestion_errors']:
            if type(item) is not dict or set(item) != {'suggestion_id', 'code', 'message'} or type(item['suggestion_id']) is not int or not 1 <= item['suggestion_id'] <= MAX_SAFE_INTEGER or item['code'] not in ('PATCH_INVALID', 'TARGET_STALE') or item['message'] != ERRORS[item['code']][2]:
                raise ValueError('Suggestion errors require program-owned codes and safe messages')
            projected.append(dict(item))
        if len({item['suggestion_id'] for item in projected}) != len(projected): raise ValueError('Suggestion errors must have distinct identities')
        return {'suggestion_errors': projected}
    if code == 'INVALID_INPUT':
        if type(value) is not dict or set(value) != {'field_errors'}:
            raise ValueError('Invalid field error projection')
        errors = value['field_errors']
        if type(errors) is not list or not errors:
            raise ValueError('Nonempty field error list is required')
        projected = []
        for error in errors:
            if type(error) is not dict or set(error) != {'field', 'reason', 'message'}:
                raise ValueError('Invalid field error projection')
            if any(type(error[key]) is not str or not error[key] for key in error):
                raise ValueError('Nonempty strings required')
            if error['reason'] not in REASONS:
                raise ValueError('Unregistered validation reason')
            projected.append({'field': error['field'], 'reason': error['reason'], 'message': error['message']})
        return {'field_errors': projected}
    if code == 'CARD_ALREADY_ANSWERED':
        if type(value) is not dict or set(value) != {'response_message_id'}:
            raise ValueError('Existing response reference required')
        identity = value['response_message_id']
        if type(identity) is not int or not 1 <= identity <= MAX_SAFE_INTEGER:
            raise ValueError('Invalid response identity')
        return {'response_message_id': identity}
    if value is not None:
        raise ValueError('No details registered for this error')
    return None


def error_response(code: str, details: object, *, allowed_errors: Collection[str], request_id: str) -> HttpError:
    """Project only registered and reachable errors; malformed results become 500.

    request_id is owned by the request context, so logging and the envelope use
    the same value. A new request (including replay) must allocate a new context.
    """
    request_id = _request_id(request_id)
    if type(code) is not str or code not in ERRORS or code not in allowed_errors:
        code, details = 'INTERNAL_ERROR', None
    try:
        projected = _details(code, details)
    except ValueError:
        code, projected = 'INTERNAL_ERROR', None
    status, error_code, message = ERRORS[code]
    return HttpError(status, {'success': False, 'data': None, 'error': {'code': error_code, 'message': message, 'details': projected}, 'meta': {'request_id': request_id}})
