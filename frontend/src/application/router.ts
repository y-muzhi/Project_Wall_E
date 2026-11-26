import type { WalleApi } from '../api/walle.ts';
import {
  bindBrowserHistory,
  ScopedStoragePort,
  type BrowserHistoryPort,
  type StoragePort,
} from '../api/environment-storage.ts';
import { RequirementWorkbench } from '../requirements/workbench.ts';
import type { WorkbenchQuery } from '../requirements/workbench.ts';
import { CreateRequirementFlow } from '../requirements/create.ts';
import {
  WorkbenchHistory,
  pageRoute,
  decodeWorkbenchEntry,
} from '../requirements/workbench-history.ts';
import type {
  WorkbenchEntry,
  PageRoute,
  WorkbenchNavIntent,
} from '../requirements/workbench-history.ts';
import type { DetailDeparture } from '../requirements/departure.ts';
import type { CodeSettingsSection } from '../code-tasks/settings/section.ts';
import { DEFAULT_TASK_QUERY, readCodeTaskQuery, safeId } from '../code-tasks/list-model.ts';
import type { CodeTaskQuery } from '../code-tasks/list-model.ts';
import { readWorkspaceRoute, workspacePath } from '../code-tasks/workspace-route.ts';
import type { WorkspaceRoute } from '../code-tasks/workspace-route.ts';

export type DocumentReading = Readonly<{
  documentId: number;
  revisionId: number | null;
  scroll: number;
}>;
export type DocumentHandoffLink = Readonly<{
  documentId: number;
  taskId: number;
  handoffId: number;
}>;
export type DocumentHandoffEntry = DocumentHandoffLink | 'INVALID' | null;

function handoffQuery(search: string): DocumentHandoffEntry {
  const query = new URLSearchParams(search);
  const keys = ['document_id', 'code_task_id', 'code_handoff_id'];
  if (!keys.some((key) => query.has(key))) return null;
  if ([...query].length !== keys.length || keys.some((key) => query.getAll(key).length !== 1))
    return 'INVALID';
  const [documentId, taskId, handoffId] = keys.map((key) => {
    const text = query.get(key);
    return text && /^[1-9][0-9]*$/.test(text) ? Number(text) : null;
  });
  return safeId(documentId) && safeId(taskId) && safeId(handoffId)
    ? { documentId, taskId, handoffId }
    : 'INVALID';
}

type CodeListRoute = Extract<PageRoute, { kind: 'CODE_TASK_LIST' }>;
type TaskListEntry = Readonly<{
  kind: 'WALLE_CODE_LIST';
  entry_id: string;
  position: number;
  requirementId: number;
  documentId: number;
  query: CodeTaskQuery;
  scroll: number;
  revisionId: number | null;
  fromDetail: boolean;
}>;
type TaskEntry = Readonly<{
  kind: 'WALLE_CODE_TASK';
  entry_id: string;
  position: number;
  taskId: number;
  fromList: { requirementId: number; documentId: number } | null;
  scroll: number;
}>;

function documentReading(value: unknown): DocumentReading | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Partial<DocumentReading>;
  return safeId(row.documentId) &&
    (row.revisionId === null || safeId(row.revisionId)) &&
    typeof row.scroll === 'number' &&
    Number.isFinite(row.scroll) &&
    row.scroll >= 0
    ? { documentId: row.documentId, revisionId: row.revisionId, scroll: row.scroll }
    : null;
}
const listPath = (requirementId: number, documentId: number) =>
  '/requirements/' + requirementId + '/documents/' + documentId + '/code-tasks';

