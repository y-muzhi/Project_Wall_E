import { useId, useRef, useState, useSyncExternalStore } from 'react';
import type { CommentCommand, CommentOutcome } from './commands.ts';
import type { CommentScopeMode } from './commands.ts';
import { SingleSelect } from '../shared/single-select.tsx';
import type { DetailSnapshot } from '../requirements/detail-read.ts';
import { Confirmation } from '../shared/confirmation.tsx';
const labels = {
  CREATE: '添加评论',
  EDIT: '保存评论',
  RESOLVE: '解决评论',
  REOPEN: '重新打开评论',
  DELETE: '删除评论',
  MODIFY: '生成修改建议',
} as const;

/** The parent owns one flow per comment across page/historical/actual refresh.
 * Positive refresh failure is a GET retry, not a second user operation. */
export function CommentCommandControl(
  props: Readonly<{
    flow: CommentCommand;
    blocked: boolean;
    writeReady: boolean;
    readActual(): Promise<DetailSnapshot>;
    changed(outcome: CommentOutcome): void | Promise<void>;
    cancel?(): void;
    confirmOnMount?: boolean;
  }>,
) {
  const state = useSyncExternalStore(props.flow.subscribe, props.flow.getSnapshot),
    [open, setOpen] = useState(
      () =>
        props.confirmOnMount === true &&
        props.flow.intent.kind === 'DELETE' &&
        state.phase === 'READY',
    ),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null),
    pending = useRef(false);
  const intent = props.flow.intent,
    text = intent.kind === 'CREATE' || intent.kind === 'EDIT',
    active = busy || ['SUBMITTING', 'READING'].includes(state.phase),
    unknown = state.phase === 'UNKNOWN',
    help = useId();
  const scopeLocked =
    props.blocked ||
    active ||
    unknown ||
    state.phase === 'CONFIRMED' ||
    !props.writeReady ||
    !props.flow.allowed;
  const execute = async (readOnly = false) => {
    if (
      pending.current ||
      props.blocked ||
      (!readOnly && !unknown && (!props.writeReady || !props.flow.allowed))
    )
      return;
    pending.current = true;
    setBusy(true);
    setError(null);
    try {
      const confirmed = readOnly
        ? true
        : unknown
          ? await props.flow.retryUnknown(props.readActual)
          : await props.flow.submit();
      if (confirmed) {
        setOpen(false);
        const outcome = props.flow.getSnapshot().outcome;
        if (outcome) await props.changed(outcome);
      }
    } catch {
      setError('评论操作已确认，实际详情暂时无法重新读取，请重试读取');
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };
  const quote =
    intent.kind === 'CREATE'
      ? intent.target.quote
      : 'selected_text' in intent.comment.anchor_ref
        ? intent.comment.anchor_ref.selected_text
        : intent.comment.anchor_ref.block_markdown_snapshot;
  return (
    <div className="comment-command" aria-busy={active}>
      {intent.kind === 'MODIFY' && (
        <div className="comment-ai-settings">
          <p className="comment-ai-target">
            目标文档{' '}
            <strong>
              {props.flow.scopeDocument.name} · V{props.flow.scopeDocument.content_version}
            </strong>
          </p>
          <div className="comment-scope-field">
            <span aria-hidden="true">处理范围</span>
            <SingleSelect
              label="AI处理范围"
              value={state.scope_mode}
              disabled={scopeLocked}
              describedBy={help}
              options={[
                { value: 'COMMENT', label: '原评论范围' },
                { value: 'BLOCK', label: '所在区块' },
                { value: 'SECTION', label: '所在章节', disabled: !props.flow.sectionAvailable },
                { value: 'DOCUMENT', label: '整篇文档' },
              ]}
              change={(value) => props.flow.changeScope(value as CommentScopeMode)}
            />
          </div>
          <p id={help} className="comment-scope-help">
            {state.scope_mode === 'COMMENT'
              ? intent.comment.anchor_type === 'SELECTION'
                ? '仅处理这条评论标注的文字。'
                : '仅处理这条评论标注的区块。'
              : state.scope_mode === 'BLOCK'
                ? '可以调整评论所在区块中的其他文字。'
                : state.scope_mode === 'SECTION'
                  ? '可以调整评论所在章节；范围由该评论的位置确定。'
                  : '可以在本文档中提出修改建议，原评论定位不变。'}
          </p>
          {!props.flow.sectionAvailable && (
            <p className="comment-scope-help">评论位置之前没有章节标题，“所在章节”不可用。</p>
          )}
          {state.scope_review && (
            <p role="status">
              正文或评论已更新，请核对目标版本与处理范围。
              <button
                className="ui-button"
                type="button"
                disabled={
                  scopeLocked || (state.scope_mode === 'SECTION' && !props.flow.sectionAvailable)
                }
                onClick={() => props.flow.changeScope(state.scope_mode)}
              >
                已核对处理范围
              </button>
            </p>
          )}
        </div>
      )}
      {text && (
        <>
          <blockquote className="comment-quote">{quote}</blockquote>
          <label>
            评论正文
            <textarea
              className="ui-input"
              aria-label="评论正文"
              value={state.content}
              disabled={
                props.blocked ||
                active ||
                unknown ||
                state.phase === 'CONFIRMED' ||
                !props.writeReady ||
                !props.flow.allowed
              }
              onChange={(event) => props.flow.change(event.target.value)}
            />
          </label>
        </>
      )}
      {state.error && (
        <p role="alert" className="inline-error">
          {state.error}
        </p>
      )}
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
      {active && (
        <p role="status">
          {state.phase === 'READING'
            ? '正在核实评论结果…'
            : state.phase === 'CONFIRMED'
              ? '正在重新读取实际详情…'
              : '正在提交评论操作…'}
        </p>
      )}
      {state.observed && unknown && <p role="status">已读取实际状态，仍需确认原请求结果。</p>}
      {state.phase === 'CONFIRMED' ? (
        <>
          <p role="status">
            {intent.kind === 'MODIFY' ? '修改任务已接受，评论保持未解决。' : '评论操作已确认。'}
          </p>
          <button
            className="ui-button"
            type="button"
            disabled={props.blocked || active}
            onClick={() => void execute(true)}
          >
            重新读取评论与详情
          </button>
        </>
      ) : (
        <button
          className={'ui-button' + (intent.kind === 'MODIFY' ? ' primary' : '')}
          type="button"
          disabled={
            props.blocked ||
            active ||
            (!unknown &&
              (!props.writeReady ||
                !props.flow.allowed ||
                (intent.kind === 'MODIFY' &&
                  (state.scope_review ||
                    (state.scope_mode === 'SECTION' && !props.flow.sectionAvailable)))))
          }
          onClick={() => (intent.kind === 'DELETE' ? setOpen(true) : void execute())}
        >
          {unknown ? '重新确认评论操作结果' : labels[intent.kind]}
        </button>
      )}
      {props.cancel && state.phase !== 'CONFIRMED' && (
        <button className="ui-button" type="button" disabled={active} onClick={props.cancel}>
          {unknown ? '保留请求并关闭编辑区' : intent.kind === 'MODIFY' ? '取消' : '取消编辑'}
        </button>
      )}
      <Confirmation
        open={open}
        dangerous
        title="删除评论？"
        description="确认后评论将从默认列表移除，历史来源会保留。"
        busy={active}
        confirmDisabled={props.blocked || (!unknown && (!props.writeReady || !props.flow.allowed))}
        error={state.error}
        confirmLabel={unknown ? '重新确认删除结果' : '确认删除'}
        cancelLabel={unknown ? '保留请求并关闭弹窗' : '保留评论'}
        cancel={() => {
          setOpen(false);
          if (!unknown) props.cancel?.();
        }}
        confirm={() => void execute()}
      />
    </div>
  );
}
