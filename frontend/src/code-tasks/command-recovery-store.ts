/** Only a committed transaction in the original ledger can grant a send gate. */
import { object, snapshotObject, positiveInteger } from '../api/client.ts';
import { commandOrigin, verifiedCommandIdentity } from '../api/code-command-snapshot.ts';
import type { FrozenCodeCommand } from '../api/code-command-snapshot.ts';
import type { CommandReceipt } from '../api/code-command-receipts.ts';
import { decodeEnvironmentScope, type EnvironmentScope } from '../api/environment-binding.ts';
import {
  pendingSummary,
  verifiedSummary,
  verifiedFrozen,
  pendingSize,
  uuid,
  digest,
  receiptLocal,
  persistedReceipt,
  COMMAND_PENDING_LIMIT,
  COMMAND_PENDING_BYTES,
  COMMAND_METADATA_BYTES,
  IMMUTABLE_FIELDS,
} from './command-recovery-model.ts';
import type {
  PendingSummary,
  PendingAction,
  CommandReceiptLocal,
} from './command-recovery-model.ts';

export class CommandStorageError extends Error {
  readonly reason: 'UNAVAILABLE' | 'CAPACITY' | 'CORRUPT';
  constructor(reason: 'UNAVAILABLE' | 'CAPACITY' | 'CORRUPT') {
    super(
      reason === 'CAPACITY'
        ? '待核对操作暂存容量不足，原输入已保留'
        : reason === 'CORRUPT'
          ? '原请求记录无法完整核实，请保留记录并核对原结果'
          : '待核对操作暂存不可用，请保留原输入并核对原结果',
    );
    this.reason = reason;
  }
}
const PENDING = 'pending_commands',
  RECEIPTS = 'command_receipts';
type Stores = { pending: IDBObjectStore; receipts: IDBObjectStore };
type Complete<T> = (value: T) => void;
type Fail = (error: CommandStorageError) => void;
type Changed = { pending?: Record<string, unknown>; receipt?: CommandReceiptLocal };
type ReserveResult =
  | Readonly<{ kind: 'PREPARED' | 'EXISTING'; record: PendingSummary }>
  | Readonly<{ kind: 'RESOLVED'; receipt: CommandReceiptLocal }>;
function reason(error: unknown): CommandStorageError {
  if (error instanceof CommandStorageError) return error;
  if (error instanceof DOMException && error.name === 'QuotaExceededError')
    return new CommandStorageError('CAPACITY');
  return new CommandStorageError('UNAVAILABLE');
}
function corrupt(): never {
  throw new CommandStorageError('CORRUPT');
}
function checked<T>(body: () => T, fail: Fail): void {
  try {
    body();
  } catch (error) {
    fail(
      error instanceof CommandStorageError || error instanceof DOMException
        ? reason(error)
        : new CommandStorageError('CORRUPT'),
    );
  }
}
function nextRevision(value: number): number {
  if (value === Number.MAX_SAFE_INTEGER) throw new CommandStorageError('CAPACITY');
  return value + 1;
}
function localTime(previous?: string): string {
  const now = new Date().toISOString();
  return previous !== undefined && now < previous ? previous : now;
}
function bodyDigest(row: Record<string, unknown>, allowMissing: boolean): string | null {
  try {
    return digest(row.body_sha256);
  } catch {
    if (allowMissing) return null;
    return corrupt();
  }
}
function terminal(
  summary: PendingSummary,
  row: Record<string, unknown>,
  state: CommandReceiptLocal['final_state'],
  status: number | null,
  code: string | null,
  scope: EnvironmentScope | undefined,
): CommandReceiptLocal {
  return receiptLocal(
    {
      schema_version: summary.schema_version,
      ...(scope
        ? {
            scope_version: 1,
            environment_id: scope.environment_id,
            data_generation: scope.data_generation,
          }
        : {}),
      owner_module: summary.owner_module,
      origin: summary.origin,
      key: summary.key,
      method: summary.method,
      path: summary.path,
      identity_sha256: summary.identity_sha256,
      body_sha256: bodyDigest(row, state === 'CLOSED_UNEXECUTED'),
      final_state: state,
      task_id: summary.task_id,
      testing_task_id: summary.testing_task_id,
      operation_id: summary.operation_id,
      http_status: status,
      result_code: code,
      resolved_at: localTime(summary.updated_at),
    },
    summary.origin,
    scope,
  );
}
function observed(
  summary: PendingSummary,
  receipt: CommandReceipt<unknown>,
): Record<string, unknown> {
  const updates: Record<string, unknown> = { lookup_status: receipt.lookup_status };
  for (const field of ['task_id', 'testing_task_id', 'operation_id'] as const) {
    const actual = receipt[field],
      previous = summary[field];
    if (actual !== null) positiveInteger(actual);
    if (previous !== null && actual !== null && previous !== actual) return corrupt();
    updates[field] = actual ?? previous;
  }
  if (
    receipt.lookup_status === 'FOUND' &&
    receipt.record_status === 'SUCCEEDED' &&
    receipt.original_http_status === 202
  ) {
    if (receipt.operation_id === null) return corrupt();
    updates.status = 'ACCEPTED';
  }
  return updates;
}

