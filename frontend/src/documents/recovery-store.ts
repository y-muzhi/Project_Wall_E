import type { Ctx } from '@milkdown/kit/ctx';
import { validateBlockState } from './contracts.ts';
import type { BlockState, DocumentReadModel } from './contracts.ts';
import { exact, positiveInteger, snapshotObject } from '../api/client.ts';
import { time } from '../api/decoding.ts';

export type LocalDraftSnapshot = Readonly<{ schema_version: 1; base_confirmed_version: number; markdown_content: string;
  block_state_json: BlockState; local_revision: number; updated_at: string }>;
export class DraftStorageError extends Error {
  readonly reason: 'UNAVAILABLE' | 'CAPACITY' | 'CORRUPT';
  constructor(reason: 'UNAVAILABLE' | 'CAPACITY' | 'CORRUPT') { super(reason === 'CAPACITY' ? '本地暂存容量已满，请保持页面或导出未同步内容' : '本地暂存不可用，请保持页面以免丢失未同步内容'); this.reason = reason; }
}
export const DRAFT_BYTES = 8 * 1024 * 1024, TOTAL_DRAFT_BYTES = 160 * 1024 * 1024, DRAFT_RECORDS = 20;
const storeName = 'draft_snapshots';
function bytes(value: unknown): number { return new TextEncoder().encode(JSON.stringify(snapshotObject(value))).length; }
function key(requirement: number, draft: number): [number, number] { return [positiveInteger(requirement), positiveInteger(draft)]; }

/** Local intentions, not a server DocumentReadModel or saved receipt. */
export function validateLocalDraftSnapshot(ctx:Ctx,value:unknown):LocalDraftSnapshot {
  try{
    const row=exact(value,['schema_version','base_confirmed_version','markdown_content','block_state_json','local_revision','updated_at']);
    if(row.schema_version!==1)throw new TypeError('Invalid local schema');
    positiveInteger(row.base_confirmed_version);positiveInteger(row.local_revision);time(row.updated_at);
    const pair=validateBlockState(ctx,row.markdown_content,row.block_state_json);
    return Object.freeze({schema_version:1,base_confirmed_version:row.base_confirmed_version as number,
      markdown_content:pair.source.markdown,block_state_json:pair.state,local_revision:row.local_revision as number,updated_at:row.updated_at as string});
  }catch{throw new DraftStorageError('CORRUPT');}
}

/** The caller offers RESTORE only after it has read actual draft/occupancy.
 * Comparison never adopts content, guesses a completed request or increments
 * the confirmed server version. Revision mismatch retains both snapshots.
 */
export function recoveryChoice(local: LocalDraftSnapshot, draft: DocumentReadModel): 'RESTORE_AVAILABLE' | 'COMPARE_REQUIRED' {
  if (draft.document_type !== 'MANUAL_DRAFT') throw new TypeError('Actual draft required');
  return local.base_confirmed_version === draft.content_version ? 'RESTORE_AVAILABLE' : 'COMPARE_REQUIRED';
}

/** Real IndexedDB transactions. Quota/blocked/damaged data never trigger an
 * automatic deletion of another unconfirmed draft. Optional name/factory are
 * private browser diagnostics; production keeps walle-v1/version1.
 */
