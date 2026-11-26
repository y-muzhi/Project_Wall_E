import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { WalleApi } from '../api/walle.ts';
import { CommandRecoveryStore } from '../code-tasks/command-recovery-store.ts';
import type { PendingSummary } from '../code-tasks/command-recovery-model.ts';
import type { RecoveryLookup } from '../code-tasks/command-recovery.ts';
import { RecoveryActions } from '../code-tasks/settings/recovery-actions.tsx';
import { RecoveryListReader } from '../code-tasks/settings/recovery-reader.ts';

type Result = (record: PendingSummary, lookup: RecoveryLookup) => void;
export function useTestingRecovery(
  api: WalleApi,
  includes: (record: PendingSummary) => boolean,
  onResult: Result,
) {
  const listeners = useRef({ includes, onResult });
  listeners.current = { includes, onResult };
  const [access] = useState(() => {
    const store = new CommandRecoveryStore({ scope: api.environmentScope });
    const recovery = api.configurationRecovery(store, async (original, association, signal) => {
      const task = association.testing_task_id;
      if (original.owner_module !== 'TESTING' || task === null || association.task_id !== null)
        throw new TypeError('Original Testing operation has another owner');
      const { data } = await api.testingTaskOperation(task, association.operation_id, signal);
      return {
        task_id: data.task_id,
        testing_task_id: data.testing_task_id,
        operation_id: data.id,
        status: data.status,
      };
    });
    const reader = new RecoveryListReader(
      {
        store: {
          list: async () =>
            (await store.list()).filter(
              (row) => row.owner_module === 'TESTING' && listeners.current.includes(row),
            ),
        },
        lookup: (key, signal) => recovery.lookup(key, signal),
        reconcileOperation: (key, signal) => recovery.reconcileOperation(key, signal),
      },
      async (record, lookup, signal) => {
        if (!signal.aborted) listeners.current.onResult(record, lookup);
      },
    );
    return { recovery, reader };
  });
  const status = useSyncExternalStore(access.reader.subscribe, access.reader.getSnapshot);
  useEffect(() => {
    function inspect() {
      if (document.hidden) access.reader.pause();
      else void access.reader.refresh();
    }
    inspect();
    window.addEventListener('focus', inspect);
    document.addEventListener('visibilitychange', inspect);
    return () => {
      window.removeEventListener('focus', inspect);
      document.removeEventListener('visibilitychange', inspect);
      access.reader.dispose();
      access.recovery.dispose();
    };
  }, [access]);
  return {
    ...access,
    status,
    blocked(path: string) {
      if (status.error !== null || status.records === null) return '请先核对原请求存储';
      if (status.records.some((row) => row.path === path)) return '此操作的原请求尚待核对';
      return null;
    },
    settled(record: PendingSummary, lookup: RecoveryLookup | null) {
      if (lookup !== null) listeners.current.onResult(record, lookup);
      if (!document.hidden) void access.reader.refresh();
    },
  };
}

export function OriginalTaskRequests({
  access,
}: Readonly<{ access: ReturnType<typeof useTestingRecovery> }>) {
  const { status, reader, recovery, settled } = access;
  if (status.error === null && !status.records?.length) return null;
  return (
    <section className="testing-editor-panel" aria-label="独立任务原请求">
      <div className="code-settings-form-actions">
        <button
          className="ui-button"
          type="button"
          disabled={status.loading}
          title={status.loading ? '正在核对原请求' : undefined}
          onClick={() => void reader.refresh()}
        >
          核对独立任务原请求
        </button>
      </div>
      {status.error && (
        <p className="inline-error" role="alert">
          {status.error}
        </p>
      )}
      {status.records?.map((row) => (
        <div key={row.key}>
          {row.operation_id === null ? (
            <p>原请求结果待核对</p>
          ) : (
            <p>原操作 #{row.operation_id} · 待核对</p>
          )}
          {status.rowErrors[row.key] && (
            <p className="inline-error" role="alert">
              {status.rowErrors[row.key]}
            </p>
          )}
          <RecoveryActions
            record={row}
            recovery={recovery}
            replayEnabled
            settled={(record, result) => settled(record, result)}
          />
        </div>
      ))}
    </section>
  );
}
