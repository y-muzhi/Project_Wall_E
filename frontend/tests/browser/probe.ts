import { Crepe } from '@milkdown/crepe';
import { editorViewCtx, remarkCtx } from '@milkdown/kit/core';
import fixtures from '../../../shared/fixtures/markdown-v1.json';
import editorFixtures from '../../../shared/fixtures/markdown-editor-v1.json';
import { installSourceNodes } from '../../src/documents/source-nodes.ts';
import { EditorSource, blockProjection } from '../../src/documents/editor-source.ts';
import { installIdentityAttributes, installIdentityState, identityState, topBlockIds } from '../../src/documents/identity.ts';
import { verifyContracts } from './contracts.ts';
import { fixtureDraft, editTime, verifyEditedSnapshots } from './edited-snapshot.ts';
import { EditedSnapshotLedger } from '../../src/documents/edited-snapshot.ts';
import { autolinkBaseline } from './autolink-baseline.ts';
import { autolinkConformance } from './autolink-conformance.ts';
import { verifyStrikethrough } from './strikethrough.ts';
import { verifyRawSource } from './raw-source.ts';
import { verifyEditorSelection, keyboardSelection } from './editor-selection.ts';

let crepe: Crepe | undefined;
let ledger: EditedSnapshotLedger | undefined;
const root = document.querySelector<HTMLElement>('#editor')!;
const source = document.querySelector<HTMLTextAreaElement>('#source')!;
const status = document.querySelector<HTMLElement>('#status')!;
async function load(markdown: string, adapted = false, identity?: {ids: readonly number[]; next: number}) {
  ledger = undefined;
  await crepe?.destroy();
  root.replaceChildren();
  crepe = new Crepe({root, defaultValue: markdown, features: {
    [Crepe.Feature.CodeMirror]: false, [Crepe.Feature.ListItem]: false,
    [Crepe.Feature.LinkTooltip]: false, [Crepe.Feature.Cursor]: false,
    [Crepe.Feature.ImageBlock]: false, [Crepe.Feature.BlockEdit]: false,
    [Crepe.Feature.Toolbar]: false, [Crepe.Feature.Placeholder]: false,
    [Crepe.Feature.Table]: false, [Crepe.Feature.Latex]: false,
    [Crepe.Feature.TopBar]: false, [Crepe.Feature.AI]: false,
  }});
  if (adapted) await installSourceNodes(crepe);
  if (identity) {
    installIdentityAttributes(crepe);
    installIdentityState(crepe, identity.ids, identity.next);
  }
  await crepe.create();
  const result = crepe.editor.action(ctx => ({
    markdown: crepe!.getMarkdown(),
    document: ctx.get(editorViewCtx).state.doc.toJSON(),
    ast: ctx.get(remarkCtx).runSync(ctx.get(remarkCtx).parse(markdown), markdown),
    ...(adapted && !identity ? (() => {
      const parsed = new EditorSource(ctx, markdown);
      return {preserved: parsed.unchangedMarkdown(ctx.get(editorViewCtx).state.doc), parts: parsed.parts,
        blocks: parsed.blocks.map(({node: _node, ...block}) => block)};
    })() : {}),
  }));
  status.textContent = JSON.stringify(result, null, 2);
  return result;
}
Object.assign(window, { editorProbe: {
  load,
  autolinkBaseline: () => autolinkBaseline(markdown => load(markdown, true), () => crepe!),
  autolinkConformance: () => autolinkConformance((markdown, ids, next) => load(markdown, true, {ids, next}), () => crepe!),
  verifyStrikethrough: () => verifyStrikethrough((markdown, ids, next) => load(markdown, true, {ids, next}), () => crepe!),
  verifyRawSource: () => verifyRawSource((markdown, ids, next) => load(markdown, true, {ids, next}), () => crepe!),
  verifyEditorSelection: () => verifyEditorSelection((markdown, ids, next) => load(markdown, true, {ids, next}), () => crepe!),
  prepareSelection: () => load('甲😀乙\n', true, {ids: [10], next: 20}),
  keyboardSelection: () => keyboardSelection(crepe!),
  prepareIdentity: async () => {
    const markdown = '甲乙\n\n尾\n';
    await load(markdown, true, {ids: [10, 20], next: 30});
    ledger = crepe!.editor.action(ctx => new EditedSnapshotLedger(ctx, fixtureDraft(ctx, markdown, [10,20], 30), ctx.get(editorViewCtx).state));
  },
  verifyEditedSnapshots: () => verifyEditedSnapshots((markdown, ids, next) => load(markdown, true, {ids, next}), () => crepe!),
  verifyContracts: () => crepe!.editor.action(ctx => verifyContracts(ctx)),
  identityReport: () => crepe!.editor.action(ctx => ({
    ids: topBlockIds(ctx.get(editorViewCtx).state.doc),
    next: identityState(ctx.get(editorViewCtx).state).next_block_id,
    position: ctx.get(editorViewCtx).state.selection.from,
    text: ctx.get(editorViewCtx).state.doc.textContent,
    serialized: crepe!.getMarkdown(),
    ...(() => {
      const pair = ledger!.capture(ctx.get(editorViewCtx).state, editTime);
      return {pair, pair_projection: new EditorSource(ctx, pair.markdown_content).blocks.map(block => ({
        block_type: block.block_type, plain_text: block.plain_text, section_path: block.section_path,
      }))};
    })(),
    dom_ids: [...ctx.get(editorViewCtx).dom.querySelectorAll('[data-block-id]')].map(node => node.getAttribute('data-block-id')),
  })),
  async verifyIdentityTypes() {
    const results = [];
    for (const entry of [...fixtures.cases, ...editorFixtures.cases]) {
      const ids = entry.blocks.map((_block, index) => index + 1);
      await load(entry.markdown, true, {ids, next: ids.length + 1});
      const actual = crepe!.editor.action(ctx => {
        const doc = ctx.get(editorViewCtx).state.doc;
        return {ids: ids.length ? topBlockIds(doc) : [], next: identityState(ctx.get(editorViewCtx).state).next_block_id,
          projection: entry.blocks.map((_block, index) => blockProjection(doc.child(index))),
          serialized: crepe!.getMarkdown(),
          unchanged_pair: new EditedSnapshotLedger(ctx, fixtureDraft(ctx, entry.markdown, ids, ids.length + 1), ctx.get(editorViewCtx).state).capture(ctx.get(editorViewCtx).state, editTime),
          dom_ids: [...ctx.get(editorViewCtx).dom.querySelectorAll('[data-block-id]')].map(node => node.getAttribute('data-block-id'))};
      });
      if (JSON.stringify(actual.ids) !== JSON.stringify(ids) || actual.next !== ids.length + 1 ||
          JSON.stringify(actual.dom_ids) !== JSON.stringify(ids.map(String)) ||
          JSON.stringify(actual.projection) !== JSON.stringify(entry.blocks.map(block => block.plain_text)) ||
          actual.unchanged_pair.markdown_content !== entry.markdown ||
          actual.serialized.includes('walle_block_id')) throw new Error(`身份属性改变了方言或丢失区块: ${entry.name}`);
      results.push({name: entry.name, ...actual});
    }
    return results;
  },
  async fixtures(adapted = false) {
    const results = [];
    for (const entry of [...fixtures.cases, ...editorFixtures.cases]) {
      try { results.push({name: entry.name, input: entry.markdown, expected: entry.blocks, result: await load(entry.markdown, adapted)}); }
      catch (error) { results.push({name: entry.name, error: String(error)}); }
    }
    return results;
  },
  async verify() {
    const results = [];
    for (const entry of [...fixtures.cases, ...editorFixtures.cases]) {
      const result = await load(entry.markdown, true);
      const actual = result.blocks!.map(({block_type, plain_text, section_path, heading_level}) =>
        ({type: block_type, plain_text, section_path, heading_level}));
      if (JSON.stringify(actual) !== JSON.stringify(entry.blocks)) throw new Error(`投影不一致: ${entry.name}`);
      if (result.preserved !== entry.markdown || result.parts!.join('') !== entry.markdown) throw new Error(`原文变化: ${entry.name}`);
      if ('__walleUnsafe' in window || root.querySelector('script')) throw new Error('原始HTML被执行或渲染为HTML');
      const changedRejected = crepe!.editor.action(ctx => {
        const parsed = new EditorSource(ctx, entry.markdown);
        // A real transaction changes a node, rather than comparing two copied
        // serializations. Every fixture also has an editable caret paragraph.
        const altered = ctx.get(editorViewCtx).state.tr.insertText('变更', 1).doc;
        try { parsed.unchangedMarkdown(altered); return false; } catch { return true; }
      });
      if (!changedRejected) throw new Error('编辑后仍返回旧源码');
      results.push({name: entry.name, raw_equal: true, projection_equal: true, changed_rejected: true,
        blocks: result.blocks, preserved: result.preserved});
    }
    return {user_agent: navigator.userAgent, cases: results, html_inert: true};
  },
}});
document.querySelector('#load')!.addEventListener('click', () => {
  void load(source.value).catch(error => { status.textContent = String(error); });
});
await load('# 浏览器验证\n\n甲😀乙\n');
