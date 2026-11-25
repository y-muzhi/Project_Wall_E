import { useCallback, useEffect, useRef, useState } from 'react';
import type { DocumentHandoffLink } from '../application/router.ts';
import type { WalleApi } from '../api/walle.ts';
import type { CodeTaskView } from '../api/code-task-creation.ts';
import { TaskStartControl } from './start-control.tsx';
import { TaskStopControl } from './stop-control.tsx';
import { TaskConfigurationControl } from './configuration-control.tsx';
import { LegacyTaskBudgetRecovery } from './budget-control.tsx';
import { TaskResumeControl } from './resume-control.tsx';
import { CodeTaskUsage } from './usage.tsx';
import { CandidateHistory } from './candidate-history.tsx';
import { VerificationDetail } from './verification-history.tsx';
import { TaskChecks } from './checks.tsx';
import { TestingPublication } from './testing-publication.tsx';
import { HistoricalCodingReport } from './testing-report-link.tsx';
import { TaskDefects } from './task-defects.tsx';
import { DeliveryWorkspace, HistoricalDeliveryPlan } from './delivery-workspace.tsx';
import { TaskRecords } from './task-records.tsx';
import { RoleReconciliation } from './role-reconciliation.tsx';
import { TaskOperationHistory } from './operation-history.tsx';
import { TaskNativeIssues } from './native-issues.tsx';
import { EmptyState } from '../shared/empty-state.tsx';
import { Pagination } from '../shared/pagination.tsx';
import { localTime } from '../shared/time.ts';
import { useSettingsRead, useSettingsVisibility } from './settings/read.ts';
import { TASK_PHASE, TASK_STATUS } from './list-model.ts';
import { workspaceTabs } from './workspace-route.ts';
import type { WorkspaceRoute, WorkspaceTab } from './workspace-route.ts';
import './task-pages.css';

const waitingLabel = {
  BUDGET: '模型预算或调用额度需要处理。',
  MODEL_RESULT: '原模型调用结果待核对，费用预留仍保留。',
  OPERATION_RESULT: '原操作结果待核对。',
  CONFIGURATION: '配置应用结果待核对。',
  DELIVERY_RESULT: '原交付结果或运行资源回收待核对。',
  QUESTION: '原生问题需要处理或核对。',
  PERMISSION: '原权限请求需要处理或核对。',
} as const;

type Props = Readonly<{
  api: WalleApi;
  taskId: number;
  route: WorkspaceRoute | null;
  restoreScroll: number | null;
  navigate(route: WorkspaceRoute): void;
  pinFileScope(route: WorkspaceRoute, identity: number): void;
  back(requirementId: number, documentId: number): void;
  openDocument(requirementId: number, documentId: number): void;
  openHandoff(requirementId: number, link: DocumentHandoffLink): void;
}>;

function taskPollDelay(result: { data: CodeTaskView }) {
  const task = result.data;
  if (task.status === 'TERMINATED' || task.status === 'COMPLETED')
    return task.budget.unresolved_call_count > 0 ? 5000 : null;
  if (task.active_operations.length > 0 || task.status === 'RUNNING' || task.status === 'STOPPING')
    return 1000;
  return 5000;
}

const runtimeEnvironment: Record<CodeTaskView['runtime']['environment_status'], string> = {
  NOT_PREPARED: '执行环境尚未准备',
  PREPARING: '正在准备执行环境',
  VERIFIED: '执行环境已核实',
  UNKNOWN: '执行环境待核对',
};

const runtimeActivity: Record<CodeTaskView['runtime']['activity_status'], string> = {
  NOT_STARTED: '执行活动尚未开始',
  UNKNOWN: '活动状态待核对',
  QUIESCENT: '当前阶段已静止',
};

