import type { MouseEvent, ReactNode } from 'react';
import { useId, useMemo, useState, useSyncExternalStore } from 'react';
import type { GuideRun } from '../api/models.ts';
import type { RequirementDiscussion } from '../requirements/discussion.ts';
import type { RequirementDocumentOwner } from '../requirements/document-owner.ts';
import type { RequirementGuideComposer } from './composer.ts';
import { reviewTarget, chapterTargets, nextChapter } from './scope.ts';
import { instructionFeedback } from './input-feedback.ts';
import { composerFeedback, composerProgress } from './composer-feedback.ts';
import { composerShortcut } from './send-shortcut.ts';
import { FormationPage } from '../formation/page-view.tsx';
import { SingleSelect } from '../shared/single-select.tsx';
import { Icon } from '../shared/icon.tsx';
const names = {
  DISCUSS: '讨论',
  REVISE: '写入当前文档',
} as const;

const quietSubscribe = () => () => {};
const empty = () => null;

const shortcutHint = 'Enter 发送 · Ctrl / ⌘ + Enter 换行';

function closeOtherDisclosures(event: MouseEvent<HTMLElement>) {
  if (!(event.target instanceof Element)) return;
  const current = event.target.closest('.guide-composer-disclosure');
  for (const panel of event.currentTarget.querySelectorAll<HTMLDetailsElement>(
    '.guide-composer-disclosure[open]',
  )) {
    if (panel !== current) panel.open = false;
  }
}

