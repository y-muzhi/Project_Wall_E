import type { Session } from './api.ts';
import {
  commandScope,
  pendingCommand,
  commandBinding,
  scopeParts,
  scopeRecord,
  type PendingCommand,
} from './command-intent.ts';
import { uuid, type operationDetail } from './model.ts';

const name = 'walle-v2.01-environment-management';
const pending = 'pending_commands';
const receipts = 'receipts';
const byIntent = 'by_scope_intent';
const commandLimit = 100;
const totalLimit = 10 * 1024 * 1024;

type Result = ReturnType<typeof operationDetail>;
type Register = Pick<PendingCommand, 'body' | 'intent_sha256' | 'submit_intent_id' | 'command_key'>;
type Store = typeof pending | typeof receipts;

export class ManagementStorageError extends Error {
  constructor(readonly reason: 'UNAVAILABLE' | 'CAPACITY' | 'CONFLICT' | 'IN_USE' | 'CORRUPT') {
    super(
      {
        UNAVAILABLE: '浏览器无法保存管理原请求，当前未开始新的派发。',
        CAPACITY: '本机待核对记录已达上限。可以先查看现有原请求。',
        CONFLICT: '本机原请求已有变化，请重新读取。',
        IN_USE: '另一标签正在处理同一原请求。',
        CORRUPT: '本机原请求无法核实，已保留记录。',
      }[reason],
    );
  }
}

function failed(error: unknown): ManagementStorageError {
  if (error instanceof ManagementStorageError) return error;
  return new ManagementStorageError(
    error instanceof DOMException && error.name === 'QuotaExceededError'
      ? 'CAPACITY'
      : 'UNAVAILABLE',
  );
}

function open(factory: IDBFactory): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = factory.open(name, 1);
    let refused = false;
    request.onupgradeneeded = (event) => {
      if (event.oldVersion !== 0) {
        request.transaction?.abort();
        return;
      }
      request.result
        .createObjectStore(pending)
        .createIndex(byIntent, ['scope_id', 'submit_intent_id'], { unique: true });
      request.result
        .createObjectStore(receipts)
        .createIndex(byIntent, ['scope_id', 'submit_intent_id'], { unique: true });
    };
    request.onblocked = () => {
      refused = true;
      reject(new ManagementStorageError('IN_USE'));
    };
    request.onerror = () => reject(failed(request.error));
    request.onsuccess = () => {
      const database = request.result;
      database.onversionchange = () => database.close();
      if (refused) database.close();
      else resolve(database);
    };
  });
}

type ReadRequest = <T>(request: IDBRequest<T>, use: (value: T) => void) => void;
type UseTransaction<T> = (
  transaction: IDBTransaction,
  complete: (value: T) => void,
  read: ReadRequest,
) => void;

// No network or digest await inside the transaction. Resolving only after oncomplete gates dispatch.
async function transact<T>(
  names: Store[],
  mode: IDBTransactionMode,
  use: UseTransaction<T>,
): Promise<T> {
  let database: IDBDatabase | undefined;
  try {
    database = await open(globalThis.indexedDB);
    const transaction = database.transaction(
      names,
      mode,
      mode === 'readwrite' ? { durability: 'strict' } : {},
    );
    return await new Promise<T>((resolve, reject) => {
      let answer: { data: T } | undefined;
      let aborted: ManagementStorageError | undefined;
      transaction.oncomplete = () => {
        if (answer) resolve(answer.data);
        else reject(new ManagementStorageError('CORRUPT'));
      };
      transaction.onabort = () => reject(aborted ?? failed(transaction.error));
      const safely = (step: () => void) => {
        try {
          step();
        } catch (error) {
          aborted = failed(error);
          transaction.abort();
        }
      };
      const read: ReadRequest = (request, method) => {
        request.onsuccess = () => safely(() => method(request.result));
      };
      safely(() =>
        use(
          transaction,
          (data) => {
            answer = { data };
          },
          read,
        ),
      );
    });
  } catch (error) {
    throw failed(error);
  } finally {
    database?.close();
  }
}

