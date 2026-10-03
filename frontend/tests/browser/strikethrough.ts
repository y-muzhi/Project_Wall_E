import type { Crepe } from '@milkdown/crepe';
import { editorViewCtx } from '@milkdown/kit/core';
import fixtures from '../../../shared/fixtures/strikethrough-v1.json';
import { EditorSource, inlineProjection } from '../../src/documents/editor-source.ts';
import { EditedSnapshotLedger } from '../../src/documents/edited-snapshot.ts';
import { fixtureDraft, editTime } from './edited-snapshot.ts';

export async function verifyStrikethrough(load: (markdown: string, ids: readonly number[], next: number) => Promise<unknown>, get: () => Crepe) {
  const records = [], outputs = [];
  for (const entry of fixtures.cases) {
    const ids = entry.plain_text.map((_plain, index) => index + 1);
    await load(entry.markdown, ids, ids.length + 1);
    records.push(get().editor.action(ctx => {
      const view = ctx.get(editorViewCtx), source = new EditorSource(ctx, entry.markdown);
      const deleted: string[] = [];
      let lastEnd = -1;
      source.document.descendants((node, position) => {
        if (node.isInline && node.marks.some(mark => mark.type.name === 'strike_through')) {
          const text = inlineProjection(node);
          if (lastEnd === position) deleted[deleted.length - 1] += text;
          else deleted.push(text);
          lastEnd = position + node.nodeSize;
        }
      });
      const actual = {plain_text: source.blocks.map(block => block.plain_text), deleted};
      const expected = {plain_text: entry.plain_text, deleted: entry.deleted};
      if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error(`实际Crepe删除线不一致: ${entry.name}: ${JSON.stringify(actual)}`);
      const ledger = new EditedSnapshotLedger(ctx, fixtureDraft(ctx, entry.markdown, ids, ids.length + 1), view.state);
      const pair = ledger.capture(view.state, editTime);
      if (pair.markdown_content !== entry.markdown || source.parts.join('') !== entry.markdown) throw new Error('删除线改变原始源');
      outputs.push({pair, projection: source.blocks.map(block => ({block_type: block.block_type, plain_text: block.plain_text, section_path: block.section_path}))});
      return {name: entry.name, actual, expected};
    }));
  }
  for (const name of ['double-with-unmatched-single', 'nested-width', 'table']) {
    const entry = fixtures.cases.find(entry => entry.name === name)!;
    await load(entry.markdown, [10], 20);
    outputs.push(get().editor.action(ctx => {
      const view = ctx.get(editorViewCtx);
      const ledger = new EditedSnapshotLedger(ctx, fixtureDraft(ctx, entry.markdown, [10], 20), view.state);
      let first: number | undefined;
      view.state.doc.descendants((node, position) => { if (node.isText && first === undefined) first = position; });
      if (first === undefined) throw new Error('删除线编辑缺少实际文本');
      view.dispatch(view.state.tr.insertText('新', first));
      const pair = ledger.capture(view.state, editTime), source = new EditorSource(ctx, pair.markdown_content);
      if (source.blocks[0]!.plain_text !== '新' + entry.plain_text[0]) throw new Error('删除线编辑丢失标记内外原文');
      return {pair, projection: source.blocks.map(block => ({block_type: block.block_type, plain_text: block.plain_text, section_path: block.section_path}))};
    }));
  }
  return {scope: '18 independent GFM strikethrough cases and 3 actual edited outputs; fixture provenance only', records, outputs};
}