type DetailEntry = Readonly<{
  schema_version: 2;
  kind: 'WALLE_DETAIL';
  entry_id: string;
  id: number;
  position: number;
  reading?: DocumentReading | null;
  from: Readonly<{ entry: WorkbenchEntry; position: number }> | null;
}>;
type Destination = Readonly<{ path: string; state: unknown; position: number | null }>;
export interface BrowserPort {
  history: BrowserHistoryPort;
  pathname(): string;
  search?(): string;
  scroll(): number;
  scrollTop(): void;
  listen(listener: () => void): () => void;
}
export type ApplicationState = Readonly<{
  route: PageRoute;
  epoch: number;
  workbench: RequirementWorkbench | null;
  creation: CreateRequirementFlow | null;
  entry: WorkbenchEntry | null;
  navIntent: WorkbenchNavIntent;
  restoreScroll: number | null;
  warning: string | null;
  documentReading: DocumentReading | null;
  documentHandoff: DocumentHandoffEntry;
  taskList: TaskListEntry | null;
  task: TaskEntry | null;
  taskWorkspace: WorkspaceRoute | null;
}>;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const entryId = (state: unknown): string | null => {
  if (
    state &&
    typeof state === 'object' &&
    'entry_id' in state &&
    typeof state.entry_id === 'string' &&
    uuid.test(state.entry_id)
  )
    return state.entry_id;
  return null;
};
const positionKey = (id: string) => 'walle:v1.5:route-position:' + id;
/** Real route owner: workbench entries belong to browser history positions.
 * Popstate is restored before asking an active detail to save/leave, so a
 * failed save keeps both the mounted editor and its original browser entry. */
