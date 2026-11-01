import { useId, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import { Icon } from '../shared/icon.tsx';
import { EmptyState } from '../shared/empty-state.tsx';
import { createPortal } from 'react-dom';
import type { CommentItem } from '../api/models.ts';
import type {
  RequirementDocumentOwner,
  CurrentDocumentBinding,
} from '../requirements/document-owner.ts';
import { BlockAuxiliary } from '../documents/navigation-view.tsx';
import { CommentList, CommentMarkerLayer } from './components.tsx';
import { CommentCommandControl } from './command-control.tsx';
import { commentTarget } from './target.ts';
import { locateComment } from './locate.ts';
import {
  documentSelectionToolbarPosition,
  observeDocumentSelection,
} from '../documents/selection-surface.ts';
import type { RequirementCommentPanel, CommentSlot } from './panel-owner.ts';

function Operation({
  panel,
  slot,
}: Readonly<{ panel: RequirementCommentPanel; slot: CommentSlot }>) {
  const state = slot.flow.getSnapshot(),
    current = panel.getSnapshot().detail.current,
    intent = slot.flow.intent,
    id = useId(),
    trigger = useRef<HTMLButtonElement>(null);
  if (!slot.open && intent.kind !== 'MODIFY')
    return (
      <button
        className="ui-button"
        type="button"
        disabled={panel.blocked}
        onClick={() => panel.open(slot.flow)}
      >
        继续处理未确认评论操作
      </button>
    );
  return (
    <>
      {intent.kind === 'MODIFY' && (
        <button
          ref={trigger}
          className="ui-button comment-ai-toggle"
          type="button"
          aria-expanded={slot.open}
          aria-controls={id}
          disabled={panel.blocked}
          onClick={() => (slot.open ? panel.collapse(slot.flow) : panel.open(slot.flow))}
        >
          <Icon name="settings" />
          AI处理设置
          <Icon name={slot.open ? 'up' : 'down'} />
        </button>
      )}
      <div
        id={id}
        className="motion-disclosure"
        hidden={!slot.open}
        inert={!slot.open}
        aria-hidden={!slot.open}
        onKeyDown={(event) => {
          if (
            intent.kind === 'MODIFY' &&
            event.key === 'Escape' &&
            !event.defaultPrevented &&
            !['SUBMITTING', 'READING'].includes(state.phase)
          ) {
            event.preventDefault();
            panel.collapse(slot.flow);
            trigger.current?.focus();
          }
        }}
      >
        {intent.kind === 'CREATE' &&
          (intent.target.document_id !== current?.id ||
            intent.target.content_version !== current?.content_version) && (
            <p role="status">正文已变化，请在当前正文重新选择评论范围；输入仍保留。</p>
          )}
        <CommentCommandControl
          key={slot.key}
          flow={slot.flow}
          blocked={panel.blocked}
          writeReady={panel.writable(slot.flow)}
          readActual={panel.observe}
          changed={(outcome) => panel.finish(slot.flow, outcome)}
          cancel={() => panel.close(slot.flow)}
          confirmOnMount
        />
        {slot.identity !== null &&
          ['READY', 'ERROR'].includes(state.phase) &&
          !panel.comments
            .getSnapshot()
            .confirmed?.items.some((row) => row.id === slot.identity) && (
            <button
              className="ui-button"
              type="button"
              disabled={panel.blocked}
              onClick={() => void panel.select(slot.identity!)}
            >
              返回评论所在页
            </button>
          )}
      </div>
    </>
  );
}
function CardActions({
  panel,
  comment,
  toolsHost,
}: Readonly<{
  panel: RequirementCommentPanel;
  comment: CommentItem;
  toolsHost: HTMLElement | null;
}>) {
  type Action = 'EDIT' | 'MODIFY' | 'DELETE' | 'RESOLVE' | 'REOPEN';
  const operation = useRef<HTMLDivElement>(null),
    hadSlot = useRef(false),
    lastAction = useRef<Action>('EDIT');
  const statusTrigger = useRef<HTMLButtonElement>(null),
    editTrigger = useRef<HTMLButtonElement>(null),
    deleteTrigger = useRef<HTMLButtonElement>(null),
    modifyTrigger = useRef<HTMLButtonElement>(null);
  const triggers = {
    EDIT: editTrigger,
    DELETE: deleteTrigger,
    MODIFY: modifyTrigger,
    RESOLVE: statusTrigger,
    REOPEN: statusTrigger,
  };
  const disabledHelp = useId();
  const slot = panel.slot(comment.id);
  useLayoutEffect(() => {
    if (slot?.open && slot.flow.intent.kind === 'EDIT')
      operation.current
        ?.querySelector<HTMLTextAreaElement>('textarea:not(:disabled)')
        ?.focus({ preventScroll: true });
    if (slot?.open && slot.flow.intent.kind === 'MODIFY')
      operation.current
        ?.querySelector<HTMLButtonElement>('[role=combobox]:not(:disabled)')
        ?.focus({ preventScroll: true });
    if (!slot && hadSlot.current)
      triggers[lastAction.current].current?.focus({ preventScroll: true });
    hadSlot.current = slot !== null;
  }, [slot?.key, slot?.open]);
  const beginOperation = (kind: 'EDIT' | 'MODIFY' | 'DELETE') => {
    lastAction.current = kind;
    panel.begin(comment.id, kind);
  };
  const execute = (kind: 'RESOLVE' | 'REOPEN') => {
    lastAction.current = kind;
    const flow = panel.begin(comment.id, kind);
    if (flow) void panel.submit(flow);
  };
  // Retained requests and inputs stay visible until the owner adopts actual results.
  if (slot)
    return (
      <div className="comment-operation" ref={operation}>
        <Operation panel={panel} slot={slot} />
      </div>
    );
  const allowed = panel.writeReady,
    orphan = comment.anchor_status === 'ORPHANED' || comment.location.status === 'ORPHANED';
  const statusLabel = comment.status === 'OPEN' ? '解决评论并隐藏' : '重新打开评论';
  const disabledReason = allowed
    ? null
    : (panel.writeUnavailableReason ?? '评论暂不可修改，请重新读取评论与正文。');
  return (
    <div className="comment-action-group">
      {toolsHost &&
        createPortal(
          <div className="comment-card-tools" role="group" aria-label="评论操作">
            {disabledReason && (
              <span id={disabledHelp} className="sr-only">
                {disabledReason}
              </span>
            )}
            <span className="comment-tool-slot" title={disabledReason ?? statusLabel}>
              <button
                ref={statusTrigger}
                className="ui-button icon-button comment-tool-button"
                type="button"
                aria-label={statusLabel}
                title={disabledReason ?? statusLabel}
                disabled={!allowed}
                aria-describedby={disabledReason ? disabledHelp : undefined}
                onClick={() => execute(comment.status === 'OPEN' ? 'RESOLVE' : 'REOPEN')}
              >
                <Icon name={comment.status === 'OPEN' ? 'check' : 'reopen'} />
              </button>
            </span>
            {comment.status === 'OPEN' && (
              <span className="comment-tool-slot" title={disabledReason ?? '编辑评论'}>
                <button
                  ref={editTrigger}
                  className="ui-button icon-button comment-tool-button"
                  type="button"
                  aria-label="编辑评论"
                  title={disabledReason ?? '编辑评论'}
                  disabled={!allowed}
                  aria-describedby={disabledReason ? disabledHelp : undefined}
                  onClick={() => beginOperation('EDIT')}
                >
                  <Icon name="edit" />
                </button>
              </span>
            )}
            <span className="comment-tool-slot" title={disabledReason ?? '删除评论'}>
              <button
                ref={deleteTrigger}
                className="ui-button icon-button comment-tool-button comment-destructive"
                type="button"
                aria-label="删除评论"
                title={disabledReason ?? '删除评论'}
                disabled={!allowed}
                aria-describedby={disabledReason ? disabledHelp : undefined}
                onClick={() => beginOperation('DELETE')}
              >
                <Icon name="trash" />
              </button>
            </span>
          </div>,
          toolsHost,
        )}
      {comment.status === 'OPEN' && !orphan && (
        <button
          ref={modifyTrigger}
          className="ui-button comment-action"
          type="button"
          aria-label="根据评论提出修改建议"
          title={disabledReason ?? '根据评论提出修改建议'}
          aria-describedby={disabledReason ? disabledHelp : undefined}
          disabled={!allowed}
          onClick={() => beginOperation('MODIFY')}
        >
          <Icon name="robot" />
          提出修改建议
        </button>
      )}
    </div>
  );
}

/** All current-comment UI disappears in history. The parent owner stays alive,
 * so late write receipts, unknown requests and unsent inputs remain recoverable. */
export function CommentPanel({
  panel,
  documents,
}: Readonly<{ panel: RequirementCommentPanel; documents: RequirementDocumentOwner }>) {
  const state = useSyncExternalStore(panel.subscribe, panel.getSnapshot),
    read = useSyncExternalStore(panel.comments.subscribe, panel.comments.getSnapshot);
  const documentState = useSyncExternalStore(documents.subscribe, documents.getSnapshot),
    binding = documents.currentBinding;
  if (state.view === 'HISTORY' || documentState.mode === 'HISTORY')
    return <EmptyState icon="history" message="历史版本不显示评论" fill />;
  if (
    documentState.mode === 'EMPTY' &&
    state.slots.length === 0 &&
    !state.error &&
    !read.error &&
    !read.loading &&
    !state.refreshing
  )
    return <EmptyState icon="comment" message="请先选择文档" fill />;
  const visible = new Set(read.confirmed?.items.map((row) => row.id) ?? []),
    offPage = state.slots.filter((slot) => slot.identity !== null && !visible.has(slot.identity)),
    creation = panel.slot(null);
  return (
    <section aria-label="需求评论" className="requirement-comments">
      <header className="read-section-heading">
        <strong>
          评论
          {read.confirmed && (
            <span className="comment-count">{read.confirmed.index.total_count}</span>
          )}
        </strong>
        <span className="read-status" role="status">
          {state.refreshing || read.loading ? '正在读取评论…' : ''}
        </span>
      </header>
      {state.suspended && <p role="status">评论操作已暂停，输入和未确认请求仍保留。</p>}
      {state.view === 'MANUAL' && <p role="status">评论关联正式正文，人工草稿尚未生效。</p>}
      {panel.writeUnavailableReason && (
        <p className="comment-availability" role="status">
          {panel.writeUnavailableReason}
        </p>
      )}
      {state.error && (
        <p role="alert" className="inline-error">
          {state.error}
        </p>
      )}
      {(state.error || state.needs_refresh) && (
        <button
          className="ui-button"
          type="button"
          disabled={panel.blocked || state.refreshing}
          onClick={() => void panel.refresh().catch(() => undefined)}
        >
          重新读取评论与正文
        </button>
      )}
      {creation && (
        <section aria-label="新建评论" className="comment-composer-card">
          <header className="comment-composer-heading">
            <Icon name="comment" />
            <strong>添加评论</strong>
          </header>
          <Operation panel={panel} slot={creation} />
        </section>
      )}
      {offPage.length > 0 && (
        <section aria-label="保留的评论操作">
          <p>以下操作仍保留；列表继续按创建时间分页。</p>
          {offPage.map((slot) => (
            <div key={slot.key} data-retained-comment={slot.identity}>
              <Operation panel={panel} slot={slot} />
            </div>
          ))}
        </section>
      )}
      <CommentList
        comments={panel.comments}
        blocked={panel.blocked || state.refreshing}
        locateReady={binding !== null}
        keepVisible={(identity) => panel.slot(identity) !== null}
        locate={(identity) =>
          binding !== null &&
          locateComment(panel.comments, binding.editor, binding.navigation, identity)
        }
        changePage={(page) => void panel.page(page)}
        retry={() => void panel.refresh().catch(() => undefined)}
        actions={(comment, toolsHost) => (
          <CardActions panel={panel} comment={comment} toolsHost={toolsHost} />
        )}
      />
    </section>
  );
}

function CreationEntries({
  panel,
  documents,
  binding,
  openPanel,
}: Readonly<{
  panel: RequirementCommentPanel;
  documents: RequirementDocumentOwner;
  binding: CurrentDocumentBinding;
  openPanel?: () => void;
}>) {
  const navigation = useSyncExternalStore(
      binding.navigation.subscribe,
      binding.navigation.getSnapshot,
    ),
    documentState = useSyncExternalStore(documents.subscribe, documents.getSnapshot),
    selection = documentState.selection,
    id = useId();
  const [selectionPosition, setSelectionPosition] = useState<{ left: number; top: number } | null>(
      null,
    ),
    [dismissedSelection, setDismissedSelection] = useState<typeof selection>(null);
  const selectionSurface = useRef<ReturnType<typeof observeDocumentSelection> | null>(null),
    repositionSelection = useRef<() => void>(() => {});
  repositionSelection.current = () => {
    if (!selection || selection === dismissedSelection || selectionSurface.current?.selecting) {
      setSelectionPosition(null);
      return;
    }
    const next = documentSelectionToolbarPosition(binding.root, 116, 40);
    setSelectionPosition((previous) =>
      previous?.left === next?.left && previous?.top === next?.top ? previous : next,
    );
  };
  useLayoutEffect(() => {
    const editorDOM = binding.root.querySelector<HTMLElement>('.ProseMirror');
    if (!editorDOM) return;
    const surface = observeDocumentSelection(editorDOM, () => repositionSelection.current());
    selectionSurface.current = surface;
    return () => {
      surface.destroy();
      selectionSurface.current = null;
    };
  }, [binding]);
  useLayoutEffect(() => repositionSelection.current(), [binding, selection, dismissedSelection]);
  const reason = panel.writeUnavailableReason,
    blockReason = reason ?? (navigation.selected_block === null ? '请先选择正文区块。' : null),
    selectionReason =
      reason ?? (selection === null ? '请先选中同一正文区块内的文字，再评论选区。' : null);
  const create = (range: boolean) => {
    try {
      const block = range ? selection?.block_id : navigation.selected_block;
      if (block !== null && block !== undefined) {
        if (panel.create(commentTarget(binding.editor, block, range ? selection : null)))
          openPanel?.();
      } else panel.rejectTarget();
    } catch {
      panel.rejectTarget();
    }
  };
  return (
    <>
      <BlockAuxiliary
        navigation={binding.navigation}
        extra={
          <>
            <span title={blockReason ?? '评论当前区块'}>
              <button
                className="ui-button comment-entry"
                role="menuitem"
                type="button"
                title={blockReason ?? undefined}
                aria-describedby={blockReason ? id + '-block' : undefined}
                disabled={blockReason !== null}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => create(false)}
              >
                <Icon name="comment" />
                评论区块
              </button>
            </span>
            {blockReason && (
              <span id={id + '-block'} className="block-comment-help">
                {blockReason}
              </span>
            )}
          </>
        }
      />
      {selectionPosition &&
        createPortal(
          <div
            className="block-selection-comment"
            role="group"
            aria-label="选区评论"
            style={selectionPosition}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                setDismissedSelection(selection);
              }
            }}
          >
            <button
              className="ui-button comment-entry"
              type="button"
              title={selectionReason ?? undefined}
              aria-describedby={selectionReason ? id + '-selection' : undefined}
              disabled={selectionReason !== null}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => create(true)}
            >
              <Icon name="comment" />
              评论选区
            </button>
            {selectionReason && (
              <span id={id + '-selection'} className="block-comment-help">
                {selectionReason}
              </span>
            )}
          </div>,
          document.body,
        )}
    </>
  );
}
export function CommentDocumentTools({
  panel,
  documents,
  openPanel,
}: Readonly<{
  panel: RequirementCommentPanel;
  documents: RequirementDocumentOwner;
  openPanel?: () => void;
}>) {
  const state = useSyncExternalStore(panel.subscribe, panel.getSnapshot);
  useSyncExternalStore(documents.subscribe, documents.getSnapshot);
  const binding = documents.currentBinding;
  const creation = panel.slot(null),
    creationIntent = creation?.flow.intent;
  const draft = creationIntent?.kind === 'CREATE' ? creationIntent.target : null;
  if (panel.blocked || state.view !== 'CURRENT' || binding === null) return null;
  return (
    <>
      <CreationEntries
        panel={panel}
        documents={documents}
        binding={binding}
        {...(openPanel ? { openPanel } : {})}
      />
      {createPortal(
        <CommentMarkerLayer
          comments={panel.comments}
          draft={draft}
          editor={binding.editor}
          documentRoot={binding.root}
          navigation={binding.navigation}
          blocked={state.refreshing}
          select={(identity) => {
            openPanel?.();
            void panel.select(identity);
          }}
        />,
        binding.root.parentElement!,
      )}
    </>
  );
}
