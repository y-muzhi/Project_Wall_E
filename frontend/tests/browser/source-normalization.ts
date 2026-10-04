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
  return {scope: 'Explicit raw reparse and complete-source reference rebind, actual PM/history/DOM and atomic local pair; no complete component or HTTP/DB save', checks, outputs};
}