export class ApplicationRouter {
  private readonly api: WalleApi;
  private readonly browser: BrowserPort;
  private readonly historyPort: BrowserHistoryPort;
  private readonly storage: Pick<Storage, 'getItem' | 'setItem'> | null;
  private readonly identify: () => string;
  private readonly history: WorkbenchHistory;
  private readonly lists = new Map<string, RequirementWorkbench>();
  private readonly positions = new Map<string, number>();
  private readonly trustedCodeBack = new Set<string>();
  private readonly originalTaskListPositions = new Map<string, number>();
  private readonly listeners = new Set<() => void>();
  private release: () => void;
  private position = 0;
  private currentPath: string;
  private currentState: unknown;
  private testingListSearch = '';
  private departure: DetailDeparture | null = null;
  private blocked = false;
  private closed = false;
  private restoration: Readonly<{ original: Destination; target: Destination }> | null = null;
  private approved: Destination | null = null;
  private value: ApplicationState = Object.freeze({
    route: { kind: 'NOT_FOUND' as const },
    epoch: 0,
    workbench: null,
    creation: null,
    entry: null,
    navIntent: null,
    restoreScroll: null,
    warning: null,
    documentReading: null,
    documentHandoff: null,
    taskList: null,
    task: null,
    taskWorkspace: null,
  });
  constructor(
    api: WalleApi,
    browser: BrowserPort,
    storage: StoragePort | null,
    identify = () => crypto.randomUUID(),
  ) {
    this.api = api;
    this.browser = browser;
    const scope = api.environmentScope;
    this.historyPort = scope ? bindBrowserHistory(browser.history, scope) : browser.history;
    this.storage = scope && storage ? new ScopedStoragePort(storage, scope) : storage;
    this.identify = identify;
    this.history = new WorkbenchHistory(this.historyPort, this.storage, identify);
    this.currentPath = browser.pathname();
    this.currentState = this.historyPort.state;
    this.position = this.readPosition(this.currentState, this.currentPath) ?? 0;
    this.apply(this.currentPath, true);
    this.release = browser.listen(this.pop);
  }
  getSnapshot = (): ApplicationState => this.value;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  get applicationApi(): WalleApi {
    return this.api;
  }
  private publish(changes: Partial<ApplicationState>) {
    if (this.closed) return;
    this.value = Object.freeze({ ...this.value, ...changes });
    for (const listener of this.listeners) listener();
  }
  private readPosition(state: unknown, path: string): number | null {
    const route = pageRoute(path);
    if (route.kind === 'DETAIL') {
      const detail = this.decodeDetail(state, route.id);
      if (detail) return detail.position;
    }
    const identity = entryId(state);
    if (!identity) return null;
    const known = this.positions.get(identity);
    if (known !== undefined) return known;
    try {
      const raw = this.storage?.getItem(positionKey(identity));
      if (raw !== null && raw !== undefined) {
        const value = JSON.parse(raw);
        if (Number.isSafeInteger(value) && value >= 0) {
          this.positions.set(identity, value);
          return value;
        }
      }
    } catch {
      /* Actual route remains usable; no guessed predecessor. */
    }
    return null;
  }
  private remember(state: unknown, position: number) {
    const identity = entryId(state);
    if (!identity) return;
    this.positions.set(identity, position);
    try {
      this.storage?.setItem(positionKey(identity), JSON.stringify(position));
    } catch {
      this.publish({ warning: '浏览器返回位置暂存不可用，刷新后可能无法恢复。' });
    }
  }
  private decodeDetail(state: unknown, id: number): DetailEntry | null {
    try {
      if (!state || typeof state !== 'object') return null;
      const row = state as DetailEntry;
      if (
        row.kind !== 'WALLE_DETAIL' ||
        row.schema_version !== 2 ||
        row.id !== id ||
        !uuid.test(row.entry_id) ||
        !Number.isSafeInteger(row.position) ||
        row.position < 0
      )
        return null;
      if (row.from !== null) {
        if (
          !row.from ||
          !Number.isSafeInteger(row.from.position) ||
          row.from.position < 0 ||
          row.from.position >= row.position
        )
          return null;
        // Use the same strict public browser-entry decoder, not a second query definition.
        decodeWorkbenchEntry(row.from.entry);
      }
      return Object.freeze({
        ...row,
        reading: documentReading(row.reading),
        from: row.from
          ? Object.freeze({ ...row.from, entry: decodeWorkbenchEntry(row.from.entry) })
          : null,
      });
    } catch {
      return null;
    }
  }
  private readTaskList(route: CodeListRoute, value: unknown): TaskListEntry | null {
    if (!value || typeof value !== 'object') return null;
    const row = value as Partial<TaskListEntry>;
    const id = entryId(row);
    if (
      row.kind !== 'WALLE_CODE_LIST' ||
      !id ||
      row.requirementId !== route.requirementId ||
      row.documentId !== route.documentId ||
      typeof row.position !== 'number' ||
      !Number.isSafeInteger(row.position) ||
      row.position < 0
    )
      return null;
    return {
      kind: 'WALLE_CODE_LIST',
      entry_id: id,
      position: row.position,
      requirementId: route.requirementId,
      documentId: route.documentId,
      query: readCodeTaskQuery(row.query),
      scroll:
        typeof row.scroll === 'number' && Number.isFinite(row.scroll) && row.scroll >= 0
          ? row.scroll
          : 0,
      revisionId: safeId(row.revisionId) ? row.revisionId : null,
      fromDetail: row.fromDetail === true && row.position > 0,
    };
  }
  private readTask(taskId: number, value: unknown): TaskEntry | null {
    if (!value || typeof value !== 'object') return null;
    const row = value as Partial<TaskEntry>;
    const id = entryId(row);
    if (
      row.kind !== 'WALLE_CODE_TASK' ||
      !id ||
      row.taskId !== taskId ||
      typeof row.position !== 'number' ||
      !Number.isSafeInteger(row.position) ||
      row.position < 0
    )
      return null;
    const from = row.fromList;
    return {
      kind: 'WALLE_CODE_TASK',
      taskId,
      entry_id: id,
      position: row.position,
      scroll:
        typeof row.scroll === 'number' && Number.isFinite(row.scroll) && row.scroll >= 0
          ? row.scroll
          : 0,
      fromList:
        row.position > 0 && from && safeId(from.requirementId) && safeId(from.documentId)
          ? { requirementId: from.requirementId, documentId: from.documentId }
          : null,
    };
  }
  private apply(path: string, restore: boolean, navIntent: WorkbenchNavIntent = null) {
    const prior = this.value;
    prior.workbench?.pause();
    prior.creation?.dispose();
    this.departure = null;
    this.blocked = false;
    const route = pageRoute(path);
    let workbench: RequirementWorkbench | null = null,
      creation: CreateRequirementFlow | null = null,
      entry: WorkbenchEntry | null = null;
    let reading: DocumentReading | null = null;
    let handoff: DocumentHandoffEntry = null;
    let taskList: TaskListEntry | null = null;
    let task: TaskEntry | null = null;
    if (route.kind === 'WORKBENCH') {
      if (path === '/') {
        this.historyPort.replaceState(this.historyPort.state, '', '/requirements');
        path = '/requirements';
      }
      entry = this.history.enter(restore ? 'RESTORE' : 'DEFAULT', navIntent);
      navIntent = entry.nav_intent;
      workbench = this.lists.get(entry.entry_id) ?? new RequirementWorkbench(this.api, entry.query);
      this.lists.set(entry.entry_id, workbench);
      creation = new CreateRequirementFlow(this.api);
      this.remember(entry, this.position);
    } else if (route.kind === 'DETAIL') {
      const detailEntry =
        this.decodeDetail(this.historyPort.state, route.id) ??
        Object.freeze({
          schema_version: 2,
          kind: 'WALLE_DETAIL',
          entry_id: this.identify(),
          id: route.id,
          position: this.position,
          from: null,
        });
      const search = this.browser.search?.() ?? '';
      handoff = handoffQuery(search);
      this.historyPort.replaceState(detailEntry, '', handoff ? path + search : path);
      if (detailEntry.from) {
        const { entry, position } = detailEntry.from;
        this.positions.set(entry.entry_id, position);
        navIntent = entry.nav_intent;
      }
      this.remember(detailEntry, this.position);
      reading =
        handoff && handoff !== 'INVALID'
          ? { documentId: handoff.documentId, revisionId: null, scroll: 0 }
          : 'reading' in detailEntry
            ? (detailEntry.reading ?? null)
            : null;
    } else if (route.kind === 'CODE_TASK_LIST') {
      taskList = this.readTaskList(route, this.historyPort.state) ?? {
        kind: 'WALLE_CODE_LIST',
        entry_id: this.identify(),
        position: this.position,
        requirementId: route.requirementId,
        documentId: route.documentId,
        query: DEFAULT_TASK_QUERY,
        scroll: 0,
        revisionId: null,
        fromDetail: false,
      };
      this.historyPort.replaceState(taskList, '', path);
      this.remember(taskList, this.position);
    } else if (route.kind === 'CODE_TASK') {
      task = this.readTask(route.taskId, this.historyPort.state) ?? {
        kind: 'WALLE_CODE_TASK',
        entry_id: this.identify(),
        position: this.position,
        taskId: route.taskId,
        fromList: null,
        scroll: 0,
      };
      this.historyPort.replaceState(task, '');
      this.remember(task, this.position);
    }
    this.currentPath = path;
    this.currentState = this.historyPort.state;
    if (route.kind !== 'CODE_SETTINGS' || prior.route.kind !== 'CODE_SETTINGS')
      this.browser.scrollTop();
    this.publish({
      route,
      documentReading: reading,
      documentHandoff: handoff,
      taskList,
      task,
      taskWorkspace: task === null ? null : readWorkspaceRoute(this.browser.search?.() ?? ''),
      workbench,
      creation,
      entry,
      navIntent,
      restoreScroll: restore ? (entry?.scroll ?? task?.scroll ?? null) : null,
      epoch: prior.epoch + 1,
      warning: this.history.storageWarning,
    });
  }
  saveEntry = (query: WorkbenchQuery, scroll: number): void => {
    const entry = this.value.entry;
    if (
      this.closed ||
      this.value.route.kind !== 'WORKBENCH' ||
      !entry ||
      entryId(this.historyPort.state) !== entry.entry_id
    )
      return;
    const saved = this.history.save(entry, query, scroll);
    this.currentState = this.historyPort.state;
    this.publish({ entry: saved, warning: this.history.storageWarning });
  };
  navigationGuard = (blocked: boolean): void => {
    this.blocked = blocked;
  };
  attachDeparture = (departure: DetailDeparture): void => {
    this.departure = departure;
  };
  discardCreation = (): void => {
    if (!this.value.creation || this.value.creation.state.busy || this.value.creation.state.unknown)
      return;
    this.value.creation.dispose();
    this.publish({ creation: new CreateRequirementFlow(this.api) });
  };
  private allowed(next: () => void) {
    if (this.closed) return;
    if (this.value.route.kind === 'DETAIL' && this.departure) {
      void this.departure.request(next);
      return;
    }
    if (this.blocked && !this.value.creation?.state.result) {
      this.publish({ warning: '请先在新建需求抽屉中确认输入或恢复原请求。' });
      return;
    }
    next();
  }
  openRequirement = (id: number): void => {
    if (pageRoute('/requirements/' + id).kind !== 'DETAIL')
      throw TypeError('Canonical requirement ID required');
    this.allowed(() => {
      if (this.value.entry && this.value.workbench)
        this.saveEntry(this.value.workbench.state.requested, this.browser.scroll());
      const from = this.value.entry
        ? Object.freeze({ entry: this.value.entry, position: this.position })
        : null;
      const entry: DetailEntry = Object.freeze({
        schema_version: 2,
        kind: 'WALLE_DETAIL',
        entry_id: this.identify(),
        id,
        position: this.position + 1,
        from,
      });
      this.historyPort.pushState(entry, '', '/requirements/' + id);
      this.position++;
      this.apply('/requirements/' + id, true);
    });
  };
  private pushPage(path: string, state: unknown, routePath = path) {
    this.historyPort.pushState(state, '', path);
    this.position++;
    this.apply(routePath, true);
  }
  openCodeTaskList = (
    requirementId: number,
    reading: DocumentReading,
    source: DocumentReading | null = reading,
  ): void => {
    if (
      this.value.route.kind !== 'DETAIL' ||
      this.value.route.id !== requirementId ||
      !documentReading(reading) ||
      (source !== null && !documentReading(source))
    )
      return;
    this.allowed(() => {
      const detail = this.decodeDetail(this.historyPort.state, requirementId);
      if (!detail) throw Error('Missing original document history');
      this.historyPort.replaceState({ ...detail, reading: source }, '');
      const next: TaskListEntry = {
        kind: 'WALLE_CODE_LIST',
        entry_id: this.identify(),
        position: this.position + 1,
        requirementId,
        documentId: reading.documentId,
        query: DEFAULT_TASK_QUERY,
        scroll: 0,
        revisionId: reading.revisionId,
        fromDetail: true,
      };
      this.trustedCodeBack.add(next.entry_id);
      this.pushPage(listPath(requirementId, reading.documentId), next);
    });
  };
  saveCodeTaskList = (query: CodeTaskQuery, scroll: number): void => {
    const list = this.value.taskList;
    if (!list || entryId(this.historyPort.state) !== list.entry_id) return;
    const state = { ...list, query: readCodeTaskQuery(query), scroll: Math.max(0, scroll) };
    this.historyPort.replaceState(state, '');
    this.currentState = state;
    this.publish({ taskList: state });
  };
  openCodeTask = (taskId: number, requirementId: number, documentId: number): void => {
    const list = this.value.taskList;
    if (!safeId(taskId) || list?.requirementId !== requirementId || list.documentId !== documentId)
      return;
    this.saveCodeTaskList(list.query, this.browser.scroll());
    const next: TaskEntry = {
      kind: 'WALLE_CODE_TASK',
      entry_id: this.identify(),
      position: this.position + 1,
      taskId,
      fromList: { requirementId, documentId },
      scroll: 0,
    };
    this.originalTaskListPositions.set(next.entry_id, this.position);
    this.pushPage('/code-tasks/' + taskId, next);
  };
  openCodeTaskWorkspace = (selection: WorkspaceRoute): void => {
    const task = this.value.task;
    if (this.value.route.kind !== 'CODE_TASK' || task === null || this.closed) return;
    const routePath = '/code-tasks/' + task.taskId;
    const path = workspacePath(task.taskId, selection);
    const query = path.slice(routePath.length);
    const location = readWorkspaceRoute(query);
    if (location === null || query === this.browser.search?.()) return;

    const scroll = Math.max(0, this.browser.scroll());
    this.historyPort.replaceState({ ...task, scroll }, '');
    const next: TaskEntry = {
      ...task,
      entry_id: this.identify(),
      position: this.position + 1,
      scroll,
    };
    const source = this.originalTaskListPositions.get(task.entry_id);
    if (source !== undefined) this.originalTaskListPositions.set(next.entry_id, source);
    this.historyPort.pushState(next, '', path);
    this.position = next.position;
    this.currentState = next;
    this.remember(next, this.position);
    this.publish({ task: next, taskWorkspace: location, restoreScroll: null });
  };
  pinCodeTaskFileScope = (route: WorkspaceRoute, identity: number): void => {
    const task = this.value.task;
    if (
      this.closed ||
      task === null ||
      this.value.route.kind !== 'CODE_TASK' ||
      this.value.taskWorkspace !== route ||
      route.filePath === undefined ||
      !safeId(identity)
    )
      return;
    let scoped: WorkspaceRoute;
    if (route.tab === 'code' && route.candidateId === undefined)
      scoped = { ...route, candidateId: identity };
    else if (route.tab === 'delivery' && route.planId === undefined)
      scoped = { ...route, planId: identity };
    else return;

    this.historyPort.replaceState(task, '', workspacePath(task.taskId, scoped));
    this.currentState = task;
    this.publish({ taskWorkspace: scoped });
  };
  returnToTaskList = (requirementId: number, documentId: number): void => {
    if (!safeId(requirementId) || !safeId(documentId) || this.value.route.kind !== 'CODE_TASK')
      return;
    const task = this.value.task;
    const from = task?.fromList;
    const position = task ? this.originalTaskListPositions.get(task.entry_id) : undefined;
    if (
      from?.requirementId === requirementId &&
      from.documentId === documentId &&
      position !== undefined &&
      position < this.position
    )
      this.historyPort.go(position - this.position);
    else this.pushPage(listPath(requirementId, documentId), null);
  };
  returnToCodeDocument = (requirementId: number, documentId: number): void => {
    if (!safeId(requirementId) || !safeId(documentId)) return;
    const list = this.value.taskList;
    const sameDocument = list?.requirementId === requirementId && list.documentId === documentId;
    if (list?.fromDetail && sameDocument && this.trustedCodeBack.has(list.entry_id)) {
      this.historyPort.go(-1);
      return;
    }
    const entry: DetailEntry = {
      schema_version: 2,
      kind: 'WALLE_DETAIL',
      entry_id: this.identify(),
      id: requirementId,
      position: this.position + 1,
      from: null,
      reading: { documentId, revisionId: sameDocument ? list.revisionId : null, scroll: 0 },
    };
    this.pushPage('/requirements/' + requirementId, entry);
  };
  openCodeHandoff = (requirementId: number, link: DocumentHandoffLink): void => {
    const route = this.value.route;
    if (
      route.kind !== 'CODE_TASK' ||
      route.taskId !== link.taskId ||
      !safeId(requirementId) ||
      !safeId(link.documentId) ||
      !safeId(link.handoffId)
    )
      return;
    const routePath = '/requirements/' + requirementId;
    const query = new URLSearchParams({
      document_id: String(link.documentId),
      code_task_id: String(link.taskId),
      code_handoff_id: String(link.handoffId),
    });
    const entry: DetailEntry = {
      schema_version: 2,
      kind: 'WALLE_DETAIL',
      entry_id: this.identify(),
      id: requirementId,
      position: this.position + 1,
      from: null,
    };
    this.pushPage(routePath + '?' + query.toString(), entry, routePath);
  };
  openCodeSettings = (): void => {
    this.allowed(() => {
      this.historyPort.pushState(null, '', '/settings/code');
      this.position++;
      this.apply('/settings/code', false);
    });
  };
  openTestingSettings = (): void => {
    this.allowed(() => this.pushPage('/settings/testing', null));
  };
  openTestingList = (): void => {
    this.allowed(() => this.pushPage('/testing' + this.testingListSearch, null, '/testing'));
  };
  selectTestingList = (search: URLSearchParams): void => {
    this.testingListSearch = search.size ? '?' + search.toString() : '';
    this.openTestingList();
  };
  openTestingTask = (identity: number, search?: URLSearchParams): void => {
    if (!safeId(identity)) return;
    if (this.value.route.kind === 'TESTING_LIST')
      this.testingListSearch = this.browser.search?.() ?? this.testingListSearch;
    const path = '/testing/tasks/' + identity;
    this.allowed(() =>
      this.pushPage(search?.size ? path + '?' + search.toString() : path, null, path),
    );
  };
  openTestingPlans = (
    plan: number | null = null,
    version: number | null = null,
    pack: number | null = null,
    validation: number | null = null,
  ): void => {
    if (
      (plan !== null && !safeId(plan)) ||
      (version !== null && (plan === null || !safeId(version))) ||
      (pack !== null && (version === null || !safeId(pack))) ||
      (validation !== null && (pack === null || !safeId(validation)))
    )
      return;
    const path = '/testing/plans';
    const search = new URLSearchParams();
    if (plan !== null) search.set('plan_id', String(plan));
    if (version !== null) search.set('plan_version_id', String(version));
    if (pack !== null) search.set('pack_id', String(pack));
    if (validation !== null) search.set('validation_id', String(validation));
    this.allowed(() => this.pushPage(search.size ? path + '?' + search : path, null, path));
  };
  selectCodeSettingsSection = (section: CodeSettingsSection): void => {
    if (this.closed || this.value.route.kind !== 'CODE_SETTINGS') return;
    const path = '/settings/code';
    this.historyPort.pushState(null, '', path + '?section=' + section);
    this.position++;
    this.apply(path, false);
  };
  private openWorkbench(navIntent: WorkbenchNavIntent) {
    this.allowed(() => {
      if (this.value.workbench)
        this.saveEntry(this.value.workbench.state.requested, this.browser.scroll());
      this.historyPort.pushState(null, '', '/requirements');
      this.position++;
      this.apply('/requirements', false, navIntent);
    });
  }
  mainNavigation = (): void => this.openWorkbench(null);
  openCodeDevelopment = (): void => this.openWorkbench('CHOOSE_CODE_DOCUMENT');
  /** Called by the detail component only after its own departure succeeded. */
  backToWorkbench = (): void => {
    if (this.closed) return;
    this.historyPort.replaceState(null, '', '/requirements');
    this.apply('/requirements', false);
  };
  private pop = (): void => {
    if (this.closed) return;
    const target: Destination = {
      path: this.browser.pathname(),
      state: this.historyPort.state,
      position: this.readPosition(this.historyPort.state, this.browser.pathname()),
    };
    if (this.restoration) {
      const pending = this.restoration;
      if (
        target.path !== pending.original.path ||
        entryId(target.state) !== entryId(pending.original.state)
      ) {
        this.publish({ warning: '浏览器返回位置尚未恢复，请保持当前页面。' });
        return;
      }
      this.restoration = null;
      this.allowed(() => {
        this.approved = pending.target;
        this.historyPort.go(pending.target.position! - this.position);
      });
      return;
    }
    if (this.approved) {
      const approved = this.approved;
      this.approved = null;
      const approvedIdentity = entryId(approved.state);
      const matchesEntry = approvedIdentity
        ? entryId(target.state) === approvedIdentity
        : approved.position === null || target.position === approved.position;
      if (target.path === approved.path && matchesEntry) {
        if (approved.state && pageRoute(target.path).kind === 'WORKBENCH')
          this.historyPort.replaceState(approved.state, '', target.path);
        this.position = approved.position ?? target.position ?? this.position;
        this.apply(target.path, true);
        return;
      }
    }
    const guarded = (this.value.route.kind === 'DETAIL' && this.departure) || this.blocked;
    if (guarded) {
      const original: Destination = {
        path: this.currentPath,
        state: this.currentState,
        position: this.position,
      };
      if (target.position !== null && target.position !== this.position) {
        this.restoration = { original, target };
        this.historyPort.go(this.position - target.position);
        return;
      }
      // Unowned/corrupt history cannot justify a guessed history.go direction.
      this.historyPort.replaceState(original.state, '', original.path);
      this.allowed(() => {
        this.historyPort.replaceState(target.state, '', target.path);
        this.position = target.position ?? this.position;
        this.apply(target.path, true);
      });
      return;
    }
    this.position = target.position ?? this.position;
    const activeTask = this.value.task;
    if (activeTask !== null && target.path === '/code-tasks/' + activeTask.taskId) {
      const task = this.readTask(activeTask.taskId, target.state);
      if (task !== null && task.position === this.position) {
        this.currentState = task;
        this.publish({
          task,
          taskWorkspace: readWorkspaceRoute(this.browser.search?.() ?? ''),
          restoreScroll: task.scroll,
        });
        return;
      }
    }
    this.apply(target.path, true);
  };
  dispose(): void {
    this.closed = true;
    this.release();
    for (const list of this.lists.values()) list.dispose();
    this.value.creation?.dispose();
    this.listeners.clear();
  }
}
