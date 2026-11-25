import { useCallback, useEffect, useRef, useState } from 'react';
import { positiveInteger } from '../api/client.ts';
import { testingAuthorizationPath } from '../api/testing-policy.ts';
import {
  testingTaskPurposes,
  testingTaskStatuses,
  testingTasksPath,
} from '../api/testing-tasks.ts';
import type { TestingTaskFilters } from '../api/testing-tasks.ts';
import type { WalleApi } from '../api/walle.ts';
import { SectionPageHeader } from '../application/header.tsx';
import { Pagination } from '../shared/pagination.tsx';
import { RecordList } from '../shared/record-list.tsx';
import { SingleSelect } from '../shared/single-select.tsx';
import { localTime } from '../shared/time.ts';
import { CreateTestingTaskDrawer } from './create-task.tsx';
import type { CreationReceipt } from './create-task.tsx';
import { useTestingRead } from './plans/read.tsx';
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

const statusOptions = [
  { value: '', label: '全部状态' },
  ...testingTaskStatuses.map((value) => ({ value, label: testingStatus[value] })),
];
const purposeOptions = [
  { value: '', label: '全部用途' },
  ...testingTaskPurposes.map((value) => ({ value, label: testingPurpose[value] })),
];

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
  const filterParameters = new URLSearchParams(query);
  filterParameters.delete('page');
  const filterKey = selected === null ? null : filterParameters.toString();
  const searchField = useRef<HTMLInputElement>(null);
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
  const tasks = useTestingRead('testing-list:' + query, selected === null ? null : load, true);
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
    setDraft(filterText(parseList(filterKey ?? '')?.filters ?? {}));
  }, [filterKey]);
  useEffect(() => {
    const old = document.title;
    document.title = 'WALL-E · 独立测试任务';
    return () => {
      document.title = old;
    };
  }, []);
  const invalidRequirement = draft.requirement_id !== '' && textId(draft.requirement_id) === null;
  const invalidDocument = draft.document_id !== '' && textId(draft.document_id) === null;
  const invalid = invalidRequirement || invalidDocument;
  const clearable =
    Object.values(draft).some((value) => value !== '') ||
    (selected !== null && Object.keys(selected.filters).length > 0);
  const pagination = tasks.data?.meta.pagination;
  const outOfRange =
    pagination !== undefined && pagination.page > Math.max(1, pagination.total_pages);
  const filtered = selected !== null && Object.keys(selected.filters).length > 0;
  const items =
    tasks.data?.data.items.map((row) => ({
      id: row.id,
      title: (
        <>
          测试任务 #{row.id} <span className="record-status">{testingStatus[row.status]}</span>
        </>
      ),
      metadata: (
        <>
          <span>
            {testingPurpose[row.purpose]} · {testingPhase[row.phase]}
          </span>
          <span>
            {row.target_kind === 'SNAPSHOT'
              ? '仓库快照 #' + row.snapshot_id
              : 'Coding 候选 #' + row.candidate_id}
          </span>
          <span>
            需求 #{row.requirement_id} · 文档 #{row.document_id}
          </span>
          <span>{localTime(row.created_at)}</span>
          {row.report_id !== null && <span>原报告 #{row.report_id}</span>}
        </>
      ),
      selected: false,
      disabled: false,
      label: `打开测试任务 #${row.id}，${testingStatus[row.status]}`,
      open: () => open(row.id),
    })) ?? [];
  function filter() {
    if (invalid || selected === null) return;
    const next = new URLSearchParams();
    for (const [field, value] of Object.entries(draft)) if (value !== '') next.set(field, value);
    for (const field of ['candidate_id', 'snapshot_id'] as const) {
      const value = selected.filters[field];
      if (value !== undefined) next.set(field, String(value));
    }
    if (next.toString() !== new URLSearchParams(query).toString()) navigate(next);
  }
  function pageTo(page: number) {
    const next = new URLSearchParams(query);
    if (page === 1) next.delete('page');
    else next.set('page', String(page));
    navigate(next);
  }
  function clearFilters() {
    setDraft(filterText({}));
    if (query !== '') navigate(new URLSearchParams());
    searchField.current?.focus({ preventScroll: true });
  }
  function onCreated(task: number) {
    setDrawer(false);
    tasks.reload();
    open(task);
  }
  return (
    <main className="testing-page testing-task-list">
      <SectionPageHeader title="独立测试任务">
        <button className="ui-button" type="button" onClick={() => plans()}>
          测试计划与资源
        </button>
        <button className="ui-button" type="button" onClick={settings}>
          测试配置与恢复
        </button>
        <button className="ui-button primary" type="button" onClick={() => setDrawer(true)}>
          新建测试任务
        </button>
      </SectionPageHeader>
      <OriginalTaskRequests access={access} />
      {received?.kind === 'create' && !drawer && (
        <p role="status">
          已核实原创建{' '}
          <button className="ui-button" type="button" onClick={() => open(received.id)}>
            打开测试任务 #{received.id}
          </button>
        </p>
      )}
      {selected === null ? (
        <div className="testing-list-actions">
          <p role="alert" className="inline-error">
            测试任务筛选参数无效。
          </p>
          <button className="ui-button" type="button" onClick={clearFilters}>
            返回完整目录
          </button>
        </div>
      ) : (
        <>
          <form
            className="testing-task-filters"
            aria-label="测试任务筛选"
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              filter();
            }}
          >
            <div className="testing-filter-field">
              <label htmlFor="testing-filter-requirement">需求 ID</label>
              <input
                ref={searchField}
                id="testing-filter-requirement"
                className="ui-input"
                inputMode="numeric"
                autoComplete="off"
                aria-invalid={invalidRequirement}
                aria-describedby={
                  invalidRequirement ? 'testing-filter-requirement-error' : undefined
                }
                value={draft.requirement_id}
                onChange={(event) =>
                  setDraft({ ...draft, requirement_id: event.currentTarget.value })
                }
              />
              {invalidRequirement && (
                <span id="testing-filter-requirement-error" className="inline-error">
                  请输入正整数
                </span>
              )}
            </div>
            <div className="testing-filter-field">
              <label htmlFor="testing-filter-document">文档 ID</label>
              <input
                id="testing-filter-document"
                className="ui-input"
                inputMode="numeric"
                autoComplete="off"
                aria-invalid={invalidDocument}
                aria-describedby={invalidDocument ? 'testing-filter-document-error' : undefined}
                value={draft.document_id}
                onChange={(event) => setDraft({ ...draft, document_id: event.currentTarget.value })}
              />
              {invalidDocument && (
                <span id="testing-filter-document-error" className="inline-error">
                  请输入正整数
                </span>
              )}
            </div>
            <div className="testing-filter-field">
              <label htmlFor="testing-filter-status">状态</label>
              <SingleSelect
                id="testing-filter-status"
                label="状态"
                options={statusOptions}
                value={draft.status}
                change={(status) => setDraft({ ...draft, status })}
              />
            </div>
            <div className="testing-filter-field">
              <label htmlFor="testing-filter-purpose">用途</label>
              <SingleSelect
                id="testing-filter-purpose"
                label="用途"
                options={purposeOptions}
                value={draft.purpose}
                change={(purpose) => setDraft({ ...draft, purpose })}
              />
            </div>
            <div className="testing-list-actions">
              <button
                type="submit"
                className="ui-button testing-apply-filters"
                disabled={invalid}
                title={invalid ? '请修正筛选中的 ID' : undefined}
              >
                应用筛选
              </button>
              <button
                type="button"
                className="ui-button"
                disabled={!clearable}
                title={clearable ? undefined : '当前没有筛选条件'}
                onClick={clearFilters}
              >
                清除筛选
              </button>
            </div>
          </form>
          {(selected.filters.candidate_id !== undefined ||
            selected.filters.snapshot_id !== undefined) && (
            <p className="read-status testing-list-context">
              {selected.filters.candidate_id !== undefined && (
                <span>Coding 候选 #{selected.filters.candidate_id}</span>
              )}
              {selected.filters.snapshot_id !== undefined && (
                <span>仓库快照 #{selected.filters.snapshot_id}</span>
              )}
            </p>
          )}
          {(tasks.stale || tasks.error !== null) && items.length > 0 && (
            <p className="read-status testing-list-context">显示上次读取的记录</p>
          )}
          <RecordList
            title="任务目录"
            headingLevel={2}
            showCount={false}
            total={pagination?.total ?? null}
            loading={tasks.loading}
            error={tasks.error}
            retry={tasks.reload}
            retryDisabled={tasks.loading}
            items={items}
            empty={{
              icon: filtered && !outOfRange ? 'search' : 'outline',
              message: outOfRange
                ? '此页没有测试任务'
                : filtered
                  ? '没有符合当前筛选的测试任务'
                  : '当前没有测试任务',
            }}
          />
          {pagination && (!tasks.stale || tasks.loading) && (
            <Pagination
              value={pagination}
              loading={tasks.loading}
              showLoadingStatus={false}
              change={pageTo}
              compactSingle
            />
          )}
        </>
      )}
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
