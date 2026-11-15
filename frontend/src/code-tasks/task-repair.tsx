import { useCallback, useState } from 'react';
import type { CodeTaskView } from '../api/code-task-creation.ts';
import { repairPath } from '../api/code-task-repair.ts';
import type { WalleApi } from '../api/walle.ts';
import { Confirmation } from '../shared/confirmation.tsx';
import { EmptyState } from '../shared/empty-state.tsx';
import { localTime } from '../shared/time.ts';
import { meta, Pager, ReadState, useTestingRead } from '../testing/plans/read.tsx';
import type { OperationReader } from './command-recovery.ts';
import { useCodeTaskCommand } from './handoff-command.ts';
import { RecoveryActions } from './settings/recovery-actions.tsx';

const labels = {
  PENDING: '等待处理',
  RUNNING: '正在修复',
  UNKNOWN: '结果待核对',
  SUCCEEDED: '新候选已生成，需检查',
  FAILED: '修复失败',
  CANCELLED: '已取消',
};
const repairFailureText = new Map([
  ['SOURCE_CHANGED', '工作区内容与固定候选不同，本次修复未发送。'],
  ['EXECUTION_NOT_STOPPED', '原执行是否静止尚未核实，本次修复未发送。'],
  ['CONTENT_NOT_READY', '无法读取本次修复的固定来源。'],
  ['CONFIG_NOT_READY', '本次修复的执行资源尚未就绪。'],
  ['EXTERNAL_RESULT_UNKNOWN', '原修复操作结果待核对。'],
]);

function unavailableRepairReason(reason: string | null | undefined): string {
  if (reason === 'EXECUTION_NOT_STOPPED') return '请先核对原活动已停止';
  if (reason === 'CONFIG_NOT_READY') return '修复所需的执行资源尚未就绪';
  if (reason === 'OPERATION_CONFLICT') return '任务中有其他操作，请完成或核对后再发起修复';
  return '当前任务无法发起修复';
}

type Intent = { candidate_id: number; defect_ids: number[]; expected_state_version: number };

