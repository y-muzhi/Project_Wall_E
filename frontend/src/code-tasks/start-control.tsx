import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiRejected, ApiUnknown } from '../api/client.ts';
import type { CodeTaskView } from '../api/code-task-creation.ts';
import { taskStartPath } from '../api/code-task-start.ts';
import type { WalleApi } from '../api/walle.ts';
import { CommandRecoveryStore, CommandStorageError } from './command-recovery-store.ts';
import type { PendingSummary } from './command-recovery-model.ts';
import type { RecoveryLookup } from './command-recovery.ts';
import { RecoveryActions } from './settings/recovery-actions.tsx';

type Props = Readonly<{
  api: WalleApi;
  task: CodeTaskView;
  visible: boolean;
  ready: boolean;
  changed(): void;
}>;

function errorMessage(error: unknown) {
  return error instanceof ApiRejected ||
    error instanceof ApiUnknown ||
    error instanceof CommandStorageError
    ? error.message
    : '暂时无法核对开始请求。';
}

export function TaskStartControl({ api, task, visible, ready, changed }: Props) {
  const taskId = task.id;
  const path = taskStartPath(taskId);
  const recovery = useMemo(
    () =>
      api.configurationRecovery(new CommandRecoveryStore(), async (original, link, signal) => {
        if (original.decoder_kind !== 'APP-CODE-CMD-C35' || original.parameters.task_id !== taskId)
          throw TypeError('Original start belongs to another task');
        const { data } = await api.taskStartOperation(
          link.operation_id,
          taskId,
          signal,
          original.key,
        );
        return {
          operation_id: data.id,
          task_id: data.task_id,
          testing_task_id: null,
          status: data.status,
        };
      }),
    [api, taskId],
  );
  const [pending, setPending] = useState<PendingSummary | null>(null);
  const [ledgerReady, setLedgerReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [operationId, setOperationId] = useState<number | null>(null);
  const [observationAttempt, retryObservation] = useState(0);
  const mounted = useRef(false);
  const running = useRef(false);
  const sending = useRef<AbortController | null>(null);
  const [canStopWaiting, setCanStopWaiting] = useState(false);

  async function readPending() {
    const records = await recovery.store.list();
    if (!mounted.current) return;
    setPending(records.find((row) => row.path === path) ?? null);
    setLedgerReady(true);
  }

  useEffect(() => {
    mounted.current = true;
    let retired = false;
    void recovery.store.list().then(
      (records) => {
        if (retired) return;
        setPending(records.find((row) => row.path === path) ?? null);
        setLedgerReady(true);
      },
      (failure) => {
        if (!retired) setError(errorMessage(failure));
      },
    );
    return () => {
      retired = true;
      mounted.current = false;
      sending.current?.abort();
      recovery.dispose();
    };
  }, [path, recovery]);

  const accepted = pending?.status === 'ACCEPTED' ? pending : null;
  useEffect(() => {
    if (!visible || accepted === null) return;
    const controller = new AbortController();
    let timer: number | undefined;
    async function observe(record: PendingSummary) {
      try {
        if (record.operation_id === null) throw TypeError('Original start operation is missing');
        const { data } = await api.taskStartOperation(
          record.operation_id,
          taskId,
          controller.signal,
          record.key,
        );
        if (controller.signal.aborted) return;
        if (
          data.status === 'FAILED' ||
          data.status === 'CANCELLED' ||
          data.status === 'SUCCEEDED'
        ) {
          await recovery.reconcileOperation(record.key, controller.signal);
          if (controller.signal.aborted) return;
          setPending(null);
          setNotice(null);
          changed();
        } else if (data.status === 'UNKNOWN') {
          setNotice('开始操作结果待核对。');
          changed();
        } else {
          timer = window.setTimeout(() => void observe(record), 1200);
        }
      } catch (failure) {
        if (!controller.signal.aborted) setError(errorMessage(failure));
      }
    }
    void observe(accepted);
    return () => {
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [accepted, api, changed, observationAttempt, recovery, taskId, visible]);

  const start = task.available_actions.find((action) => action.action === 'START');
  const active = task.active_operations.find((operation) => operation.operation_type === 'START');
  const existing = active?.id ?? start?.related_id ?? operationId ?? accepted?.operation_id ?? null;
  const reason =
    !ready || !ledgerReady
      ? '正在核对任务与原请求'
      : pending && !accepted
        ? '请先核对原开始请求'
        : task.status === 'RUNNING' || task.status === 'WAITING'
          ? '任务已开始执行'
          : existing !== null
            ? '已有原开始操作'
            : task.status === 'TERMINATED'
              ? '任务已终止'
              : task.status === 'STOPPING'
                ? '已封闭任务后续执行'
                : !start?.enabled
                  ? '执行条件尚未就绪'
                  : null;

  async function apply(result: RecoveryLookup) {
    if (!mounted.current) return;
    const id = result.original_receipt?.operation_id ?? result.local?.operation_id;
    const outcome = result.original_receipt?.original_outcome;
    if (id !== null && id !== undefined) {
      setOperationId(id);
      setNotice('开始请求已提交，正在核对原操作。');
      changed();
    } else if (outcome && !outcome.success) {
      setError(outcome.error.message);
    } else if (!result.local || !('final_state' in result.local)) {
      setNotice('开始请求结果待核对。');
    }
    await readPending();
  }

  async function run(action: () => Promise<void>) {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (failure) {
      if (mounted.current) {
        setError(errorMessage(failure));
        await readPending().catch(() => undefined);
        if (failure instanceof ApiRejected && failure.code === 'VERSION_CONFLICT') changed();
      }
    } finally {
      running.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  function submit() {
    if (reason !== null) return;
    void run(async () => {
      const original = await recovery.stageIntent(path, {
        expected_state_version: task.state_version,
      });
      if (!mounted.current) return;
      if (original.kind !== 'PREPARED') {
        setNotice('已有原开始请求，请先核对。');
        await readPending();
        return;
      }
      setPending(original.record);
      const controller = new AbortController();
      sending.current = controller;
      setCanStopWaiting(true);
      try {
        await apply(
          await recovery.send(
            original.record.key,
            original.record.record_revision,
            controller.signal,
          ),
        );
      } finally {
        sending.current = null;
        if (mounted.current) setCanStopWaiting(false);
      }
    });
  }

  const waiting = pending !== null && accepted === null;
  return (
    <>
      <div className="code-task-toolbar">
        <button
          type="button"
          className="ui-button"
          disabled={reason !== null || busy}
          aria-describedby={reason ? 'code-start-reason' : undefined}
          onClick={submit}
        >
          开始任务
        </button>
        {canStopWaiting && (
          <button type="button" className="ui-button" onClick={() => sending.current?.abort()}>
            停止等待
          </button>
        )}
        {reason && (
          <span id="code-start-reason" className="read-status">
            {reason}
          </span>
        )}
        {existing !== null && (
          <button
            type="button"
            className="ui-button"
            onClick={() => {
              setError(null);
              changed();
              if (accepted) retryObservation((value) => value + 1);
            }}
          >
            刷新执行进度
          </button>
        )}
        {waiting && (
          <button
            type="button"
            className="ui-button"
            disabled={busy}
            onClick={() => void run(async () => apply(await recovery.lookup(pending.key)))}
          >
            核对原开始请求
          </button>
        )}
      </div>
      {notice && <p role="status">{notice}</p>}
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      {waiting && (
        <RecoveryActions
          record={pending}
          recovery={recovery}
          replayEnabled={ready && start?.enabled === true && !busy}
          settled={(_original, result, text) => {
            setNotice(text);
            void run(() => (result ? apply(result) : readPending()));
          }}
        />
      )}
    </>
  );
}
