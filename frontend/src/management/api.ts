import { parseEnvironmentJson } from '../api/environment-binding.ts';
import { exact, object, positiveInteger } from '../api/wire-shape.ts';
import {
  actor,
  candidateCatalog,
  capacity,
  configuration,
  controlReceipt,
  controlResult,
  environment,
  environmentBackups,
  environmentList,
  handshake,
  hash,
  operationDetail,
  operationList,
  text,
  utc,
  uuid,
} from './model.ts';

import {
  maintenanceDetails,
  releaseCatalog,
  releasePlan,
  type ReleaseVariables,
} from './release-model.ts';

import { backupOptions, backupPlan, type BackupVariables } from './backup-model.ts';
import { restoreOptions, restorePlan, type RestoreVariables } from './restore-model.ts';
import { priorResult, priorResultScopes, type PriorResultInput } from './prior-result-model.ts';

export const managementOperationsPath = '/management/api/v1/operations';
const root = '/management/api/v1';
const publicPath = '/.well-known/walle-management.json';

const descriptions: Readonly<Record<string, string>> = {
  MANAGEMENT_ACCESS_DENIED: '当前账号无权查看此记录。',
  MANAGEMENT_INPUT_INVALID: '查询条件无效，请核对后重试。',
  MANAGEMENT_RECORD_NOT_FOUND: '当前管理范围内没有这条记录。',
  MANAGEMENT_SCOPE_MISMATCH: '管理入口或登记代次已变化，请重新核对。',
  MANAGEMENT_NOT_READY: '管理登记暂时不可用，请先核对原请求。',
  MANAGEMENT_DISPATCH_PAUSED: '管理登记当前只读，写入暂不可用。',
  MANAGEMENT_PRIOR_REGISTRY_RESULT_UNVERIFIED: '原登记回执尚无法核实。',
  MANAGEMENT_KEY_CONFLICT: '原请求键已绑定另一份输入。',
  MANAGEMENT_VERSION_CONFLICT: '环境或分配版本已变化，请重新读取。',
  MANAGEMENT_OPERATION_CONFLICT: '目标已有进行中的操作或资源占用。',
  MANAGEMENT_RESOURCE_UNVERIFIED: '部分管理资源暂时无法核实。',
  RELEASE_PLAN_CHANGED: '维护计划已过期或环境发生变化，请重新核对。',
  BACKUP_ASSET_UNSUPPORTED: '当前备份资产或核验方式尚未准入。',
  MAINTENANCE_DRAIN_BLOCKED: '宿主尚未核对源环境已经正常停止。',
  RELEASE_COMPATIBILITY_UNVERIFIED: '固定候选的兼容性或平台验证尚未通过。',
  REQUEST_SOURCE_REJECTED: '当前页面的管理请求来源无法核实。',
  ACTION_NOT_AVAILABLE: '当前管理入口未开放这项操作。',
};

type OriginalOperation = ReturnType<typeof operationDetail>['original'];

function originalRecoveryDisposition(
  wire: { source: string; disposition: unknown },
  original: OriginalOperation,
) {
  if (wire.disposition === undefined) return null;
  const record = exact(wire.disposition, [
    'operation_id',
    'source_registry_generation',
    'source_revision',
    'recorded_registry_generation',
    'recorded_at',
    'disposition',
  ]);
  const kind = record.disposition;
  const undispatched =
    kind === 'UNDISPATCHED_CANCELLED' &&
    original.action === 'START' &&
    original.state === 'WAITING_CAPACITY';
  const completedBackup =
    kind === 'BACKUP_COMPLETED' &&
    original.action === 'BACKUP' &&
    (original.state === 'RUNNING' ||
      original.state === 'UNKNOWN' ||
      original.state === 'SUCCEEDED');
  if (
    uuid(record.operation_id) !== original.id ||
    uuid(record.source_registry_generation) !== wire.source ||
    positiveInteger(record.source_revision) !== original.revision ||
    uuid(record.recorded_registry_generation) === wire.source ||
    (!undispatched && !completedBackup)
  )
    throw new TypeError('Original recovery disposition differs from the preserved operation');
  return { recordedAt: utc(record.recorded_at), kind };
}

export class ManagementReadError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

export function managementWriteBlocked() {
  return new ManagementReadError(
    'MANAGEMENT_DISPATCH_PAUSED',
    descriptions.MANAGEMENT_DISPATCH_PAUSED!,
  );
}

function changed() {
  return new ManagementReadError(
    'MANAGEMENT_SCOPE_MISMATCH',
    descriptions.MANAGEMENT_SCOPE_MISMATCH!,
  );
}

