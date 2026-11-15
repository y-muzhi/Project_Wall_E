import { useCallback, useState } from 'react';
import type { CodeTaskView } from '../api/code-task-creation.ts';
import type { CodeTaskOperation } from '../api/code-task-operations.ts';
import { reconciliationPath } from '../api/code-task-reconciliation.ts';
import type { WalleApi } from '../api/walle.ts';
import { Confirmation } from '../shared/confirmation.tsx';
import type { OperationReader } from './command-recovery.ts';
import { useCodeTaskCommand } from './handoff-command.ts';
import { RecoveryActions } from './settings/recovery-actions.tsx';

type Props = Readonly<{
  api: WalleApi;
  task: CodeTaskView;
  ready: boolean;
  changed(): void;
  delivery?: boolean;
}>;
type Intent = Readonly<{ operation_id: number; expected_state_version: number }>;

type RepairOperation = Extract<CodeTaskOperation, { operation_type: 'REPAIR' }>;

function repairObservationResult(operation: RepairOperation) {
  if (operation.status === 'SUCCEEDED') return '原修复已完成，请查看新候选和后续检查。';
  if (operation.status === 'CANCELLED') return '原修复已取消，请查看修复记录。';
  if (operation.status === 'FAILED') return '原修复未完成，请查看修复记录。';
  const send = operation.steps[1];
  if (!send) throw Error('原修复步骤缺失');
  if (send.status === 'SUCCEEDED') return '已确认原修复消息，修复结果仍在等待。';
  if (send.status === 'PENDING') return '原修复会话创建已核实，修复尚未发送。';
  return '原修复会话创建已核实，发送状态仍需核对。';
}

export function RoleReconciliation({ api, task, ready, changed, delivery = false }: Props) {
  const action = task.available_actions.find((item) => item.action === 'RECONCILE');
  const original = task.active_operations.find(
    (item) =>
      (delivery
        ? item.operation_type === 'DELIVER'
        : item.operation_type === 'HANDOFF_ROLE' || item.operation_type === 'REPAIR') &&
      (item.status === 'UNKNOWN' || (delivery && item.status === 'RUNNING')),
  );
  const [repairResult, setRepairResult] = useState(false);
  const repair = original ? original.operation_type === 'REPAIR' : repairResult;
  const title = delivery ? '核对原交付结果' : repair ? '核对原修复结果' : '核对原角色操作';
  const [confirm, setConfirm] = useState<Intent | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const readOperation = useCallback<OperationReader>(
    async (_, association, signal) => {
      if (association.task_id !== task.id || association.testing_task_id !== null)
        throw Error('原角色核对跨任务');
      const response = await api.codeTaskOperation(task.id, association.operation_id, signal);
      const row = response.data;
      if (row.operation_type !== 'RECONCILE') throw Error('原角色核对类型不一致');
      const observation = row.steps.at(-1)?.result_ref;
      if (!signal?.aborted) {
        if (row.status === 'CANCELLED') setResult('核对已取消。');
        else if (observation?.original_status === 'SUCCEEDED')
          setResult(delivery ? '原交付和收尾已核实。' : '已确认原消息接收，角色交接已完成。');
        else if (observation?.original_status === 'RUNNING') {
          if (delivery) {
            setResult('原交付仍在处理，请查看交付进度。');
          } else {
            const originalId = observation?.operation_id;
            if (
              typeof originalId !== 'number' ||
              !Number.isSafeInteger(originalId) ||
              originalId <= 0
            )
              throw Error('原操作身份不一致');
            const source = await api.codeTaskOperation(task.id, originalId, signal);
            if (!signal?.aborted) {
              if (source.data.operation_type === 'REPAIR') {
                setRepairResult(true);
                setResult(repairObservationResult(source.data));
              } else if (source.data.operation_type === 'HANDOFF_ROLE') {
                setRepairResult(false);
                setResult(
                  source.data.status === 'SUCCEEDED'
                    ? '已确认原消息接收，角色交接已完成。'
                    : source.data.status === 'UNKNOWN'
                      ? '原会话创建已核实，请继续核对角色交接。'
                      : '原会话创建已核实，角色交接仍在继续。',
                );
              } else throw Error('原操作类型不一致');
            }
          }
        } else if (observation?.original_status === 'UNKNOWN')
          setResult(
            delivery ? '原交付仍需核对，请查看原交付记录。' : '本次观察仍未取得原接收证据。',
          );
        else setResult(delivery ? '正在核对原交付。' : '正在核对原会话。');
      }
      return {
        task_id: row.task_id,
        testing_task_id: row.testing_task_id,
        operation_id: row.id,
        status: row.status,
      };
    },
    [api, task.id, delivery],
  );
  const command = useCodeTaskCommand(
    api,
    reconciliationPath(task.id),
    () => undefined,
    changed,
    delivery ? '原交付核对' : '原会话核对',
    '核对请求已接收。',
    readOperation,
  );
  if (!original && !command.pending && !result) return null;
  const allowed = Boolean(
    ready && original && action?.enabled && action.related_id === original.id,
  );
  const disabledReason = !allowed
    ? action?.reason_code === 'OPERATION_IN_PROGRESS'
      ? '原核对正在处理'
      : '原运行范围暂不能核对'
    : command.busy
      ? '正在提交或核对原请求'
      : !command.ready
        ? '正在读取原请求记录'
        : command.pending !== null
          ? '请先核对已保存的原请求'
          : null;
  const current = Boolean(
    disabledReason === null &&
    confirm &&
    confirm.operation_id === original?.id &&
    confirm.expected_state_version === task.state_version,
  );

  function choose() {
    if (disabledReason === null && original)
      setConfirm({ operation_id: original.id, expected_state_version: task.state_version });
  }

  function submit() {
    if (!current || !confirm) return;
    setConfirm(null);
    setResult(null);
    command.submit(confirm);
  }

  return (
    <section aria-label={delivery ? '原交付核对' : repair ? '原修复核对' : '原角色操作核对'}>
      <div className="code-task-toolbar">
        {original && (
          <button
            className="ui-button"
            type="button"
            onClick={choose}
            disabled={disabledReason !== null}
            title={disabledReason ?? undefined}
          >
            {title}
          </button>
        )}
        {original && disabledReason !== null && <span>{disabledReason}</span>}
        {command.busy && (
          <button className="ui-button" type="button" onClick={command.stop}>
            停止等待
          </button>
        )}
      </div>
      {command.error && (
        <p role="alert" className="inline-error">
          {command.error}
        </p>
      )}
      {command.notice && <p role="status">{command.notice}</p>}
      {result && <p role="status">{result}</p>}
      {command.pending && (
        <div className="code-task-toolbar">
          <button
            className="ui-button"
            type="button"
            disabled={command.busy}
            onClick={command.pending.status === 'ACCEPTED' ? command.observe : command.lookup}
          >
            {command.pending.status === 'ACCEPTED' ? '读取本次核对结果' : '核对原请求'}
          </button>
          <RecoveryActions
            record={command.pending}
            recovery={command.recovery}
            replayEnabled={allowed}
            settled={command.settled}
          />
        </div>
      )}
      <Confirmation
        open={confirm !== null}
        busy={command.busy}
        title={title}
        description={
          delivery
            ? '读取原 Git 目标、写入结果及已保存的交付证据。'
            : '读取原会话创建、消息接收及保存的操作证据。'
        }
        confirmLabel="开始核对"
        confirmDisabled={!current}
        confirm={submit}
        cancel={() => setConfirm(null)}
      />
    </section>
  );
}
