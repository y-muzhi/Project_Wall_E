import { useLayoutEffect, useRef, useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import type { FormationWorkspace } from './workspace.ts';
import type { FormationPathEditor } from './path-editor.ts';
import { pathChangeLabels } from './path-editor.ts';
import type { previewEntity } from '../api/formation-preview.ts';
import { registerModal, trapModalTab } from '../shared/modal.ts';
import { EmptyState } from '../shared/empty-state.tsx';
import { stepLabels, branchLabels, issueLabels } from './labels.ts';
import './editor-view.css';
type Entity = ReturnType<typeof previewEntity>;
function entityText(value: Entity | null): string {
  if (value === null) return '无';
  switch (value.kind) {
    case 'GOAL':
      return value.text;
    case 'STEP':
      return (
        value.title +
        ' · ' +
        stepLabels[value.status] +
        ' · 第' +
        value.position +
        '步；' +
        value.expected_results.map((row) => row.description).join('；')
      );
    case 'RESULT':
      return (
        value.description +
        '（' +
        (value.result_kind === 'CONTENT' ? '文档内容' : '分析结论') +
        '）'
      );
    case 'ISSUE':
      return (
        '问题 ' + value.issue_ref + ' → ' + value.step_ref + ' · ' + issueLabels[value.disposition]
      );
    case 'BRANCH':
      return (
        '支线 ' +
        value.branch_ref +
        '：来源 ' +
        value.origin_step_ref +
        '，返回 ' +
        value.return_step_ref +
        ' · ' +
        branchLabels[value.status]
      );
    case 'ARTIFACT':
      return (
        '关联 ' +
        value.artifact_ref +
        ' · 步骤 ' +
        value.step_ref +
        ' · ' +
        value.result_refs.join('、')
      );
    case 'DEPENDENCIES':
      return '步骤 ' + value.step_ref + ' 的前置步骤：' + (value.dependencies.join('、') || '无');
    case 'ARTIFACT_LINK':
      return (
        '关联至步骤 ' +
        value.step_ref +
        '；覆盖 ' +
        value.result_refs.join('、') +
        '；采用版本 #' +
        value.revision_id +
        ' 的 ' +
        value.block_ids.length +
        ' 个区块'
      );
  }
}
function Preview({ editor }: Readonly<{ editor: FormationPathEditor }>) {
  const state = useSyncExternalStore(editor.subscribe, editor.getSnapshot),
    preview = state.preview;
  if (preview === null) return null;
  const current = state.phase === 'PREVIEW_READY';
  return (
    <section className="formation-path-preview" aria-label="路线调整预览">
      <h3>{current ? '调整预览' : '上次预览（已过时）'}</h3>
      <p>预览仅读取实际记录，保存时仍会重新核对全部约束。</p>
      <h4>
        影响 {preview.affected_items.total} 项 · 本页 {preview.affected_items.items.length} 项
      </h4>
      {preview.affected_items.items.length === 0 ? (
        <EmptyState icon="outline" message="没有影响项" compact />
      ) : (
        <ol className="formation-preview-changes">
          {preview.affected_items.items.map((row) => (
            <li key={row.ordinal}>
              <strong>{pathChangeLabels[row.change_type]}</strong>
              <div>
                <span>调整前</span>
                <p>{entityText(row.before)}</p>
              </div>
              <div>
                <span>调整后</span>
                <p>{entityText(row.after)}</p>
              </div>
            </li>
          ))}
        </ol>
      )}
      <div className="formation-toolbar">
        <button
          type="button"
          className="ui-button"
          disabled={!current}
          onClick={() => void editor.preview('AFFECTED')}
        >
          影响首页
        </button>
        <button
          type="button"
          className="ui-button"
          disabled={!current || !preview.affected_items.has_more}
          onClick={() =>
            void editor.preview('AFFECTED', preview.affected_items.next_cursor ?? undefined)
          }
        >
          下一页影响
        </button>
      </div>
      <h4>
        提示 {preview.warnings.total} 项 · 本页 {preview.warnings.items.length} 项
      </h4>
      {preview.warnings.items.length === 0 ? (
        <EmptyState icon="info" message="本次调整没有附加提示" compact />
      ) : (
        <ul>
          {preview.warnings.items.map((row) => (
            <li key={row.ordinal}>{row.message}</li>
          ))}
        </ul>
      )}
      <div className="formation-toolbar">
        <button
          type="button"
          className="ui-button"
          disabled={!current}
          onClick={() => void editor.preview('WARNINGS')}
        >
          提示首页
        </button>
        <button
          type="button"
          className="ui-button"
          disabled={!current || !preview.warnings.has_more}
          onClick={() => void editor.preview('WARNINGS', preview.warnings.next_cursor ?? undefined)}
        >
          下一页提示
        </button>
      </div>
    </section>
  );
}
export function FormationPathEditorView({
  owner,
  editor,
}: Readonly<{ owner: FormationWorkspace; editor: FormationPathEditor }>) {
  const state = useSyncExternalStore(editor.subscribe, editor.getSnapshot),
    workspace = useSyncExternalStore(owner.subscribe, owner.getSnapshot);
  const ref = useRef<HTMLDialogElement>(null),
    title = useRef<HTMLHeadingElement>(null);
  useLayoutEffect(() => {
    const dialog = ref.current!,
      original = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.showModal();
    const release = registerModal(dialog);
    title.current?.focus();
    return () => {
      dialog.close();
      release();
      if (original?.isConnected && !original.closest('[hidden],[inert]'))
        original.focus({ preventScroll: true });
    };
  }, [editor]);
  const validating = editor.validation;
  const saving = state.phase === 'SAVING';
  const save = async () => {
    await editor.save();
    if (editor.getSnapshot().phase === 'SAVED') owner.closePathEditor();
  };
  return createPortal(
    <dialog
      ref={ref}
      className="formation-path-dialog"
      aria-label="旧路线草稿"
      tabIndex={-1}
      onKeyDown={trapModalTab}
      onCancel={(event) => {
        event.stopPropagation();
        event.preventDefault();
        owner.closePathEditor();
      }}
    >
      <header>
        <h2 tabIndex={-1} ref={title}>
          旧路线草稿
        </h2>
        <button
          type="button"
          className="ui-button"
          aria-label="关闭草稿"
          onClick={() => owner.closePathEditor()}
        >
          关闭
        </button>
      </header>
      <div className="formation-path-editor">
        <p className="field-help">
          这是此前保存在本机的草稿。可查看原操作，依据仍有效时可预览并保存。
        </p>
        {state.based_on_proposal !== null && (
          <p>基于原路线提案，保存成功后保留原提案并记录替代关系。</p>
        )}
        {state.warning && <p role="status">{state.warning}</p>}
        {state.error && (
          <p role="alert" className="inline-error">
            {state.error}
          </p>
        )}
        {state.phase === 'UNKNOWN' && (
          <p role="status">原调整的结果待核实。请关闭草稿，从待核实操作中读取原请求的结果。</p>
        )}
        {state.phase === 'SAVING' && <p role="status">正在保存原草稿，结果将记录在本次操作下。</p>}
        {editor.stale && (
          <p role="status">主线或正文已更新。可查看原草稿，回到对话按最新状态提出调整。</p>
        )}
        {state.reason && <p>{state.reason}</p>}
        <ol>
          {state.changes.map((change) => (
            <li key={change.local_key}>
              <details>
                <summary>
                  {pathChangeLabels[change.value.type as keyof typeof pathChangeLabels] ??
                    '草稿操作'}
                </summary>
                <pre>{JSON.stringify(change.value, null, 2)}</pre>
              </details>
            </li>
          ))}
        </ol>
        {state.result_routes.length > 0 && (
          <details>
            <summary>原成果去向</summary>
            <pre>{JSON.stringify(state.result_routes, null, 2)}</pre>
          </details>
        )}
        {validating !== null && <p className="field-help">{validating}</p>}
        <Preview editor={editor} />
      </div>
      <footer>
        <div>
          {state.phase === 'PREVIEWING'
            ? '正在读取预览…'
            : editor.canSave
              ? '预览对应当前草稿，可确认保存'
              : editor.stale
                ? '请先核对最新版本'
                : workspace.pending.length > 0
                  ? '请先核实原操作'
                  : (owner.writeReason ?? '请先预览原草稿')}
        </div>
        <div className="formation-toolbar">
          <button
            type="button"
            className="ui-button"
            disabled={validating !== null || editor.stale || saving || state.phase === 'PREVIEWING'}
            onClick={() => void editor.preview()}
          >
            预览影响
          </button>
          <button
            type="button"
            className="ui-button primary"
            disabled={!editor.canSave}
            onClick={() => void save()}
          >
            保存原草稿
          </button>
        </div>
      </footer>
    </dialog>,
    document.body,
  );
}
