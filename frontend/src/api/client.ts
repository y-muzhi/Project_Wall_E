/** API-COM transport and immutable user actions; pages own business refresh. */
export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type JsonObject = { [key: string]: Json };
export type PagePagination = { page: number; page_size: 20; total: number; total_pages: number };
export type CursorPagination = { page_size: 20; next_cursor: number | null; has_more: boolean };
export type ApiMeta = { request_id: string; pagination?: PagePagination | CursorPagination };
export type ApiSuccess<T> = { data: T; meta: ApiMeta; status: number };
type Decoder<T> = (value: unknown) => T;
type CommandMethod = 'POST' | 'PATCH' | 'PUT' | 'DELETE';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const ERROR_STATUS: Readonly<Record<string, number>> = {
  VALIDATION_FAILED: 422, NOT_FOUND: 404, MANUAL_DRAFT_NOT_FOUND: 404,
  STATE_CONFLICT: 409, WORK_STATE_CONFLICT: 409, WORK_STATE_INCONSISTENT: 409, CONTENT_VERSION_CONFLICT: 409,
  TEMPLATE_INVALID: 422, DOCUMENT_INVALID: 422, ANCHOR_INVALID: 422, SCOPE_INVALID: 422, SOURCE_INVALID: 422,
  PATCH_INVALID: 422, TARGET_STALE: 409, BATCH_PENDING: 422, COMMENT_ORPHANED: 409,
  CARD_ALREADY_ANSWERED: 409, CARD_EXPIRED: 409, CONFIG_INVALID: 503, STORAGE_UNAVAILABLE: 503,
  CAPACITY_EXHAUSTED: 503, IDEMPOTENCY_CONFLICT: 409, REQUEST_IN_PROGRESS: 409, INTERNAL_ERROR: 500,
};

export class ApiUnknown extends Error {
  readonly code = 'RESULT_UNKNOWN';
  readonly mutation: boolean;
  constructor(mutation: boolean) { super(mutation ? '本次操作结果待核实，已保留原请求' : '暂时无法读取数据，请重试'); this.mutation = mutation; }
}
export class ApiRejected extends Error {
  readonly code: string; readonly details: JsonObject | null; readonly request_id: string; readonly status: number;
  constructor(code: string, message: string, details: JsonObject | null, request_id: string, status: number) {
    super(message); this.code = code; this.details = details; this.request_id = request_id; this.status = status;
  }
}

export function object(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new TypeError('Expected object');
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) throw new TypeError('Expected plain object');
  return value as Record<string, unknown>;
}
export function exact(value: unknown, keys: readonly string[]): Record<string, unknown> {
  const result = object(value);
  if (Object.keys(result).length !== keys.length || keys.some(key => !Object.hasOwn(result, key))) throw new TypeError('Unexpected fields');
  return result;
}
export function positiveInteger(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 1) throw new TypeError('Invalid identity');
  return value;
}
function nonnegative(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) throw new TypeError('Invalid count');
  return value;
}
function jsonValue(value: unknown, seen = new Set<unknown>()): asserts value is Json {
  if (value === null || typeof value === 'boolean') return;
  if (typeof value === 'string') {
    for (const character of value) if (character.length === 1 && character.charCodeAt(0) >= 0xd800 && character.charCodeAt(0) <= 0xdfff) throw new TypeError('Invalid Unicode');
    return;
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value) || Number.isInteger(value) && !Number.isSafeInteger(value)) throw new TypeError('Invalid JSON number');
    return;
  }
  if (typeof value !== 'object' || seen.has(value)) throw new TypeError('Invalid JSON value');
  seen.add(value);
  if (Array.isArray(value)) { for (const item of value) jsonValue(item, seen); }
  else { for (const [key, item] of Object.entries(object(value))) { jsonValue(key); jsonValue(item, seen); } }
  seen.delete(value);
}
function path(value: string): string {
  if (!/^\/api\/v1\/[a-z0-9-]+(?:\/[a-z0-9-]+)*$/.test(value)) throw new TypeError('Invalid same-origin API path');
  return value;
}
function snapshot(value: unknown, seen = new Set<unknown>()): Json {
  if (value === null || typeof value !== 'object') { jsonValue(value); return value; }
  if (seen.has(value)) throw new TypeError('Cyclic JSON');
  seen.add(value);
  let result: Json;
  if (Array.isArray(value)) result = Array.from(value, item => snapshot(item, seen));
  else result = Object.fromEntries(Object.entries(object(value)).map(([key, item]) => { jsonValue(key); return [key, snapshot(item, seen)]; }));
  seen.delete(value);
  return result;
}
function meta(value: unknown): ApiMeta {
  const row = object(value);
  exact(row, Object.hasOwn(row, 'pagination') ? ['request_id', 'pagination'] : ['request_id']);
  if (typeof row.request_id !== 'string' || !UUID.test(row.request_id)) throw new TypeError('Invalid request ID');
  if (!Object.hasOwn(row, 'pagination')) return { request_id: row.request_id };
  const item = object(row.pagination);
  if (item.page_size !== 20) throw new TypeError('Invalid page size');
  let pagination: PagePagination | CursorPagination;
  if (Object.hasOwn(item, 'page')) {
    exact(item, ['page', 'page_size', 'total', 'total_pages']);
    const page = positiveInteger(item.page), total = nonnegative(item.total), total_pages = nonnegative(item.total_pages);
    if (page > 100000 || total_pages !== Math.ceil(total / 20)) throw new TypeError('Inconsistent pagination');
    pagination = { page, page_size: 20, total, total_pages };
  } else {
    exact(item, ['page_size', 'next_cursor', 'has_more']);
    const next_cursor = item.next_cursor === null ? null : positiveInteger(item.next_cursor);
    if (typeof item.has_more !== 'boolean' || item.has_more !== (next_cursor !== null)) throw new TypeError('Invalid cursor pagination');
    pagination = { page_size: 20, next_cursor, has_more: item.has_more };
  }
  return { request_id: row.request_id, pagination };
}

