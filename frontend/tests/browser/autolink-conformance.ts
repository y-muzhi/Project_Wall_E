import type { Crepe } from '@milkdown/crepe';
import { editorViewCtx } from '@milkdown/kit/core';
import base from '../../../shared/fixtures/autolink-v1.json';
import contexts from '../../../shared/fixtures/autolink-context-v1.json';
import unicode from '../../../shared/fixtures/autolink-unicode-v1.json';
import { EditorSource } from '../../src/documents/editor-source.ts';
import { EditedSnapshotLedger } from '../../src/documents/edited-snapshot.ts';
import { fixtureDraft, editTime } from './edited-snapshot.ts';

export async function autolinkConformance(load: (markdown: string, ids: readonly number[], next: number) => Promise<unknown>, get: () => Crepe) {
  const records = [], outputs = [];
  for (const entry of [...base.cases.map(entry => ({...entry, plain_text: [entry.plain_text]})), ...contexts.cases, ...unicode.cases]) {
    const ids = entry.plain_text.map((_plain, index) => index + 1);
    await load(entry.markdown, ids, ids.length + 1);
    const actual = get().editor.action(ctx => {
      const source = new EditorSource(ctx, entry.markdown);
      const links: {text: string; href: string}[] = [];
      // Adjacent text nodes split by strong/strike marks still form one link.
      let lastEnd = -1;
      source.document.descendants((node, position) => {
        const link = node.marks.find(mark => mark.type.name === 'link');
        if (link && node.isText) {
          const href = String(link.attrs.href), previous = links.at(-1);
          if (previous && lastEnd === position && previous.href === href) previous.text += node.text!;
          else links.push({text: node.text!, href});
          lastEnd = position + node.nodeSize;
        }
      });
      const view = ctx.get(editorViewCtx);
      const ledger = new EditedSnapshotLedger(ctx, fixtureDraft(ctx, entry.markdown, ids, ids.length + 1), view.state);
      const pair = ledger.capture(view.state, editTime);
      outputs.push({pair, projection: source.blocks.map(block => ({block_type: block.block_type, plain_text: block.plain_text, section_path: block.section_path}))});
      if (pair.markdown_content !== entry.markdown || source.parts.join('') !== entry.markdown) throw new Error(`自动链接改变完整源码: ${entry.name}`);
      return {plain_text: source.blocks.map(block => block.plain_text), links};
    });
    const expected = {plain_text: entry.plain_text, links: entry.links};
    records.push({name: entry.name, expected, actual, conforms: JSON.stringify(actual) === JSON.stringify(expected)});
  }
  // A real edit forces serialization, rather than simply returning old source.
  const markdown = '访问 www.example.test/a*b*c.\r\n';
  await load(markdown, [10], 20);
  const edited = get().editor.action(ctx => {
    const view = ctx.get(editorViewCtx);
    const ledger = new EditedSnapshotLedger(ctx, fixtureDraft(ctx, markdown, [10], 20), view.state);
    view.dispatch(view.state.tr.insertText('新', 1));
    const pair = ledger.capture(view.state, editTime), parsed = new EditorSource(ctx, pair.markdown_content);
    if (parsed.blocks[0]!.plain_text !== '新访问 www.example.test/a*b*c.') throw new Error('编辑后自动链接丢失原文字号');
    return {pair, projection: parsed.blocks.map(block => ({block_type: block.block_type, plain_text: block.plain_text, section_path: block.section_path}))};
  });
  outputs.push(edited);
  for (const name of ['table-header-chunk', 'table-escaped-pipe']) {
    const entry = contexts.cases.find(entry => entry.name === name)!;
    await load(entry.markdown, [10], 20);
    outputs.push(get().editor.action(ctx => {
      const view = ctx.get(editorViewCtx);
      const ledger = new EditedSnapshotLedger(ctx, fixtureDraft(ctx, entry.markdown, [10], 20), view.state);
      let first: number | undefined;
      view.state.doc.descendants((node, position) => { if (node.isText && first === undefined) first = position; });
      if (first === undefined) throw new Error('表格缺少实际文本位置');
      view.dispatch(view.state.tr.insertText('新', first));
      const pair = ledger.capture(view.state, editTime), parsed = new EditorSource(ctx, pair.markdown_content);
      if (parsed.blocks[0]!.plain_text !== '新' + entry.plain_text[0]) throw new Error(`表格编辑破坏链接原文: ${name}`);
      return {pair, projection: parsed.blocks.map(block => ({block_type: block.block_type, plain_text: block.plain_text, section_path: block.section_path}))};
    }));
  }
  for (const name of ['astral-letter-domain-and-offset', 'unicode-table-chunk']) {
    const entry = unicode.cases.find(entry => entry.name === name)!;
    await load(entry.markdown, [10], 20);
    outputs.push(get().editor.action(ctx => {
      const view = ctx.get(editorViewCtx);
      const ledger = new EditedSnapshotLedger(ctx, fixtureDraft(ctx, entry.markdown, [10], 20), view.state);
      let first: number | undefined;
      view.state.doc.descendants((node, position) => { if (node.isText && first === undefined) first = position; });
      if (first === undefined) throw new Error('Unicode链接缺少实际编辑位置');
      view.dispatch(view.state.tr.insertText('新', first));
      const pair = ledger.capture(view.state, editTime), parsed = new EditorSource(ctx, pair.markdown_content);
      if (parsed.blocks[0]!.plain_text !== '新' + entry.plain_text[0]) throw new Error('Unicode链接编辑破坏域名或原文字号');
      return {pair, projection: parsed.blocks.map(block => ({block_type: block.block_type, plain_text: block.plain_text, section_path: block.section_path}))};
    }));
  }
  return {scope: '56 independent literal/context cases plus 5 actual edited snapshots; no complete dialect or product acceptance', records, outputs,
    mismatches: records.filter(record => !record.conforms).map(record => record.name)};
}