export class CommandRecoveryStore {
  readonly origin: string;
  readonly scope: EnvironmentScope | undefined;
  private readonly name: string;
  private readonly intentIndex: string;
  private readonly intentFields: string[];
  private readonly factory: () => IDBFactory;
  private database: IDBDatabase | undefined;
  private opening: Promise<IDBDatabase> | undefined;
  private closed = false;
  private readonly active = new Set<IDBTransaction>();
  private readonly tasks = new Set<Promise<unknown>>();
  constructor(
    diagnostic: {
      origin?: string;
      name?: string;
      factory?: () => IDBFactory;
      scope?: EnvironmentScope | undefined;
    } = {},
  ) {
    this.scope = diagnostic.scope ? decodeEnvironmentScope(diagnostic.scope) : undefined;
    this.origin = commandOrigin(
      diagnostic.origin ?? this.scope?.origin ?? globalThis.location.origin,
    );
    if (this.scope && this.scope.origin !== this.origin)
      throw new TypeError('Command ledger origin differs from the bound environment');
    this.name =
      diagnostic.name ??
      (this.scope ? 'walle-v2.01-code-command-recovery' : 'walle-v2-code-command-recovery');
    this.intentIndex = this.scope ? 'by_scope_intent' : 'by_origin_intent';
    this.intentFields = this.scope
      ? ['origin', 'environment_id', 'data_generation', 'intent_key']
      : ['origin', 'intent_key'];
    this.factory = diagnostic.factory ?? (() => globalThis.indexedDB);
  }

  private key(last: string): string[] {
    return this.scope
      ? [this.origin, this.scope.environment_id, this.scope.data_generation, last]
      : [this.origin, last];
  }

  private primaryKey(value: IDBValidKey): string[] {
    if (
      !Array.isArray(value) ||
      value.length !== (this.scope ? 4 : 2) ||
      value.some((part) => typeof part !== 'string')
    )
      return corrupt();
    return value as string[];
  }

  private ownsKey(key: string[]): boolean {
    return (
      key[0] === this.origin &&
      (!this.scope ||
        (key[1] === this.scope.environment_id && key[2] === this.scope.data_generation))
    );
  }

