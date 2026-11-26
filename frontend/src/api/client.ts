/** API-COM transport and immutable user actions; pages own business refresh. */
import { exact, object, positiveInteger } from './wire-shape.ts';
import {
  compareResponseScope,
  EnvironmentEntryError,
  environmentHeaders,
  sameEnvironmentScope,
  type BoundEnvironment,
  type EnvironmentScope,
} from './environment-binding.ts';
import type { EnvironmentConnection } from './environment-connection.ts';
import {
  allowsOrdinaryRequest,
  allowsRecoveryRequest,
  ORDINARY_OPERATION_UNAVAILABLE,
  RECOVERY_READ_ONLY,
} from './environment-actions.ts';

export { exact, object, positiveInteger } from './wire-shape.ts';
export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type JsonObject = { [key: string]: Json };
export type PagePagination = { page: number; page_size: 20; total: number; total_pages: number };
export type CursorPagination = { page_size: 20; next_cursor: number | null; has_more: boolean };
export type FormationCursorPagination = Readonly<{
  page_size: number;
  next_cursor: string | null;
  has_more: boolean;
}>;
type LegacyPagination = PagePagination | CursorPagination;
type ApiPagination = LegacyPagination | FormationCursorPagination;
export type ApiMeta<P extends ApiPagination = LegacyPagination> = {
  request_id: string;
  pagination?: P;
};
export type ApiSuccess<T, P extends ApiPagination = LegacyPagination> = {
  data: T;
  meta: ApiMeta<P>;
  status: number;
};
export type ApiErrorPolicy = Readonly<{
  decode: (code: string, message: string, details: unknown, status: number) => JsonObject | null;
  mutationUnknown: (code: string, status: number) => boolean;
}>;
function frozenErrorPolicy(policy: ApiErrorPolicy | undefined): ApiErrorPolicy | undefined {
  if (policy === undefined) return undefined;
  if (typeof policy.decode !== 'function' || typeof policy.mutationUnknown !== 'function')
    throw new TypeError('Invalid native error policy');
  return Object.freeze({ decode: policy.decode, mutationUnknown: policy.mutationUnknown });
}
type Decoder<T> = (value: unknown) => T;
type CommandMethod = 'POST' | 'PATCH' | 'PUT' | 'DELETE';
/** Per HTTP exchange, including the response body; not an AI execution limit. */
export const API_REQUEST_TIMEOUT_MS = 30_000;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const ERROR_STATUS: Readonly<Record<string, number>> = {
  VALIDATION_FAILED: 422,
  NOT_FOUND: 404,
  MANUAL_DRAFT_NOT_FOUND: 404,
  STATE_CONFLICT: 409,
  WORK_STATE_CONFLICT: 409,
  WORK_STATE_INCONSISTENT: 409,
  CONTENT_VERSION_CONFLICT: 409,
  METADATA_VERSION_CONFLICT: 409,
  DISCUSSION_VERSION_CONFLICT: 409,
  SOURCE_VERSION_CONFLICT: 409,
  TEMPLATE_INVALID: 422,
  DOCUMENT_INVALID: 422,
  ANCHOR_INVALID: 422,
  SCOPE_INVALID: 422,
  SOURCE_INVALID: 422,
  PATCH_INVALID: 422,
  TARGET_STALE: 409,
  BATCH_PENDING: 422,
  COMMENT_ORPHANED: 409,
  CARD_ALREADY_ANSWERED: 409,
  CARD_EXPIRED: 409,
  CONFIG_INVALID: 503,
  STORAGE_UNAVAILABLE: 503,
  CAPACITY_EXHAUSTED: 503,
  IDEMPOTENCY_CONFLICT: 409,
  REQUEST_IN_PROGRESS: 409,
  INTERNAL_ERROR: 500,
};

