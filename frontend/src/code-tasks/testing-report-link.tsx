import { useCallback, useState } from 'react';
import { reportLinkPath } from '../api/code-task-report-link.ts';
import type { CodeTaskView } from '../api/code-task-creation.ts';
import type { TestingReport } from '../api/testing-reports.ts';
import type { WalleApi } from '../api/walle.ts';
import { Confirmation } from '../shared/confirmation.tsx';
import { EmptyState } from '../shared/empty-state.tsx';
import { meta, Pager, ReadState, useTestingRead } from '../testing/plans/read.tsx';
import { ReportFacts } from '../testing/report/task-report.tsx';
import { useCodeTaskCommand } from './handoff-command.ts';
import { RecoveryActions } from './settings/recovery-actions.tsx';

type Picked = { report: number; testingTask: number };
type Fixed = { candidate_id: number; test_report_id: number; expected_state_version: number };
const openReport = (report: TestingReport) =>
  '/testing/tasks/' + report.testing_task_id + '?tab=report&report_id=' + report.id;

function ReportRecord({
  api,
  owner,
  identity,
  testingTask,
  receive,
  show,
  historical = false,
  visible = true,
}: Readonly<{
  api: WalleApi;
  owner: number;
  identity: number;
  testingTask?: number;
  receive?: boolean;
  show?: ((report: TestingReport) => void) | undefined;
  historical?: boolean;
  visible?: boolean;
}>) {
  const load = useCallback(
    (signal: AbortSignal) => api.testingReport(identity, signal),
    [api, identity],
  );
  const read = useTestingRead('coding-report:' + owner + ':' + identity, visible ? load : null);
  const report = read.data?.data;
  const mismatch =
    report !== undefined &&
    (report.provenance.target_kind !== 'CANDIDATE' ||
      report.provenance.source_code_task_id !== owner ||
      (testingTask !== undefined && report.testing_task_id !== testingTask));
  return (
    <section
      className="testing-editor-panel"
      aria-label={
        historical
          ? '指定独立测试报告 #' + identity
          : receive
            ? '可关联的原报告'
            : '已关联的独立报告'
      }
    >
      <ReadState
        loading={read.loading}
        error={read.error}
        stale={report !== undefined}
        retry={read.reload}
      />
      {mismatch && (
        <p role="alert" className="inline-error">
          此报告不属于当前 Coding 任务。
        </p>
      )}
      {report && !mismatch && (
        <>
          {historical && <p className="read-status">指定独立测试报告，仅供查看</p>}
          <ReportFacts report={report} />
          <div className="code-task-toolbar">
            <a className="ui-button" href={openReport(report)}>
              打开原测试任务
            </a>
            <button
              type="button"
              className="ui-button"
              disabled={read.loading}
              onClick={read.reload}
            >
              核对报告资格
            </button>
            {show && (
              <button
                type="button"
                className="ui-button"
                disabled={read.loading || read.error !== null || !report.delivery_eligible}
                title={!report.delivery_eligible ? '请核对该报告的交付资格原因' : undefined}
                onClick={() => show(report)}
              >
                选择此报告
              </button>
            )}
          </div>
        </>
      )}
    </section>
  );
}

export function HistoricalCodingReport({
  api,
  task,
  report,
  visible,
  close,
}: Readonly<{
  api: WalleApi;
  task: number;
  report: number;
  visible: boolean;
  close(): void;
}>) {
  return (
    <section className="code-task-result" aria-label="历史独立测试报告">
      <div className="code-task-toolbar">
        <button type="button" className="ui-button" onClick={close}>
          返回当前独立测试
        </button>
      </div>
      <ReportRecord api={api} owner={task} identity={report} historical visible={visible} />
    </section>
  );
}

