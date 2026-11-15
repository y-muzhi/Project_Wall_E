import { useCallback, useEffect, useState } from 'react';
import type { TestingTaskOperation } from '../api/testing-task-operations.ts';
import type { TestingTaskView } from '../api/testing-tasks.ts';
import type { WalleApi } from '../api/walle.ts';
import { PageHeader } from '../application/header.tsx';
import { useSettingsVisibility } from '../code-tasks/settings/read.ts';
import { EmptyState } from '../shared/empty-state.tsx';
import { localTime } from '../shared/time.ts';
import { meta, Pager, ReadState, useTestingRead } from './plans/read.tsx';
import { TaskReport } from './report/task-report.tsx';
import { TaskResults } from './report/task-results.tsx';
import { TaskControls, textId } from './task-controls.tsx';
import { testingPhase, testingPurpose, testingStatus } from './task-labels.ts';
import { OriginalTaskRequests, useTestingRecovery } from './task-recovery.tsx';
import { TaskUsage } from './task-usage.tsx';

const tabs = {
  overview: '概览',
  plan: '计划',
  results: '执行结果',
  report: '报告',
  usage: '用量',
} as const;
type Tab = keyof typeof tabs;
const operationLabels = {
  TERMINATE: '终止',
  ATTACH_ASSETS: '绑定测试资产',
  INCREASE_TEST_BUDGET: '提高模型预算',
  RUN_TEST: '独立测试',
  DRAFT_PLAN: 'AI 起草计划',
  RESUME: '继续测试',
  RECONCILE: '核对原操作',
} as const;
const stepLabels: Readonly<Record<string, string>> = {
  FENCE: '关闭新的派发',
  STOP_OWN_ACTIVITIES: '停止本任务活动',
  VERIFY_STOP: '核对停止事实',
  CLEANUP: '核对资源清理',
  SAVE_TERMINATED: '保存终止结果',
  VALIDATE: '校验固定输入',
  SAVE_FACT: '保存原事实',
  FIX_INPUT: '固定测试输入',
  MATERIALIZE: '准备只读测试副本',
  PREPARE: '准备执行环境',
  EXECUTE: '执行受控用例',
  STOP: '核对停止',
  VERIFY_INPUT: '复核输入完整性',
  SAVE_REPORT: '保存原报告',
  BUILD_CONTEXT: '固定设计和材料',
  RESERVE: '预留模型费用',
  CALL_MODEL: '读取原模型结果',
  SAVE_DRAFT: '保存草稿',
  RECONCILE: '核对原步骤',
  CHECK_CONDITIONS: '复核继续条件',
  CONTINUE_OR_OBSERVE: '继续原操作',
  QUERY: '读取原操作',
  COMPARE: '核对原事实',
  RECORD: '保存核对记录',
};
const operationStates = {
  PENDING: '待处理',
  RUNNING: '处理中',
  UNKNOWN: '待核对',
  SUCCEEDED: '已完成',
  FAILED: '未完成',
  CANCELLED: '已取消',
} as const;
type Query = {
  tab: Tab;
  operation: number | null;
  verification: number | null;
  report: number | null;
};
function workspaceQuery(search: string): Query | null {
  const query = new URLSearchParams(search);
  const known = new Set(['tab', 'operation_id', 'verification_id', 'report_id']);
  if ([...query].some(([key]) => !known.has(key) || query.getAll(key).length !== 1)) return null;
  const tab = query.get('tab') ?? 'overview';
  if (!Object.hasOwn(tabs, tab)) return null;
  const links = ['operation_id', 'verification_id', 'report_id'].map((field) => {
    const value = query.get(field);
    return value === null ? null : (textId(value) ?? 0);
  });
  if (links.some((item) => item === 0)) return null;
  return { tab: tab as Tab, operation: links[0]!, verification: links[1]!, report: links[2]! };
}

function OperationDetails({ operation }: Readonly<{ operation: TestingTaskOperation }>) {
  return (
    <>
      <h4>
        {operationLabels[operation.operation_type]} #{operation.id} ·{' '}
        {operationStates[operation.status]}
      </h4>
      {operation.failure_code && (
        <p role="status">
          {operation.failure_code === 'EXECUTION_NOT_STOPPED'
            ? '尚无法证实本任务活动已停止'
            : operation.failure_code === 'EVIDENCE_INCOMPLETE'
              ? '原执行证据不完整'
              : '原操作未能完成'}
        </p>
      )}
      {operation.operation_type === 'RECONCILE' && operation.status === 'SUCCEEDED' && (
        <p role="status">已记录原操作的观察结果。</p>
      )}
      <ol>
        {operation.steps.map((step) => (
          <li key={step.step_no}>
            {stepLabels[step.step_type] ?? step.step_type} · {operationStates[step.status]}
          </li>
        ))}
      </ol>
    </>
  );
}

