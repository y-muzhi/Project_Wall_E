import { useCallback, useState } from 'react';
import { issueStatuses } from '../api/code-task-issues.ts';
import type { IssueKind, IssueStatus, NativeIssue } from '../api/code-task-issues.ts';
import type { WalleApi } from '../api/walle.ts';
import type { CodeTaskView } from '../api/code-task-creation.ts';
import type { DocumentHandoffLink } from '../application/router.ts';
import { QuestionHandoffControl } from './question-handoff-control.tsx';
import { PermissionResponseControl } from './permission-response-control.tsx';
import { QuestionResponseControl } from './question-response-control.tsx';
import { EmptyState } from '../shared/empty-state.tsx';
import { Pagination } from '../shared/pagination.tsx';
import { useSettingsRead } from './settings/read.ts';

const labels = { questions: '原生问题', permissions: '权限请求' };
const statuses = {
  OPEN: '待处理',
  ANSWERING: '处理中',
  RESOLVED: '已处理',
  REJECTED: '已拒绝',
  UNKNOWN: '结果待核对',
  OBSOLETE: '已退役',
};
const reasons = {
  CONFIG_NOT_READY: '当前环境尚未启用处理操作。',
  SESSION_NOT_CURRENT: '原会话已不再是当前执行会话。',
  TASK_ENDED: '任务已结束。',
  INVALID_STATE: '任务正在停止。',
  EXTERNAL_RESULT_UNKNOWN: '原请求的处理结果待核对。',
  QUESTION_NOT_OPEN: '该请求已结束处理。',
  OPERATION_IN_PROGRESS: '原任务正在处理另一项控制操作。',
  PERMISSION_NOT_GRANTED: '需先调整授权。',
};
const permissionActions = {
  READ: '读取',
  WRITE: '写入',
  EXECUTE: '执行',
  NETWORK: '网络访问',
  UNKNOWN: '待核实',
};

type Props = Readonly<{
  api: WalleApi;
  task: CodeTaskView;
  visible: boolean;
  live: boolean;
  ready: boolean;
  changed(): void;
  openHandoff(requirementId: number, link: DocumentHandoffLink): void;
}>;

export function TaskNativeIssues(props: Props) {
  const [selected, setSelected] = useState<IssueKind | null>(null);
  return (
    <section className="code-task-controls" aria-label="原生问题和权限">
      <div className="code-task-toolbar">
        {(Object.keys(labels) as IssueKind[]).map((kind) => (
          <button
            key={kind}
            type="button"
            className="ui-button"
            aria-expanded={selected === kind}
            onClick={() => setSelected((current) => (current === kind ? null : kind))}
          >
            {labels[kind]}
          </button>
        ))}
      </div>
      {selected && <IssueList key={selected} {...props} kind={selected} />}
    </section>
  );
}

function pollIssuePage() {
  return 2000;
}

