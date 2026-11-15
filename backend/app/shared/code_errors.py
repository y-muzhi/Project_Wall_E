"""V2 error facts for the existing HTTP envelope, scoped away from V1.5 contracts."""

from datetime import datetime
import re

from backend.app.code_tasks.error_codes import ERROR_HTTP
from .validation import MAX_SAFE_INTEGER

INPUT_CODES = frozenset(
    {
        'INVALID_INPUT',
        'CHECK_CONFIGURATION_INVALID',
        'BASIS_REF_INVALID',
        'DEFECT_SOURCE_MISMATCH',
        'BUDGET_NOT_INCREASED',
    }
)
AUTH_CODES = frozenset(
    {
        'AUTHORIZATION_NOT_APPLICABLE',
        'PERMISSION_NOT_GRANTED',
        'DELIVERY_NOT_AUTHORIZED',
    }
)
READINESS_CODES = frozenset({'CONFIG_NOT_READY', 'STORAGE_UNAVAILABLE'})
CONFLICT_FIELDS = frozenset(
    {
        'task_id',
        'current_state_version',
        'related_operation_id',
        'related_entity_kind',
        'related_entity_id',
    }
)
ENTITY_KINDS = frozenset(
    {
        'TASK',
        'REVISION',
        'SNAPSHOT',
        'CANDIDATE',
        'VERIFICATION',
        'PLAN',
        'QUESTION',
        'SESSION',
        'REPOSITORY',
        'AUTHORIZATION',
    }
)
CAPABILITIES = frozenset(
    {
        'Q20-OC',
        'Q20-CONFIG',
        'Q20-WINDOWS',
        'Q20-MODEL',
        'Q20-CONTENT',
        'Q20-GIT',
        'Q20-CHECKS',
        'Q20-DB',
        'Q20-TEST',
        'Q20-FE',
        'DATABASE',
        'CONTENT_STORE',
        'RUNTIME',
    }
)
MESSAGES = {
    'INVALID_INPUT': '请求参数不合法',
    'CHECK_CONFIGURATION_INVALID': '检查配置不符合要求',
    'BASIS_REF_INVALID': '设计依据无效',
    'DEFECT_SOURCE_MISMATCH': '缺陷来源不匹配',
    'BUDGET_NOT_INCREASED': '新预算必须高于当前预算',
    'NOT_FOUND': '资源不存在',
    'AUTHORIZATION_NOT_APPLICABLE': '授权不适用于当前操作',
    'PERMISSION_NOT_GRANTED': '没有操作权限',
    'DELIVERY_NOT_AUTHORIZED': '尚未获得交付授权',
    'COMMAND_CLOSED': '原请求已关闭，不再执行',
    'VERSION_CONFLICT': '任务已更新，请重新核对',
    'ACTIVE_TASK_EXISTS': '该文档已有活动代码任务',
    'INVALID_STATE': '当前状态不允许此操作',
    'TASK_ENDED': '任务已经结束',
    'OPERATION_CONFLICT': '请求与已有操作冲突',
    'OPERATION_IN_PROGRESS': '原操作仍在处理中',
    'RESOURCE_CONFLICT': '资源与已有记录冲突',
    'TEST_REPORT_NOT_ELIGIBLE': '测试报告不符合采用条件',
    'TEST_SOURCE_MISMATCH': '测试来源不匹配',
    'TEST_ASSET_REVOKED': '测试资产已撤销',
    'VERIFICATION_STAGE_NOT_READY': '尚不具备本阶段检查条件',
    'SOURCE_CHANGED': '来源已变化，请重新核对',
    'SOURCE_BUSY': '来源正在使用',
    'SOURCE_UNSUPPORTED': '不支持此来源',
    'PRECONDITION_FAILED': '操作前提尚未满足',
    'BASIS_NOT_CONFIRMED': '设计依据尚未确认',
    'EXTERNAL_RESULT_UNKNOWN': '外部执行结果尚未核清',
    'EXECUTION_NOT_STOPPED': '尚未确认执行已停止',
    'QUESTION_NOT_OPEN': '该问题已不接受答复',
    'SESSION_NOT_CURRENT': '会话已不是当前会话',
    'WRITER_ACTIVE': '仍有活动写入者',
    'CONTENT_NOT_READY': '固定内容暂时不可读取',
    'CANDIDATE_NOT_CURRENT': '候选已不是当前候选',
    'CHECKS_NOT_PASSED': '检查尚未通过',
    'HANDOFF_CHECKS_NOT_PASSED': '角色交接检查尚未通过',
    'DELIVERY_PLAN_STALE': '交付计划已失效',
    'TARGET_CHANGED': '交付目标已变化',
    'TARGET_CHECKED_OUT': '交付目标正在工作区使用',
    'DELIVERY_WINDOW_REQUIRED': '需要重新确认交付窗口',
    'REPOSITORY_UNSUPPORTED': '不支持此仓库',
    'CONFIG_NOT_READY': '所需执行配置尚未就绪',
    'STORAGE_UNAVAILABLE': '数据暂时无法访问，请稍后核对',
    'INTERNAL_ERROR': '系统处理失败，请稍后核对',
}