function TaskOperations({
  api,
  task,
  original,
  select,
  verified,
}: Readonly<{
  api: WalleApi;
  task: TestingTaskView;
  original: number | null;
  select(id: number): void;
  verified(id: number): void;
}>) {
  const visible = useSettingsVisibility();
  const [page, setPage] = useState(1);
  const [history, setHistory] = useState(false);
  const read = useCallback(
    (signal: AbortSignal) => api.testingTaskOperation(task.id, original!, signal),
    [api, task.id, original],
  );
  const list = useCallback(
    (signal: AbortSignal) => api.testingTaskOperations(task.id, page, signal),
    [api, task.id, page],
  );
  const detail = useTestingRead(
    'testing-operation:' + task.id + ':' + original,
    original === null ? null : read,
  );
  const rows = useTestingRead('testing-operations:' + task.id + ':' + page, history ? list : null);
  const displayed = detail.data?.data ?? null;
  useEffect(() => {
    if (displayed !== null && displayed.id === original) verified(displayed.id);
  }, [displayed, original, verified]);
  useEffect(() => {
    if (
      !visible ||
      detail.loading ||
      detail.error !== null ||
      (displayed?.status !== 'PENDING' && displayed?.status !== 'RUNNING')
    )
      return;
    const timer = window.setTimeout(detail.reload, 1100);
    return () => window.clearTimeout(timer);
  }, [visible, displayed, detail.loading, detail.error, detail.reload]);
  useEffect(() => {
    detail.reload();
    rows.reload();
  }, [task.state_version, detail.reload, rows.reload]);
  return (
    <section className="testing-editor-panel" aria-label="独立任务原操作">
      <h3>原操作</h3>
      {original !== null && (
        <>
          <ReadState
            loading={detail.loading}
            error={detail.error}
            stale={detail.data !== null}
            retry={detail.reload}
          />
          {detail.data && <OperationDetails operation={detail.data.data} />}
        </>
      )}
      <details onToggle={(event) => setHistory(event.currentTarget.open)}>
        <summary>查看操作记录</summary>
        <ReadState
          loading={rows.loading}
          error={rows.error}
          stale={rows.data !== null}
          retry={rows.reload}
        />
        {rows.data && (
          <>
            {!rows.loading && !rows.error && rows.data.data.items.length === 0 && (
              <EmptyState
                icon="outline"
                message={page === 1 ? '此任务尚无操作记录' : '此页没有操作记录'}
                compact
              />
            )}
            <ol className="code-settings-version-items">
              {rows.data.data.items.map((row) => (
                <li key={row.id}>
                  <button
                    type="button"
                    className="ui-button"
                    aria-pressed={original === row.id}
                    onClick={() => select(row.id)}
                  >
                    {operationLabels[row.operation_type]} #{row.id} · {operationStates[row.status]}
                  </button>
                </li>
              ))}
            </ol>
            <Pager
              meta={meta(rows.data.meta.pagination)}
              page={page}
              busy={rows.loading}
              select={setPage}
            />
          </>
        )}
      </details>
    </section>
  );
}

