import { useEffect, useRef, useState } from 'react';
import { exact, snapshotObject } from '../../api/client.ts';
import { findingClassifications, reviewTestingFindingPath } from '../../api/testing-reports.ts';
import type { TestingFinding } from '../../api/testing-reports.ts';
import { Confirmation } from '../../shared/confirmation.tsx';
import { errorText } from '../plans/read.tsx';
import type { useTestingRecovery } from '../task-recovery.tsx';

export const classificationText = {
  UNCLASSIFIED: '尚未归因',
  PRODUCT: '产品实现偏差',
  TEST_DESIGN: '测试设计问题',
  REQUIREMENT: '需求或设计歧义',
  ENVIRONMENT: '测试环境问题',
  UNKNOWN: '原因未确定',
};
type Classification = (typeof findingClassifications)[number];
type Draft = { classification: Classification; reason: string };
type Confirm = Draft & { expected_state_version: number };
const storageKey = (id: number) => 'walle:v2.0:testing:draft:' + location.origin + ':FINDING:' + id;
function restore(finding: TestingFinding): Draft {
  const fallback = {
    classification: finding.classification === 'UNCLASSIFIED' ? 'UNKNOWN' : finding.classification,
    reason: finding.review_reason ?? '',
  } as const;
  try {
    const saved = sessionStorage.getItem(storageKey(finding.id));
    if (saved === null) return fallback;
    const envelope = exact(JSON.parse(saved), ['schema_version', 'updated_at', 'content']);
    const draft = exact(envelope.content, ['classification', 'reason']);
    const classification = findingClassifications.find((item) => item === draft.classification);
    if (
      envelope.schema_version === 1 &&
      typeof envelope.updated_at === 'string' &&
      typeof draft.reason === 'string' &&
      [...draft.reason].length <= 2000 &&
      classification
    )
      return { classification, reason: draft.reason };
  } catch {
    // A malformed or unavailable tab draft does not change the saved finding.
  }
  return fallback;
}

export function clearSavedFindingDraft(finding: TestingFinding): boolean {
  try {
    const key = storageKey(finding.id);
    const saved = sessionStorage.getItem(key);
    if (saved === null) return true;
    const envelope = exact(JSON.parse(saved), ['schema_version', 'updated_at', 'content']);
    const draft = exact(envelope.content, ['classification', 'reason']);
    if (
      envelope.schema_version !== 1 ||
      draft.classification !== finding.classification ||
      typeof draft.reason !== 'string' ||
      draft.reason.trim() !== finding.review_reason
    )
      return false;
    sessionStorage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

export function FindingReview({
  finding,
  access,
  stale,
  refreshed,
  closed,
}: Readonly<{
  finding: TestingFinding;
  access: ReturnType<typeof useTestingRecovery>;
  stale: boolean;
  refreshed(): void;
  closed(): void;
}>) {
  const [draft, setDraft] = useState(() => restore(finding));
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(false),
    sending = useRef(false);
  const version = useRef(finding.state_version);
  const path = reviewTestingFindingPath(finding.id);
  const reason = draft.reason.trim();
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  function update(next: Draft) {
    setDraft(next);
    setError(null);
    try {
      sessionStorage.setItem(
        storageKey(finding.id),
        JSON.stringify({
          schema_version: 1,
          updated_at: new Date().toISOString(),
          content: next,
        }),
      );
    } catch {
      // The form can still hold its draft in this tab.
    }
  }
  function blocked() {
    if (busy) return '正在保存归因';
    if (stale) return '请先核对原发现项';
    if (version.current !== finding.state_version) return '原归因版本已更新，请核对后重新编辑';
    const pending = access.blocked(path);
    if (pending !== null) return pending;
    if (!reason || [...reason].length > 2000) return '请填写 1–2000 个字符的归因理由';
    if (
      draft.classification === 'PRODUCT' &&
      (finding.case_id === null || finding.basis_ref === null || finding.expected_behavior === null)
    )
      return '产品归因需要原失败用例、预期行为和设计依据';
    return null;
  }
  async function commit() {
    if (confirm === null || sending.current || blocked() !== null) return;
    sending.current = true;
    setBusy(true);
    setError(null);
    let done = false;
    try {
      const staged = await access.recovery.stageIntent(path, snapshotObject(confirm));
      if (staged.kind !== 'PREPARED') {
        if (alive.current) setError('已有原归因请求，请先核对');
        return;
      }
      if (!alive.current) return;
      await access.recovery.send(staged.record.key, staged.record.record_revision);
      done = true;
      try {
        sessionStorage.removeItem(storageKey(finding.id));
      } catch {
        /* Saved on the server. */
      }
    } catch (failure) {
      if (alive.current) setError(errorText(failure, '暂时无法核实原归因请求'));
    } finally {
      sending.current = false;
      if (alive.current) {
        setConfirm(null);
        setBusy(false);
        refreshed();
        if (done) closed();
      }
    }
  }
  const disabled = blocked();
  return (
    <div>
      <label>
        归因分类
        <select
          value={draft.classification}
          disabled={busy}
          onChange={(event) => {
            const kind = findingClassifications.find((item) => item === event.currentTarget.value);
            if (kind) update({ ...draft, classification: kind });
          }}
        >
          {findingClassifications.map((kind) => (
            <option key={kind} value={kind}>
              {classificationText[kind]}
            </option>
          ))}
        </select>
      </label>
      <label>
        归因理由
        <textarea
          value={draft.reason}
          disabled={busy}
          onChange={(event) => update({ ...draft, reason: event.currentTarget.value })}
        />
      </label>
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      <div className="code-settings-form-actions">
        <button
          type="button"
          className="ui-button"
          disabled={disabled !== null}
          title={disabled ?? undefined}
          onClick={() => {
            if (blocked() === null)
              setConfirm({
                classification: draft.classification,
                reason,
                expected_state_version: version.current,
              });
          }}
        >
          提交归因
        </button>
        <button type="button" className="ui-button" disabled={busy} onClick={closed}>
          关闭编辑
        </button>
      </div>
      {disabled && <p className="read-status">{disabled}</p>}
      <Confirmation
        open={confirm !== null}
        title="确认测试发现项归因"
        description={
          confirm === null
            ? ''
            : classificationText[confirm.classification] + ' · ' + confirm.reason
        }
        busy={busy}
        confirmLabel="保存归因"
        confirmDisabled={!busy && disabled !== null}
        confirm={() => void commit()}
        cancel={() => setConfirm(null)}
      />
    </div>
  );
}