def empty_conflict():
    return dict.fromkeys(sorted(CONFLICT_FIELDS))


def _object(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError('Error details differ from the registered contract')
    return value


def _nullable_id(value):
    if value is not None and (type(value) is not int or not 1 <= value <= MAX_SAFE_INTEGER):
        raise ValueError('Invalid safe error identity')


def validate_details(code, value):
    if code in INPUT_CODES:
        fields = _object(value, {'field_errors'})['field_errors']
        if type(fields) is not list or not fields:
            raise ValueError('Input errors must be nonempty')
        for field in fields:
            _object(field, {'field', 'reason'})
            if (
                type(field['field']) is not str
                or len(field['field']) > 256
                or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.\[\]-]*', field['field']) is None
                or type(field['reason']) is not str
                or field['reason']
                not in (
                    'REQUIRED',
                    'TYPE',
                    'ENUM',
                    'RANGE',
                    'UNKNOWN_FIELD',
                    'DUPLICATE',
                    'RELATION',
                )
            ):
                raise ValueError('Invalid input error field or reason')
    elif code in AUTH_CODES:
        _object(value, {'task_id', 'authorization_id'})
        for identity in value.values():
            _nullable_id(identity)
    elif code == 'COMMAND_CLOSED':
        _object(value, {'method', 'path', 'closed_at'})
        from backend.app.code_tasks.command_registry import registered_command

        registered_command(value['method'], value['path'], '00000000-0000-4000-8000-000000000001')
        time = value['closed_at']
        if (
            type(time) is not str
            or re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z', time) is None
        ):
            raise ValueError('Invalid closed time')
        datetime.fromisoformat(time.replace('Z', '+00:00'))
    elif code in READINESS_CODES:
        values = _object(value, {'capability_codes'})['capability_codes']
        if (
            type(values) is not list
            or not values
            or any(type(item) is not str or item not in CAPABILITIES for item in values)
            or len(set(values)) != len(values)
        ):
            raise ValueError('Invalid readiness codes')
    elif ERROR_HTTP.get(code) == 409:
        _object(value, CONFLICT_FIELDS)
        for field in CONFLICT_FIELDS - {'related_entity_kind'}:
            _nullable_id(value[field])
        if value['related_entity_kind'] is not None and (
            type(value['related_entity_kind']) is not str
            or value['related_entity_kind'] not in ENTITY_KINDS
        ):
            raise ValueError('Unregistered related entity')
        if (value['related_entity_kind'] is None) != (value['related_entity_id'] is None):
            raise ValueError('Related entity kind and identity must appear together')
    elif code not in ('NOT_FOUND', 'INTERNAL_ERROR') or value is not None:
        raise ValueError('No details registered for this error')
    return value


def error_fact(code, details):
    """Raise on corrupt stored facts; callers decide whether to map failures to 500."""
    if type(code) is not str or code not in ERROR_HTTP:
        raise ValueError('Unregistered V2 error')
    return ERROR_HTTP[code], code, MESSAGES[code], validate_details(code, details)


def validation_details(error):
    reasons = {
        'REQUIRED': 'REQUIRED',
        'INVALID_TYPE': 'TYPE',
        'INVALID_FORMAT': 'TYPE',
        'INVALID_ENUM': 'ENUM',
        'TOO_SHORT': 'RANGE',
        'TOO_LONG': 'RANGE',
        'OUT_OF_RANGE': 'RANGE',
        'UNKNOWN_FIELD': 'UNKNOWN_FIELD',
        'DUPLICATE_PARAMETER': 'DUPLICATE',
    }
    fields = []
    for item in error.errors:
        field = item.field
        if item.reason == 'UNKNOWN_FIELD':
            field = 'body' if field.startswith('body.') else 'query'
        elif len(field) > 256 or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.\[\]-]*', field) is None:
            field = 'request'
        fields.append({'field': field, 'reason': reasons[item.reason]})
    return {'field_errors': fields}
