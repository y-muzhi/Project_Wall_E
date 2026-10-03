import type { Crepe } from '@milkdown/crepe';
import type { Ctx } from '@milkdown/kit/ctx';
import { editorViewCtx } from '@milkdown/kit/core';
import { undo, redo } from '@milkdown/kit/prose/history';
import { splitBlock } from '@milkdown/kit/prose/commands';
import { TextSelection } from '@milkdown/kit/prose/state';
import { EditedSnapshotLedger, type EditedSnapshot } from '../../src/documents/edited-snapshot.ts';
import { EditorSource } from '../../src/documents/editor-source.ts';
import { moveTopBlock, identityState } from '../../src/documents/identity.ts';

const initialTime = '2026-10-03T00:00:00.000Z';
export const editTime = '2026-10-03T00:01:00.000Z';
export function fixtureDraft(ctx: Ctx, markdown: string, ids: readonly number[], next: number) {
  const source = new EditorSource(ctx, markdown);
  // Test fixtures only: structural origins, not real database source objects.
  return {id: 90, requirement_id: 7, document_type: 'MANUAL_DRAFT', markdown_content: markdown,
    block_state_json: {schema_version: 1, next_block_id: next, blocks: source.blocks.map((block, index) => ({
      block_id: ids[index]!, block_type: block.block_type, section_path: block.section_path,
      created_by_type: 'SYSTEM', created_source_type: 'TEMPLATE', created_source_id: null, created_at: initialTime,
      last_modified_by_type: 'SYSTEM', last_modified_source_type: 'TEMPLATE', last_modified_source_id: null, last_modified_at: initialTime,
    }))}, content_version: 3, created_at: initialTime, updated_at: initialTime};
}
function equal(actual: unknown, expected: unknown, label: string): void {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error(`${label}: ${JSON.stringify(actual)} != ${JSON.stringify(expected)}`);
}
function blockIds(pair: EditedSnapshot) { return pair.block_state_json.blocks.map(block => block.block_id); }

