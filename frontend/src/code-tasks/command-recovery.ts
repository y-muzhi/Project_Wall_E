/** Native API + durable browser ledger. Reads never dispatch or mint an action. */
import {
  ApiClient,
  ApiRejected,
  ApiUnknown,
  exact,
  object,
  positiveInteger,
  snapshotObject,
} from '../api/client.ts';
import type { ApiSuccess, JsonObject } from '../api/client.ts';
import { COMMAND_ROUTES, registeredCommand } from '../api/code-command-registry.ts';
import type { CommandIdentity } from '../api/code-command-registry.ts';
import { prepareCodeCommand, restoreCodeCommand } from '../api/code-command-snapshot.ts';
import type { CodeCommandBinding, FrozenCodeAction } from '../api/code-command-snapshot.ts';
import { commandReceipt, readCommandReceipt } from '../api/code-command-receipts.ts';
import type { CommandReceipt, OriginalResultPolicy } from '../api/code-command-receipts.ts';
import { prepareCloseOriginalCommand } from '../api/code-command-close.ts';
import type { CommandCloseReceipt } from '../api/code-command-close.ts';
import { codeErrorPolicy } from '../api/code-errors.ts';
import { CommandRecoveryStore } from './command-recovery-store.ts';
import { originalFrozen, pendingSummary } from './command-recovery-model.ts';
import type { PendingSummary, CommandReceiptLocal } from './command-recovery-model.ts';

type LocalResult = PendingSummary | CommandReceiptLocal | null;
export type RecoveryLookup = Readonly<{
  original_receipt: CommandReceipt<unknown> | null;
  local: LocalResult;
}>;
export type CommandStage =
  | Readonly<{ kind: 'PREPARED' | 'EXISTING'; record: PendingSummary }>
  | Readonly<{ kind: 'RESOLVED'; receipt: CommandReceiptLocal }>;
