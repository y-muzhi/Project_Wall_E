import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import type { MouseEvent } from 'react';
import type { CodingExecutionRecord } from '../api/code-task-records.ts';
import type { WalleApi } from '../api/walle.ts';
import { EmptyState } from '../shared/empty-state.tsx';
import { localTime } from '../shared/time.ts';
import { Pager, ReadState } from '../testing/plans/read.tsx';
import { useSettingsRead } from './settings/read.ts';
import { workspacePath } from './workspace-route.ts';

const kindLabel: Record<CodingExecutionRecord['kind'], string> = {
  MESSAGE: '消息',
  TOOL: '工具',
  COMMAND_OUTPUT: '命令输出',
  CONTROL: '控制记录',
  ERROR: '错误',
};

function activePollDelay() {
  return 2000;
}

type RecordPage = Awaited<ReturnType<WalleApi['codeTaskRecords']>>;
type RecordsRead = Readonly<{ page: number; direction: 'PAGE' | 'LATEST' | 'FOLLOW' }>;
type ShownRecords = Readonly<{ value: RecordPage; scrollToEnd: boolean }>;

function canFollow(viewport: HTMLElement | null) {
  return (
    viewport !== null &&
    viewport.scrollHeight - viewport.clientHeight - viewport.scrollTop <= 4 &&
    (window.getSelection()?.isCollapsed ?? true) &&
    !document.activeElement?.closest(
      'input, select, textarea, [contenteditable]:not([contenteditable="false"]), [role="dialog"], dialog[open]',
    )
  );
}

function SessionRecords({
  api,
  task,
  session,
  ready,
  live,
  routePage,
  onPage,
  openOperation,
}: Readonly<{
  api: WalleApi;
  task: number;
  session: number | null;
  ready: boolean;
  live: boolean;
  routePage: number;
  onPage(page: number): void;
  openOperation(id: number, source: HTMLAnchorElement): void;
}>) {
  const [target, setTarget] = useState<RecordsRead>({ page: routePage, direction: 'PAGE' });
  const [shown, setShown] = useState<ShownRecords | null>(null);
  const [observed, setObserved] = useState<RecordPage['meta']['pagination'] | null>(null);
  const [seenTotal, setSeenTotal] = useState<number | null>(null);
  const [following, setFollowing] = useState(false);
  const viewport = useRef<HTMLDivElement>(null);
  const [retry, setRetry] = useState(0);
  const load = useCallback(
    async (signal: AbortSignal) => {
      void retry;
      return { target, value: await api.codeTaskRecords(task, target.page, session, signal) };
    },
    [api, task, target, session, retry],
  );
  const read = useSettingsRead(
    load,
    ready,
    '暂时无法读取执行记录',
    live ? activePollDelay : undefined,
  );
  const handled = useRef<typeof read.value>(null);
  const handledTarget = useRef<RecordsRead>(null);

  useLayoutEffect(() => {
    const result = read.value;
    if (result === null || result === handled.current || result.target !== target) return;
    handled.current = result;
    const firstForTarget = handledTarget.current !== target;
    handledTarget.current = target;
    const value = result.value;
    const incoming = value.meta.pagination;
    const lastPage = Math.max(1, incoming.total_pages);
    setObserved(incoming);
    if (seenTotal === null || incoming.total < seenTotal) setSeenTotal(incoming.total);

    function showLatest() {
      setShown({ value, scrollToEnd: true });
      const shownThrough = incoming.page * incoming.page_size;
      setSeenTotal(Math.min(incoming.total, shownThrough));
    }

    if (firstForTarget && target.direction === 'LATEST') {
      showLatest();
      return;
    }

    if (firstForTarget && target.direction === 'FOLLOW') {
      if (following && canFollow(viewport.current)) {
        showLatest();
        return;
      }
      const previousPage = shown?.value.meta.pagination.page ?? 1;
      setTarget({ page: previousPage, direction: 'PAGE' });
      return;
    }

    const prior = shown?.value.meta.pagination;
    const grew = seenTotal !== null && incoming.total > seenTotal;
    if (
      grew &&
      prior?.page === incoming.page &&
      prior.page === Math.max(1, prior.total_pages) &&
      following &&
      canFollow(viewport.current)
    ) {
      if (lastPage > prior.page) {
        setTarget({ page: lastPage, direction: 'FOLLOW' });
      } else {
        showLatest();
      }
      return;
    }

    if (!grew || prior?.page !== incoming.page || prior.total === 0) {
      setShown({ value, scrollToEnd: false });
      if (prior?.total === 0 && incoming.page === 1)
        setSeenTotal(Math.min(incoming.total, incoming.page_size));
    }
  }, [read.value, target, seenTotal, shown, following]);

  useLayoutEffect(() => {
    const list = viewport.current;
    if (list !== null && shown?.scrollToEnd) list.scrollTop = list.scrollHeight;
  }, [shown]);

  useLayoutEffect(() => {
    setFollowing(false);
    setTarget((previous) =>
      previous.page === routePage && previous.direction === 'PAGE'
        ? previous
        : { page: routePage, direction: 'PAGE' },
    );
  }, [routePage]);

  function selectPage(page: number) {
    setFollowing(false);
    if (page === routePage) setTarget({ page, direction: 'PAGE' });
    else onPage(page);
  }

  function openLatest() {
    if (observed !== null)
      setTarget({ page: Math.max(1, observed.total_pages), direction: 'LATEST' });
  }

  function changeFollowing() {
    setFollowing(!following);
    if (!following) openLatest();
  }

  const items = shown?.value.data.items;
  const page = shown?.value.meta.pagination.page ?? target.page;
  const loading = ready && (read.loading || (!read.error && read.value?.target !== target));
  const unseen = Math.max(0, (observed?.total ?? 0) - (seenTotal ?? 0));
  const paging = observed === null ? null : { page, total_pages: observed.total_pages };
  const recordsReady = observed !== null && !loading && !read.error;
  return (
    <>
      <div className="code-task-toolbar code-record-toolbar">
        <button
          type="button"
          className="ui-button"
          aria-pressed={following}
          disabled={!recordsReady && !following}
          title={!recordsReady && !following ? '记录尚未读到' : undefined}
          onClick={changeFollowing}
        >
          跟随最新
        </button>
        <button
          type="button"
          className="ui-button"
          disabled={!recordsReady}
          title={!recordsReady ? '请先恢复记录读取' : undefined}
          onClick={openLatest}
        >
          {unseen > 0 ? '查看最新（' + unseen + ' 条新增）' : '查看最新'}
        </button>
      </div>
      <ReadState
        loading={loading}
        error={read.error}
        stale={shown !== null}
        retry={() => setRetry((value) => value + 1)}
      />
      {items && items.length === 0 && !loading && !read.error && (
        <EmptyState
          icon="outline"
          message={page > 1 ? '当前页没有执行记录' : '暂无执行记录'}
          compact
        />
      )}
      <div
        className="code-task-record-viewport"
        ref={viewport}
        role={items?.length ? 'group' : undefined}
        aria-label={items?.length ? '记录内容' : undefined}
        tabIndex={items?.length ? 0 : undefined}
      >
        {items && items.length > 0 && (
          <ol
            className="code-task-execution-records"
            start={(page - 1) * (observed?.page_size ?? 20) + 1}
          >
            {items.map((row) => (
              <li key={row.id}>
                <header>
                  {kindLabel[row.kind]} · {localTime(row.observed_at)}
                  {row.session_id !== null && ' · 会话 #' + row.session_id}
                  {row.source_kind === 'OPERATION' && row.source_id !== null && (
                    <>
                      {' · '}
                      <OperationSourceLink
                        task={task}
                        operation={row.source_id}
                        open={openOperation}
                      />
                    </>
                  )}
                </header>
                <p>{row.text}</p>
              </li>
            ))}
          </ol>
        )}
      </div>
      <Pager meta={paging} page={page} busy={loading} select={selectPage} />
    </>
  );
}

