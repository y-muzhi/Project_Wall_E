import { Crepe } from '@milkdown/crepe';
import { editorViewCtx, remarkCtx } from '@milkdown/kit/core';
import fixtures from '../../../shared/fixtures/markdown-v1.json';
import editorFixtures from '../../../shared/fixtures/markdown-editor-v1.json';
import { installSourceNodes } from '../../src/documents/source-nodes.ts';
import { EditorSource } from '../../src/documents/editor-source.ts';

let crepe: Crepe | undefined;
const root = document.querySelector<HTMLElement>('#editor')!;
const source = document.querySelector<HTMLTextAreaElement>('#source')!;
const status = document.querySelector<HTMLElement>('#status')!;
async function load(markdown: string, adapted = false) {
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
  await crepe.create();
  const result = crepe.editor.action(ctx => ({
    markdown: crepe!.getMarkdown(),
    document: ctx.get(editorViewCtx).state.doc.toJSON(),
    ast: ctx.get(remarkCtx).runSync(ctx.get(remarkCtx).parse(markdown), markdown),
    ...(adapted ? (() => {
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