export function TaskRepairControl({
  api,
  task,
  ready,
  chosen,
  reset,
  changed,
}: Readonly<{
  api: WalleApi;
  task: CodeTaskView;
  ready: boolean;
  chosen: readonly number[];
  reset(): void;
  changed(): void;
}>) {
  const [confirm, setConfirm] = useState<Intent | null>(null);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<number | null>(null);
  const candidate = task.current_candidate_id;
  const read = useCallback(
    (signal: AbortSignal) => api.codeRepairs(task.id, page, signal),
    [api, task.id, page],
  );
  const repairs = useTestingRead('repair:' + task.id + ':' + page, read);
  const loadDetail = useCallback(
    (signal: AbortSignal) => api.codeRepair(task.id, selected!, signal),
    [api, task.id, selected],
  );
  const detail = useTestingRead(
    'repair-detail:' + task.id + ':' + selected,
    selected === null ? null : loadDetail,
  );
  const readOperation = useCallback<OperationReader>(
    async (_, association, signal) => {
      if (association.task_id !== task.id || association.testing_task_id !== null)
        throw Error('原修复操作不属于当前任务');
      const { data } = await api.codeTaskOperation(task.id, association.operation_id, signal);
      if (data.operation_type !== 'REPAIR') throw Error('原修复操作类型不一致');
      return {
        task_id: data.task_id,
        testing_task_id: null,
        operation_id: data.id,
        status: data.status,
      };
    },
    [api, task.id],
  );
  const command = useCodeTaskCommand(
    api,
    repairPath(task.id),
    reset,
    () => {
      repairs.reload();
      detail.reload();
      changed();
    },
    '修复',
    '修复请求已提交。',
    readOperation,
  );
  const action = task.available_actions.find((row) => row.action === 'REPAIR');
  const reason = !ready
    ? '请先核对当前任务'
    : command.busy
      ? '正在处理原修复请求'
      : !command.ready
        ? '正在读取原修复请求'
        : command.pending
          ? '请先核对原修复请求'
          : candidate === null
            ? '当前任务没有固定候选'
            : !action?.enabled
              ? unavailableRepairReason(action?.reason_code)
              : chosen.length === 0
                ? '请选择当前候选的缺陷'
                : null;
  const canConfirm =
    confirm !== null &&
    reason === null &&
    confirm.candidate_id === candidate &&
    confirm.expected_state_version === task.state_version &&
    confirm.defect_ids.every((id) => chosen.includes(id)) &&
    confirm.defect_ids.length === chosen.length;
  const rows = repairs.data?.data.items ?? [];
  const pagination = meta(repairs.data?.meta.pagination);
  function request() {
    if (reason === null && candidate !== null)
      setConfirm({
        candidate_id: candidate,
        defect_ids: [...chosen],
        expected_state_version: task.state_version,
      });
  }
  function submit() {
    if (!canConfirm || confirm === null) return;
    command.submit(confirm);
    setConfirm(null);
  }
  return (
    <section aria-label="缺陷修复">
      <h3>缺陷修复</h3>
      <div className="code-task-toolbar">
        <button
          type="button"
          className="ui-button"
          disabled={reason !== null}
          title={reason ?? undefined}
          onClick={request}
        >
          按所选报告修复
        </button>
        <button
          type="button"
          className="ui-button"
          disabled={repairs.loading}
          onClick={repairs.reload}
        >
          核对修复记录
        </button>
      </div>
      {chosen.length > 0 && <p>已选择 {chosen.length} 条缺陷。</p>}
      {reason && <p className="read-status">{reason}</p>}
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
            核对原修复请求
          </button>
          {command.pending.status === 'ACCEPTED' && (
            <button
              type="button"
              className="ui-button"
              disabled={command.busy}
              onClick={command.observe}
            >
              读取原修复进度
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
      <ReadState
        loading={repairs.loading}
        error={repairs.error}
        stale={repairs.data !== null}
        retry={repairs.reload}
      />
      {!repairs.loading && !repairs.error && rows.length === 0 && (
        <EmptyState
          icon="outline"
          message={page === 1 ? '此任务尚无修复记录' : '当前页没有修复记录'}
          compact
        />
      )}
      {rows.length > 0 && (
        <ul>
          {rows.map((row) => (
            <li key={row.id}>
              <button type="button" className="ui-button" onClick={() => setSelected(row.id)}>
                查看修复 #{row.id}
              </button>
              {' · '}
              {labels[row.status]}
            </li>
          ))}
        </ul>
      )}
      {pagination && (
        <Pager meta={pagination} page={page} busy={repairs.loading} select={setPage} />
      )}
      {selected !== null && (
        <section aria-label={'原修复 #' + selected}>
          <ReadState
            loading={detail.loading}
            error={detail.error}
            stale={detail.data !== null}
            retry={detail.reload}
          />
          {detail.data && (
            <dl>
              <dt>状态</dt>
              <dd>{labels[detail.data.data.status]}</dd>
              {detail.data.data.failure_code !== null && (
                <>
                  <dt>原因</dt>
                  <dd>
                    {repairFailureText.get(detail.data.data.failure_code) ?? '请核对原修复操作。'}
                  </dd>
                </>
              )}
              <dt>来源候选</dt>
              <dd>#{detail.data.data.source_candidate_id}</dd>
              <dt>缺陷报告</dt>
              <dd>{detail.data.data.defect_ids.map((id) => '#' + id).join('、')}</dd>
              <dt>发起时间</dt>
              <dd>{localTime(detail.data.data.created_at)}</dd>
              {detail.data.data.result_candidate_id !== null && (
                <>
                  <dt>新候选</dt>
                  <dd>#{detail.data.data.result_candidate_id}，需完成自检及独立复测</dd>
                </>
              )}
            </dl>
          )}
          <button type="button" className="ui-button" onClick={() => setSelected(null)}>
            关闭修复详情
          </button>
        </section>
      )}
      <Confirmation
        open={confirm !== null}
        busy={command.busy}
        title="发起缺陷修复"
        description={
          '按候选 #' +
          confirm?.candidate_id +
          ' 的缺陷 ' +
          confirm?.defect_ids.map((id) => '#' + id).join('、') +
          ' 发起一次修复。原报告保留，旧候选的接收资格失效。'
        }
        confirmLabel="发起修复"
        confirmDisabled={!canConfirm}
        confirm={submit}
        cancel={() => setConfirm(null)}
      />
    </section>
  );
}
