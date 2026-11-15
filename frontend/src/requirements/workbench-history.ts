import { snapshotObject } from '../api/client.ts';
import { workbenchQuery, defaultWorkbenchQuery } from './workbench.ts';
import type { WorkbenchQuery } from './workbench.ts';

export type WorkbenchNavIntent = 'CHOOSE_CODE_DOCUMENT' | null;

export type WorkbenchEntry = Readonly<{
  schema_version: 2;
  kind: 'WALLE_WORKBENCH';
  entry_id: string;
  query: WorkbenchQuery;
  scroll: number;
  nav_intent: WorkbenchNavIntent;
}>;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const key = (id: string) => 'walle:v1.5:workbench:' + id;
function scroll(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0)
    throw new TypeError('Invalid scroll');
  return value;
}
export function decodeWorkbenchEntry(input: unknown): WorkbenchEntry {
  const row = snapshotObject(input);
  const fields = Object.keys(row).sort().join(',');
  if (
    (fields !== 'entry_id,kind,nav_intent,query,schema_version,scroll' &&
      fields !== 'entry_id,kind,query,schema_version,scroll') ||
    (fields.includes('nav_intent') &&
      row.nav_intent !== null &&
      row.nav_intent !== 'CHOOSE_CODE_DOCUMENT') ||
    row.schema_version !== 2 ||
    row.kind !== 'WALLE_WORKBENCH' ||
    typeof row.entry_id !== 'string' ||
    !uuid.test(row.entry_id)
  )
    throw new TypeError('Invalid workbench entry');
  const query = workbenchQuery(row.query as unknown as WorkbenchQuery);
  const original = row.query as unknown as WorkbenchQuery;
  if (
    original.keyword !== query.keyword ||
    JSON.stringify(original.status) !== JSON.stringify(query.status) ||
    JSON.stringify(original.requirement_type) !== JSON.stringify(query.requirement_type)
  )
    throw new TypeError('Noncanonical stored query');
  return Object.freeze({
    schema_version: 2,
    kind: 'WALLE_WORKBENCH',
    entry_id: row.entry_id,
    query,
    scroll: scroll(row.scroll),
    nav_intent: row.nav_intent === 'CHOOSE_CODE_DOCUMENT' ? row.nav_intent : null,
  });
}

/** One entry belongs to one actual browser history position, never "latest list". */
export class WorkbenchHistory {
  private readonly history: Pick<History, 'state' | 'replaceState'> &
    Partial<Pick<History, 'scrollRestoration'>>;
  private readonly storage: Pick<Storage, 'getItem' | 'setItem'> | null;
  private readonly identify: () => string;
  private readonly memory = new Map<string, WorkbenchEntry>();
  private warning: string | null = null;
  private restorationWarning: string | null = null;
  constructor(
    history: Pick<History, 'state' | 'replaceState'> & Partial<Pick<History, 'scrollRestoration'>>,
    storage: Pick<Storage, 'getItem' | 'setItem'> | null,
    identify = () => crypto.randomUUID(),
  ) {
    this.history = history;
    this.storage = storage;
    this.identify = identify;
    try {
      if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
    } catch {
      this.restorationWarning = '浏览器返回位置控制不可用，可能提前恢复滚动位置';
    }
  }
  get storageWarning(): string | null {
    return this.warning ?? this.restorationWarning;
  }
  enter(mode: 'DEFAULT' | 'RESTORE', navIntent: WorkbenchNavIntent = null): WorkbenchEntry {
    this.warning = null;
    if (mode === 'RESTORE') {
      try {
        const entry = decodeWorkbenchEntry(this.history.state);
        this.memory.set(entry.entry_id, entry);
        return entry;
      } catch {
        /* Supplement only the same entry. */
      }
      let identity: string | null = null;
      try {
        const row = snapshotObject(this.history.state);
        if (
          row.kind === 'WALLE_WORKBENCH' &&
          row.schema_version === 2 &&
          typeof row.entry_id === 'string' &&
          uuid.test(row.entry_id)
        )
          identity = row.entry_id;
      } catch {
        /* Unrelated history uses defaults. */
      }
      if (identity) {
        const existing = this.memory.get(identity);
        if (existing) return existing;
        try {
          const value = this.storage?.getItem(key(identity));
          if (value) {
            const saved = decodeWorkbenchEntry(JSON.parse(value));
            if (saved.entry_id === identity) return this.persist(saved);
          }
        } catch {
          this.warning = '返回位置暂存不可用，已使用默认查询';
        }
      }
    }
    const identity = this.identify();
    if (!uuid.test(identity)) throw new TypeError('UUIDv4 entry required');
    return this.persist(
      decodeWorkbenchEntry({
        schema_version: 2,
        kind: 'WALLE_WORKBENCH',
        entry_id: identity,
        query: defaultWorkbenchQuery,
        scroll: 0,
        nav_intent: navIntent,
      }),
    );
  }
  save(entry: WorkbenchEntry, query: WorkbenchQuery, position: number): WorkbenchEntry {
    const next = decodeWorkbenchEntry({
      ...entry,
      query: workbenchQuery(query),
      scroll: scroll(position),
    });
    return this.persist(next);
  }
  private persist(entry: WorkbenchEntry): WorkbenchEntry {
    this.memory.set(entry.entry_id, entry);
    try {
      this.history.replaceState(entry, '');
    } catch {
      this.warning = '无法保存浏览器返回位置，请保持当前页面';
    }
    try {
      if (!this.storage) throw new Error('Storage unavailable');
      this.storage.setItem(key(entry.entry_id), JSON.stringify(entry));
    } catch {
      this.warning ??= '返回位置暂存不可用，刷新后可能无法恢复';
    }
    return entry;
  }
}

