import { useCallback, useEffect, useRef, useState } from 'react';
import { snapshotObject } from '../api/client.ts';
import type { JsonObject } from '../api/client.ts';
import { money, moneyMicro } from '../api/code-values.ts';
import { testingTaskControlPath } from '../api/testing-tasks.ts';
import type { TestingTaskView } from '../api/testing-tasks.ts';
import type { WalleApi } from '../api/walle.ts';
import { Confirmation } from '../shared/confirmation.tsx';
import { AssetSelection } from './asset-selection.tsx';
import type { AssetChoice } from './asset-selection.tsx';
import { errorText, ReadState, useTestingRead } from './plans/read.tsx';
import { testingReason } from './task-labels.ts';
import type { useTestingRecovery } from './task-recovery.tsx';

type Action = 'terminate' | 'assets' | 'budget' | 'run' | 'resume' | 'reconcile' | 'draft-plan';
const types = {
  terminate: 'TERMINATE',
  assets: 'ATTACH_ASSETS',
  budget: 'INCREASE_TEST_BUDGET',
  run: 'RUN_TEST',
  'draft-plan': 'DRAFT_PLAN',
  resume: 'RESUME',
  reconcile: 'RECONCILE',
} as const;
const labels = {
  terminate: '终止测试任务',
  assets: '绑定或重验测试资产',
  budget: '提高模型预算',
  run: '开始独立测试',
  'draft-plan': 'AI 起草计划',
  resume: '继续原测试',
  reconcile: '核对原操作',
} as const;
const descriptions = {
  terminate: '提交终止后，系统核对此测试任务的活动和收尾。已保存的事实仍可查阅。',
  assets: '固定所选计划和测试包。已绑定版本只能重验。',
  budget: '用所选独立授权调整此任务总预算，保留已发生的费用。',
  run: '按已绑定的固定来源、计划和测试包执行。可以在原操作中查看进度。',
  'draft-plan': '提交一次模型调用。系统按固定设计和材料生成草稿，并按此任务的模型预算记账。',
  resume: '在原测试中继续已核实尚未派发的步骤。',
  reconcile: '核对所选原操作的已保存状态。',
} as const;
export function textId(value: string): number | null {
  const n = Number(value);
  return /^[1-9][0-9]*$/.test(value) && Number.isSafeInteger(n) ? n : null;
}

