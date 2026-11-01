import { editorViewCtx } from '@milkdown/kit/core';
import type { Ctx } from '@milkdown/kit/ctx';
import { validateBlockState } from './contracts.ts';
import type { BlockMetadata } from './contracts.ts';
import type { EditedSnapshot } from './edited-snapshot.ts';
import { bindIdentityDocument } from './identity.ts';
import type { RequirementEditor } from './editor.ts';
import type { RevisionViewer } from '../revisions/viewer.ts';
import { DocumentBlockHighlight } from './block-highlight.ts';
import { TextSelection } from '@milkdown/kit/prose/state';
import {
  DocumentSectionVisibility,
  foldedBlockIds,
  foldedTransactionEffect,
  headingSections,
  selectionTouchesBlocks,
} from './section-folding.ts';
import type { HeadingSection } from './section-folding.ts';

export type OutlineEntry = Readonly<{
  block_id: number;
  level: number;
  depth: number;
  text: string;
}>;
export type NavigationContent = Readonly<{
  kind: 'CURRENT' | 'MANUAL_DRAFT' | 'REVISION';
  blocks: readonly BlockMetadata[];
  outline: readonly OutlineEntry[];
}>;
export type NavigationState = Readonly<{
  content: NavigationContent | null;
  active_heading: number | null;
  selected_block: number | null;
  source_block: number | null;
  toolbar: Readonly<{ left: number; top: number }> | null;
  collapsed_headings: readonly number[];
  foldable_headings: readonly number[];
  hidden_blocks: readonly number[];
  heading_controls: readonly Readonly<{ block_id: number; left: number; top: number }>[];
  error: string | null;
}>;
interface NavigationPort {
  read(): NavigationContent;
  element(blockId: number): HTMLElement | null;
  prepareCollapse?(heading: number, hidden: ReadonlySet<number>): void;
}

/** Align 24×28 controls to the first line; reserve the 8px fold gap only when needed. */
export function blockControlPositions(
  block: Readonly<{ left: number; top: number }>,
  bounds: Readonly<{ left: number; right: number; top: number; bottom: number }>,
  lineHeight: number,
  hasFoldControl: boolean,
  paddingTop = 0,
) {
  const top = Math.max(
      bounds.top + 4,
      Math.min(bounds.bottom - 32, block.top + paddingTop + (lineHeight - 28) / 2),
    ),
    foldOffset = hasFoldControl ? 32 : 0,
    foldLeft = Math.max(bounds.left + 4 + foldOffset, Math.min(bounds.right - 44, block.left - 44));
  return { actions: { left: foldLeft - foldOffset, top }, fold: { left: foldLeft, top } };
}

/** Heading depth follows the real preceding hierarchy, including skipped levels
 * and duplicate text. Section names never become identities. */
export function headingOutline(
  headings: readonly Readonly<{ block_id: number; level: number; text: string }>[],
): readonly OutlineEntry[] {
  const stack: number[] = [],
    ids = new Set<number>();
  return Object.freeze(
    headings.map((heading) => {
      if (
        !Number.isSafeInteger(heading.block_id) ||
        heading.block_id < 1 ||
        ids.has(heading.block_id) ||
        !Number.isInteger(heading.level) ||
        heading.level < 1 ||
        heading.level > 6
      )
        throw TypeError('Invalid heading identity/level');
      ids.add(heading.block_id);
      while (stack.length && stack.at(-1)! >= heading.level) stack.pop();
      const depth = stack.length;
      stack.push(heading.level);
      return Object.freeze({ ...heading, depth });
    }),
  );
}
function readNavigation(
  ctx: Ctx,
  pair: EditedSnapshot,
  kind: NavigationContent['kind'],
): NavigationContent {
  const { source, state } = validateBlockState(ctx, pair.markdown_content, pair.block_state_json),
    view = ctx.get(editorViewCtx);
  if (
    !view.state.doc.eq(
      bindIdentityDocument(
        source.document,
        state.blocks.map((block) => block.block_id),
        state.next_block_id,
      ),
    )
  )
    throw Error('Displayed nodes differ from the complete source snapshot');
  const headings = source.blocks.flatMap((block, index) =>
    block.heading_level === null
      ? []
      : [
          {
            block_id: state.blocks[index]!.block_id,
            level: block.heading_level,
            text: block.plain_text,
          },
        ],
  );
  return Object.freeze({ kind, blocks: state.blocks, outline: headingOutline(headings) });
}
function blockElement(ctx: Ctx, id: number): HTMLElement | null {
  const view = ctx.get(editorViewCtx);
  let result: HTMLElement | null = null;
  view.state.doc.forEach((node, position) => {
    if (node.attrs.walle_block_id !== id) return;
    const dom = view.nodeDOM(position);
    if (dom instanceof HTMLElement) result = dom;
  });
  return result;
}

