import type { Crepe } from '@milkdown/crepe';
import { editorViewCtx } from '@milkdown/kit/core';
import { undo, redo, closeHistory } from '@milkdown/kit/prose/history';
import { EditorSource, EditorSourceInvalid } from '../../src/documents/editor-source.ts';
import { EditedSnapshotLedger, type EditedSnapshot } from '../../src/documents/edited-snapshot.ts';
import { IdentityInvalid, identityState, topBlockIds } from '../../src/documents/identity.ts';
import { normalizeRawSourceBlock } from '../../src/documents/source-normalization.ts';
import { fixtureDraft, editTime } from './edited-snapshot.ts';

function equal(actual: unknown, expected: unknown, label: string): void {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error(`${label}: ${JSON.stringify(actual)} != ${JSON.stringify(expected)}`);
}

export async function verifySourceNormalization(load: (markdown: string, ids: readonly number[], next: number) => Promise<unknown>, get: () => Crepe) {
  const checks: string[] = [], outputs: {pair: EditedSnapshot; projection: {block_type: string; plain_text: string; section_path: readonly string[]}[]}[] = [];
  async function setup(markdown: string, ids: readonly number[], next: number) {
    await load(markdown, ids, next);
    return get().editor.action(ctx => new EditedSnapshotLedger(ctx, fixtureDraft(ctx, markdown, ids, next), ctx.get(editorViewCtx).state));
  }
  function record(pair: EditedSnapshot) {
    outputs.push(get().editor.action(ctx => ({pair, projection: new EditorSource(ctx, pair.markdown_content).blocks.map(block => ({
      block_type: block.block_type, plain_text: block.plain_text, section_path: block.section_path,
    }))})));
    if (pair.markdown_content.includes('walle_block_id') || pair.markdown_content.includes('walle_source_revision') ||
        get().getMarkdown().includes('walle_source_revision') ||
        JSON.stringify(pair.block_state_json).includes('walle_source_revision')) throw new Error('重新分块泄漏私有历史属性');
  }
  function rewrite(ledger: EditedSnapshotLedger, value: string, index = 0) {
    return get().editor.action(ctx => {
      const view = ctx.get(editorViewCtx);
      let position = 0;
      for (let child = 0; child < index; child++) position += view.state.doc.child(child).nodeSize;
      const original = view.state.doc.child(index);
      view.dispatch(view.state.tr.insertText(value, position + 1, position + 1 + original.content.size));
      const pending = view.state, normalized = normalizeRawSourceBlock(ctx, pending, index);
      const pair = ledger.capture(normalized.state, editTime, normalized); // Validate before replacing the visible state.
      if (view.state !== pending) throw new Error('预检提前修改实际视图');
      view.updateState(normalized.state);
      equal(topBlockIds(view.state.doc).filter(id => id !== null), pair.block_state_json.blocks.map(block => block.block_id), '视图/输出身份不同');
      return pair;
    });
  }

  const initial = '\r\n<div>\r\n原样\r\n</div>\r\n\r\n尾😀\r\n';
  let ledger = await setup(initial, [10,20], 30);
  const changed = rewrite(ledger, '\r\n甲😀\r\n\r\n# 新章\r\n');
  equal(changed.markdown_content, '\r\n\r\n甲😀\r\n\r\n# 新章\r\n\r\n尾😀\r\n', '分块原始CRLF/gap');
  equal(changed.block_state_json.blocks.map(block => block.block_id), [10,30,20], '首ID与新ID');
  equal(changed.block_state_json.next_block_id, 31, '分块高水位');
  equal(changed.block_state_json.blocks.map(block => block.created_by_type), ['SYSTEM','USER','SYSTEM'], '创建来源继承');
  equal(changed.block_state_json.blocks[1]!.created_source_id, 90, '新块引用实际输入草稿');
  equal(changed.block_state_json.blocks[2]!.section_path, ['新章'], '后继章节路径');
  record(changed);
  get().editor.action(ctx => {
    const view = ctx.get(editorViewCtx);
    equal(view.state.doc.child(0).type.name, 'paragraph', '原始节点未转换为真实段落');
    equal(view.state.doc.child(1).type.name, 'heading', '新标题未显示');
    const repeated = ledger.capture(view.state, editTime);
    equal(repeated, changed, '重复输出改变原文/元数据'); record(repeated);
    if (!undo(view.state, tr => view.dispatch(tr))) throw new Error('实际撤销未执行');
    const restored = ledger.capture(view.state, editTime);
    equal(restored.markdown_content, initial, '撤销未恢复原始源');
    equal(restored.block_state_json.blocks.map(block => block.block_id), [10,20], '撤销身份');
    equal(restored.block_state_json.next_block_id, 31, '撤销回退高水位'); record(restored);
    if (!redo(view.state, tr => view.dispatch(tr))) throw new Error('实际重做未执行');
    const redone = ledger.capture(view.state, editTime);
    equal(redone.markdown_content, changed.markdown_content, '重做原始字节');
    equal(redone.block_state_json.blocks.map(block => block.block_id), [10,30,20], '重做身份'); record(redone);
  });
  checks.push('raw-split-source-gaps-and-view', 'creation-path-and-high-water', 'repeat-undo-redo-exact-source');

  const scenarios = [
    {name: 'paragraph', value: '甲\r\n', types: ['paragraph']},
    {name: 'paragraphs-eof', value: '甲\n\n乙', types: ['paragraph','paragraph']},
    {name: 'adjacent-definitions', value: '[a]: /one\r\n[a]: /two\r\n\r\n[标签][a]\r\n', types: ['link_definition','link_definition','paragraph']},
    {name: 'code', value: '```python\r\nx😀\r\n```\r\n', types: ['code_block']},
    {name: 'table', value: '| 键 | 值 |\r\n| --- | --- |\r\n| A | 一 |\r\n', types: ['table']},
    {name: 'list', value: '- 一\r\n- 二\r\n', types: ['bullet_list']},
    {name: 'empty-whitespace', value: '\r\n \r\n', types: []},
  ];
  for (const scenario of scenarios) {
    ledger = await setup('<div>起</div>\r\n', [10], 20);
    const pair = rewrite(ledger, scenario.value);
    equal(pair.markdown_content, scenario.value, '重解析改变输入原文');
    equal(pair.block_state_json.blocks.map(block => block.block_type), scenario.types, '实际解析类型');
    equal(pair.block_state_json.blocks.map(block => block.block_id), scenario.types.map((_type, index) => index ? 19 + index : 10), '类型变化身份');
    record(pair); checks.push(scenario.name);
  }

  const withFooter = '\r\n<div>起</div>\r\n\r\n尾\r\n';
  ledger = await setup(withFooter, [10,20], 30);
  const whitespace = rewrite(ledger, '\n \n');
  equal(whitespace.markdown_content, '\r\n\n \n\r\n尾\r\n', '删除原始块后空白次序');
  equal(whitespace.block_state_json.blocks.map(block => block.block_id), [20], '删除未保留空白Block'); record(whitespace);
  get().editor.action(ctx => {
    const view = ctx.get(editorViewCtx);
    if (!undo(view.state, tr => view.dispatch(tr))) throw new Error('空白删除撤销失败');
    const pair = ledger.capture(view.state, editTime);
    equal(pair.markdown_content, withFooter, '空白删除撤销原源'); record(pair);
  });
  checks.push('removed-block-whitespace-order-and-history');

  ledger = await setup(withFooter, [10,20], 30);
  get().editor.action(ctx => {
    const view = ctx.get(editorViewCtx);
    view.dispatch(view.state.tr.insertText('<script>\r\n未闭合\r\n', 1, 1 + view.state.doc.child(0).content.size));
    const pending = view.state, normalized = normalizeRawSourceBlock(ctx, pending, 0);
    try { ledger.capture(normalized.state, editTime, normalized); throw new Error('单块重解析吞掉后继仍被接受'); }
    catch (error) { if (!(error instanceof EditorSourceInvalid)) throw error; }
    if (view.state !== pending || view.state.doc.child(0).textContent !== '<script>\r\n未闭合\r\n') throw new Error('拒绝组合丢失用户当前原文');
    if (!undo(view.state, tr => view.dispatch(tr))) throw new Error('拒绝组合后的撤销失败');
    const pair = ledger.capture(view.state, editTime);
    equal(pair.markdown_content, withFooter, '失败组合污染源码账本'); record(pair);
  });
  checks.push('composition-failure-keeps-pending-source-and-ledger');

  ledger = await setup('<div>起</div>\r\n', [10], 20);
  const first = rewrite(ledger, '甲\n'); record(first);
  get().editor.action(ctx => {
    const view = ctx.get(editorViewCtx);
    view.dispatch(closeHistory(view.state.tr));
    view.dispatch(view.state.tr.setNodeMarkup(0, view.state.schema.nodes.walle_raw_source!, {kind: 'html_block', walle_block_id: 10}));
  });
  const second = rewrite(ledger, '甲\r\n'); record(second);
  get().editor.action(ctx => {
    const view = ctx.get(editorViewCtx);
    if (!undo(view.state, tr => view.dispatch(tr))) throw new Error('等价节点字节撤销失败');
    const reverted = ledger.capture(view.state, editTime);
    equal(reverted.markdown_content, '甲\n', '节点相同误恢复较新CRLF'); record(reverted);
    if (!redo(view.state, tr => view.dispatch(tr))) throw new Error('等价节点字节重做失败');
    const replayed = ledger.capture(view.state, editTime);
    equal(replayed.markdown_content, '甲\r\n', '节点相同丢失CRLF'); record(replayed);
    view.dispatch(closeHistory(view.state.tr));
    view.dispatch(view.state.tr.insertText('新', 1));
    const ordinary = ledger.capture(view.state, editTime);
    equal(ordinary.markdown_content, '新甲\n', '修订后普通富文本序列化'); record(ordinary);
    if (!undo(view.state, tr => view.dispatch(tr))) throw new Error('普通富文本撤销失败');
    const originalRaw = ledger.capture(view.state, editTime);
    equal(originalRaw.markdown_content, '甲\r\n', '普通撤销未恢复修订源码'); record(originalRaw);
  });
  checks.push('same-rich-nodes-distinct-raw-history', 'ordinary-rich-edit-restores-source-revision');

  ledger = await setup('<div>起</div>\r\n', [10], 20);
  get().editor.action(ctx => {
    const view = ctx.get(editorViewCtx);
    view.dispatch(view.state.tr.insertText('甲\n', 1, 1 + view.state.doc.child(0).content.size));
    const before = view.state, normalized = normalizeRawSourceBlock(ctx, before, 0);
    for (const [state, proof] of [[before, normalized], [normalized.state, {state: normalized.state}]] as const) {
      try { ledger.capture(state, editTime, proof); throw new Error('伪造/异状态证明被接受'); }
      catch (error) { if (!(error instanceof EditorSourceInvalid)) throw error; }
    }
    if (view.state !== before) throw new Error('拒绝证明修改视图');
    const pair = ledger.capture(normalized.state, editTime, normalized); view.updateState(normalized.state); record(pair);
  });
  checks.push('proof-and-state-atomic-rejection');

  ledger = await setup('<div>起</div>\r\n', [1], Number.MAX_SAFE_INTEGER - 1);
  get().editor.action(ctx => {
    const view = ctx.get(editorViewCtx);
    view.dispatch(view.state.tr.insertText('一\n\n二\n\n三\n', 1, 1 + view.state.doc.child(0).content.size));
    const before = view.state, identity = identityState(before);
    try { normalizeRawSourceBlock(ctx, before, 0); throw new Error('容量耗尽仍分配'); }
    catch (error) { if (!(error instanceof IdentityInvalid) || error.code !== 'CAPACITY_EXCEEDED') throw error; }
    if (view.state !== before) throw new Error('容量失败修改实际源');
    equal(identityState(view.state).next_block_id, identity.next_block_id, '容量失败回退/前进高水位');
    equal([...identityState(view.state).known_ids], [...identity.known_ids], '容量失败泄漏新ID');
  });
  checks.push('capacity-keeps-pending-source-and-identity');
  return {scope: 'Explicit top-level raw reparse, actual PM/history and complete local source pair; no complete component or HTTP save', checks, outputs};
}