export async function verifyEditedSnapshots(load: (markdown: string, ids: readonly number[], next: number) => Promise<unknown>, get: () => Crepe) {
  const checks: string[] = [];
  const outputs: {pair: EditedSnapshot; projection: {block_type: string; plain_text: string; section_path: readonly string[]}[]}[] = [];
  async function setup(markdown: string, ids: readonly number[], next: number) {
    await load(markdown, ids, next);
    return get().editor.action(ctx => new EditedSnapshotLedger(ctx, fixtureDraft(ctx, markdown, ids, next), ctx.get(editorViewCtx).state));
  }
  function action<T>(callback: (ctx: Ctx) => T): T { return get().editor.action(callback); }
  function capture(ledger: EditedSnapshotLedger, at = editTime) {
    return action(ctx => {
      const pair = ledger.capture(ctx.get(editorViewCtx).state, at);
      outputs.push({pair, projection: new EditorSource(ctx, pair.markdown_content).blocks.map(block => ({
        block_type: block.block_type, plain_text: block.plain_text, section_path: block.section_path,
      }))});
      return pair;
    });
  }

  const raw = '\r\n甲 *乙*\r\n\r\n[重复]: /a\r\n[重复]: /b\r\n\r\n<!-- 惰性 -->\r\n\r\n尾😀\r\n\t\r\n';
  let ledger = await setup(raw, [10,20,30,40,50], 60);
  equal(capture(ledger).markdown_content, raw, '无编辑完整源码');
  action(ctx => {
    const view = ctx.get(editorViewCtx);
    view.dispatch(view.state.tr.insertText('新', 1));
  });
  const edited = capture(ledger);
  const parsed = action(ctx => new EditorSource(ctx, edited.markdown_content));
  equal(parsed.blocks.slice(1).map(block => block.markdown), ['[重复]: /a\r\n','[重复]: /b\r\n','<!-- 惰性 -->\r\n','尾😀\r\n'], '未改区块CRLF及定义保留');
  equal(edited.block_state_json.blocks.map(block => block.last_modified_by_type), ['USER','SYSTEM','SYSTEM','SYSTEM','SYSTEM'], '只有原文变化更新署名');
  equal(edited.block_state_json.blocks[0]!.created_by_type, 'SYSTEM', '已有创建不改');
  equal(edited.block_state_json.blocks[0]!.last_modified_source_id, 90, '来源为实际输入草稿ID');
  equal(capture(ledger).block_state_json, edited.block_state_json, '重复捕获不改元数据');
  checks.push('edit-preserves-unrelated-CRLF-definitions-HTML', 'creation-preserved-and-draft-origin', 'repeat-capture-stable');

  ledger = await setup('\r\n甲\r\n\r\n乙\r\n\r\n', [10,20], 30);
  const beforeMove = capture(ledger);
  action(ctx => { const view = ctx.get(editorViewCtx); view.dispatch(moveTopBlock(view.state, 1, 0)); });
  const moved = capture(ledger);
  equal(blockIds(moved), [20,10], '移动身份');
  equal(moved.block_state_json.blocks, [...beforeMove.block_state_json.blocks].reverse(), '无章节变化移动保持全部元数据');
  checks.push('explicit-move-preserves-origin-and-time');

  ledger = await setup('# A\r\n\r\np\r\n\r\n## B\r\n\r\nq\r\n', [10,20,30,40], 50);
  action(ctx => { const view = ctx.get(editorViewCtx); view.dispatch(view.state.tr.insertText('X', 2)); });
  const headingEdit = capture(ledger);
  equal(headingEdit.block_state_json.blocks.map(block => block.section_path), [['AX'],['AX'],['AX','B'],['AX','B']], '派生章节路径');
  equal(headingEdit.block_state_json.blocks.map(block => block.last_modified_at), [editTime,editTime,editTime,editTime], '派生变化署名');
  checks.push('heading-change-updates-descendant-paths');

  ledger = await setup('甲\r\n', [10], 30);
  action(ctx => { const view = ctx.get(editorViewCtx); view.dispatch(view.state.tr.insert(view.state.doc.content.size, view.state.doc.firstChild!)); });
  const copied = capture(ledger);
  equal(blockIds(copied), [10,30], '复制同文不复用身份');
  equal(copied.block_state_json.blocks[1]!.created_source_id, 90, '复制创建人工来源');
  equal(copied.block_state_json.blocks[1]!.created_at, editTime, '复制创建时间');
  checks.push('copy-allocates-manual-creation');

  ledger = await setup('甲乙\r\n\r\n尾\r\n', [10,20], 30);
  action(ctx => { const view = ctx.get(editorViewCtx); view.dispatch(view.state.tr.addMark(1, 2, view.state.schema.marks.strong!.create())); });
  const marked = capture(ledger);
  equal(action(ctx => new EditorSource(ctx, marked.markdown_content)).blocks.map(block => block.plain_text), ['甲乙','尾'], '加标记不丢文本');
  equal(marked.block_state_json.blocks[1]!.last_modified_by_type, 'SYSTEM', '邻域不误署名');
  checks.push('mark-edit-preserves-intent');

  ledger = await setup('```js\r\nabc\r\n```\r\n\r\n尾\r\n', [10,20], 30);
  action(ctx => { const view = ctx.get(editorViewCtx); view.dispatch(view.state.tr.insertText('X', 2)); });
  const code = capture(ledger);
  equal(action(ctx => new EditorSource(ctx, code.markdown_content)).blocks.map(block => block.plain_text), ['aXbc\n','尾'], '代码编辑投影');
  checks.push('code-edit-full-reparse');

  ledger = await setup('| k | v |\r\n| --- | --- |\r\n| a | b |\r\n\r\n尾\r\n', [10,20], 30);
  action(ctx => {
    const view = ctx.get(editorViewCtx);
    let position = -1;
    view.state.doc.descendants((node, pos) => { if (node.isText && node.text === 'b') position = pos; });
    if (position < 0) throw new Error('没有找到真实单元格');
    view.dispatch(view.state.tr.insertText('X', position + 1));
  });
  const table = capture(ledger);
  equal(action(ctx => new EditorSource(ctx, table.markdown_content)).blocks.map(block => block.plain_text), ['k\tv\na\tbX','尾'], '真实表格编辑');
  checks.push('table-edit-full-reparse');

  for (const [name, markdown] of [
    ['blockquote', '> 甲\r\n>\r\n> 乙\r\n'], ['bullet_list', '- 甲\r\n- 乙\r\n'],
    ['ordered_list', '3. 甲\r\n4. 乙\r\n'], ['task_list', '- [ ] 甲\r\n- [x] 乙\r\n'],
  ]) {
    ledger = await setup(markdown! + '\r\n尾\r\n', [10,20], 30);
    action(ctx => {
      const view = ctx.get(editorViewCtx);
      let position = -1;
      view.state.doc.descendants((node, pos) => { if (node.isText && node.text === '甲') position = pos; });
      if (position < 0) throw new Error('没有找到真实容器文本');
      view.dispatch(view.state.tr.insertText('新', position));
    });
    const container = capture(ledger);
    const containerSource = action(ctx => new EditorSource(ctx, container.markdown_content));
    equal(containerSource.blocks[0]!.plain_text, '新甲\n乙', `${name}保留嵌套内容`);
    equal(containerSource.blocks[1]!.markdown, '尾\r\n', `${name}未改邻域`);
    equal(blockIds(container), [10,20], `${name}顶层身份`);
    checks.push(`${name}-edit-full-reparse`);
  }

  ledger = await setup('[x]: /old\r\n\r\n[x]\r\n\r\n***\r\n', [10,20,30], 40);
  action(ctx => {
    const view = ctx.get(editorViewCtx);
    view.dispatch(view.state.tr.insertText('[x]: /new\r\n', 1, view.state.doc.firstChild!.nodeSize - 1));
  });
  const definition = capture(ledger);
  const definitionSource = action(ctx => new EditorSource(ctx, definition.markdown_content));
  equal(definitionSource.blocks[1]!.markdown, '[x]\r\n', '引用原文保留');
  equal(definitionSource.blocks[1]!.plain_text, 'x', '引用由完整新快照解析');
  equal(definitionSource.blocks[1]!.node.firstChild!.marks[0]!.attrs.href, '/new', '定义改变实际引用目标');
  equal(definition.block_state_json.blocks[1]!.last_modified_by_type, 'SYSTEM', '同原文同章节引用不误署名');
  equal(definitionSource.blocks[2]!.markdown, '***\r\n', '分隔线原始拼写保留');
  checks.push('definition-edit-rebinds-verbatim-reference');

  ledger = await setup('甲\r\n\r\n\r\n乙\r\n\r\n', [10,20], 30);
  const deletionBaseline = capture(ledger);
  action(ctx => { const view = ctx.get(editorViewCtx); view.dispatch(view.state.tr.delete(0, view.state.doc.firstChild!.nodeSize)); });
  equal(blockIds(capture(ledger)), [20], '删除只保留实际区块');
  action(ctx => { const view = ctx.get(editorViewCtx); if (!undo(view.state, tr => view.dispatch(tr))) throw new Error('真实撤销失败'); });
  const restored = capture(ledger);
  equal(restored.markdown_content, deletionBaseline.markdown_content, '撤销删除恢复原文含全部空白');
  equal(restored.block_state_json.blocks[0]!.created_at, initialTime, '撤销恢复创建来源时间');
  action(ctx => { const view = ctx.get(editorViewCtx); if (!redo(view.state, tr => view.dispatch(tr))) throw new Error('真实重做失败'); });
  equal(blockIds(capture(ledger)), [20], '重做删除');
  checks.push('deletion-undo-redo-restores-authored-source');

  ledger = await setup('甲\r\n', [10], 30);
  const invalidCurrent = action(ctx => ({...fixtureDraft(ctx, '甲\r\n', [10], 30), document_type: 'CURRENT'}));
  let currentRejected = false;
  try { action(ctx => new EditedSnapshotLedger(ctx, invalidCurrent, ctx.get(editorViewCtx).state)); } catch { currentRejected = true; }
  if (!currentRejected) throw new Error('CURRENT被作为人工编辑来源');
  const mismatched = action(ctx => fixtureDraft(ctx, '另一正文\r\n', [10], 30));
  let mismatchedRejected = false;
  try { action(ctx => new EditedSnapshotLedger(ctx, mismatched, ctx.get(editorViewCtx).state)); } catch { mismatchedRejected = true; }
  if (!mismatchedRejected) throw new Error('初始同ID异正文被绑定');
  checks.push('current-and-mismatched-initial-state-rejected');

  ledger = await setup('甲乙\n\n尾\n', [10,20], 30);
  action(ctx => {
    const view = ctx.get(editorViewCtx);
    view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc, 2)));
    if (!splitBlock(view.state, tr => view.dispatch(tr))) throw new Error('真实拆分失败');
  });
  equal(capture(ledger).markdown_content, '甲\n\n乙\n\n尾\n', '拆分生成边界');
  action(ctx => {
    const view = ctx.get(editorViewCtx);
    view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc, 1)));
    if (!splitBlock(view.state, tr => view.dispatch(tr))) throw new Error('真实空前段拆分失败');
  });
  const emptyFirst = capture(ledger);
  equal(emptyFirst.markdown_content, '甲\n\n乙\n\n尾\n', '空前段不转移正文间gap到文首');
  equal(blockIds(emptyFirst), [31,30,20], '空前段不伪造业务区块');
  checks.push('generated-boundaries-and-empty-first-split');

  ledger = await setup('<!-- ok -->\r\n\r\n尾\r\n', [10,20], 30);
  const unchanged = capture(ledger);
  action(ctx => { const view = ctx.get(editorViewCtx); view.dispatch(view.state.tr.insertText('<!--', 1, view.state.doc.firstChild!.nodeSize - 1)); });
  let rejected = false;
  try { capture(ledger); } catch (error) { if ((error as {code?: string}).code !== 'DOCUMENT_INVALID') throw error; rejected = true; }
  if (!rejected) throw new Error('吞邻块的未闭合HTML被接受');
  action(ctx => { const view = ctx.get(editorViewCtx); view.dispatch(view.state.tr.insertText('<!-- ok -->\r\n', 1, view.state.doc.firstChild!.nodeSize - 1)); });
  equal(capture(ledger), unchanged, '失败不污染源码/元数据');
  checks.push('unsafe-composition-rejected-and-ledger-atomic');

  ledger = await setup('甲\r\n\r\n乙\r\n', [10,20], 30);
  action(ctx => { const view = ctx.get(editorViewCtx); view.dispatch(view.state.tr.delete(0, view.state.doc.content.size)); });
  const empty = capture(ledger);
  equal(empty.block_state_json.blocks, [], '全删空文档无伪造caret块');
  equal(empty.block_state_json.next_block_id, 30, '全删高水位保留');
  let invalidTimeRejected = false;
  try { capture(ledger, '2026-02-30T00:00:00.000Z'); } catch { invalidTimeRejected = true; }
  if (!invalidTimeRejected) throw new Error('空文档接受非法时间');
  equal(action(ctx => identityState(ctx.get(editorViewCtx).state)).next_block_id, 30, '失败未改编辑器高水位');
  checks.push('empty-document-high-water-and-time-validation');
  return {checks, outputs, scope: 'Actual Crepe transaction output; fixture origins only, no HTTP/DB save assertion'};
}