/** Snapshot/DOM navigation only: no HTTP, comment index, saved receipt or write
 * capability. Parent must refresh after adopting a server metadata receipt. */
export class DocumentNavigation {
  private readonly root: HTMLElement;
  private readonly port: NavigationPort;
  private readonly scrollport: HTMLElement | null;
  private readonly listeners = new Set<() => void>();
  private readonly removers: (() => void)[] = [];
  private observer: MutationObserver;
  private resize: ResizeObserver;
  private frame: number | null = null;
  private needsRead = false;
  private closed = false;
  private visible = true;
  private interacting = false;
  private readonly highlight: DocumentBlockHighlight;
  private readonly folding: DocumentSectionVisibility;
  private sections: readonly HeadingSection[] = [];
  private leaveTimer: ReturnType<typeof setTimeout> | undefined;
  private highlightTimer: ReturnType<typeof setTimeout> | undefined;
  private value: NavigationState = Object.freeze({
    content: null,
    active_heading: null,
    selected_block: null,
    source_block: null,
    toolbar: null,
    collapsed_headings: Object.freeze([]),
    foldable_headings: Object.freeze([]),
    hidden_blocks: Object.freeze([]),
    heading_controls: Object.freeze([]),
    error: null,
  });
  private constructor(root: HTMLElement, port: NavigationPort, scrollport: HTMLElement | null) {
    this.root = root;
    this.port = port;
    this.scrollport = scrollport;
    this.highlight = new DocumentBlockHighlight(root);
    this.folding = new DocumentSectionVisibility(root, () => this.schedule(false));
    const listen = (
      target: EventTarget,
      name: string,
      callback: EventListener,
      capture = false,
    ) => {
      target.addEventListener(name, callback, capture);
      this.removers.push(() => target.removeEventListener(name, callback, capture));
    };
    listen(window, 'scroll', () => this.schedule(false), true);
    listen(window, 'resize', () => this.schedule(false));
    listen(root, 'pointerover', (event) => {
      this.cancelLeave();
      this.selectTarget(event.target);
    });
    listen(root, 'focusin', (event) => this.selectTarget(event.target));
    const inAuxiliary = (target: EventTarget | null) =>
      target instanceof Element &&
      !!target.closest(
        '.block-operation-trigger,.document-heading-toggle,.block-auxiliary,.block-source-popover,.block-selection-comment',
      );
    const leave = () => {
      this.cancelLeave();
      this.leaveTimer = setTimeout(() => {
        this.leaveTimer = undefined;
        if (root.contains(document.activeElement) || inAuxiliary(document.activeElement)) return;
        this.interacting = false;
        this.measure();
      }, 180);
    };
    listen(root, 'pointerleave', (event) => {
      if (inAuxiliary((event as PointerEvent).relatedTarget)) return;
      leave();
    });
    listen(root, 'focusout', (event) => {
      if (
        root.contains((event as FocusEvent).relatedTarget as Node | null) ||
        inAuxiliary((event as FocusEvent).relatedTarget)
      )
        return;
      leave();
    });
    listen(document, 'pointerover', (event) => {
      if (root.contains(event.target as Node | null) || inAuxiliary(event.target)) {
        this.cancelLeave();
        return;
      }
      if (this.interacting && this.leaveTimer === undefined) leave();
    });
    listen(root, 'compositionstart', () => this.schedule(true));
    listen(root, 'compositionend', () => this.schedule(true));
    listen(root, 'keyup', () => {
      const selection = window.getSelection();
      if (selection?.anchorNode) this.selectTarget(selection.anchorNode);
    });
    this.observer = new MutationObserver(() => this.schedule(true));
    this.observer.observe(root, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: ['data-block-id'],
    });
    this.resize = new ResizeObserver(() => this.schedule(false));
    this.resize.observe(root);
    if (scrollport) this.resize.observe(scrollport);
    this.refresh();
  }
  static forEditor(
    root: HTMLElement,
    editor: RequirementEditor,
    scrollport: HTMLElement | null = null,
  ): DocumentNavigation {
    const navigation = new DocumentNavigation(
      root,
      {
        read: () => {
          if (!editor.valid) throw Error('Draft has incomplete input');
          const input = editor.loadedDocument;
          return editor.action((ctx) =>
            readNavigation(ctx, editor.ledger?.currentSnapshot ?? input, input.document_type),
          );
        },
        element: (id) => editor.action((ctx) => blockElement(ctx, id)),
        prepareCollapse: (heading, hidden) =>
          editor.action((ctx) => {
            const view = ctx.get(editorViewCtx),
              selection = view.state.selection;
            if (
              !selectionTouchesBlocks(view.state.doc, selection.from, selection.to, hidden).length
            )
              return;
            view.state.doc.forEach((node, position) => {
              if (node.attrs.walle_block_id !== heading) return;
              view.dispatch(
                view.state.tr.setSelection(
                  TextSelection.create(view.state.doc, position + node.nodeSize - 1),
                ),
              );
            });
          }),
      },
      scrollport,
    );
    navigation.removers.push(
      editor.guardTransactions((state, transaction) => {
        if (navigation.value.error || !navigation.value.hidden_blocks.length) return true;
        const effect = foldedTransactionEffect(
          state,
          transaction,
          new Set(navigation.value.hidden_blocks),
        );
        if (effect.reveal.length) navigation.revealBlocks(effect.reveal);
        return !effect.reject;
      }),
    );
    return navigation;
  }
  static forRevision(
    root: HTMLElement,
    viewer: RevisionViewer,
    scrollport: HTMLElement | null = null,
  ): DocumentNavigation {
    return new DocumentNavigation(
      root,
      {
        read: () => viewer.action((ctx) => readNavigation(ctx, viewer.snapshot, 'REVISION')),
        element: (id) => viewer.action((ctx) => blockElement(ctx, id)),
      },
      scrollport,
    );
  }
  getSnapshot = (): NavigationState => this.value;
  subscribe = (callback: () => void): (() => void) => {
    this.listeners.add(callback);
    return () => this.listeners.delete(callback);
  };
  private publish(changes: Partial<NavigationState>): void {
    if (this.closed) return;
    const next = Object.freeze({ ...this.value, ...changes });
    if (
      next.content === this.value.content &&
      next.active_heading === this.value.active_heading &&
      next.selected_block === this.value.selected_block &&
      next.source_block === this.value.source_block &&
      next.collapsed_headings === this.value.collapsed_headings &&
      next.foldable_headings === this.value.foldable_headings &&
      next.hidden_blocks === this.value.hidden_blocks &&
      next.heading_controls.length === this.value.heading_controls.length &&
      next.heading_controls.every((control, index) => {
        const previous = this.value.heading_controls[index]!;
        return (
          control.block_id === previous.block_id &&
          control.left === previous.left &&
          control.top === previous.top
        );
      }) &&
      next.error === this.value.error &&
      next.toolbar?.left === this.value.toolbar?.left &&
      next.toolbar?.top === this.value.toolbar?.top
    )
      return;
    this.value = next;
    for (const callback of this.listeners)
      try {
        callback();
      } catch (error) {
        console.error('WALL-E document navigation observer failed', error);
      }
  }
  private schedule(read: boolean): void {
    if (this.closed) return;
    this.needsRead ||= read;
    if (this.frame !== null) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = null;
      const read = this.needsRead;
      this.needsRead = false;
      if (read) this.refresh();
      else this.measure();
    });
  }
  refresh(): void {
    if (this.closed) return;
    this.clearHighlight();
    try {
      const content = this.port.read(),
        ids = new Set(content.blocks.map((block) => block.block_id));
      this.sections = headingSections(
        content.blocks.map((block) => block.block_id),
        content.outline,
      );
      const foldable = this.sections
          .filter((section) => section.to > section.from + 1)
          .map((section) => section.block_id),
        collapsed = this.value.collapsed_headings.filter((id) => foldable.includes(id)),
        hidden = foldedBlockIds(
          content.blocks.map((block) => block.block_id),
          this.sections,
          new Set(collapsed),
        );
      this.folding.hide(hidden);
      this.publish({
        content,
        foldable_headings: Object.freeze(foldable),
        collapsed_headings: Object.freeze(collapsed),
        hidden_blocks: hidden,
        error: null,
        selected_block:
          this.value.selected_block !== null && ids.has(this.value.selected_block)
            ? this.value.selected_block
            : null,
        source_block:
          this.value.source_block !== null && ids.has(this.value.source_block)
            ? this.value.source_block
            : null,
      });
      this.measure();
    } catch {
      this.highlight.hover(null);
      this.folding.hide([]);
      this.publish({
        error: '当前输入尚未形成完整文档，大纲和区块来源暂不可操作。',
        toolbar: null,
        source_block: null,
        heading_controls: Object.freeze([]),
      });
    }
  }
  private bounds(): { left: number; right: number; top: number; bottom: number } {
    const box = this.scrollport?.getBoundingClientRect(),
      toolbar = this.root.querySelector('.editor-format-toolbar')?.getBoundingClientRect();
    return {
      left: Math.max(0, box?.left ?? 0),
      right: Math.min(window.innerWidth, box?.right ?? window.innerWidth),
      top: Math.max(0, box?.top ?? 0, toolbar?.bottom ?? 0),
      bottom: Math.min(window.innerHeight, box?.bottom ?? window.innerHeight),
    };
  }
  private controls(
    element: HTMLElement,
    bounds: ReturnType<DocumentNavigation['bounds']>,
    hasFoldControl: boolean,
  ) {
    const box = element.getBoundingClientRect(),
      browser = element.ownerDocument?.defaultView ?? this.root.ownerDocument.defaultView,
      style = browser?.getComputedStyle?.(element),
      lineHeight = Number.parseFloat(style?.lineHeight ?? ''),
      paddingTop = Number.parseFloat(style?.paddingTop ?? '');
    return blockControlPositions(
      box,
      bounds,
      Number.isFinite(lineHeight) ? lineHeight : Math.min(box.bottom - box.top, 28),
      hasFoldControl,
      Number.isFinite(paddingTop) ? paddingTop : 0,
    );
  }
  private measure(): void {
    if (this.closed || !this.visible || this.value.error || !this.value.content) return;
    const bounds = this.bounds();
    const headingControls: { block_id: number; left: number; top: number }[] = [];
    let heading: number | null = null,
      first: number | null = null;
    const scrolling = this.scrollport ?? document.scrollingElement,
      atEnd =
        scrolling !== null &&
        scrolling.scrollHeight > scrolling.clientHeight + 1 &&
        scrolling.scrollHeight - scrolling.clientHeight - scrolling.scrollTop <= 1;
    if (this.root.getClientRects().length) {
      for (const entry of this.value.content.outline) {
        if (this.value.hidden_blocks.includes(entry.block_id)) continue;
        const element = this.port.element(entry.block_id);
        if (!element?.getClientRects().length) continue;
        const box = element.getBoundingClientRect(),
          top = box.top;
        if (
          this.value.foldable_headings.includes(entry.block_id) &&
          box.bottom > bounds.top &&
          box.top < bounds.bottom
        )
          headingControls.push({
            block_id: entry.block_id,
            ...this.controls(element, bounds, true).fold,
          });
        first ??= entry.block_id;
        if (top <= (atEnd ? bounds.bottom - 1 : bounds.top + 24)) heading = entry.block_id;
      }
    }
    heading ??= first;
    const element =
        this.value.selected_block === null ? null : this.port.element(this.value.selected_block),
      box = element?.getBoundingClientRect();
    const visible =
      (this.interacting || this.value.source_block !== null) &&
      !this.value.hidden_blocks.includes(this.value.selected_block ?? -1) &&
      element?.getClientRects().length &&
      box &&
      box.bottom > bounds.top &&
      box.top < bounds.bottom;
    this.highlight.hover(visible ? this.value.selected_block : null);
    // The document reserves a left gutter. Controls stay outside its text and
    // inside the visible document viewport, even for a partly scrolled block.
    this.publish({
      active_heading: heading,
      heading_controls: Object.freeze(headingControls.map((control) => Object.freeze(control))),
      toolbar: visible
        ? Object.freeze(
            this.controls(
              element,
              bounds,
              this.value.foldable_headings.includes(this.value.selected_block!),
            ).actions,
          )
        : null,
    });
  }
  private selectTarget(target: EventTarget | null): void {
    if (!this.visible || this.value.error || !this.value.content || !(target instanceof Node))
      return;
    if (this.value.source_block !== null) return;
    for (const block of this.value.content.blocks) {
      const element = this.port.element(block.block_id);
      if (element && (element === target || element.contains(target))) {
        this.interacting = true;
        this.publish({ selected_block: block.block_id });
        this.measure();
        return;
      }
    }
  }
  private cancelLeave(): void {
    if (this.leaveTimer !== undefined) clearTimeout(this.leaveTimer);
    this.leaveTimer = undefined;
  }
  hoverHeading(blockId: number): void {
    if (
      !this.visible ||
      this.value.error ||
      this.value.source_block !== null ||
      !this.value.foldable_headings.includes(blockId)
    )
      return;
    this.cancelLeave();
    this.interacting = true;
    this.publish({ selected_block: blockId });
    this.measure();
  }
  private applyCollapsed(collapsed: readonly number[]): void {
    const content = this.value.content;
    if (!content) return;
    const hidden = foldedBlockIds(
      content.blocks.map((block) => block.block_id),
      this.sections,
      new Set(collapsed),
    );
    this.folding.hide(hidden);
    this.publish({
      collapsed_headings: Object.freeze([...collapsed]),
      hidden_blocks: hidden,
      source_block:
        this.value.source_block !== null && hidden.includes(this.value.source_block)
          ? null
          : this.value.source_block,
    });
    this.measure();
  }
  toggleHeading(blockId: number): boolean {
    if (
      this.closed ||
      !this.visible ||
      this.value.error ||
      !this.value.foldable_headings.includes(blockId)
    )
      return false;
    if (this.value.source_block !== null) this.source(null);
    const collapsed = new Set(this.value.collapsed_headings);
    if (collapsed.has(blockId)) collapsed.delete(blockId);
    else {
      const section = this.sections.find((entry) => entry.block_id === blockId)!,
        hidden = this.value
          .content!.blocks.slice(section.from + 1, section.to)
          .map((block) => block.block_id);
      this.port.prepareCollapse?.(blockId, new Set(hidden));
      collapsed.add(blockId);
    }
    this.applyCollapsed([...collapsed]);
    this.hoverHeading(blockId);
    return true;
  }
  private revealBlocks(blockIds: readonly number[]): void {
    const blocks = this.value.content?.blocks.map((block) => block.block_id) ?? [],
      positions = blockIds.map((id) => blocks.indexOf(id)),
      ancestors = new Set(
        this.sections
          .filter((section) =>
            positions.some((index) => index > section.from && index < section.to),
          )
          .map((section) => section.block_id),
      ),
      collapsed = this.value.collapsed_headings.filter((id) => !ancestors.has(id));
    if (collapsed.length !== this.value.collapsed_headings.length) this.applyCollapsed(collapsed);
  }
  dismissAuxiliary(): void {
    if (this.closed) return;
    this.cancelLeave();
    this.interacting = false;
    this.highlight.hover(null);
    this.publish({ toolbar: null, source_block: null });
  }
  private clearHighlight(): void {
    if (this.highlightTimer !== undefined) clearTimeout(this.highlightTimer);
    this.highlightTimer = undefined;
    this.highlight.locate(null);
  }
  locate(blockId: number, highlight = false): boolean {
    if (
      this.closed ||
      !this.visible ||
      this.value.error ||
      !this.value.content?.blocks.some((block) => block.block_id === blockId)
    )
      return false;
    this.revealBlocks([blockId]);
    const element = this.port.element(blockId);
    if (!element?.getClientRects().length) return false;
    if (this.scrollport) {
      const top =
        element.getBoundingClientRect().top -
        this.scrollport.getBoundingClientRect().top -
        this.scrollport.clientTop;
      this.scrollport.scrollTop += top;
    } else element.scrollIntoView({ block: 'start', inline: 'nearest', behavior: 'instant' });
    this.interacting = true;
    this.publish({ selected_block: blockId });
    this.measure();
    if (highlight) {
      this.clearHighlight();
      this.highlight.locate(blockId);
      this.highlightTimer = setTimeout(() => this.clearHighlight(), 2000);
    }
    return true;
  }
  source(blockId: number | null): void {
    if (this.closed) return;
    if (
      blockId !== null &&
      (!this.visible ||
        this.value.error ||
        !this.value.content?.blocks.some((block) => block.block_id === blockId))
    )
      return;
    this.publish({ source_block: blockId });
    this.measure();
  }
  setVisible(visible: boolean): void {
    if (this.closed || this.visible === visible) return;
    this.visible = visible;
    if (visible) this.refresh();
    else {
      this.cancelLeave();
      this.highlight.hover(null);
      this.clearHighlight();
      this.publish({
        toolbar: null,
        source_block: null,
        active_heading: null,
        heading_controls: Object.freeze([]),
      });
    }
  }
  dispose(): void {
    if (this.closed) return;
    this.closed = true;
    this.cancelLeave();
    this.clearHighlight();
    this.highlight.destroy();
    this.folding.destroy();
    for (const remove of this.removers) remove();
    this.observer.disconnect();
    this.resize.disconnect();
    if (this.frame !== null) cancelAnimationFrame(this.frame);
    this.listeners.clear();
  }
}