function IssueList({
  api,
  task,
  visible,
  live,
  ready,
  changed,
  openHandoff,
  kind,
}: Props & Readonly<{ kind: IssueKind }>) {
  const taskId = task.id;
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<IssueStatus | ''>('');
  const [retry, setRetry] = useState(0);
  const afterAnswer = useCallback(() => {
    setRetry((value) => value + 1);
    changed();
  }, [changed]);
  const load = useCallback(
    async (signal: AbortSignal) => {
      void retry;
      const result = await api.codeTaskIssues(taskId, kind, page, status, signal);
      return { result, status, page };
    },
    [api, taskId, kind, page, status, retry],
  );
  const state = useSettingsRead(
    load,
    visible,
    '暂时无法读取' + labels[kind],
    live ? pollIssuePage : undefined,
  );
  const value =
    state.value?.status === status && state.value.page === page ? state.value.result : null;
  const metadata = value?.meta.pagination;
  const pagination = metadata && 'page' in metadata ? metadata : null;
  const rows = value?.data.items;

  return (
    <section aria-label={labels[kind] + '列表'} aria-busy={state.loading}>
      <div className="code-task-toolbar">
        <label>
          请求状态{' '}
          <select
            value={status}
            onChange={(event) => {
              const next = issueStatuses.find((entry) => entry === event.target.value) ?? '';
              setStatus(next);
              setPage(1);
            }}
          >
            <option value="">全部状态</option>
            {issueStatuses.map((entry) => (
              <option key={entry} value={entry}>
                {statuses[entry]}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="ui-button"
          disabled={state.loading}
          onClick={() => setRetry((value) => value + 1)}
        >
          刷新{labels[kind]}
        </button>
      </div>
      {state.loading && <p role="status">正在读取{labels[kind]}…</p>}
      {state.error && (
        <p role="alert" className="inline-error">
          {state.error}
        </p>
      )}
      {rows?.length === 0 && !state.loading && !state.error && (
        <EmptyState
          icon="outline"
          message={
            pagination?.total
              ? '该页没有' + labels[kind]
              : status
                ? '当前筛选没有' + labels[kind]
                : '任务尚无' + labels[kind]
          }
        />
      )}
      {rows && rows.length > 0 && (
        <ul>
          {rows.map((row) => (
            <Issue
              key={row.session_id + ':' + row.id}
              row={row}
              api={api}
              task={task}
              visible={visible}
              ready={ready && !state.error && !state.loading}
              listUnavailable={state.error !== null}
              changed={afterAnswer}
              openHandoff={openHandoff}
            />
          ))}
        </ul>
      )}
      {pagination && (
        <Pagination
          value={pagination}
          change={setPage}
          loading={state.loading}
          compactSingle
          showLoadingStatus={false}
        />
      )}
    </section>
  );
}

function Issue({
  row,
  api,
  task,
  visible,
  ready,
  listUnavailable,
  changed,
  openHandoff,
}: Omit<Props, 'live'> & Readonly<{ row: NativeIssue; listUnavailable: boolean }>) {
  const question = 'questions' in row;
  const answerReason = row.available_actions.find(
    (item) => item.action === 'ANSWER_QUESTION',
  )?.reason_code;
  const handoffReason = row.available_actions.find(
    (item) => item.action === 'PREPARE_HANDOFF',
  )?.reason_code;
  return (
    <li>
      <h3>
        {question ? '原生问题' : '权限请求'} #{row.id} · {statuses[row.status]}
      </h3>
      {question ? (
        <ol>
          {row.questions.map((item) => (
            <li key={item.index}>
              <h4>{item.header}</h4>
              <p>{item.text}</p>
              {item.options.length > 0 && (
                <ul>
                  {item.options.map((option, index) => (
                    <li key={index}>
                      {option.label}
                      {option.description && ' · ' + option.description}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ol>
      ) : (
        <>
          <p>
            工具 {row.tool_name} · {permissionActions[row.requested_action]}
          </p>
          {row.object_refs.map((item) => (
            <p key={item.path}>
              工作区对象 <code>{item.path}</code>
            </p>
          ))}
          {row.patterns.length > 0 && (
            <ul>
              {row.patterns.map((pattern, index) => (
                <li key={index}>
                  <code>{pattern}</code>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {question ? (
        <QuestionResponseControl
          api={api}
          task={task}
          row={row}
          visible={visible}
          ready={ready}
          changed={changed}
          listUnavailable={listUnavailable}
          disabledReason={answerReason ? reasons[answerReason] : null}
        />
      ) : (
        <PermissionResponseControl
          api={api}
          task={task}
          row={row}
          visible={visible}
          ready={ready}
          changed={changed}
        />
      )}
      {question && (
        <QuestionHandoffControl
          api={api}
          task={task}
          row={row}
          visible={visible}
          ready={ready}
          changed={changed}
          openHandoff={openHandoff}
          disabledReason={handoffReason ? reasons[handoffReason] : null}
        />
      )}
    </li>
  );
}
