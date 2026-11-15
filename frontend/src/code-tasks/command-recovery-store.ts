/** One v4 IndexedDB ledger. Only transaction completion grants a send gate. */
import { object, snapshotObject, positiveInteger } from '../api/client.ts';
import { commandOrigin, verifiedCommandIdentity } from '../api/code-command-snapshot.ts';
import type { FrozenCodeCommand } from '../api/code-command-snapshot.ts';
import type { CommandReceipt } from '../api/code-command-receipts.ts';
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
  RECEIPTS = 'command_receipts',
  INTENT = 'by_origin_intent';
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
): CommandReceiptLocal {
  return receiptLocal(
    {
      schema_version: 4,
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
  private readonly name: string;
  private readonly factory: () => IDBFactory;
  private database: IDBDatabase | undefined;
  private opening: Promise<IDBDatabase> | undefined;
  private closed = false;
  private readonly active = new Set<IDBTransaction>();
  private readonly tasks = new Set<Promise<unknown>>();
  constructor(diagnostic: { origin?: string; name?: string; factory?: () => IDBFactory } = {}) {
    this.origin = commandOrigin(diagnostic.origin ?? globalThis.location.origin);
    this.name = diagnostic.name ?? 'walle-v2-code-command-recovery';
    this.factory = diagnostic.factory ?? (() => globalThis.indexedDB);
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
          pending.createIndex(INTENT, ['origin', 'intent_key'], { unique: true });
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
            !pending.indexNames.contains(INTENT)
          )
            throw new Error('Unavailable keys');
          const index = pending.index(INTENT);
          if (
            !index.unique ||
            index.multiEntry ||
            JSON.stringify(index.keyPath) !== JSON.stringify(['origin', 'intent_key'])
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
          const key = cursor.key;
          if (!Array.isArray(key) || key.length !== 2) return corrupt();
          if (key[0] === this.origin) {
            const summary = pendingSummary(cursor.value, this.origin);
            if (summary.key !== key[1]) return corrupt();
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
    const results = await Promise.all(values.map((value) => verifiedSummary(value, this.origin)));
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
      const request = pending.get([this.origin, key]);
      request.onsuccess = () => done(request.result);
    });
    if (value === undefined) return null;
    const verified = await verifiedSummary(value, this.origin);
    if (verified.key !== key) return corrupt();
    return value;
  }
  async receipt(key: string): Promise<CommandReceiptLocal | null> {
    uuid(key);
    const value = await this.transaction<unknown>('readonly', ({ receipts }, done) => {
      const request = receipts.get([this.origin, key]);
      request.onsuccess = () => done(request.result);
    });
    if (value === undefined) return null;
    const receipt = receiptLocal(value, this.origin);
    if (receipt.key !== key) return corrupt();
    await verifiedCommandIdentity(receipt, this.origin);
    return receipt;
  }
  async reserve(value: FrozenCodeCommand): Promise<ReserveResult> {
    const { frozen, recovery_mode } = await verifiedFrozen(value, this.origin);
    const now = localTime();
    const record: PendingAction = Object.freeze({
      ...frozen,
      recovery_mode,
      schema_version: 4,
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
    const encoded = pendingSize(record);
    const result = await this.transaction<
      { kind: 'PREPARED' | 'EXISTING'; value: unknown } | { kind: 'RESOLVED'; value: unknown }
    >('readwrite', ({ pending, receipts }, done, fail) => {
      const oldReceipt = receipts.get([this.origin, frozen.key]);
      oldReceipt.onsuccess = () =>
        checked(() => {
          if (oldReceipt.result !== undefined) {
            done({ kind: 'RESOLVED', value: oldReceipt.result });
            return;
          }
          const existing = pending.index(INTENT).get([this.origin, record.intent_key]);
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
                    total += pendingSize(cursor.value);
                    cursor.continue();
                    return;
                  }
                  if (count >= COMMAND_PENDING_LIMIT || total + encoded > COMMAND_PENDING_BYTES)
                    throw new CommandStorageError('CAPACITY');
                  const saved = pending.add(record, [this.origin, record.key]);
                  saved.onsuccess = () => done({ kind: 'PREPARED', value: record });
                }, fail);
            }, fail);
        }, fail);
    });
    if (result.kind === 'RESOLVED') {
      const receipt = receiptLocal(result.value, this.origin);
      if (receipt.key !== frozen.key || receipt.identity_sha256 !== frozen.identity_sha256)
        return corrupt();
      await verifiedCommandIdentity(receipt, this.origin);
      return Object.freeze({ kind: 'RESOLVED', receipt });
    }
    return Object.freeze({
      kind: result.kind,
      record: await verifiedSummary(result.value, this.origin),
    });
  }
  private async change(
    expected: PendingSummary,
    mutate: (row: Record<string, unknown>, summary: PendingSummary) => Changed | null,
  ): Promise<PendingSummary | CommandReceiptLocal | null> {
    const identity = snapshotObject(expected);
    await verifiedCommandIdentity(identity, this.origin);
    positiveInteger(identity.record_revision);
    const result = await this.transaction<{ pending?: unknown; receipt?: unknown } | null>(
      'readwrite',
      ({ pending, receipts }, done, fail) => {
        const tombstone = receipts.get([this.origin, identity.key as string]);
        tombstone.onsuccess = () =>
          checked(() => {
            if (tombstone.result !== undefined) {
              done(null);
              return;
            }
            const load = pending.get([this.origin, identity.key as string]);
            load.onsuccess = () =>
              checked(() => {
                if (load.result === undefined) {
                  done(null);
                  return;
                }
                const summary = pendingSummary(load.result, this.origin);
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
                  const receipt = receiptLocal(persistedReceipt(change.receipt), this.origin);
                  receipts.add(persistedReceipt(receipt), [this.origin, summary.key]);
                  const remove = pending.delete([this.origin, summary.key]);
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
                  const checkedSummary = pendingSummary(next, this.origin);
                  if (
                    new TextEncoder().encode(JSON.stringify(checkedSummary)).length >
                    COMMAND_METADATA_BYTES
                  )
                    throw new CommandStorageError('CAPACITY');
                  const saved = pending.put(next, [this.origin, summary.key]);
                  saved.onsuccess = () => done({ pending: next });
                } else return corrupt();
              }, fail);
          }, fail);
      },
    );
    if (result === null) return null;
    if (result.receipt !== undefined) return receiptLocal(result.receipt, this.origin);
    return verifiedSummary(result.pending, this.origin);
  }
  /** Caller already revalidated the native DTO. Gate commits before any HTTP. */
  async dispatch(
    expected: PendingSummary,
    value: FrozenCodeCommand,
    ownerId: string,
    replay = false,
  ): Promise<PendingSummary | null> {
    const owner = uuid(ownerId);
    const { frozen, recovery_mode } = await verifiedFrozen(value, this.origin);
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
      const bound = pendingSummary(merged, this.origin);
      if (original.lookup_status === 'FOUND') {
        if (original.record_status === 'CLOSED') {
          if (
            original.original_http_status !== 409 ||
            original.original_outcome?.success !== false ||
            original.original_outcome.error.code !== 'COMMAND_CLOSED'
          )
            return corrupt();
          return { receipt: terminal(bound, row, 'CLOSED_UNEXECUTED', 409, 'COMMAND_CLOSED') };
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
            receipt: terminal(bound, row, 'CONFIRMED', original.original_http_status, null),
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
      return { receipt: terminal(summary, row, 'CONFIRMED', 202, null) };
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
      return { receipt: terminal(summary, row, 'CANCELLED_UNSENT', null, null) };
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
          const key = cursor.key;
          if (!Array.isArray(key) || key.length !== 2) return corrupt();
          if (key[0] === this.origin) {
            const receipt = receiptLocal(cursor.value, this.origin);
            if (receipt.key !== key[1]) return corrupt();
            if (Date.parse(receipt.resolved_at) <= cutoff)
              found.push({ key: receipt.key, raw: JSON.stringify(cursor.value), receipt });
          }
          cursor.continue();
        }, fail);
    });
    for (const candidate of candidates)
      await verifiedCommandIdentity(candidate.receipt, this.origin);
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
        const load = receipts.get([this.origin, candidate.key]);
        load.onsuccess = () =>
          checked(() => {
            if (JSON.stringify(load.result) !== candidate.raw) {
              finished();
              return;
            }
            const remove = receipts.delete([this.origin, candidate.key]);
            remove.onsuccess = () => {
              removed++;
              finished();
            };
          }, fail);
      }
    });
  }
}
