import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiRejected, ApiUnknown } from '../api/client.ts';
import type { CodeTaskView } from '../api/code-task-creation.ts';
import type { NativePermission } from '../api/code-task-issues.ts';
import {
  permissionDecisions,
  permissionResponsePath,
} from '../api/code-task-permission-response.ts';
import type {
  PermissionDecision,
  PermissionOperation,
} from '../api/code-task-permission-response.ts';
import type { WalleApi } from '../api/walle.ts';
import { Confirmation } from '../shared/confirmation.tsx';
import type { PendingSummary } from './command-recovery-model.ts';
import { CommandRecoveryStore, CommandStorageError } from './command-recovery-store.ts';
import type { RecoveryLookup } from './command-recovery.ts';
import { RecoveryActions } from './settings/recovery-actions.tsx';
import { useSettingsRead } from './settings/read.ts';

const labels = { ALLOW_ONCE: '允许一次', DENY: '拒绝本会话待批权限' };
const denyScope = '将拒绝本会话中当前待批的权限请求，任务不会因此自动终止。';
const reasons = {
  CONFIG_NOT_READY: '当前环境尚未启用处理操作。',
  SESSION_NOT_CURRENT: '原会话已不再是当前执行会话。',
  TASK_ENDED: '任务已结束。',
  INVALID_STATE: '任务正在停止。',
  EXTERNAL_RESULT_UNKNOWN: '原请求的处理结果待核对。',
  QUESTION_NOT_OPEN: '该请求已结束处理。',
  OPERATION_IN_PROGRESS: '原任务正在处理另一项控制操作。',
  PERMISSION_NOT_GRANTED: '需先调整授权。当前生效授权无法核实该对象。',
};

type Props = Readonly<{
  api: WalleApi;
  task: CodeTaskView;
  row: NativePermission;
  visible: boolean;
  ready: boolean;
  changed(): void;
}>;

function errorText(error: unknown) {
  return error instanceof ApiRejected ||
    error instanceof ApiUnknown ||
    error instanceof CommandStorageError
    ? error.message
    : '暂时无法核对原权限决定。';
}

function terminal(value: PermissionOperation['status']) {
  return value === 'SUCCEEDED' || value === 'FAILED' || value === 'CANCELLED';
}

function poll(value: PermissionOperation) {
  return terminal(value.status) ? null : value.status === 'UNKNOWN' ? 5000 : 1500;
}

function progress(value: PermissionOperation) {
  const action = labels[value.fixed_input.decision];
  switch (value.status) {
    case 'PENDING':
      return action + '请求已接收，等待原生确认。';
    case 'RUNNING':
      return '正在核对' + action + '的原生结果。';
    case 'UNKNOWN':
      return action + '的处理结果待核对，请查看各项权限状态。';
    case 'SUCCEEDED':
      return action + '已由执行器确认。';
    case 'FAILED':
      return value.failure_code === 'PERMISSION_NOT_GRANTED'
        ? '未派发。需先调整授权或核实原权限对象。'
        : '未派发。原待批权限或连接暂时无法核对。';
    case 'CANCELLED':
      return '任务停止时取消了尚未派发的权限决定。';
  }
}

