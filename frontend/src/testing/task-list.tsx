import { useCallback, useEffect, useState } from 'react';
import { positiveInteger } from '../api/client.ts';
import { testingAuthorizationPath } from '../api/testing-policy.ts';
import {
  testingTaskPurposes,
  testingTaskStatuses,
  testingTasksPath,
} from '../api/testing-tasks.ts';
import type { TestingTaskFilters, TestingTaskSummary } from '../api/testing-tasks.ts';
import type { WalleApi } from '../api/walle.ts';
import { PageHeader } from '../application/header.tsx';
import { EmptyState } from '../shared/empty-state.tsx';
import { localTime } from '../shared/time.ts';
import { CreateTestingTaskDrawer } from './create-task.tsx';
import type { CreationReceipt } from './create-task.tsx';
import { meta, Pager, ReadState, useTestingRead } from './plans/read.tsx';
import { textId } from './task-controls.tsx';
import { testingPhase, testingPurpose, testingStatus } from './task-labels.ts';
import { OriginalTaskRequests, useTestingRecovery } from './task-recovery.tsx';

type FilterDraft = { requirement_id: string; document_id: string; status: string; purpose: string };
type Selection = { filters: TestingTaskFilters; page: number };
function parseList(search: string): Selection | null {
  const query = new URLSearchParams(search);
  const known = new Set([
    'page',
    'requirement_id',
    'document_id',
    'status',
    'purpose',
    'candidate_id',
    'snapshot_id',
  ]);
  if ([...query].some(([key]) => !known.has(key) || query.getAll(key).length !== 1)) return null;
  const page = query.has('page') ? textId(query.get('page')!) : 1;
  if (page === null || page > 100000) return null;
  const result: Partial<
    Record<'requirement_id' | 'document_id' | 'candidate_id' | 'snapshot_id', number>
  > = {};
  for (const field of ['requirement_id', 'document_id', 'candidate_id', 'snapshot_id'] as const) {
    const value = query.get(field);
    if (value === null) continue;
    const id = textId(value);
    if (id === null) return null;
    result[field] = id;
  }
  const status = testingTaskStatuses.find((item) => item === query.get('status'));
  const purpose = testingTaskPurposes.find((item) => item === query.get('purpose'));
  if (
    (query.has('status') && status === undefined) ||
    (query.has('purpose') && purpose === undefined)
  )
    return null;
  return {
    page,
    filters: {
      ...result,
      ...(status === undefined ? {} : { status }),
      ...(purpose === undefined ? {} : { purpose }),
    },
  };
}
function filterText(filters: TestingTaskFilters): FilterDraft {
  return {
    requirement_id: filters.requirement_id?.toString() ?? '',
    document_id: filters.document_id?.toString() ?? '',
    status: filters.status ?? '',
    purpose: filters.purpose ?? '',
  };
}

function TaskRows({
  items,
  open,
}: Readonly<{ items: readonly TestingTaskSummary[]; open(id: number): void }>) {
  return (
    <ol className="code-settings-version-items">
      {items.map((row) => (
        <li key={row.id} className="testing-editor-panel">
          <div className="code-settings-form-actions">
            <button type="button" className="ui-button" onClick={() => open(row.id)}>
              测试任务 #{row.id}
            </button>
            <span>
              {testingStatus[row.status]} · {testingPhase[row.phase]} ·{' '}
              {testingPurpose[row.purpose]}
            </span>
          </div>
          <p>
            {row.target_kind === 'SNAPSHOT'
              ? '仓库快照 #' + row.snapshot_id
              : 'Coding 候选 #' + row.candidate_id}
            {' · '}需求 #{row.requirement_id} · 文档 #{row.document_id}
          </p>
          <p>
            {localTime(row.created_at)}
            {row.report_id !== null && ' · 原报告 #' + row.report_id}
          </p>
        </li>
      ))}
    </ol>
  );
}