export class ManagementCommandStore {
  readonly scope;
  readonly actor;
  readonly scopeId;
  readonly #prefix;

  constructor(session: Session) {
    this.scope = commandScope(session);
    this.actor = session.principal;
    this.scopeId = JSON.stringify(scopeParts(this.scope));
    this.#prefix = this.scopeId.slice(0, -1) + ',';
  }

  key(key: string) {
    return JSON.stringify([...scopeParts(this.scope), key]);
  }

  private get range() {
    return IDBKeyRange.bound(this.#prefix, this.#prefix + '\uffff');
  }

  private entry(input: unknown): PendingCommand {
    if (typeof input !== 'object' || input === null || Array.isArray(input))
      throw new ManagementStorageError('CORRUPT');
    const { scope_id: scopeId, ...record } = input as Record<string, unknown>;
    try {
      const command = pendingCommand(record);
      if (scopeId !== this.scopeId || JSON.stringify(scopeParts(command.scope)) !== this.scopeId)
        throw new TypeError('Management scope changed');
      return command;
    } catch {
      throw new ManagementStorageError('CORRUPT');
    }
  }

  private comparable(current: PendingCommand, original: PendingCommand) {
    if (
      current.actor !== this.actor ||
      current.command_key !== original.command_key ||
      current.submit_intent_id !== original.submit_intent_id ||
      current.body !== original.body ||
      current.intent_sha256 !== original.intent_sha256 ||
      current.kind !== original.kind ||
      current.action !== original.action ||
      current.operation_id !== original.operation_id
    ) {
      throw new ManagementStorageError('CONFLICT');
    }
  }

  read(key: string): Promise<PendingCommand | null> {
    return transact([pending], 'readonly', (tx, complete, read) => {
      read(tx.objectStore(pending).get(this.key(key)), (data) => {
        const entry = data === undefined ? null : this.entry(data);
        complete(entry?.actor === this.actor ? entry : null);
      });
    });
  }

  list(): Promise<PendingCommand[]> {
    return transact([pending], 'readonly', (tx, complete, read) => {
      const all = tx.objectStore(pending);
      read(all.getAll(this.range, commandLimit + 1), (values) => {
        if (values.length > commandLimit) throw new ManagementStorageError('CAPACITY');
        complete(values.map((row) => this.entry(row)).filter((row) => row.actor === this.actor));
      });
    });
  }

  historicalGenerations(input: string): Promise<string[]> {
    const key = uuid(input);
    const prefix = JSON.stringify(scopeParts(this.scope).slice(0, 3)).slice(0, -1) + ',';
    const range = IDBKeyRange.bound(prefix, prefix + '\uffff');
    return transact([pending, receipts], 'readonly', (tx, complete, read) => {
      const found = new Set<string>();
      function keyFor(scope: ReturnType<typeof scopeRecord>) {
        return JSON.stringify([...scopeParts(scope), key]);
      }
      const inspect = (cursor: IDBCursorWithValue) => {
        const row: unknown = cursor.value;
        if (typeof row !== 'object' || row === null || Array.isArray(row)) return;
        const record = row as Record<string, unknown>;
        if (record.actor !== this.actor || record.command_key !== key || record.kind !== 'ACTION')
          return;
        try {
          const scope = scopeRecord(record.scope);
          if (
            scope.origin !== this.scope.origin ||
            scope.manager_id !== this.scope.manager_id ||
            record.scope_id !== JSON.stringify(scopeParts(scope)) ||
            cursor.primaryKey !== keyFor(scope)
          )
            throw new TypeError('Management history scope differs from its original key');
          if (scope.registry_generation !== this.scope.registry_generation)
            found.add(scope.registry_generation);
        } catch {
          throw new ManagementStorageError('CORRUPT');
        }
      };
      function scan(store: Store, finished: () => void) {
        read(tx.objectStore(store).openCursor(range), (cursor) => {
          if (cursor === null) {
            finished();
            return;
          }
          inspect(cursor);
          cursor.continue();
        });
      }
      scan(pending, () => scan(receipts, () => complete([...found].sort())));
    });
  }

  persist(original: Register, operationId: string | null = null): Promise<PendingCommand> {
    const binding = commandBinding(original.body, operationId);
    const command: PendingCommand = {
      record_version: 1,
      ...binding,
      scope: this.scope,
      actor: this.actor,
      ...original,
      method: 'POST',
      revision: 1,
      dispatch_owner: null,
      state: 'PREPARED',
    };
    pendingCommand(command);
    return transact([pending, receipts], 'readwrite', (tx, complete, read) => {
      const commands = tx.objectStore(pending);
      const localId = [this.scopeId, command.submit_intent_id];
      // Slot survives terminal completion in the receipts store, so a delayed duplicate is safe.
      read(tx.objectStore(receipts).index(byIntent).getKey(localId), (finished) => {
        if (finished !== undefined) throw new ManagementStorageError('CONFLICT');
        read(commands.index(byIntent).get(localId), (existing) => {
          if (existing !== undefined) {
            const value = this.entry(existing);
            this.comparable(value, command);
            complete(value);
            return;
          }
          const data = { ...command, scope_id: this.scopeId };
          read(commands.getAll(this.range, commandLimit), (rows) => {
            const encoder = new TextEncoder();
            let size = encoder.encode(JSON.stringify(data)).byteLength;
            for (const row of rows) {
              this.entry(row);
              size += encoder.encode(JSON.stringify(row)).byteLength;
            }
            if (rows.length >= commandLimit || size > totalLimit)
              throw new ManagementStorageError('CAPACITY');
            commands.add(data, this.key(command.command_key));
            complete(command);
          });
        });
      });
    });
  }

  claim(original: PendingCommand, owner: string): Promise<PendingCommand> {
    return transact([pending], 'readwrite', (tx, complete, read) => {
      const store = tx.objectStore(pending);
      const key = this.key(original.command_key);
      read(store.get(key), (data) => {
        if (data === undefined) throw new ManagementStorageError('CONFLICT');
        const current = this.entry(data);
        this.comparable(current, original);
        if (current.revision !== original.revision) throw new ManagementStorageError('CONFLICT');
        const updated = pendingCommand({
          ...current,
          state: 'DISPATCHING',
          dispatch_owner: owner,
          revision: current.revision + 1,
        });
        store.put({ ...updated, scope_id: this.scopeId }, key);
        complete(updated);
      });
    });
  }

  uncertain(claim: PendingCommand): Promise<void> {
    return transact([pending], 'readwrite', (tx, complete, read) => {
      const store = tx.objectStore(pending);
      const key = this.key(claim.command_key);
      read(store.get(key), (data) => {
        if (data !== undefined) {
          const current = this.entry(data);
          this.comparable(current, claim);
          if (
            current.dispatch_owner === claim.dispatch_owner &&
            current.revision === claim.revision
          ) {
            const updated = pendingCommand({
              ...current,
              state: 'UNCERTAIN',
              dispatch_owner: null,
              revision: current.revision + 1,
            });
            store.put({ ...updated, scope_id: this.scopeId }, key);
          }
        }
        complete(undefined);
      });
    });
  }

  finish(original: PendingCommand, result: Result): Promise<void> {
    return transact([pending, receipts], 'readwrite', (tx, complete, read) => {
      const store = tx.objectStore(pending);
      const key = this.key(original.command_key);
      read(store.get(key), (data) => {
        if (data !== undefined) {
          const current = this.entry(data);
          this.comparable(current, original);
          const { original: outcome } = result;
          tx.objectStore(receipts).add(
            {
              record_version: 1,
              kind: current.kind,
              scope: current.scope,
              scope_id: this.scopeId,
              actor: current.actor,
              submit_intent_id: current.submit_intent_id,
              command_key: current.command_key,
              method: current.method,
              path: current.path,
              intent_sha256: current.intent_sha256,
              target: current.target,
              target_version: current.target_version,
              action: current.action,
              operation_id: outcome.id,
              status: outcome.state,
              revision: outcome.revision,
            },
            key,
          );
          store.delete(key);
        }
        complete(undefined);
      });
    });
  }
}
