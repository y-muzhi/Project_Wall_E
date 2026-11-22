import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiRejected } from '../api/client.ts';
import type { WalleApi } from '../api/walle.ts';
import { environmentBrowserStorage } from '../api/environment-storage.ts';
import type { CodeTaskSummary } from '../api/code-task-list.ts';
import { EmptyState } from '../shared/empty-state.tsx';
import { MultiFilter } from '../shared/filter.tsx';
import { Pagination } from '../shared/pagination.tsx';
import { useSettingsRead, useSettingsVisibility } from './settings/read.ts';
import { ACTIVE_TASK_STATUSES, DEFAULT_TASK_QUERY, TASK_PHASE, TASK_STATUS } from './list-model.ts';
import type { CodeTaskQuery } from './list-model.ts';
import type { CodeTaskStatus } from '../api/code-task-list.ts';
import { CreateCodeTaskDrawer } from './create.tsx';
import { CommandRecoveryStore } from './command-recovery-store.ts';
import { createTaskPath, restoreCreateDraft } from './create-draft.ts';
import './task-pages.css';

const statuses = (Object.keys(TASK_STATUS) as CodeTaskStatus[]).map((value) => ({
  value,
  label: TASK_STATUS[value],
}));
type Props = Readonly<{
  api: WalleApi;
  requirementId: number;
  documentId: number;
  query: CodeTaskQuery;
  restoreScroll: number;
  revisionId: number | null;
  update(query: CodeTaskQuery, scroll: number): void;
  openTask(taskId: number, requirementId: number, documentId: number): void;
  back(requirementId: number, documentId: number): void;
  settings(): void;
}>;

function TaskRevision({
  api,
  row,
  requirementId,
  visible,
}: Readonly<{
  api: WalleApi;
  row: CodeTaskSummary;
  requirementId: number;
  visible: boolean;
}>) {
  const load = useCallback(
    async (signal: AbortSignal) => {
      const task = (await api.codeTask(row.id, signal)).data;
      if (task.requirement_id !== requirementId || task.document_id !== row.document_id)
        throw Error('Task basis has a different owner');
      const revision = (await api.getRevision(task.design_revision_id, signal)).data;
      if (revision.requirement_id !== requirementId || revision.document_id !== row.document_id)
        throw Error('Task basis has a different document');
      return revision.version_no;
    },
    [api, row.id, row.document_id, requirementId],
  );
  const state = useSettingsRead(load, visible, '版本信息暂不可读');
  return (
    <span>
      {state.value !== null
        ? '版本 ' + state.value
        : state.loading
          ? '正在读取版本'
          : '版本信息暂不可读'}
    </span>
  );
}

export function DocumentCodeTasks(props: Props) {
  const { api, requirementId, documentId, query, update } = props;
  const visible = useSettingsVisibility();
  const [ownerRetry, retryOwner] = useState(0);
  const load = useCallback(
    async (signal: AbortSignal) => {
      void ownerRetry;
      try {
        return (await api.getCurrentDocument(requirementId, documentId, signal)).data;
      } catch (error) {
        if (error instanceof ApiRejected && error.code === 'NOT_FOUND')
          throw new ApiRejected(
            error.code,
            '当前文档不存在或不属于此需求',
            error.details,
            error.request_id,
            error.status,
          );
        throw error;
      }
    },
    [api, requirementId, documentId, ownerRetry],
  );
  const owner = useSettingsRead(load, visible, '暂时无法读取所属文档');
  return (
    <main className="code-task-page" aria-busy={owner.loading}>
      <header className="code-task-heading">
        <div>
          <h1>代码任务</h1>
          {owner.value && <p>{owner.value.name}</p>}
        </div>
        {owner.value && (
          <button
            type="button"
            className="ui-button"
            onClick={() => props.back(requirementId, documentId)}
          >
            返回文档
          </button>
        )}
      </header>
      {owner.loading && <p role="status">正在核对所属文档…</p>}
      {owner.error && (
        <p role="alert" className="inline-error">
          {owner.error}{' '}
          <button
            type="button"
            className="ui-button"
            onClick={() => retryOwner((value) => value + 1)}
          >
            重试读取文档
          </button>
        </p>
      )}
      {owner.value && (
        <OwnedTaskList
          {...props}
          query={query}
          update={update}
          ownerReady={!owner.loading && !owner.error}
          documentTitle={owner.value.name}
          visible={visible}
        />
      )}
    </main>
  );
}