const ENVIRONMENT_ERRORS: Readonly<Record<string, readonly [number, string]>> = {
  ENVIRONMENT_ACCESS_DENIED: [403, '当前访问身份无权执行此操作'],
  REQUEST_SOURCE_REJECTED: [403, '请求来源不符合当前环境要求'],
  ENVIRONMENT_BINDING_INVALID: [400, '环境绑定信息缺失或不合法'],
  ENVIRONMENT_MISMATCH: [409, '当前入口与请求所属环境不一致'],
  DATA_GENERATION_MISMATCH: [409, '数据已更换，请先核对原操作和草稿'],
  BINDING_PROTOCOL_MISMATCH: [409, '客户端与服务的环境协议不兼容'],
  ENVIRONMENT_CAPABILITY_DISABLED: [403, '此环境未启用该操作所需能力'],
  RECOVERY_READ_ONLY: [403, RECOVERY_READ_ONLY],
  ENVIRONMENT_CAPABILITY_UNAVAILABLE: [503, '此环境所需能力尚未就绪'],
  ENVIRONMENT_NOT_READY: [503, '环境尚未就绪，请稍后查看状态'],
  ENVIRONMENT_MAINTENANCE: [503, '当前环境维护中，此次新操作未受理'],
  ENVIRONMENT_CONTROL_UNVERIFIED: [503, '环境控制状态尚未核实'],
};
const BINDING_REJECTIONS = new Set([
  'ENVIRONMENT_MISMATCH',
  'DATA_GENERATION_MISMATCH',
  'BINDING_PROTOCOL_MISMATCH',
]);

export class ApiUnknown extends Error {
  readonly code = 'RESULT_UNKNOWN';
  readonly mutation: boolean;
  constructor(mutation: boolean) {
    super(mutation ? '本次操作结果待核实，已保留原请求' : '暂时无法读取数据，请重试');
    this.mutation = mutation;
  }
}
export class ApiRejected extends Error {
  readonly code: string;
  readonly details: JsonObject | null;
  readonly request_id: string | null;
  readonly status: number | null;
  constructor(
    code: string,
    message: string,
    details: JsonObject | null,
    request_id: string | null,
    status: number | null,
  ) {
    super(message);
    this.code = code;
    this.details = details;
    this.request_id = request_id;
    this.status = status;
  }
}

/** Local refusal before a transport was invoked. No HTTP receipt exists. */
export class ApiNotSent extends ApiRejected {
  constructor(message: string, code = 'ENVIRONMENT_LOCAL_PAUSE') {
    super(code, message, null, null, null);
  }
}

