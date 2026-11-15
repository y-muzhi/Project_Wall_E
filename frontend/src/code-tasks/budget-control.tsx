import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiRejected, ApiUnknown } from '../api/client.ts';
import { taskBudgetPath } from '../api/code-task-budget.ts';
import type { CodeTaskView } from '../api/code-task-creation.ts';
import { moneyMicro } from '../api/code-values.ts';
import type { WalleApi } from '../api/walle.ts';
import { CommandRecoveryStore, CommandStorageError } from './command-recovery-store.ts';
import type { PendingSummary } from './command-recovery-model.ts';
import type { RecoveryLookup } from './command-recovery.ts';
import { RecoveryActions } from './settings/recovery-actions.tsx';

type Props = Readonly<{ api: WalleApi; task: CodeTaskView; ready: boolean; changed(): void }>;

function validation(amount: string, reason: string, limit: string) {
  if (!amount) return '请输入新的人民币预算总额';
  try {
    if (moneyMicro(amount) <= moneyMicro(limit)) return '新预算必须高于当前预算';
  } catch {
    return '请输入最多六位小数的人民币金额';
  }
  if (!reason.trim()) return '请输入调整说明';
  return null;
}

function message(error: unknown) {
  if (
    error instanceof ApiRejected ||
    error instanceof ApiUnknown ||
    error instanceof CommandStorageError
  )
    return error.message;
  return '暂时无法核对预算请求，请保留原请求。';
}

