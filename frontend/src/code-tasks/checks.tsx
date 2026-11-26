import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiRejected, ApiUnknown } from '../api/client.ts';
import type { CodeTaskView } from '../api/code-task-creation.ts';
import { candidateCheckPath, captureCheckPath } from '../api/code-task-checks.ts';
import type { CodeTaskOperation } from '../api/code-task-operations.ts';
import type { WalleApi } from '../api/walle.ts';
import { Confirmation } from '../shared/confirmation.tsx';
import { EmptyState } from '../shared/empty-state.tsx';
import type { PendingSummary } from './command-recovery-model.ts';
import { CommandRecoveryStore, CommandStorageError } from './command-recovery-store.ts';
import type { RecoveryLookup } from './command-recovery.ts';
import { RecoveryActions } from './settings/recovery-actions.tsx';
import { useSettingsRead } from './settings/read.ts';
import { VerificationHistory } from './verification-history.tsx';

type Props = Readonly<{
  api: WalleApi;
  task: CodeTaskView;
  visible: boolean;
  ready: boolean;
  changed(): void;
  selectVerification(id: number): void;
  page: number;
  selectPage(page: number): void;
}>;

const titles = { CAPTURE_AND_CHECK: '固定代码并自检', VERIFY_CANDIDATE: '重新自检' } as const;
type CheckAction = keyof typeof titles;
type Intent = Readonly<{ action: CheckAction; version: number; candidate: number | null }>;

const disabledReasons = {
  TASK_STATE: '当前任务状态不允许此操作',
  ROLE_CHAIN_INCOMPLETE: '当前角色的交接记录尚未核实',
  ROLE_CHAIN_UNKNOWN: '原角色交接结果待核对',
  SESSION_NOT_CURRENT: '当前执行会话尚未核实',
  WRITER_ACTIVE: '原执行或检查活动尚未核清',
  RESOURCE_NOT_READY: '开发自检资源尚未就绪',
  CANDIDATE_NOT_CURRENT: '尚无可重查的当前固定代码',
} as const;

function isCheck(operation: { operation_type: string }) {
  return (
    operation.operation_type === 'CAPTURE_AND_CHECK' ||
    operation.operation_type === 'VERIFY_CANDIDATE'
  );
}