/** Opaque command handle. Snapshot/string/key remain private and never mutate. */
export type PreparedCommand = Readonly<{ kind: 'WALLE_COMMAND' }>;
type FrozenCommand = { method: CommandMethod; path: string; body: string | null; key: string | null; success_status: number };

export class ApiClient {
  private readonly commands = new WeakMap<PreparedCommand, FrozenCommand>();
  private readonly send: typeof fetch; private readonly uuid: () => string;
  constructor(send: typeof fetch = globalThis.fetch.bind(globalThis), uuid: () => string = () => globalThis.crypto.randomUUID()) {
    this.send = send; this.uuid = uuid;
  }

  prepare(method: CommandMethod, target: string, body: JsonObject | null, options: { idempotent: boolean; success_status: 200 | 201 | 202 }): PreparedCommand {
    if (!['POST', 'PATCH', 'PUT', 'DELETE'].includes(method)) throw new TypeError('Invalid command method');
    const location = path(target);
    if (typeof options.idempotent !== 'boolean' || ![200, 201, 202].includes(options.success_status)) throw new TypeError('Invalid command policy');
    if (body !== null) object(body);
    const frozenBody = body === null ? null : JSON.stringify(snapshot(body));
    const key = options.idempotent ? this.uuid() : null;
    if (key !== null && !UUID.test(key)) throw new TypeError('Invalid action key');
    const action = Object.freeze({ kind: 'WALLE_COMMAND' as const });
    this.commands.set(action, { method, path: location, body: frozenBody, key, success_status: options.success_status });
    return action;
  }

  async commit<T>(action: PreparedCommand, decode: Decoder<T>, signal?: AbortSignal): Promise<ApiSuccess<T>> {
    const command = this.commands.get(action);
    if (command === undefined) throw new TypeError('Command must belong to this client');
    return this.request(command.path, command.method, command.body, command.key, command.success_status, decode, signal);
  }
  async read<T>(target: string, decode: Decoder<T>, query: readonly (readonly [string, string])[] = [], signal?: AbortSignal): Promise<ApiSuccess<T>> {
    const parameters = new URLSearchParams();
    for (const [key, value] of query) parameters.append(key, value);
    const encoded = parameters.toString();
    return this.request(path(target) + (encoded ? '?' + encoded : ''), 'GET', null, null, 200, decode, signal);
  }
  private async request<T>(target: string, method: string, body: string | null, key: string | null, successStatus: number,
                           decode: Decoder<T>, signal?: AbortSignal): Promise<ApiSuccess<T>> {
    const mutation = method !== 'GET';
    try {
      const headers: Record<string, string> = { Accept: 'application/json' };
      if (body !== null) headers['Content-Type'] = 'application/json';
      if (key !== null) headers['Idempotency-Key'] = key;
      const options: RequestInit = { method, headers, credentials: 'same-origin', redirect: 'error', cache: 'no-store' };
      if (body !== null) options.body = body;
      if (signal !== undefined) options.signal = signal;
      const response = await this.send(target, options);
      if (response.headers.get('Content-Type')?.split(';')[0]?.trim().toLowerCase() !== 'application/json') throw new TypeError('Expected API JSON');
      const parsed: unknown = JSON.parse(await response.text()); jsonValue(parsed);
      const envelope = exact(parsed, ['success', 'data', 'error', 'meta']), context = meta(envelope.meta);
      if (envelope.success === true && envelope.error === null && response.status === successStatus) {
        return { data: decode(envelope.data), meta: context, status: response.status };
      }
      if (envelope.success !== false || envelope.data !== null || Object.hasOwn(context, 'pagination') || response.status < 400 || response.status > 599) throw new TypeError('Invalid response');
      const error = exact(envelope.error, ['code', 'message', 'details']);
      if (typeof error.code !== 'string' || !/^[A-Z][A-Z_]+$/.test(error.code) || typeof error.message !== 'string' || !error.message) throw new TypeError('Invalid API error');
      if (!Object.hasOwn(ERROR_STATUS, error.code) || ERROR_STATUS[error.code] !== response.status) throw new TypeError('Unregistered error');
      if (mutation && (error.code === 'INTERNAL_ERROR' || error.code === 'STORAGE_UNAVAILABLE')) throw new ApiUnknown(true);
      const details = error.details === null ? null : object(error.details) as JsonObject;
      throw new ApiRejected(error.code, error.message, details, context.request_id, response.status);
    } catch (error) {
      if (error instanceof ApiRejected) throw error;
      // Includes transport, abort, response/body parse and success projection:
      // none prove that a previously submitted command failed to commit.
      throw new ApiUnknown(mutation);
    }
  }
}
