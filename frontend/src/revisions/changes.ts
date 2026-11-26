export type RevisionBlock = Readonly<{ id: number; markdown: string; section: readonly string[] }>;
export type RevisionChange = Readonly<{
  section: readonly string[];
  removed: string;
  added: string;
}>;

/** Unchanged blocks anchor the surrounding changes by stable identity. */
export function compareRevisionBlocks(
  before: readonly RevisionBlock[],
  after: readonly RevisionBlock[],
): readonly RevisionChange[] {
  const earlier = new Map(before.map((block, index) => [block.id, { block, index }]));
  const changes: RevisionChange[] = [];
  let oldStart = 0;
  let newStart = 0;
  function collect(oldEnd: number, newEnd: number) {
    if (oldStart === oldEnd && newStart === newEnd) return;
    const removed = before.slice(oldStart, oldEnd);
    const added = after.slice(newStart, newEnd);
    changes.push({
      section: added[0]?.section ?? removed[0]?.section ?? [],
      removed: removed.map((block) => block.markdown.trimEnd()).join('\n\n'),
      added: added.map((block) => block.markdown.trimEnd()).join('\n\n'),
    });
  }
  after.forEach((block, index) => {
    const anchor = earlier.get(block.id);
    if (!anchor || anchor.index < oldStart || anchor.block.markdown !== block.markdown) return;
    collect(anchor.index, index);
    oldStart = anchor.index + 1;
    newStart = index + 1;
  });
  collect(before.length, after.length);
  return changes;
}
