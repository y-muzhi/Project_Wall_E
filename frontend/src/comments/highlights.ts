import type { EditorView } from '@milkdown/kit/prose/view';
import type { Node as ProseNode } from '@milkdown/kit/prose/model';
import type { DocumentReadModel } from '../documents/contracts.ts';
import { blockProjection } from '../documents/editor-source.ts';
import { editorRangeForSelection } from '../documents/editor-selection.ts';
import { codepointToUtf16, selectionFromProjectedText } from '../documents/selection.ts';
import type { SelectionEvent } from '../documents/selection.ts';
import type { CommentIndex } from './read.ts';
import type { CommentTarget } from './commands.ts';

let highlightIdentity = 0;
type Block = Readonly<{ node: ProseNode; position: number; element: HTMLElement }>;

function selectionRange(
  view: EditorView,
  current: DocumentReadModel,
  block: Block,
  selection: SelectionEvent | null,
): Range {
  const range = block.element.ownerDocument.createRange();
  if (!selection) range.selectNodeContents(block.element);
  else {
    const projected = editorRangeForSelection(
      view.state,
      { document_id: current.id, content_version: current.content_version },
      selection,
    );
    if (projected.node_selection) range.selectNodeContents(block.element);
    else {
      const start = view.domAtPos(projected.from, 1),
        end = view.domAtPos(projected.to, -1);
      range.setStart(start.node, start.offset);
      range.setEnd(end.node, end.offset);
    }
  }
  return range;
}

/** Paints immutable CURRENT ranges without a transaction, DOM marks, focus or IO.
 * Each document owns registry names and releases only its own highlights. */
export class CommentHighlights {
  private readonly root: HTMLElement;
  private readonly names: readonly [string, string, string];
  private readonly stylesheet: HTMLStyleElement | null;
  constructor(root: HTMLElement) {
    this.root = root;
    const key = 'walle-comment-' + ++highlightIdentity;
    this.names = [key, key + '-active', key + '-resolved'];
    this.stylesheet = null;
    if (typeof Highlight === 'undefined' || typeof CSS === 'undefined' || !CSS.highlights) return;
    this.stylesheet = root.ownerDocument.createElement('style');
    this.stylesheet.textContent =
      '::highlight(' +
      this.names[0] +
      ') { background-color: var(--comment-mark); }' +
      '::highlight(' +
      this.names[1] +
      ') { background-color: var(--comment-mark-active); }' +
      '::highlight(' +
      this.names[2] +
      ') { background-color: var(--success-soft); text-decoration: underline; }' +
      '@media (forced-colors: active) { ::highlight(' +
      this.names.join('), ::highlight(') +
      ') { background-color: Highlight; color: HighlightText; } }';
    root.ownerDocument.head.append(this.stylesheet);
  }
  paint(
    view: EditorView,
    current: DocumentReadModel,
    index: CommentIndex,
    selected: number | null,
    draft: CommentTarget | null,
    hidden: ReadonlySet<number>,
  ): void {
    this.clear();
    if (
      !this.stylesheet ||
      current.document_type !== 'CURRENT' ||
      index.document_id !== current.id ||
      index.requirement_id !== current.requirement_id ||
      index.content_version !== current.content_version
    )
      return;
    const blocks = new Map<number, Block>();
    view.state.doc.forEach((node, position) => {
      const identity = node.attrs.walle_block_id as number;
      if (hidden.has(identity)) return;
      const element = view.nodeDOM(position);
      if (element instanceof HTMLElement && this.root.contains(element))
        blocks.set(identity, { node, position, element });
    });
    const normal: Range[] = [],
      active: Range[] = [],
      resolved: Range[] = [];
    for (const comment of index.comments) {
      if (
        comment.anchor_status !== 'ATTACHED' ||
        comment.location.status !== 'ATTACHED' ||
        (comment.status !== 'OPEN' && comment.id !== selected)
      )
        continue;
      const blockId = comment.location.block_id;
      const block = blockId === null ? undefined : blocks.get(blockId);
      if (!block || blockId === null) continue;
      try {
        let selection: SelectionEvent | null = null;
        if (comment.location.start_offset !== null && comment.location.end_offset !== null) {
          const text = blockProjection(block.node);
          selection = selectionFromProjectedText(
            {
              document_id: current.id,
              content_version: current.content_version,
              block_id: blockId,
            },
            text,
            codepointToUtf16(text, comment.location.start_offset),
            codepointToUtf16(text, comment.location.end_offset),
          );
        }
        const range = selectionRange(view, current, block, selection);
        if (range.collapsed) continue;
        if (comment.status === 'RESOLVED') resolved.push(range);
        else (comment.id === selected ? active : normal).push(range);
      } catch {
        // An unrepresentable atom/virtual endpoint is never replaced by a guess.
      }
    }
    if (
      draft &&
      draft.document_id === current.id &&
      draft.content_version === current.content_version
    ) {
      const block = blocks.get(draft.block_id);
      if (block) {
        try {
          const range = selectionRange(view, current, block, draft.selection);
          if (!range.collapsed) active.push(range);
        } catch {
          // A changed or stale draft keeps its original quote, not a false mark.
        }
      }
    }
    for (const [position, ranges] of [normal, active, resolved].entries()) {
      if (!ranges.length) continue;
      const highlight = new Highlight();
      for (const range of ranges) highlight.add(range);
      highlight.priority = position;
      CSS.highlights.set(this.names[position]!, highlight);
    }
  }
  clear(): void {
    if (this.stylesheet) for (const name of this.names) CSS.highlights.delete(name);
  }
  destroy(): void {
    this.clear();
    this.stylesheet?.remove();
  }
}