export class DraftRecoveryStore {
  private readonly ctx: Ctx; private readonly name: string; private readonly factory: () => IDBFactory;
  private opening: Promise<IDBDatabase> | undefined; private database: IDBDatabase | undefined; private closed = false;
  private readonly pending = new Set<Promise<unknown>>();
  constructor(ctx: Ctx, diagnostic: { name?: string; factory?: () => IDBFactory } = {}) {
    this.ctx = ctx; this.name = diagnostic.name ?? 'walle-v1'; this.factory = diagnostic.factory ?? (() => globalThis.indexedDB);
  }
  private validate(value: unknown): LocalDraftSnapshot {
    return validateLocalDraftSnapshot(this.ctx,value);
  }
  private open(): Promise<IDBDatabase> {
    if (this.closed) return Promise.reject(new DraftStorageError('UNAVAILABLE'));
    if (this.opening) return this.opening;
    this.opening = new Promise((resolve, reject) => {
      let request: IDBOpenDBRequest;
      try { request = this.factory().open(this.name, 1); } catch { reject(new DraftStorageError('UNAVAILABLE')); return; }
      let refused = false;
      request.onblocked = () => { refused = true; reject(new DraftStorageError('UNAVAILABLE')); };
      request.onerror = () => reject(new DraftStorageError('UNAVAILABLE'));
      request.onupgradeneeded = () => { request.result.createObjectStore(storeName); };
      request.onsuccess = () => {
        const database = request.result;
        if (this.closed || refused || !database.objectStoreNames.contains(storeName)) { database.close(); reject(new DraftStorageError('UNAVAILABLE')); return; }
        this.database = database;
        database.onversionchange = () => this.close();
        resolve(database);
      };
    });
    return this.opening;
  }
  private transaction<T>(mode: IDBTransactionMode, perform: (store: IDBObjectStore, complete: (value: T) => void, fail: (error: DraftStorageError) => void) => void): Promise<T> {
    const task=this.performTransaction(mode,perform);this.pending.add(task);
    void task.then(()=>this.pending.delete(task),()=>this.pending.delete(task));return task;
  }
  private async performTransaction<T>(mode: IDBTransactionMode, perform: (store: IDBObjectStore, complete: (value: T) => void, fail: (error: DraftStorageError) => void) => void): Promise<T> {
    const database = await this.open();
    return new Promise((resolve, reject) => {
      let transaction: IDBTransaction;
      try { transaction = database.transaction(storeName, mode); } catch { reject(new DraftStorageError('UNAVAILABLE')); return; }
      let output: T, produced = false, failure: DraftStorageError | undefined;
      const fail = (error: DraftStorageError) => { failure = error; try { transaction.abort(); } catch { reject(error); } };
      transaction.onabort = () => reject(failure ?? new DraftStorageError('UNAVAILABLE'));
      transaction.onerror = () => { failure ??= new DraftStorageError('UNAVAILABLE'); };
      transaction.oncomplete = () => produced ? resolve(output) : reject(new DraftStorageError('UNAVAILABLE'));
      try { perform(transaction.objectStore(storeName), value => { output = value; produced = true; }, fail); }
      catch { fail(new DraftStorageError('UNAVAILABLE')); }
    });
  }
  /** Owner stops new work first, then keeps the parser context and opening
   * connection alive until all actual transactions settle. No deletion or
   * claim of protection when a transaction was refused. */
  async settle():Promise<void>{while(this.pending.size)await Promise.allSettled([...this.pending]);}
  async get(requirement: number, draft: number): Promise<LocalDraftSnapshot | null> {
    const identity = key(requirement, draft);
    const value = await this.transaction<unknown>('readonly', (store, complete) => {
      const request = store.get(identity); request.onsuccess = () => complete(request.result);
    });
    if (value === undefined) return null;
    try { if (bytes(value) > DRAFT_BYTES) throw new TypeError('Oversized persisted value'); }
    catch { throw new DraftStorageError('CORRUPT'); }
    return this.validate(value);
  }
  async put(requirement: number, draft: number, value: unknown): Promise<boolean> {
    const identity = key(requirement, draft); let encoded: number;
    try { encoded = bytes(value); } catch { throw new DraftStorageError('CORRUPT'); }
    if (encoded > DRAFT_BYTES) throw new DraftStorageError('CAPACITY');
    const record = this.validate(value);
    return this.transaction<boolean>('readwrite', (store, complete, fail) => {
      let total = 0, entries = 0, previous = 0, exists = false;
      let superseded = false;
      const cursor = store.openCursor();
      cursor.onsuccess = () => {
        const entry = cursor.result;
        if (entry) {
          let size: number;
          try { size = bytes(entry.value); } catch { fail(new DraftStorageError('CORRUPT')); return; }
          total += size; entries++;
          if (Array.isArray(entry.key) && entry.key[0] === identity[0] && entry.key[1] === identity[1]) {
            exists = true; previous = size;
            let saved: LocalDraftSnapshot;
            try { saved = this.validate(entry.value); } catch { fail(new DraftStorageError('CORRUPT')); return; }
            superseded = saved.local_revision > record.local_revision || saved.local_revision === record.local_revision &&
              (saved.base_confirmed_version > record.base_confirmed_version || saved.base_confirmed_version === record.base_confirmed_version && saved.updated_at > record.updated_at);
          }
          entry.continue(); return;
        }
        if (superseded) { complete(false); return; }
        if (entries + Number(!exists) > DRAFT_RECORDS || total - previous + encoded > TOTAL_DRAFT_BYTES) { fail(new DraftStorageError('CAPACITY')); return; }
        const saved = store.put(record, identity); saved.onsuccess = () => complete(true);
      };
    });
  }
  /** A late acknowledgement cannot clear a newer persisted local revision. */
  async clearIfRevision(requirement: number, draft: number, revision: number): Promise<boolean> {
    const identity = key(requirement, draft); positiveInteger(revision);
    return this.transaction<boolean>('readwrite', (store, complete, fail) => {
      const request = store.get(identity);
      request.onsuccess = () => {
        if (request.result === undefined) { complete(false); return; }
        let row: LocalDraftSnapshot;
        try { row = this.validate(request.result); } catch { fail(new DraftStorageError('CORRUPT')); return; }
        if (row.local_revision !== revision) { complete(false); return; }
        const removed = store.delete(identity); removed.onsuccess = () => complete(true);
      };
    });
  }
  /** Only called after a parent confirms actual complete/cancel success. */
  async clearClosedDraft(requirement: number, draft: number): Promise<void> {
    const identity = key(requirement, draft);
    return this.transaction<void>('readwrite', (store, complete) => { const removed = store.delete(identity); removed.onsuccess = () => complete(undefined); });
  }
  close(): void { this.closed = true; this.database?.close(); this.database = undefined; }
}