const runtimeStop: Record<Exclude<CodeTaskView['runtime']['stop_status'], 'NONE'>, string> = {
  REQUESTED: '停止请求已保存',
  ABORTING: '正在停止会话',
  TERMINATING: '正在结束相关进程',
  VERIFIED: '执行已停止',
  UNKNOWN: '停止结果待核对',
};

const runtimeCleanup: Record<
  Exclude<CodeTaskView['runtime']['cleanup_status'], 'NOT_STARTED'>,
  string
> = {
  CLEANING: '正在回收运行资源',
  VERIFIED: '运行资源已回收',
  UNKNOWN: '资源回收待核对',
};

function RuntimeFacts({ runtime }: Readonly<{ runtime: CodeTaskView['runtime'] }>) {
  return (
    <>
      <dt>执行环境</dt>
      <dd>{runtimeEnvironment[runtime.environment_status]}</dd>
      <dt>阶段活动</dt>
      <dd>{runtimeActivity[runtime.activity_status]}</dd>
      <dt>活动进程</dt>
      <dd>{runtime.active_process_count ?? '进程数量待核对'}</dd>
      {runtime.stop_status !== 'NONE' && (
        <>
          <dt>停止状态</dt>
          <dd>{runtimeStop[runtime.stop_status]}</dd>
        </>
      )}
      {runtime.cleanup_status !== 'NOT_STARTED' && (
        <>
          <dt>资源回收</dt>
          <dd>{runtimeCleanup[runtime.cleanup_status]}</dd>
        </>
      )}
      {runtime.observed_at !== null && (
        <>
          <dt>最近核对</dt>
          <dd>
            <time dateTime={runtime.observed_at}>{localTime(runtime.observed_at)}</time>
          </dd>
        </>
      )}
    </>
  );
}

