import type { Node } from '@milkdown/kit/prose/model';
import { Decoration, DecorationSet } from '@milkdown/kit/prose/view';
import type { EditorSourceBlock } from './editor-source.ts';

function escaped(source: string, offset: number): boolean {
  let cursor = offset;
  while (cursor > 0 && source[cursor - 1] === '\\') cursor--;
  return (offset - cursor) % 2 === 1;
}

/** Display the CJK closing-punctuation case without reinterpreting source offsets. */
export function chineseStrongDecorations(
  document: Node,
  blocks: readonly Pick<EditorSourceBlock, 'markdown'>[],
): DecorationSet {
  const decorations: Decoration[] = [];
  document.forEach((block, blockOffset, index) => {
    const raw = blocks[index]?.markdown;
    if (!raw?.includes('**')) return;
    block.descendants((node, offset, parent) => {
      if (!node.text || node.marks.length || parent?.type.spec.code) return;
      const pairs = node.text.matchAll(
        /(?<!\*)\*\*([\p{L}\p{N}][^*\r\n]*[：？！。，；、…）】》」』])\*\*(?=\p{Script=Han})/gu,
      );
      const first = pairs.next();
      if (first.done) return;
      // A decoded or repeated span cannot be assigned unambiguously to source.
      const sourceOffset = raw.indexOf(node.text);
      if (sourceOffset < 0 || raw.indexOf(node.text, sourceOffset + 1) >= 0) return;
      for (const pair of [first.value, ...pairs]) {
        const markerOffset = sourceOffset + pair.index;
        const end = markerOffset + pair[0].length - 2;
        if (escaped(raw, markerOffset) || escaped(raw, end)) continue;
        const from = blockOffset + offset + pair.index + 1;
        const to = from + pair[0].length;
        const hidden = { class: 'walle-strong-marker', 'aria-hidden': 'true' };
        decorations.push(
          Decoration.inline(from, from + 2, hidden),
          Decoration.inline(from + 2, to - 2, { nodeName: 'strong' }),
          Decoration.inline(to - 2, to, hidden),
        );
      }
    });
  });
  return DecorationSet.create(document, decorations);
}
