/** Shared DB2 connection and durable transaction gate; no business dispatch. */
import { commandOrigin } from '../api/code-command-snapshot.ts';
export class CommandStorageError extends Error {
  readonly reason: 'UNAVAILABLE' | 'CAPACITY' | 'CORRUPT' | 'BLOCKED' | 'VERSION';
  constructor(reason: 'UNAVAILABLE' | 'CAPACITY' | 'CORRUPT' | 'BLOCKED' | 'VERSION') {
    super(
      reason === 'CAPACITY'
        ? '待核对操作暂存容量不足，原输入已保留'
        : reason === 'CORRUPT'
          ? '原请求记录无法完整核实，请保留记录并核对原结果'
          : reason === 'BLOCKED'
            ? '恢复记录升级中，请刷新或关闭旧版本标签页'
            : reason === 'VERSION'
              ? '恢复记录版本较新，请使用兼容版本打开'
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
export function reason(error: unknown): CommandStorageError {
  if (error instanceof CommandStorageError) return error;
  if (error instanceof DOMException && error.name === 'QuotaExceededError')
    return new CommandStorageError('CAPACITY');
  return new CommandStorageError('UNAVAILABLE');
}
export function corrupt(): never {
  throw new CommandStorageError('CORRUPT');
}
export function checked<T>(body: () => T, fail: Fail): void {
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
export class CommandLedger {
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
        request = this.factory().open(this.name, 2);
      } catch {
        reject(new CommandStorageError('UNAVAILABLE'));
        return;
      }
      let refused = false;
      const refuse = () => {
        refused = true;
        reject(new CommandStorageError('UNAVAILABLE'));
      };
      request.onblocked = () => {
        refused = true;
        reject(new CommandStorageError('BLOCKED'));
      };
      request.onerror = () => {
        refused = true;
        reject(
          request.error?.name === 'VersionError'
            ? new CommandStorageError('VERSION')
            : reason(request.error),
        );
      };
      request.onupgradeneeded = (event) => {
        if (this.closed || refused) {
          request.transaction?.abort();
          return;
        }
        try {
          if (event.oldVersion !== 0) return;
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
            database.version !== 2 ||
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
  protected transaction<T>(
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
}
