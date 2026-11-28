import { positiveInteger } from '../api/client.ts';
import {
  decodeEnvironmentScope,
  sameEnvironmentScope,
  type EnvironmentScope,
} from '../api/environment-binding.ts';
import { verifiedCommandIdentity } from '../api/code-command-snapshot.ts';
import { COMMAND_PENDING_LIMIT, pendingSummary } from '../code-tasks/command-recovery-model.ts';
import {
  DRAFT_BYTES,
  DRAFT_RECORDS,
  localDraftEnvelope,
  scopedDraftPayload,
  type LocalDraftSnapshot,
} from '../documents/recovery-store.ts';

const sources = [
  { name: 'walle-v2.01-document-assistant', store: 'draft_snapshots', scoped: true },
  { name: 'walle-v1.5-document-assistant', store: 'draft_snapshots', scoped: false },
  { name: 'walle-v2.01-code-command-recovery', store: 'pending_commands', scoped: true },
  { name: 'walle-v2-code-command-recovery', store: 'pending_commands', scoped: false },
] as const;

type Source = (typeof sources)[number];
type DraftSource = Extract<Source, { store: 'draft_snapshots' }>;
type DraftEntry = Readonly<{
  kind: 'DRAFT';
  source: DraftSource;
  key: IDBValidKey;
  scope: EnvironmentScope | null;
  version: number;
  revision: number;
  updatedAt: string;
}>;
type CommandEntry = Readonly<{
  kind: 'COMMAND';
  scope: EnvironmentScope | null;
  key: string;
  action: string;
  state: ReturnType<typeof pendingSummary>['status'];
}>;
type Entry = DraftEntry | CommandEntry;

export type ArchiveScan = Readonly<{
  entries: readonly Entry[];
  damaged: number;
  unreadable: number;
  truncated: boolean;
}>;
export type ArchivedDraftValidator = (value: unknown) => LocalDraftSnapshot;

const unavailable = () => Error('Existing browser records are unavailable');

async function access<T>(
  source: Source,
  operation: (store: IDBObjectStore, finish: (value: T) => void) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(source.name, 1);
    let database: IDBDatabase | undefined;
    let settled = false;
    const timeout = window.setTimeout(() => fail(), 8000);
    function close(): void {
      window.clearTimeout(timeout);
      database?.close();
    }
    function fail(): void {
      if (settled) return;
      settled = true;
      close();
      reject(unavailable());
    }
    request.onerror = fail;
    request.onblocked = fail;
    // Discovery and open can race with a deletion. Abort a would-be creation.
    request.onupgradeneeded = () => {
      request.transaction?.abort();
      fail();
    };
    request.onsuccess = () => {
      database = request.result;
      if (settled) {
        database.close();
        return;
      }
      try {
        const transaction = database.transaction(source.store, 'readonly');
        const store = transaction.objectStore(source.store);
        if (store.keyPath !== null || store.autoIncrement) throw unavailable();
        let outcome: { ready: false } | { ready: true; value: T } = { ready: false };
        transaction.oncomplete = () => {
          if (!settled && outcome.ready) {
            settled = true;
            close();
            resolve(outcome.value);
          } else fail();
        };
        transaction.onabort = fail;
        transaction.onerror = fail;
        operation(store, (value) => {
          outcome = { ready: true, value };
        });
      } catch {
        fail();
      }
    };
  });
}

function parts(key: IDBValidKey, length: number): IDBValidKey[] {
  if (!Array.isArray(key) || key.length !== length) throw TypeError('Invalid stored key');
  return key;
}

function storedScope(key: IDBValidKey[], origin: string): EnvironmentScope {
  const scope = decodeEnvironmentScope({
    binding_protocol: 1,
    origin: key[0],
    environment_id: key[1],
    data_generation: key[2],
  });
  if (scope.origin !== origin) throw TypeError('Unexpected storage origin');
  return scope;
}