export function TaskControls({
  api,
  task,
  access,
  stale,
  originalOperation,
  updated,
}: Readonly<{
  api: WalleApi;
  task: TestingTaskView;
  access: ReturnType<typeof useTestingRecovery>;
  stale: boolean;
  originalOperation: number | null;
  updated(action: Action, operation: number | null): void;
}>) {
  const [confirm, setConfirm] = useState<{
    action: Action;
    version: number;
    payload: JsonObject;
  } | null>(null);
  const [busy, setBusy] = useState<Action | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [assets, setAssets] = useState<AssetChoice | null>(null);
  const [authorizationText, setAuthorizationText] = useState('');
  const [budget, setBudget] = useState('');
  const [authorizationId, setAuthorizationId] = useState<number | null>(null);
  const sending = useRef(false);
  const live = useRef(false);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  const readAuthorization = useCallback(
    (signal: AbortSignal) => api.testingAuthorization(authorizationId!, signal),
    [api, authorizationId],
  );
  const approval = useTestingRead(
    'budget-authorization:' + authorizationId,
    authorizationId === null ? null : readAuthorization,
  );
  const pinned =
    task.plan_version_id !== null && task.test_pack_version_id !== null
      ? { plan: task.plan_version_id, pack: task.test_pack_version_id }
      : null;
  const chosen = pinned ?? assets;
  const grant = approval.data?.data ?? null;
  let amount: string | null = null;
  try {
    if (moneyMicro(budget) > moneyMicro(task.budget_limit_cny)) amount = money(budget);
  } catch {
    // Keep the draft while the amount is being entered.
  }
  function blocked(action: Action): string | null {
    if (busy !== null) return '正在保存原操作';
    if (stale) return '请先核对最新任务版本';
    const unready = access.blocked(testingTaskControlPath(task.id, action));
    if (unready !== null) return unready;
    const advertised = task.available_actions.find((item) => item.action === types[action]);
    if (!advertised?.enabled) return testingReason[advertised?.reason_code ?? 'TASK_STATE'];
    if (action === 'reconcile' && originalOperation === null) return '请先选择一条已核实的原操作';
    if (action === 'resume' && task.active_operation_id === null) return '此任务没有可继续的原操作';
    if (action === 'assets' && chosen === null) return '请选择固定计划和测试包';
    if (action === 'budget') {
      if (amount === null) return '请输入高于当前总预算的有效金额';
      if (
        approval.loading ||
        approval.error !== null ||
        grant === null ||
        grant.id !== textId(authorizationText)
      )
        return '请先核对新的独立授权';
      if (
        grant.scope_kind !== 'TASK' ||
        grant.status !== 'APPROVED_UNBOUND' ||
        grant.profile_version_id !== task.profile_version_id ||
        moneyMicro(grant.budget_limit_cny) < moneyMicro(amount)
      )
        return '此授权与任务配置或新总预算不匹配';
    }
    return null;
  }
  function ask(action: Action) {
    if (blocked(action) !== null) return;
    setError(null);
    const version = task.state_version;
    const payload: JsonObject = { expected_state_version: version };
    switch (action) {
      case 'assets':
        payload.plan_version_id = chosen!.plan;
        payload.test_pack_version_id = chosen!.pack;
        break;
      case 'budget':
        payload.new_budget_limit_cny = amount!;
        payload.authorization_id = grant!.id;
        break;
      case 'resume':
        payload.operation_id = task.active_operation_id!;
        break;
      case 'reconcile':
        payload.operation_id = originalOperation!;
        break;
    }
    setConfirm({ action, version, payload: snapshotObject(payload) });
  }
  async function commit() {
    if (
      confirm === null ||
      (confirm.action === 'reconcile' && confirm.payload.operation_id !== originalOperation) ||
      (confirm.action === 'resume' && confirm.payload.operation_id !== task.active_operation_id) ||
      confirm.version !== task.state_version ||
      blocked(confirm.action) !== null ||
      sending.current
    )
      return;
    const { action, payload } = confirm;
    let operation: number | null = null;
    sending.current = true;
    setBusy(action);
    setError(null);
    try {
      const original = await access.recovery.stageIntent(
        testingTaskControlPath(task.id, action),
        payload,
      );
      if (original.kind !== 'PREPARED') {
        if (live.current) setError('已有原操作，请先核对');
        return;
      }
      if (!live.current) return;
      const saved = await access.recovery.send(
        original.record.key,
        original.record.record_revision,
      );
      operation = saved.original_receipt.operation_id;
      if (live.current && action === 'budget') {
        setBudget('');
        setAuthorizationText('');
        setAuthorizationId(null);
      }
    } catch (failure) {
      if (live.current) setError(errorText(failure, '暂时无法核实原任务操作'));
    } finally {
      sending.current = false;
      if (live.current) {
        setBusy(null);
        setConfirm(null);
        updated(action, operation);
      }
    }
  }
  const terminal = task.status === 'TERMINATED' || task.status === 'COMPLETED';
  const executionActions =
    terminal || task.status === 'STOPPING'
      ? (['reconcile'] as const)
      : task.kind === 'PRODUCT'
        ? (['draft-plan', 'run', 'resume', 'reconcile'] as const)
        : (['run', 'resume', 'reconcile'] as const);
  const stopBlock = blocked('terminate'),
    assetsBlock = blocked('assets'),
    budgetBlock = blocked('budget');
  return (
    <section className="testing-editor-panel" aria-label="测试任务控制">
      <h3>任务控制</h3>
      <div className="code-settings-form-actions">
        {executionActions.map((action) => {
          const reason = blocked(action);
          return (
            <div key={action}>
              <button
                type="button"
                className="ui-button"
                disabled={reason !== null}
                title={reason ?? undefined}
                onClick={() => ask(action)}
              >
                {labels[action]}
              </button>
              {reason && <p className="read-status">{reason}</p>}
            </div>
          );
        })}
        {!terminal && (
          <div>
            <button
              type="button"
              className="ui-button"
              disabled={stopBlock !== null}
              title={stopBlock ?? undefined}
              onClick={() => ask('terminate')}
            >
              {labels.terminate}
            </button>
            {stopBlock && <p className="read-status">{stopBlock}</p>}
          </div>
        )}
      </div>
      {!terminal && task.kind === 'PRODUCT' && task.status !== 'STOPPING' && (
        <>
          <details>
            <summary>测试资产</summary>
            {pinned ? (
              <p>
                固定计划版本 #{pinned.plan} · 固定测试包 #{pinned.pack}
              </p>
            ) : (
              <AssetSelection
                key={task.design_revision_id}
                api={api}
                basis={task}
                disabled={busy !== null}
                change={setAssets}
              />
            )}
            <div className="code-settings-form-actions">
              <button
                type="button"
                className="ui-button"
                disabled={assetsBlock !== null}
                title={assetsBlock ?? undefined}
                onClick={() => ask('assets')}
              >
                {labels.assets}
              </button>
              {assetsBlock && <p className="read-status">{assetsBlock}</p>}
            </div>
          </details>
          <details>
            <summary>模型预算</summary>
            <div className="code-settings-form-actions">
              <label>
                新的预算总额（元）{' '}
                <input
                  className="ui-input"
                  inputMode="decimal"
                  value={budget}
                  onChange={(event) => setBudget(event.currentTarget.value)}
                  disabled={busy !== null}
                />
              </label>
              <label>
                已批准的独立授权编号{' '}
                <input
                  className="ui-input"
                  inputMode="numeric"
                  value={authorizationText}
                  disabled={busy !== null}
                  onChange={(event) => {
                    setAuthorizationText(event.currentTarget.value);
                    setAuthorizationId(null);
                  }}
                />
              </label>
              <button
                type="button"
                className="ui-button"
                disabled={textId(authorizationText) === null || busy !== null}
                onClick={() => {
                  if (authorizationId === textId(authorizationText)) approval.reload();
                  else setAuthorizationId(textId(authorizationText));
                }}
              >
                核对独立授权
              </button>
            </div>
            <ReadState
              loading={approval.loading}
              error={approval.error}
              stale={grant !== null}
              retry={approval.reload}
            />
            {grant && (
              <p>
                授权 #{grant.id} · 批准上限 {grant.budget_limit_cny} 元
              </p>
            )}
            <div className="code-settings-form-actions">
              <button
                type="button"
                className="ui-button"
                disabled={budgetBlock !== null}
                title={budgetBlock ?? undefined}
                onClick={() => ask('budget')}
              >
                {labels.budget}
              </button>
              {budgetBlock && <p className="read-status">{budgetBlock}</p>}
            </div>
          </details>
        </>
      )}
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
      <Confirmation
        open={confirm !== null}
        title={labels[confirm?.action ?? 'terminate']}
        description={
          confirm?.action === 'reconcile'
            ? '核对原操作 #' + confirm.payload.operation_id + ' 的已保存状态。'
            : confirm?.action === 'run'
              ? '执行固定计划版本 #' +
                task.plan_version_id +
                ' 与测试包 #' +
                task.test_pack_version_id +
                '。'
              : descriptions[confirm?.action ?? 'terminate']
        }
        busy={busy !== null}
        confirmDisabled={confirm !== null && blocked(confirm.action) !== null && busy === null}
        confirm={() => void commit()}
        cancel={() => setConfirm(null)}
      />
    </section>
  );
}
