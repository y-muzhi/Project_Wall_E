import './document-associations.css';
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { RequirementDetailOwner } from './detail-owner.ts';
import { EmptyState } from '../shared/empty-state.tsx';

export function DocumentAssociations({
  owner,
  active,
  blocked,
}: Readonly<{ owner: RequirementDetailOwner; active: boolean; blocked: boolean }>) {
  const flow = owner.regions!.discussion;
  const composer = owner.regions!.conversation.composer;
  const state = useSyncExternalStore(flow.subscribe, flow.getSnapshot);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<readonly number[] | null>(null);
  const [latest, setLatest] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const panel = useRef<HTMLDetailsElement>(null);
  const documentId = owner.getSnapshot().detail?.selected_document_id ?? null;
  const binding = state.discussion?.binding;
  const references = binding?.source_refs ?? [];
  const saved = references.filter(
    (item) => item.kind === 'REVISION' && item.document_id !== documentId,
  );
  const selected = draft ?? saved.map((item) => Number(item.document_id));
  const documents = state.detail.documents.filter((item) => item.id !== documentId);
  const changed =
    latest ||
    JSON.stringify([...selected].sort()) !==
      JSON.stringify(saved.map((item) => Number(item.document_id)).sort());
  const locked = blocked || !flow.allowed || documentId === null;
  const reason = blocked
    ? '当前阅读或编辑状态不允许调整关联文档。'
    : state.detail.requirement.document_work_state !== 'IDLE'
      ? '请先结束当前编辑、建议审阅或 AI 任务。'
      : state.phase === 'UNKNOWN'
        ? '保存结果待核实，请先核实原请求。'
        : state.phase === 'CONFIRMED'
          ? '关联已保存，请先读取最新结果。'
          : state.phase === 'SUBMITTING'
            ? '正在保存关联文档。'
            : state.loading
              ? '正在读取关联文档。'
              : '关联信息尚未就绪，请重新读取。';
  const stale = saved.some((source) =>
    documents.some(
      (item) => item.id === source.document_id && item.current_revision_id !== source.revision_id,
    ),
  );
  useEffect(() => {
    if (!active || !open) return;
    const current = flow.getSnapshot();
    if (!current.discussion || current.version !== current.detail.requirement.discussion_version)
      void flow.load();
  }, [active, open, state.detail.requirement.discussion_version, flow]);
  useEffect(() => {
    if (state.phase !== 'READY' || !binding) return;
    if (composer.getSnapshot().detail.requirement.discussion_version === state.version)
      composer.syncAssociatedSources(binding.source_refs);
  }, [state.phase, state.version, binding, composer]);
  const cancel = () => {
    setDraft(null);
    setLatest(false);
    setError(null);
    if (panel.current) {
      panel.current.open = false;
      panel.current.querySelector('summary')?.focus();
    }
  };
  const reconcile = async (done: boolean) => {
    if (!done) return;
    try {
      if (owner.getSnapshot().detail?.selected_document_id !== documentId) return;
      const actual = flow.getSnapshot().discussion;
      if (actual) composer.syncAssociatedSources(actual.binding.source_refs);
      owner.toasts.push('success', '关联文档已保存');
      cancel();
    } catch {
      setError('关联已保存，详情暂时无法读取，请重新读取。');
    }
  };
  const save = async () => {
    if (locked || !binding || documentId === null || !changed) return;
    setError(null);
    try {
      const sourceRefs = [
        ...references.filter((item) => item.kind !== 'REVISION'),
        ...selected.map((identity) => {
          const existing = saved.find((item) => item.document_id === identity);
          if (existing && !latest) return existing;
          const document = documents.find((item) => item.id === identity);
          if (!document) throw Error('关联文档已变化，请重新读取。');
          return {
            kind: 'REVISION',
            document_id: identity,
            revision_id: document.current_revision_id,
            block_ids: null,
          };
        }),
      ];
      await reconcile(
        await flow.submit({
          type: 'SET_BINDING',
          target_document_id: documentId,
          scope:
            binding.target_document_id === documentId
              ? binding.scope
              : { scope_type: 'DOCUMENT', scope_ref: null },
          source_refs: sourceRefs,
        }),
      );
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '关联文档保存失败');
    }
  };
  const reread = async () => {
    setError(null);
    try {
      if (owner.getSnapshot().detail?.selected_document_id !== documentId) return;
      await owner.refresh();
      await flow.load();
    } catch {
      setError('关联文档暂时无法读取，原选择已保留。');
    }
  };
  const pending = ['SUBMITTING', 'UNKNOWN', 'CONFIRMED'].includes(state.phase);
  return (
    <details
      ref={panel}
      className="guide-associated-documents"
      onToggle={(event) => {
        const expanded = event.currentTarget.open;
        setOpen(expanded);
        if (!expanded && !pending) {
          setDraft(null);
          setLatest(false);
        }
      }}
      onKeyDown={(event) => {
        if (event.key === 'Escape' && !event.defaultPrevented && !event.nativeEvent.isComposing) {
          event.preventDefault();
          event.stopPropagation();
          if (!pending) cancel();
        }
      }}
    >
      <summary>关联文档 · {saved.length}</summary>
      {state.loading && <p role="status">正在读取关联文档…</p>}
      {locked && <p className="field-help">{reason}</p>}
      {binding && (
        <>
          <fieldset disabled={locked}>
            <legend>关联文档</legend>
            {documents.length ? (
              documents.map((document) => (
                <label key={document.id}>
                  <input
                    type="checkbox"
                    checked={selected.includes(document.id)}
                    onChange={(event) => {
                      setDraft(
                        event.currentTarget.checked
                          ? [...selected, document.id]
                          : selected.filter((id) => id !== document.id),
                      );
                    }}
                  />
                  <span>
                    {document.name} · v{document.content_version}
                  </span>
                </label>
              ))
            ) : (
              <EmptyState icon="info" message="暂无其他可关联文档" compact />
            )}
          </fieldset>
          {stale && (
            <p className="field-help">
              部分来源已有新版本；已有关联继续使用保存的版本。
              <button
                type="button"
                className="ui-button"
                disabled={locked || latest}
                onClick={() => setLatest(true)}
              >
                使用最新版本
              </button>
            </p>
          )}
          {latest && (
            <p className="field-help">完成后将采用所选文档的当前版本，已发送请求保留原快照。</p>
          )}
          <div className="guide-settings-actions">
            <button type="button" className="ui-button" disabled={pending} onClick={cancel}>
              取消
            </button>
            <button
              type="button"
              className="ui-button primary"
              title={locked ? reason : !changed ? '关联文档未改变。' : undefined}
              disabled={locked || !changed}
              onClick={() => void save()}
            >
              保存关联文档
            </button>
          </div>
        </>
      )}
      {(state.error || error) && (
        <p role="alert" className="inline-error">
          {error ?? state.error}
        </p>
      )}
      {!state.loading && !pending && (!binding || state.error || error) && (
        <button type="button" className="ui-button" onClick={() => void reread()}>
          重新读取关联文档
        </button>
      )}
      {state.phase === 'UNKNOWN' && (
        <button
          type="button"
          className="ui-button"
          disabled={blocked}
          onClick={() => void flow.retryUnknown().then(reconcile)}
        >
          核实原请求
        </button>
      )}
      {state.phase === 'CONFIRMED' && (
        <button
          type="button"
          className="ui-button"
          disabled={blocked || state.loading}
          onClick={() => void flow.finish().then(reconcile)}
        >
          读取保存结果
        </button>
      )}
    </details>
  );
}