export type PageRoute =
  | Readonly<{ kind: 'WORKBENCH' }>
  | Readonly<{ kind: 'DETAIL'; id: number }>
  | Readonly<{ kind: 'CODE_SETTINGS' }>
  | Readonly<{ kind: 'TESTING_SETTINGS' }>
  | Readonly<{ kind: 'TESTING_PLANS' }>
  | Readonly<{ kind: 'TESTING_LIST' }>
  | Readonly<{ kind: 'TESTING_TASK'; taskId: number }>
  | Readonly<{ kind: 'TESTING_PARAMETERS' }>
  | Readonly<{ kind: 'CODE_TASK_LIST'; requirementId: number; documentId: number }>
  | Readonly<{ kind: 'CODE_TASK'; taskId: number }>
  | Readonly<{ kind: 'CODE_PARAMETERS' }>
  | Readonly<{ kind: 'NOT_FOUND' }>;
function canonicalId(value: string): number | null {
  if (!/^[1-9][0-9]*$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : null;
}

export function pageRoute(path: string): PageRoute {
  if (path === '/settings/code') return Object.freeze({ kind: 'CODE_SETTINGS' });
  if (path === '/settings/testing') return Object.freeze({ kind: 'TESTING_SETTINGS' });
  if (path === '/testing/plans') return Object.freeze({ kind: 'TESTING_PLANS' });
  if (path === '/testing') return Object.freeze({ kind: 'TESTING_LIST' });
  const testingTask = /^\/testing\/tasks\/([^/]+)$/.exec(path);
  if (testingTask) {
    const taskId = canonicalId(testingTask[1]!);
    return taskId
      ? Object.freeze({ kind: 'TESTING_TASK', taskId })
      : Object.freeze({ kind: 'TESTING_PARAMETERS' });
  }
  if (path === '/requirements' || path === '/') return Object.freeze({ kind: 'WORKBENCH' });
  const list = /^\/requirements\/([^/]+)\/documents\/([^/]+)\/code-tasks$/.exec(path);
  if (list) {
    const [requirementId, documentId] = list.slice(1).map(canonicalId);
    return requirementId && documentId
      ? Object.freeze({ kind: 'CODE_TASK_LIST', requirementId, documentId })
      : Object.freeze({ kind: 'CODE_PARAMETERS' });
  }
  const task = /^\/code-tasks\/([^/]+)$/.exec(path);
  if (task) {
    const taskId = canonicalId(task[1]!);
    return taskId
      ? Object.freeze({ kind: 'CODE_TASK', taskId })
      : Object.freeze({ kind: 'CODE_PARAMETERS' });
  }
  const match = /^\/requirements\/([1-9][0-9]*)$/.exec(path);
  if (match) {
    const id = Number(match[1]);
    if (Number.isSafeInteger(id) && id >= 1) return Object.freeze({ kind: 'DETAIL', id });
  }
  return Object.freeze({ kind: 'NOT_FOUND' });
}