export function CodeTaskWorkspace(props: Props) {
  const { api, taskId, route, restoreScroll, navigate, pinFileScope } = props;
  const visible = useSettingsVisibility();
  const workspace = useRef<HTMLElement | null>(null);
  const tab = route?.tab ?? null;
  const [refresh, setRefresh] = useState(0);
  const changed = useCallback(() => setRefresh((value) => value + 1), []);
  const load = useCallback(
    (signal: AbortSignal) => {
      void refresh;
      return api.codeTask(taskId, signal);
    },
    [api, taskId, refresh],
  );
  const result = useSettingsRead(
    load,
    visible && tab !== null,
    '暂时无法读取代码任务',
    taskPollDelay,
  );
  const task = result.value?.data;
  const waitingForCandidate =
    route?.tab === 'code' && route.filePath !== undefined && route.candidateId === undefined;
  const waitingForPlan =
    route?.tab === 'delivery' && route.filePath !== undefined && route.planId === undefined;
  const fileScope = waitingForCandidate
    ? task?.current_candidate_id
    : task?.current_refs.delivery_plan_id;
  const fileUnpinned = waitingForCandidate || waitingForPlan;
  useEffect(() => {
    if (
      route !== null &&
      fileUnpinned &&
      !result.loading &&
      result.error === null &&
      fileScope !== undefined &&
      fileScope !== null
    )
      pinFileScope(route, fileScope);
  }, [route, fileUnpinned, fileScope, result.loading, result.error, pinFileScope]);

  const loadedTask = task?.id;
  useEffect(() => {
    const region = workspace.current;
    const top = restoreScroll;
    if (top === null || loadedTask === undefined || region === null) return;

    const restore = () => {
      window.scrollTo(0, top);
      if (Math.abs(window.scrollY - top) <= 1) observer.disconnect();
    };

    const observer = new ResizeObserver(restore);
    observer.observe(region);
    restore();
    const timeout = window.setTimeout(() => observer.disconnect(), 2000);
    return () => {
      observer.disconnect();
      window.clearTimeout(timeout);
    };
  }, [loadedTask, restoreScroll, route]);

  function selectPage(page: number) {
    if (route !== null) navigate({ ...route, page });
  }

  function selectOperation(operationId: number | null) {
    navigate({
      tab: 'execution',
      page: route?.page ?? 1,
      ...(operationId === null ? {} : { operationId }),
    });
  }

  function selectCandidate(candidateId: number | null) {
    navigate(candidateId === null ? { tab: 'code' } : { tab: 'code', candidateId });
  }

  function selectCandidateFile(candidateId: number, filePath: string | null) {
    navigate({
      tab: 'code',
      candidateId,
      page: route?.page ?? 1,
      ...(filePath === null ? {} : { filePath }),
    });
  }

  function selectVerification(verificationId: number | null) {
    navigate(verificationId === null ? { tab: 'checks' } : { tab: 'checks', verificationId });
  }

  function selectPlan(planId: number | null) {
    navigate(planId === null ? { tab: 'delivery' } : { tab: 'delivery', planId });
  }

  function selectPlanFile(planId: number, filePath: string | null) {
    navigate({
      tab: 'delivery',
      planId,
      page: route?.page ?? 1,
      ...(filePath === null ? {} : { filePath }),
    });
  }

  function closeReport() {
    navigate({ tab: 'testing' });
  }

  return (
    <main
      ref={workspace}
      className="code-task-page code-task-workspace"
      aria-busy={tab !== null && result.loading}
    >
      <header className="code-task-heading">
        <h1>代码任务 #{taskId}</h1>
        {task && (
          <div className="code-task-toolbar">
            <button
              className="ui-button"
              type="button"
              onClick={() => props.openDocument(task.requirement_id, task.document_id)}
            >
              打开所属文档
            </button>
            <button
              className="ui-button"
              type="button"
              onClick={() => props.back(task.requirement_id, task.document_id)}
            >
              返回任务列表
            </button>
          </div>
        )}
      </header>
      {tab === null ? (
        <>
          <p role="alert">代码任务页面参数无效。</p>
          <button
            type="button"
            className="ui-button"
            onClick={() => navigate({ tab: 'execution' })}
          >
            返回任务执行
          </button>
        </>
      ) : (
        <>
          {result.loading && <p role="status">正在读取代码任务…</p>}
          {result.error && (
            <p className="inline-error" role="alert">
              {task ? '当前状态尚未核实。' : result.error}{' '}
              <button
                className="ui-button"
                type="button"
                onClick={() => setRefresh((value) => value + 1)}
              >
                重试读取
              </button>
            </p>
          )}
          {task && (
            <>
              <dl className="code-task-facts">
                <dt>状态</dt>
                <dd>{TASK_STATUS[task.status]}</dd>
                <dt>阶段</dt>
                <dd>{TASK_PHASE[task.phase]}</dd>
                <dt>固定设计版本</dt>
                <dd>#{task.design_revision_id}</dd>
                <dt>目标分支</dt>
                <dd>{task.target_branch}</dd>
                {tab === 'execution' && <RuntimeFacts runtime={task.runtime} />}
              </dl>
              {task.current_basis_difference.length > 0 && (
                <section aria-label="文档版本差异">
                  <h2>文档版本差异</h2>
                  <ul>
                    {task.current_basis_difference.map((item) => (
                      <li key={item.document_id}>
                        文档 #{item.document_id}，固定版本 #{item.fixed_revision_id}，当前版本 #
                        {item.current_revision_id}
                      </li>
                    ))}
                  </ul>
                </section>
              )}
              <TaskConfigurationControl
                key={task.id + ':configuration'}
                api={api}
                task={task}
                visible={visible}
                ready={!result.loading && !result.error}
                changed={changed}
              />
              <LegacyTaskBudgetRecovery
                key={task.id + ':legacy-budget'}
                api={api}
                taskId={task.id}
                changed={changed}
              />
              <TaskResumeControl
                key={task.id + ':resume'}
                api={api}
                task={task}
                visible={visible}
                ready={!result.loading && !result.error}
                changed={changed}
              />
              <TaskStopControl
                api={api}
                task={task}
                visible={visible}
                ready={!result.loading && !result.error}
                changed={changed}
              />
              <nav className="code-task-toolbar" aria-label="任务工作区">
                {(Object.keys(workspaceTabs) as WorkspaceTab[]).map((key) => (
                  <button
                    key={key}
                    className="ui-button"
                    type="button"
                    aria-current={tab === key ? 'page' : undefined}
                    onClick={() => navigate({ tab: key })}
                  >
                    {workspaceTabs[key]}
                  </button>
                ))}
              </nav>
              {fileUnpinned ? (
                <section aria-label="固定文件来源">
                  {result.error === null &&
                    (result.loading || fileScope !== null ? (
                      <p role="status">正在核对文件所属版本…</p>
                    ) : (
                      <EmptyState
                        icon="outline"
                        message={
                          waitingForCandidate ? '此任务尚无当前固定候选' : '此任务尚无当前交付预览'
                        }
                      />
                    ))}
                  <button className="ui-button" type="button" onClick={() => navigate({ tab })}>
                    关闭文件选择
                  </button>
                </section>
              ) : (
                <TaskTab
                  key={task.id + ':' + tab}
                  api={api}
                  task={task}
                  tab={tab}
                  operationId={route?.operationId ?? null}
                  candidateId={route?.candidateId ?? null}
                  verificationId={route?.verificationId ?? null}
                  planId={route?.planId ?? null}
                  reportId={route?.reportId ?? null}
                  filePath={route?.filePath ?? null}
                  page={route?.page ?? 1}
                  selectPage={selectPage}
                  selectOperation={selectOperation}
                  selectCandidate={selectCandidate}
                  selectCandidateFile={selectCandidateFile}
                  selectVerification={selectVerification}
                  selectPlan={selectPlan}
                  selectPlanFile={selectPlanFile}
                  closeReport={closeReport}
                  visible={visible && !result.error}
                  ready={!result.loading && !result.error}
                  refresh={changed}
                  openHandoff={props.openHandoff}
                />
              )}
            </>
          )}
        </>
      )}
    </main>
  );
}

