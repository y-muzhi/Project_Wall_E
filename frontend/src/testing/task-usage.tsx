import { useCallback, useEffect, useState } from 'react';
import type { TestingTaskView } from '../api/testing-tasks.ts';
import type { WalleApi } from '../api/walle.ts';
import { useSettingsVisibility } from '../code-tasks/settings/read.ts';
import { EmptyState } from '../shared/empty-state.tsx';
import { localTime } from '../shared/time.ts';
import { meta, Pager, ReadState, useTestingRead } from './plans/read.tsx';

const calls = { RUNNING: '调用中', SUCCEEDED: '已响应', FAILED: '调用失败', CANCELLED: '已取消' };
const usage = {
  NOT_REPORTED: '用量未记录',
  PARTIAL: '仅有部分用量',
  FINAL: '已记录最终用量',
  DISPUTED: '用量记录不一致',
};
const result = { PENDING: '尚未完成', SUCCEEDED: '成功', FAILED: '失败' };
function tokens(amount: number | null) {
  return amount === null ? '未记录' : amount.toLocaleString('zh-HK');
}

function Snapshot({
  title,
  value,
}: Readonly<{ title: string; value: Record<string, unknown> | null }>) {
  const [open, setOpen] = useState(false);
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>{title}</summary>
      {open &&
        (value === null ? (
          <p>此项尚无原记录</p>
        ) : (
          <textarea aria-label={title} readOnly rows={8} value={JSON.stringify(value, null, 2)} />
        ))}
    </details>
  );
}

function CallDetail({
  api,
  task,
  identity,
  close,
}: Readonly<{
  api: WalleApi;
  task: number;
  identity: number;
  close(): void;
}>) {
  const load = useCallback(
    (signal: AbortSignal) => api.testingCall(task, identity, signal),
    [api, task, identity],
  );
  const read = useTestingRead('testing-call:' + task + ':' + identity, load);
  const row = read.data?.data;
  return (
    <section className="testing-editor-panel code-model-audit" aria-label={'原调用 #' + identity}>
      <div className="code-settings-form-actions">
        <h4>原调用 #{identity}</h4>
        <button className="ui-button" type="button" onClick={close}>
          关闭调用详情
        </button>
      </div>
      <ReadState
        loading={read.loading}
        error={read.error}
        stale={row !== undefined}
        retry={read.reload}
      />
      {row && (
        <>
          <p>
            原起草操作 #{row.operation_id} · {calls[row.call_status]}
          </p>
          <p>
            解析 {result[row.parse_status]} · 校验 {result[row.validation_status]}
          </p>
          <p>
            {usage[row.usage_status]} · 输入 {tokens(row.input_tokens)} · 输出{' '}
            {tokens(row.output_tokens)}
          </p>
          <p>
            原预留 {row.reserved_cny} 元 ·{' '}
            {row.settled_cny === null ? '结算尚无记录' : '已结算 ' + row.settled_cny + ' 元'}
          </p>
          {row.settlement_basis !== null && (
            <p>
              结算依据 {row.settlement_basis === 'VERIFIED_USAGE' ? '已核实用量' : '供应方账单'}
            </p>
          )}
          {row.provider_request_id !== null && <p>供应方原请求标识 {row.provider_request_id}</p>}
          <Snapshot title="原请求" value={row.request_snapshot} />
          <Snapshot title="原响应" value={row.response_snapshot} />
          <Snapshot title="解析输出" value={row.parsed_output} />
          <Snapshot title="已校验计划草稿" value={row.trusted_output} />
        </>
      )}
    </section>
  );
}

export function TaskUsage({ api, task }: Readonly<{ api: WalleApi; task: TestingTaskView }>) {
  const [page, setPage] = useState(1),
    [selected, select] = useState<number | null>(null);
  const visible = useSettingsVisibility();
  const load = useCallback(
    (signal: AbortSignal) => api.testingCalls(task.id, page, signal),
    [api, task.id, page],
  );
  const read = useTestingRead('testing-calls:' + task.id + ':' + page, load);
  const rows = read.data?.data.items;
  useEffect(() => {
    if (!visible || task.status !== 'PLANNING' || read.loading || read.error !== null) return;
    const timer = window.setTimeout(read.reload, 5000);
    return () => window.clearTimeout(timer);
  }, [visible, task.status, read.loading, read.error, read.reload]);
  return (
    <section className="testing-editor-panel" aria-label="独立模型用量">
      <p>
        已结算 {task.budget.settled_cny} 元 · 预留 {task.budget.reserved_cny} 元 · 可用{' '}
        {task.budget.available_cny} 元
      </p>
      <p>
        请求 {task.budget.model_request_count} / {task.budget.request_limit}
      </p>
      <div className="code-settings-form-actions">
        <h3>原模型调用</h3>
        <button className="ui-button" type="button" disabled={read.loading} onClick={read.reload}>
          核对模型调用
        </button>
      </div>
      <ReadState
        loading={read.loading}
        error={read.error}
        stale={rows !== undefined}
        retry={read.reload}
      />
      {!read.loading && !read.error && rows?.length === 0 && (
        <EmptyState
          icon="outline"
          message={page === 1 ? '此任务尚无模型调用记录' : '此页没有模型调用记录'}
          compact
        />
      )}
      {!!rows?.length && (
        <ul className="code-model-calls">
          {rows.map((row) => (
            <li key={row.id}>
              <div>
                <h4>
                  调用 {row.call_no} · {row.model_name} · {calls[row.call_status]}
                </h4>
                <p>
                  {localTime(row.started_at)} · {usage[row.usage_status]}
                </p>
                <p>
                  输入 {tokens(row.input_tokens)} · 输出 {tokens(row.output_tokens)}
                </p>
              </div>
              <button
                className="ui-button"
                type="button"
                aria-pressed={selected === row.id}
                onClick={() => select(row.id)}
              >
                查看调用 #{row.id}
              </button>
            </li>
          ))}
        </ul>
      )}
      {read.data && (
        <Pager
          meta={meta(read.data.meta.pagination)}
          page={page}
          busy={read.loading}
          select={(next) => {
            select(null);
            setPage(next);
          }}
        />
      )}
      {selected !== null && (
        <CallDetail
          key={selected}
          api={api}
          task={task.id}
          identity={selected}
          close={() => select(null)}
        />
      )}
    </section>
  );
}