function nonnegative(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0)
    throw new TypeError('Invalid count');
  return value;
}
function jsonValue(value: unknown, seen = new Set<unknown>()): asserts value is Json {
  if (value === null || typeof value === 'boolean') return;
  if (typeof value === 'string') {
    for (const character of value)
      if (
        character.length === 1 &&
        character.charCodeAt(0) >= 0xd800 &&
        character.charCodeAt(0) <= 0xdfff
      )
        throw new TypeError('Invalid Unicode');
    return;
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value) || (Number.isInteger(value) && !Number.isSafeInteger(value)))
      throw new TypeError('Invalid JSON number');
    return;
  }
  if (typeof value !== 'object' || seen.has(value)) throw new TypeError('Invalid JSON value');
  seen.add(value);
  if (Array.isArray(value)) {
    for (const item of value) jsonValue(item, seen);
  } else {
    for (const [key, item] of Object.entries(object(value))) {
      jsonValue(key);
      jsonValue(item, seen);
    }
  }
  seen.delete(value);
}
function path(value: string): string {
  if (!/^\/api\/v1\/[a-z0-9-]+(?:\/[a-z0-9-]+)*$/.test(value))
    throw new TypeError('Invalid same-origin API path');
  return value;
}
function snapshot(value: unknown, seen = new Set<unknown>()): Json {
  if (value === null || typeof value !== 'object') {
    jsonValue(value);
    return value;
  }
  if (seen.has(value)) throw new TypeError('Cyclic JSON');
  seen.add(value);
  let result: Json;
  if (Array.isArray(value)) result = Array.from(value, (item) => snapshot(item, seen));
  else
    result = Object.fromEntries(
      Object.entries(object(value)).map(([key, item]) => {
        jsonValue(key);
        return [key, snapshot(item, seen)];
      }),
    );
  seen.delete(value);
  return result;
}
/** Capture once before a business binding closes over response expectations. */
export function stableJson(value: unknown): string | undefined {
  return JSON.stringify(value, (_key, item: unknown) => {
    if (typeof item !== 'object' || item === null || Array.isArray(item)) return item;
    const entries = Object.entries(item);
    entries.sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0));
    return Object.fromEntries(entries);
  });
}
export function snapshotObject(value: unknown): JsonObject {
  object(value);
  const copied = snapshot(value) as JsonObject;
  function freeze(item: Json): void {
    if (item !== null && typeof item === 'object') {
      for (const child of Object.values(item)) freeze(child);
      Object.freeze(item);
    }
  }
  freeze(copied);
  return copied;
}
function errorDetails(code: string, value: unknown): JsonObject | null {
  if (
    [
      'METADATA_VERSION_CONFLICT',
      'DISCUSSION_VERSION_CONFLICT',
      'SOURCE_VERSION_CONFLICT',
    ].includes(code) &&
    value !== null
  ) {
    const result = exact(value, [
      'expected_version',
      'actual_version',
      'resource_kind',
      'resource_id',
    ]);
    for (const field of ['expected_version', 'actual_version', 'resource_id'])
      positiveInteger(result[field]);
    if (
      !['Requirement', 'RequirementDocument', 'Discussion', 'Revision'].includes(
        result.resource_kind as string,
      )
    )
      throw new TypeError('Invalid version conflict target');
    return result as JsonObject;
  }
  if (code === 'CARD_ALREADY_ANSWERED') {
    const result = exact(value, ['response_message_id']);
    positiveInteger(result.response_message_id);
    return result as JsonObject;
  }
  if (code === 'VALIDATION_FAILED') {
    const result = exact(value, ['field_errors']);
    if (!Array.isArray(result.field_errors) || result.field_errors.length === 0)
      throw new TypeError('Missing field errors');
    const reasons = new Set([
      'REQUIRED',
      'INVALID_TYPE',
      'INVALID_FORMAT',
      'INVALID_ENUM',
      'TOO_SHORT',
      'TOO_LONG',
      'OUT_OF_RANGE',
      'UNKNOWN_FIELD',
      'DUPLICATE_PARAMETER',
    ]);
    for (const value of result.field_errors) {
      const item = exact(value, ['field', 'reason', 'message']);
      if (
        Object.values(item).some((value) => typeof value !== 'string' || value.length === 0) ||
        !reasons.has(item.reason as string)
      )
        throw new TypeError('Invalid field error');
    }
    return result as JsonObject;
  }
  if ((code === 'PATCH_INVALID' || code === 'TARGET_STALE') && value !== null) {
    const result = exact(value, ['suggestion_errors']);
    if (
      !Array.isArray(result.suggestion_errors) ||
      result.suggestion_errors.length < 1 ||
      result.suggestion_errors.length > 100
    )
      throw new TypeError('Invalid suggestion errors');
    const ids = new Set<number>();
    for (const value of result.suggestion_errors) {
      const item = exact(value, ['suggestion_id', 'code', 'message']),
        identity = positiveInteger(item.suggestion_id);
      if (
        ids.has(identity) ||
        !['PATCH_INVALID', 'TARGET_STALE'].includes(item.code as string) ||
        item.message !==
          (item.code === 'PATCH_INVALID'
            ? '修改建议结构不合法或不能组合应用'
            : '修改目标或原内容已变化')
      )
        throw new TypeError('Invalid suggestion error');
      ids.add(identity);
    }
    return result as JsonObject;
  }
  if (value !== null) throw new TypeError('Unregistered error details');
  return null;
}
export function documentFailureDetails(
  code: string,
  details: unknown,
  status: number,
): JsonObject | null {
  if (!Object.hasOwn(ERROR_STATUS, code) || ERROR_STATUS[code] !== status)
    throw new TypeError('Unregistered error');
  return errorDetails(code, details);
}
function meta(value: unknown): ApiMeta {
  const row = object(value);
  exact(row, Object.hasOwn(row, 'pagination') ? ['request_id', 'pagination'] : ['request_id']);
  if (typeof row.request_id !== 'string' || !UUID.test(row.request_id))
    throw new TypeError('Invalid request ID');
  if (!Object.hasOwn(row, 'pagination')) return { request_id: row.request_id };
  const item = object(row.pagination);
  if (item.page_size !== 20) throw new TypeError('Invalid page size');
  let pagination: PagePagination | CursorPagination;
  if (Object.hasOwn(item, 'page')) {
    exact(item, ['page', 'page_size', 'total', 'total_pages']);
    const page = positiveInteger(item.page),
      total = nonnegative(item.total),
      total_pages = nonnegative(item.total_pages);
    if (page > 100000 || total_pages !== Math.ceil(total / 20))
      throw new TypeError('Inconsistent pagination');
    pagination = { page, page_size: 20, total, total_pages };
  } else {
    exact(item, ['page_size', 'next_cursor', 'has_more']);
    const next_cursor = item.next_cursor === null ? null : positiveInteger(item.next_cursor);
    if (typeof item.has_more !== 'boolean' || item.has_more !== (next_cursor !== null))
      throw new TypeError('Invalid cursor pagination');
    pagination = { page_size: 20, next_cursor, has_more: item.has_more };
  }
  return { request_id: row.request_id, pagination };
}

