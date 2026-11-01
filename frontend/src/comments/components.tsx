import { Icon } from '../shared/icon.tsx';
import { EmptyState } from '../shared/empty-state.tsx';
import { useEffect, useId, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import { editorViewCtx } from '@milkdown/kit/core';
import type { ReactNode } from 'react';
import type { CommentItem } from '../api/models.ts';
import { Pagination } from '../shared/pagination.tsx';
import { localTime } from '../shared/time.ts';
import type { RequirementComments } from './read.ts';
import type { RequirementEditor } from '../documents/editor.ts';
import { editorReadModel } from '../documents/contracts.ts';
import type { DocumentNavigation } from '../documents/navigation.ts';
import { CommentHighlights } from './highlights.ts';
import type { CommentTarget } from './commands.ts';

type CommentActions = (comment: CommentItem, toolsHost: HTMLElement | null) => ReactNode;
function CommentCard({
  comment,
  selected,
  blocked,
  locateReady,
  commentsReady,
  indicate,
  actions,
}: Readonly<{
  comment: CommentItem;
  selected: boolean;
  blocked: boolean;
  locateReady: boolean;
  commentsReady: boolean;
  indicate(identity: number): void;
  actions: CommentActions | undefined;
}>) {
  const [toolsHost, setToolsHost] = useState<HTMLElement | null>(null);

  const orphan = comment.anchor_status === 'ORPHANED' || comment.location.status === 'ORPHANED',
    quote =
      'selected_text' in comment.anchor_ref
        ? comment.anchor_ref.selected_text
        : comment.anchor_ref.block_markdown_snapshot;
  return (
    <article
      tabIndex={-1}
      data-comment-id={comment.id}
      key={comment.id}
      aria-label={'评论：' + [...comment.content].slice(0, 40).join('')}
      className={
        'comment-card' +
        (comment.status === 'RESOLVED' ? ' is-resolved' : '') +
        (orphan ? ' is-orphaned' : '') +
        (selected ? ' is-selected' : '')
      }
      onClick={(event) => {
        if (
          orphan ||
          !(event.target instanceof Element) ||
          event.target.closest('button,a,input,textarea,label,select') ||
          window.getSelection()?.isCollapsed === false
        )
          return;
        indicate(comment.id);
      }}
    >
      <div className={'comment-card-reference' + (actions ? ' has-tools' : '')}>
        <blockquote className="comment-quote">{quote}</blockquote>
        {actions && <div className="comment-card-tools-host" ref={setToolsHost} />}
      </div>
      <div className="comment-status">
        <span className="comment-state">{comment.status === 'OPEN' ? '未解决' : '已解决'}</span>
        <span className="comment-anchor-state">
          锚点：{comment.anchor_status === 'ORPHANED' ? '已失效' : '有效'}
        </span>
        <span className="comment-location-label">{orphan ? '当前位置已失效' : '当前可定位'}</span>
        <time dateTime={comment.created_at}>{localTime(comment.created_at)}</time>
      </div>
      {orphan && (
        <p className="comment-orphan-warning">
          <Icon name="warning" />
          <span>以下是创建评论时的历史引用，当前正文位置已失效。</span>
        </p>
      )}
      <p className="comment-content">{comment.content}</p>
      <div className="comment-actions">
        <button
          className="ui-button comment-action"
          type="button"
          disabled={blocked || !locateReady || orphan || !commentsReady}
          onClick={() => indicate(comment.id)}
        >
          <Icon name="locate" />
          定位正文
        </button>
        {actions?.(comment, toolsHost)}
      </div>
    </article>
  );
}

export function CommentList({
  comments,
  locate,
  actions,
  keepVisible,
  blocked = false,
  locateReady = true,
  changePage,
  retry,
}: Readonly<{
  comments: RequirementComments;
  locate(identity: number): boolean;
  actions?: CommentActions;
  keepVisible?: (identity: number) => boolean;
  blocked?: boolean;
  locateReady?: boolean;
  changePage?: (page: number) => void;
  retry?: () => void;
}>) {
  const state = useSyncExternalStore(comments.subscribe, comments.getSnapshot),
    list = useRef<HTMLDivElement>(null),
    [locationError, setLocationError] = useState<string | null>(null),
    [showResolved, setShowResolved] = useState(false),
    resolvedToggle = useRef<HTMLButtonElement>(null),
    resolvedId = useId();
  const items = state.confirmed?.items ?? [];
  const visible = items.filter((comment) => comment.status === 'OPEN' || keepVisible?.(comment.id));
  const resolved = items.filter(
    (comment) => comment.status === 'RESOLVED' && !keepVisible?.(comment.id),
  );
  const selectedResolved = resolved.some((comment) => comment.id === state.selected);
  const resolvedVisible = showResolved || selectedResolved;
  const toggleResolved = () => {
    setShowResolved(!resolvedVisible);
    if (resolvedVisible && selectedResolved && state.selected !== null)
      comments.hideResolved(state.selected);
  };
  useLayoutEffect(() => setShowResolved(false), [state.resolved_revision]);
  useEffect(() => {
    if (!state.resolved_revision || document.activeElement !== document.body) return;
    const visibleCard = Array.from(
      list.current?.querySelectorAll<HTMLElement>('.comment-card') ?? [],
    ).find((card) => card.getClientRects().length > 0);
    (visibleCard ?? resolvedToggle.current ?? list.current)?.focus({ preventScroll: true });
  }, [state.resolved_revision]);
  const indicate = (identity: number) => {
    if (blocked || !locateReady || !comments.ready) return;
    if (locate(identity)) {
      comments.markLocated(identity);
      setLocationError(null);
    } else setLocationError('当前正文或评论位置无法定位，请重新读取评论及关联详情。');
  };
  useEffect(() => {
    if (state.selected !== null && !state.loading && !state.error) {
      const card = list.current?.querySelector<HTMLElement>(
        '[data-comment-id="' + state.selected + '"]',
      );
      card?.scrollIntoView({ block: 'nearest' });
      card?.focus({ preventScroll: true });
    }
  }, [state.selection_revision]);
  const renderComment = (comment: CommentItem) => (
    <CommentCard
      key={comment.id}
      comment={comment}
      selected={state.selected === comment.id}
      blocked={blocked}
      locateReady={locateReady}
      commentsReady={comments.ready}
      indicate={indicate}
      actions={actions}
    />
  );
  return (
    <section className="comment-panel" aria-label="评论列表" aria-busy={state.loading}>
      {!state.active && <p role="status">当前评论交互已暂停</p>}
      {state.loading && !state.confirmed && <p role="status">正在读取评论</p>}
      {state.error && (
        <p role="alert">
          {state.error}{' '}
          <button
            className="ui-button"
            type="button"
            disabled={blocked || state.loading || !state.active}
            onClick={() => (retry ? retry() : void comments.refresh())}
          >
            重试读取评论
          </button>
        </p>
      )}
      <div ref={list} className="comment-list-content" tabIndex={-1}>
        <div className="comment-list-rows">{visible.map(renderComment)}</div>
        {resolved.length > 0 && (
          <section className="comment-resolved-section" aria-label="本页已解决评论">
            <button
              ref={resolvedToggle}
              className="ui-button comment-resolved-toggle"
              type="button"
              disabled={blocked || state.loading || !state.active}
              aria-expanded={resolvedVisible}
              aria-controls={resolvedId}
              onClick={toggleResolved}
            >
              <Icon name={resolvedVisible ? 'up' : 'down'} />
              已解决（本页 {resolved.length}）
            </button>
            <div
              id={resolvedId}
              className="comment-list-rows comment-resolved-list"
              hidden={!resolvedVisible}
              inert={!resolvedVisible}
              aria-hidden={!resolvedVisible}
            >
              {resolved.map(renderComment)}
            </div>
          </section>
        )}
      </div>
      {locationError && (
        <p role="alert">
          {locationError}{' '}
          <button
            className="ui-button"
            type="button"
            disabled={blocked || state.loading || !state.active}
            onClick={() => (retry ? retry() : void comments.refresh())}
          >
            重新读取评论与正文
          </button>
        </p>
      )}
      {items.length > 0 &&
        visible.length === 0 &&
        !resolvedVisible &&
        !state.loading &&
        !state.error && <EmptyState icon="comment" message="本页暂无未解决评论" />}
      {state.confirmed?.items.length === 0 && !state.loading && !state.error && (
        <EmptyState
          icon="comment"
          message={state.confirmed.pagination.total ? '当前页暂无评论' : '暂无评论'}
        />
      )}
      {state.confirmed && (
        <Pagination
          compactSingle
          value={state.confirmed.pagination}
          loading={blocked || state.loading || !state.active}
          showLoadingStatus={false}
          change={(page) => (changePage ? changePage(page) : void comments.refresh(page))}
        />
      )}
    </section>
  );
}

/** A block auxiliary control consumes the whole I37 count, not the visible
 * page. Parent places it beside that actual CURRENT block. */
export function BlockCommentMarker({
  comments,
  blockId,
  blocked = false,
  select,
}: Readonly<{
  comments: RequirementComments;
  blockId: number;
  blocked?: boolean;
  select?: (identity: number) => void;
}>) {
  const state = useSyncExternalStore(comments.subscribe, comments.getSnapshot),
    block = state.confirmed?.index.blocks.find((row) => row.block_id === blockId);
  if (!block) return null;
  return (
    <button
      type="button"
      className="ui-button comment-marker"
      data-comment-block={blockId}
      disabled={blocked || !comments.ready}
      aria-label={block.open_count + '条未解决评论'}
      onClick={() =>
        select ? select(block.comment_ids[0]!) : void comments.select(block.comment_ids[0]!)
      }
    >
      <Icon name="comment" />
      <span>{block.open_count}</span>
    </button>
  );
}

/** Owned sibling overlay, outside ProseMirror/Markdown. The parent gives it
 * the same relative container and CURRENT root; history hides it explicitly. */
export function CommentMarkerLayer({
  comments,
  editor,
  documentRoot,
  navigation,
  visible = true,
  blocked = false,
  select,
  draft = null,
}: Readonly<{
  comments: RequirementComments;
  draft?: CommentTarget | null;
  editor: RequirementEditor;
  documentRoot: HTMLElement;
  navigation: DocumentNavigation;
  visible?: boolean;
  blocked?: boolean;
  select?: (identity: number) => void;
}>) {
  const state = useSyncExternalStore(comments.subscribe, comments.getSnapshot),
    [positions, setPositions] = useState<readonly Readonly<{ id: number; top: number }>[]>([]);
  useLayoutEffect(() => {
    const highlights = new CommentHighlights(documentRoot);
    const paint = () => {
      const confirmed = state.confirmed,
        displayed = editor.loadedDocument;
      if (
        !visible ||
        !confirmed ||
        !editor.valid ||
        displayed.document_type !== 'CURRENT' ||
        JSON.stringify(editorReadModel(displayed)) !==
          JSON.stringify(editorReadModel(confirmed.current))
      ) {
        highlights.clear();
        return;
      }
      editor.action((ctx) =>
        highlights.paint(
          ctx.get(editorViewCtx),
          confirmed.current,
          confirmed.index,
          state.selected,
          draft,
          new Set(navigation.getSnapshot().hidden_blocks),
        ),
      );
    };
    paint();
    const release = navigation.subscribe(paint);
    return () => {
      release();
      highlights.destroy();
    };
  }, [state.confirmed, state.selected, editor, documentRoot, navigation, visible, draft]);

  useEffect(() => {
    const measure = () => {
      const current = state.confirmed?.current,
        displayed = editor.loadedDocument;
      if (
        !visible ||
        !current ||
        !editor.valid ||
        displayed.document_type !== 'CURRENT' ||
        JSON.stringify(editorReadModel(displayed)) !== JSON.stringify(editorReadModel(current)) ||
        !documentRoot.getClientRects().length
      ) {
        setPositions([]);
        return;
      }
      const box = documentRoot.getBoundingClientRect();
      const hidden = new Set(navigation.getSnapshot().hidden_blocks);
      const result = editor.action((ctx) => {
        const view = ctx.get(editorViewCtx),
          positions: { id: number; top: number }[] = [];
        view.state.doc.forEach((node, offset) => {
          if (hidden.has(node.attrs.walle_block_id as number)) return;
          if (
            !state.confirmed!.index.blocks.some(
              (block) => block.block_id === node.attrs.walle_block_id,
            )
          )
            return;
          const dom = view.nodeDOM(offset);
          if (dom instanceof HTMLElement && dom.getClientRects().length)
            positions.push({
              id: node.attrs.walle_block_id as number,
              top: dom.getBoundingClientRect().top - box.top,
            });
        });
        return positions;
      });
      setPositions(result);
    };
    measure();
    const releaseNavigation = navigation.subscribe(measure);
    const resize = new ResizeObserver(measure);
    resize.observe(documentRoot);
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    return () => {
      releaseNavigation();
      resize.disconnect();
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure, true);
    };
  }, [state.confirmed, editor, documentRoot, visible, navigation]);
  return (
    <div className="comment-marker-layer" aria-label="正文评论标记">
      {positions.map((position) => (
        <div key={position.id} style={{ top: position.top }}>
          <BlockCommentMarker
            comments={comments}
            blockId={position.id}
            blocked={blocked}
            {...(select ? { select } : {})}
          />
        </div>
      ))}
    </div>
  );
}
