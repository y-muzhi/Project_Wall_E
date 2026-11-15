import { useCallback, useEffect, useId as useReactId, useMemo, useRef, useState } from 'react';
import type { CodeTaskView } from '../api/code-task-creation.ts';
import type { CodeCallDetail } from '../api/code-task-usage.ts';
import type { WalleApi } from '../api/walle.ts';
import { CopyButton } from '../shared/copy-button.tsx';
import { EmptyState } from '../shared/empty-state.tsx';
import { Pagination } from '../shared/pagination.tsx';
import { useSettingsRead } from './settings/read.ts';

const callStatus = {
  RUNNING: '调用中',
  SUCCEEDED: '已响应',
  FAILED: '调用失败',
  CANCELLED: '已取消',
};
const transportStatus = {
  NOT_SENT: '未发送',
  SENDING: '发送中',
  SENT: '已发送',
  COMPLETE: '响应完整',
  INTERRUPTED: '响应中断',
  UNKNOWN: '传输待核对',
};
const captureStatus = {
  FULL: '完整记录',
  REDACTED: '已脱敏',
  INCOMPLETE: '记录不完整',
};
const reservationStatus = {
  RESERVED: '已预留',
  SETTLED: '已核算',
  RELEASED_UNSENT: '未发送，已释放预留',
  UNKNOWN: '费用待核对',
  DISPUTED: '用量不一致，费用待核对',
};
const usageStatus = {
  NOT_REPORTED: '未记录',
  PARTIAL: '仅有部分用量',
  FINAL: '已记录最终用量',
  DISPUTED: '用量记录不一致',
};
const displayTime = new Intl.DateTimeFormat('zh-HK', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});
function timestamp(value: string | null) {
  return value === null ? '尚未结束' : displayTime.format(new Date(value));
}
function tokens(value: number | null) {
  return value === null ? '未记录' : value.toLocaleString('zh-HK');
}

type Props = Readonly<{
  api: WalleApi;
  task: CodeTaskView;
  visible: boolean;
  page: number;
  selectPage(page: number): void;
}>;
export function CodeTaskUsage({ api, task, visible, page, selectPage }: Props) {
  const taskId = task.id;
  const [attempt, retry] = useState(0);
  const [selected, select] = useState<number | null>(null);
  const lastButton = useRef<HTMLButtonElement | null>(null);
  const heading = useRef<HTMLHeadingElement | null>(null);
  const load = useCallback(
    (signal: AbortSignal) => {
      void attempt;
      return api.codeModelCalls(taskId, page, signal);
    },
    [api, taskId, page, attempt],
  );
  const observing =
    task.status === 'RUNNING' || task.status === 'STOPPING' || task.active_operations.length > 0;
  const pollDelay = useCallback(() => (observing ? 5000 : null), [observing]);
  const list = useSettingsRead(load, visible, '暂时无法读取模型调用', pollDelay);
  const observedPage = list.value?.meta.pagination;
  const pagination = observedPage?.page === page ? observedPage : undefined;
  const rows = pagination === undefined ? undefined : list.value?.data.items;

  function closeDetail() {
    select(null);
    const previous = lastButton.current;
    if (previous?.isConnected) previous.focus();
    else heading.current?.focus();
  }

  return (
    <section className="code-task-result" aria-label="模型用量">
      <dl className="code-task-facts">
        <dt>预算</dt>
        <dd>¥{task.budget.limit_cny}</dd>
        <dt>已核算</dt>
        <dd>¥{task.budget.settled_cny}</dd>
        <dt title="为模型调用暂留的预算，核算后释放差额">预留</dt>
        <dd>¥{task.budget.reserved_cny}</dd>
        <dt>可用</dt>
        <dd>¥{task.budget.available_cny}</dd>
        <dt>费用待核对</dt>
        <dd>{task.budget.unresolved_call_count} 次</dd>
      </dl>
      <div className="code-task-toolbar">
        <h2 ref={heading} tabIndex={-1}>
          模型调用
        </h2>
        <button
          className="ui-button"
          type="button"
          disabled={!visible || list.loading}
          onClick={() => retry((value) => value + 1)}
        >
          刷新模型调用
        </button>
      </div>
      <div aria-busy={list.loading}>
        {list.loading && <p role="status">正在读取模型调用…</p>}
        {list.error && <p role="alert">{list.error}</p>}
        {rows && rows.length > 0 && (
          <ul className="code-model-calls">
            {rows.map((call) => (
              <li key={call.id}>
                <div>
                  <h3>
                    {call.model_name} · {call.call_purpose === 'CODE' ? '编码' : '上下文压缩'}
                  </h3>
                  <p>
                    执行会话 #{call.execution_session_id} · 调用 {call.call_no} ·{' '}
                    {callStatus[call.call_status]}
                  </p>
                  <p>
                    {transportStatus[call.transport_status]} · {timestamp(call.started_at)} 至{' '}
                    {timestamp(call.ended_at)}
                  </p>
                  <p>
                    输入 {tokens(call.input_tokens)} · 输出 {tokens(call.output_tokens)} · 缓存{' '}
                    {tokens(call.cached_tokens)} · 耗时{' '}
                    {call.duration_ms === null ? '未记录' : call.duration_ms + ' 毫秒'}
                  </p>
                </div>
                <button
                  type="button"
                  className="ui-button"
                  aria-pressed={selected === call.id}
                  onClick={(event) => {
                    lastButton.current = event.currentTarget;
                    select(call.id);
                  }}
                >
                  查看调用 #{call.id}
                </button>
              </li>
            ))}
          </ul>
        )}
        {!list.loading && !list.error && rows?.length === 0 && (
          <EmptyState
            icon="outline"
            message={page === 1 ? '任务尚无模型调用' : '当前页超出调用记录范围'}
          />
        )}
        {pagination && 'page' in pagination && (
          <Pagination value={pagination} loading={list.loading} change={selectPage} />
        )}
      </div>
      {selected !== null && (
        <SelectedCall
          key={selected}
          api={api}
          taskId={taskId}
          useId={selected}
          visible={visible}
          close={closeDetail}
        />
      )}
    </section>
  );
}