export type OriginalRecoveryOptions = Readonly<{
  replay: boolean;
  replayReason: string | null;
  close: boolean;
}>;
export type OperationReader = (
  original: CommandIdentity,
  association: Readonly<{
    task_id: number | null;
    testing_task_id: number | null;
    operation_id: number;
  }>,
  signal?: AbortSignal,
) => Promise<unknown>;
function replayCandidate(summary: PendingSummary): boolean {
  return (
    summary.close_state === 'NONE' &&
    summary.status !== 'ACCEPTED' &&
    summary.lookup_status === 'NOT_FOUND'
  );
}
const PROBE_KEY = '00000000-0000-4000-8000-000000000000';
function nativeBinding(value: CodeCommandBinding<unknown>): CodeCommandBinding<unknown> {
  if (
    !COMMAND_ROUTES.some((route) => route[1] === value.decoder_kind) ||
    typeof value.validate_input !== 'function' ||
    typeof value.decode !== 'function' ||
    !value.success_status.length ||
    new Set(value.success_status).size !== value.success_status.length ||
    value.success_status.some((status) => ![200, 201, 202].includes(status))
  )
    throw new TypeError('Invalid native command binding');
  codeErrorPolicy(value.errors);
  return Object.freeze({
    decoder_kind: value.decoder_kind,
    validate_input: value.validate_input,
    decode: value.decode,
    errors: Object.freeze([...value.errors]),
    success_status: Object.freeze([...value.success_status]),
  });
}
export class CommandRecovery {
  private readonly bindings = new Map<string, CodeCommandBinding<unknown>>();
  private readonly fresh = new Map<string, FrozenCodeAction<unknown>>();
  private readonly ownerId: string;
  private disposed = false;
  private readonly client: ApiClient;
  readonly store: CommandRecoveryStore;
  private readonly readOperation: OperationReader;
  constructor(
    client: ApiClient,
    store: CommandRecoveryStore,
    nativeBindings: readonly CodeCommandBinding<unknown>[],
    readOperation: OperationReader,
  ) {
    this.client = client;
    this.store = store;
    this.readOperation = readOperation;
    if (typeof readOperation !== 'function')
      throw new TypeError('Native operation reader required');
    for (const value of nativeBindings) {
      const binding = nativeBinding(value);
      if (this.bindings.has(binding.decoder_kind))
        throw new TypeError('Duplicate native command binding');
      this.bindings.set(binding.decoder_kind, binding);
    }
    this.ownerId = crypto.randomUUID();
  }
  private requireOpen(): void {
    if (this.disposed) throw new TypeError('Command recovery owner closed');
  }
  dispose(): void {
    this.disposed = true;
    this.fresh.clear();
    this.store.close();
  }
  private binding(original: CommandIdentity): CodeCommandBinding<unknown> {
    const value = this.bindings.get(original.decoder_kind);
    if (value === undefined)
      throw new TypeError('Original input/result binding is not implemented');
    return value;
  }
  private async load(key: string): Promise<{
    row: unknown;
    summary: PendingSummary;
    original: CommandIdentity;
    binding: CodeCommandBinding<unknown>;
  } | null> {
    this.requireOpen();
    const row = await this.store.detail(key);
    this.requireOpen();
    if (row === null) return null;
    const summary = pendingSummary(row, this.store.origin);
    const original = registeredCommand(summary.method, summary.path, summary.key);
    return { row, summary, original, binding: this.binding(original) };
  }
  async stage(path: string, body: JsonObject): Promise<PendingSummary | CommandReceiptLocal> {
    const staged = await this.stageIntent(path, body);
    return staged.kind === 'RESOLVED' ? staged.receipt : staged.record;
  }
  async stageIntent(path: string, body: JsonObject): Promise<CommandStage> {
    this.requireOpen();
    const scope = registeredCommand('POST', path, PROBE_KEY);
    const binding = this.binding(scope);
    const input = snapshotObject(body);
    const existing = (await this.store.list()).find((row) => row.intent_key === 'POST ' + path);
    this.requireOpen();
    if (existing) return Object.freeze({ kind: 'EXISTING', record: existing });
    const action = await prepareCodeCommand(this.client, path, input, binding, this.store.origin);
    this.requireOpen();
    const result = await this.store.reserve(action.frozen);
    this.requireOpen();
    if (result.kind === 'PREPARED') this.fresh.set(result.record.key, action);
    return result;
  }
  private async policy(
    loaded: NonNullable<Awaited<ReturnType<CommandRecovery['load']>>>,
  ): Promise<OriginalResultPolicy<unknown>> {
    try {
      const restored = await restoreCodeCommand(
        this.client,
        originalFrozen(loaded.row),
        loaded.binding,
        this.store.origin,
      );
      return restored.result_policy;
    } catch {
      // Safe identity still permits querying/closing. Success cannot be decoded
      // without the original valid input; never fill it from today's form.
      return Object.freeze({
        decoder_kind: loaded.original.decoder_kind,
        success_status: loaded.binding.success_status,
        errors: loaded.binding.errors,
        decode: () => {
          throw new TypeError('Original input unavailable for result verification');
        },
      });
    }
  }
  private async merge(
    key: string,
    expectedIdentity: string,
    receipt: CommandReceipt<unknown>,
    closeAlreadyReceived = false,
  ): Promise<LocalResult> {
    for (let attempt = 0; attempt < 2; attempt++) {
      const current = await this.load(key);
      if (current === null) {
        this.fresh.delete(key);
        const terminal = await this.store.receipt(key);
        if (terminal !== null && terminal.identity_sha256 !== expectedIdentity)
          throw new TypeError('Original terminal identity changed');
        return terminal;
      }
      if (current.summary.identity_sha256 !== expectedIdentity)
        throw new TypeError('Original stored identity changed');
      const saved = await this.store.observe(current.summary, receipt, closeAlreadyReceived);
      if (saved !== null) {
        if ('final_state' in saved) this.fresh.delete(key);
        return saved;
      }
    }
    return null; // Another tab won; never overwrite or recreate its record.
  }
  async lookup(key: string, signal?: AbortSignal): Promise<RecoveryLookup> {
    const loaded = await this.load(key);
    if (loaded === null)
      return Object.freeze({ original_receipt: null, local: await this.store.receipt(key) });
    const policy = await this.policy(loaded);
    this.requireOpen();
    const result = await readCommandReceipt(this.client, loaded.original, policy, signal);
    const local = await this.merge(key, loaded.summary.identity_sha256, result.data);
    return Object.freeze({ original_receipt: result.data, local });
  }
  /** Only load the original body after the user opens recovery options. */
  async inspectOriginal(
    key: string,
    expectedRevision: number,
    replayEnabled: boolean,
  ): Promise<OriginalRecoveryOptions> {
    const loaded = await this.load(key);
    if (loaded === null || loaded.summary.record_revision !== expectedRevision)
      throw new TypeError('Original recovery view changed');
    const summary = loaded.summary;
    const close =
      summary.close_state !== 'ALREADY_RECEIVED' &&
      summary.status !== 'ACCEPTED' &&
      summary.lookup_status !== 'IN_PROGRESS';
    if (!replayEnabled)
      return Object.freeze({ close, replay: false, replayReason: '当前入口暂不支持按原请求恢复' });
    if (!replayCandidate(summary))
      return Object.freeze({ close, replay: false, replayReason: '当前只能核对原请求结果' });
    try {
      const original = await restoreCodeCommand(
        this.client,
        originalFrozen(loaded.row),
        loaded.binding,
        this.store.origin,
      );
      this.requireOpen();
      if (original.recovery_mode !== 'REPLAY_SAME_KEY')
        return Object.freeze({ close, replay: false, replayReason: '此原请求只能核对或关闭' });
      return Object.freeze({ close, replay: true, replayReason: null });
    } catch {
      return Object.freeze({ close, replay: false, replayReason: '原请求内容无法验证' });
    }
  }
  /** Explicit user send only. A cold QUERY_ONLY request cannot submit. */
  send(key: string, expectedRevision: number, signal?: AbortSignal) {
    return this.dispatchOriginal(key, expectedRevision, false, signal);
  }
  replayOriginal(key: string, expectedRevision: number) {
    return this.dispatchOriginal(key, expectedRevision, true);
  }
  /** C05 permits explicit re-observation of the same accepted PIN outcome. */
  async observeBaselineOriginal(key: string, expectedRevision: number) {
    const loaded = await this.load(key);
    if (
      !loaded ||
      loaded.original.decoder_kind !== 'APP-CODE-CMD-C05' ||
      loaded.summary.record_revision !== expectedRevision ||
      loaded.summary.status !== 'ACCEPTED' ||
      loaded.summary.close_state !== 'NONE' ||
      loaded.summary.operation_id === null
    )
      throw TypeError('Original baseline observation is unavailable');
    const operationId = loaded.summary.operation_id;
    const observed = exact(
      await this.readOperation(loaded.original, {
        task_id: null,
        testing_task_id: null,
        operation_id: operationId,
      }),
      ['operation_id', 'task_id', 'testing_task_id', 'status'],
    );
    if (
      observed.operation_id !== operationId ||
      observed.task_id !== null ||
      observed.testing_task_id !== null ||
      observed.status !== 'UNKNOWN'
    )
      throw TypeError('Only the unknown original baseline can be observed again');
    return this.dispatchOriginal(key, expectedRevision, true, undefined, operationId);
  }

