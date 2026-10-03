import type { MarkdownNode } from '@milkdown/kit/transformer';

// ProseMirror represents a style as one mark, rather than a nested mark stack.
// Closing an inner delete in Milkdown would otherwise also close the outer
// style, leaving its remaining text unmarked. Keep the outer span and all
// child syntax/positions; source preservation still owns the original tildes.
export function collapseNestedDeletion(root: MarkdownNode): void {
  function visit(node: MarkdownNode, inside: boolean): void {
    if (!node.children) return;
    const active = inside || node.type === 'delete';
    for (const child of node.children) visit(child, active);
    if (active) node.children = node.children.flatMap(child => child.type === 'delete' ? child.children ?? [] : [child]);
  }
  visit(root, false);
}