function SelectedCall({
  api,
  taskId,
  useId,
  visible,
  close,
}: Readonly<{
  api: WalleApi;
  taskId: number;
  useId: number;
  visible: boolean;
  close(): void;
}>) {
  const [attempt, retry] = useState(0);
  const heading = useRef<HTMLHeadingElement | null>(null);
  const load = useCallback(
    (signal: AbortSignal) => {
      void attempt;
      return api.codeModelCall(taskId, useId, signal);
    },
    [api, taskId, useId, attempt],
  );
  const detail = useSettingsRead(load, visible, '暂时无法读取原调用详情');
  const labelId = useReactId();
  useEffect(() => {
    if (visible) heading.current?.focus();
  }, [visible]);
  return (
    <section className="code-model-audit" aria-labelledby={labelId} aria-busy={detail.loading}>
      <div className="code-task-toolbar">
        <h2 ref={heading} tabIndex={-1} id={labelId}>
          模型调用 #{useId}
        </h2>
        <button className="ui-button" type="button" onClick={close}>
          关闭详情
        </button>
      </div>
      {detail.loading && <p role="status">正在读取原调用详情…</p>}
      {detail.error && (
        <p role="alert">
          {detail.error}{' '}
          <button className="ui-button" type="button" onClick={() => retry((value) => value + 1)}>
            重试读取详情
          </button>
        </p>
      )}
      {detail.value && <CallDetails call={detail.value.data} />}
    </section>
  );
}

function CallDetails({ call }: Readonly<{ call: CodeCallDetail }>) {
  const response = call.response_snapshot;
  const basis =
    call.settlement_basis === 'VERIFIED_USAGE'
      ? '按用量核算'
      : call.settlement_basis === 'PROVIDER_BILL'
        ? '已与供应商账单核对'
        : '尚未核算';
  return (
    <>
      <dl className="code-task-facts">
        <dt>传输状态</dt>
        <dd>{transportStatus[call.transport_status]}</dd>
        <dt>记录状态</dt>
        <dd>{captureStatus[call.capture_status]}</dd>
        <dt>用量状态</dt>
        <dd>{usageStatus[call.usage_status]}</dd>
        <dt>费用状态</dt>
        <dd>{reservationStatus[call.reservation_status]}</dd>
        <dt>调用预留</dt>
        <dd>¥{call.reserved_cny}</dd>
        <dt>费用依据</dt>
        <dd>
          {basis}
          {call.settled_cny === null ? '' : ' · ¥' + call.settled_cny}
        </dd>
        <dt>协议版本</dt>
        <dd>{call.protocol_version}</dd>
        {call.provider_request_id !== null && (
          <>
            <dt>供应商请求标识</dt>
            <dd>{call.provider_request_id}</dd>
          </>
        )}
      </dl>
      <AuditSection title="实际请求" snapshot={call.request_snapshot} />
      {response === null ? (
        <p role="status">尚未记录响应内容。</p>
      ) : (
        <>
          {!response.complete && (
            <p role="status">
              {call.call_status === 'RUNNING'
                ? '调用尚未结束，以下为当前已记录的响应。'
                : '响应记录不完整，以下为已保存内容。'}
            </p>
          )}
          <AuditSection title="实际响应" snapshot={response} />
        </>
      )}
    </>
  );
}

function AuditSection({ title, snapshot }: Readonly<{ title: string; snapshot: unknown }>) {
  const [open, setOpen] = useState(false);
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>{title}</summary>
      {open && <AuditText title={title} snapshot={snapshot} />}
    </details>
  );
}

function AuditText({ title, snapshot }: Readonly<{ title: string; snapshot: unknown }>) {
  const [formatted, setFormatted] = useState(false);
  const [query, setQuery] = useState('');
  const [notice, setNotice] = useState('');
  const last = useRef(-1);
  const target = useRef<HTMLTextAreaElement | null>(null);
  const content = useMemo(
    () => JSON.stringify(snapshot, null, formatted ? 2 : undefined),
    [formatted, snapshot],
  );
  function find() {
    const input = target.current;
    if (!input || query.length === 0) return;
    let index = content.indexOf(query, last.current + 1);
    if (index < 0 && last.current >= 0) index = content.indexOf(query);
    if (index < 0) {
      setNotice('未找到匹配内容');
      return;
    }
    last.current = index;
    input.focus();
    input.setSelectionRange(index, index + query.length);
    setNotice('已选中匹配内容');
  }
  return (
    <>
      <div className="code-task-toolbar">
        <button
          className="ui-button"
          type="button"
          onClick={() => {
            last.current = -1;
            setNotice('');
            setFormatted(!formatted);
          }}
        >
          {formatted ? '紧凑 JSON' : '格式化 JSON'}
        </button>
        <label>
          搜索{title}{' '}
          <input
            type="search"
            value={query}
            onChange={(event) => {
              last.current = -1;
              setQuery(event.target.value);
              setNotice('');
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                find();
              }
            }}
          />
        </label>
        <button className="ui-button" type="button" disabled={query.length === 0} onClick={find}>
          查找下一处
        </button>
        <CopyButton content={content} />
      </div>
      {notice && <p role="status">{notice}</p>}
      <textarea ref={target} aria-label={title + '内容'} readOnly rows={12} value={content} />
    </>
  );
}