  private storedBytes(cursor: IDBCursorWithValue): number {
    if (!this.scope) return pendingSize(cursor.value);
    const key = this.primaryKey(cursor.key);
    if (key[0] !== this.origin) return corrupt();
    const scope = decodeEnvironmentScope({
      binding_protocol: 1,
      origin: key[0],
      environment_id: key[1],
      data_generation: key[2],
    });
    const summary = pendingSummary(cursor.value, scope.origin, scope);
    if (summary.key !== key[3]) return corrupt();
    return pendingSize(cursor.value, scope);
  }
  private disconnect(): void {
    for (const transaction of this.active) {
      try {
        transaction.abort();
      } catch {
        /* Already settled; no new gate. */
      }
    }
    this.database?.close();
    this.database = undefined;
    this.opening = undefined;
  }
  close(): void {
    this.closed = true;
    this.disconnect();
  }
  async settle(): Promise<void> {
    while (this.tasks.size) await Promise.allSettled([...this.tasks]);
  }
  private open(): Promise<IDBDatabase> {
    if (this.closed) return Promise.reject(new CommandStorageError('UNAVAILABLE'));
    if (this.opening) return this.opening;
    this.opening = new Promise((resolve, reject) => {
      let request: IDBOpenDBRequest;
      try {
        request = this.factory().open(this.name, 1);
      } catch {
        reject(new CommandStorageError('UNAVAILABLE'));
        return;
      }
      let refused = false;
      const refuse = () => {
        refused = true;
        reject(new CommandStorageError('UNAVAILABLE'));
      };
      request.onblocked = refuse;
      request.onerror = () => {
        refused = true;
        reject(reason(request.error));
      };
      request.onupgradeneeded = () => {
        if (this.closed || refused) {
          request.transaction?.abort();
          return;
        }
        try {
          const pending = request.result.createObjectStore(PENDING);
          pending.createIndex(this.intentIndex, this.intentFields, { unique: true });
          request.result.createObjectStore(RECEIPTS);
        } catch {
          refuse();
          request.transaction?.abort();
        }
      };
      request.onsuccess = () => {
        const database = request.result;
        try {
          if (
            this.closed ||
            refused ||
            database.version !== 1 ||
            database.objectStoreNames.length !== 2 ||
            !database.objectStoreNames.contains(PENDING) ||
            !database.objectStoreNames.contains(RECEIPTS)
          )
            throw new Error('Unavailable stores');
          const transaction = database.transaction([PENDING, RECEIPTS], 'readonly');
          const pending = transaction.objectStore(PENDING),
            receipts = transaction.objectStore(RECEIPTS);
          if (
            pending.keyPath !== null ||
            receipts.keyPath !== null ||
            pending.autoIncrement ||
            receipts.autoIncrement ||
            !pending.indexNames.contains(this.intentIndex) ||
            (this.scope && (pending.indexNames.length !== 1 || receipts.indexNames.length !== 0))
          )
            throw new Error('Unavailable keys');
          const index = pending.index(this.intentIndex);
          if (
            !index.unique ||
            index.multiEntry ||
            JSON.stringify(index.keyPath) !== JSON.stringify(this.intentFields)
          )
            throw new Error('Unavailable index');
          this.database = database;
          database.onversionchange = () => this.close();
          resolve(database);
        } catch {
          database.close();
          refuse();
        }
      };
    });
    return this.opening;
  }
  private transaction<T>(
    mode: IDBTransactionMode,
    perform: (stores: Stores, complete: Complete<T>, fail: Fail) => void,
  ): Promise<T> {
    const task = this.runTransaction(mode, perform);
    this.tasks.add(task);
    void task.then(
      () => this.tasks.delete(task),
      () => this.tasks.delete(task),
    );
    return task;
  }
  private async runTransaction<T>(
    mode: IDBTransactionMode,
    perform: (stores: Stores, complete: Complete<T>, fail: Fail) => void,
  ): Promise<T> {
    const database = await this.open();
    if (this.closed || database !== this.database) throw new CommandStorageError('UNAVAILABLE');
    return new Promise((resolve, reject) => {
      let transaction: IDBTransaction;
      try {
        transaction = database.transaction([PENDING, RECEIPTS], mode, { durability: 'strict' });
      } catch (error) {
        this.disconnect();
        reject(reason(error));
        return;
      }
      this.active.add(transaction);
      let output: T,
        produced = false,
        failure: CommandStorageError | undefined;
      const fail: Fail = (error) => {
        failure = error;
        try {
          transaction.abort();
        } catch {
          reject(error);
        }
      };
      transaction.onerror = () => {
        failure ??= reason(transaction.error);
      };
      transaction.onabort = () => {
        this.active.delete(transaction);
        // A logical capacity/CAS refusal preserves records; storage failures drop this connection.
        if (failure?.reason !== 'CAPACITY' && failure?.reason !== 'CORRUPT') this.disconnect();
        reject(failure ?? reason(transaction.error));
      };
      transaction.oncomplete = () => {
        this.active.delete(transaction);
        if (!produced || this.closed || database !== this.database)
          reject(new CommandStorageError('UNAVAILABLE'));
        else resolve(output);
      };
      try {
        perform(
          {
            pending: transaction.objectStore(PENDING),
            receipts: transaction.objectStore(RECEIPTS),
          },
          (value) => {
            output = value;
            produced = true;
          },
          fail,
        );
      } catch (error) {
        fail(reason(error));
      }
    });
  }
  async list(): Promise<readonly PendingSummary[]> {
    const values = await this.transaction<unknown[]>('readonly', ({ pending }, done, fail) => {
      const rows: unknown[] = [];
      const request = pending.openCursor();
      request.onsuccess = () =>
        checked(() => {
          const cursor = request.result;
          if (!cursor) {
            done(rows);
            return;
          }
          const key = this.primaryKey(cursor.key);
          if (this.ownsKey(key)) {
            const summary = pendingSummary(cursor.value, this.origin, this.scope);
            if (summary.key !== key.at(-1)) return corrupt();
            // Never pass original body into a list owner.
            rows.push(
              Object.fromEntries([
                ...Object.entries(summary),
                ['body_json', null],
                ['body_sha256', null],
                ['recovery_mode', null],
              ]),
            );
          }
          cursor.continue();
        }, fail);
    });
    const results = await Promise.all(
      values.map((value) => verifiedSummary(value, this.origin, this.scope)),
    );
    return Object.freeze(
      results.sort(
        (a, b) => a.created_at.localeCompare(b.created_at) || a.key.localeCompare(b.key),
      ),
    );
  }
  /** Explicit detail only; lists never return body. No implicit restore/send. */
  async detail(key: string): Promise<unknown | null> {
    uuid(key);
    const value = await this.transaction<unknown>('readonly', ({ pending }, done) => {
      const request = pending.get(this.key(key));
      request.onsuccess = () => done(request.result);
    });
    if (value === undefined) return null;
    const verified = await verifiedSummary(value, this.origin, this.scope);
    if (verified.key !== key) return corrupt();
    return value;
  }
  async receipt(key: string): Promise<CommandReceiptLocal | null> {
    uuid(key);
    const value = await this.transaction<unknown>('readonly', ({ receipts }, done) => {
      const request = receipts.get(this.key(key));
      request.onsuccess = () => done(request.result);
    });
    if (value === undefined) return null;
    const receipt = receiptLocal(value, this.origin, this.scope);
    if (receipt.key !== key) return corrupt();
    await verifiedCommandIdentity(receipt, this.origin, this.scope);
    return receipt;
  }
  async reserve(value: FrozenCodeCommand): Promise<ReserveResult> {
    const { frozen, recovery_mode } = await verifiedFrozen(value, this.origin, this.scope);
    const now = localTime();
    const record: PendingAction = Object.freeze({
      ...frozen,
      recovery_mode,
      schema_version: this.scope ? 5 : 4,
      intent_key: frozen.method + ' ' + frozen.path,
      close_state: 'NONE',
      close_requested_at: null,
      status: 'PREPARED',
      task_id: null,
      testing_task_id: null,
      operation_id: null,
      created_at: now,
      updated_at: now,
      submitted_at: null,
      dispatch_count: 0,
      dispatch_owner_id: null,
      record_revision: 1,
      lookup_status: null,
    });
    const encoded = pendingSize(record, this.scope);
    const result = await this.transaction<
      { kind: 'PREPARED' | 'EXISTING'; value: unknown } | { kind: 'RESOLVED'; value: unknown }
    >('readwrite', ({ pending, receipts }, done, fail) => {
      const oldReceipt = receipts.get(this.key(frozen.key));
      oldReceipt.onsuccess = () =>
        checked(() => {
          if (oldReceipt.result !== undefined) {
            done({ kind: 'RESOLVED', value: oldReceipt.result });
            return;
          }
          const existing = pending.index(this.intentIndex).get(this.key(record.intent_key));
          existing.onsuccess = () =>
            checked(() => {
              if (existing.result !== undefined) {
                done({ kind: 'EXISTING', value: existing.result });
                return;
              }
              let count = 0,
                total = 0;
              const scan = pending.openCursor();
              scan.onsuccess = () =>
                checked(() => {
                  const cursor = scan.result;
                  if (cursor) {
                    count++;
                    total += this.storedBytes(cursor);
                    cursor.continue();
                    return;
                  }
                  if (count >= COMMAND_PENDING_LIMIT || total + encoded > COMMAND_PENDING_BYTES)
                    throw new CommandStorageError('CAPACITY');
                  const saved = pending.add(record, this.key(record.key));
                  saved.onsuccess = () => done({ kind: 'PREPARED', value: record });
                }, fail);
            }, fail);
        }, fail);
    });
    if (result.kind === 'RESOLVED') {
      const receipt = receiptLocal(result.value, this.origin, this.scope);
      if (receipt.key !== frozen.key || receipt.identity_sha256 !== frozen.identity_sha256)
        return corrupt();
      await verifiedCommandIdentity(receipt, this.origin, this.scope);
      return Object.freeze({ kind: 'RESOLVED', receipt });
    }
    return Object.freeze({
      kind: result.kind,
      record: await verifiedSummary(result.value, this.origin, this.scope),
    });
  }
  private async change(
    expected: PendingSummary,
    mutate: (row: Record<string, unknown>, summary: PendingSummary) => Changed | null,
  ): Promise<PendingSummary | CommandReceiptLocal | null> {
    const identity = snapshotObject(expected);
    await verifiedCommandIdentity(identity, this.origin, this.scope);
    positiveInteger(identity.record_revision);
    const result = await this.transaction<{ pending?: unknown; receipt?: unknown } | null>(
      'readwrite',
      ({ pending, receipts }, done, fail) => {
        const tombstone = receipts.get(this.key(identity.key as string));
        tombstone.onsuccess = () =>
          checked(() => {
            if (tombstone.result !== undefined) {
              done(null);
              return;
            }
            const load = pending.get(this.key(identity.key as string));
            load.onsuccess = () =>
              checked(() => {
                if (load.result === undefined) {
                  done(null);
                  return;
                }
                const summary = pendingSummary(load.result, this.origin, this.scope);
                if (
                  summary.record_revision !== identity.record_revision ||
                  summary.identity_sha256 !== identity.identity_sha256 ||
                  summary.method !== identity.method ||
                  summary.path !== identity.path ||
                  summary.key !== identity.key ||
                  summary.owner_module !== identity.owner_module ||
                  summary.decoder_kind !== identity.decoder_kind
                ) {
                  done(null);
                  return;
                }
                const row = object(load.result);
                const change = mutate(row, summary);
                if (change === null) {
                  done(null);
                  return;
                }
                if (change.receipt !== undefined) {
                  const receipt = receiptLocal(
                    persistedReceipt(change.receipt),
                    this.origin,
                    this.scope,
                  );
                  receipts.add(persistedReceipt(receipt), this.key(summary.key));
                  const remove = pending.delete(this.key(summary.key));
                  remove.onsuccess = () => done({ receipt: persistedReceipt(receipt) });
                } else if (change.pending !== undefined) {
                  const next: Record<string, unknown> = {
                    ...change.pending,
                    record_revision: nextRevision(summary.record_revision),
                    updated_at: localTime(summary.updated_at),
                  };
                  for (const field of IMMUTABLE_FIELDS) {
                    if (next[field] !== row[field]) return corrupt();
                  }
                  const checkedSummary = pendingSummary(next, this.origin, this.scope);
                  if (
                    new TextEncoder().encode(JSON.stringify(checkedSummary)).length >
                    COMMAND_METADATA_BYTES
                  )
                    throw new CommandStorageError('CAPACITY');
                  const saved = pending.put(next, this.key(summary.key));
                  saved.onsuccess = () => done({ pending: next });
                } else return corrupt();
              }, fail);
          }, fail);
      },
    );
    if (result === null) return null;
    if (result.receipt !== undefined) return receiptLocal(result.receipt, this.origin, this.scope);
    return verifiedSummary(result.pending, this.origin, this.scope);
  }
  /** Caller already revalidated the native DTO. Gate commits before any HTTP. */
  async dispatch(
    expected: PendingSummary,
    value: FrozenCodeCommand,
    ownerId: string,
    replay = false,
  ): Promise<PendingSummary | null> {
    const owner = uuid(ownerId);
    const { frozen, recovery_mode } = await verifiedFrozen(value, this.origin, this.scope);
    if (frozen.identity_sha256 !== expected.identity_sha256) return corrupt();
    const result = await this.change(expected, (row, summary) => {
      for (const [field, entry] of Object.entries(frozen))
        if (row[field] !== entry) return corrupt();
      if (row.recovery_mode !== recovery_mode || summary.close_state !== 'NONE') return null;
      if (replay) {
        if (recovery_mode !== 'REPLAY_SAME_KEY' || summary.dispatch_count === 0) return null;
      } else if (summary.status !== 'PREPARED' || summary.dispatch_count !== 0) return null;
      return {
        pending: {
          ...row,
          status: 'DISPATCHING',
          lookup_status: null,
          submitted_at: localTime(summary.updated_at),
          dispatch_owner_id: owner,
          dispatch_count: nextRevision(summary.dispatch_count),
        },
      };
    });
    return result as PendingSummary | null;
  }
  /** Restore the local pre-dispatch state only when transport refused before
   * invoking fetch and the gate still belongs to that exact reservation. */
  async restoreUnsent(gate: PendingSummary, before: PendingSummary): Promise<void> {
    if (
      gate.identity_sha256 !== before.identity_sha256 ||
      gate.key !== before.key ||
      gate.status !== 'DISPATCHING' ||
      gate.dispatch_count !== before.dispatch_count + 1 ||
      gate.record_revision !== before.record_revision + 1
    )
      return corrupt();
    await this.change(gate, (row) => ({
      pending: {
        ...row,
        status: before.status,
        dispatch_count: before.dispatch_count,
        submitted_at: before.submitted_at,
        dispatch_owner_id: before.dispatch_owner_id,
        lookup_status: before.lookup_status,
      },
    }));
  }