  private async dispatchOriginal(
    key: string,
    expectedRevision: number,
    explicitReplay: boolean,
    signal?: AbortSignal,
    baselineObservation?: number,
  ): Promise<{
    response: ApiSuccess<unknown>;
    original_receipt: CommandReceipt<unknown>;
    local: LocalResult;
  }> {
    positiveInteger(expectedRevision);
    const loaded = await this.load(key);
    if (loaded === null || loaded.summary.record_revision !== expectedRevision)
      throw new TypeError('Original request changed or is already resolved');
    if (baselineObservation !== undefined) {
      if (
        loaded.original.decoder_kind !== 'APP-CODE-CMD-C05' ||
        loaded.summary.status !== 'ACCEPTED' ||
        loaded.summary.operation_id !== baselineObservation ||
        loaded.summary.close_state !== 'NONE'
      )
        throw TypeError('Original baseline observation changed');
    } else if (explicitReplay && !replayCandidate(loaded.summary)) {
      throw new TypeError('Original request is not eligible for replay');
    }
    const restored = await restoreCodeCommand(
      this.client,
      originalFrozen(loaded.row),
      loaded.binding,
      this.store.origin,
    );
    this.requireOpen();
    let action = this.fresh.get(key);
    if (action !== undefined) {
      if (
        Object.entries(action.frozen).some(
          ([field, value]) => object(restored.frozen)[field] !== value,
        )
      )
        throw new TypeError('Original frozen bytes changed');
    } else action = restored;
    if (
      action.recovery_mode === 'QUERY_ONLY' &&
      (explicitReplay || action === restored || loaded.summary.dispatch_count !== 0)
    )
      throw new TypeError('Original cooperation window permits query/close only');
    const gate = await this.store.dispatch(
      loaded.summary,
      action.frozen,
      this.ownerId,
      loaded.summary.dispatch_count !== 0,
    );
    this.requireOpen();
    if (gate === null) throw new TypeError('Original send gate was not committed');
    this.fresh.delete(key);
    let response: ApiSuccess<unknown>;
    try {
      response = await action.submit(signal);
    } catch (error) {
      if (error instanceof ApiRejected) {
        try {
          await this.lookup(key, signal);
        } catch {
          /* Keep original pending for another explicit lookup. */
        }
      } else {
        try {
          await this.store.markUnknown(gate);
        } catch {
          /* Original DISPATCHING still remains. */
        }
      }
      throw error;
    }
    let receipt: CommandReceipt<unknown>;
    try {
      const data = object(response.data);
      if (baselineObservation !== undefined && data.operation_id !== baselineObservation)
        throw TypeError('Baseline observation changed the original operation');
      const association = (field: string) => (Object.hasOwn(data, field) ? data[field] : null);
      receipt = commandReceipt(
        {
          lookup_status: 'FOUND',
          record_status: 'SUCCEEDED',
          original_http_status: response.status,
          original_outcome: { success: true, data: response.data, error: null },
          task_id:
            loaded.original.decoder_kind === 'APP-CODE-CMD-C32' ||
            (loaded.original.decoder_kind === 'APP-CODE-CMD-C37' && response.status === 200)
              ? positiveInteger(data.id)
              : association('task_id'),
          testing_task_id:
            response.status === 200 &&
            ['APP-TEST-CMD-C27', 'APP-TEST-CMD-C29', 'APP-TEST-CMD-C31'].includes(
              loaded.original.decoder_kind,
            )
              ? positiveInteger(data.id)
              : association('testing_task_id'),
          operation_id: association('operation_id'),
        },
        loaded.original,
        action.result_policy,
      );
    } catch {
      try {
        await this.store.markUnknown(gate);
      } catch {
        /* Preserve original dispatch. */
      }
      throw new ApiUnknown(true);
    }
    return {
      response,
      original_receipt: receipt,
      local: await this.merge(key, loaded.summary.identity_sha256, receipt),
    };
  }
  /** First read original receipt; REQUESTED must commit before control POST. */
  async closeOriginal(
    key: string,
    expectedRevision: number,
    signal?: AbortSignal,
  ): Promise<{
    response: ApiSuccess<CommandCloseReceipt<unknown>> | null;
    original_receipt: CommandReceipt<unknown> | null;
    local: LocalResult;
  }> {
    positiveInteger(expectedRevision);
    const first = await this.load(key);
    if (first === null)
      return { response: null, original_receipt: null, local: await this.store.receipt(key) };
    if (first.summary.record_revision !== expectedRevision)
      throw new TypeError('Original close view changed');
    const lookup = await this.lookup(key, signal);
    if (lookup.local !== null && 'final_state' in lookup.local)
      return { response: null, ...lookup };
    // A received fact needs no further control POST and never opens replay.
    const current = await this.load(key);
    if (current === null)
      return {
        response: null,
        original_receipt: lookup.original_receipt,
        local: await this.store.receipt(key),
      };
    if (current.summary.identity_sha256 !== first.summary.identity_sha256)
      throw new TypeError('Original close identity changed');
    if (
      lookup.original_receipt?.record_status === 'PROCESSING' ||
      lookup.original_receipt?.record_status === 'SUCCEEDED'
    ) {
      const requested = await this.store.requestClose(current.summary);
      if (requested === null) throw new TypeError('Original close gate changed');
      const local = await this.merge(
        key,
        first.summary.identity_sha256,
        lookup.original_receipt,
        true,
      );
      return { response: null, original_receipt: lookup.original_receipt, local };
    }
    if (current.summary.close_state === 'ALREADY_RECEIVED')
      return { response: null, original_receipt: lookup.original_receipt, local: current.summary };
    const requested = await this.store.requestClose(current.summary);
    this.requireOpen();
    if (requested === null) throw new TypeError('Original close gate was not committed');
    const policy = await this.policy(current);
    this.requireOpen();
    const control = await prepareCloseOriginalCommand(
      this.client,
      requested,
      this.store.origin,
      policy,
    );
    this.requireOpen();
    const response = await control.submit(signal);
    const local = await this.merge(
      key,
      first.summary.identity_sha256,
      response.data.original_receipt,
      response.data.close_status === 'ALREADY_RECEIVED',
    );
    return { response, original_receipt: response.data.original_receipt, local };
  }
  async reconcileOperation(key: string, signal?: AbortSignal): Promise<LocalResult> {
    const loaded = await this.load(key);
    if (loaded === null) return this.store.receipt(key);
    const summary = loaded.summary;
    if (summary.status !== 'ACCEPTED' || summary.operation_id === null)
      throw new TypeError('No verified original operation to read');
    const value = await this.readOperation(
      loaded.original,
      {
        operation_id: summary.operation_id,
        task_id: summary.task_id,
        testing_task_id: summary.testing_task_id,
      },
      signal,
    );
    this.requireOpen();
    const row = exact(value, ['operation_id', 'task_id', 'testing_task_id', 'status']);
    if (
      row.operation_id !== summary.operation_id ||
      row.task_id !== summary.task_id ||
      row.testing_task_id !== summary.testing_task_id ||
      !['PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'UNKNOWN', 'CANCELLED'].includes(
        row.status as string,
      )
    )
      throw new TypeError('Original operation scope differs');
    if (row.status !== 'SUCCEEDED' && row.status !== 'FAILED' && row.status !== 'CANCELLED')
      return summary;
    return this.store.completeOperation(summary, summary.operation_id, row.status);
  }
}
