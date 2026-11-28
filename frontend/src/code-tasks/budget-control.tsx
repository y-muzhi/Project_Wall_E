import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiRejected, ApiUnknown } from '../api/client.ts';
import { taskBudgetPath } from '../api/code-task-budget.ts';
import type { WalleApi } from '../api/walle.ts';
import { CommandRecoveryStore, CommandStorageError } from './command-recovery-store.ts';
import type { PendingSummary } from './command-recovery-model.ts';
import type { RecoveryLookup } from './command-recovery.ts';
import { RecoveryActions } from './settings/recovery-actions.tsx';

function errorMessage(error: unknown) {
  if (
    error instanceof ApiRejected ||
    error instanceof ApiUnknown ||
    error instanceof CommandStorageError
  )
    return error.message;
  return '暂时无法核对原预算请求。';
}

export function LegacyTaskBudgetRecovery({
  api,
  taskId,
  changed,
}: Readonly<{
  api: WalleApi;
  taskId: number;
  changed(): void;
}>) {
  const path = taskBudgetPath(taskId);
  const recovery = useMemo(
    () =>
      api.configurationRecovery(
        new CommandRecoveryStore({ scope: api.environmentScope }),
        async () => {
          throw Error('Budget changes do not produce a background operation');
        },
      ),
    [api],
  );
  const [pending, setPending] = useState<PendingSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const active = useRef(false);
  const lookingUp = useRef(false);

  const readOriginal = useCallback(async () => {
    const records = await recovery.store.list();
    if (active.current) setPending(records.find((record) => record.path === path) ?? null);
  }, [path, recovery]);

  useEffect(() => {
    active.current = true;
    void readOriginal().catch((failure) => {
      if (active.current) setError(errorMessage(failure));
    });
    return () => {
      active.current = false;
      recovery.dispose();
    };
  }, [readOriginal, recovery]);

  async function adopt(result: RecoveryLookup | null, fallback: string) {
    if (!active.current) return;
    const outcome = result?.original_receipt?.original_outcome;
    const local = result?.local;
    if (
      outcome?.success ||
      (local && 'final_state' in local && local.final_state === 'CONFIRMED')
    ) {
      setNotice('已核实原预算请求结果。');
      changed();
    } else if (outcome && !outcome.success) {
      setError(outcome.error.message);
      if (outcome.error.code === 'VERSION_CONFLICT') changed();
    } else {
      setNotice(fallback);
    }
    await readOriginal();
  }

  async function lookup() {
    if (lookingUp.current) return;
    lookingUp.current = true;
    setBusy(true);
    setError(null);
    try {
      if (pending) await adopt(await recovery.lookup(pending.key), '原请求结果仍待核对。');
      else await readOriginal();
    } catch (failure) {
      if (active.current) setError(errorMessage(failure));
    } finally {
      lookingUp.current = false;
      if (active.current) setBusy(false);
    }
  }

  if (!pending && !notice && !error) return null;
  return (
    <section className="code-task-controls" aria-label="历史预算请求">
      {(pending || error) && (
        <button type="button" className="ui-button" disabled={busy} onClick={() => void lookup()}>
          {pending ? '核对原预算请求' : '重新读取请求记录'}
        </button>
      )}
      {notice && <p role="status">{notice}</p>}
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      {pending && (
        <RecoveryActions
          record={pending}
          recovery={recovery}
          replayEnabled={!busy}
          settled={(_record, result, message) => {
            void adopt(result, message).catch((failure) => {
              if (active.current) setError(errorMessage(failure));
            });
          }}
        />
      )}
    </section>
  );
}
