import type { Node } from '@milkdown/kit/prose/model';
import type { EditorState, Transaction } from '@milkdown/kit/prose/state';
import { DisclosureMotion } from '../shared/disclosure-motion.ts';

export type SectionHeading = Readonly<{ block_id: number; level: number }>;
export type HeadingSection = Readonly<{ block_id: number; from: number; to: number }>;

/** Both document and outline use the same next-same-or-higher boundary. */
export function headingSections(
  blocks: readonly number[],
  headings: readonly SectionHeading[],
): readonly HeadingSection[] {
  const byId = new Map(headings.map((heading) => [heading.block_id, heading])),
    sections: { block_id: number; level: number; from: number; to: number }[] = [],
    ancestors: number[] = [];
  blocks.forEach((block, index) => {
    const heading = byId.get(block);
    if (!heading) return;
    while (ancestors.length && sections[ancestors.at(-1)!]!.level >= heading.level) {
      sections[ancestors.pop()!]!.to = index;
    }
    ancestors.push(sections.length);
    sections.push({ ...heading, from: index, to: blocks.length });
  });
  return Object.freeze(
    sections.map(({ block_id, from, to }) => Object.freeze({ block_id, from, to })),
  );
}

export function foldedBlockIds(
  blocks: readonly number[],
  sections: readonly HeadingSection[],
  collapsed: ReadonlySet<number>,
): readonly number[] {
  const hidden = new Set<number>();
  for (const section of sections) {
    if (!collapsed.has(section.block_id)) continue;
    for (let index = section.from + 1; index < section.to; index++) hidden.add(blocks[index]!);
  }
  return Object.freeze(blocks.filter((block) => hidden.has(block)));
}

export function selectionTouchesBlocks(
  doc: Node,
  from: number,
  to: number,
  ids: ReadonlySet<number>,
) {
  const touched: number[] = [];
  doc.forEach((node, position) => {
    const id = node.attrs.walle_block_id as number;
    if (!ids.has(id)) return;
    const end = position + node.nodeSize;
    if (from === to ? from > position && from < end : from < end && to > position) touched.push(id);
  });
  return touched;
}

/** Never let an edit silently modify hidden text. A rejected first action only
 * reveals the affected section; its original editor/history state is retained. */
export function foldedTransactionEffect(
  state: EditorState,
  transaction: Transaction,
  hidden: ReadonlySet<number>,
): Readonly<{ reveal: readonly number[]; reject: boolean }> {
  const changed = new Set<number>(),
    after = new Map<number, Node>();
  if (transaction.docChanged) {
    transaction.doc.forEach((node) => after.set(node.attrs.walle_block_id as number, node));
    state.doc.forEach((node) => {
      const id = node.attrs.walle_block_id as number,
        current = after.get(id);
      if (hidden.has(id) && (!current || !node.eq(current))) changed.add(id);
    });
    const ranges: { id: number; from: number; to: number }[] = [];
    state.doc.forEach((node, position) => {
      const id = node.attrs.walle_block_id as number;
      if (hidden.has(id)) ranges.push({ id, from: position, to: position + node.nodeSize });
    });
    for (const map of transaction.mapping.maps) {
      for (const range of ranges) {
        map.forEach((from, to) => {
          const deletesContent = from < range.to && to > range.from,
            insertsInside = from === to && from > range.from && from < range.to;
          if (deletesContent || insertsInside) changed.add(range.id);
        });
        range.from = map.map(range.from, 1);
        range.to = map.map(range.to, -1);
      }
    }
  }
  const selected = selectionTouchesBlocks(
    transaction.doc,
    transaction.selection.from,
    transaction.selection.to,
    hidden,
  );
  return { reveal: [...new Set([...changed, ...selected])], reject: changed.size > 0 };
}

let foldingIdentity = 0;
export class DocumentSectionVisibility {
  private readonly root: HTMLElement;
  private readonly scope = `document-folding-${++foldingIdentity}`;
  private readonly stylesheet: HTMLStyleElement;
  private hidden: readonly number[] = [];
  private changing = new Set<number>();
  private readonly motion = new DisclosureMotion();
  private readonly moved: () => void;
  constructor(root: HTMLElement, moved: () => void) {
    this.root = root;
    this.moved = moved;
    root.classList.add(this.scope);
    this.stylesheet = root.ownerDocument.createElement('style');
    root.ownerDocument.head.append(this.stylesheet);
  }
  hide(blocks: readonly number[]): void {
    const previous = new Set(this.hidden),
      next = new Set(blocks),
      changed = [...new Set([...previous, ...next])].filter(
        (id) => previous.has(id) !== next.has(id),
      );
    if (!changed.length) return;
    const browser = this.root.ownerDocument.defaultView!;
    const moving = [...new Set([...this.changing, ...changed])];
    this.hidden = Object.freeze([...blocks]);
    this.motion.run(
      moving.flatMap((id) => {
        const element = this.root.querySelector<HTMLElement>(
          `.ProseMirror > [data-block-id="${id}"]`,
        );
        return element ? [{ element, collapsed: next.has(id) }] : [];
      }),
      (active) => {
        this.changing = new Set(active ? moving : []);
        this.paint();
      },
      this.moved,
      // Older browsers settle immediately rather than leave hidden text focusable.
      browser.CSS.supports('interactivity', 'inert'),
    );
  }
  private selectors(blocks: readonly number[]): string {
    return blocks.map((id) => `.${this.scope} .ProseMirror > [data-block-id="${id}"]`).join(',');
  }
  private paint(): void {
    const rules: string[] = [];
    if (this.changing.size)
      rules.push(`.${this.scope} { overflow-anchor: none; }
      ${this.selectors([...this.changing])} {
        overflow: clip;
        min-height: 0 !important;
      }`);
    if (this.hidden.length)
      rules.push(`${this.selectors(this.hidden)} {
        pointer-events: none;
        interactivity: inert;
      }`);
    const settled = this.hidden.filter((id) => !this.changing.has(id));
    if (settled.length)
      rules.push(`${this.selectors(settled)} {
        display: none !important;
      }`);
    this.stylesheet.textContent = rules.join('\n');
  }
  destroy(): void {
    this.motion.dispose();
    this.stylesheet.remove();
    this.root.classList.remove(this.scope);
  }
}
