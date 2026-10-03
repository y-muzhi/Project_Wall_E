import type { Crepe } from '@milkdown/crepe';
import { editorViewCtx } from '@milkdown/kit/core';
import fixtures from '../../../shared/fixtures/raw-source-containers-v1.json';
import { EditorSource } from '../../src/documents/editor-source.ts';
import { EditedSnapshotLedger } from '../../src/documents/edited-snapshot.ts';
import { fixtureDraft, editTime } from './edited-snapshot.ts';

export async function verifyRawSource(load: (markdown: string, ids: readonly number[], next: number) => Promise<unknown>, get: () => Crepe) {
  const records = [], outputs = [];
  for (const entry of fixtures.cases) {
    await load(entry.markdown, [10], 20);
    records.push(get().editor.action(ctx => {
      const view = ctx.get(editorViewCtx), source = new EditorSource(ctx, entry.markdown);
      const actual = source.blocks.map(block => ({block_type: block.block_type, plain_text: block.plain_text}));
      if (JSON.stringify(actual) !== JSON.stringify([{block_type: entry.block_type, plain_text: entry.plain_text}])) {
        throw new Error(`容器原始源投影不一致: ${entry.name}: ${JSON.stringify(actual)}`);
      }
      if (source.parts.join('') !== entry.markdown || view.state.doc.childCount !== 1 ||
          '__walleNestedUnsafe' in window || view.dom.querySelector('script')) throw new Error('原始节点丢失区块或HTML被执行');
      const ledger = new EditedSnapshotLedger(ctx, fixtureDraft(ctx, entry.markdown, [10], 20), view.state);
      const pair = ledger.capture(view.state, editTime);
      if (pair.markdown_content !== entry.markdown) throw new Error('未改容器源发生变化');
      outputs.push({pair, projection: source.blocks.map(block => ({block_type: block.block_type, plain_text: block.plain_text, section_path: block.section_path}))});
      return {name: entry.name, actual, preserved: pair.markdown_content, inert: true};
    }));
  }
  for (const name of ['quote-html', 'list-first-html', 'quote-list-html', 'list-after-paragraph-definition']) {
    const entry = fixtures.cases.find(entry => entry.name === name)!;
    await load(entry.markdown, [10], 20);
    outputs.push(get().editor.action(ctx => {
      const view = ctx.get(editorViewCtx);
      const ledger = new EditedSnapshotLedger(ctx, fixtureDraft(ctx, entry.markdown, [10], 20), view.state);
      let target: number | undefined;
      const word = name === 'list-after-paragraph-definition' ? '一' : '原样';
      view.state.doc.descendants((node, position) => {
        if (node.isText && node.text!.includes(word) && target === undefined) target = position + node.text!.indexOf(word);
      });
      if (target === undefined) throw new Error('原始容器缺少编辑位置');
      view.dispatch(view.state.tr.insertText('新', target));
      const pair = ledger.capture(view.state, editTime), source = new EditorSource(ctx, pair.markdown_content);
      if (source.blocks.length !== 1 || source.blocks[0]!.plain_text !== entry.plain_text.replace(word, '新' + word)) {
        throw new Error(`编辑后容器源丢失/规范化: ${name}: ${JSON.stringify(source.blocks.map(block => block.plain_text))}`);
      }
      if (pair.block_state_json.blocks[0]!.block_id !== 10) throw new Error('容器内编辑改变顶层身份');
      return {pair, projection: source.blocks.map(block => ({block_type: block.block_type, plain_text: block.plain_text, section_path: block.section_path}))};
    }));
  }
  return {scope: '18 independent nested raw-source/container cases and 4 actual edits; fixture provenance only', records, outputs};
}
