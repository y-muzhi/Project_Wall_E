/** V2 endpoint-scoped errors, independent of the document error contract. */
import { exact, positiveInteger, snapshotObject } from './client.ts';
import type { JsonObject, ApiErrorPolicy } from './client.ts';
import { time } from './decoding.ts';
import { registeredCommand } from './code-command-registry.ts';
export const ERROR_HTTP = Object.freeze({
  INVALID_INPUT: 422,
  CHECK_CONFIGURATION_INVALID: 422,
  BASIS_REF_INVALID: 422,
  DEFECT_SOURCE_MISMATCH: 422,
  BUDGET_NOT_INCREASED: 422,
  NOT_FOUND: 404,
  AUTHORIZATION_NOT_APPLICABLE: 403,
  PERMISSION_NOT_GRANTED: 403,
  DELIVERY_NOT_AUTHORIZED: 403,
  COMMAND_CLOSED: 409,
  VERSION_CONFLICT: 409,
  ACTIVE_TASK_EXISTS: 409,
  INVALID_STATE: 409,
  TASK_ENDED: 409,
  OPERATION_CONFLICT: 409,
  OPERATION_IN_PROGRESS: 409,
  RESOURCE_CONFLICT: 409,
  TEST_REPORT_NOT_ELIGIBLE: 409,
  TEST_SOURCE_MISMATCH: 409,
  TEST_ASSET_REVOKED: 409,
  VERIFICATION_STAGE_NOT_READY: 409,
  SOURCE_CHANGED: 409,
  SOURCE_BUSY: 409,
  SOURCE_UNSUPPORTED: 409,
  PRECONDITION_FAILED: 409,
  BASIS_NOT_CONFIRMED: 409,
  EXTERNAL_RESULT_UNKNOWN: 409,
  EXECUTION_NOT_STOPPED: 409,
  QUESTION_NOT_OPEN: 409,
  SESSION_NOT_CURRENT: 409,
  WRITER_ACTIVE: 409,
  CONTENT_NOT_READY: 409,
  CANDIDATE_NOT_CURRENT: 409,
  CHECKS_NOT_PASSED: 409,
  HANDOFF_CHECKS_NOT_PASSED: 409,
  DELIVERY_PLAN_STALE: 409,
  TARGET_CHANGED: 409,
  TARGET_CHECKED_OUT: 409,
  DELIVERY_WINDOW_REQUIRED: 409,
  REPOSITORY_UNSUPPORTED: 409,
  CONFIG_NOT_READY: 503,
  STORAGE_UNAVAILABLE: 503,
  INTERNAL_ERROR: 500,
} as const);
export const ERROR_MESSAGES = Object.freeze({
  INVALID_INPUT: '请求参数不合法',
  CHECK_CONFIGURATION_INVALID: '检查配置不符合要求',
  BASIS_REF_INVALID: '设计依据无效',
  DEFECT_SOURCE_MISMATCH: '缺陷来源不匹配',
  BUDGET_NOT_INCREASED: '新预算必须高于当前预算',
  NOT_FOUND: '资源不存在',
  AUTHORIZATION_NOT_APPLICABLE: '授权不适用于当前操作',
  PERMISSION_NOT_GRANTED: '没有操作权限',
  DELIVERY_NOT_AUTHORIZED: '尚未获得交付授权',
  COMMAND_CLOSED: '原请求已关闭，不再执行',
  VERSION_CONFLICT: '任务已更新，请重新核对',
  ACTIVE_TASK_EXISTS: '该文档已有活动代码任务',
  INVALID_STATE: '当前状态不允许此操作',
  TASK_ENDED: '任务已经结束',
  OPERATION_CONFLICT: '请求与已有操作冲突',
  OPERATION_IN_PROGRESS: '原操作仍在处理中',
  RESOURCE_CONFLICT: '资源与已有记录冲突',
  TEST_REPORT_NOT_ELIGIBLE: '测试报告不符合采用条件',
  TEST_SOURCE_MISMATCH: '测试来源不匹配',
  TEST_ASSET_REVOKED: '测试资产已撤销',
  VERIFICATION_STAGE_NOT_READY: '尚不具备本阶段检查条件',
  SOURCE_CHANGED: '来源已变化，请重新核对',
  SOURCE_BUSY: '来源正在使用',
  SOURCE_UNSUPPORTED: '不支持此来源',
  PRECONDITION_FAILED: '操作前提尚未满足',
  BASIS_NOT_CONFIRMED: '设计依据尚未确认',
  EXTERNAL_RESULT_UNKNOWN: '外部执行结果尚未核清',
  EXECUTION_NOT_STOPPED: '尚未确认执行已停止',
  QUESTION_NOT_OPEN: '该问题已不接受答复',
  SESSION_NOT_CURRENT: '会话已不是当前会话',
  WRITER_ACTIVE: '仍有活动写入者',
  CONTENT_NOT_READY: '固定内容暂时不可读取',
  CANDIDATE_NOT_CURRENT: '候选已不是当前候选',
  CHECKS_NOT_PASSED: '检查尚未通过',
  HANDOFF_CHECKS_NOT_PASSED: '角色交接检查尚未通过',
  DELIVERY_PLAN_STALE: '交付计划已失效',
  TARGET_CHANGED: '交付目标已变化',
  TARGET_CHECKED_OUT: '交付目标正在工作区使用',
  DELIVERY_WINDOW_REQUIRED: '需要重新确认交付窗口',
  REPOSITORY_UNSUPPORTED: '不支持此仓库',
  CONFIG_NOT_READY: '所需执行配置尚未就绪',
  STORAGE_UNAVAILABLE: '数据暂时无法访问，请稍后核对',
  INTERNAL_ERROR: '系统处理失败，请稍后核对',
} as const);