function OperationSourceLink({
  task,
  operation,
  open,
}: Readonly<{
  task: number;
  operation: number;
  open(id: number, source: HTMLAnchorElement): void;
}>) {
  function activate(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey)
      return;
    event.preventDefault();
    open(operation, event.currentTarget);
  }

  return (
    <a href={workspacePath(task, { tab: 'execution', operationId: operation })} onClick={activate}>
      原操作 #{operation}
    </a>
  );
}

export function TaskRecords({
  api,
  task,
  currentSession,
  ready,
  live,
  page,
  selectPage,
  openOperation,
}: Readonly<{
  api: WalleApi;
  task: number;
  currentSession: number | null;
  ready: boolean;
  live: boolean;
  page: number;
  selectPage(page: number): void;
  openOperation(id: number, source: HTMLAnchorElement): void;
}>) {
  const [filter, setFilter] = useState<'all' | 'current'>('all');
  const session = filter === 'current' ? currentSession : null;
  return (
    <section className="code-task-result" aria-label="执行记录">
      <h2>执行记录</h2>
      <div className="code-task-toolbar">
        <label>
          会话范围{' '}
          <select
            value={session === null ? 'all' : 'current'}
            onChange={(event) => {
              setFilter(event.currentTarget.value === 'current' ? 'current' : 'all');
              if (page !== 1) selectPage(1);
            }}
          >
            <option value="all">全部会话</option>
            <option value="current" disabled={currentSession === null}>
              当前会话
            </option>
          </select>
        </label>
      </div>
      <SessionRecords
        key={task + ':' + session}
        api={api}
        task={task}
        session={session}
        ready={ready}
        live={live}
        routePage={page}
        onPage={selectPage}
        openOperation={openOperation}
      />
    </section>
  );
}