export function TestingTaskWorkspace({
  api,
  identity,
  query,
  back,
  select,
  plans,
}: Readonly<{
  api: WalleApi;
  identity: number;
  query: string;
  back(): void;
  select(value: URLSearchParams): void;
  plans(plan?: number | null, version?: number | null): void;
}>) {
  const selected = workspaceQuery(query);
  const [verifiedOperation, setVerifiedOperation] = useState<number | null>(null);
  const visible = useSettingsVisibility();
  const load = useCallback(
    (signal: AbortSignal) => api.testingTask(identity, signal),
    [api, identity],
  );
  const read = useTestingRead('testing-task:' + identity, selected === null ? null : load);
  const task = read.data?.data ?? null;
  const scope = '/api/v1/testing-tasks/' + identity + '/';
  const recovery = useTestingRecovery(
    api,
    (record) => record.path.startsWith(scope),
    (_record, result) => {
      if (result.original_receipt?.original_outcome?.success === true) read.reload();
    },
  );
  useEffect(() => {
    const previous = document.title;
    document.title = 'WALL-E · 独立测试任务';
    return () => {
      document.title = previous;
    };
  }, []);
  useEffect(() => {
    if (
      !visible ||
      task === null ||
      (task.status !== 'RUNNING' &&
        task.status !== 'PLANNING' &&
        (task.status !== 'STOPPING' || task.runtime.stop_status === 'UNKNOWN')) ||
      read.loading ||
      read.error !== null
    )
      return;
    const timer = window.setTimeout(() => {
      read.reload();
      void recovery.reader.refresh();
    }, 1100);
    return () => window.clearTimeout(timer);
  }, [visible, task, read.loading, read.error, read.reload, recovery.reader]);
  function navigate(tab: Tab, operation?: number) {
    const next = new URLSearchParams();
    if (tab !== 'overview') next.set('tab', tab);
    if (operation !== undefined) next.set('operation_id', String(operation));
    select(next);
  }
  const original =
    selected?.operation ?? task?.termination_operation_id ?? task?.active_operation_id ?? null;
  const ownedOperation =
    original !== null &&
    (original === task?.termination_operation_id ||
      original === task?.active_operation_id ||
      original === verifiedOperation)
      ? original
      : null;
  const mismatched =
    task !== null &&
    selected !== null &&
    ((selected.report !== null && selected.report !== task.report_id) ||
      (selected.verification !== null && selected.verification !== task.current_verification_id));
  return (
    <main className="code-settings testing-plans">
      <PageHeader>
        <header className="code-settings-heading">
          <h1>独立测试任务 #{identity}</h1>
        </header>
      </PageHeader>
      <div className="code-settings-form-actions">
        <button type="button" className="ui-button" onClick={back}>
          返回测试任务列表
        </button>
        <button
          type="button"
          className="ui-button"
          disabled={selected === null || read.loading}
          title={read.loading ? '正在读取任务' : undefined}
          onClick={() => {
            read.reload();
            void recovery.reader.refresh();
          }}
        >
          核对任务状态
        </button>
      </div>
      <OriginalTaskRequests access={recovery} />
      {selected === null ? (
        <p role="alert" className="inline-error">
          测试任务定位参数无效。
        </p>
      ) : (
        <ReadState
          loading={read.loading}
          error={read.error}
          stale={task !== null}
          retry={read.reload}
        />
      )}
      {mismatched && (
        <p role="alert" className="inline-error">
          所选报告或验证不属于此任务。
        </p>
      )}
      {task && selected && !mismatched && (
        <>
          <section className="testing-editor-panel" aria-label="固定任务来源">
            <h2>{testingStatus[task.status]}</h2>
            <p>
              {task.target_kind === 'CANDIDATE'
                ? 'Coding 候选 #' + task.candidate_id
                : '仓库快照 #' + task.snapshot_id}
              {' · '}
              {testingPurpose[task.purpose]}
              {' · '}
              {testingPhase[task.phase]}
            </p>
            <p>
              需求 #{task.requirement_id} · 主文档 #{task.document_id} · 固定版本 #
              {task.design_revision_id}
            </p>
            <p>创建时间 {localTime(task.created_at)}</p>
          </section>
          <nav className="code-settings-form-actions" aria-label="任务分区">
            {(Object.keys(tabs) as Tab[]).map((tab) => (
              <button
                type="button"
                className="ui-button"
                key={tab}
                aria-current={selected.tab === tab ? 'page' : undefined}
                onClick={() => navigate(tab, selected.operation ?? undefined)}
              >
                {tabs[tab]}
              </button>
            ))}
          </nav>
          {selected.tab === 'overview' && (
            <>
              <TaskControls
                api={api}
                task={task}
                access={recovery}
                stale={read.error !== null || read.loading}
                originalOperation={ownedOperation}
                updated={(_action, operation) => {
                  if (operation !== null) navigate('overview', operation);
                  read.reload();
                  void recovery.reader.refresh();
                }}
              />
              <TaskOperations
                key={identity}
                api={api}
                task={task}
                original={original}
                select={(id) => navigate('overview', id)}
                verified={setVerifiedOperation}
              />
            </>
          )}
          {selected.tab === 'plan' && (
            <section className="testing-editor-panel" aria-label="任务测试计划">
              {task.plan_version_id === null ? (
                <EmptyState icon="outline" message="此任务尚未绑定测试计划和测试包" compact />
              ) : (
                <p>
                  计划版本 #{task.plan_version_id} · 测试包 #{task.test_pack_version_id}
                </p>
              )}
              {task.draft_plan_result !== null && (
                <p>原起草结果 · 计划版本 #{task.draft_plan_result.plan_version_id}</p>
              )}
              <button
                className="ui-button"
                type="button"
                onClick={() =>
                  plans(task.draft_plan_result?.plan_id, task.draft_plan_result?.plan_version_id)
                }
              >
                打开测试计划管理
              </button>
            </section>
          )}
          {selected.tab === 'results' && <TaskResults key={identity} api={api} task={task} />}
          {selected.tab === 'report' && (
            <TaskReport
              key={identity}
              api={api}
              task={task}
              openResults={(verification) => {
                select(
                  new URLSearchParams({ tab: 'results', verification_id: String(verification) }),
                );
              }}
            />
          )}
          {selected.tab === 'usage' && <TaskUsage key={identity} api={api} task={task} />}
        </>
      )}
    </main>
  );
}
