import type { ReactNode } from 'react';
import { useId, useMemo, useState, useSyncExternalStore } from 'react';
import type { GuideRun } from '../api/models.ts';
import type { RequirementDiscussion } from '../requirements/discussion.ts';
import type { RequirementDocumentOwner } from '../requirements/document-owner.ts';
import type { RequirementGuideComposer } from './composer.ts';
import { reviewTarget, chapterTargets, nextChapter } from './scope.ts';
import { instructionFeedback } from './input-feedback.ts';
import { composerFeedback } from './composer-feedback.ts';
import { composerShortcut } from './send-shortcut.ts';
import { SingleSelect } from '../shared/single-select.tsx';
import { Icon } from '../shared/icon.tsx';
const names = {
  DISCUSS: '讨论',
  REVISE: '写入当前文档',
} as const;

const quietSubscribe = () => () => {};
const empty = () => null;

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
  const help = useId();
  const target = state.target;
  const writing = state.action === 'REVISE';
  const available = state.available && !document.busy && document.mode === 'CURRENT';
  const disabled = !available || !owner.editable || state.refreshing;
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
  const readTopics = () => {
    if (!discussionState?.loading && discussion && !topicUpdating) void discussion.load();
  };

  return (
    <section
      aria-label="AI 消息输入"
      className="guide-composer"
      aria-busy={state.refreshing || state.phase === 'SUBMITTING' || state.phase === 'READING'}
    >
      <div className="guide-composer-body">
        {handoff}
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
            <div className="guide-chapter-controls">
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
          ) : (
            discussion &&
            discussionState && (
              <details
                className="guide-topic-controls"
                onToggle={(event) => {
                  if (event.currentTarget.open && latestDiscussion === null) readTopics();
                }}
              >
                <summary title={focusTitle ?? undefined}>
                  <span>讨论主题</span>
                  <strong>{focusTitle ?? '暂无讨论主题'}</strong>
                </summary>
                {discussionState.loading && <p role="status">正在读取讨论主题…</p>}
                {topics.length > 0 && (
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
                {(latestDiscussion === null || discussionState.error) &&
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
              </details>
            )
          )}
        </div>
        {discussionState?.error &&
          (!writing ||
            discussionState.phase === 'CONFIRMED' ||
            discussionState.phase === 'UNKNOWN') && (
            <p role="alert" className="inline-error">
              {discussionState.error}
            </p>
          )}
        {discussion && topicUpdating && (
          <div className="guide-send-guidance">
            {discussionState?.phase === 'SUBMITTING' && <p role="status">正在保存讨论主题…</p>}
            {discussionState?.phase === 'UNKNOWN' && (
              <button
                type="button"
                className="ui-button"
                disabled={disabled}
                onClick={() => void discussion.retryUnknown()}
              >
                核实原主题请求
              </button>
            )}
            {discussionState?.phase === 'CONFIRMED' && (
              <button
                type="button"
                className="ui-button"
                disabled={disabled || discussionState.loading}
                onClick={() => void discussion.finish()}
              >
                读取主题保存结果
              </button>
            )}
          </div>
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
            disabled={disabled}
            placeholder={writing ? '说明要写入的内容…' : '说明本次希望讨论的问题…'}
            rows={2}
            aria-invalid={!composing && state.instruction.length > 0 && !feedback.valid}
            aria-describedby={`${effectId} ${help}`}
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
        {blocked && (
          <p id={guidanceId} className="guide-send-guidance">
            {blocked}
          </p>
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
          aria-describedby={blocked ? guidanceId : help}
          onClick={send}
        >
          <Icon name="send" />
          {state.parent ? '继续讨论' : names[state.action]}
        </button>
      </footer>
    </section>
  );
}
