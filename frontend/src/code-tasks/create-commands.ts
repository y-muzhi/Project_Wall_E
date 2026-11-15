import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiRejected, ApiUnknown, object } from '../api/client.ts';
import type { JsonObject } from '../api/client.ts';
import type { WalleApi } from '../api/walle.ts';
import type { RepositoryOperation } from '../api/code-repository-operations.ts';
import { CommandRecoveryStore, CommandStorageError } from './command-recovery-store.ts';
import type { PendingSummary } from './command-recovery-model.ts';
import type { RecoveryLookup } from './command-recovery.ts';
import type { CreateTaskDraft } from './create-draft.ts';
import { createTaskPath } from './create-draft.ts';
import { safeId } from './list-model.ts';

export type CreationRef = Readonly<{ key: string; path: string }>;

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiRejected ||
    error instanceof ApiUnknown ||
    error instanceof CommandStorageError
    ? error.message
    : fallback;
}

export function useCreationCommands(
  api: WalleApi,
  draft: CreateTaskDraft,
  update: (change: Partial<CreateTaskDraft>) => void,
  created: (id: number, key: string) => void,
  conflict: (id: number) => void,
) {
  const store = useMemo(() => new CommandRecoveryStore(), []);
  const recovery = useMemo(
    () =>
      api.configurationRecovery(store, async (original, association, signal) => {
        const operation = (await api.repositoryOperation(association.operation_id, signal)).data;
        if (
          operation.idempotency_key !== original.key ||
          operation.resource_id !== original.parameters.id ||
          (original.decoder_kind === 'APP-CODE-CMD-C02' &&
            operation.operation_type !== 'REFRESH_REPOSITORY') ||
          (original.decoder_kind === 'APP-CODE-CMD-C05' &&
            operation.operation_type !== 'REGISTER_BASE')
        )
          throw Error('Original repository operation does not match');
        return {
          operation_id: operation.id,
          task_id: null,
          testing_task_id: null,
          status: operation.status,
        };
      }),
    [api, store],
  );
  const [record, setRecord] = useState<PendingSummary | null>(null);
  const [ledgerReady, setLedgerReady] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [operation, setOperation] = useState<RepositoryOperation | null>(null);
  const [busy, setBusy] = useState(false);
  const gate = useRef(false);
  const mounted = useRef(true);
  const current = useRef({ draft, update, created, conflict });
  current.current = { draft, update, created, conflict };
  const updateDraft = useCallback((change: Partial<CreateTaskDraft>) => {
    current.current.draft = { ...current.current.draft, ...change };
    current.current.update(change);
  }, []);

  const lookupLocal = useCallback(async () => {
    const records = await store.list();
    if (!mounted.current) return;
    const input = current.current.draft;
    const pending =
      records.find((item) =>
        input.original_key
          ? item.key === input.original_key && item.path === input.original_path
          : item.path === createTaskPath(input.document_id),
      ) ?? null;
    setRecord(pending);
    setLedgerReady(true);
    if (pending && input.original_key === null)
      updateDraft({ original_key: pending.key, original_path: pending.path });
  }, [store, updateDraft]);

  useEffect(() => {
    mounted.current = true;
    void lookupLocal().catch((error) => {
      if (mounted.current) setMessage(errorMessage(error, '无法读取本地请求记录'));
    });
    return () => {
      mounted.current = false;
      recovery.dispose();
    };
  }, [lookupLocal, recovery]);

  const applyResult = useCallback(
    async (ref: CreationRef, result: RecoveryLookup) => {
      if (!mounted.current || current.current.draft.original_key !== ref.key) return;
      const local = result.local;
      const receipt = result.original_receipt;
      const outcome = receipt?.original_outcome;
      if (outcome && !outcome.success && outcome.error.code === 'ACTIVE_TASK_EXISTS') {
        const id = object(outcome.error.details).task_id;
        if (safeId(id)) current.current.conflict(id);
      }
      if (ref.path === createTaskPath(current.current.draft.document_id)) {
        const id = receipt?.task_id ?? local?.task_id;
        if (
          safeId(id) &&
          (receipt?.original_http_status === 201 ||
            (local &&
              'final_state' in local &&
              local.final_state === 'CONFIRMED' &&
              local.http_status === 201))
        ) {
          current.current.created(id, ref.key);
          return;
        }
      } else if (ref.path === '/api/v1/code-authorizations' && outcome?.success) {
        const id = object(outcome.data).resource_id;
        if (!safeId(id)) throw Error('Original approved authorization is missing');
        updateDraft({ authorization_id: id, original_key: null, original_path: null });
        setMessage('授权已批准，任务创建后等待应用。');
      } else {
        const operationId = receipt?.operation_id ?? local?.operation_id;
        if (safeId(operationId)) {
          const found = (await api.repositoryOperation(operationId)).data;
          if (!mounted.current || current.current.draft.original_key !== ref.key) return;
          const repositoryId = current.current.draft.repository_id;
          const refresh = ref.path === '/api/v1/code-repositories/' + repositoryId + '/refresh';
          const baseline = ref.path === '/api/v1/code-repositories/' + repositoryId + '/snapshots';
          if (
            found.resource_id !== repositoryId ||
            found.idempotency_key !== ref.key ||
            (refresh
              ? found.operation_type !== 'REFRESH_REPOSITORY'
              : !baseline || found.operation_type !== 'REGISTER_BASE')
          )
            throw Error('Original repository operation differs');
          setOperation(found);
          if (['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(found.status)) {
            await recovery.reconcileOperation(ref.key);
            if (!mounted.current || current.current.draft.original_key !== ref.key) return;
          }
          if (found.status === 'SUCCEEDED') {
            const final = found.steps.at(-1)?.result_ref;
            const id = final?.[refresh ? 'observation_id' : 'snapshot_id'];
            if (!safeId(id)) throw Error('Missing confirmed repository result');
            updateDraft(
              refresh
                ? {
                    observation_id: id,
                    target_branch: null,
                    original_key: null,
                    original_path: null,
                  }
                : { base_snapshot_id: id, original_key: null, original_path: null },
            );
            setMessage(refresh ? '已读取本次仓库信息。' : '固定代码起点已登记。');
          } else if (found.status === 'FAILED' || found.status === 'CANCELLED') {
            updateDraft({ original_key: null, original_path: null });
            setMessage(
              found.status === 'CANCELLED'
                ? '原仓库操作已取消。'
                : '原仓库操作失败，请检查来源后重试。',
            );
          } else {
            setMessage(
              found.status === 'UNKNOWN'
                ? '原仓库操作结果待核对。'
                : '已接收，正在核对原仓库操作。',
            );
            await lookupLocal();
            return;
          }
        }
      }
      if (current.current.draft.original_key === ref.key && local && 'final_state' in local) {
        updateDraft({ original_key: null, original_path: null });
        setMessage(
          outcome && !outcome.success
            ? outcome.error.message
            : local.final_state === 'CONFIRMED'
              ? '原操作已完成，请重新读取选择。'
              : '原请求已结束。',
        );
      } else if (current.current.draft.original_key === ref.key && !operation)
        setMessage(outcome && !outcome.success ? outcome.error.message : '原请求结果待核对。');
      await lookupLocal();
    },
    [api, lookupLocal, operation, recovery, updateDraft],
  );

  async function run(work: () => Promise<void>) {
    if (gate.current) return;
    gate.current = true;
    setBusy(true);
    try {
      await work();
    } catch (error) {
      if (!mounted.current) return;
      if (error instanceof ApiRejected && error.code === 'ACTIVE_TASK_EXISTS') {
        const id = object(error.details).task_id;
        if (safeId(id)) current.current.conflict(id);
      }
      const { original_key: key, original_path: path } = current.current.draft;
      if (error instanceof ApiRejected && key && path) {
        try {
          const result = await recovery.lookup(key);
          if (result.local && 'final_state' in result.local)
            await applyResult({ key, path }, result);
        } catch {
          // An unconfirmed command remains linked to the original input.
        }
      }
      if (!mounted.current) return;
      setMessage(errorMessage(error, '操作结果暂不可确认，请核对原请求。'));
      await lookupLocal().catch(() => undefined);
    } finally {
      gate.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  function submit(path: string, body: JsonObject) {
    if (!ledgerReady || current.current.draft.original_key) return;
    return run(async () => {
      const staged = await recovery.stageIntent(path, body);
      if (!mounted.current) return;
      if (staged.kind !== 'PREPARED') {
        setMessage('已有同范围原请求，请先核对。');
        await lookupLocal();
        return;
      }
      const key = staged.record.key;
      updateDraft({ original_key: key, original_path: path });
      setRecord(staged.record);
      const result = await recovery.send(key, staged.record.record_revision);
      await applyResult({ key, path }, result);
    });
  }

  function check() {
    const { original_key: key, original_path: path } = current.current.draft;
    if (!key || !path) return;
    return run(async () => {
      await applyResult({ key, path }, await recovery.lookup(key));
      await lookupLocal();
    });
  }

  const canObserveBaseline =
    record?.decoder_kind === 'APP-CODE-CMD-C05' &&
    record.status === 'ACCEPTED' &&
    operation?.status === 'UNKNOWN' &&
    record.key === operation.idempotency_key &&
    record.key === draft.original_key &&
    operation.steps[1]?.step_type === 'PIN_COMMIT' &&
    operation.steps[1].status === 'UNKNOWN' &&
    operation.steps.slice(2).every((step) => step.status === 'PENDING');

  function observeBaseline() {
    if (!canObserveBaseline || !record || record.key !== current.current.draft.original_key) return;
    const original = record;
    return run(async () => {
      const result = await recovery.observeBaselineOriginal(original.key, original.record_revision);
      await applyResult({ key: original.key, path: original.path }, result);
    });
  }

  function settled(original: PendingSummary, result: RecoveryLookup | null, text: string) {
    if (!mounted.current) return;
    setMessage(text);
    if (result) void run(() => applyResult({ key: original.key, path: original.path }, result));
    else void lookupLocal().catch(() => undefined);
  }
  return {
    recovery,
    record,
    operation,
    ledgerReady,
    busy,
    message,
    submit,
    check,
    settled,
    canObserveBaseline,
    observeBaseline,
  };
}
