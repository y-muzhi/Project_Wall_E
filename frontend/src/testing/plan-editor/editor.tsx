import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiRejected, snapshotObject, stableJson } from '../../api/client.ts';
import type { TestPlanVersion } from '../../api/testing-plans.ts';
import type { WalleApi } from '../../api/walle.ts';
import type { CommandRecovery } from '../../code-tasks/command-recovery.ts';
import { Confirmation } from '../../shared/confirmation.tsx';
import { errorText } from '../plans/read.tsx';
import { PlanBasis } from './basis.tsx';
import { CoverageEditor } from './coverage.tsx';
import {
  draftPath,
  initialDraft,
  loadDraft,
  receiptMatches,
  saveLocal,
  validateDraft,
} from './draft.ts';
import type { Draft, DraftReceipt, LocalDraft } from './draft.ts';
import './editor.css';

type Props = Readonly<{
  api: WalleApi;
  planId: number;
  version: TestPlanVersion | null;
  recovery: CommandRecovery;
  blocked: string | null;
  recovered: DraftReceipt | undefined;
  saved(version: TestPlanVersion): void;
  refresh(): void;
  dirty?(value: boolean): void;
}>;
function fieldMessage(error: unknown) {
  const message = errorText(error, '暂时无法核实草稿保存结果');
  if (!(error instanceof ApiRejected) || !Array.isArray(error.details?.field_errors))
    return message;
  const fields = error.details.field_errors.flatMap((item) =>
    item !== null &&
    typeof item === 'object' &&
    !Array.isArray(item) &&
    typeof item.field === 'string'
      ? [item.field]
      : [],
  );
  return fields.length ? message + '。请核对 ' + fields.join('、') : message;
}

