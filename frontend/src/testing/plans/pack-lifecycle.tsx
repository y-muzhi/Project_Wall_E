import { useCallback, useEffect, useRef, useState } from 'react';
import { positiveInteger, snapshotObject } from '../../api/client.ts';
import type { JsonObject } from '../../api/client.ts';
import { testingPackControlPath } from '../../api/testing-assets.ts';
import type {
  TestPack,
  TestingReferenceSet,
  TestingValidationReceipt,
} from '../../api/testing-assets.ts';
import type { TestPlanVersion } from '../../api/testing-plans.ts';
import type { WalleApi } from '../../api/walle.ts';
import type { CommandRecovery } from '../../code-tasks/command-recovery.ts';
import { optionPage, PagedTaskSelect } from '../../code-tasks/create-selection.tsx';
import { useSettingsVisibility } from '../../code-tasks/settings/read.ts';
import { Confirmation } from '../../shared/confirmation.tsx';
import { EmptyState } from '../../shared/empty-state.tsx';
import { testingStatus } from '../task-labels.ts';
import { textId } from '../task-controls.tsx';
import { errorText, ReadState, useTestingRead } from './read.tsx';
import { ReferenceSets } from './reference-sets.tsx';

type Action = 'validations' | 'publish' | 'revoke';
const titles = { validations: '验证测试包有效性', publish: '发布测试包', revoke: '撤销测试包' };
const descriptions = {
  validations: '对固定参考样本及缺陷对照执行预登记的完整重复序列。',
  publish: '采用该封存包同一摘要下的完整有效性验证，发布供产品测试选择。',
  revoke: '撤销此测试包的使用资格，保留原内容、验证和报告。',
};
const resultNames = {
  PENDING: '待处理',
  RUNNING: '验证中',
  PASSED: '已通过',
  FAILED: '未通过',
  UNAVAILABLE: '资源不可用',
  UNKNOWN: '结果待核对',
};