export function PermissionResponseControl({ api, task, row, visible, ready, changed }: Props) {
  const taskId = task.id;
  const permissionId = row.id;
  const sessionId = row.session_id;
  const path = permissionResponsePath(taskId, permissionId);
  const recovery = useMemo(
    () =>
      api.configurationRecovery(
        new CommandRecoveryStore({ scope: api.environmentScope }),
        async (original, link, signal) => {
          if (original.path !== path || link.task_id !== taskId)
            throw Error('Original permission response owner differs');
          const { data } = await api.codeTaskOperation(taskId, link.operation_id, signal);
          if (
            data.operation_type !== 'DECIDE_PERMISSION' ||
            data.fixed_input.permission_id !== permissionId ||
            data.session_id !== sessionId ||
            data.idempotency_key !== original.key
          )
            throw Error('Original permission operation differs');
          return {
            operation_id: data.id,
            task_id: taskId,
            testing_task_id: null,
            status: data.status,
          };
        },
      ),
    [api, path, permissionId, sessionId, taskId],
  );
  const [pending, setPending] = useState<PendingSummary | null>(null);
  const [accepted, setAccepted] = useState<number | null>(null);
  const [ledgerReady, setLedgerReady] = useState(false);
  const [choice, setChoice] = useState<PermissionDecision | null>(null);
  const [busy, setBusy] = useState(false);
  const [canStopWaiting, setCanStopWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const alive = useRef(false);
  const inProgress = useRef(false);
  const sending = useRef<AbortController | null>(null);
  const completed = useRef<number | null>(null);

  const readPending = useCallback(async () => {
    const rows = await recovery.store.list();
    if (!alive.current) return;
    const original = rows.find((entry) => entry.path === path) ?? null;
    setPending(original);
    if (original?.operation_id != null) setAccepted(original.operation_id);
    setLedgerReady(true);
  }, [path, recovery]);

  useEffect(() => {
    alive.current = true;
    void readPending().catch((failure) => {
      if (alive.current) setError(errorText(failure));
    });
    return () => {
      alive.current = false;
      sending.current?.abort();
      recovery.dispose();
    };
  }, [readPending, recovery]);

  const operationId = pending?.operation_id ?? accepted;
  const load = useCallback(
    async (signal: AbortSignal) => {
      void retry;
      if (operationId === null) throw Error('Original permission operation not selected');
      const { data } = await api.codeTaskOperation(taskId, operationId, signal);
      if (
        data.operation_type !== 'DECIDE_PERMISSION' ||
        data.fixed_input.permission_id !== permissionId ||
        data.session_id !== sessionId
      )
        throw Error('Original permission operation differs');
      return data;
    },
    [api, operationId, permissionId, retry, sessionId, taskId],
  );
  const read = useSettingsRead(
    load,
    visible && operationId !== null,
    '暂时无法读取原权限操作',
    poll,
  );
  const operation = read.value?.id === operationId ? read.value : null;
  useEffect(() => {
    if (!operation || !terminal(operation.status) || completed.current === operation.id) return;
    const controller = new AbortController();
    async function finish() {
      if (!operation) return;
      if (pending?.operation_id === operation.id && pending.status === 'ACCEPTED') {
        await recovery.reconcileOperation(pending.key, controller.signal);
        if (!controller.signal.aborted) await readPending();
      }
      if (!controller.signal.aborted) {
        completed.current = operation.id;
        changed();
      }
    }
    void finish().catch((failure) => {
      if (!controller.signal.aborted) setError(errorText(failure));
    });
    return () => controller.abort();
  }, [changed, operation, pending, readPending, recovery, retry]);

  async function run(action: () => Promise<void>) {
    if (inProgress.current) return;
    inProgress.current = true;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
    } catch (failure) {
      if (!alive.current) return;
      setError(errorText(failure));
      await readPending().catch(() => undefined);
      if (failure instanceof ApiRejected && failure.code === 'VERSION_CONFLICT') changed();
    } finally {
      inProgress.current = false;
      if (alive.current) setBusy(false);
    }
  }

  async function apply(result: RecoveryLookup) {
    if (!alive.current) return;
    const id = result.original_receipt?.operation_id ?? result.local?.operation_id;
    const outcome = result.original_receipt?.original_outcome;
    if (id != null) {
      setAccepted(id);
      setNotice('权限决定已接收，等待原生确认。');
      changed();
    } else if (outcome && !outcome.success) {
      setError(outcome.error.message);
      if (outcome.error.code === 'VERSION_CONFLICT') changed();
    } else setNotice('原权限决定结果待核对。');
    await readPending();
  }

  const waits = task.waiting_items.filter((item) => item.kind === 'PERMISSION');
  function unavailable(decision: PermissionDecision) {
    if (pending) return '请先核对原权限决定。';
    if (!ledgerReady) return '正在核对本地原请求。';
    const action = row.available_actions.find((item) => item.action === decision);
    if (!action?.enabled)
      return action?.reason_code ? reasons[action.reason_code] : '当前权限请求暂不可处理。';
    if (
      !ready ||
      task.active_session_id !== sessionId ||
      task.control_generation !== row.control_generation ||
      !waits.some((item) => item.source_id === permissionId)
    )
      return '当前任务与原待批权限的状态正在核对。';
    return null;
  }

  function submit() {
    if (!choice || unavailable(choice) || inProgress.current) return;
    const decision = choice;
    setChoice(null);
    void run(async () => {
      const staged = await recovery.stageIntent(path, {
        expected_state_version: task.state_version,
        session_id: sessionId,
        decision,
      });
      if (!alive.current) return;
      if (staged.kind !== 'PREPARED') {
        await readPending();
        setNotice('已有原权限决定，请先核对。');
        return;
      }
      setPending(staged.record);
      const controller = new AbortController();
      sending.current = controller;
      setCanStopWaiting(true);
      try {
        await apply(
          await recovery.send(staged.record.key, staged.record.record_revision, controller.signal),
        );
      } finally {
        sending.current = null;
        if (alive.current) setCanStopWaiting(false);
      }
    });
  }

  return (
    <section aria-label={'决定权限请求 #' + permissionId}>
      <div className="code-task-toolbar">
        {permissionDecisions.map((decision) => {
          const reason = unavailable(decision);
          const reasonId = 'permission-' + permissionId + '-' + decision;
          return (
            <div key={decision}>
              <button
                type="button"
                className="ui-button"
                disabled={busy || reason !== null}
                aria-describedby={reason ? reasonId : undefined}
                onClick={() => setChoice(decision)}
              >
                {labels[decision]}
              </button>
              {reason && (
                <p id={reasonId} className="field-help">
                  {reason}
                </p>
              )}
            </div>
          );
        })}
      </div>
      {row.status === 'OPEN' && (
        <p className="field-help">
          {denyScope} 当前观察到的待批权限
          {waits.length && task.active_session_id === sessionId
            ? ' ' + waits.map((item) => '#' + item.source_id).join('、') + '。'
            : '暂不可核对。'}
        </p>
      )}
      <div className="code-task-toolbar">
        {pending && (
          <button
            type="button"
            className="ui-button"
            disabled={busy}
            onClick={() => void run(async () => apply(await recovery.lookup(pending.key)))}
          >
            核对原权限决定
          </button>
        )}
        {canStopWaiting && (
          <button type="button" className="ui-button" onClick={() => sending.current?.abort()}>
            停止等待权限结果
          </button>
        )}
        {operationId !== null && (
          <button
            type="button"
            className="ui-button"
            disabled={read.loading}
            onClick={() => setRetry((value) => value + 1)}
          >
            核对权限操作 #{operationId}
          </button>
        )}
        {!ledgerReady && error && (
          <button
            type="button"
            className="ui-button"
            disabled={busy}
            onClick={() => void run(readPending)}
          >
            重新读取原权限决定
          </button>
        )}
      </div>
      {operation ? (
        <p role="status">{progress(operation)}</p>
      ) : (
        notice && <p role="status">{notice}</p>
      )}
      {(error || read.error) && (
        <p className="inline-error" role="alert">
          {error ?? read.error}
        </p>
      )}
      {pending && (
        <RecoveryActions
          record={pending}
          recovery={recovery}
          replayEnabled={false}
          settled={(_, result, message) => {
            if (result) void run(() => apply(result));
            else
              void run(async () => {
                await readPending();
                setNotice(message);
              });
          }}
        />
      )}
      {choice && (
        <Confirmation
          open
          title={labels[choice]}
          description={
            choice === 'DENY' ? denyScope : '仅对当前待批请求放行一次，生效授权范围保持原值。'
          }
          confirmLabel={choice === 'DENY' ? '确认拒绝' : '确认允许'}
          cancelLabel="取消"
          busy={busy}
          dangerous={choice === 'DENY'}
          confirmDisabled={unavailable(choice) !== null}
          confirm={submit}
          cancel={() => setChoice(null)}
        />
      )}
    </section>
  );
}