function terminal(operation: CodeTaskOperation) {
  return ['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(operation.status);
}

function operationDelay(result: { data: CodeTaskOperation }) {
  if (terminal(result.data)) return null;
  return result.data.status === 'UNKNOWN' ? 3000 : 1000;
}

function failureMessage(error: unknown) {
  return error instanceof ApiRejected ||
    error instanceof ApiUnknown ||
    error instanceof CommandStorageError
    ? error.message
    : '无法核对原开发自检请求。';
}

function operationMessage(operation: CodeTaskOperation) {
  switch (operation.status) {
    case 'PENDING':
      return '原请求已接收，等待核对检查条件。';
    case 'RUNNING':
      return operation.steps.some((step) => step.step_type === 'CHECK' && step.status === 'RUNNING')
        ? '正在执行开发自检。'
        : '正在核对固定检查输入。';
    case 'UNKNOWN':
      return '原检查结果待核对，现有操作保留。';
    case 'SUCCEEDED':
      return '开发自检结果已保存，请查看各项结果。';
    case 'CANCELLED':
      return '原检查操作已取消。';
    case 'FAILED':
      return operation.failure_code === 'EVIDENCE_INCOMPLETE'
        ? '未能形成完整检查证据。'
        : '原操作失败，请核对固定代码和检查条件。';
  }
}

export function TaskChecks({
  api,
  task,
  visible,
  ready,
  changed,
  selectVerification,
  page,
  selectPage,
}: Props) {
  const taskId = task.id;
  const candidate = task.current_candidate_id;
  const capturePath = captureCheckPath(taskId);
  const recovery = useMemo(
    () =>
      api.configurationRecovery(
        new CommandRecoveryStore({ scope: api.environmentScope }),
        async (original, link, signal) => {
          if (
            (original.decoder_kind !== 'APP-CODE-CMD-C50' &&
              original.decoder_kind !== 'APP-CODE-CMD-C51') ||
            original.parameters.task_id !== taskId ||
            link.task_id !== taskId
          )
            throw Error('Original check belongs to another task');
          const { data } = await api.codeTaskOperation(taskId, link.operation_id, signal);
          const same =
            original.decoder_kind === 'APP-CODE-CMD-C50'
              ? data.operation_type === 'CAPTURE_AND_CHECK'
              : data.operation_type === 'VERIFY_CANDIDATE' &&
                data.fixed_input.candidate_id === original.parameters.candidate_id;
          if (!same || data.idempotency_key !== original.key) throw Error('Original check differs');
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
  const [ledgerReady, setLedgerReady] = useState(false);
  const [localOperation, setLocalOperation] = useState<number | null>(null);
  const [confirm, setConfirm] = useState<Intent | null>(null);
  const [busy, setBusy] = useState(false);
  const [sending, setSending] = useState(false);
  const [retry, setRetry] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const mounted = useRef(false);
  const inFlight = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const settledOperation = useRef<number | null>(null);

  const readPending = useCallback(async () => {
    const rows = await recovery.store.list();
    if (!mounted.current) return;
    const original =
      rows.find(
        (row) =>
          (row.decoder_kind === 'APP-CODE-CMD-C50' && row.path === capturePath) ||
          (row.decoder_kind === 'APP-CODE-CMD-C51' &&
            row.path.startsWith(capturePath + '/') &&
            row.path.endsWith('/verifications')),
      ) ?? null;
    setPending(original);
    if (original?.operation_id != null) setLocalOperation(original.operation_id);
    setLedgerReady(true);
  }, [recovery, capturePath]);

  useEffect(() => {
    mounted.current = true;
    void readPending().catch((failure: unknown) => {
      if (mounted.current) setError(failureMessage(failure));
    });
    return () => {
      mounted.current = false;
      controller.current?.abort();
      recovery.dispose();
    };
  }, [readPending, recovery]);

  const active = task.active_operations.find(isCheck);
  const identity = active?.id ?? pending?.operation_id ?? localOperation;
  const loadOperation = useCallback(
    async (signal: AbortSignal) => {
      void retry;
      if (identity === null) throw Error('No original check selected');
      const result = await api.codeTaskOperation(taskId, identity, signal);
      if (!isCheck(result.data)) throw Error('Original operation type differs');
      return result;
    },
    [api, taskId, identity, retry],
  );
  const observed = useSettingsRead(
    loadOperation,
    visible && identity !== null,
    '暂时无法读取自检进度',
    operationDelay,
  );
  const operation = observed.value?.data.id === identity ? observed.value.data : null;

  useEffect(() => {
    if (!operation || !terminal(operation) || settledOperation.current === operation.id) return;
    const reading = new AbortController();
    async function settle(original: CodeTaskOperation) {
      if (pending?.operation_id === original.id && pending.status === 'ACCEPTED') {
        await recovery.reconcileOperation(pending.key, reading.signal);
        if (!reading.signal.aborted) await readPending();
      }
      if (!reading.signal.aborted) {
        settledOperation.current = original.id;
        changed();
      }
    }
    void settle(operation).catch((failure: unknown) => {
      if (!reading.signal.aborted) setError(failureMessage(failure));
    });
    return () => reading.abort();
  }, [operation, pending, recovery, readPending, changed]);

  async function run(work: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await work();
    } catch (failure) {
      if (mounted.current) {
        setError(failureMessage(failure));
        await readPending().catch(() => undefined);
        if (failure instanceof ApiRejected && failure.code === 'VERSION_CONFLICT') changed();
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  async function apply(result: RecoveryLookup) {
    if (!mounted.current) return;
    const accepted = result.original_receipt?.operation_id ?? result.local?.operation_id;
    const original = result.original_receipt?.original_outcome;
    if (accepted != null) {
      setLocalOperation(accepted);
      setNotice('自检请求已接收，正在核对原操作。');
      changed();
    } else if (original && !original.success) {
      setError(original.error.message);
      if (original.error.code === 'VERSION_CONFLICT') changed();
    } else if (result.local && 'final_state' in result.local) {
      setNotice('原自检请求已结束。');
    } else setNotice('原自检请求结果待核对。');
    await readPending();
  }

  function reason(action: CheckAction) {
    if (active) return active.status === 'UNKNOWN' ? '原自检结果待核对' : '原自检操作正在处理';
    if (pending) return '请先核对原自检请求';
    if (!ready) return '当前任务状态正在核对';
    if (!ledgerReady) return '本地请求记录尚未核实';
    const purpose = task.verification_purposes.find((item) => item.action === action);
    const actionAvailable = task.available_actions.some(
      (item) => item.action === action && item.enabled,
    );
    if (action === 'VERIFY_CANDIDATE' && candidate === null) return '尚无可重查的当前固定代码';
    if (purpose?.enabled && actionAvailable) return null;
    return purpose?.reason_code ? disabledReasons[purpose.reason_code] : '当前阶段未开放此操作';
  }

  const confirmationCurrent =
    confirm !== null &&
    confirm.version === task.state_version &&
    (confirm.action === 'CAPTURE_AND_CHECK' || confirm.candidate === candidate) &&
    reason(confirm.action) === null;

  function submit() {
    if (!confirmationCurrent || !confirm || inFlight.current) return;
    const intent = confirm;
    const path =
      intent.action === 'CAPTURE_AND_CHECK'
        ? capturePath
        : intent.candidate === null
          ? null
          : candidateCheckPath(taskId, intent.candidate);
    if (path === null) return;
    setConfirm(null);
    void run(async () => {
      const stage = await recovery.stageIntent(path, {
        purpose: 'HANDOFF',
        expected_state_version: intent.version,
      });
      if (!mounted.current) return;
      if (stage.kind !== 'PREPARED') {
        setNotice('已有原自检请求，请先核对。');
        await readPending();
        return;
      }
      setPending(stage.record);
      const sendingController = new AbortController();
      controller.current = sendingController;
      setSending(true);
      try {
        await apply(
          await recovery.send(
            stage.record.key,
            stage.record.record_revision,
            sendingController.signal,
          ),
        );
      } finally {
        controller.current = null;
        if (mounted.current) setSending(false);
      }
    });
  }

  function recovered(_original: PendingSummary, result: RecoveryLookup | null, detail: string) {
    if (result) void run(() => apply(result));
    else
      void run(async () => {
        setNotice(detail);
        await readPending();
      });
  }

  return (
    <section className="code-task-result" aria-label="开发自检">
      <h2>开发自检</h2>
      <div className="code-task-toolbar">
        {(Object.keys(titles) as CheckAction[]).map((action) => {
          const disabled = reason(action);
          const id = 'coding-check-' + taskId + '-' + action;
          return (
            <div key={action} className="code-check-action">
              <button
                className="ui-button"
                type="button"
                disabled={busy || disabled !== null}
                aria-describedby={disabled ? id : undefined}
                onClick={() => setConfirm({ action, version: task.state_version, candidate })}
              >
                {titles[action]}
              </button>
              {disabled && (
                <span className="field-help" id={id}>
                  {disabled}
                </span>
              )}
            </div>
          );
        })}
        {pending && (
          <button
            className="ui-button"
            type="button"
            disabled={busy}
            onClick={() => void run(async () => apply(await recovery.lookup(pending.key)))}
          >
            核对原自检请求
          </button>
        )}
        {sending && (
          <button className="ui-button" type="button" onClick={() => controller.current?.abort()}>
            停止等待自检响应
          </button>
        )}
        {identity !== null && observed.error && (
          <button className="ui-button" type="button" onClick={() => setRetry((n) => n + 1)}>
            重试读取原操作
          </button>
        )}
        {!ledgerReady && error && (
          <button
            className="ui-button"
            type="button"
            disabled={busy}
            onClick={() => void run(readPending)}
          >
            重读本地请求记录
          </button>
        )}
      </div>
      {(operation || notice) && (
        <p role="status">{operation ? operationMessage(operation) : notice}</p>
      )}
      {(error || observed.error) && (
        <p className="inline-error" role="alert">
          {error ?? observed.error}
        </p>
      )}
      {pending && (
        <RecoveryActions
          record={pending}
          recovery={recovery}
          replayEnabled={
            !busy &&
            ready &&
            (pending.path === capturePath ||
              (candidate !== null && pending.path === candidateCheckPath(taskId, candidate)))
          }
          settled={recovered}
        />
      )}
      {candidate === null ? (
        <EmptyState icon="outline" message="当前没有固定代码的开发自检记录" />
      ) : (
        <VerificationHistory
          key={candidate}
          api={api}
          taskId={taskId}
          candidateId={candidate}
          currentVerificationId={task.current_refs.verification_id}
          visible={visible}
          onSelect={selectVerification}
          selectedPage={page}
          selectPage={selectPage}
        />
      )}
      <Confirmation
        open={confirm !== null}
        busy={busy}
        title={confirm ? titles[confirm.action] : '开发自检'}
        description={
          confirm?.action === 'VERIFY_CANDIDATE'
            ? '使用当前固定代码和已采用配置重新检查。'
            : '固定当前代码并执行本阶段已登记的开发自检。'
        }
        confirmLabel={confirm?.action === 'VERIFY_CANDIDATE' ? '确认重新自检' : '确认固定并自检'}
        confirmDisabled={!confirmationCurrent}
        confirm={submit}
        cancel={() => setConfirm(null)}
      />
    </section>
  );
}