function TaskTab({
  api,
  task,
  tab,
  operationId,
  candidateId,
  verificationId,
  planId,
  reportId,
  filePath,
  page,
  selectPage,
  selectOperation,
  selectCandidate,
  selectCandidateFile,
  selectVerification,
  selectPlan,
  selectPlanFile,
  closeReport,
  visible,
  ready,
  refresh,
  openHandoff,
}: Readonly<{
  api: WalleApi;
  task: CodeTaskView;
  tab: WorkspaceTab;
  operationId: number | null;
  candidateId: number | null;
  verificationId: number | null;
  planId: number | null;
  reportId: number | null;
  filePath: string | null;
  page: number;
  selectPage(page: number): void;
  selectOperation(id: number | null): void;
  selectCandidate(id: number | null): void;
  selectCandidateFile(id: number, path: string | null): void;
  selectVerification(id: number | null): void;
  selectPlan(id: number | null): void;
  selectPlanFile(id: number, path: string | null): void;
  closeReport(): void;
  visible: boolean;
  ready: boolean;
  refresh(): void;
  openHandoff(requirementId: number, link: DocumentHandoffLink): void;
}>) {
  const recordLink = useRef<HTMLAnchorElement | null>(null);

  function openRecordOperation(id: number, source: HTMLAnchorElement) {
    recordLink.current = source;
    selectOperation(id);
  }

  function selectFromHistory(id: number | null) {
    if (id !== null) recordLink.current = null;
    selectOperation(id);
  }

  function restoreRecordFocus() {
    const source = recordLink.current;
    recordLink.current = null;
    if (!source?.isConnected) return false;
    source.focus();
    return true;
  }

  if (tab === 'code')
    return (
      <>
        <CandidateHistory
          api={api}
          taskId={task.id}
          currentId={task.current_candidate_id}
          selection={candidateId}
          select={selectCandidate}
          filePath={filePath}
          selectFile={selectCandidateFile}
          page={page}
          selectPage={selectPage}
          visible={visible}
        />
        <BaselineFiles api={api} id={task.base_snapshot_id} visible={visible} />
      </>
    );
  if (tab === 'execution') {
    const start = task.active_operations.find((operation) => operation.operation_type === 'START');
    const handoff = task.active_operations.find(
      (operation) => operation.operation_type === 'HANDOFF_ROLE',
    );
    const unavailable = task.available_actions.find(
      (action) =>
        action.action === 'START' &&
        action.related_id !== null &&
        (action.reason_code === 'CONTENT_NOT_READY' || action.reason_code === 'CONFIG_NOT_READY'),
    );
    const startId = start?.id ?? unavailable?.related_id;
    const showProgress = startId !== undefined && startId !== null && task.status === 'PENDING';
    const status = unavailable
      ? unavailable.reason_code === 'CONFIG_NOT_READY'
        ? '执行环境尚未就绪'
        : '固定代码、设计或材料暂不可用'
      : start?.status === 'UNKNOWN'
        ? task.workspace_id === null
          ? '工作区准备结果待核对'
          : '任务启动结果待核对'
        : task.workspace_id !== null
          ? '工作区已核验，等待后续准备'
          : '正在准备工作区';
    return (
      <section className="code-task-result" aria-label="任务执行">
        <TaskStartControl api={api} task={task} visible={visible} ready={ready} changed={refresh} />
        {showProgress ? (
          <p role="status">
            {status} · 操作 #{startId}
          </p>
        ) : task.status === 'WAITING' ? (
          <ul aria-label="当前等待事项">
            {task.waiting_items.map((item) => (
              <li key={item.id}>
                {waitingLabel[item.kind]}
                {item.source_kind === 'LLM_USE' && ' 调用 #' + item.source_id}
              </li>
            ))}
          </ul>
        ) : task.status === 'RUNNING' ? (
          <p role="status">首条执行消息已接收，任务已进入{TASK_PHASE[task.phase]}阶段。</p>
        ) : handoff ? (
          <p role="status">正在交接下一角色 · 操作 #{handoff.id}</p>
        ) : task.status === 'VERIFYING' ? (
          <p role="status">当前代码已固定，等待开发自检结果。</p>
        ) : task.status === 'AWAITING_TESTING' ? (
          <p role="status">当前联调候选已发布供独立测试。</p>
        ) : (
          <EmptyState
            icon="outline"
            message={
              task.status === 'TERMINATED'
                ? task.workspace_id === null
                  ? '任务已终止，未开始执行'
                  : '任务已终止，原执行资源已回收'
                : task.status === 'STOPPING'
                  ? '正在核对停止范围'
                  : '任务已创建，尚未开始执行'
            }
          />
        )}
        <div className="code-task-execution-columns">
          <div className="code-task-execution-issues">
            <TaskNativeIssues
              api={api}
              task={task}
              visible={visible}
              ready={ready}
              changed={refresh}
              openHandoff={openHandoff}
              live={task.status === 'RUNNING' || task.status === 'WAITING'}
            />
            <RoleReconciliation api={api} task={task} ready={ready} changed={refresh} />
          </div>
          <div className="code-task-execution-record-column">
            <TaskRecords
              api={api}
              task={task.id}
              currentSession={task.active_session_id}
              ready={ready && visible}
              live={task.status !== 'COMPLETED' && task.status !== 'TERMINATED'}
              openOperation={openRecordOperation}
              page={page}
              selectPage={selectPage}
            />
          </div>
        </div>
        <TaskOperationHistory
          api={api}
          taskId={task.id}
          visible={visible}
          selected={operationId}
          selectOperation={selectFromHistory}
          restoreSourceFocus={restoreRecordFocus}
        />
      </section>
    );
  }
  if (tab === 'usage')
    return (
      <CodeTaskUsage api={api} task={task} visible={visible} page={page} selectPage={selectPage} />
    );
  if (tab === 'checks') {
    if (verificationId !== null) {
      return (
        <section className="code-task-result" aria-label="指定开发自检">
          <div className="code-task-toolbar">
            <button type="button" className="ui-button" onClick={() => selectVerification(null)}>
              返回当前开发自检
            </button>
          </div>
          <VerificationDetail
            key={verificationId}
            api={api}
            taskId={task.id}
            candidateId={null}
            verificationId={verificationId}
            visible={visible}
            readOnly
          />
        </section>
      );
    }
    return (
      <TaskChecks
        api={api}
        task={task}
        visible={visible}
        ready={ready}
        changed={refresh}
        selectVerification={selectVerification}
        page={page}
        selectPage={selectPage}
      />
    );
  }
  if (tab === 'testing' && reportId !== null) {
    return (
      <HistoricalCodingReport
        key={reportId}
        api={api}
        task={task.id}
        report={reportId}
        visible={visible}
        close={closeReport}
      />
    );
  }
  if (tab === 'testing')
    return (
      <>
        <TestingPublication api={api} task={task} ready={ready} changed={refresh} />
        <TaskDefects
          key={task.id + ':' + task.current_candidate_id}
          page={page}
          selectPage={selectPage}
          api={api}
          task={task}
          ready={ready}
          visible={visible}
          changed={refresh}
        />
      </>
    );
  if (planId !== null) {
    return (
      <HistoricalDeliveryPlan
        key={planId}
        api={api}
        task={task.id}
        plan={planId}
        filePath={filePath}
        selectFile={(path) => selectPlanFile(planId, path)}
        page={page}
        selectPage={selectPage}
        visible={visible}
        close={() => selectPlan(null)}
      />
    );
  }
  return (
    <DeliveryWorkspace
      key={task.id + ':' + task.current_refs.delivery_plan_id}
      api={api}
      task={task}
      ready={ready}
      visible={visible}
      changed={refresh}
      selectPlan={selectPlan}
      planPage={page}
      selectPlanPage={selectPage}
    />
  );
}

