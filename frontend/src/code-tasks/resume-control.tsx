import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiRejected, ApiUnknown } from '../api/client.ts';
import type { CodeTaskView } from '../api/code-task-creation.ts';
import { taskResumePath } from '../api/code-task-resume.ts';
import type { TaskResumeOperation } from '../api/code-task-resume.ts';
import type { WalleApi } from '../api/walle.ts';
import { Confirmation } from '../shared/confirmation.tsx';
import { CommandRecoveryStore, CommandStorageError } from './command-recovery-store.ts';
import type { PendingSummary } from './command-recovery-model.ts';
import type { RecoveryLookup } from './command-recovery.ts';
import { RecoveryActions } from './settings/recovery-actions.tsx';
import { useSettingsRead } from './settings/read.ts';

type Props = Readonly<{
  api: WalleApi;
  task: CodeTaskView;
  visible: boolean;
  ready: boolean;
  changed(): void;
}>;

function terminal(operation: TaskResumeOperation) {
  return ['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(operation.status);
}

function delay(result: { data: TaskResumeOperation }) {
  if (terminal(result.data)) return null;
  return result.data.status === 'UNKNOWN' ? 3000 : 1000;
}

function message(error: unknown) {
  return error instanceof ApiRejected ||
    error instanceof ApiUnknown ||
    error instanceof CommandStorageError
    ? error.message
    : '暂时无法核对原继续请求。';
}

function progress(operation: TaskResumeOperation, cleanup: boolean) {
  const result = operation.steps.at(-1)?.result_ref;
  if (result && 'delivery_id' in result) return '已恢复原交付收尾，正在等待停止和清理证据。';
  if (cleanup && !('repository_quiescent_confirmed' in operation.fixed_input)) {
    if (operation.status === 'FAILED') return '原交付暂时无法继续收尾。';
    if (operation.status === 'CANCELLED') return '继续收尾已随任务停止而取消。';
    return '正在核对原交付的收尾范围。';
  }
  if ('repository_quiescent_confirmed' in operation.fixed_input) {
    if (operation.status === 'SUCCEEDED') return '已确认原交付的新合作窗口。';
    if (operation.status === 'FAILED') return '原交付暂时无法重新确认合作窗口。';
    if (operation.status === 'CANCELLED') return '合作窗口确认已随任务停止而取消。';
    return '正在核对原交付和本次合作窗口。';
  }
  switch (operation.status) {
    case 'PENDING':
      return '继续请求已接收，等待核对原会话。';
    case 'RUNNING':
      return '正在核对继续消息。';
    case 'UNKNOWN':
      return '继续消息的接收结果待核对。';
    case 'SUCCEEDED':
      return '原会话已接收继续消息。';
    case 'CANCELLED':
      return '继续请求已随任务停止而取消。';
    case 'FAILED':
      return operation.failure_code === 'EXECUTION_NOT_STOPPED'
        ? '原会话的上一轮执行尚未核实结束。'
        : '当前执行配置、模型额度或价格暂不满足继续条件。';
  }
}

export function TaskResumeControl({ api, task, visible, ready, changed }: Props) {
  const taskId = task.id;
  const delivery = task.phase === 'DELIVERY';
  const cleanup = delivery && task.runtime.cleanup_status === 'UNKNOWN';
  const mode = cleanup ? 'CLEANUP' : delivery ? 'WINDOW' : 'MODEL';
  const path = taskResumePath(taskId);
  const recovery = useMemo(
    () =>
      api.configurationRecovery(
        new CommandRecoveryStore({ scope: api.environmentScope }),
        async (original, link, signal) => {
          if (
            original.decoder_kind !== 'APP-CODE-CMD-C36' ||
            original.parameters.task_id !== taskId ||
            link.task_id !== taskId
          )
            throw Error('Original continuation belongs to another task');
          const { data } = await api.taskResumeOperation(
            link.operation_id,
            taskId,
            signal,
            original.key,
          );
          return {
            operation_id: data.id,
            task_id: taskId,
            testing_task_id: null,
            status: data.status,
          };
        },
      ),
    [api, taskId],
  );
  const [pending, setPending] = useState<PendingSummary | null>(null);
  const [localOperation, setLocalOperation] = useState<number | null>(null);
  const [ledgerReady, setLedgerReady] = useState(false);
  const [confirm, setConfirm] = useState<{
    mode: typeof mode;
    version: number;
    source: number;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [canStopWaiting, setCanStopWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const mounted = useRef(true);
  const sending = useRef<AbortController | null>(null);
  const inFlight = useRef(false);
  const settledOperation = useRef<number | null>(null);

  const readPending = useCallback(async () => {
    const rows = await recovery.store.list();
    if (!mounted.current) return;
    const original = rows.find((row) => row.path === path) ?? null;
    setPending(original);
    if (original?.operation_id != null) setLocalOperation(original.operation_id);
    setLedgerReady(true);
  }, [path, recovery]);

  useEffect(() => {
    mounted.current = true;
    void readPending().catch((failure) => {
      if (mounted.current) setError(message(failure));
    });
    return () => {
      mounted.current = false;
      sending.current?.abort();
      recovery.dispose();
    };
  }, [readPending, recovery]);

  const active = task.active_operations.find((row) => row.operation_type === 'RESUME');
  const identity = active?.id ?? pending?.operation_id ?? localOperation;
  const operationLoad = useCallback(
    (signal: AbortSignal) => {
      void retry;
      if (identity === null) throw Error('No original continuation to read');
      return api.taskResumeOperation(identity, taskId, signal);
    },
    [api, identity, taskId, retry],
  );
  const operationRead = useSettingsRead(
    operationLoad,
    visible && identity !== null,
    '暂时无法读取继续进度',
    delay,
  );
  const operation = operationRead.value?.data.id === identity ? operationRead.value.data : null;

  useEffect(() => {
    if (
      !ledgerReady ||
      !operation ||
      !terminal(operation) ||
      settledOperation.current === operation.id ||
      (pending !== null && (pending.operation_id !== operation.id || pending.status !== 'ACCEPTED'))
    )
      return;
    const controller = new AbortController();
    async function settle() {
      if (!operation) return;
      try {
        if (pending?.operation_id === operation.id && pending.status === 'ACCEPTED') {
          await recovery.reconcileOperation(pending.key, controller.signal);
          if (!controller.signal.aborted) await readPending();
        }
        if (!controller.signal.aborted) {
          settledOperation.current = operation.id;
          changed();
        }
      } catch (failure) {
        if (!controller.signal.aborted) setError(message(failure));
      }
    }
    void settle();
    return () => controller.abort();
  }, [operation, pending, recovery, readPending, changed, retry, ledgerReady]);

  async function apply(result: RecoveryLookup) {
    if (!mounted.current) return;
    const acceptedId = result.original_receipt?.operation_id ?? result.local?.operation_id;
    const outcome = result.original_receipt?.original_outcome;
    if (acceptedId != null) {
      setLocalOperation(acceptedId);
      setNotice('继续请求已接收，正在核对原操作。');
      changed();
    } else if (outcome && !outcome.success) {
      setError(outcome.error.message);
      if (outcome.error.code === 'VERSION_CONFLICT') changed();
    } else if (result.local && 'final_state' in result.local) {
      setNotice('原继续请求已结束。');
    } else {
      setNotice('原继续请求结果待核对。');
    }
    await readPending();
  }

  async function run(action: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
    } catch (failure) {
      if (mounted.current) {
        setError(message(failure));
        await readPending().catch(() => undefined);
        if (failure instanceof ApiRejected && failure.code === 'VERSION_CONFLICT') changed();
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  const action = task.available_actions.find((row) => row.action === 'RESUME');
  const pendingNativeIssue = task.waiting_items.some(
    (item) => item.kind === 'QUESTION' || item.kind === 'PERMISSION',
  );
  const reason = pending
    ? '请先核对原继续请求'
    : !ready
      ? '当前任务状态正在核对'
      : !ledgerReady
        ? '本地请求记录尚未核实'
        : action?.reason_code === 'EXTERNAL_RESULT_UNKNOWN'
          ? '原模型或继续操作结果仍待核对'
          : action?.reason_code === 'OPERATION_IN_PROGRESS'
            ? '原继续操作正在处理'
            : pendingNativeIssue
              ? '请先核对待处理的原生问题或权限请求'
              : !action?.enabled
                ? '当前任务尚无可继续的等待事项'
                : null;

  const currentConfirmation =
    confirm !== null &&
    confirm.mode === mode &&
    confirm.version === task.state_version &&
    confirm.source === action?.related_id;

  function choose() {
    if (reason !== null || !action?.related_id) return;
    setConfirm({ mode, version: task.state_version, source: action.related_id });
  }

  function submit() {
    if (reason || !currentConfirmation || !confirm || inFlight.current) return;
    setConfirm(null);
    void run(async () => {
      const staged = await recovery.stageIntent(path, {
        expected_state_version: confirm.version,
        operation_id: confirm.source,
        waiting_item_ids: task.waiting_items.map((item) => item.id),
        ...(confirm.mode === 'WINDOW' ? { repository_quiescent_confirmed: true } : {}),
      });
      if (!mounted.current) return;
      if (staged.kind !== 'PREPARED') {
        setNotice('已有原继续请求，请先核对。');
        await readPending();
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
        if (mounted.current) setCanStopWaiting(false);
      }
    });
  }

  function recovered(_record: PendingSummary, result: RecoveryLookup | null, detail: string) {
    if (result) void run(() => apply(result));
    else {
      setNotice(detail);
      void run(readPending);
    }
  }

  if (task.status !== 'WAITING' && !pending && identity === null && !error) return null;
  return (
    <section className="code-task-controls" aria-label="继续代码任务">
      <div className="code-task-toolbar">
        {task.status === 'WAITING' && (
          <button
            type="button"
            className="ui-button"
            aria-describedby={reason ? 'task-resume-reason' : undefined}
            disabled={busy || reason !== null}
            onClick={choose}
          >
            {cleanup ? '继续原交付收尾' : delivery ? '重新确认交付窗口' : '继续原操作'}
          </button>
        )}
        {pending && (
          <button
            type="button"
            className="ui-button"
            disabled={busy}
            onClick={() => void run(async () => apply(await recovery.lookup(pending.key)))}
          >
            核对原继续请求
          </button>
        )}
        {canStopWaiting && (
          <button type="button" className="ui-button" onClick={() => sending.current?.abort()}>
            停止等待继续结果
          </button>
        )}
        {identity !== null && (
          <button
            type="button"
            className="ui-button"
            disabled={operationRead.loading}
            onClick={() => setRetry((value) => value + 1)}
          >
            核对继续操作 #{identity}
          </button>
        )}
        {!ledgerReady && error && (
          <button
            type="button"
            className="ui-button"
            disabled={busy}
            onClick={() => void run(readPending)}
          >
            重新读取继续请求记录
          </button>
        )}
      </div>
      {task.status === 'WAITING' && reason && (
        <p className="field-help" id="task-resume-reason">
          {reason}
        </p>
      )}
      {operation ? (
        <p role="status">{progress(operation, cleanup)}</p>
      ) : (
        notice && <p role="status">{notice}</p>
      )}
      {(error || operationRead.error) && (
        <p className="inline-error" role="alert">
          {error ?? operationRead.error}
        </p>
      )}
      {pending && (
        <RecoveryActions
          record={pending}
          recovery={recovery}
          replayEnabled={!busy && ready}
          settled={recovered}
        />
      )}
      <Confirmation
        open={confirm !== null}
        busy={busy}
        title={
          confirm?.mode === 'CLEANUP'
            ? '继续原交付收尾'
            : confirm?.mode === 'WINDOW'
              ? '确认原交付合作窗口'
              : '继续原代码操作'
        }
        description={
          confirm?.mode === 'CLEANUP'
            ? '核对已交付事实，仅继续本任务尚未完成的停止或清理。'
            : confirm?.mode === 'WINDOW'
              ? '确认在本次原交付结束前暂停此仓库的其他 Git 写操作。'
              : '核对原会话、等待事项和模型额度后，向原会话发送一次继续消息。'
        }
        confirmLabel={confirm?.mode === 'WINDOW' ? '确认合作窗口' : '确认继续'}
        confirmDisabled={reason !== null || !currentConfirmation}
        confirm={submit}
        cancel={() => setConfirm(null)}
      />
    </section>
  );
}
