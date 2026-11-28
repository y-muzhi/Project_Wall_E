import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiRejected, ApiUnknown } from '../api/client.ts';
import type { JsonObject } from '../api/client.ts';
import type { WalleApi } from '../api/walle.ts';
import type { PendingSummary } from './command-recovery-model.ts';
import { CommandRecoveryStore, CommandStorageError } from './command-recovery-store.ts';
import type { OperationReader, RecoveryLookup } from './command-recovery.ts';

export function useCodeTaskCommand(
  api: WalleApi,
  path: string,
  saved: (data: unknown) => void,
  refresh: () => void,
  noun = '原移交',
  savedMessage = '原移交记录已保存。',
  readOperation?: OperationReader,
) {
  const recovery = useMemo(
    () =>
      api.configurationRecovery(
        new CommandRecoveryStore({ scope: api.environmentScope }),
        readOperation ??
          (async () => {
            throw Error('A synchronous Coding command has no active receipt operation');
          }),
      ),
    [api, path, readOperation],
  );
  const [pending, setPending] = useState<PendingSummary | null>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const active = useRef(false);
  const sending = useRef<AbortController | null>(null);

  const read = useCallback(async () => {
    const records = await recovery.store.list();
    if (!active.current) return;
    setPending(records.find((item) => item.path === path) ?? null);
    setReady(true);
  }, [path, recovery]);

  useEffect(() => {
    active.current = true;
    void read().catch(() => {
      if (active.current) setError('本地' + noun + '请求暂时无法读取。');
    });
    return () => {
      active.current = false;
      sending.current?.abort();
      recovery.dispose();
    };
  }, [read, recovery, noun]);

  async function apply(result: RecoveryLookup) {
    if (!active.current) return;
    const outcome = result.original_receipt?.original_outcome;
    if (outcome?.success) {
      saved(outcome.data);
      setNotice(savedMessage);
      refresh();
    } else if (outcome && !outcome.success) {
      setError(outcome.error.message);
      if (outcome.error.code === 'VERSION_CONFLICT') refresh();
    } else setNotice(noun + '请求结果待核对。');
    await read();
  }

  async function run(action: (signal: AbortSignal) => Promise<void>) {
    if (sending.current) return;
    const controller = new AbortController();
    sending.current = controller;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action(controller.signal);
    } catch (failure) {
      if (!active.current) return;
      setError(
        failure instanceof ApiRejected ||
          failure instanceof ApiUnknown ||
          failure instanceof CommandStorageError
          ? failure.message
          : '暂时无法核对' + noun + '请求。',
      );
      if (failure instanceof ApiRejected && failure.code === 'VERSION_CONFLICT') refresh();
      await read().catch(() => undefined);
    } finally {
      sending.current = null;
      if (active.current) setBusy(false);
    }
  }

  function submit(value: JsonObject) {
    if (!ready || pending) return;
    void run(async (signal) => {
      const staged = await recovery.stageIntent(path, value);
      if (!active.current) return;
      if (staged.kind === 'PREPARED') {
        setPending(staged.record);
        await apply(await recovery.send(staged.record.key, staged.record.record_revision, signal));
      } else {
        setNotice('已有' + noun + '请求，请先核对。');
        await read();
      }
    });
  }

  return {
    recovery,
    pending,
    ready,
    busy,
    error,
    notice,
    submit,
    stop: () => sending.current?.abort(),
    lookup: () => {
      if (pending) void run(async (signal) => apply(await recovery.lookup(pending.key, signal)));
    },
    observe: () => {
      if (pending?.status === 'ACCEPTED')
        void run(async (signal) => {
          await recovery.reconcileOperation(pending.key, signal);
          await read();
          refresh();
        });
    },
    reload: () => void run(read),
    settled: (_original: PendingSummary, result: RecoveryLookup | null, message: string) => {
      if (result) void run(() => apply(result));
      else
        void run(async () => {
          await read();
          setNotice(message);
        });
    },
  };
}