export function TestingTaskList({
  api,
  query,
  navigate,
  open,
  plans,
  settings,
}: Readonly<{
  api: WalleApi;
  query: string;
  navigate(value: URLSearchParams): void;
  open(id: number): void;
  plans(): void;
  settings(): void;
}>) {
  const selected = parseList(query);
  const [draft, setDraft] = useState<FilterDraft>(() => filterText(selected?.filters ?? {}));
  const [drawer, setDrawer] = useState(false);
  const [received, setReceived] = useState<CreationReceipt | null>(null);
  const load = useCallback(
    (signal: AbortSignal) => {
      const original = parseList(query);
      if (original === null) throw new TypeError('Testing list query differs');
      return api.testingTasks(original.filters, original.page, signal);
    },
    [api, query],
  );
  const tasks = useTestingRead('testing-list:' + query, selected === null ? null : load);
  const access = useTestingRecovery(
    api,
    (record) => record.path === testingTasksPath || record.path === testingAuthorizationPath,
    (record, lookup) => {
      const outcome = lookup.original_receipt?.original_outcome;
      if (outcome?.success !== true) return;
      if (record.path === testingTasksPath) {
        setReceived({
          key: record.key,
          kind: 'create',
          id: positiveInteger((outcome.data as { testing_task_id: number }).testing_task_id),
        });
        tasks.reload();
      } else {
        setReceived({
          key: record.key,
          kind: 'approve',
          id: positiveInteger((outcome.data as { id: number }).id),
        });
      }
    },
  );
  useEffect(() => {
    setDraft(filterText(parseList(query)?.filters ?? {}));
  }, [query]);
  useEffect(() => {
    const old = document.title;
    document.title = 'WALL-E · 独立测试任务';
    return () => {
      document.title = old;
    };
  }, []);
  const invalid = [draft.requirement_id, draft.document_id].some(
    (value) => value !== '' && textId(value) === null,
  );
  function filter() {
    if (invalid) return;
    const next = new URLSearchParams();
    for (const [field, value] of Object.entries(draft)) if (value !== '') next.set(field, value);
    navigate(next);
  }
  function pageTo(page: number) {
    const next = new URLSearchParams(query);
    if (page === 1) next.delete('page');
    else next.set('page', String(page));
    navigate(next);
  }
  function onCreated(task: number) {
    setDrawer(false);
    tasks.reload();
    open(task);
  }
  return (
    <main className="code-settings testing-plans">
      <PageHeader>
        <header className="code-settings-heading">
          <h1>独立测试任务</h1>
        </header>
      </PageHeader>
      <div className="code-settings-form-actions">
        <button className="ui-button" type="button" onClick={() => setDrawer(true)}>
          新建测试任务
        </button>
        <button className="ui-button" type="button" onClick={() => plans()}>
          测试计划与资源
        </button>
        <button className="ui-button" type="button" onClick={settings}>
          测试配置与恢复
        </button>
      </div>
      <OriginalTaskRequests access={access} />
      {received?.kind === 'create' && !drawer && (
        <p role="status">
          已核实原创建{' '}
          <button className="ui-button" type="button" onClick={() => open(received.id)}>
            打开测试任务 #{received.id}
          </button>
        </p>
      )}
      <section className="testing-editor-panel" aria-label="测试任务目录">
        <h2>任务目录</h2>
        {selected === null ? (
          <div className="code-settings-form-actions">
            <p role="alert" className="inline-error">
              测试任务筛选参数无效。
            </p>
            <button
              className="ui-button"
              type="button"
              onClick={() => navigate(new URLSearchParams())}
            >
              返回完整目录
            </button>
          </div>
        ) : (
          <>
            <form
              className="code-settings-form-actions"
              onSubmit={(event) => {
                event.preventDefault();
                filter();
              }}
            >
              <label>
                需求编号{' '}
                <input
                  className="ui-input"
                  inputMode="numeric"
                  value={draft.requirement_id}
                  onChange={(event) =>
                    setDraft({ ...draft, requirement_id: event.currentTarget.value })
                  }
                />
              </label>
              <label>
                文档编号{' '}
                <input
                  className="ui-input"
                  inputMode="numeric"
                  value={draft.document_id}
                  onChange={(event) =>
                    setDraft({ ...draft, document_id: event.currentTarget.value })
                  }
                />
              </label>
              <label>
                状态{' '}
                <select
                  className="ui-input"
                  value={draft.status}
                  onChange={(event) => setDraft({ ...draft, status: event.currentTarget.value })}
                >
                  <option value="">全部状态</option>
                  {testingTaskStatuses.map((key) => (
                    <option key={key} value={key}>
                      {testingStatus[key]}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                用途{' '}
                <select
                  className="ui-input"
                  value={draft.purpose}
                  onChange={(event) => setDraft({ ...draft, purpose: event.currentTarget.value })}
                >
                  <option value="">全部用途</option>
                  {testingTaskPurposes.map((key) => (
                    <option key={key} value={key}>
                      {testingPurpose[key]}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="submit"
                className="ui-button"
                disabled={invalid}
                title={invalid ? '需求和文档编号须为正整数' : undefined}
              >
                应用筛选
              </button>
              <button
                type="button"
                className="ui-button"
                onClick={() => {
                  setDraft(filterText({}));
                  navigate(new URLSearchParams());
                }}
              >
                清除筛选
              </button>
            </form>
            <ReadState
              loading={tasks.loading}
              error={tasks.error}
              stale={tasks.data !== null}
              retry={tasks.reload}
            />
            {tasks.data && (
              <>
                {tasks.data.data.items.length === 0 && !tasks.loading && !tasks.error && (
                  <EmptyState
                    icon="outline"
                    message={
                      selected.page > 1
                        ? '此页没有测试任务'
                        : Object.keys(selected.filters).length > 0
                          ? '没有符合当前筛选的测试任务'
                          : '当前没有测试任务'
                    }
                  />
                )}
                <TaskRows items={tasks.data.data.items} open={open} />
                <Pager
                  meta={meta(tasks.data.meta.pagination)}
                  page={selected.page}
                  busy={tasks.loading}
                  select={pageTo}
                />
              </>
            )}
          </>
        )}
      </section>
      {drawer && (
        <CreateTestingTaskDrawer
          api={api}
          access={access}
          received={received}
          close={() => setDrawer(false)}
          created={onCreated}
        />
      )}
    </main>
  );
}