export function PackLifecycle({
  api,
  pack,
  plan,
  validationId,
  recovery,
  unavailable,
  pending,
  select,
  openTask,
  refresh,
}: Readonly<{
  api: WalleApi;
  pack: TestPack;
  plan: TestPlanVersion;
  validationId: number | null;
  recovery: CommandRecovery;
  unavailable: string | null;
  pending(path: string): string | null;
  select(id: number | null): void;
  openTask(id: number): void;
  refresh(): void;
}>) {
  const visible = useSettingsVisibility();
  const live = useRef(false),
    sending = useRef(false);
  const [reason, setReason] = useState(''),
    [reference, setReference] = useState<TestingReferenceSet | null>(null);
  const [profileId, setProfileId] = useState<number | null>(null);
  const [approvalText, setApprovalText] = useState('');
  const [approvalId, setApprovalId] = useState<number | null>(null);
  const [viewText, setViewText] = useState('');
  const [busy, setBusy] = useState<Action | null>(null),
    [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<{
    action: Action;
    version: number;
    body: JsonObject;
  } | null>(null);
  const selected = validationId ?? pack.validation_id;
  const readValidation = useCallback(
    (signal: AbortSignal) => api.testingValidation(pack.id, selected!, signal),
    [api, pack.id, selected],
  );
  const validation = useTestingRead(
    'pack-validation:' + pack.id + ':' + selected,
    selected === null ? null : readValidation,
  );
  const profiles = useCallback(
    async (page: number, signal: AbortSignal) =>
      optionPage(await api.testingProfiles(page, null, signal), (row) => ({
        id: row.id,
        label: row.name + ' · 版本 ' + row.version + (row.ready ? '' : ' · 执行未准入'),
      })),
    [api],
  );
  const readProfile = useCallback(
    (signal: AbortSignal) => api.testingProfile(profileId!, signal),
    [api, profileId],
  );
  const profile = useTestingRead(
    'validation-profile:' + profileId,
    profileId === null ? null : readProfile,
  );
  const readApproval = useCallback(
    (signal: AbortSignal) => api.testingAuthorization(approvalId!, signal),
    [api, approvalId],
  );
  const approval = useTestingRead(
    'validation-approval:' + approvalId,
    approvalId === null ? null : readApproval,
  );
  const result = validation.data?.data,
    grant = approval.data?.data;
  const referenceMissing = pack.reason_codes.includes('REFERENCE_SET_NOT_REGISTERED');
  const revoked = pack.status === 'REVOKED' || plan.status === 'REVOKED';
  const validationActive = result?.result === 'PENDING' || result?.result === 'RUNNING';
  const trimmed = reason.trim();
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  useEffect(() => {
    if (!visible || !validationActive || validation.loading || validation.error !== null) return;
    const timer = window.setTimeout(validation.reload, 1100);
    return () => window.clearTimeout(timer);
  }, [visible, validationActive, validation.loading, validation.error, validation.reload]);

  function blocked(action: Action): string | null {
    if (busy !== null) return '正在提交原测试包操作';
    if (unavailable !== null) return unavailable;
    const current = pending(testingPackControlPath(pack.id, action));
    if (current !== null) return current;
    if (action === 'revoke') {
      if (pack.status === 'REVOKED') return '测试包已撤销';
      return [...trimmed].length > 0 && [...trimmed].length <= 2000
        ? null
        : '请输入有效撤销原因，最多 2000 个字符';
    }
    if (revoked) return '所属计划或测试包已撤销';
    if (pack.status !== 'SEALED') return '须先封存测试包';
    if (referenceMissing) return '该固定设计尚无预登记参考集';
    if (action === 'publish') {
      if (validation.loading || validation.error !== null || result?.result !== 'PASSED')
        return '请核对该封存版本的原有效性验证通过结果';
      return null;
    }
    if (validationActive) return '原有效性验证尚未结束';
    if (reference === null || !reference.ready) return '请选择已登记且可读取的参考集';
    if (profile.loading || profile.error !== null || profile.data?.data.id !== profileId)
      return '请选择并核对测试配置';
    if (!profile.data?.data.ready) return '所选配置的独立执行环境尚未准入';
    if (
      approval.loading ||
      approval.error !== null ||
      grant === undefined ||
      grant.id !== textId(approvalText) ||
      grant.scope_kind !== 'PACK_VALIDATION' ||
      grant.profile_version_id !== profileId ||
      grant.budget_limit_cny !== '0.000000' ||
      grant.status !== 'APPROVED_UNBOUND'
    )
      return '请选择同配置、零预算且未绑定的有效性验证授权';
    return null;
  }

  function ask(action: Action) {
    if (blocked(action) !== null) return;
    setError(null);
    const expected_state_version = pack.state_version;
    const body =
      action === 'revoke'
        ? { expected_state_version, reason: trimmed }
        : action === 'publish'
          ? { expected_state_version }
          : {
              expected_state_version,
              profile_version_id: profileId!,
              reference_set_ref: reference!.reference_set_ref,
              authorization_id: grant!.id,
            };
    setConfirm({ action, version: expected_state_version, body: snapshotObject(body) });
  }

  async function commit() {
    if (
      confirm === null ||
      confirm.version !== pack.state_version ||
      blocked(confirm.action) !== null ||
      sending.current
    )
      return;
    const original = confirm;
    sending.current = true;
    setBusy(original.action);
    setError(null);
    try {
      const stage = await recovery.stageIntent(
        testingPackControlPath(pack.id, original.action),
        original.body,
      );
      if (stage.kind !== 'PREPARED') {
        if (live.current) setError('已有原测试包操作，请先核对');
        return;
      }
      if (!live.current) return;
      const response = await recovery.send(stage.record.key, stage.record.record_revision);
      if (!live.current) return;
      if (original.action === 'validations') {
        select(positiveInteger((response.response.data as TestingValidationReceipt).validation_id));
      } else if (original.action === 'revoke') setReason('');
    } catch (failure) {
      if (live.current) setError(errorText(failure, '暂时无法核实原测试包操作'));
    } finally {
      sending.current = false;
      if (live.current) {
        setBusy(null);
        setConfirm(null);
        refresh();
      }
    }
  }
  function button(action: Action) {
    const disabled = blocked(action);
    return (
      <div className="code-settings-form-actions">
        <button
          type="button"
          className="ui-button"
          disabled={disabled !== null}
          title={disabled ?? undefined}
          onClick={() => ask(action)}
        >
          {titles[action]}
        </button>
        {disabled && !(action !== 'revoke' && referenceMissing) && (
          <p className="read-status">{disabled}</p>
        )}
      </div>
    );
  }
  const sealed = pack.status === 'SEALED' || pack.status === 'PUBLISHED' || pack.sha256 !== null;
  return (
    <>
      {sealed && (
        <ReferenceSets
          api={api}
          selected={reference?.reference_set_ref}
          choose={pack.status === 'SEALED' && !revoked ? setReference : undefined}
          blocked={referenceMissing ? '该固定设计尚无预登记参考集' : null}
        />
      )}
      {sealed && (
        <section className="testing-editor-panel" aria-label="测试包有效性">
          <h4>有效性验证</h4>
          <div className="code-settings-form-actions">
            <label>
              原验证编号{' '}
              <input
                className="ui-input"
                inputMode="numeric"
                value={viewText}
                onChange={(event) => setViewText(event.currentTarget.value)}
              />
            </label>
            <button
              type="button"
              className="ui-button"
              disabled={textId(viewText) === null}
              onClick={() => {
                const id = textId(viewText);
                if (id === selected) validation.reload();
                else select(id);
              }}
            >
              查看原验证
            </button>
          </div>
          <ReadState
            loading={validation.loading}
            error={validation.error}
            stale={result !== undefined}
            retry={validation.reload}
          />
          {selected === null && <EmptyState icon="outline" message="未选择有效性验证" compact />}
          {result && (
            <>
              <p>
                原验证 #{result.id} · {resultNames[result.result]} · 原操作 #{result.operation_id}
              </p>
              <p>登记参考集 {result.reference_set_ref}</p>
              <ol className="code-settings-version-items">
                {result.testing_tasks.map((task) => (
                  <li key={task.id}>
                    <button className="ui-button" type="button" onClick={() => openTask(task.id)}>
                      验证任务 #{task.id} · {testingStatus[task.status]}
                    </button>
                  </li>
                ))}
              </ol>
            </>
          )}
          {pack.status === 'SEALED' && !revoked && (
            <>
              <p>
                {reference === null
                  ? '尚未选择预登记参考集'
                  : '所选参考集 ' +
                    reference.reference_set_ref +
                    ' · 每个样本重复 ' +
                    reference.repeat_count +
                    ' 次'}
              </p>
              <PagedTaskSelect
                label="验证用测试配置"
                load={profiles}
                visible={visible}
                value={profileId}
                disabled={busy !== null}
                change={(id) => {
                  setProfileId(id);
                  setApprovalId(null);
                  setApprovalText('');
                }}
              />
              <ReadState
                loading={profile.loading}
                error={profile.error}
                stale={profile.data !== null}
                retry={profile.reload}
              />
              <div className="code-settings-form-actions">
                <label>
                  有效性验证授权编号{' '}
                  <input
                    className="ui-input"
                    inputMode="numeric"
                    value={approvalText}
                    disabled={busy !== null}
                    onChange={(event) => {
                      setApprovalText(event.currentTarget.value);
                      setApprovalId(null);
                    }}
                  />
                </label>
                <button
                  type="button"
                  className="ui-button"
                  disabled={textId(approvalText) === null || busy !== null}
                  onClick={() => {
                    const id = textId(approvalText);
                    if (id === approvalId) approval.reload();
                    else setApprovalId(id);
                  }}
                >
                  核对验证授权
                </button>
              </div>
              <ReadState
                loading={approval.loading}
                error={approval.error}
                stale={grant !== undefined}
                retry={approval.reload}
              />
              {button('validations')}
              {button('publish')}
            </>
          )}
        </section>
      )}
      {pack.status !== 'REVOKED' && (
        <section className="testing-editor-panel" aria-label="撤销测试包">
          <h4>撤销资格</h4>
          <label>
            测试包撤销原因{' '}
            <textarea
              className="ui-input"
              value={reason}
              disabled={busy !== null}
              onChange={(event) => setReason(event.currentTarget.value)}
            />
          </label>
          {button('revoke')}
        </section>
      )}
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      <Confirmation
        open={confirm !== null}
        title={titles[confirm?.action ?? 'revoke']}
        description={descriptions[confirm?.action ?? 'revoke']}
        busy={busy !== null}
        confirmDisabled={confirm !== null && busy === null && blocked(confirm.action) !== null}
        confirm={() => void commit()}
        cancel={() => setConfirm(null)}
      />
    </>
  );
}