export function TaskBudgetControl({ api, task, ready, changed }: Props) {
  const path = taskBudgetPath(task.id);
  const recovery = useMemo(
    () =>
      api.configurationRecovery(new CommandRecoveryStore(), async () => {
        throw Error('Budget changes do not produce a background operation');
      }),
    [api],
  );
  const [pending, setPending] = useState<PendingSummary | null>(null);
  const [ledgerReady, setLedgerReady] = useState(false);
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [canStopWaiting, setCanStopWaiting] = useState(false);
  const active = useRef(true);
  const inFlight = useRef(false);
  const sending = useRef<AbortController | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);
  const amountInput = useRef<HTMLInputElement>(null);

  const refreshOriginal = useCallback(async () => {
    const records = await recovery.store.list();
    if (!active.current) return;
    setPending(records.find((record) => record.path === path) ?? null);
    setLedgerReady(true);
  }, [path, recovery]);

  useEffect(() => {
    active.current = true;
    void refreshOriginal().catch((failure) => {
      if (active.current) setError(message(failure));
    });
    return () => {
      active.current = false;
      sending.current?.abort();
      recovery.dispose();
    };
  }, [refreshOriginal, recovery]);

  useEffect(() => {
    if (open) amountInput.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open && restoreFocus.current && !busy && !pending && ready && !trigger.current?.disabled) {
      restoreFocus.current = false;
      trigger.current?.focus();
    }
  }, [open, busy, pending, ready]);

  function closeForm() {
    setOpen(false);
    if (trigger.current?.disabled) restoreFocus.current = true;
    else trigger.current?.focus();
  }

  async function apply(result: RecoveryLookup) {
    if (!active.current) return;
    const original = result.original_receipt?.original_outcome;
    const local = result.local;
    if (
      original?.success ||
      (local && 'final_state' in local && local.final_state === 'CONFIRMED')
    ) {
      setNotice('预算总额已更新。');
      setAmount('');
      setReason('');
      closeForm();
      changed();
    } else if (original && !original.success) {
      setError(original.error.message);
      if (original.error.code === 'VERSION_CONFLICT') changed();
    } else if (local && 'final_state' in local && local.final_state === 'CLOSED_UNEXECUTED') {
      setNotice('原预算请求已关闭。');
    } else {
      setNotice('原预算请求结果待核对。');
    }
    await refreshOriginal();
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
      if (active.current) {
        setError(message(failure));
        await refreshOriginal().catch(() => undefined);
        if (failure instanceof ApiRejected && failure.code === 'VERSION_CONFLICT') changed();
      }
    } finally {
      inFlight.current = false;
      if (active.current) setBusy(false);
    }
  }

  const action = task.available_actions.find((item) => item.action === 'INCREASE_BUDGET');
  const unavailable = pending
    ? '请先核对原预算请求'
    : !ready
      ? '当前任务状态正在核对'
      : !ledgerReady
        ? '本地请求记录尚未核实'
        : !action?.enabled
          ? task.status === 'STOPPING' || task.status === 'TERMINATED'
            ? '任务正在停止或已结束'
            : action?.reason_code === 'OPERATION_IN_PROGRESS'
              ? '原启动操作正在核对'
              : '当前任务状态不能调整预算'
          : null;
  const invalid = validation(amount, reason, task.budget.limit_cny);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (unavailable || invalid || inFlight.current) return;
    void run(async () => {
      const staged = await recovery.stageIntent(path, {
        expected_state_version: task.state_version,
        new_budget_limit_cny: amount,
        reason,
      });
      if (!active.current) return;
      if (staged.kind !== 'PREPARED') {
        setNotice('已有原预算请求，请先核对。');
        await refreshOriginal();
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
        if (active.current) setCanStopWaiting(false);
      }
    });
  }

  function recoverySettled(_record: PendingSummary, result: RecoveryLookup | null, text: string) {
    if (!active.current) return;
    if (result) void run(() => apply(result));
    else {
      setNotice(text);
      void refreshOriginal().catch((failure) => setError(message(failure)));
    }
  }

  return (
    <section className="code-task-controls" aria-label="任务预算调整">
      <div className="code-task-toolbar">
        <button
          type="button"
          className="ui-button"
          ref={trigger}
          aria-expanded={open}
          aria-describedby={unavailable ? 'task-budget-state' : undefined}
          disabled={busy || unavailable !== null}
          onClick={() => (open ? closeForm() : setOpen(true))}
        >
          增加预算
        </button>
        {unavailable && (
          <span id="task-budget-state" className="read-status">
            {unavailable}
          </span>
        )}
        {pending && (
          <button
            type="button"
            className="ui-button"
            disabled={busy}
            onClick={() => void run(async () => apply(await recovery.lookup(pending.key)))}
          >
            核对原预算请求
          </button>
        )}
        {error && !ledgerReady && (
          <button
            type="button"
            className="ui-button"
            disabled={busy}
            onClick={() => void run(refreshOriginal)}
          >
            重新读取请求记录
          </button>
        )}
      </div>
      {open && (
        <form onSubmit={submit} aria-label="追加任务预算">
          <p>当前预算总额 ¥{task.budget.limit_cny}。保存新总额后，任务保留原执行状态。</p>
          <div className="code-task-toolbar">
            <label>
              新预算总额（元）{' '}
              <input
                ref={amountInput}
                value={amount}
                inputMode="decimal"
                disabled={busy || pending !== null}
                onChange={(event) => setAmount(event.target.value)}
                required
              />
            </label>
            <label>
              调整说明{' '}
              <input
                value={reason}
                disabled={busy || pending !== null}
                onChange={(event) => setReason(event.target.value)}
                required
              />
            </label>
          </div>
          {invalid && <p className="field-help">{invalid}</p>}
          <div className="code-task-toolbar">
            <button
              className="ui-button primary"
              type="submit"
              disabled={busy || unavailable !== null || invalid !== null}
              aria-busy={busy}
            >
              保存新预算
            </button>
            <button className="ui-button" type="button" disabled={busy} onClick={closeForm}>
              取消调整
            </button>
            {canStopWaiting && (
              <button className="ui-button" type="button" onClick={() => sending.current?.abort()}>
                停止等待预算结果
              </button>
            )}
          </div>
        </form>
      )}
      {notice && <p role="status">{notice}</p>}
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
      {pending && (
        <RecoveryActions
          record={pending}
          recovery={recovery}
          replayEnabled={!busy}
          settled={recoverySettled}
        />
      )}
    </section>
  );
}
