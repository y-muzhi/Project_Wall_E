import { useCallback, useState } from 'react';
import type { CodeCandidateDiff } from '../api/code-task-candidates.ts';
import type { CodeTaskView } from '../api/code-task-creation.ts';
import type { DeliveryPlanView } from '../api/code-task-delivery.ts';
import { acceptPath, planPath } from '../api/code-task-delivery.ts';
import type { WalleApi } from '../api/walle.ts';
import { Confirmation } from '../shared/confirmation.tsx';
import { EmptyState } from '../shared/empty-state.tsx';
import { localTime } from '../shared/time.ts';
import { meta, Pager, ReadState, useTestingRead } from '../testing/plans/read.tsx';
import { CandidateFilePreview } from './candidate-file-preview.tsx';
import type { OperationReader } from './command-recovery.ts';
import { useCodeTaskCommand } from './handoff-command.ts';
import { RoleReconciliation } from './role-reconciliation.tsx';
import { useSettingsRead } from './settings/read.ts';
import { RecoveryActions } from './settings/recovery-actions.tsx';

const deliveryLabel = {
  PENDING: '待交付',
  PREPARING: '正在准备',
  WRITING: '正在核对 Git 写入',
  UNKNOWN: '结果待核对',
  SUCCEEDED: '已交付',
  BLOCKED: '交付受阻',
  CANCELLED: '已取消',
};
const windowLabel = {
  REQUIRED: '需确认本次合作窗口',
  ACTIVE: '本次合作窗口有效',
  EXPIRED: '合作窗口已过期',
  CLOSED: '合作窗口已结束',
  UNKNOWN: '合作窗口待核对',
};
const changes = { ADD: '新增', MODIFY: '修改', DELETE: '删除', MODE: '文件模式变更' };
type PreviewInput = {
  expected_state_version: number;
  candidate_id: number;
  test_report_id: number;
};
type AcceptanceInput = PreviewInput & {
  delivery_plan_id: number;
  expected_target_commit: string;
  repository_quiescent_confirmed: true;
  manual_risk_accepted: boolean;
};

function useDeliveryPlanRead(
  api: WalleApi,
  task: number,
  planId: number | null,
  page: number,
  visible: boolean,
) {
  const [attempt, setAttempt] = useState(0);
  const load = useCallback(
    (signal: AbortSignal) => {
      void attempt;
      if (planId === null) throw Error('No fixed delivery plan selected');
      return api.deliveryPlan(task, planId, page, signal);
    },
    [api, task, planId, page, attempt],
  );
  const read = useSettingsRead(load, visible && planId !== null, '暂时无法读取固定交付预览');
  const original = read.value?.data.id === planId ? read.value : null;
  const observedPage = meta(original?.meta.pagination);
  return {
    plan: original?.data,
    pagination: observedPage?.page === page ? observedPage : null,
    loading: planId !== null && read.loading,
    error: read.error,
    reload: () => setAttempt((value) => value + 1),
  };
}

