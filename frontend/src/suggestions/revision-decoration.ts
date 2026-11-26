import type { Ctx } from '@milkdown/kit/ctx';
import type { Node } from '@milkdown/kit/prose/model';
import { Decoration, DecorationSet } from '@milkdown/kit/prose/view';
import type { Suggestion } from '../api/models.ts';
import { suggestionMarkdown } from './preview.ts';

function inserted(position: number, text: string, suggestionId: number) {
  return Decoration.widget(position, () => {
    const insertion = document.createElement('ins');
    insertion.className = 'document-revision-inserted';
    insertion.dataset.revisionSuggestion = String(suggestionId);
    insertion.textContent = text;
    return insertion;
  });
}

function textReplacement(
  before: string,
  after: string,
  position: number,
  suggestionId: number,
): Decoration[] {
  const oldCharacters = Array.from(before);
  const newCharacters = Array.from(after);
  let start = 0;
  let oldEnd = oldCharacters.length;
  let newEnd = newCharacters.length;
  while (start < oldEnd && start < newEnd && oldCharacters[start] === newCharacters[start]) start++;
  while (
    oldEnd > start &&
    newEnd > start &&
    oldCharacters[oldEnd - 1] === newCharacters[newEnd - 1]
  ) {
    oldEnd--;
    newEnd--;
  }
  const from = position + oldCharacters.slice(0, start).join('').length;
  const to = from + oldCharacters.slice(start, oldEnd).join('').length;
  const replacement = newCharacters.slice(start, newEnd).join('');
  const decorations: Decoration[] = [];
  if (to > from)
    decorations.push(
      Decoration.inline(from, to, {
        nodeName: 'del',
        class: 'document-revision-deleted',
        'data-revision-suggestion': String(suggestionId),
      }),
    );
  if (replacement) decorations.push(inserted(to, replacement, suggestionId));
  return decorations;
}

function previewBlock(position: number, item: Suggestion, render: (element: HTMLElement) => void) {
  const side =
    item.patch_operation === 'REPLACE_BLOCK'
      ? -1000
      : item.patch_operation === 'INSERT_AFTER'
        ? item.order_no - 101
        : item.order_no;
  return Decoration.widget(
    position,
    () => {
      const wrapper = document.createElement('div');
      wrapper.className = 'document-revision-added-block';
      wrapper.dataset.revisionSuggestion = String(item.id);
      wrapper.setAttribute('role', 'group');
      wrapper.setAttribute('aria-label', '建议新增内容');
      render(wrapper);
      return wrapper;
    },
    { side },
  );
}

export function revisionDecoration(
  ctx: Ctx,
  doc: Node,
  node: Node,
  position: number,
  item: Suggestion,
): DecorationSet {
  const remove = Decoration.node(position, position + node.nodeSize, {
    class: 'document-revision-deleted-block',
    'data-revision-suggestion': String(item.id),
  });
  if (item.patch_operation === 'DELETE_BLOCK') return DecorationSet.create(doc, [remove]);
  if (item.patch_operation === 'REPLACE_TABLE_ROW') {
    const selector = item.selector!;
    const rows: { node: Node; start: number }[] = [];
    node.forEach((row, offset, index) => {
      const column = selector.key_column_index;
      if (
        index > 0 &&
        column < row.childCount &&
        row.child(column).textContent.trim() === selector.key_value
      )
        rows.push({ node: row, start: position + 1 + offset });
    });
    if (rows.length !== 1) return DecorationSet.empty;
    const row = rows[0]!;
    const cells: string[] = item.user_edited_content
      ? (JSON.parse(item.user_edited_content) as { cells: string[] }).cells
      : item.proposed_data!.cells.slice();
    const decorations: Decoration[] = [];
    row.node.forEach((cell, offset, index) => {
      const replacement = cells[index];
      if (replacement === undefined || cell.childCount !== 1) return;
      const paragraph = cell.child(0);
      if (!paragraph.isTextblock || paragraph.textContent.length !== paragraph.content.size) return;
      decorations.push(
        ...textReplacement(paragraph.textContent, replacement, row.start + offset + 3, item.id),
      );
    });
    return DecorationSet.create(doc, decorations);
  }
  const proposed = item.user_edited_content ?? item.proposed_markdown!;
  const fragment = suggestionMarkdown(ctx, proposed);
  if (
    item.patch_operation === 'REPLACE_BLOCK' &&
    node.isTextblock &&
    node.textContent.length === node.content.size &&
    fragment.childElementCount === 1 &&
    fragment.firstElementChild?.children.length === 0
  ) {
    const rendered = fragment.firstElementChild;
    const sameKind =
      (node.type.name === 'paragraph' && rendered.tagName === 'P') ||
      (node.type.name === 'heading' && rendered.tagName === 'H' + node.attrs.level);
    if (sameKind)
      return DecorationSet.create(
        doc,
        textReplacement(node.textContent, rendered.textContent ?? '', position + 1, item.id),
      );
  }
  const insertion = previewBlock(
    item.patch_operation === 'INSERT_BEFORE' ? position : position + node.nodeSize,
    item,
    (wrapper) => wrapper.append(fragment.cloneNode(true)),
  );
  return DecorationSet.create(
    doc,
    item.patch_operation === 'REPLACE_BLOCK' ? [remove, insertion] : [insertion],
  );
}