function draftEntry(
  source: DraftSource,
  key: IDBValidKey,
  value: unknown,
  scope: EnvironmentScope | null,
): DraftEntry {
  const identity = parts(key, scope ? 7 : 4).slice(scope ? 3 : 0);
  identity.forEach(positiveInteger);
  if (identity[1] === identity[2]) throw TypeError('Draft and target are the same');
  const payload = scope ? scopedDraftPayload(value, key, scope.origin) : value;
  const metadata = localDraftEnvelope(payload);
  if (metadata.markdown_content.length > DRAFT_BYTES)
    throw TypeError('Draft exceeds the archived text limit');
  return {
    kind: 'DRAFT',
    source,
    key,
    scope,
    version: metadata.base_confirmed_version,
    revision: metadata.local_revision,
    updatedAt: metadata.updated_at,
  };
}

async function scan(
  source: Source,
  current: EnvironmentScope,
): Promise<{
  entries: Entry[];
  damaged: number;
  truncated: boolean;
}> {
  let damaged = 0;
  let truncated = false;
  const candidates = await access<Promise<Entry | null>[]>(source, (store, finish) => {
    const entries: Promise<Entry | null>[] = [];
    const request = store.openCursor();
    const limit = source.store === 'draft_snapshots' ? DRAFT_RECORDS : COMMAND_PENDING_LIMIT;
    let visited = 0;
    request.onsuccess = () => {
      const cursor = request.result;
      if (!cursor || visited >= limit) {
        truncated = cursor !== null;
        finish(entries);
        return;
      }
      visited += 1;
      try {
        const draft = source.store === 'draft_snapshots';
        const key = parts(
          cursor.primaryKey,
          draft ? (source.scoped ? 7 : 4) : source.scoped ? 4 : 2,
        );
        const scope = source.scoped ? storedScope(key, current.origin) : null;
        if (!scope || !sameEnvironmentScope(scope, current)) {
          if (source.store === 'draft_snapshots') {
            entries.push(Promise.resolve(draftEntry(source, key, cursor.value, scope)));
          } else {
            if (key[0] !== current.origin) throw TypeError('Unexpected command origin');
            const command = pendingSummary(cursor.value, current.origin, scope ?? undefined);
            if (command.key !== key.at(-1)) throw TypeError('Command key does not match');
            entries.push(
              verifiedCommandIdentity(command, current.origin, scope ?? undefined)
                .then((): CommandEntry => ({
                  kind: 'COMMAND',
                  scope,
                  key: command.key,
                  action: command.method + ' ' + command.path,
                  state: command.status,
                }))
                .catch(() => null),
            );
          }
        }
      } catch {
        damaged += 1;
      }
      cursor.continue();
    };
  });
  const accepted = (await Promise.all(candidates)).filter((row) => row !== null);
  return { entries: accepted, damaged: damaged + candidates.length - accepted.length, truncated };
}

export async function readBrowserArchive(current: EnvironmentScope): Promise<ArchiveScan> {
  if (typeof indexedDB.databases !== 'function') throw unavailable();
  const existing = new Map((await indexedDB.databases()).map((item) => [item.name, item.version]));
  const available = sources.filter((source) => existing.has(source.name));
  const results = await Promise.allSettled(
    available.map(async (source) => {
      if (existing.get(source.name) !== 1) throw unavailable();
      return scan(source, current);
    }),
  );
  const successful = results.flatMap((item) => (item.status === 'fulfilled' ? [item.value] : []));
  return {
    entries: successful.flatMap((item) => item.entries),
    damaged: successful.reduce((count, item) => count + item.damaged, 0),
    unreadable: results.length - successful.length,
    truncated: successful.some((item) => item.truncated),
  };
}

export async function readArchivedDraft(entry: DraftEntry, validate: ArchivedDraftValidator) {
  const exists = await indexedDB.databases();
  if (!exists.some((item) => item.name === entry.source.name && item.version === 1))
    throw unavailable();
  const value = await access<unknown>(entry.source, (store, finish) => {
    const read = store.get(entry.key);
    read.onsuccess = () => finish(read.result);
  });
  const current = draftEntry(entry.source, entry.key, value, entry.scope);
  if (
    current.version !== entry.version ||
    current.revision !== entry.revision ||
    current.updatedAt !== entry.updatedAt
  )
    throw TypeError('Archived draft changed after listing');
  const payload = entry.scope ? scopedDraftPayload(value, entry.key, entry.scope.origin) : value;
  return validate(payload).markdown_content;
}