function DeliveryPlanContent({
  api,
  task,
  plan,
  page,
  pagination,
  loading,
  failed,
  selectPage,
  filePath,
  selectFile,
  visible,
}: Readonly<{
  api: WalleApi;
  task: number;
  plan: DeliveryPlanView;
  page: number;
  pagination: ReturnType<typeof meta>;
  loading: boolean;
  failed: boolean;
  selectPage(page: number): void;
  filePath?: string | null;
  selectFile?(path: string | null): void;
  visible: boolean;
}>) {
  const [selectionHint, setSelectionHint] = useState<CodeCandidateDiff | null>(null);
  const selected = selectFile === undefined ? (selectionHint?.path ?? null) : (filePath ?? null);
  const rows = pagination === null ? null : plan.target_diff_items;

  function openFile(item: CodeCandidateDiff) {
    setSelectionHint(item);
    selectFile?.(item.path);
  }

  function closeFile() {
    setSelectionHint(null);
    selectFile?.(null);
  }

  return (
    <>
      <h3>交付预览 #{plan.id}</h3>
      <dl className="code-task-facts">
        <dt>目标分支</dt>
        <dd>{plan.target_branch}</dd>
        <dt>预期目标提交</dt>
        <dd>
          <code>{plan.expected_target_commit}</code>
        </dd>
        <dt>候选与报告</dt>
        <dd>
          候选 #{plan.candidate_id} · 报告 #{plan.test_report_id}
        </dd>
        <dt>目标观察时间</dt>
        <dd>{localTime(plan.target_observed_at)}</dd>
      </dl>
      <p>以下是固定目标完整代码树与候选结果的差异。若按此预览交付，目标独有文件将删除。</p>
      {!loading && !failed && rows?.length === 0 && (
        <EmptyState
          icon="outline"
          message={page === 1 ? '固定目标与候选没有文件差异' : '当前页没有差异条目'}
          compact
        />
      )}
      {!!rows?.length && (
        <ul>
          {rows.map((item) => (
            <li key={item.path}>
              <button
                type="button"
                className="ui-button"
                aria-pressed={selected === item.path}
                onClick={() => openFile(item)}
              >
                查看 {item.path}
              </button>
              {' · '}
              {changes[item.change]}
            </li>
          ))}
        </ul>
      )}
      {pagination && <Pager meta={pagination} page={page} busy={loading} select={selectPage} />}
      {selected !== null && (
        <CandidateFilePreview
          key={selected}
          api={api}
          taskId={task}
          candidateId={plan.candidate_id}
          planId={plan.id}
          filePath={selected}
          item={selectionHint?.path === selected ? selectionHint : undefined}
          visible={visible}
          close={closeFile}
        />
      )}
    </>
  );
}

export function HistoricalDeliveryPlan({
  api,
  task,
  plan,
  filePath,
  selectFile,
  page,
  selectPage,
  visible,
  close,
}: Readonly<{
  api: WalleApi;
  task: number;
  plan: number;
  filePath: string | null;
  selectFile(path: string | null): void;
  page: number;
  selectPage(page: number): void;
  visible: boolean;
  close(): void;
}>) {
  const read = useDeliveryPlanRead(api, task, plan, page, visible);
  const value = read.plan;
  return (
    <section
      className="code-task-result code-delivery-workspace"
      aria-label={'指定交付预览 #' + plan}
    >
      <div className="code-task-toolbar">
        <button type="button" className="ui-button" onClick={close}>
          返回当前交付
        </button>
      </div>
      <ReadState
        loading={read.loading}
        error={read.error}
        stale={value !== undefined}
        retry={read.reload}
      />
      {value && (
        <>
          <p className="read-status">指定交付预览，仅供查看</p>
          <DeliveryPlanContent
            api={api}
            task={task}
            plan={value}
            page={page}
            pagination={read.pagination}
            loading={read.loading}
            failed={read.error !== null}
            selectPage={selectPage}
            filePath={filePath}
            selectFile={selectFile}
            visible={visible}
          />
        </>
      )}
    </section>
  );
}