function OwnedTaskList({
  api,
  requirementId,
  documentId,
  query,
  restoreScroll,
  update,
  openTask,
  revisionId,
  documentTitle,
  settings,
  ownerReady,
  visible,
}: Props & Readonly<{ ownerReady: boolean; documentTitle: string; visible: boolean }>) {
  const [readRetry, retryList] = useState(0);
  const [activeRetry, retryActive] = useState(0);
  const [drawer, setDrawer] = useState(false);
  const [conflictId, setConflictId] = useState<number | null>(null);
  const [openingDrawer, setOpeningDrawer] = useState(false);
  const openDrawerRequest = useRef<AbortController | null>(null);
  const [revisionPage, setRevisionPage] = useState(1);
  const [selectedRevisionLabel, setSelectedRevisionLabel] = useState<string | null>(null);
  const [opening, setOpening] = useState<number | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);
  const openRequest = useRef<AbortController | null>(null);
  const firstScroll = useRef(restoreScroll);
  const restored = useRef(false);
  const activeReader = visible && ownerReady;
  const loadTasks = useCallback(
    (signal: AbortSignal) => {
      void readRetry;
      return api.documentCodeTasks(
        documentId,
        query.page,
        {
          statuses: query.statuses,
          ...(query.revisionId === null ? {} : { designRevisionId: query.revisionId }),
        },
        signal,
      );
    },
    [api, documentId, query, readRetry],
  );
  const loadChoices = useCallback(
    (signal: AbortSignal) => api.listRevisions(requirementId, documentId, revisionPage, signal),
    [api, requirementId, documentId, revisionPage],
  );
  const loadActive = useCallback(
    (signal: AbortSignal) => {
      void activeRetry;
      return api.documentCodeTasks(documentId, 1, { statuses: ACTIVE_TASK_STATUSES }, signal);
    },
    [api, documentId, activeRetry],
  );
  const loadRecovery = useCallback(
    async (signal: AbortSignal) => {
      void activeRetry;
      const store = new CommandRecoveryStore({ scope: api.environmentScope });
      try {
        const draft = restoreCreateDraft(
          environmentBrowserStorage('sessionStorage', api.environmentScope).getItem(
            'walle:v2.0:code:create:' + location.origin + ':' + requirementId + ':' + documentId,
          ),
          requirementId,
          documentId,
        );
        if (draft.original_key !== null) return true;
      } catch {}
      try {
        const pending = await store.list();
        return (
          !signal.aborted && pending.some((record) => record.path === createTaskPath(documentId))
        );
      } finally {
        store.close();
      }
    },
    [api, requirementId, documentId, activeRetry],
  );
  const rows = useSettingsRead(loadTasks, activeReader, '暂时无法读取任务列表');
  const revisions = useSettingsRead(loadChoices, activeReader, '暂时无法读取筛选版本');
  const active = useSettingsRead(loadActive, activeReader, '暂时无法核对活动任务名额');
  const activeTaskId = active.value?.data.items[0]?.id ?? conflictId;
  const recovery = useSettingsRead(loadRecovery, activeReader, '暂时无法核对原请求记录');
  const pagination = rows.value?.meta.pagination;
  const page = pagination && 'page' in pagination ? pagination : null;
  const revisionPagination = revisions.value?.meta.pagination;
  const versionPage =
    revisionPagination && 'page' in revisionPagination ? revisionPagination : null;

  useEffect(() => {
    if (activeReader)
      return () => {
        openRequest.current?.abort();
        openRequest.current = null;
        openDrawerRequest.current?.abort();
        openDrawerRequest.current = null;
      };
    setOpening(null);
    setOpeningDrawer(false);
  }, [activeReader]);
  useEffect(() => {
    if (!restored.current && rows.value) {
      restored.current = true;
      window.scrollTo(0, firstScroll.current);
    }
  }, [rows.value]);
  function change(next: CodeTaskQuery) {
    update(next, 0);
  }
  async function inspectTask(id: number) {
    if (!ownerReady || openRequest.current) return;
    const controller = new AbortController();
    openRequest.current = controller;
    setOpening(id);
    setOpenError(null);
    try {
      const task = (await api.codeTask(id, controller.signal)).data;
      if (controller.signal.aborted) return;
      if (task.document_id !== documentId || task.requirement_id !== requirementId)
        throw Error('Task belongs to another document');
      openTask(task.id, requirementId, documentId);
    } catch (error) {
      if (!controller.signal.aborted)
        setOpenError(
          error instanceof ApiRejected
            ? error.code === 'NOT_FOUND'
              ? '代码任务不存在'
              : error.message
            : '暂时无法读取该任务，请重试',
        );
    } finally {
      if (openRequest.current === controller) openRequest.current = null;
      if (!controller.signal.aborted) setOpening(null);
    }
  }
  function taskConflict(id: number) {
    setConflictId(id);
    retryActive((value) => value + 1);
    retryList((value) => value + 1);
  }
  async function openCreate() {
    if (openDrawerRequest.current || !activeReader || activeTaskId !== null) return;
    const request = new AbortController();
    openDrawerRequest.current = request;
    setOpeningDrawer(true);
    setOpenError(null);
    try {
      const result = await api.documentCodeTasks(
        documentId,
        1,
        { statuses: ACTIVE_TASK_STATUSES },
        request.signal,
      );
      if (request.signal.aborted) return;
      const task = result.data.items[0];
      if (task) taskConflict(task.id);
      else setDrawer(true);
    } catch {
      if (!request.signal.aborted) setOpenError('暂时无法核对活动任务名额，请重试。');
    } finally {
      if (openDrawerRequest.current === request) openDrawerRequest.current = null;
      if (!request.signal.aborted) setOpeningDrawer(false);
    }
  }
  function closeDrawer() {
    setDrawer(false);
    setConflictId(null);
    retryActive((value) => value + 1);
    retryList((value) => value + 1);
  }
  const inPage = revisions.value?.data.items.some((item) => item.id === query.revisionId);
  const activeHint = !ownerReady
    ? '等待核对所属文档'
    : active.loading || openingDrawer
      ? '正在核对活动任务名额…'
      : (active.error ?? (activeTaskId !== null ? '当前文档已有活动任务' : null));
  return (
    <>
      <div className="code-task-toolbar">
        <MultiFilter
          name="状态"
          options={statuses}
          value={query.statuses}
          disabled={!ownerReady}
          change={(values, all) => change({ ...query, page: 1, statuses: all ? [] : values })}
        />
        <label>
          固定版本{' '}
          <select
            value={query.revisionId ?? ''}
            disabled={!ownerReady || !revisions.value}
            onChange={(event) => {
              const revisionId = event.target.value === '' ? null : Number(event.target.value);
              setSelectedRevisionLabel(event.target.selectedOptions[0]?.text ?? null);
              change({ ...query, page: 1, revisionId });
            }}
          >
            <option value="">全部版本</option>
            {query.revisionId !== null && !inPage && (
              <option value={query.revisionId}>
                {selectedRevisionLabel ?? '原选版本 #' + query.revisionId}
              </option>
            )}
            {revisions.value?.data.items.map((item) => (
              <option key={item.id} value={item.id}>
                版本 {item.version_no} · #{item.id}
              </option>
            ))}
          </select>
        </label>
        {versionPage && versionPage.total_pages > 1 && (
          <div className="code-task-toolbar" aria-label="版本选项分页">
            <button
              type="button"
              className="ui-button"
              disabled={revisions.loading || revisionPage <= 1}
              onClick={() => setRevisionPage(revisionPage - 1)}
            >
              上一页版本
            </button>
            <button
              type="button"
              className="ui-button"
              disabled={revisions.loading || revisionPage >= versionPage.total_pages}
              onClick={() => setRevisionPage(revisionPage + 1)}
            >
              下一页版本
            </button>
          </div>
        )}
        <button
          type="button"
          className="ui-button"
          disabled={!ownerReady}
          onClick={() => change(DEFAULT_TASK_QUERY)}
        >
          清除筛选
        </button>
        <button
          type="button"
          className="ui-button"
          aria-describedby={activeHint ? 'create-code-task-reason' : undefined}
          disabled={activeHint !== null || recovery.loading}
          onClick={() => void openCreate()}
        >
          创建任务
        </button>
      </div>
      <p id="create-code-task-reason" className="read-status" role="status">
        {activeHint}{' '}
        {active.error && (
          <button
            type="button"
            className="ui-button"
            disabled={!ownerReady}
            onClick={() => retryActive((value) => value + 1)}
          >
            重试核对活动名额
          </button>
        )}
        {activeTaskId !== null && (
          <button
            type="button"
            className="ui-button"
            disabled={opening !== null || !ownerReady}
            onClick={() => void inspectTask(activeTaskId)}
          >
            查看活动任务 #{activeTaskId}
          </button>
        )}
      </p>
      {recovery.value && activeTaskId !== null && (
        <button
          type="button"
          className="ui-button"
          disabled={!ownerReady}
          onClick={() => setDrawer(true)}
        >
          核对原创建请求
        </button>
      )}
      {drawer && (
        <CreateCodeTaskDrawer
          api={api}
          requirementId={requirementId}
          documentId={documentId}
          documentTitle={documentTitle}
          revisionId={revisionId}
          visible={activeReader}
          activeTaskId={activeTaskId}
          close={closeDrawer}
          created={(id) => openTask(id, requirementId, documentId)}
          conflict={taskConflict}
          settings={settings}
        />
      )}
      {revisions.error && <p role="alert">{revisions.error}</p>}
      {openError && (
        <p className="inline-error" role="alert">
          {openError}
        </p>
      )}
      <section className="code-task-result" aria-label="文档任务列表" aria-busy={rows.loading}>
        {rows.loading && <p role="status">正在读取任务…</p>}
        {rows.error && (
          <p role="alert" className="inline-error">
            {rows.error}{' '}
            <button
              type="button"
              className="ui-button"
              disabled={!ownerReady}
              onClick={() => retryList((value) => value + 1)}
            >
              重试读取
            </button>
          </p>
        )}
        {rows.value?.data.items.length ? (
          <ol className="code-task-rows">
            {rows.value.data.items.map((row) => (
              <li key={row.id}>
                <time dateTime={row.created_at}>
                  {new Date(row.created_at).toLocaleString('zh-CN')}
                </time>
                <TaskRevision
                  api={api}
                  row={row}
                  requirementId={requirementId}
                  visible={activeReader}
                />
                <span>{TASK_PHASE[row.phase]}</span>
                <span>{TASK_STATUS[row.status]}</span>
                <button
                  type="button"
                  className="ui-button"
                  disabled={!ownerReady || opening !== null}
                  onClick={() => void inspectTask(row.id)}
                >
                  {opening === row.id ? '正在读取任务…' : '查看任务 #' + row.id}
                </button>
              </li>
            ))}
          </ol>
        ) : !rows.loading && !rows.error && page ? (
          <EmptyState
            icon="outline"
            message={
              page.page > Math.max(page.total_pages, 1)
                ? '当前页超出任务列表范围'
                : query.statuses.length || query.revisionId !== null
                  ? '没有符合筛选条件的任务'
                  : '当前文档尚无代码任务'
            }
          />
        ) : null}
        {page && (
          <Pagination
            value={page}
            loading={rows.loading}
            showLoadingStatus={false}
            change={(number) => change({ ...query, page: number })}
          />
        )}
        {page && page.total === 0 && page.page > 1 && (
          <button
            type="button"
            className="ui-button"
            onClick={() => change({ ...query, page: page.page - 1 })}
          >
            上一页
          </button>
        )}
      </section>
    </>
  );
}