export type CodeErrorCode = keyof typeof ERROR_HTTP;
const INPUT_CODES = new Set<string>([
  'INVALID_INPUT',
  'CHECK_CONFIGURATION_INVALID',
  'BASIS_REF_INVALID',
  'DEFECT_SOURCE_MISMATCH',
  'BUDGET_NOT_INCREASED',
]);
const AUTH_CODES = new Set<string>([
  'AUTHORIZATION_NOT_APPLICABLE',
  'PERMISSION_NOT_GRANTED',
  'DELIVERY_NOT_AUTHORIZED',
]);
const CAPABILITIES = new Set([
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
]);
const ENTITY_KINDS = new Set([
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
]);
const CONFLICT_FIELDS = [
  'task_id',
  'current_state_version',
  'related_operation_id',
  'related_entity_kind',
  'related_entity_id',
] as const;
const nullableId = (value: unknown) => (value === null ? null : positiveInteger(value));

export function codeErrorDetails(code: CodeErrorCode, value: unknown): JsonObject | null {
  if (INPUT_CODES.has(code)) {
    const row = exact(value, ['field_errors']);
    if (!Array.isArray(row.field_errors) || row.field_errors.length === 0)
      throw new TypeError('Invalid input errors');
    for (const value of row.field_errors) {
      const field = exact(value, ['field', 'reason']);
      if (
        typeof field.field !== 'string' ||
        field.field.length > 256 ||
        !/^[A-Za-z_][A-Za-z0-9_.\[\]-]*$/.test(field.field) ||
        !['REQUIRED', 'TYPE', 'ENUM', 'RANGE', 'UNKNOWN_FIELD', 'DUPLICATE', 'RELATION'].includes(
          field.reason as string,
        )
      )
        throw new TypeError('Invalid input error');
    }
  } else if (AUTH_CODES.has(code)) {
    const row = exact(value, ['task_id', 'authorization_id']);
    nullableId(row.task_id);
    nullableId(row.authorization_id);
  } else if (code === 'COMMAND_CLOSED') {
    const row = exact(value, ['method', 'path', 'closed_at']);
    registeredCommand(row.method, row.path, '00000000-0000-4000-8000-000000000001');
    time(row.closed_at);
  } else if (code === 'CONFIG_NOT_READY' || code === 'STORAGE_UNAVAILABLE') {
    const row = exact(value, ['capability_codes']);
    if (
      !Array.isArray(row.capability_codes) ||
      row.capability_codes.length === 0 ||
      row.capability_codes.some((item) => typeof item !== 'string' || !CAPABILITIES.has(item)) ||
      new Set(row.capability_codes).size !== row.capability_codes.length
    )
      throw new TypeError('Invalid readiness details');
  } else if (ERROR_HTTP[code] === 409) {
    const row = exact(value, CONFLICT_FIELDS);
    for (const field of CONFLICT_FIELDS) {
      if (field !== 'related_entity_kind') nullableId(row[field]);
    }
    if (
      (row.related_entity_kind === null) !== (row.related_entity_id === null) ||
      (row.related_entity_kind !== null &&
        (typeof row.related_entity_kind !== 'string' || !ENTITY_KINDS.has(row.related_entity_kind)))
    )
      throw new TypeError('Invalid conflict identity');
  } else if ((code !== 'NOT_FOUND' && code !== 'INTERNAL_ERROR') || value !== null) {
    throw new TypeError('Unregistered error details');
  }
  return value === null ? null : snapshotObject(value);
}

export function codeErrorPolicy(allowedCodes: readonly CodeErrorCode[]): ApiErrorPolicy {
  const allowed = new Set(allowedCodes);
  if (
    allowed.size !== allowedCodes.length ||
    allowedCodes.some((code) => !Object.hasOwn(ERROR_HTTP, code))
  )
    throw new TypeError('Unregistered endpoint error policy');
  return Object.freeze({
    decode(code: string, message: string, details: unknown, status: number): JsonObject | null {
      if (
        !allowed.has(code as CodeErrorCode) ||
        ERROR_HTTP[code as CodeErrorCode] !== status ||
        ERROR_MESSAGES[code as CodeErrorCode] !== message
      )
        throw new TypeError('Unregistered endpoint error');
      return codeErrorDetails(code as CodeErrorCode, details);
    },
    mutationUnknown(_code: string, status: number): boolean {
      return status >= 500;
    },
  });
}