function formationMeta(value: unknown): ApiMeta<FormationCursorPagination> {
  const row = object(value);
  exact(row, Object.hasOwn(row, 'pagination') ? ['request_id', 'pagination'] : ['request_id']);
  if (typeof row.request_id !== 'string' || !UUID.test(row.request_id))
    throw new TypeError('Invalid request ID');
  if (!Object.hasOwn(row, 'pagination')) return { request_id: row.request_id };
  const item = exact(row.pagination, ['page_size', 'next_cursor', 'has_more']);
  const page_size = positiveInteger(item.page_size);
  if (
    page_size > 100 ||
    typeof item.has_more !== 'boolean' ||
    item.has_more !== (item.next_cursor !== null) ||
    (item.next_cursor !== null &&
      (typeof item.next_cursor !== 'string' ||
        item.next_cursor.length < 1 ||
        item.next_cursor.length > 4096))
  )
    throw new TypeError('Invalid formation pagination');
  return {
    request_id: row.request_id,
    pagination: {
      page_size,
      next_cursor: item.next_cursor as string | null,
      has_more: item.has_more,
    },
  };
}
function formationPath(value: string): string {
  const base = /^\/api\/v1\/requirements\/[1-9][0-9]*\/documents\/[1-9][0-9]*\/formation\//;
  if (!base.test(value)) throw new TypeError('Invalid formation path');
  const tail = value.replace(base, '');
  const number = '[1-9][0-9]*';
  const allowed = [
    '(steps|branches|issues|artifacts|proposals)',
    'steps/s' + number,
    'steps/s' + number + '/relations',
    'artifacts/a' + number + '(/(ranges|lineage))?',
    'events',
    'events/' + number + '/changes(/' + number + '/members)?',
    'events/' + number + '/closure-items',
    'events/' +
      number +
      '/closure-items/(RESULT|ISSUE|BRANCH)/(s' +
      number +
      '\\.o' +
      number +
      '|i' +
      number +
      '|b' +
      number +
      ')/evidence',
  ];
  if (!allowed.some((pattern) => new RegExp('^' + pattern + '$').test(tail)))
    throw new TypeError('Unregistered formation read');
  return value;
}
function noPagination(value: unknown): ApiMeta {
  const result = meta(value);
  if (result.pagination !== undefined) throw new TypeError('Unexpected pagination');
  return result;
}