  async requestClose(expected: PendingSummary): Promise<PendingSummary | null> {
    const result = await this.change(expected, (row, summary) => {
      if (summary.close_state !== 'NONE') return { pending: row };
      return {
        pending: {
          ...row,
          close_state: 'REQUESTED',
          close_requested_at: localTime(summary.updated_at),
        },
      };
    });
    return result as PendingSummary | null;
  }
  async markUnknown(expected: PendingSummary): Promise<PendingSummary | null> {
    const result = await this.change(expected, (row, summary) =>
      summary.dispatch_count === 0
        ? null
        : { pending: { ...row, status: summary.status === 'ACCEPTED' ? 'ACCEPTED' : 'UNKNOWN' } },
    );
    return result as PendingSummary | null;
  }
  /** Accept only strictly decoded original receipts from the API owner. */
  async observe(
    expected: PendingSummary,
    receipt: CommandReceipt<unknown>,
    closeAlreadyReceived = false,
  ): Promise<PendingSummary | CommandReceiptLocal | null> {
    const observation = snapshotObject(receipt);
    return this.change(expected, (row, summary) => {
      const original = observation as CommandReceipt<unknown>;
      const updates = observed(summary, original);
      const merged = { ...row, ...updates };
      if (closeAlreadyReceived) {
        if (
          summary.close_state === 'NONE' ||
          (original.record_status !== 'PROCESSING' &&
            original.record_status !== 'SUCCEEDED' &&
            original.record_status !== 'REJECTED')
        )
          return corrupt();
        merged.close_state = 'ALREADY_RECEIVED';
      }
      // Associations are from the original receipt, not caller-entered navigation.
      const bound = pendingSummary(merged, this.origin, this.scope);
      if (original.lookup_status === 'FOUND') {
        if (original.record_status === 'CLOSED') {
          if (
            original.original_http_status !== 409 ||
            original.original_outcome?.success !== false ||
            original.original_outcome.error.code !== 'COMMAND_CLOSED'
          )
            return corrupt();
          return {
            receipt: terminal(bound, row, 'CLOSED_UNEXECUTED', 409, 'COMMAND_CLOSED', this.scope),
          };
        }
        if (original.record_status === 'REJECTED') {
          if (
            original.original_outcome?.success !== false ||
            original.original_http_status === null ||
            original.original_http_status < 400 ||
            original.original_http_status > 499
          )
            return corrupt();
          return {
            receipt: terminal(
              bound,
              row,
              'REJECTED',
              original.original_http_status,
              original.original_outcome.error.code,
              this.scope,
            ),
          };
        }
        if (original.record_status === 'SUCCEEDED' && original.original_http_status !== 202) {
          if (
            original.original_outcome?.success !== true ||
            (original.original_http_status !== 200 && original.original_http_status !== 201)
          )
            return corrupt();
          return {
            receipt: terminal(
              bound,
              row,
              'CONFIRMED',
              original.original_http_status,
              null,
              this.scope,
            ),
          };
        }
      }
      return { pending: merged };
    });
  }
  async completeOperation(
    expected: PendingSummary,
    operationId: number,
    operationStatus: 'SUCCEEDED' | 'FAILED' | 'CANCELLED',
  ): Promise<CommandReceiptLocal | null> {
    positiveInteger(operationId);
    if (!['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(operationStatus)) return corrupt();
    const result = await this.change(expected, (row, summary) => {
      if (summary.status !== 'ACCEPTED' || summary.operation_id !== operationId) return null;
      return { receipt: terminal(summary, row, 'CONFIRMED', 202, null, this.scope) };
    });
    return result as CommandReceiptLocal | null;
  }
  async cancelUnsent(expected: PendingSummary): Promise<CommandReceiptLocal | null> {
    const result = await this.change(expected, (row, summary) => {
      if (
        summary.status !== 'PREPARED' ||
        summary.lookup_status !== null ||
        summary.dispatch_count !== 0 ||
        summary.close_state !== 'NONE' ||
        summary.submitted_at !== null
      )
        return null;
      return { receipt: terminal(summary, row, 'CANCELLED_UNSENT', null, null, this.scope) };
    });
    return result as CommandReceiptLocal | null;
  }
  /** Never prune pending records. Explicit maintenance removes only old tombstones. */
  async pruneResolved(now: string): Promise<number> {
    const instant = Date.parse(now);
    if (!Number.isFinite(instant) || new Date(instant).toISOString() !== now) return corrupt();
    const cutoff = instant - 30 * 24 * 60 * 60 * 1000;
    const candidates = await this.transaction<
      { key: string; raw: string; receipt: CommandReceiptLocal }[]
    >('readonly', ({ receipts }, done, fail) => {
      const found: { key: string; raw: string; receipt: CommandReceiptLocal }[] = [];
      const scan = receipts.openCursor();
      scan.onsuccess = () =>
        checked(() => {
          const cursor = scan.result;
          if (!cursor) {
            done(found);
            return;
          }
          const key = this.primaryKey(cursor.key);
          if (this.ownsKey(key)) {
            const receipt = receiptLocal(cursor.value, this.origin, this.scope);
            if (receipt.key !== key.at(-1)) return corrupt();
            if (Date.parse(receipt.resolved_at) <= cutoff)
              found.push({ key: receipt.key, raw: JSON.stringify(cursor.value), receipt });
          }
          cursor.continue();
        }, fail);
    });
    for (const candidate of candidates)
      await verifiedCommandIdentity(candidate.receipt, this.origin, this.scope);
    return this.transaction<number>('readwrite', ({ receipts }, done, fail) => {
      let left = candidates.length,
        removed = 0;
      if (left === 0) {
        done(0);
        return;
      }
      const finished = () => {
        if (--left === 0) done(removed);
      };
      for (const candidate of candidates) {
        const load = receipts.get(this.key(candidate.key));
        load.onsuccess = () =>
          checked(() => {
            if (JSON.stringify(load.result) !== candidate.raw) {
              finished();
              return;
            }
            const remove = receipts.delete(this.key(candidate.key));
            remove.onsuccess = () => {
              removed++;
              finished();
            };
          }, fail);
      }
    });
  }
}
