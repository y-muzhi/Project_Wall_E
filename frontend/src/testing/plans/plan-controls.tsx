import { useEffect, useRef, useState } from 'react';
import { ApiRejected, ApiUnknown } from '../../api/client.ts';
import { normalizedName } from '../../api/code-configuration-identities.ts';
import { testingPlanControlPath } from '../../api/testing-plans.ts';
import type { TestPlanVersion } from '../../api/testing-plans.ts';
import { CommandStorageError } from '../../code-tasks/command-recovery-store.ts';
import type { CommandRecovery } from '../../code-tasks/command-recovery.ts';
import { Confirmation } from '../../shared/confirmation.tsx';

type Action = 'publish' | 'revoke';
type Fixed = { action: Action; versionId: number; stateVersion: number; reason: string | null };

function publicationReason(version: TestPlanVersion): string | null {
  if (version.behaviors.length === 0) return '请先登记测试行为及覆盖';
  if (version.unresolved_questions.length > 0) return '请先处理草稿中的待解决问题';
  if (version.behaviors.some((item) => item.mode === 'UNCOVERED' && item.importance !== 'NORMAL'))
    return '关键行为仍未覆盖';
  const cases = new Map(version.cases.map((item) => [item.case_id, item]));
  const behaviors = new Map(version.behaviors.map((item) => [item.behavior_id, item]));
  for (const behavior of version.behaviors) {
    if (behavior.mode === 'AUTO') {
      if (
        behavior.case_ids.length === 0 ||
        behavior.case_ids.some(
          (caseId) => !cases.get(caseId)?.behavior_ids.includes(behavior.behavior_id),
        )
      )
        return '请为自动覆盖的行为关联有效用例';
    } else if (!behavior.explanation || behavior.case_ids.length > 0) {
      return '请补充覆盖说明并核对用例关联';
    }
  }
  for (const item of version.cases) {
    if (item.steps.length === 0 || item.assertions.length === 0) return '每个用例须填写步骤和断言';
    if (
      item.behavior_ids.some((key) => {
        const behavior = behaviors.get(key);
        return behavior?.mode !== 'AUTO' || !behavior.case_ids.includes(item.case_id);
      })
    )
      return '请核对用例和行为的双向关联';
  }
  return null;
}

export function PlanControls({
  version,
  recovery,
  unavailable,
  refresh,
}: Readonly<{
  version: TestPlanVersion;
  recovery: CommandRecovery;
  unavailable: string | null;
  refresh(message: string | null, reload: boolean): void;
}>) {
  const [reason, setReason] = useState('');
  const [fixed, setFixed] = useState<Fixed | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const active = useRef(true);
  const sending = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  if (version.status === 'REVOKED') return null;
  const publish = version.status === 'DRAFT';
  let normalizedReason: string | null = null;
  if (!publish) {
    try {
      const value = normalizedName(reason);
      if ([...value].length <= 2000) normalizedReason = value;
    } catch {
      // The reason remains in the form for correction.
    }
  }
  const reasonDisabled = busy
    ? '正在提交原计划操作'
    : (unavailable ??
      (publish
        ? publicationReason(version)
        : normalizedReason === null
          ? '请输入有效的撤销原因，最多 2000 个字符'
          : null));

  async function commit() {
    if (
      fixed === null ||
      sending.current ||
      reasonDisabled !== null ||
      fixed.versionId !== version.id ||
      fixed.stateVersion !== version.state_version
    )
      return;
    const original = fixed;
    sending.current = true;
    setBusy(true);
    setError(null);
    let message: string | null = null;
    let reload = false;
    try {
      const input =
        original.reason === null
          ? { expected_state_version: original.stateVersion }
          : { expected_state_version: original.stateVersion, reason: original.reason };
      const staged = await recovery.stageIntent(
        testingPlanControlPath(original.versionId, original.action),
        input,
      );
      if (staged.kind !== 'PREPARED') {
        if (active.current) setError('已有原计划请求，请先核对');
        return;
      }
      await recovery.send(staged.record.key, staged.record.record_revision);
      message = original.action === 'publish' ? '固定计划版本已发布' : '计划版本已撤销';
      reload = true;
      if (active.current && original.action === 'revoke') setReason('');
    } catch (failure) {
      if (active.current) {
        setError(
          failure instanceof ApiRejected ||
            failure instanceof ApiUnknown ||
            failure instanceof CommandStorageError
            ? failure.message
            : '暂时无法核实原计划操作',
        );
        reload = failure instanceof ApiRejected && failure.code === 'VERSION_CONFLICT';
      }
    } finally {
      sending.current = false;
      if (active.current) {
        setBusy(false);
        setFixed(null);
        refresh(message, reload);
      }
    }
  }

  return (
    <section className="code-settings-create" aria-label="计划发布与撤销">
      <h3>{publish ? '发布评审' : '撤销资格'}</h3>
      {publish ? (
        <p>
          确认固定设计依据和覆盖。发布后该版本的内容固定。
          {version.cases.length > 0 && '服务端会核对自动用例及登记的编译能力。'}
        </p>
      ) : (
        <label>
          撤销原因{' '}
          <textarea
            className="ui-input"
            value={reason}
            disabled={busy}
            onChange={(event) => setReason(event.currentTarget.value)}
          />
        </label>
      )}
      <div className="code-settings-form-actions">
        <button
          className="ui-button"
          type="button"
          disabled={reasonDisabled !== null}
          title={reasonDisabled ?? undefined}
          onClick={() => {
            setError(null);
            setFixed({
              action: publish ? 'publish' : 'revoke',
              versionId: version.id,
              stateVersion: version.state_version,
              reason: normalizedReason,
            });
          }}
        >
          {publish ? '发布测试计划' : '撤销测试计划'}
        </button>
        {reasonDisabled && <p className="read-status">{reasonDisabled}</p>}
      </div>
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      <Confirmation
        open={fixed !== null}
        title={publish ? '发布固定测试计划' : '撤销测试计划资格'}
        description={
          publish
            ? '确认发布所选版本的固定依据和覆盖。'
            : '确认撤销所选版本的使用资格。已保存的内容和结果保留。'
        }
        busy={busy}
        dangerous={!publish}
        confirmLabel={publish ? '确认发布' : '确认撤销'}
        confirmDisabled={
          fixed !== null &&
          (fixed.versionId !== version.id || fixed.stateVersion !== version.state_version)
        }
        confirm={() => void commit()}
        cancel={() => setFixed(null)}
      />
    </section>
  );
}