export function DeliveryWorkspace({
  api,
  task,
  ready,
  visible,
  changed,
  selectPlan,
  planPage,
  selectPlanPage,
}: Readonly<{
  api: WalleApi;
  task: CodeTaskView;
  ready: boolean;
  visible: boolean;
  changed(): void;
  selectPlan(id: number): void;
  planPage: number;
  selectPlanPage(page: number): void;
}>) {
  const planId = task.current_refs.delivery_plan_id;
  const reportId = task.current_refs.test_report_id;
  const candidate = task.current_candidate_id;
  const currentDelivery = task.current_refs.delivery_id;
  const [localHistoryPage, setLocalHistoryPage] = useState(1);
  const historyPage = planId === null ? planPage : localHistoryPage;
  const selectHistoryPage = planId === null ? selectPlanPage : setLocalHistoryPage;
  const [selected, setSelected] = useState<number | null>(null);
  const [cooperation, setCooperation] = useState(false);
  const [manual, setManual] = useState(false);
  const [previewIntent, setPreviewIntent] = useState<PreviewInput | null>(null);
  const [acceptance, setAcceptance] = useState<AcceptanceInput | null>(null);
  const planRead = useDeliveryPlanRead(api, task.id, planId, planPage, visible);
  const plan = planRead.plan;
  const loadReport = useCallback(
    (signal: AbortSignal) => api.testingReport(reportId!, signal),
    [api, reportId],
  );
  const reportRead = useTestingRead(
    'delivery-report:' + task.id + ':' + reportId,
    reportId === null ? null : loadReport,
  );
  const report = reportRead.data?.data;
  const loadHistory = useCallback(
    (signal: AbortSignal) => api.deliveries(task.id, historyPage, signal),
    [api, task.id, historyPage],
  );
  const history = useTestingRead('delivery-history:' + task.id + ':' + historyPage, loadHistory);
  const identity = selected ?? currentDelivery;
  const loadDetail = useCallback(
    (signal: AbortSignal) => api.delivery(task.id, identity!, signal),
    [api, task.id, identity],
  );
  const detail = useTestingRead(
    'delivery-detail:' + task.id + ':' + identity,
    identity === null ? null : loadDetail,
  );
  const delivery = detail.data?.data;
  const readOperation = useCallback<OperationReader>(
    async (original, association, signal) => {
      if (association.task_id !== task.id || association.testing_task_id !== null)
        throw Error('原交付操作不属于当前任务');
      const { data } = await api.codeTaskOperation(task.id, association.operation_id, signal);
      const expected =
        original.decoder_kind === 'APP-CODE-CMD-C62' ? 'PREPARE_DELIVERY' : 'DELIVER';
      if (data.operation_type !== expected) throw Error('原交付操作类型不一致');
      return {
        task_id: data.task_id,
        testing_task_id: null,
        operation_id: data.id,
        status: data.status,
      };
    },
    [api, task.id],
  );
  const preview = useCodeTaskCommand(
    api,
    planPath(task.id),
    () => undefined,
    changed,
    '交付预览',
    '交付预览请求已提交。',
    readOperation,
  );
  const accept = useCodeTaskCommand(
    api,
    acceptPath(task.id),
    () => {
      setCooperation(false);
      setManual(false);
    },
    () => {
      history.reload();
      changed();
    },
    '接收',
    '代码已接收，等待实际交付。',
    readOperation,
  );
  const canPreview =
    ready &&
    preview.ready &&
    !preview.busy &&
    !preview.pending &&
    candidate !== null &&
    reportId !== null &&
    task.available_actions.some((row) => row.action === 'PREPARE_DELIVERY' && row.enabled);
  const reportReady =
    report?.id === reportId &&
    report?.provenance.candidate_id === candidate &&
    report?.provenance.source_code_task_id === task.id &&
    report.delivery_eligible &&
    !reportRead.loading &&
    reportRead.error === null;
  const risk = (report?.manual_coverage_ids.length ?? 0) > 0;
  const canAccept =
    ready &&
    accept.ready &&
    !accept.busy &&
    !accept.pending &&
    plan !== undefined &&
    !planRead.loading &&
    planRead.pagination !== null &&
    planRead.error === null &&
    reportReady &&
    cooperation &&
    (!risk || manual) &&
    plan.id === planId &&
    plan.candidate_id === candidate &&
    plan.test_report_id === reportId &&
    task.available_actions.some((row) => row.action === 'ACCEPT' && row.enabled);
  const previewOpen =
    previewIntent !== null &&
    canPreview &&
    previewIntent.expected_state_version === task.state_version &&
    previewIntent.candidate_id === candidate &&
    previewIntent.test_report_id === reportId;
  const acceptOpen =
    acceptance !== null &&
    canAccept &&
    acceptance.expected_state_version === task.state_version &&
    acceptance.delivery_plan_id === planId &&
    acceptance.test_report_id === reportId &&
    acceptance.candidate_id === candidate &&
    acceptance.manual_risk_accepted === (risk && manual);
  function openPreview() {
    if (!canPreview || candidate === null || reportId === null) return;
    setPreviewIntent({
      candidate_id: candidate,
      test_report_id: reportId,
      expected_state_version: task.state_version,
    });
  }
  function openAcceptance() {
    if (!canAccept || candidate === null || reportId === null || !plan) return;
    setAcceptance({
      candidate_id: candidate,
      test_report_id: reportId,
      expected_state_version: task.state_version,
      delivery_plan_id: plan.id,
      expected_target_commit: plan.expected_target_commit,
      repository_quiescent_confirmed: true,
      manual_risk_accepted: risk && manual,
    });
  }
  const historyMeta = meta(history.data?.meta.pagination);
  const historyRows = history.data?.data.items ?? [];
  return (
    <section className="code-task-result code-delivery-workspace" aria-label="接收与交付">
      <h2>接收与交付</h2>
      <div className="code-task-toolbar">
        <button
          className="ui-button"
          type="button"
          disabled={!canPreview}
          title={!canPreview ? '请先核对已关联的报告、授权及原操作' : undefined}
          onClick={openPreview}
        >
          准备完整目标预览
        </button>
      </div>
      {reportId === null && (
        <EmptyState icon="outline" message="此任务尚未关联合格的独立测试报告" compact />
      )}
      <ReadState
        loading={planRead.loading}
        error={planRead.error}
        stale={plan !== undefined}
        retry={planRead.reload}
      />
      {plan && (
        <section aria-label="固定交付预览">
          <DeliveryPlanContent
            key={plan.id}
            api={api}
            task={task.id}
            plan={plan}
            page={planPage}
            pagination={planRead.pagination}
            loading={planRead.loading}
            failed={planRead.error !== null}
            selectPage={selectPlanPage}
            visible={visible}
          />
          <ReadState
            loading={reportRead.loading}
            error={reportRead.error}
            stale={report !== undefined}
            retry={reportRead.reload}
          />
          {report && report.manual_coverage_ids.length > 0 && (
            <>
              <h4>人工验证范围</h4>
              <ul>
                {report.manual_coverage_ids.map((id) => (
                  <li key={id}>{id}</li>
                ))}
              </ul>
              <label>
                <input
                  type="checkbox"
                  checked={manual}
                  disabled={!ready || !reportReady}
                  onChange={(event) => setManual(event.currentTarget.checked)}
                />
                已阅读并确认人工验证范围的风险
              </label>
            </>
          )}
          <div className="code-task-toolbar">
            <label>
              <input
                type="checkbox"
                checked={cooperation}
                disabled={!ready || !reportReady || currentDelivery !== null}
                onChange={(event) => setCooperation(event.currentTarget.checked)}
              />
              交付期间暂停此仓库的其他 Git 写操作
            </label>
            <button
              type="button"
              className="ui-button"
              disabled={!canAccept}
              title={!canAccept ? '请核对原预览和报告，并完成适用的确认' : undefined}
              onClick={openAcceptance}
            >
              接收此候选
            </button>
          </div>
        </section>
      )}
      {[preview, accept].map((command, index) => (
        <div key={index}>
          {command.notice && <p role="status">{command.notice}</p>}
          {command.error && (
            <p role="alert" className="inline-error">
              {command.error}
            </p>
          )}
          {command.pending && (
            <div className="code-task-toolbar">
              <button
                type="button"
                className="ui-button"
                disabled={command.busy}
                onClick={command.lookup}
              >
                {index === 0 ? '核对原预览请求' : '核对原接收请求'}
              </button>
              {command.pending.status === 'ACCEPTED' && (
                <button
                  type="button"
                  className="ui-button"
                  disabled={command.busy}
                  onClick={command.observe}
                >
                  读取原操作进度
                </button>
              )}
              <RecoveryActions
                record={command.pending}
                recovery={command.recovery}
                replayEnabled={false}
                settled={command.settled}
              />
            </div>
          )}
        </div>
      ))}
      {task.phase === 'DELIVERY' && (
        <RoleReconciliation
          api={api}
          task={task}
          ready={ready}
          changed={() => {
            history.reload();
            detail.reload();
            changed();
          }}
          delivery
        />
      )}
      <h3>交付记录</h3>
      <ReadState
        loading={history.loading}
        error={history.error}
        stale={history.data !== null}
        retry={history.reload}
      />
      {!history.loading && !history.error && historyRows.length === 0 && (
        <EmptyState
          icon="outline"
          message={historyPage === 1 ? '此任务尚无交付记录' : '当前页没有交付记录'}
          compact
        />
      )}
      {historyRows.length > 0 && (
        <ul>
          {historyRows.map((item) => (
            <li key={item.id}>
              <button type="button" className="ui-button" onClick={() => setSelected(item.id)}>
                查看交付 #{item.id}
              </button>
              {' · '}
              {deliveryLabel[item.status]}
            </li>
          ))}
        </ul>
      )}
      {historyMeta && (
        <Pager
          meta={historyMeta}
          page={historyPage}
          busy={history.loading}
          select={selectHistoryPage}
        />
      )}
      <ReadState
        loading={detail.loading}
        error={detail.error}
        stale={delivery !== undefined}
        retry={detail.reload}
      />
      {delivery && (
        <dl className="code-task-facts">
          <dt>交付 #{delivery.id}</dt>
          <dd>{deliveryLabel[delivery.status]}</dd>
          <dt>接收记录</dt>
          <dd>#{delivery.acceptance_id}</dd>
          <dt>交付预览</dt>
          <dd>
            <button
              type="button"
              className="ui-button"
              onClick={() => selectPlan(delivery.delivery_plan_id)}
            >
              查看原交付预览 #{delivery.delivery_plan_id}
            </button>
          </dd>
          <dt>本次窗口</dt>
          <dd>{windowLabel[delivery.delivery_window.state]}</dd>
          {delivery.delivered_at && (
            <>
              <dt>交付时间</dt>
              <dd>{localTime(delivery.delivered_at)}</dd>
            </>
          )}
          {['CONFLICT', 'UNKNOWN'].includes(delivery.postcheck_status) && (
            <>
              <dt>后核对</dt>
              <dd>仓库状态待核对</dd>
            </>
          )}
        </dl>
      )}
      <Confirmation
        open={previewIntent !== null}
        title="准备交付预览"
        busy={preview.busy}
        description="读取并固定任务目标分支的完整代码树，供接收前审阅。"
        confirmDisabled={!previewOpen}
        confirm={() => {
          if (previewOpen && previewIntent) {
            preview.submit(previewIntent);
            setPreviewIntent(null);
          }
        }}
        cancel={() => setPreviewIntent(null)}
      />
      <Confirmation
        open={acceptance !== null}
        title="接收代码候选"
        busy={accept.busy}
        description={
          '确认候选 #' +
          acceptance?.candidate_id +
          '、报告 #' +
          acceptance?.test_report_id +
          '及完整目标预览 #' +
          acceptance?.delivery_plan_id +
          '。交付结果以实际 Git 核对为准。'
        }
        confirmLabel="确认接收"
        confirmDisabled={!acceptOpen}
        confirm={() => {
          if (acceptOpen && acceptance) {
            accept.submit(acceptance);
            setAcceptance(null);
          }
        }}
        cancel={() => setAcceptance(null)}
      />
    </section>
  );
}