/** Opaque command handle. Snapshot/string/key remain private and never mutate. */
export type PreparedCommand = Readonly<{ kind: 'WALLE_COMMAND' }>;
/** Serializable bytes only; native decoders/policies never come from storage. */
export type FrozenRequest = Readonly<{
  method: CommandMethod;
  path: string;
  body: string | null;
  key: string | null;
  binding_scope?: EnvironmentScope;
}>;
export type CommandOptions = Readonly<{
  idempotent: boolean;
  error_policy?: ApiErrorPolicy;
  success_status: 200 | 201 | 202 | readonly (200 | 201 | 202)[];
}>;
type FrozenCommand = {
  method: CommandMethod;
  path: string;
  body: string | null;
  key: string | null;
  success_status: readonly number[];
  error_policy: ApiErrorPolicy | undefined;
};

export class ApiClient {
  private readonly commands = new WeakMap<PreparedCommand, FrozenCommand>();
  private readonly send: typeof fetch;
  private readonly uuid: () => string;
  private readonly environment: BoundEnvironment | undefined;
  readonly environmentConnection: EnvironmentConnection | undefined;
  private readonly observedRuns = new Set<string>();
  constructor(
    send: typeof fetch = globalThis.fetch.bind(globalThis),
    uuid: () => string = () => globalThis.crypto.randomUUID(),
    environment?: BoundEnvironment,
    environmentConnection?: EnvironmentConnection,
  ) {
    if (
      environmentConnection &&
      (!environment ||
        !sameEnvironmentScope(
          environmentConnection.getSnapshot().environment.scope,
          environment.scope,
        ))
    )
      throw new TypeError('Transport and connection scopes differ');
    this.environmentConnection = environmentConnection;
    this.send = send;
    this.uuid = uuid;
    this.environment = environment
      ? Object.freeze({ ...environment, scope: Object.freeze({ ...environment.scope }) })
      : undefined;
    if (environment) this.observedRuns.add(environment.runId);
  }

  get environmentScope(): EnvironmentScope | undefined {
    return this.environment?.scope;
  }

  assertCanDispatch(): void {
    this.assertConnection(true);
  }

  private assertConnection(mutation: boolean): void {
    const reason = this.environmentConnection?.blockReason(mutation);
    if (reason) throw new ApiNotSent(reason);
  }

  prepare(
    method: CommandMethod,
    target: string,
    body: JsonObject | null,
    options: CommandOptions,
  ): PreparedCommand {
    if (body !== null) object(body);
    const frozenBody = body === null ? null : JSON.stringify(snapshot(body));
    return this.remember(
      method,
      target,
      frozenBody,
      options.idempotent ? this.uuid() : null,
      options,
    );
  }

  exportPrepared(action: PreparedCommand): FrozenRequest {
    const command = this.commands.get(action);
    if (command === undefined) throw new TypeError('Command must belong to this client');
    return Object.freeze({
      method: command.method,
      path: command.path,
      body: command.body,
      key: command.key,
      ...(this.environment ? { binding_scope: this.environment.scope } : {}),
    });
  }

  /** Native caller must additionally verify origin, registration and input DTO.
   * Restored bodies must be exactly bytes our own prepare could have emitted.
   */
  restorePrepared(value: FrozenRequest, options: CommandOptions): PreparedCommand {
    const fields = ['method', 'path', 'body', 'key'];
    if (this.environment) fields.push('binding_scope');
    const row = exact(value, fields);
    if (this.environment && !sameEnvironmentScope(row.binding_scope, this.environment.scope))
      throw new TypeError('Frozen request belongs to another environment');
    if (
      typeof row.method !== 'string' ||
      typeof row.path !== 'string' ||
      (row.key !== null && typeof row.key !== 'string') ||
      (row.body !== null && typeof row.body !== 'string')
    )
      throw new TypeError('Invalid frozen request');
    if (row.body !== null) {
      const parsed: unknown = JSON.parse(row.body);
      if (JSON.stringify(snapshotObject(parsed)) !== row.body)
        throw new TypeError('Frozen body differs from original serialization');
    }
    return this.remember(row.method as CommandMethod, row.path, row.body, row.key, options);
  }

