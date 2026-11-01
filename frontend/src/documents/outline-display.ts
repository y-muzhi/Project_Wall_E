import type { OutlineEntry } from './navigation.ts';
import { foldedBlockIds, headingSections } from './section-folding.ts';

/** Folding affects visibility only; the authoritative outline stays intact. */
export function visibleOutline(
  outline: readonly OutlineEntry[],
  collapsed: ReadonlySet<number>,
): readonly boolean[] {
  const blocks = outline.map((heading) => heading.block_id),
    hidden = new Set(foldedBlockIds(blocks, headingSections(blocks, outline), collapsed));
  return blocks.map((block) => !hidden.has(block));
}
