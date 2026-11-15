import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiRejected, positiveInteger } from '../../api/client.ts';
import { testingPackSealPath } from '../../api/testing-assets.ts';
import type { TestPack, TestingSealReceipt } from '../../api/testing-assets.ts';
import type { TestPlanVersion } from '../../api/testing-plans.ts';
import type { WalleApi } from '../../api/walle.ts';
import type { CommandRecovery } from '../../code-tasks/command-recovery.ts';
import { useSettingsVisibility } from '../../code-tasks/settings/read.ts';
import { Confirmation } from '../../shared/confirmation.tsx';
import { errorText, ReadState, useTestingRead } from './read.tsx';

const stepLabels = {
  VALIDATE_PLAN: '核对固定计划',
  COMPILE: '编译测试用例',
  SEAL: '封存原测试资源',
  SAVE_PACK: '保存封存版本',
} as const;
const stateLabels = {
  PENDING: '等待处理',
  RUNNING: '处理中',
  SUCCEEDED: '已完成',
  FAILED: '失败',
} as const;
const failureLabels = {
  INVALID_STATE: '测试包或计划的状态已变化',
  CONFIG_NOT_READY: '所需编译资源尚未就绪',
  CHECK_CONFIGURATION_INVALID: '固定用例无法编译',
  CONTENT_NOT_READY: '固定资源无法读取或已变化',
  TEST_ASSET_REVOKED: '所属计划或测试包已撤销',
} as const;

function sessionOperation(pack: number, version: number): number {
  try {
    const value = sessionStorage.getItem('walle:testing-seal:' + version + ':' + pack);
    return value === null ? 0 : positiveInteger(Number(value));
  } catch {
    return 0;
  }
}

export function PackSeal({
  api,
  pack,
  plan,
  recovery,
  unavailable,
  recovered,
  refresh,
}: Readonly<{
  api: WalleApi;
  pack: TestPack;
  plan: TestPlanVersion;
  recovery: CommandRecovery;
  unavailable: string | null;
  recovered: number | undefined;
  refresh(): void;
}>) {
  const visible = useSettingsVisibility();
  const live = useRef(false);
  const sending = useRef(false);
  const terminal = useRef<number | null>(null);
  const [confirm, setConfirm] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accepted, setAccepted] = useState(() => sessionOperation(pack.id, plan.id));
  const operationId = Math.max(accepted, recovered ?? 0);
  const read = useCallback(
    (signal: AbortSignal) => api.testingSeal(pack.id, operationId, signal),
    [api, pack.id, operationId],
  );
  const operation = useTestingRead(
    'seal:' + pack.id + ':' + operationId,
    operationId > 0 ? read : null,
  );
  const state = operation.data?.data.status;
  const unfinished = operationId > 0 && state !== 'FAILED' && state !== 'SUCCEEDED';
  const blocked = busy
    ? '正在提交原封存请求'
    : unfinished
      ? '原封存操作尚待核实'
      : (unavailable ??
        (plan.status !== 'PUBLISHED'
          ? '所属计划已撤销或尚未发布'
          : plan.cases.length === 0
            ? '固定计划没有可封存的受控用例'
            : pack.reason_codes.includes('Q20-CHECKS')
              ? '独立编译资源尚未登记'
              : null));
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  useEffect(() => {
    if (operationId === 0) return;
    try {
      sessionStorage.setItem('walle:testing-seal:' + plan.id + ':' + pack.id, String(operationId));
    } catch {
      // The durable command record still guards the original acceptance.
    }
  }, [operationId, pack.id, plan.id]);
  useEffect(() => {
    if (!visible || !unfinished || operation.loading || operation.error !== null) return;
    const tick = window.setTimeout(operation.reload, 1100);
    return () => window.clearTimeout(tick);
  }, [unfinished, visible, operation.loading, operation.error, operation.reload]);
  useEffect(() => {
    if (
      operationId > 0 &&
      (state === 'SUCCEEDED' || state === 'FAILED') &&
      terminal.current !== operationId
    ) {
      terminal.current = operationId;
      refresh();
    }
  }, [operationId, state, refresh]);
  async function seal() {
    if (confirm === null || confirm !== pack.state_version || blocked !== null || sending.current)
      return;
    const expected = confirm;
    sending.current = true;
    setBusy(true);
    setError(null);
    try {
      const original = await recovery.stageIntent(testingPackSealPath(pack.id), {
        expected_state_version: expected,
      });
      if (original.kind !== 'PREPARED') {
        if (live.current) setError('已有原封存请求，请先核对');
        return;
      }
      if (!live.current) return;
      const result = await recovery.send(original.record.key, original.record.record_revision);
      if (!live.current) return;
      const receipt = result.response.data as TestingSealReceipt;
      setAccepted(positiveInteger(receipt.operation_id));
    } catch (failure) {
      if (!live.current) return;
      if (failure instanceof ApiRejected && failure.code === 'OPERATION_IN_PROGRESS') {
        const id = failure.details?.related_operation_id;
        if (typeof id === 'number' && Number.isSafeInteger(id) && id > 0) setAccepted(id);
      }
      setError(errorText(failure, '暂时无法核实原封存请求'));
    } finally {
      sending.current = false;
      if (live.current) {
        setBusy(false);
        setConfirm(null);
        refresh();
      }
    }
  }
  if (pack.status !== 'DRAFT' && operationId === 0) return null;
  return (
    <section className="testing-editor-panel" aria-label="测试包封存">
      {pack.status === 'DRAFT' && (
        <div className="code-settings-form-actions">
          <button
            className="ui-button"
            type="button"
            disabled={blocked !== null}
            title={blocked ?? undefined}
            onClick={() => {
              setError(null);
              setConfirm(pack.state_version);
            }}
          >
            编译并封存测试包
          </button>
          {blocked && <p className="read-status">{blocked}</p>}
        </div>
      )}
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
      {operationId > 0 && (
        <>
          <h4>原封存操作 #{operationId}</h4>
          <ReadState
            loading={operation.loading}
            error={operation.error}
            stale={operation.data !== null}
            retry={operation.reload}
          />
          {operation.data && (
            <>
              <p role="status">{stateLabels[operation.data.data.status]}</p>
              {operation.data.data.failure_code && (
                <p role="alert">{failureLabels[operation.data.data.failure_code]}</p>
              )}
              <ol>
                {operation.data.data.steps.map((step) => (
                  <li key={step.step_no}>
                    {stepLabels[step.step_type]} · {stateLabels[step.status]}
                  </li>
                ))}
              </ol>
            </>
          )}
        </>
      )}
      <Confirmation
        open={confirm !== null}
        title="编译并封存测试包"
        description="根据固定计划和登记资源生成测试包。封存后须单独完成有效性验证，才能发布测试包。"
        busy={busy}
        confirmLabel="确认封存"
        confirmDisabled={blocked !== null && !busy}
        confirm={() => void seal()}
        cancel={() => setConfirm(null)}
      />
    </section>
  );
}