async function body(response: Response, maximum: number) {
  if (
    !/^application\/json(?:;|$)/i.test(response.headers.get('Content-Type') ?? '') ||
    !response.body
  )
    throw new ManagementReadError('WIRE', '管理入口返回了无法识别的内容。');
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let total = 0;
  let raw = '';
  try {
    for (;;) {
      const item = await reader.read();
      if (item.done) return parseEnvironmentJson(raw + decoder.decode());
      total += item.value.byteLength;
      if (total > maximum)
        throw new ManagementReadError('WIRE', '管理响应超过当前页面可读取的范围。');
      raw += decoder.decode(item.value, { stream: true });
    }
  } finally {
    void reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

function identity(response: Response) {
  return {
    manager: uuid(response.headers.get('X-WALL-E-Manager-ID')),
    generation: uuid(response.headers.get('X-WALL-E-Registry-Generation')),
    run: uuid(response.headers.get('X-WALL-E-Manager-Run-ID')),
    principal: response.headers.get('X-WALL-E-Manager-Principal'),
  };
}

function envelope(value: unknown, status: number, expected = [200]) {
  const data = exact(value, ['success', 'data', 'error', 'meta']);
  uuid(exact(data.meta, ['request_id']).request_id);
  if (data.success === true && expected.includes(status) && data.error === null) return data.data;
  if (data.success !== false || data.data !== null)
    throw new TypeError('Invalid management result');
  const error = exact(data.error, ['code', 'message', 'details']);
  if (error.details !== null) throw new TypeError('Invalid management diagnostic');
  const code = text(error.code, 96);
  text(error.message, 500);
  throw new ManagementReadError(code, descriptions[code] ?? '管理资料暂时无法读取。');
}

export function same(
  config: ReturnType<typeof configuration>,
  other: ReturnType<typeof configuration>,
) {
  return (
    config.manager === other.manager &&
    config.host === other.host &&
    config.generation === other.generation &&
    config.origin === other.origin
  );
}

export type Session = ReturnType<typeof handshake> & Readonly<{ bindingChanged: boolean }>;
export type Filter = {
  purpose?: string;
  registration_state?: string;
  task_id?: string;
  status?: string;
  environment_id?: string;
  cursor?: string;
};

export class ManagementClient {
  #session: Session | null = null;
  #origin: string;
  #listeners = new Set<() => void>();

  constructor(origin: string) {
    this.#origin = origin;
  }

  current = () => this.#session;

  subscribe = (listener: () => void) => {
    this.#listeners.add(listener);
    return () => {
      this.#listeners.delete(listener);
    };
  };

  private async request(
    path: string,
    signal: AbortSignal,
    binding: Session | null,
    submission?: Readonly<{ key?: string; body: string }>,
  ) {
    const headers = new Headers({ 'X-WALL-E-Client': 'web-v1', Accept: 'application/json' });
    if (binding) {
      headers.set('X-WALL-E-Manager-ID', binding.config.manager);
      headers.set('X-WALL-E-Registry-Generation', binding.config.generation);
      headers.set('X-WALL-E-Management-Protocol', '1');
    }
    if (submission && binding) {
      if (submission.key) headers.set('Idempotency-Key', uuid(submission.key));
      headers.set('X-WALL-E-Expected-Principal', binding.principal);
      headers.set('Content-Type', 'application/json; charset=UTF-8');
    }
    const response = await fetch(path, {
      method: submission ? 'POST' : 'GET',
      ...(submission && { body: submission.body }),
      headers,
      credentials: 'same-origin',
      cache: 'no-store',
      redirect: 'error',
      signal,
    });
    if (response.status === 401) throw new ManagementReadError('AUTH', '请先登录独立管理入口。');
    if (
      [502, 503, 504].includes(response.status) &&
      !/^application\/json/i.test(response.headers.get('Content-Type') ?? '')
    )
      throw new ManagementReadError('OFFLINE', '管理服务暂时无法连接。');
    return response;
  }

  private publish(session: Session) {
    this.#session = session;
    for (const listener of this.#listeners) listener();
  }

  private freeze(): ManagementReadError {
    if (this.#session && !this.#session.bindingChanged) {
      this.publish({ ...this.#session, bindingChanged: true, phase: 'BLOCKED' });
    }
    return changed();
  }

  async check(signal: AbortSignal): Promise<Session> {
    if (this.#session?.bindingChanged) throw changed();
    const first = await this.request(publicPath, signal, null);
    if (first.status !== 200) {
      envelope(await body(first, 16384), first.status);
      throw new TypeError('Invalid management entry response');
    }
    const config = configuration(await body(first, 16384), this.#origin);
    if (this.#session && !same(this.#session.config, config)) throw this.freeze();
    const head = await this.request(root + '/identity', signal, null);
    const checked = handshake(envelope(await body(head, 16384), head.status), this.#origin);
    const headers = identity(head);
    const entry = identity(first);
    if (
      !same(config, checked.config) ||
      config.name !== checked.config.name ||
      headers.manager !== config.manager ||
      headers.generation !== config.generation ||
      headers.run !== checked.run ||
      headers.principal !== checked.principal ||
      entry.manager !== headers.manager ||
      entry.generation !== headers.generation ||
      entry.run !== headers.run ||
      entry.principal !== headers.principal ||
      (this.#session && !same(this.#session.config, config))
    )
      throw this.freeze();
    if (this.#session?.bindingChanged) throw changed();
    const next = { ...checked, bindingChanged: false };
    if (!this.#session || JSON.stringify(this.#session) !== JSON.stringify(next))
      this.publish(next);
    return next;
  }

  private async read<T>(
    path: string,
    decode: (input: unknown) => T,
    signal: AbortSignal,
  ): Promise<T> {
    const original = this.#session;
    if (!original || original.bindingChanged) throw changed();
    const response = await this.request(root + path, signal, original);
    await this.checkResponse(response, original, signal);
    return decode(envelope(await body(response, 512 * 1024), response.status));
  }

  private async checkResponse(response: Response, original: Session, signal: AbortSignal) {
    if (this.#session?.bindingChanged) throw changed();
    const hint = identity(response);
    if (hint.manager !== original.config.manager || hint.generation !== original.config.generation)
      throw this.freeze();
    if (hint.principal !== null && actor(hint.principal) !== original.principal) {
      await this.check(signal);
      throw changed();
    }
    if (this.#session?.run !== hint.run) {
      const current = await this.check(signal);
      if (
        current.run !== hint.run ||
        current.principal !== original.principal ||
        current.role !== original.role
      )
        throw new ManagementReadError('STALE', '管理身份或运行已更新，请重新读取。');
    }
    if (this.#session?.principal !== original.principal || this.#session.role !== original.role)
      throw changed();
    if (response.ok && hint.principal !== original.principal) throw changed();
  }

  private requireWriteSession(original: Session) {
    if (
      !this.#session ||
      this.#session.bindingChanged ||
      !same(this.#session.config, original.config) ||
      this.#session.principal !== original.principal ||
      this.#session.role !== original.role
    )
      throw changed();
    if (this.#session.phase === 'BLOCKED') throw managementWriteBlocked();
  }

  async submitOperation(
    original: Session,
    submission: Readonly<{ key: string; body: string }>,
    signal: AbortSignal,
  ) {
    this.requireWriteSession(original);
    const response = await this.request(managementOperationsPath, signal, original, submission);
    await this.checkResponse(response, original, signal);
    return operationDetail(envelope(await body(response, 512 * 1024), response.status, [200, 202]));
  }

  backupOptions(id: string, signal: AbortSignal) {
    const target = uuid(id);
    const filters = new URLSearchParams({ environment_id: target, kind: 'BACKUP' });
    return this.read(
      '/catalog?' + filters.toString(),
      (value) => backupOptions(value, target),
      signal,
    );
  }

  async planBackup(original: Session, values: BackupVariables, signal: AbortSignal) {
    this.requireWriteSession(original);
    const response = await this.request(root + '/plans', signal, original, {
      body: JSON.stringify({ kind: 'BACKUP', ...values }),
    });
    await this.checkResponse(response, original, signal);
    return backupPlan(envelope(await body(response, 65536), response.status, [201]), values);
  }

  priorResultScopes(id: string, signal: AbortSignal) {
    const target = uuid(id);
    return this.read(
      '/environments/' + target + '/prior-command-results',
      (value) => priorResultScopes(value, target),
      signal,
    );
  }

  priorResult(id: string, input: PriorResultInput, signal: AbortSignal) {
    const target = uuid(id);
    const filters = new URLSearchParams(input);
    return this.read(
      '/environments/' + target + '/prior-command-results?' + filters.toString(),
      (value) => priorResult(value, target, input.source_data_generation),
      signal,
    );
  }

  restoreOptions(id: string, signal: AbortSignal) {
    const target = uuid(id);
    const filters = new URLSearchParams({ environment_id: target, kind: 'RESTORE' });
    return this.read(
      '/catalog?' + filters.toString(),
      (value) => restoreOptions(value, target),
      signal,
    );
  }

  async planRestore(original: Session, variables: RestoreVariables, signal: AbortSignal) {
    this.requireWriteSession(original);
    const response = await this.request(root + '/plans', signal, original, {
      body: JSON.stringify({ kind: 'RESTORE', ...variables }),
    });
    await this.checkResponse(response, original, signal);
    return restorePlan(envelope(await body(response, 65536), response.status, [201]), variables);
  }

  releaseOptions(id: string, signal: AbortSignal) {
    const target = uuid(id);
    return this.read(
      '/catalog' + this.parameters({ environment_id: target }),
      (value) => releaseCatalog(value, target),
      signal,
    );
  }

  async planRelease(original: Session, variables: ReleaseVariables, signal: AbortSignal) {
    this.requireWriteSession(original);
    const response = await this.request(root + '/plans', signal, original, {
      body: JSON.stringify({ kind: 'RELEASE', ...variables }),
    });
    await this.checkResponse(response, original, signal);
    return releasePlan(envelope(await body(response, 65536), response.status, [201]), variables);
  }

  catalog(signal: AbortSignal) {
    return this.read('/catalog', candidateCatalog, signal);
  }

  private parameters(filter: Filter): string {
    const params = new URLSearchParams();
    for (const [name, value] of Object.entries(filter)) if (value) params.set(name, value);
    const query = params.toString();
    return query ? '?' + query : '';
  }

  environments(filter: Filter, signal: AbortSignal) {
    return this.read('/environments' + this.parameters(filter), environmentList, signal);
  }

  environment(id: string, signal: AbortSignal) {
    return this.read('/environments/' + uuid(id), environment, signal);
  }

  maintenance(id: string, signal: AbortSignal) {
    const target = uuid(id);
    return this.read(
      '/environments/' + target + '/maintenance',
      (value) => maintenanceDetails(value, target),
      signal,
    );
  }

  backups(id: string, cursor: string, signal: AbortSignal) {
    const target = uuid(id);
    return this.read(
      '/environments/' + target + '/backups' + this.parameters({ cursor }),
      (value) => environmentBackups(value, target),
      signal,
    );
  }

  operations(filter: Filter, signal: AbortSignal) {
    return this.read('/operations' + this.parameters(filter), operationList, signal);
  }

  operation(id: string, signal: AbortSignal) {
    return this.read('/operations/' + uuid(id), operationDetail, signal);
  }

  original(key: string, signal: AbortSignal) {
    return this.read('/operations/by-key/' + uuid(key), operationDetail, signal);
  }

  private historical(generation: string, path: string, signal: AbortSignal) {
    const source = uuid(generation);
    return this.read(
      '/prior-registry/' + source + '/operations' + path,
      (value) => {
        const fields = ['source_registry_generation', 'snapshot_receipt_sha256', 'result'];
        if (Object.hasOwn(object(value), 'recovery_disposition'))
          fields.push('recovery_disposition');
        const receipt = exact(value, fields);
        if (uuid(receipt.source_registry_generation) !== source)
          throw new TypeError('Original registry generation differs from the request');
        hash(receipt.snapshot_receipt_sha256);
        return { source, value: receipt.result, disposition: receipt.recovery_disposition };
      },
      signal,
    );
  }

  async historicalOriginal(generation: string, key: string, signal: AbortSignal) {
    const original = uuid(key);
    const wire = await this.historical(generation, '/by-key/' + original, signal);
    const result = operationDetail(wire.value);
    if (result.original.key !== original) throw new TypeError('Original request key differs');
    const recoveryDisposition = originalRecoveryDisposition(wire, result.original);
    return { ...result, recoveryDisposition };
  }

  async historicalControl(
    generation: string,
    operationId: string,
    key: string,
    signal: AbortSignal,
  ) {
    const operation = uuid(operationId);
    const original = uuid(key);
    const wire = await this.historical(
      generation,
      '/' + operation + '/commands/' + original,
      signal,
    );
    const result = controlResult(wire.value, operation, original);
    originalRecoveryDisposition(wire, result.operation.original);
    return result.receipt;
  }

  control(operationId: string, key: string, signal: AbortSignal) {
    return this.read(
      '/operations/' + uuid(operationId) + '/commands/' + uuid(key),
      (value) => controlReceipt(value, operationId, key),
      signal,
    );
  }

  originalControl(operationId: string, key: string, signal: AbortSignal) {
    return this.read(
      '/operations/' + uuid(operationId) + '/commands/' + uuid(key),
      (value) => controlResult(value, operationId, key),
      signal,
    );
  }

  async submitControl(
    original: Session,
    operationId: string,
    submission: Readonly<{ key: string; body: string }>,
    signal: AbortSignal,
  ) {
    this.requireWriteSession(original);
    if (original.role === 'VIEWER')
      throw new ManagementReadError(
        'MANAGEMENT_ACCESS_DENIED',
        descriptions.MANAGEMENT_ACCESS_DENIED!,
      );
    const path = managementOperationsPath + '/' + uuid(operationId) + '/commands';
    const response = await this.request(path, signal, original, submission);
    await this.checkResponse(response, original, signal);
    return controlResult(
      envelope(await body(response, 512 * 1024), response.status, [200, 202]),
      operationId,
      submission.key,
    );
  }

  capacity(signal: AbortSignal) {
    return this.read('/capacity', capacity, signal);
  }
}