function BaselineFiles({
  api,
  id,
  visible,
}: Readonly<{ api: WalleApi; id: number; visible: boolean }>) {
  const [page, setPage] = useState(1);
  const [attempt, retry] = useState(0);
  const load = useCallback(
    (signal: AbortSignal) => {
      void attempt;
      return api.codeBaselineFiles(id, page, signal);
    },
    [api, id, page, attempt],
  );
  const result = useSettingsRead(load, visible, '暂时无法读取固定代码起点');
  const pagination = result.value?.meta.pagination;
  return (
    <section className="code-task-result" aria-label="固定代码起点" aria-busy={result.loading}>
      <h2>固定代码起点 #{id}</h2>
      {result.loading && <p role="status">正在读取固定文件…</p>}
      {result.error && (
        <p role="alert">
          {result.error}{' '}
          <button type="button" className="ui-button" onClick={() => retry((value) => value + 1)}>
            重试读取
          </button>
        </p>
      )}
      {!!result.value?.data.items.length && (
        <ul>
          {result.value.data.items.map((file) => (
            <li key={file.path}>
              <code>{file.path}</code> · {file.byte_count} 字节
            </li>
          ))}
        </ul>
      )}
      {!result.loading && !result.error && result.value?.data.items.length === 0 && (
        <EmptyState
          icon="outline"
          message={page > 1 ? '当前页超出固定文件范围' : '固定起点没有文件'}
        />
      )}
      {pagination && 'page' in pagination && (
        <Pagination value={pagination} loading={result.loading} change={setPage} />
      )}
    </section>
  );
}