  private remember(
    method: CommandMethod,
    target: string,
    body: string | null,
    key: string | null,
    options: CommandOptions,
  ): PreparedCommand {
    if (!['POST', 'PATCH', 'PUT', 'DELETE'].includes(method))
      throw new TypeError('Invalid command method');
    const location = path(target);
    const statuses =
      typeof options.success_status === 'number'
        ? [options.success_status]
        : [...options.success_status];
    if (
      typeof options.idempotent !== 'boolean' ||
      options.idempotent !== (key !== null) ||
      statuses.length === 0 ||
      new Set(statuses).size !== statuses.length ||
      statuses.some((status) => ![200, 201, 202].includes(status))
    )
      throw new TypeError('Invalid command policy');
    if (key !== null && !UUID.test(key)) throw new TypeError('Invalid action key');
    const action = Object.freeze({ kind: 'WALLE_COMMAND' as const });
    this.commands.set(action, {
      method,
      path: location,
      body,
      key,
      success_status: Object.freeze(statuses),
      error_policy: frozenErrorPolicy(options.error_policy),
    });
    return action;
  }

  async commit<T>(
    action: PreparedCommand,
    decode: Decoder<T>,
    signal?: AbortSignal,
  ): Promise<ApiSuccess<T>> {
    const command = this.commands.get(action);
    if (command === undefined) throw new TypeError('Command must belong to this client');
    return this.request(
      command.path,
      command.method,
      command.body,
      command.key,
      command.success_status,
      decode,
      meta,
      true,
      signal,
      command.error_policy,
    );
  }
  async read<T>(
    target: string,
    decode: Decoder<T>,
    query: readonly (readonly [string, string])[] = [],
    signal?: AbortSignal,
    errorPolicy?: ApiErrorPolicy,
  ): Promise<ApiSuccess<T>> {
    const parameters = new URLSearchParams();
    for (const [key, value] of query) parameters.append(key, value);
    const encoded = parameters.toString();
    return this.request(
      path(target) + (encoded ? '?' + encoded : ''),
      'GET',
      null,
      null,
      [200],
      decode,
      meta,
      false,
      signal,
      errorPolicy,
    );
  }
  async readFormation<T>(
    target: string,
    decode: Decoder<T>,
    query: readonly (readonly [string, string])[] = [],
    signal?: AbortSignal,
    errorPolicy?: ApiErrorPolicy,
  ): Promise<ApiSuccess<T, FormationCursorPagination>> {
    const parameters = new URLSearchParams();
    for (const [key, value] of query) parameters.append(key, value);
    const encoded = parameters.toString();
    return this.request(
      formationPath(target) + (encoded ? '?' + encoded : ''),
      'GET',
      null,
      null,
      [200],
      decode,
      formationMeta,
      false,
      signal,
      errorPolicy,
    );
  }
  async previewFormation<T>(
    target: string,
    body: JsonObject,
    decode: Decoder<T>,
    signal?: AbortSignal,
    errorPolicy?: ApiErrorPolicy,
  ): Promise<ApiSuccess<T>> {
    if (
      !/^\/api\/v1\/requirements\/[1-9][0-9]*\/documents\/[1-9][0-9]*\/formation\/path-preview$/.test(
        target,
      )
    )
      throw new TypeError('Invalid formation preview path');
    return this.request(
      target,
      'POST',
      JSON.stringify(snapshot(body)),
      null,
      [200],
      decode,
      noPagination,
      false,
      signal,
      errorPolicy,
    );
  }
  private async request<T, P extends ApiPagination>(
    target: string,
    method: string,
    body: string | null,
    key: string | null,
    successStatus: readonly number[],
    decode: Decoder<T>,
    decodeMeta: (value: unknown) => ApiMeta<P>,
    mutation: boolean,
    signal?: AbortSignal,
    errorPolicy?: ApiErrorPolicy,
  ): Promise<ApiSuccess<T, P>> {
    this.assertConnection(mutation);
    const connection = this.environmentConnection;
    if (connection?.getSnapshot().environment.recovery !== undefined) {
      if (!allowsRecoveryRequest(method, target))
        throw new ApiNotSent(RECOVERY_READ_ONLY, 'RECOVERY_READ_ONLY');
    } else if (connection && !allowsOrdinaryRequest(method, target)) {
      throw new ApiNotSent(ORDINARY_OPERATION_UNAVAILABLE, 'ENVIRONMENT_CAPABILITY_DISABLED');
    }
    const revision = connection?.requestRevision ?? 0;
    errorPolicy = frozenErrorPolicy(errorPolicy);
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stop: (() => void) | undefined;
    try {
      if (signal?.aborted) throw new ApiUnknown(mutation);
      const headers: Record<string, string> = { Accept: 'application/json' };
      if (this.environment) Object.assign(headers, environmentHeaders(this.environment.scope));
      if (body !== null) headers['Content-Type'] = 'application/json';
      if (key !== null) headers['Idempotency-Key'] = key;
      const options: RequestInit = {
        method,
        headers,
        credentials: 'same-origin',
        redirect: 'error',
        cache: 'no-store',
      };
      if (body !== null) options.body = body;
      options.signal = controller.signal;
      // Race explicitly as well as aborting fetch: a stalled/custom transport
      // must not retain the caller's write barrier after its deadline.
      const cancelled = new Promise<never>((_resolve, reject) => {
        stop = () => {
          reject(new ApiUnknown(mutation));
          controller.abort();
        };
      });
      signal?.addEventListener('abort', stop!, { once: true });
      timer = setTimeout(stop!, API_REQUEST_TIMEOUT_MS);
      const exchange = (async () => {
        const response = await this.send(target, options);
        if (controller.signal.aborted) {
          // Never decode a late receipt or leave its unread stream open.
          void response.body?.cancel().catch(() => undefined);
          throw new ApiUnknown(mutation);
        }
        const json =
          response.headers.get('Content-Type')?.split(';')[0]?.trim().toLowerCase() ===
          'application/json';
        if (connection && (response.status === 401 || (!json && response.status === 403))) {
          void response.body?.cancel().catch(() => undefined);
          throw new EnvironmentEntryError(response.status === 401 ? 'ACCESS' : 'PERMISSION');
        }
        if (!json) {
          void response.body?.cancel().catch(() => undefined);
          throw new TypeError('Expected API JSON');
        }
        const text = await response.text();
        if (controller.signal.aborted) throw new ApiUnknown(mutation);
        return { response, text };
      })();
      const { response, text } = await Promise.race([exchange, cancelled]);
      if (controller.signal.aborted) throw new ApiUnknown(mutation);
      const parsed: unknown = JSON.parse(text);
      jsonValue(parsed);
      const envelope = exact(parsed, ['success', 'data', 'error', 'meta']),
        context = decodeMeta(envelope.meta);
      if (
        envelope.success === true &&
        envelope.error === null &&
        successStatus.includes(response.status)
      ) {
        this.checkEnvironmentResponse(response, revision, mutation);
        return { data: decode(envelope.data), meta: context, status: response.status };
      }
      if (
        envelope.success !== false ||
        envelope.data !== null ||
        Object.hasOwn(context, 'pagination') ||
        response.status < 400 ||
        response.status > 599
      )
        throw new TypeError('Invalid response');
      const error = exact(envelope.error, ['code', 'message', 'details']);
      if (
        typeof error.code !== 'string' ||
        !/^[A-Z][A-Z_]+$/.test(error.code) ||
        typeof error.message !== 'string' ||
        !error.message
      )
        throw new TypeError('Invalid API error');
      if (this.environment && Object.hasOwn(ENVIRONMENT_ERRORS, error.code)) {
        const common = ENVIRONMENT_ERRORS[error.code]!;
        if (response.status !== common[0] || error.message !== common[1] || error.details !== null)
          throw new TypeError('Invalid common environment rejection');
        const bindingRejection = BINDING_REJECTIONS.has(error.code);
        this.checkEnvironmentResponse(response, revision, mutation, bindingRejection);
        if (connection) {
          if (bindingRejection && error.code !== 'BINDING_PROTOCOL_MISMATCH')
            connection.reportFailure(revision, 'SCOPE_CHANGED');
          else if (error.code === 'BINDING_PROTOCOL_MISMATCH')
            connection.reportFailure(revision, 'PROTOCOL');
          else if (error.code === 'REQUEST_SOURCE_REJECTED')
            connection.reportFailure(revision, 'PERMISSION');
          else if (
            [
              'ENVIRONMENT_NOT_READY',
              'ENVIRONMENT_MAINTENANCE',
              'ENVIRONMENT_CONTROL_UNVERIFIED',
            ].includes(error.code)
          )
            connection.reportFailure(revision, 'NOT_READY');
          else if (error.code === 'ENVIRONMENT_ACCESS_DENIED' && mutation)
            void connection.recheck();

          // A scope refusal describes this exchange. An original command may
          // have been accepted before the environment changed.
          if (bindingRejection && mutation) throw new ApiUnknown(true);
        }
        throw new ApiRejected(error.code, error.message, null, context.request_id, response.status);
      }
      this.checkEnvironmentResponse(response, revision, mutation);
      let details: JsonObject | null;
      if (errorPolicy !== undefined) {
        details = errorPolicy.decode(error.code, error.message, error.details, response.status);
        if (mutation && errorPolicy.mutationUnknown(error.code, response.status))
          throw new ApiUnknown(true);
      } else {
        details = documentFailureDetails(error.code, error.details, response.status);
        if (mutation && (error.code === 'INTERNAL_ERROR' || error.code === 'STORAGE_UNAVAILABLE'))
          throw new ApiUnknown(true);
      }
      throw new ApiRejected(
        error.code,
        error.message,
        details,
        context.request_id,
        response.status,
      );
    } catch (error) {
      if (error instanceof ApiRejected) throw error;
      if (connection && !signal?.aborted) {
        if (error instanceof EnvironmentEntryError) connection.reportFailure(revision, error.code);
        else if (!(error instanceof ApiUnknown) || controller.signal.aborted)
          connection.reportFailure(revision, 'UNREACHABLE');
      }
      // Includes transport, abort, response/body parse and success projection:
      // none prove that a previously submitted command failed to commit.
      throw new ApiUnknown(mutation);
    } finally {
      if (timer !== undefined) clearTimeout(timer);
      if (stop) signal?.removeEventListener('abort', stop);
    }
  }

  private checkEnvironmentResponse(
    response: Response,
    revision: number,
    mutation: boolean,
    bindingRejection = false,
  ) {
    const environment = this.environment;
    if (!environment) return;
    if (bindingRejection) {
      if (
        !UUID.test(response.headers.get('X-WALL-E-Environment-ID') ?? '') ||
        !UUID.test(response.headers.get('X-WALL-E-Data-Generation') ?? '') ||
        !UUID.test(response.headers.get('X-WALL-E-Run-ID') ?? '')
      )
        throw new TypeError('Invalid binding rejection identity');
      return;
    }
    const run = compareResponseScope(response.headers, environment.scope);
    if (this.environmentConnection) {
      if (!this.environmentConnection.acceptResponse(revision, run, mutation))
        throw new ApiUnknown(mutation);
      return;
    }
    if (!this.observedRuns.has(run)) {
      this.observedRuns.add(run);
      if (environment.onRunChanged) queueMicrotask(() => environment.onRunChanged?.(run));
    }
  }
}
