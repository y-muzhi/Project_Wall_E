import type { Crepe } from '@milkdown/crepe';
import { editorViewCtx } from '@milkdown/kit/core';
import { undo, redo, closeHistory } from '@milkdown/kit/prose/history';
import { EditorSource, EditorSourceInvalid } from '../../src/documents/editor-source.ts';
import { EditedSnapshotLedger, type EditedSnapshot } from '../../src/documents/edited-snapshot.ts';
import { IdentityInvalid, identityState, topBlockIds } from '../../src/documents/identity.ts';
import { TextSelection } from '@milkdown/kit/prose/state';
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

  const containers = [
    {name: 'quote-heading', markdown: '> <div>起</div>\r\n', value: '甲😀\r\n\r\n# 新章\r\n',
      type: 'blockquote', plain: '甲😀\n新章', descendants: ['paragraph','heading']},
    {name: 'list-paragraphs', markdown: '- <div>起</div>\r\n', value: '甲\r\n\r\n乙😀\r\n',
      type: 'bullet_list', plain: '甲\n乙😀', descendants: ['list_item','paragraph','paragraph']},
    {name: 'quote-list-code', markdown: '> - <div>起</div>\r\n', value: '```python\r\nx😀\r\n```\r\n',
      type: 'blockquote', plain: 'x😀\n', descendants: ['bullet_list','list_item','code_block']},
    {name: 'quote-definition-table', markdown: '> [a]: /old\r\n', value: '| 键 | 值 |\r\n| --- | --- |\r\n| A | 一 |\r\n',
      type: 'blockquote', plain: '键\t值\nA\t一', descendants: ['table','table_header_row','table_header','paragraph','table_header','paragraph','table_row','table_cell','paragraph','table_cell','paragraph']},
    {name: 'ordered-task', markdown: '2. <div>起</div>\r\n', value: '- [x] 一\r\n- [ ] 二\r\n',
      type: 'ordered_list', plain: '一\n二', descendants: ['list_item','bullet_list','list_item','paragraph','list_item','paragraph']},
    {name: 'quote-html-inert', markdown: '> <div>起</div>\r\n', value: '<script>window.__walleNestedReparse=1</script>\r\n',
      type: 'blockquote', plain: '<script>window.__walleNestedReparse=1</script>\r\n', descendants: ['walle_raw_source']},
  ];
  for (const scenario of containers) {
    const initial = scenario.markdown + '\r\n尾😀\r\n';
    ledger = await setup(initial, [10,20], 30);
    get().editor.action(ctx => {
      const view = ctx.get(editorViewCtx);
      let rawPosition: number | undefined, rawSize = 0;
      view.state.doc.child(0).descendants((node, position) => {
        if (node.type.name === 'walle_raw_source' && rawPosition === undefined) { rawPosition = position + 2; rawSize = node.content.size; }
      });
      if (rawPosition === undefined) throw new Error('容器缺少实际原始节点');
      view.dispatch(view.state.tr.insertText(scenario.value, rawPosition, rawPosition + rawSize));
      const pending = view.state, normalized = normalizeRawSourceBlock(ctx, pending, 0);
      const pair = ledger.capture(normalized.state, editTime, normalized);
      if (view.state !== pending) throw new Error('容器预检提前改变实际视图');
      view.updateState(normalized.state);
      const source = new EditorSource(ctx, pair.markdown_content);
      equal(source.blocks.map(block => ({type: block.block_type, plain: block.plain_text})),
        [{type: scenario.type, plain: scenario.plain}, {type: 'paragraph', plain: '尾😀'}], `容器重解释投影 ${scenario.name}`);
      const descendants: string[] = [];
      view.state.doc.child(0).descendants(node => { if (!node.isText) descendants.push(node.type.name); });
      equal(descendants, scenario.descendants, `实际子块类型 ${scenario.name}`);
      equal(topBlockIds(view.state.doc), [10,20], '容器内部编辑改变顶层身份');
      equal(pair.block_state_json.next_block_id, 30, '容器内部编辑消耗顶层ID');
      equal(pair.block_state_json.blocks.map(block => block.created_by_type), ['SYSTEM','SYSTEM'], '容器创建来源改变');
      equal(source.blocks[1]!.markdown, '尾😀\r\n', '容器重解析改变未编辑后继源');
      if ('__walleNestedReparse' in window || view.dom.querySelector('script')) throw new Error('容器原始HTML执行');
      record(pair);
      if (!undo(view.state, tr => view.dispatch(tr))) throw new Error('容器实际撤销未执行');
      const restored = ledger.capture(view.state, editTime);
      equal(restored.markdown_content, initial, '容器撤销未恢复原始CRLF/标记'); record(restored);
      if (!redo(view.state, tr => view.dispatch(tr))) throw new Error('容器实际重做未执行');
      const replayed = ledger.capture(view.state, editTime);
      equal(replayed.markdown_content, pair.markdown_content, '容器重做原文不同'); record(replayed);
    });
    checks.push(`nested-${scenario.name}`);
  }

  const middleSource = '# 章\r\n\r\n> <div>起</div>\r\n>\r\n> [stay]: /kept\r\n>\r\n> **尾** [标签][stay]\r\n\r\n后继\r\n';
  ledger = await setup(middleSource, [10,20,30], 40);
  get().editor.action(ctx => {
    const view = ctx.get(editorViewCtx), top = view.state.doc.child(1);
    let position = view.state.doc.child(0).nodeSize + 2;
    view.dispatch(view.state.tr.insertText('甲😀\r\n', position, position + top.child(0).content.size));
    const normalized = normalizeRawSourceBlock(ctx, view.state, 1);
    const pair = ledger.capture(normalized.state, editTime, normalized); view.updateState(normalized.state);
    const source = new EditorSource(ctx, pair.markdown_content);
    equal(source.blocks.map(block => block.plain_text), ['章','甲😀\n[stay]: /kept\r\n\n尾 标签','后继'], '非首容器及兄弟投影');
    equal(source.blocks.map(block => block.section_path), [['章'],['章'],['章']], '容器上下文章节路径');
    equal(topBlockIds(view.state.doc), [10,20,30], '非首容器身份');
    equal(pair.block_state_json.next_block_id, 40, '非首容器高水位');
    equal(source.blocks[0]!.markdown, '# 章\r\n', '前标题源改变');
    equal(source.blocks[2]!.markdown, '后继\r\n', '后继源改变');
    const quote = view.state.doc.child(1);
    equal(quote.child(1).textContent, '[stay]: /kept\r\n', '未编辑定义原始换行丢失');
    let bold = false, link = false;
    quote.child(2).descendants(node => {
      if (node.isText && node.text === '尾') bold = node.marks.some(mark => mark.type.name === 'strong');
      if (node.isText && node.text === '标签') link = node.marks.some(mark => mark.type.name === 'link' && mark.attrs.href === '/kept');
      if (node.attrs.walle_block_id != null) throw new Error('内部兄弟取得顶层ID');
    });
    if (!bold || !link) throw new Error('未编辑兄弟的标记或引用丢失');
    record(pair);
    if (!undo(view.state, tr => view.dispatch(tr))) throw new Error('非首容器撤销失败');
    const restored = ledger.capture(view.state, editTime);
    equal(restored.markdown_content, middleSource, '兄弟容器撤销原文'); record(restored);
    if (!redo(view.state, tr => view.dispatch(tr))) throw new Error('非首容器重做失败');
    const replayed = ledger.capture(view.state, editTime);
    equal(replayed.markdown_content, pair.markdown_content, '兄弟容器重做原文'); record(replayed);
  });
  checks.push('nested-middle-container-preserves-raw-rich-siblings-and-path');

  const references = [
    {name: 'definition-target', initial: '[a]: /old\r\n\r\n[标签][a]\r\n', value: '[a]: /new\r\n',
      ids: [10,20], before: {text: '标签', href: '/old'}, after: {text: '标签', href: '/new'}},
    {name: 'definition-removal', initial: '[a]: /old\r\n\r\n[标签][a]\r\n', value: '移除定义\r\n',
      ids: [10,20], before: {text: '标签', href: '/old'}, after: {text: '[标签][a]', href: null}},
    {name: 'definition-addition', initial: '<div>起</div>\r\n\r\n[标签][a]\r\n', value: '[a]: /new\r\n',
      ids: [10,20], before: {text: '[标签][a]', href: null}, after: {text: '标签', href: '/new'}},
    {name: 'duplicate-first-definition-removal', initial: '[a]: /old\r\n[a]: /second\r\n\r\n[标签][a]\r\n', value: '移除首定义\r\n',
      ids: [10,20,30], before: {text: '标签', href: '/old'}, after: {text: '标签', href: '/second'}},
    {name: 'nested-definition-external-reference', initial: '> [a]: /old\r\n\r\n[标签][a]\r\n', value: '[a]: /new\r\n',
      ids: [10,20], before: {text: '标签', href: '/old'}, after: {text: '标签', href: '/new'}},
  ];
  for (const scenario of references) {
    const next = scenario.ids.at(-1)! + 10;
    ledger = await setup(scenario.initial, scenario.ids, next);
    get().editor.action(ctx => {
      const view = ctx.get(editorViewCtx);
      const target = () => {
        const node = view.state.doc.lastChild!;
        return {text: node.textContent, href: node.firstChild?.marks.find(mark => mark.type.name === 'link')?.attrs.href ?? null};
      };
      equal(target(), scenario.before, '引用初始视图');
      let position = 1, size = view.state.doc.child(0).content.size;
      if (view.state.doc.child(0).type.name !== 'walle_raw_source') {
        view.state.doc.child(0).descendants((node, offset) => {
          if (node.type.name === 'walle_raw_source') { position = offset + 2; size = node.content.size; }
        });
      }
      view.dispatch(view.state.tr.insertText(scenario.value, position, position + size));
      const pending = view.state, normalized = normalizeRawSourceBlock(ctx, pending, 0);
      const prepared = ledger.prepare(normalized.state, editTime, normalized);
      if (view.state !== pending) throw new Error('上下文预检提前修改视图');
      view.updateState(prepared.state);
      const pair = ledger.accept(prepared, view.state);
      equal(target(), scenario.after, '完整源码与实际引用视图不同');
      equal(view.dom.querySelector('a')?.getAttribute('href') ?? null, scenario.after.href, '实际DOM仍保留旧引用');
      equal(new EditorSource(ctx, pair.markdown_content).blocks.at(-1)!.markdown, '[标签][a]\r\n', '重绑定改写未编辑引用原文');
      equal(topBlockIds(view.state.doc), scenario.ids, '重绑定改变区块身份');
      equal(pair.block_state_json.next_block_id, next, '重绑定分配新ID');
      equal(pair.block_state_json.blocks.at(-1)!.last_modified_by_type, 'SYSTEM', '未编辑引用原文伪造修改署名');
      equal(ledger.capture(view.state, editTime), pair, '重绑定后普通输出改写引用或元数据'); record(pair);
      if (!undo(view.state, tr => view.dispatch(tr))) throw new Error('跨块引用实际撤销失败');
      const restored = ledger.prepare(view.state, editTime);
      view.updateState(restored.state); ledger.accept(restored, view.state);
      equal(target(), scenario.before, '一次撤销未同时恢复定义与引用视图');
      equal(restored.pair.markdown_content, scenario.initial, '跨块引用撤销丢失原始源'); record(restored.pair);
      if (!redo(view.state, tr => view.dispatch(tr))) throw new Error('跨块引用实际重做失败');
      const replayed = ledger.prepare(view.state, editTime);
      view.updateState(replayed.state); ledger.accept(replayed, view.state);
      equal(target(), scenario.after, '一次重做未同时恢复定义与引用视图');
      equal(replayed.pair.markdown_content, pair.markdown_content, '跨块引用重做原文改变'); record(replayed.pair);
    });
    checks.push(`context-${scenario.name}`);
  }

  const imageSource = '[a]: /old "旧题"\r\n\r\n![图😀][a]\r\n';
  ledger = await setup(imageSource, [10,20], 30);
  get().editor.action(ctx => {
    const view = ctx.get(editorViewCtx);
    const image = () => { const node = view.state.doc.child(1).firstChild!; return {type: node.type.name, src: node.attrs.src, alt: node.attrs.alt, title: node.attrs.title}; };
    view.dispatch(view.state.tr.insertText('[a]: /new "新题"\r\n', 1, 1 + view.state.doc.child(0).content.size));
    const normalized = normalizeRawSourceBlock(ctx, view.state, 0);
    const prepared = ledger.prepare(normalized.state, editTime, normalized);
    view.updateState(prepared.state); const pair = ledger.accept(prepared, view.state);
    equal(image(), {type: 'image', src: '/new', alt: '图😀', title: '新题'}, '图片引用实际属性没有重绑定');
    // ProseMirror also renders separator img elements without authored src.
    equal(view.dom.querySelector('[data-block-id="20"] img[src]')?.getAttribute('src'), '/new', '图片DOM仍为旧来源');
    equal(new EditorSource(ctx, pair.markdown_content).blocks[1]!.markdown, '![图😀][a]\r\n', '图片引用原文被改写');
    equal(ledger.capture(view.state, editTime), pair, '图片重绑定后输出不稳定'); record(pair);
    if (!undo(view.state, tr => view.dispatch(tr))) throw new Error('图片引用撤销失败');
    const restored = ledger.prepare(view.state, editTime); view.updateState(restored.state); ledger.accept(restored, view.state);
    equal(image(), {type: 'image', src: '/old', alt: '图😀', title: '旧题'}, '图片引用撤销属性');
    equal(view.dom.querySelector('[data-block-id="20"] img[src]')?.getAttribute('src'), '/old', '图片撤销DOM');
    equal(restored.pair.markdown_content, imageSource, '图片撤销原文'); record(restored.pair);
    if (!redo(view.state, tr => view.dispatch(tr))) throw new Error('图片引用重做失败');
    const replayed = ledger.prepare(view.state, editTime); view.updateState(replayed.state); ledger.accept(replayed, view.state);
    equal(image(), {type: 'image', src: '/new', alt: '图😀', title: '新题'}, '图片引用重做属性');
    equal(view.dom.querySelector('[data-block-id="20"] img[src]')?.getAttribute('src'), '/new', '图片重做DOM'); record(replayed.pair);
  });
  checks.push('context-image-reference-src-title-alt-and-dom');

  ledger = await setup('[a]: /old\r\n\r\n[标签][a]\r\n', [10,20], 30);
  get().editor.action(ctx => {
    const view = ctx.get(editorViewCtx), before = view.state;
    const first = ledger.prepare(before, editTime), second = ledger.prepare(before, editTime);
    const other = new EditedSnapshotLedger(ctx, fixtureDraft(ctx, '[a]: /old\r\n\r\n[标签][a]\r\n', [10,20], 30), before);
    for (const action of [() => ledger.accept({...first}, first.state), () => other.accept(first, first.state),
      () => ledger.accept(first, before.apply(before.tr))]) {
      try { action(); throw new Error('伪造/跨账本/异视图预检被接受'); }
      catch (error) { if (!(error instanceof EditorSourceInvalid)) throw error; }
    }
    if (view.state !== before) throw new Error('拒绝预检修改原视图');
    view.updateState(first.state); record(ledger.accept(first, view.state));
    for (const prepared of [first, second]) {
      try { ledger.accept(prepared, prepared.state); throw new Error('重复或过期预检被接受'); }
      catch (error) { if (!(error instanceof EditorSourceInvalid)) throw error; }
    }
  });
  checks.push('context-stage-proof-owner-state-and-generation');

  ledger = await setup('甲\r\n\r\n乙\r\n', [10,20], 30);
  get().editor.action(ctx => {
    const view = ctx.get(editorViewCtx);
    view.dispatch(view.state.tr.insert(0, view.state.schema.nodes.paragraph!.create()));
    view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc, 1)));
    const before = view.state, prepared = ledger.prepare(before, editTime);
    equal(prepared.state.doc.childCount, 3, '上下文重解析删除空caret/gap');
    equal(prepared.state.selection.from, 1, '上下文重解析移走空caret');
    equal(topBlockIds(prepared.state.doc), [null,10,20], '上下文重解析给gap分配身份');
    if (view.state !== before) throw new Error('空gap预检改变视图');
    view.updateState(prepared.state); const pair = ledger.accept(prepared, view.state);
    equal(pair.markdown_content, '甲\r\n\r\n乙\r\n', '空gap被伪造为业务源码'); record(pair);
  });
  checks.push('context-preserves-unidentified-empty-caret-and-selection');

  ledger = await setup(withFooter, [10,20], 30);
  get().editor.action(ctx => {
    const view = ctx.get(editorViewCtx);
    view.dispatch(view.state.tr.insertText('<script>\r\n未闭合\r\n', 1, 1 + view.state.doc.child(0).content.size));
    const before = view.state, normalized = normalizeRawSourceBlock(ctx, before, 0);
    try { ledger.prepare(normalized.state, editTime, normalized); throw new Error('预检接受吞块源码'); }
    catch (error) { if (!(error instanceof EditorSourceInvalid)) throw error; }
    if (view.state !== before) throw new Error('失败预检丢失当前输入');
    if (!undo(view.state, tr => view.dispatch(tr))) throw new Error('预检失败后的撤销失败');
    const prepared = ledger.prepare(view.state, editTime);
    view.updateState(prepared.state); const pair = ledger.accept(prepared, view.state);
    equal(pair.markdown_content, withFooter, '失败预检污染账本/历史'); record(pair);
  });
  checks.push('context-failed-stage-preserves-live-ledger-and-pending-input');

  const sourceSplices = [
    {name: 'quote-reference', markdown: '> [a]: /old\r\n>\r\n> [标签][a]\r\n', hrefs: ['/new']},
    {name: 'list-reference', markdown: '- [a]: /old\r\n\r\n  [标签][a]\r\n', hrefs: ['/new']},
    {name: 'quote-list-reference', markdown: '> - [a]: /old\r\n>\r\n>   [标签][a]\r\n', hrefs: ['/new']},
    {name: 'quote-raw-rich-siblings', markdown: '> [a]: /old\r\n> [stay]: /kept\r\n>\r\n> **保留** [标签][a]\r\n', hrefs: ['/new']},
    {name: 'ordered-multiline-definition', markdown: '2. [a]:\r\n     /old\r\n     "旧题"\r\n\r\n   [标签][a]\r\n', hrefs: ['/new']},
    {name: 'quote-CR-definition', markdown: '> [a]: /old\r>\r> [标签][a]\r', hrefs: ['/new']},
    {name: 'tab-list-definition', markdown: '-\t[a]: /old\r\n\r\n\t[标签][a]\r\n', hrefs: ['/new']},
    {name: 'multiple-raw-ranges', markdown: '> [a]: /old\r\n> [b]: /old2\r\n>\r\n> [甲][a] **保留** [乙][b]\r\n', hrefs: ['/new','/new2']},
  ];
  for (const scenario of sourceSplices) {
    ledger = await setup(scenario.markdown, [10], 20);
    get().editor.action(ctx => {
      const view = ctx.get(editorViewCtx);
      const edits: {position: number; size: number; value: string}[] = [];
      view.state.doc.descendants((node, position) => {
        if (node.type.name === 'walle_raw_source' && node.textContent.includes('/old')) edits.push({position: position + 1,
          size: node.content.size, value: node.textContent.replaceAll('/old','/new').replace('旧题','新题')});
      });
      if (!edits.length) throw new Error('未找到源范围编辑目标');
      const transaction = view.state.tr;
      for (const edit of edits.toSorted((a,b) => b.position - a.position)) transaction.insertText(edit.value, edit.position, edit.position + edit.size);
      view.dispatch(transaction);
      const pending = view.state, normalized = ledger.normalizeRawBlock(pending, 0);
      const prepared = ledger.prepare(normalized.state, editTime, normalized);
      if (view.state !== pending) throw new Error('源范围预检提前修改视图');
      view.updateState(prepared.state); const pair = ledger.accept(prepared, view.state);
      const expected = scenario.markdown.replaceAll('/old','/new').replace('旧题','新题');
      equal(pair.markdown_content, expected, `原始兄弟/容器标记被改写 ${scenario.name}`);
      equal([...view.dom.querySelectorAll('a')].map(anchor => anchor.getAttribute('href')), scenario.hrefs, '容器内引用DOM未重绑定');
      equal(topBlockIds(view.state.doc), [10], '原源范围编辑改变顶层身份');
      equal(pair.block_state_json.next_block_id, 20, '原源范围编辑消耗新ID');
      equal(pair.block_state_json.blocks[0]!.created_by_type, 'SYSTEM', '原源范围编辑改变创建来源');
      equal(ledger.capture(view.state, editTime), pair, '原源范围后输出改写兄弟引用'); record(pair);
      if (!undo(view.state, tr => view.dispatch(tr))) throw new Error('原源范围撤销失败');
      const restored = ledger.prepare(view.state, editTime); view.updateState(restored.state); ledger.accept(restored, view.state);
      equal(restored.pair.markdown_content, scenario.markdown, '原源范围撤销没有完整恢复'); record(restored.pair);
      if (!redo(view.state, tr => view.dispatch(tr))) throw new Error('原源范围重做失败');
      const replayed = ledger.prepare(view.state, editTime); view.updateState(replayed.state); ledger.accept(replayed, view.state);
      equal(replayed.pair.markdown_content, expected, '原源范围重做不精确'); record(replayed.pair);
    });
    checks.push(`source-splice-${scenario.name}`);
  }

  const conversionSource = '> <div>起</div>\r\n>\r\n> [a]: /keep\r\n>\r\n> **兄弟** [标签][a]\r\n';
  ledger = await setup(conversionSource, [10], 20);
  get().editor.action(ctx => {
    const view = ctx.get(editorViewCtx), raw = view.state.doc.firstChild!.firstChild!;
    view.dispatch(view.state.tr.insertText('甲😀\r\n\r\n# 新章\r\n', 2, 2 + raw.content.size));
    const normalized = ledger.normalizeRawBlock(view.state, 0), prepared = ledger.prepare(normalized.state, editTime, normalized);
    view.updateState(prepared.state); const pair = ledger.accept(prepared, view.state);
    const expected = conversionSource.replace('> <div>起</div>\r\n', '> 甲😀\r\n> \r\n> # 新章\r\n');
    equal(pair.markdown_content, expected, '原始节点转换重写兄弟引用或空白');
    equal(view.state.doc.firstChild!.child(0).type.name, 'paragraph', '源范围转换没有真实段落');
    equal(view.state.doc.firstChild!.child(1).type.name, 'heading', '源范围转换没有真实标题');
    equal(view.dom.querySelector('a')?.getAttribute('href'), '/keep', '源范围转换丢失兄弟引用'); record(pair);
    if (!undo(view.state, tr => view.dispatch(tr))) throw new Error('源范围类型转换撤销失败');
    const restored = ledger.prepare(view.state, editTime); view.updateState(restored.state); ledger.accept(restored, view.state);
    equal(restored.pair.markdown_content, conversionSource, '源范围类型转换撤销原文'); record(restored.pair);
    if (!redo(view.state, tr => view.dispatch(tr))) throw new Error('源范围类型转换重做失败');
    const replayed = ledger.prepare(view.state, editTime); view.updateState(replayed.state); ledger.accept(replayed, view.state);
    equal(replayed.pair.markdown_content, expected, '源范围类型转换重做原文'); record(replayed.pair);
  });
  checks.push('source-splice-type-conversion-keeps-container-reference-syntax');

  ledger = await setup('  <div>起</div>\r\n', [10], 20);
  get().editor.action(ctx => {
    const view = ctx.get(editorViewCtx);
    view.dispatch(view.state.tr.insertText('  <div>新</div>\r\n', 1, 1 + view.state.doc.firstChild!.content.size));
    const normalized = ledger.normalizeRawBlock(view.state, 0), prepared = ledger.prepare(normalized.state, editTime, normalized);
    view.updateState(prepared.state); const pair = ledger.accept(prepared, view.state);
    equal(pair.markdown_content, '  <div>新</div>\r\n', '顶层原始缩进重复附加'); record(pair);
  });
  checks.push('source-splice-top-raw-does-not-duplicate-authored-indent');

  const guardedSource = '> [a]: /old\r\n>\r\n> **原** [标签][a]\r\n';
  ledger = await setup(guardedSource, [10], 20);
  get().editor.action(ctx => {
    const view = ctx.get(editorViewCtx), positions: {position: number; size: number; value: string}[] = [];
    view.state.doc.descendants((node, position) => {
      if (node.type.name === 'walle_raw_source') positions.push({position: position + 1, size: node.content.size, value: node.textContent.replace('/old','/new')});
      if (node.isText && node.text === '原') positions.push({position, size: node.nodeSize, value: '新原'});
    });
    const transaction = view.state.tr;
    for (const edit of positions.toSorted((a,b) => b.position - a.position)) transaction.insertText(edit.value, edit.position, edit.position + edit.size);
    view.dispatch(transaction);
    const before = view.state;
    try { ledger.normalizeRawBlock(before, 0); throw new Error('原始源范围吞掉并发富文本编辑'); }
    catch (error) { if (!(error instanceof EditorSourceInvalid)) throw error; }
    if (view.state !== before || !view.state.doc.textContent.includes('新原')) throw new Error('源范围拒绝丢失当前输入');
    if (!undo(view.state, tr => view.dispatch(tr))) throw new Error('源范围拒绝后的撤销失败');
    const prepared = ledger.prepare(view.state, editTime); view.updateState(prepared.state);
    const pair = ledger.accept(prepared, view.state);
    equal(pair.markdown_content, guardedSource, '源范围失败污染账本'); record(pair);
  });
  checks.push('source-splice-refuses-unmapped-rich-change-atomically');

  function globalRewrite(value: string, topIndex = 0) {
    return get().editor.action(ctx => {
      const view = ctx.get(editorViewCtx);
      let position = 1;
      for (let child = 0; child < topIndex; child++) position += view.state.doc.child(child).nodeSize;
      const node = view.state.doc.child(topIndex);
      view.dispatch(view.state.tr.insertText(value, position, position + node.content.size));
      const before = view.state, prepared = ledger!.prepareRawDocument(before, topIndex, editTime);
      if (view.state !== before) throw new Error('完整源预检提前改变视图');
      view.updateState(prepared.state); return ledger!.accept(prepared, view.state);
    });
  }
  function historyPair(direction: 'undo' | 'redo') {
    return get().editor.action(ctx => {
      const view = ctx.get(editorViewCtx), command = direction === 'undo' ? undo : redo;
      if (!command(view.state, tr => view.dispatch(tr))) throw new Error('完整源实际历史没有执行');
      const prepared = ledger!.prepare(view.state, editTime); view.updateState(prepared.state);
      return ledger!.accept(prepared, view.state);
    });
  }

  const globalInitial = '<div>起</div>\r\n\r\n# 后继\r\n\r\n**尾**😀\r\n';
  ledger = await setup(globalInitial, [10,20,21], 30);
  const mergedSource = '<script>\r\n未闭合\r\n\r\n# 后继\r\n\r\n**尾**😀\r\n';
  const merged = globalRewrite('<script>\r\n未闭合\r\n');
  equal(merged.markdown_content, mergedSource, '完整源未闭合HTML丢失后继源码');
  equal(merged.block_state_json.blocks.map(block => [block.block_id,block.block_type]), [[10,'html_block']], '完整源合并没有保留文档顺序首ID');
  equal(merged.block_state_json.next_block_id, 30, '合并退回/分配高水位'); record(merged);
  const restoredMerge = historyPair('undo');
  equal(restoredMerge.markdown_content, globalInitial, '跨块合并撤销没有恢复完整源');
  equal(restoredMerge.block_state_json.blocks.map(block => block.block_id), [10,20,21], '实际历史未恢复删除身份'); record(restoredMerge);
  const replayedMerge = historyPair('redo'); equal(replayedMerge.markdown_content, mergedSource, '合并重做原文'); record(replayedMerge);
  checks.push('global-unclosed-html-merges-with-source-ownership-and-history');

  get().editor.action(ctx => { const view = ctx.get(editorViewCtx); view.dispatch(closeHistory(view.state.tr)); });
  const closedSource = '<script>\r\n未闭合\r\n</script>\r\n\r\n# 后继\r\n\r\n**尾**😀\r\n';
  const split = globalRewrite(closedSource);
  equal(split.markdown_content, closedSource, '关闭HTML后完整源改变');
  equal(split.block_state_json.blocks.map(block => block.block_id), [10,30,31], '重新分块错误猜回已删除旧ID');
  equal(split.block_state_json.next_block_id, 32, '重新分块高水位');
  equal(split.block_state_json.blocks.map(block => block.created_by_type), ['SYSTEM','USER','USER'], '重新分块创建事实');
  equal(split.block_state_json.blocks[1]!.created_source_id, 90, '重新分块来源不是实际输入草稿'); record(split);
  const restoredSplit = historyPair('undo');
  equal(restoredSplit.markdown_content, mergedSource, '分块撤销原源');
  equal(restoredSplit.block_state_json.blocks.map(block => block.block_id), [10], '分块撤销身份');
  equal(restoredSplit.block_state_json.next_block_id, 32, '分块撤销回退高水位'); record(restoredSplit);
  const replayedSplit = historyPair('redo');
  equal(replayedSplit.markdown_content, closedSource, '分块重做原源');
  equal(replayedSplit.block_state_json.blocks.map(block => block.block_id), [10,30,31], '分块重做重分配ID'); record(replayedSplit);
  checks.push('global-close-html-splits-new-identities-with-monotonic-history');

  ledger = await setup('<div>起</div>\n\n尾\n', [10,20], 30);
  const joinedParagraph = globalRewrite('甲');
  equal(joinedParagraph.markdown_content, '甲\n尾\n', '无尾行原始编辑重组源码');
  equal(joinedParagraph.block_state_json.blocks.map(block => [block.block_id,block.block_type]), [[10,'paragraph']], '跨界段落合并身份'); record(joinedParagraph);
  const restoredParagraph = historyPair('undo'); equal(restoredParagraph.markdown_content, '<div>起</div>\n\n尾\n', '跨界段落撤销源'); record(restoredParagraph);
  const replayedParagraph = historyPair('redo'); equal(replayedParagraph.markdown_content, '甲\n尾\n', '跨界段落重做源'); record(replayedParagraph);
  checks.push('global-source-without-ending-merges-real-paragraphs');

  const codeInitial = '# 前\r\n\r\n<div>起</div>\r\n\r\n尾😀\r\n';
  ledger = await setup(codeInitial, [5,10,20], 30);
  const unclosedCode = globalRewrite('```python\r\n未闭合\r\n', 1);
  equal(unclosedCode.markdown_content, '# 前\r\n\r\n```python\r\n未闭合\r\n\r\n尾😀\r\n', '非首原始节点完整源');
  equal(unclosedCode.block_state_json.blocks.map(block => [block.block_id,block.block_type]), [[5,'heading'],[10,'code_block']], '未闭合代码身份/类型');
  get().editor.action(ctx => {
    equal(ctx.get(editorViewCtx).state.doc.child(1).type.name, 'code_block', '完整源未建立真实代码节点');
    equal(new EditorSource(ctx, unclosedCode.markdown_content).blocks[1]!.plain_text, '未闭合\n\n尾😀\n', '完整源代码投影丢失后继');
  }); record(unclosedCode);
  const restoredCode = historyPair('undo'); equal(restoredCode.markdown_content, codeInitial, '完整源代码撤销'); record(restoredCode);
  const replayedCode = historyPair('redo'); equal(replayedCode.markdown_content, unclosedCode.markdown_content, '完整源代码重做'); record(replayedCode);
  checks.push('global-nonfirst-code-preserves-prefix-and-absorbed-source');

  ledger = await setup('\r\n<div>起</div>\r\n\r\n# 后继\r\n', [10,20], 30);
  const deletedRaw = globalRewrite('\r\n \r\n');
  equal(deletedRaw.markdown_content, '\r\n\r\n \r\n\r\n# 后继\r\n', '原始节点删除空白顺序');
  equal(deletedRaw.block_state_json.blocks.map(block => block.block_id), [20], '原始空白错误抢占后继ID'); record(deletedRaw);
  const restoredDeleted = historyPair('undo'); equal(restoredDeleted.block_state_json.blocks.map(block => block.block_id), [10,20], '删除源撤销身份'); record(restoredDeleted);
  const replayedDeleted = historyPair('redo'); equal(replayedDeleted.markdown_content, deletedRaw.markdown_content, '删除源重做空白'); record(replayedDeleted);
  checks.push('global-whitespace-deletion-keeps-successor-identity');

  ledger = await setup('<div>起</div>\r\n', [10], 20);
  const emptyGlobal = globalRewrite('\r\n \r\n');
  equal(emptyGlobal.markdown_content, '\r\n \r\n', '完整源空文档丢失空白');
  equal(emptyGlobal.block_state_json.blocks, [], '完整源空文档伪造业务块');
  get().editor.action(ctx => equal(topBlockIds(ctx.get(editorViewCtx).state.doc), [null], '完整源空caret分配ID')); record(emptyGlobal);
  const restoredEmpty = historyPair('undo'); equal(restoredEmpty.markdown_content, '<div>起</div>\r\n', '完整源空文档撤销'); record(restoredEmpty);
  const replayedEmpty = historyPair('redo'); equal(replayedEmpty.markdown_content, emptyGlobal.markdown_content, '完整源空文档重做'); record(replayedEmpty);
  checks.push('global-empty-source-has-real-caret-without-business-block');

  ledger = await setup('<div>起</div>\r\n', [10], 20);
  const clearedGlobal = globalRewrite('');
  equal(clearedGlobal.markdown_content, '', '清空顶层原始文本错误保留已删除尾行');
  equal(clearedGlobal.block_state_json.blocks, [], '完全清空原始源仍有业务块'); record(clearedGlobal);
  const restoredCleared = historyPair('undo'); equal(restoredCleared.markdown_content, '<div>起</div>\r\n', '完全清空原始源撤销'); record(restoredCleared);
  const replayedCleared = historyPair('redo'); equal(replayedCleared.markdown_content, '', '完全清空原始源重做'); record(replayedCleared);
  checks.push('global-cleared-top-raw-removes-its-source-ending');

  ledger = await setup('<div>起</div>\n', [10], Number.MAX_SAFE_INTEGER - 1);
  get().editor.action(ctx => {
    const view = ctx.get(editorViewCtx);
    view.dispatch(view.state.tr.insertText('一\n\n二\n\n三\n', 1, 1 + view.state.doc.firstChild!.content.size));
    const before = view.state, oldIdentity = identityState(before);
    try { ledger.prepareRawDocument(before, 0, editTime); throw new Error('完整源容量耗尽仍分配'); }
    catch (error) { if (!(error instanceof IdentityInvalid) || error.code !== 'CAPACITY_EXCEEDED') throw error; }
    if (view.state !== before) throw new Error('完整源容量失败改变视图');
    equal(identityState(view.state).next_block_id, oldIdentity.next_block_id, '完整源容量失败改变高水位');
    equal([...identityState(view.state).known_ids], [...oldIdentity.known_ids], '完整源容量失败改变已知身份');
    if (!undo(view.state, tr => view.dispatch(tr))) throw new Error('完整源容量失败撤销');
    const prepared = ledger.prepare(view.state, editTime); view.updateState(prepared.state);
    record(ledger.accept(prepared, view.state));
  });
  checks.push('global-capacity-failure-does-not-publish-source-or-identity');
  return {scope: 'Explicit raw reparse and complete-source reference rebind, actual PM/history/DOM and atomic local pair; no complete component or HTTP/DB save', checks, outputs};
}