export function TestingReportLink({
  api,
  task,
  ready,
  changed,
}: Readonly<{ api: WalleApi; task: CodeTaskView; ready: boolean; changed(): void }>) {
  const [open, setOpen] = useState(false),
    [page, setPage] = useState(1);
  const [picked, setPicked] = useState<Picked | null>(null);
  const [fixed, setFixed] = useState<Fixed | null>(null);
  const candidate = task.current_candidate_id;
  const linked = task.current_refs.test_report_id;
  const command = useCodeTaskCommand(
    api,
    reportLinkPath(task.id),
    () => undefined,
    changed,
    '原关联',
    '报告已关联，等待用户接收。',
  );
  const action = task.available_actions.find((item) => item.action === 'LINK_TEST_REPORT');
  const load = useCallback(
    (signal: AbortSignal) => api.testingTasks({ candidate_id: candidate! }, page, signal),
    [api, candidate, page],
  );
  const list = useTestingRead(
    'coding-report-sources:' + task.id + ':' + candidate + ':' + page,
    !open || candidate === null ? null : load,
  );
  const rows = list.data?.data.items;
  const actionBlock = !ready
    ? '请先核对当前 Coding 任务'
    : command.busy
      ? '正在核对原报告关联'
      : !command.ready
        ? '请先读取原关联请求'
        : command.pending !== null
          ? '请先核对尚未确认的原关联请求'
          : !action?.enabled
            ? action?.reason_code === 'TEST_SOURCE_MISMATCH'
              ? '当前候选尚未有效发布'
              : action?.reason_code === 'OPERATION_CONFLICT'
                ? '请先处理原活动或等待事项'
                : '当前任务状态不允许关联报告'
            : null;
  const canLink = actionBlock === null;
  const confirmed =
    fixed !== null &&
    canLink &&
    fixed.candidate_id === candidate &&
    fixed.expected_state_version === task.state_version;
  function choose(report: TestingReport) {
    if (
      !canLink ||
      candidate === null ||
      report.id === linked ||
      !report.delivery_eligible ||
      report.provenance.candidate_id !== candidate ||
      report.provenance.source_code_task_id !== task.id
    )
      return;
    setFixed({
      candidate_id: candidate,
      test_report_id: report.id,
      expected_state_version: task.state_version,
    });
  }
  function submit() {
    if (!confirmed || fixed === null) return;
    const original = fixed;
    setFixed(null);
    command.submit(original);
  }
  const canBrowse =
    candidate !== null &&
    (task.status === 'AWAITING_TESTING' ||
      task.status === 'AWAITING_ACCEPTANCE' ||
      action?.enabled === true);
  return (
    <>
      {linked === null ? (
        <EmptyState icon="outline" message="尚未关联独立测试报告" compact />
      ) : (
        <ReportRecord key={linked} api={api} owner={task.id} identity={linked} />
      )}
      {canBrowse && (
        <div className="code-task-toolbar">
          <a className="ui-button" href={'/testing?candidate_id=' + candidate}>
            查看该候选的测试任务
          </a>
          <button
            type="button"
            className="ui-button"
            aria-expanded={open}
            onClick={() => {
              setPicked(null);
              setOpen(!open);
            }}
          >
            {open ? '关闭报告选择' : '选择已有报告'}
          </button>
        </div>
      )}
      {open && canBrowse && (
        <section className="testing-editor-panel" aria-label="候选的测试报告选择">
          <ReadState
            loading={list.loading}
            error={list.error}
            stale={rows !== undefined}
            retry={list.reload}
          />
          {!list.loading && !list.error && rows?.length === 0 && (
            <EmptyState
              icon="outline"
              message={page === 1 ? '该候选暂无独立测试任务' : '此页没有测试任务'}
              compact
            />
          )}
          {!!rows?.length && (
            <ol className="code-settings-version-items">
              {rows.map((row) => (
                <li key={row.id} className="code-task-toolbar">
                  <span>独立测试任务 #{row.id}</span>
                  <button
                    type="button"
                    className="ui-button"
                    disabled={row.report_id === null}
                    title={row.report_id === null ? '此任务尚未生成报告' : undefined}
                    aria-pressed={picked?.report === row.report_id && row.report_id !== null}
                    onClick={() => {
                      if (row.report_id !== null)
                        setPicked({ report: row.report_id, testingTask: row.id });
                    }}
                  >
                    {row.report_id === null ? '报告尚未生成' : '查看报告 #' + row.report_id}
                  </button>
                </li>
              ))}
            </ol>
          )}
          {list.data && (
            <Pager
              meta={meta(list.data.meta.pagination)}
              page={page}
              busy={list.loading}
              select={(next) => {
                setPicked(null);
                setPage(next);
              }}
            />
          )}
          {picked && (
            <ReportRecord
              key={picked.report}
              api={api}
              owner={task.id}
              identity={picked.report}
              testingTask={picked.testingTask}
              receive
              show={canLink && picked.report !== linked ? choose : undefined}
            />
          )}
          {actionBlock !== null && <p className="read-status">{actionBlock}</p>}
          {picked?.report === linked && picked !== null && (
            <p className="read-status">此报告已关联。</p>
          )}
        </section>
      )}
      {command.error && (
        <p className="inline-error" role="alert">
          {command.error}
        </p>
      )}
      {command.notice && <p role="status">{command.notice}</p>}
      {command.busy && (
        <button type="button" className="ui-button" onClick={command.stop}>
          停止等待关联
        </button>
      )}
      {command.pending && (
        <div className="code-task-toolbar">
          <button
            type="button"
            className="ui-button"
            disabled={command.busy}
            onClick={command.lookup}
          >
            核对原报告关联请求
          </button>
          <RecoveryActions
            record={command.pending}
            recovery={command.recovery}
            replayEnabled={Boolean(ready && action?.enabled)}
            settled={command.settled}
          />
        </div>
      )}
      <Confirmation
        open={fixed !== null}
        busy={command.busy}
        title="关联独立测试报告"
        description={
          fixed === null
            ? ''
            : '采用报告 #' +
              fixed.test_report_id +
              ' 作为候选 #' +
              fixed.candidate_id +
              ' 的接收依据。'
        }
        confirmLabel="确认关联"
        confirmDisabled={!confirmed}
        confirm={submit}
        cancel={() => setFixed(null)}
      />
    </>
  );
}
