import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiRejected, ApiUnknown } from '../api/client.ts';
import type { CodeTaskView } from '../api/code-task-creation.ts';
import { taskStopPath } from '../api/code-task-stop.ts';
import type { TaskStopOperation } from '../api/code-task-stop.ts';
import type { WalleApi } from '../api/walle.ts';
import { Confirmation } from '../shared/confirmation.tsx';
import { CommandRecoveryStore, CommandStorageError } from './command-recovery-store.ts';
import type { PendingSummary } from './command-recovery-model.ts';
import type { RecoveryLookup } from './command-recovery.ts';
import { RecoveryActions } from './settings/recovery-actions.tsx';
import { safeId } from './list-model.ts';

type Props = Readonly<{
  api: WalleApi;
  task: CodeTaskView;
  visible: boolean;
  ready: boolean;
  changed(): void;
}>;

function message(error: unknown) {
  return error instanceof ApiRejected ||
    error instanceof ApiUnknown ||
    error instanceof CommandStorageError
    ? error.message
    : '暂时无法核对停止结果，请保留原请求。';
}

export function TaskStopControl({ api, task, visible, ready, changed }: Props) {
  const taskId = task.id;
  const path = taskStopPath(taskId);
  const recovery = useMemo(
    () =>
      api.configurationRecovery(
        new CommandRecoveryStore({ scope: api.environmentScope }),
        async (original, association, signal) => {
          if (
            original.decoder_kind !== 'APP-CODE-CMD-C37' ||
            original.parameters.task_id !== taskId
          )
            throw Error('Original stop belongs to another task');
          const operation = (await api.taskStopOperation(association.operation_id, taskId, signal))
            .data;
          return {
            operation_id: operation.id,
            task_id: taskId,
            testing_task_id: null,
            status: operation.status,
          };
        },
      ),
    [api, taskId],
  );
  const [pending, setPending] = useState<PendingSummary | null>(null);
  const [operation, setOperation] = useState<TaskStopOperation | null>(null);
  const [acceptedId, setAcceptedId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [ledgerReady, setLedgerReady] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const mounted = useRef(true);
  const inFlight = useRef(false);

  const readPending = useCallback(async () => {
    const records = await recovery.store.list();
    if (!mounted.current) return;
    const original = records.find((row) => row.path === path) ?? null;
    setPending(original);
    setLedgerReady(true);
    if (original?.operation_id !== null && original?.operation_id !== undefined)
      setAcceptedId(original.operation_id);
  }, [path, recovery]);

  useEffect(() => {
    mounted.current = true;
    void readPending().catch((failure) => {
      if (mounted.current) setError(message(failure));
    });
    return () => {
      mounted.current = false;
      recovery.dispose();
    };
  }, [readPending, recovery]);

  const operationId = task.termination_operation_id ?? acceptedId;
  const [retryOperation, setRetryOperation] = useState(0);
  useEffect(() => {
    if (!visible || operationId === null) return;
    const controller = new AbortController();
    let timer: number | undefined;
    async function read() {
      if (operationId === null) return;
      try {
        const observed = (await api.taskStopOperation(operationId, taskId, controller.signal)).data;
        if (controller.signal.aborted) return;
        setOperation(observed);
        if (observed.status === 'SUCCEEDED') {
          if (pending?.operation_id === observed.id && pending.status === 'ACCEPTED') {
            await recovery.reconcileOperation(pending.key, controller.signal);
            if (controller.signal.aborted) return;
            await readPending();
          }
          if (!controller.signal.aborted && task.status !== 'TERMINATED') changed();
        } else {
          timer = window.setTimeout(() => void read(), observed.status === 'UNKNOWN' ? 2500 : 1200);
        }
      } catch (failure) {
        if (!controller.signal.aborted) setError(message(failure));
      }
    }
    void read();
    return () => {
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [
    api,
    taskId,
    operationId,
    task.status,
    visible,
    retryOperation,
    pending,
    recovery,
    readPending,
    changed,
  ]);

  async function apply(result: RecoveryLookup) {
    if (!mounted.current) return;
    const id = result.original_receipt?.operation_id ?? result.local?.operation_id;
    if (safeId(id)) {
      setAcceptedId(id);
      setNotice('停止请求已接收，正在核对原操作。');
      changed();
    } else if (
      result.original_receipt?.original_http_status === 200 ||
      (result.local && 'final_state' in result.local && result.local.http_status === 200)
    ) {
      setNotice('任务已结束。');
      changed();
    } else {
      const outcome = result.original_receipt?.original_outcome;
      if (outcome && !outcome.success) setError(outcome.error.message);
      else if (result.local && 'final_state' in result.local) setNotice('原停止请求已结束。');
      else setNotice('停止结果仍待核对。');
    }
    await readPending();
  }

  async function run(action: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
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

  function submit() {
    if (!ready || !ledgerReady || !mayStop || pending || operationId !== null) return;
    setConfirm(false);
    void run(async () => {
      const staged = await recovery.stageIntent(path, {
        expected_state_version: task.state_version,
      });
      if (!mounted.current) return;
      if (staged.kind !== 'PREPARED') {
        setNotice('已有原停止请求，请先核对。');
        await readPending();
        return;
      }
      setPending(staged.record);
      await apply(await recovery.send(staged.record.key, staged.record.record_revision));
    });
  }

  function settled(_original: PendingSummary, result: RecoveryLookup | null, text: string) {
    if (!mounted.current) return;
    setNotice(text);
    if (result) void run(() => apply(result));
    else void readPending().catch((failure) => setError(message(failure)));
  }

  const mayStop = task.available_actions.some(
    (action) => action.action === 'TERMINATE' && action.enabled,
  );
  const reason =
    task.status === 'TERMINATED'
      ? '任务已终止'
      : operationId !== null
        ? '已存在原停止操作'
        : pending
          ? '请先核对原停止请求'
          : !ready || !ledgerReady
            ? '正在核对任务与原请求'
            : !mayStop
              ? '当前任务状态不能停止'
              : null;
  const executionStopped = operation?.steps.some(
    (step) => step.step_type === 'STOP_OWNED_ACTIVITY' && step.status === 'SUCCEEDED',
  );
  const waiting =
    operation?.status === 'SUCCEEDED'
      ? '停止和清理已核实。'
      : executionStopped
        ? '原执行已停止，正在核对资源回收。'
        : operation?.status === 'UNKNOWN'
          ? '停止结果待核对，活动名额仍保留。'
          : operationId !== null
            ? '停止请求已接收，正在核对原操作。'
            : notice;
  return (
    <section className="code-task-stop" aria-label="任务停止">
      <div className="code-task-toolbar">
        <button
          className="ui-button"
          type="button"
          disabled={reason !== null || busy}
          aria-describedby={reason ? 'task-stop-reason' : undefined}
          onClick={() => setConfirm(true)}
        >
          停止任务
        </button>
        {reason && (
          <span id="task-stop-reason" className="read-status">
            {reason}
          </span>
        )}
        {operationId !== null && (
          <button
            className="ui-button"
            type="button"
            onClick={() => {
              setError(null);
              setRetryOperation((value) => value + 1);
            }}
          >
            核对停止操作 #{operationId}
          </button>
        )}
        {pending && pending.status !== 'ACCEPTED' && (
          <button
            className="ui-button"
            type="button"
            disabled={busy}
            onClick={() => void run(async () => apply(await recovery.lookup(pending.key)))}
          >
            核对原停止请求
          </button>
        )}
      </div>
      {waiting && <p role="status">{waiting}</p>}
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      {pending && pending.status !== 'ACCEPTED' && (
        <RecoveryActions
          record={pending}
          recovery={recovery}
          replayEnabled={!busy}
          settled={settled}
        />
      )}
      {confirm && (
        <Confirmation
          open
          title="停止代码任务"
          description="确认后会封闭任务后续执行。只有核实停止与清理后，才会释放该文档的活动任务名额。"
          confirmLabel="确认停止"
          cancelLabel="取消"
          busy={busy}
          confirmDisabled={reason !== null}
          confirm={submit}
          cancel={() => setConfirm(false)}
        />
      )}
    </section>
  );
}