export function GuideComposer({
  owner,
  documents,
  associations,
  handoff,
  discussion,
  review = null,
  viewingHistory = null,
}: {
  owner: RequirementGuideComposer;
  documents: RequirementDocumentOwner;
  associations?: ReactNode;
  handoff?: ReactNode;
  discussion?: RequirementDiscussion;
  review?: GuideRun | null;
  viewingHistory?: number | null;
}) {
  const state = useSyncExternalStore(owner.subscribe, owner.getSnapshot),
    document = useSyncExternalStore(documents.subscribe, documents.getSnapshot);
  const discussionState = useSyncExternalStore(
    discussion?.subscribe ?? quietSubscribe,
    discussion?.getSnapshot ?? empty,
  );
  const navigation = useSyncExternalStore(
    document.navigation?.subscribe ?? quietSubscribe,
    document.navigation?.getSnapshot ?? empty,
  );
  const binding = documents.currentBinding;
  const [composing, setComposing] = useState(false);
  const [showRoute, setShowRoute] = useState(false);
  const workspace = owner.formationWorkspace;
  const route = workspace?.read.getSnapshot().summary.data;
  const help = useId();
  const target = state.target;
  const writing = state.action === 'REVISE';
  const available = state.available && !document.busy && document.mode === 'CURRENT';
  const disabled = !available || !owner.editable || state.refreshing;
  const inputDisabled = !available || !owner.instructionEditable;
  const topicUpdating = Boolean(
    discussionState && ['SUBMITTING', 'UNKNOWN', 'CONFIRMED'].includes(discussionState.phase),
  );
  const current = state.detail.current;
  const chapters = useMemo(() => {
    if (!binding || document.mode !== 'CURRENT' || navigation?.error) return [];
    try {
      return chapterTargets(binding.editor);
    } catch {
      return [];
    }
  }, [binding, document.mode, navigation?.error, current?.content_version]);
  const chapterId = target?.scope.scope_type === 'SECTION' ? target.scope.scope_ref.block_id : null;
  const chapter = chapters.find((item) => item.block_id === chapterId);
  const following = chapter ? nextChapter(chapters, chapter.block_id) : null;
  const missingChapter = chapterId !== null && !chapter;
  const scopeValue =
    target?.scope.scope_type === 'DOCUMENT'
      ? 'DOCUMENT'
      : chapter
        ? String(chapter.block_id)
        : target && chapterId === null
          ? 'REFERENCE'
          : 'NONE';
  const feedback = instructionFeedback(state.instruction);
  const guidance = composerFeedback(state, available, owner.allowed);
  const blocked =
    (document.mode === 'HISTORY' ? '请返回当前文档后发送。' : null) ??
    (available && owner.editable && writing && missingChapter
      ? '原章节已失效，请重新选择。'
      : null) ??
    guidance.blocked ??
    (topicUpdating ? '请先核实讨论主题的保存结果。' : null);
  const guidanceId = help + '-guidance';
  const effectId = help + '-effect';
  const topicError =
    !writing || discussionState?.phase === 'CONFIRMED' || discussionState?.phase === 'UNKNOWN'
      ? (discussionState?.error ?? null)
      : null;
  const inputError = !composing && state.instruction.length > 0 ? feedback.error : null;
  const problem = state.error ?? topicError ?? inputError;
  const progress = composerProgress(state, discussionState?.phase === 'SUBMITTING');
  const working = progress !== null;
  const context = state.formation_proposal
    ? '已选原提案'
    : state.parent
      ? '衔接运行 #' + state.parent.id
      : handoff
        ? '查看代码移交'
        : viewingHistory === null
          ? shortcutHint
          : '查看历史运行';
  let statusLabel = progress ?? blocked ?? state.draft_warning ?? context;
  if (problem !== null) statusLabel = '操作未完成';
  if (state.phase === 'UNKNOWN' || discussionState?.phase === 'UNKNOWN') statusLabel = '结果待核实';
  const statusMessage = problem ?? progress ?? blocked ?? state.draft_warning ?? shortcutHint;
  const hasStatusActions =
    problem !== null ||
    state.phase === 'UNKNOWN' ||
    state.phase === 'CONFIRMED' ||
    discussionState?.phase === 'UNKNOWN' ||
    discussionState?.phase === 'CONFIRMED' ||
    context !== shortcutHint;
  const canSend = !disabled && !composing && blocked === null && feedback.valid;
  const chooseChapter = (id: number) => {
    const selected = chapters.find((item) => item.block_id === id);
    if (selected) owner.selectChapter(selected.target);
    else owner.rejectScope();
  };
  const chooseScope = (value: string) => {
    if (disabled || topicUpdating || current === null) return;
    if (value === 'DOCUMENT') owner.selectDocument(current.id);
    else chooseChapter(Number(value));
  };
  const send = () => {
    if (canSend) void owner.submit();
  };
  const latestDiscussion =
    discussionState && discussionState.version === state.detail.requirement.discussion_version
      ? discussionState.discussion
      : null;
  const topics = discussionState?.discussion?.topics ?? [];
  const focus = latestDiscussion
    ? latestDiscussion.focus_topic_ref
    : state.detail.discussion_summary.focus_topic_ref;
  const focusTitle = latestDiscussion
    ? topics.find((topic) => topic.topic_ref === focus)?.title
    : state.detail.discussion_summary.focus_title;
  const formationTarget = state.formation_target_label;
  const discussionLabel = formationTarget ?? focusTitle;
  const routeStatus = state.formation_read_error
    ? '主线待刷新'
    : route?.exists === false
      ? '尚未建立主线'
      : '正在读取主线';
  const readError = state.formation_read_error && workspace && (
    <div role="alert">
      <p>{state.formation_read_error}</p>
      <button type="button" className="ui-button" onClick={() => void workspace.refresh(false)}>
        重新读取主线
      </button>
    </div>
  );
  const readTopics = () => {
    if (!discussionState?.loading && discussion && !topicUpdating) void discussion.load();
  };

  const routeSteps = showRoute && workspace && route?.formation_version != null && (
    <FormationPage
      key={workspace.documentId + ':' + route.formation_version}
      scope={workspace.documentId + ':' + route.formation_version}
      icon="outline"
      empty="主线暂无步骤"
      showTotal={false}
      compactControls
      load={(cursor, signal) =>
        workspace.api.getFormationSteps(
          workspace.requirementId,
          workspace.documentId,
          {
            limit: 20,
            known_f: route.formation_version!,
            include_cancelled: false,
            ...(cursor ? { cursor } : {}),
          },
          signal,
        )
      }
      onPathChanged={() => void workspace.refresh(false)}
      identity={(row) => row.step_ref}
      render={(row) => (
        <span>
          {row.position}. {row.title}
          {row.step_ref === route.current_step_ref ? '（当前）' : ''}
        </span>
      )}
    />
  );
  return (
    <section
      aria-label="AI 消息输入"
      className="guide-composer"
      onClickCapture={closeOtherDisclosures}
      onKeyDown={(event) => {
        if (
          event.key !== 'Escape' ||
          event.defaultPrevented ||
          event.nativeEvent.isComposing ||
          !(event.target instanceof Element)
        )
          return;
        const panel = event.target.closest<HTMLDetailsElement>('.guide-composer-disclosure[open]');
        if (panel === null) return;
        event.preventDefault();
        event.stopPropagation();
        panel.open = false;
        panel.querySelector('summary')?.focus();
      }}
    >
      <div className="guide-composer-body">
        <div className="guide-composer-toolbar">
          <div className="guide-mode-switch" role="group" aria-label="对话状态">
            {(['DISCUSS', 'REVISE'] as const).map((mode) => (
              <button
                key={mode}
                className="ui-button"
                type="button"
                aria-pressed={state.action === mode}
                onClick={() => owner.choose(mode)}
              >
                {names[mode]}
              </button>
            ))}
          </div>
          {associations}
          {writing ? (
            <details className="guide-composer-disclosure guide-target-control">
              <summary title={target?.label ?? '请选择写入范围'}>
                <span>写入范围</span>
                <strong>{chapter?.title ?? target?.label ?? '请选择'}</strong>
              </summary>
              <div className="guide-composer-popover guide-chapter-controls">
                {formationTarget !== null && (
                  <details onToggle={(event) => setShowRoute(event.currentTarget.open)}>
                    <summary>
                      当前主线 · {state.formation_focus ?? state.formation_goal ?? '查看'}
                    </summary>
                    <p>{state.formation_goal ?? routeStatus}</p>
                    {routeSteps}
                    {readError}
                  </details>
                )}
                <label>
                  写入范围
                  <SingleSelect
                    label="写入范围"
                    value={scopeValue}
                    disabled={
                      disabled || topicUpdating || current === null || current.archived_at !== null
                    }
                    options={[
                      { value: 'NONE', label: '请选择写入范围', disabled: true },
                      { value: 'DOCUMENT', label: '整篇文档' },
                      ...(scopeValue === 'REFERENCE' && target
                        ? [{ value: 'REFERENCE', label: target.label }]
                        : []),
                      ...chapters.map((item) => ({
                        value: String(item.block_id),
                        label: '　'.repeat(item.level - 1) + item.title,
                      })),
                    ]}
                    change={chooseScope}
                  />
                </label>
                <p className="field-help">
                  {current && `${current.name} · V${current.content_version} · `}
                  <span id={effectId}>{guidance.effect}</span>
                </p>
                {target &&
                  current &&
                  current.content_version !== target.content_version &&
                  !missingChapter &&
                  scopeValue !== 'REFERENCE' && (
                    <button
                      className="ui-button"
                      type="button"
                      disabled={disabled || topicUpdating || current.archived_at !== null}
                      onClick={() => chooseScope(scopeValue)}
                    >
                      使用最新版本确认范围
                    </button>
                  )}
                {following && target?.content_version === current?.content_version && (
                  <button
                    className="ui-button"
                    type="button"
                    disabled={disabled || topicUpdating || current?.archived_at !== null}
                    onClick={() => chooseChapter(following.block_id)}
                  >
                    选择下一章
                  </button>
                )}
              </div>
            </details>
          ) : (
            discussion &&
            discussionState && (
              <details
                className="guide-composer-disclosure guide-target-control"
                onToggle={(event) => {
                  setShowRoute(event.currentTarget.open);
                  if (
                    formationTarget === null &&
                    event.currentTarget.open &&
                    latestDiscussion === null
                  )
                    readTopics();
                }}
              >
                <summary title={discussionLabel ?? undefined}>
                  <span>{formationTarget === null ? '讨论主题' : '主线'}</span>
                  <strong>
                    {formationTarget === null
                      ? (discussionLabel ?? '暂无讨论主题')
                      : (state.formation_goal ?? routeStatus)}
                  </strong>
                  {state.formation_goal && (
                    <span>
                      当前：
                      {state.formation_focus ??
                        (route?.current_step_ref ? '步骤 ' + route.current_step_ref : '整篇文档')}
                    </span>
                  )}
                </summary>
                <div className="guide-composer-popover guide-topic-controls">
                  {routeSteps}
                  {readError}
                  {formationTarget === null && discussionState.loading && (
                    <p role="status">正在读取讨论主题…</p>
                  )}
                  {formationTarget === null && topics.length > 0 && (
                    <SingleSelect
                      label="切换讨论主题"
                      value={focus ?? ''}
                      disabled={disabled || topicUpdating || !discussion.allowed}
                      options={[
                        { value: '', label: '请选择讨论主题', disabled: true },
                        ...topics.map((topic) => ({ value: topic.topic_ref, label: topic.title })),
                      ]}
                      change={(value) => {
                        if (!disabled && value !== focus)
                          void discussion.submit({ type: 'SET_FOCUS', topic_ref: value });
                      }}
                    />
                  )}
                  {formationTarget === null &&
                    (latestDiscussion === null || discussionState.error) &&
                    !discussionState.loading &&
                    !topicUpdating && (
                      <button
                        className="ui-button"
                        type="button"
                        onClick={() => void discussion.reread()}
                      >
                        重新读取主题
                      </button>
                    )}
                </div>
              </details>
            )
          )}
        </div>
        {!writing && (
          <span id={effectId} className="sr-only">
            {guidance.effect}
          </span>
        )}
        <label className="guide-message-field">
          <span className="sr-only">给 AI 的消息</span>
          <textarea
            className="ui-input"
            aria-label="给 AI 的消息"
            value={state.instruction}
            disabled={inputDisabled}
            placeholder={writing ? '说明要写入的内容…' : '说明本次希望讨论的问题…'}
            rows={2}
            aria-invalid={!composing && state.instruction.length > 0 && !feedback.valid}
            aria-describedby={`${effectId} ${help} ${guidanceId}`}
            onChange={(event) => owner.change(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (composing) return;
              const action = composerShortcut(event.nativeEvent);
              if (action === null) return;
              event.preventDefault();
              if (action === 'SEND') send();
              else if (action === 'NEWLINE' && !inputDisabled) {
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
      </div>
      <footer className="guide-composer-footer">
        <details className="guide-composer-disclosure guide-composer-status">
          <summary
            data-tone={problem !== null ? 'error' : working ? 'busy' : undefined}
            title={statusMessage}
          >
            {working && problem === null && (
              <span className="guide-wait-indicator" aria-hidden="true" />
            )}
            <span>{statusLabel}</span>
            {hasStatusActions && <Icon name="more" />}
          </summary>
          <div className="guide-composer-popover guide-composer-status-details">
            {progress && <p>{progress}</p>}
            {!working && blocked && blocked !== problem && <p>{blocked}</p>}
            {problem && <p className="inline-error">{problem}</p>}
            {state.draft_warning && state.draft_warning !== statusMessage && (
              <p>{state.draft_warning}</p>
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
            {discussionState?.phase === 'UNKNOWN' && discussion && (
              <button
                className="ui-button"
                type="button"
                disabled={disabled}
                onClick={() => void discussion.retryUnknown()}
              >
                核实原主题请求
              </button>
            )}
            {discussionState?.phase === 'CONFIRMED' && discussion && (
              <button
                className="ui-button"
                type="button"
                disabled={disabled || discussionState.loading}
                onClick={() => void discussion.finish()}
              >
                读取主题保存结果
              </button>
            )}
            {handoff}
            {state.formation_proposal !== null && (
              <p role="status">
                已选择调整
                {state.formation_proposal.intent === 'ADJUST_WRITE' ? '原写入提案' : '原路线提案'}。
                请在输入框填写要求，发送后才开始调整。
                <button
                  type="button"
                  className="ui-button"
                  disabled={!owner.editable}
                  onClick={() => owner.clearProposalSelection()}
                >
                  取消本轮选择
                </button>
              </p>
            )}
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

            {viewingHistory !== null && review && review.status !== 'RUNNING' && (
              <div className="guide-send-guidance">
                <button
                  type="button"
                  className="ui-button"
                  disabled={disabled || topicUpdating}
                  onClick={() => owner.continueFrom(review)}
                >
                  衔接此运行继续讨论
                </button>
                {review.action_type === 'REVIEW' &&
                  review.status === 'COMPLETED' &&
                  review.scope !== null &&
                  binding && (
                    <button
                      type="button"
                      className="ui-button"
                      disabled={disabled || topicUpdating}
                      onClick={() => {
                        try {
                          owner.useReview(review, reviewTarget(binding.editor, review.scope!));
                        } catch {
                          owner.rejectScope();
                        }
                      }}
                    >
                      根据这次检查修订
                    </button>
                  )}
              </div>
            )}
            <p className="field-help">{shortcutHint}</p>
          </div>
        </details>
        <span id={guidanceId} className="sr-only" role="status">
          {statusLabel === shortcutHint ? '' : statusMessage}
        </span>
        <p id={help} className="guide-character-count" title={`${feedback.length} / 10000 字符`}>
          {composing ? '输入中' : `${feedback.length}/10000`}
        </p>
        <button
          className="ui-button primary"
          type="button"
          aria-label={`发送：${state.parent ? '继续讨论' : names[state.action]}`}
          disabled={!canSend}
          aria-describedby={`${guidanceId} ${help}`}
          onClick={send}
        >
          <Icon name="send" />
        </button>
      </footer>
    </section>
  );
}