export function PlanDraftEditor({
  api,
  planId,
  version,
  recovery,
  blocked,
  recovered,
  saved,
  refresh,
  dirty,
}: Props) {
  const versionId = version?.id ?? null;
  const scope = api.environmentScope;
  const [local, setLocal] = useState(() => loadDraft(planId, version, scope));
  const current = useRef(local);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState(false);
  const [discard, setDiscard] = useState(false);
  const request = useRef<AbortController | null>(null);
  const active = useRef(false);
  const composing = useRef(false);
  const applied = useRef<string | null>(null);
  const path = draftPath(planId, versionId);
  const base = version?.state_version ?? null;
  const sameInput = stableJson(local.draft) === stableJson(initialDraft(version));
  const modified = !sameInput;
  const conflict = version !== null && local.base !== base;
  const check = validateDraft(local.draft);
  const disabled = busy;
  const saveReason = busy
    ? '正在保存原草稿请求'
    : (blocked ??
      (conflict
        ? '请先核对服务端当前草稿'
        : version !== null && !modified
          ? '当前没有待保存的修改'
          : check.reason));

  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      request.current?.abort();
    };
  }, []);
  useEffect(() => {
    dirty?.(modified || conflict || busy);
    return () => dirty?.(false);
  }, [dirty, modified, conflict, busy]);

  function install(value: LocalDraft, persistent = true) {
    current.current = value;
    setLocal(value);
    setWarning(!saveLocal(planId, versionId, persistent ? value : null, scope));
  }

  function reset(value: TestPlanVersion | null) {
    install(
      { draft: initialDraft(value), base: value?.state_version ?? null, change: 0, sent: null },
      false,
    );
    setError(null);
  }

  const latest = useRef({ saved, refresh, version });
  latest.current = { saved, refresh, version };
  useEffect(() => {
    if (
      recovered === undefined ||
      recovered.key === applied.current ||
      !receiptMatches(current.current, recovered)
    )
      return;
    applied.current = recovered.key;
    const stored = recovered.version;
    const next = {
      draft: initialDraft(versionId === null ? null : stored),
      base: versionId === null ? null : stored.state_version,
      change: 0,
      sent: null,
    };
    current.current = next;
    setLocal(next);
    setWarning(!saveLocal(planId, versionId, null, scope));
    setError(null);
    if (versionId === null) setOpen(false);
    latest.current.saved(stored);
  }, [recovered, planId, versionId, scope]);

  function change(draft: Draft) {
    const previous = current.current;
    install({ ...previous, draft, change: previous.change + 1 });
    setError(null);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      composing.current ||
      request.current !== null ||
      saveReason !== null ||
      check.content === null
    )
      return;
    const controller = new AbortController();
    request.current = controller;
    const submitted = current.current;
    setBusy(true);
    setError(null);
    try {
      const staged = await recovery.stageIntent(
        path,
        snapshotObject({
          plan_content: check.content,
          ...(versionId === null ? {} : { expected_state_version: submitted.base }),
        }),
      );
      if (staged.kind !== 'PREPARED') {
        if (active.current) setError('已有原草稿请求，请先核对');
        return;
      }
      if (!active.current) return;
      install({ ...submitted, sent: { key: staged.record.key, change: submitted.change } });
      if (controller.signal.aborted) return;
      const response = await recovery.send(
        staged.record.key,
        staged.record.record_revision,
        controller.signal,
      );
      if (!active.current) return;
      const stored = response.response.data as TestPlanVersion;
      if (receiptMatches(current.current, { key: staged.record.key, version: stored })) {
        applied.current = staged.record.key;
        reset(versionId === null ? null : stored);
        if (versionId === null) setOpen(false);
        latest.current.saved(stored);
      }
    } catch (problem) {
      if (!active.current) return;
      setError(fieldMessage(problem));
      if (problem instanceof ApiRejected && problem.code === 'VERSION_CONFLICT')
        latest.current.refresh();
    } finally {
      if (request.current === controller) request.current = null;
      if (active.current) {
        setBusy(false);
        latest.current.refresh();
      }
    }
  }

  function useCurrentBase() {
    const actual = latest.current.version;
    if (!actual || !conflict || disabled || blocked !== null) return;
    install({ ...current.current, base: actual.state_version, sent: null });
    setError(null);
  }

  return (
    <details
      className="code-settings-versions testing-plan-editor"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        {versionId === null ? '新建计划草稿' : '编辑计划草稿'}
        {modified ? ' · 有本地输入' : ''}
      </summary>
      {open && (
        <form
          aria-label={versionId === null ? '新计划版本草稿' : '当前计划版本草稿'}
          onSubmit={(event) => void submit(event)}
          onCompositionStart={() => {
            composing.current = true;
          }}
          onCompositionEnd={() => {
            composing.current = false;
          }}
          className="testing-editor-panel"
        >
          {warning && <p className="read-status">当前无法暂存草稿，离开页面前请保存所需输入。</p>}
          {conflict && (
            <section className="testing-editor-panel" aria-label="草稿版本冲突">
              <p role="alert" className="inline-error">
                本地草稿依据版本 {local.base}，服务端当前版本 {base}。请核对页面上的已保存版本。
              </p>
              <div className="code-settings-form-actions">
                <button
                  className="ui-button"
                  type="button"
                  disabled={disabled}
                  onClick={useCurrentBase}
                >
                  保留本地输入并采用当前版本号
                </button>
                <button
                  className="ui-button"
                  type="button"
                  disabled={disabled}
                  onClick={() => setDiscard(true)}
                >
                  重新载入已保存内容
                </button>
              </div>
            </section>
          )}
          <PlanBasis
            api={api}
            draft={local.draft}
            frozen={versionId !== null}
            disabled={disabled}
            change={change}
          />
          <CoverageEditor api={api} draft={local.draft} disabled={disabled} change={change} />
          <div className="code-settings-form-actions">
            <button
              className="ui-button"
              type="submit"
              disabled={saveReason !== null}
              title={saveReason ?? undefined}
            >
              {busy ? '正在保存草稿…' : versionId === null ? '创建计划版本' : '保存计划草稿'}
            </button>
            {busy && (
              <button className="ui-button" type="button" onClick={() => request.current?.abort()}>
                停止等待
              </button>
            )}
            {modified && !conflict && (
              <button
                className="ui-button"
                type="button"
                disabled={disabled}
                onClick={() => setDiscard(true)}
              >
                清除本地改动
              </button>
            )}
            {saveReason && <p className="read-status">{saveReason}</p>}
          </div>
          {error && (
            <p role="alert" className="inline-error">
              {error}
            </p>
          )}
        </form>
      )}
      <Confirmation
        open={discard}
        title="清除本地草稿改动"
        description="确认后重新载入已保存版本。未提交的本地编辑将清除。"
        busy={false}
        dangerous
        confirmLabel="确认清除"
        confirm={() => {
          reset(latest.current.version);
          setDiscard(false);
        }}
        cancel={() => setDiscard(false)}
      />
    </details>
  );
}
