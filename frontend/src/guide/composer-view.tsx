import { useId, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import type { GuideRun } from '../api/models.ts';
import { operations } from '../api/models.ts';
import type { RequirementDocumentOwner } from '../requirements/document-owner.ts';
import type { RequirementGuideComposer } from './composer.ts';
import { guideTarget, reviewTarget, chapterTargets, nextChapter } from './scope.ts';
import { useDocumentCreation } from '../requirements/document-directory-view.tsx';
import { instructionFeedback } from './input-feedback.ts';
import { composerFeedback } from './composer-feedback.ts';
import { composerShortcut } from './send-shortcut.ts';
import { SingleSelect } from '../shared/single-select.tsx';
import { Icon } from '../shared/icon.tsx';
const names = {
  DISCUSS: '讨论',
  GENERATE: '生成新文档',
  REVISE: '修订并保存',
  PROPOSE_CHANGES: '提出修改建议',
  COMPARE: '对照分析',
  REVIEW: '检查',
};
const scopeNames = {
  DOCUMENT: '整篇文档',
  SECTION: '当前章节',
  BLOCK: '当前区块',
  SELECTION: '当前选区',
} as const;
const kinds = { brief: '需求说明', design: '设计文档', specification: '规格说明' };
const quietSubscribe = () => () => {},
  empty = () => null;
export function GuideComposer({
  owner,
  documents,
  review = null,
  viewingHistory = null,
}: {
  owner: RequirementGuideComposer;
  documents: RequirementDocumentOwner;
  review?: GuideRun | null;
  viewingHistory?: number | null;
}) {
  const state = useSyncExternalStore(owner.subscribe, owner.getSnapshot),
    document = useSyncExternalStore(documents.subscribe, documents.getSnapshot);
  const createDocument = useDocumentCreation();
  const nav = useSyncExternalStore(
      document.navigation?.subscribe ?? quietSubscribe,
      document.navigation?.getSnapshot ?? empty,
    ),
    binding = documents.currentBinding;
  const [composing, setComposing] = useState(false),
    [settingsOpen, setSettingsOpen] = useState(false),
    settings = useRef<HTMLDetailsElement>(null),
    help = useId(),
    target = state.target;
  const targetName =
    target === null
      ? null
      : (state.detail.documents.find((item) => item.id === target.document_id)?.name ??
        target.label);
  const disabled = !state.available || !owner.editable || state.refreshing || document.busy;
  const scopeType = target?.scope.scope_type ?? 'DOCUMENT',
    feedback = instructionFeedback(state.instruction),
    guidance = composerFeedback(state, !disabled, owner.allowed),
    guidanceId = help + '-guidance',
    canSend = !disabled && !composing && owner.allowed && feedback.valid;
  const closeSettings = (cancel = false) => {
    owner.endSettings(cancel);
    if (settings.current) {
      settings.current.open = false;
      if (cancel) settings.current.querySelector('summary')?.focus();
      else
        settings.current
          .closest('.guide-composer')
          ?.querySelector<HTMLTextAreaElement>('textarea')
          ?.focus();
    }
  };
  const openSettings = () => {
    if (!settings.current) return;
    settings.current.open = true;
    requestAnimationFrame(() => {
      const selector =
        state.action === 'GENERATE' ? 'input:not([type=checkbox])' : '[aria-label="AI 工作目标"]';
      (
        settings.current?.querySelector<HTMLElement>(selector) ??
        settings.current?.querySelector<HTMLElement>('[role=combobox]')
      )?.focus();
    });
  };
  const scopeOptions = useMemo(
    () =>
      Object.keys(scopeNames).map((key) => {
        const kind = key as keyof typeof scopeNames;
        try {
          if (!binding || nav?.error || binding.editor.loadedDocument.id !== target?.document_id)
            throw Error('请先阅读工作目标文档');
          return {
            kind,
            target: guideTarget(
              binding.editor,
              kind,
              nav?.selected_block ?? nav?.active_heading ?? null,
              document.selection,
            ),
          };
        } catch {
          return { kind, target: null };
        }
      }),
    [
      binding,
      nav?.selected_block,
      nav?.active_heading,
      nav?.error,
      document.selection,
      target?.document_id,
    ],
  );
  const selectedSources = state.source_refs
    .filter((ref) => ref.kind === 'REVISION')
    .map((ref) => Number(ref.document_id));
  const chapters = useMemo(() => {
    try {
      return binding && document.mode === 'CURRENT' && !nav?.error
        ? chapterTargets(binding.editor)
        : [];
    } catch {
      return [];
    }
  }, [binding, document.mode, document.detail?.current?.content_version, nav?.error]);
  const chapterId = target?.scope.scope_type === 'SECTION' ? target.scope.scope_ref.block_id : null;
  const sameDocument = target?.document_id === binding?.editor.loadedDocument.id;
  const chapter = sameDocument ? chapters.find((item) => item.block_id === chapterId) : undefined;
  const following = chapter ? nextChapter(chapters, chapter.block_id) : null;
  const chooseChapter = (id: number) => {
    const selected = chapters.find((item) => item.block_id === id);
    if (selected) owner.selectChapter(selected.target);
    else owner.rejectScope();
  };
  const send = () => {
    if (canSend) {
      owner.endSettings();
      if (settings.current) settings.current.open = false;
      void owner.submit();
    }
  };
  return (
    <section
      aria-label="AI 消息输入"
      className="guide-composer"
      aria-busy={state.refreshing || state.phase === 'SUBMITTING' || state.phase === 'READING'}
    >
      <div className="guide-composer-body">
        {viewingHistory !== null && (
          <p className="field-help">
            正在查看运行 #{viewingHistory}。输入仅发送当前明确选择的操作。
          </p>
        )}
        {state.parent && (
          <p role="status">
            衔接运行 #{state.parent.id}，创建新的讨论轮次。
            <button
              className="ui-button"
              type="button"
              disabled={disabled}
              onClick={() => owner.continueFrom(null)}
            >
              取消衔接
            </button>
          </p>
        )}
        <details
          ref={settings}
          className="guide-composer-settings"
          onToggle={(event) => {
            const open = event.currentTarget.open;
            setSettingsOpen(open);
            if (open) {
              owner.beginSettings();
              void owner.loadBinding();
            } else owner.endSettings();
          }}
          onKeyDown={(event) => {
            if (
              event.key === 'Escape' &&
              !event.nativeEvent.isComposing &&
              !event.defaultPrevented &&
              event.currentTarget.open
            ) {
              event.preventDefault();
              event.stopPropagation();
              owner.endSettings(true);
              event.currentTarget.open = false;
              event.currentTarget.querySelector('summary')?.focus();
            }
          }}
        >
          <summary role="button" aria-label="操作设置" aria-expanded={settingsOpen}>
            <span>{names[state.action]}</span>
            <span
              className="scope-summary"
              title={
                state.action === 'GENERATE' ? state.new_target.name : (targetName ?? undefined)
              }
            >
              {state.action === 'GENERATE'
                ? state.new_target.name || '新文档'
                : target
                  ? `${targetName} · V${target.content_version}`
                  : '未指定文档'}
            </span>
            <span className="guide-settings-trigger">
              <Icon name="settings" />
              操作设置
              <span className="guide-settings-chevron">
                <Icon name="down" />
              </span>
            </span>
          </summary>
          <label>
            AI 操作
            <SingleSelect
              label="AI 操作"
              value={state.action}
              disabled={disabled || state.parent !== null}
              options={operations.map((value) => ({ value, label: names[value] }))}
              change={(value) => owner.choose(value as typeof state.action)}
            />
          </label>
          {state.action === 'GENERATE' ? (
            <>
              <label>
                文档名称
                <input
                  className="ui-input"
                  value={state.new_target.name}
                  disabled={disabled}
                  onChange={(event) =>
                    owner.configureNew(
                      event.currentTarget.value,
                      state.new_target.document_kind,
                      state.new_target.template_ref !== null,
                    )
                  }
                />
              </label>
              <label>
                文档类型
                <SingleSelect
                  label="生成文档类型"
                  value={state.new_target.document_kind}
                  disabled={disabled}
                  options={Object.entries(kinds).map(([value, label]) => ({ value, label }))}
                  change={(value) =>
                    owner.configureNew(
                      state.new_target.name,
                      value as typeof state.new_target.document_kind,
                      state.new_target.template_ref !== null,
                    )
                  }
                />
              </label>
              <label className="guide-structure-choice">
                <input
                  type="checkbox"
                  disabled={disabled}
                  checked={state.new_target.template_ref !== null}
                  onChange={(event) =>
                    owner.configureNew(
                      state.new_target.name,
                      state.new_target.document_kind,
                      event.currentTarget.checked,
                    )
                  }
                />
                绑定固定结构
              </label>
              <p className="field-help">成功后直接保存为未确认稿。</p>
              <button
                className="ui-button"
                type="button"
                disabled={disabled || !createDocument}
                onClick={() => {
                  closeSettings();
                  createDocument?.({
                    name: state.new_target.name,
                    kind: (
                      {
                        brief: 'REQUIREMENT_BRIEF',
                        design: 'DESIGN',
                        specification: 'SPECIFICATION',
                      } as const
                    )[state.new_target.document_kind],
                    framework: true,
                  });
                }}
              >
                创建框架，分章撰写
              </button>
              <p className="field-help">长文档可先创建章节框架，再选择“分章节撰写”，逐章保存。</p>
            </>
          ) : (
            <>
              <label>
                工作目标
                <SingleSelect
                  label="AI 工作目标"
                  disabled={disabled || state.parent !== null}
                  value={target === null ? 'NONE' : String(target.document_id)}
                  options={[
                    { value: 'NONE', label: '不指定文档' },
                    ...state.detail.documents.map((item) => ({
                      value: String(item.id),
                      label: item.name + (item.archived_at === null ? '' : '（已归档）'),
                    })),
                  ]}
                  change={(value) => owner.selectDocument(value === 'NONE' ? null : Number(value))}
                />
              </label>
              {document.detail?.current && (
                <button
                  type="button"
                  className="ui-button"
                  disabled={disabled || state.parent !== null}
                  onClick={() => owner.selectDocument(document.detail!.current!.id)}
                >
                  采用当前阅读文档作为目标
                </button>
              )}
              {target && (
                <>
                  <label>
                    操作范围
                    <SingleSelect
                      label="操作范围"
                      value={scopeType}
                      disabled={disabled || state.parent !== null}
                      options={scopeOptions.map((item) => ({
                        value: item.kind,
                        label: scopeNames[item.kind],
                        disabled: item.kind !== 'DOCUMENT' && item.target === null,
                      }))}
                      change={(value) => {
                        if (value === 'DOCUMENT') owner.selectDocument(target.document_id);
                        else {
                          const selected = scopeOptions.find((item) => item.kind === value)?.target;
                          if (selected) owner.select(selected);
                          else owner.rejectScope();
                        }
                      }}
                    />
                  </label>
                  <p className="field-help">
                    {targetName} · V{target.content_version} · {scopeNames[scopeType]}
                  </p>
                </>
              )}
              {state.action === 'REVISE' && (
                <p className="field-help">成功后直接保存授权范围内的修订。</p>
              )}
            </>
          )}
          <fieldset disabled={disabled || state.parent !== null}>
            <legend>参考文档</legend>
            {state.detail.documents.length === 0 ? (
              <p className="field-help">暂无可选文档</p>
            ) : (
              state.detail.documents.map((item) => (
                <label key={item.id}>
                  <input
                    type="checkbox"
                    checked={selectedSources.includes(item.id)}
                    onChange={(event) =>
                      owner.chooseReferences(
                        event.currentTarget.checked
                          ? [...selectedSources, item.id]
                          : selectedSources.filter((id) => id !== item.id),
                      )
                    }
                  />
                  {item.name} · v{item.content_version}
                </label>
              ))
            )}
          </fieldset>
          {review && review.status !== 'RUNNING' && (
            <button
              className="ui-button"
              type="button"
              disabled={disabled}
              onClick={() => owner.continueFrom(review)}
            >
              衔接此运行继续讨论
            </button>
          )}
          {review?.action_type === 'REVIEW' &&
            review.status === 'COMPLETED' &&
            review.scope !== null && (
              <button
                className="ui-button"
                type="button"
                disabled={disabled || !binding}
                onClick={() => {
                  try {
                    owner.useReview(review, reviewTarget(binding!.editor, review.scope!));
                  } catch {
                    owner.rejectScope();
                  }
                }}
              >
                根据这次检查修订
              </button>
            )}
          <div className="guide-settings-actions">
            <button
              className="ui-button"
              type="button"
              disabled={disabled}
              onClick={() => closeSettings(true)}
            >
              取消调整
            </button>
            <button
              className="ui-button primary"
              type="button"
              disabled={disabled}
              onClick={() => closeSettings()}
            >
              完成设置
            </button>
          </div>
        </details>
        {state.parent === null && chapters.length > 0 && (
          <div className="guide-chapter-controls">
            {state.action === 'REVISE' && target?.scope.scope_type === 'SECTION' && sameDocument ? (
              <>
                <label>
                  撰写章节
                  <SingleSelect
                    label="撰写章节"
                    value={chapter ? String(chapter.block_id) : 'NONE'}
                    disabled={disabled}
                    options={[
                      { value: 'NONE', label: '请选择章节', disabled: true },
                      ...chapters.map((item) => ({
                        value: String(item.block_id),
                        label: `${'　'.repeat(item.level - 1)}${item.title}`,
                      })),
                    ]}
                    change={(value) => chooseChapter(Number(value))}
                  />
                </label>
                <p className="field-help">
                  {chapter ? chapter.title : '原章节已失效，请重新选择'} ·
                  每次仅保存所选章节；填写要求后发送。
                </p>
                {chapter && target.content_version !== chapter.target.content_version && (
                  <button
                    className="ui-button"
                    type="button"
                    disabled={disabled}
                    onClick={() => chooseChapter(chapter.block_id)}
                  >
                    使用最新版本继续本章
                  </button>
                )}
                <button
                  className="ui-button"
                  type="button"
                  disabled={disabled || !following}
                  onClick={() => {
                    if (following) chooseChapter(following.block_id);
                  }}
                >
                  选择下一章
                </button>
                {!following && chapter && (
                  <span className="field-help">当前层级没有下一章，可从列表选择其他章节。</span>
                )}
              </>
            ) : (
              <button
                className="ui-button"
                type="button"
                disabled={disabled}
                onClick={() => {
                  owner.endSettings();
                  chooseChapter(chapters[0]!.block_id);
                }}
              >
                分章节撰写当前文档
              </button>
            )}
          </div>
        )}
        <p className="guide-action-effect">{guidance.effect}</p>
        {target &&
          state.action !== 'GENERATE' &&
          document.detail?.current &&
          document.detail.current.id !== target.document_id && (
            <p className="guide-target-notice">
              当前阅读与工作目标不同；本次操作仍以“{targetName}”为准。
            </p>
          )}
        <label className="guide-message-field">
          <span className="sr-only">给 AI 的消息</span>
          <textarea
            className="ui-input"
            aria-label="给 AI 的消息"
            value={state.instruction}
            disabled={disabled}
            placeholder="说明本次希望讨论或完成的工作…"
            rows={3}
            aria-invalid={!composing && state.instruction.length > 0 && !feedback.valid}
            aria-describedby={help}
            onChange={(event) => owner.change(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (composing) return;
              const action = composerShortcut(event.nativeEvent);
              if (action === null) return;
              event.preventDefault();
              if (action === 'SEND') send();
              else if (action === 'NEWLINE' && !disabled) {
                const field = event.currentTarget;
                field.setRangeText('\n', field.selectionStart, field.selectionEnd, 'end');
                owner.change(field.value);
              }
            }}
            onCompositionStart={() => setComposing(true)}
            onCompositionEnd={(event) => {
              setComposing(false);
              owner.change(event.currentTarget.value);
            }}
          />
        </label>
        <p
          id={help}
          className={
            !composing && state.instruction.length > 0 && !feedback.valid
              ? 'field-help inline-error'
              : 'field-help guide-character-count'
          }
        >
          {composing
            ? '正在输入…'
            : `${feedback.length} / 10000 字符${state.instruction.length > 0 && feedback.error ? ' · ' + feedback.error : ''}`}
        </p>
        {guidance.blocked && (
          <div id={guidanceId} className="guide-send-guidance">
            <p>{guidance.blocked}</p>
            {guidance.configure && !disabled && (
              <button type="button" className="ui-button" onClick={openSettings}>
                完善操作设置
              </button>
            )}
          </div>
        )}
        {state.phase === 'SUBMITTING' && <p role="status">正在提交本次操作…</p>}
        {state.phase === 'READING' && <p role="status">正在核实实际状态…</p>}
        {state.phase === 'CONFIRMED' && <p role="status">操作已接受，正在读取运行结果。</p>}
        {state.draft_warning && <p role="status">{state.draft_warning}</p>}
        {state.error && (
          <p role="alert" className="inline-error">
            {state.error}
          </p>
        )}
        {state.phase === 'UNKNOWN' && (
          <button
            className="ui-button"
            type="button"
            disabled={!state.available || state.refreshing}
            onClick={() => void owner.recover()}
          >
            核实原请求
          </button>
        )}
        {state.phase === 'CONFIRMED' && (
          <button
            className="ui-button"
            type="button"
            disabled={!state.available || state.refreshing}
            onClick={() => void owner.finish()}
          >
            读取已接受结果
          </button>
        )}
        {state.phase === 'ERROR' && (
          <button
            className="ui-button"
            type="button"
            disabled={disabled}
            onClick={() => void owner.refresh()}
          >
            重新读取状态
          </button>
        )}
      </div>
      <footer className="guide-composer-footer">
        <span className="guide-send-hint">Enter 发送 · Ctrl / ⌘ + Enter 换行</span>
        <button
          className="ui-button primary"
          type="button"
          disabled={!canSend}
          aria-describedby={guidance.blocked ? guidanceId : help}
          onClick={send}
        >
          <Icon name="send" />
          {state.parent ? '继续讨论' : names[state.action]}
        </button>
      </footer>
    </section>
  );
}
