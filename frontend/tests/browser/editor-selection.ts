import type { Crepe } from '@milkdown/crepe';
import { editorViewCtx } from '@milkdown/kit/core';
import { NodeSelection, TextSelection } from '@milkdown/kit/prose/state';
import type { EditorView } from '@milkdown/kit/prose/view';
import fixtures from '../../../shared/fixtures/editor-selection-v1.json';
import { editorRangeForSelection, locateEditorSelection, selectionFromEditorState, selectionFromEditorView } from '../../src/documents/editor-selection.ts';
import { selectionFromProjectedText } from '../../src/documents/selection.ts';
import { SelectionInvalid } from '../../src/documents/selection.ts';
import { EditorSource } from '../../src/documents/editor-source.ts';
import { EditedSnapshotLedger } from '../../src/documents/edited-snapshot.ts';
import { fixtureDraft, editTime } from './edited-snapshot.ts';

export const selectionContext = {document_id: 90, content_version: 3};
function endpoint(view: EditorView, point: {text: string; offset: number}): number {
  const positions: number[] = [];
  view.state.doc.descendants((node, position) => {
    if (node.isText && node.text!.includes(point.text)) positions.push(position + node.text!.indexOf(point.text) + point.offset);
  });
  if (positions.length !== 1) throw new Error('测试端点未唯一找到真实文本节点');
  return positions[0]!;
}
function select(view: EditorView, anchor: number, focus: number): void {
  view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc, anchor, focus)));
  const start = view.domAtPos(anchor), end = view.domAtPos(focus);
  view.dom.ownerDocument.getSelection()!.setBaseAndExtent(start.node, start.offset, end.node, end.offset);
}
function rejected(action: () => unknown, code = 'SELECTION_INVALID'): void {
  try { action(); } catch (error) {
    if (error instanceof SelectionInvalid && error.code === code) return;
    throw error;
  }
  throw new Error(`应拒绝无法精确映射的选区: ${code}`);
}

export async function verifyEditorSelection(load: (markdown: string, ids: readonly number[], next: number) => Promise<unknown>, get: () => Crepe) {
  const records = [], rejectedCases: string[] = [];
  for (const entry of fixtures.cases) {
    await load(entry.markdown, [10], 20);
    records.push(get().editor.action(ctx => {
      const view = ctx.get(editorViewCtx), source = new EditorSource(ctx, entry.markdown);
      if (source.blocks[0]!.plain_text !== entry.plain_text) throw new Error('选区黄金投影不一致');
      const anchor = endpoint(view, entry.anchor), focus = endpoint(view, entry.focus);
      select(view, anchor, focus);
      const actual = selectionFromEditorView(view, selectionContext);
      if (JSON.stringify(actual) !== JSON.stringify(entry.event)) throw new Error(`真实选区不一致: ${entry.name}: ${JSON.stringify(actual)}`);
      const restored = editorRangeForSelection(view.state, selectionContext, actual!);
      if (restored.from !== Math.min(anchor, focus) || restored.to !== Math.max(anchor, focus) || restored.node_selection) throw new Error('选区反向映射改变实际端点');
      locateEditorSelection(view, selectionContext, actual!);
      if (JSON.stringify(selectionFromEditorView(view, selectionContext)) !== JSON.stringify(entry.event)) throw new Error('实际视图定位改变纯文本范围');
      select(view, focus, anchor);
      if (JSON.stringify(selectionFromEditorView(view, selectionContext)) !== JSON.stringify(entry.event)) throw new Error('反向选区被改变');
      const pair = new EditedSnapshotLedger(ctx, fixtureDraft(ctx, entry.markdown, [10], 20), view.state).capture(view.state, editTime);
      return {name: entry.name, event: actual, expected: entry.event, pair, native_round_trip: true, inverse_equal: true,
        projection: source.blocks.map(block => ({block_type: block.block_type, plain_text: block.plain_text, section_path: block.section_path}))};
    }));
  }
  await load('甲\n\n乙\n', [10,20], 30);
  get().editor.action(ctx => {
    const view = ctx.get(editorViewCtx);
    select(view, endpoint(view, {text: '甲', offset: 0}), endpoint(view, {text: '乙', offset: 1}));
    rejected(() => selectionFromEditorView(view, selectionContext));
    rejectedCases.push('cross-block');
  });
  await load('甲😀乙<em>尾\n', [10], 20);
  get().editor.action(ctx => {
    const view = ctx.get(editorViewCtx), first = endpoint(view, {text: '甲', offset: 0});
    select(view, first + 1, first + 2);
    rejected(() => selectionFromEditorView(view, selectionContext));
    rejectedCases.push('surrogate-interior');
    select(view, first, first + 1);
    const native = view.dom.ownerDocument.getSelection()!;
    const html = view.dom.querySelector('[data-type="html"]')!.firstChild!;
    native.setBaseAndExtent(html, 1, html, 3);
    rejected(() => selectionFromEditorView(view, selectionContext));
    rejectedCases.push('partial-html-atom');
    const outer = document.querySelector('#status')!.firstChild!;
    native.setBaseAndExtent(outer, 0, outer, 1);
    rejected(() => selectionFromEditorView(view, selectionContext));
    rejectedCases.push('outside-editor');
    select(view, first, first + 1);
    view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc, first + 1, first + 3)));
    const start = view.domAtPos(first), end = view.domAtPos(first + 1);
    native.setBaseAndExtent(start.node, start.offset, end.node, end.offset);
    rejected(() => selectionFromEditorView(view, selectionContext), 'STALE_SELECTION');
    rejectedCases.push('stale-dom-state');
    select(view, first, first);
    if (selectionFromEditorState(view.state, selectionContext) !== null || selectionFromEditorView(view, selectionContext) !== null) throw new Error('空选区变为正文选区');
    rejectedCases.push('collapsed-no-event');
    select(view, first, first + 1);
    const original = selectionFromEditorView(view, selectionContext)!;
    const before = view.state;
    for (const [name, event, code] of [
      ['old-document', {...original, document_id: 91}, 'STALE_SELECTION'],
      ['old-version', {...original, content_version: 2}, 'STALE_SELECTION'],
      ['changed-text', {...original, selected_text: '错'}, 'STALE_SELECTION'],
      ['missing-block', {...original, block_id: 11}, 'STALE_SELECTION'],
    ] as const) {
      rejected(() => locateEditorSelection(view, selectionContext, event), code);
      if (view.state !== before) throw new Error('拒绝定位仍改变编辑器状态');
      rejectedCases.push(name);
    }
  });
  await load('前![图😀](x.png)后\n', [10], 20);
  get().editor.action(ctx => {
    const view = ctx.get(editorViewCtx), before = view.state;
    const partial = selectionFromProjectedText({...selectionContext, block_id: 10}, '前图😀后', 2, 4);
    rejected(() => locateEditorSelection(view, selectionContext, partial));
    if (view.state !== before) throw new Error('原子内部定位改变状态');
    rejectedCases.push('inverse-partial-image-alt');
  });
  const codeSource = '```\r\n甲\r\n```\r\n';
  await load(codeSource, [10], 20);
  records.push(get().editor.action(ctx => {
    const view = ctx.get(editorViewCtx), initialDoc = view.state.doc;
    const event = selectionFromProjectedText({...selectionContext, block_id: 10}, '甲\n', 0, 2);
    const range = editorRangeForSelection(view.state, selectionContext, event);
    if (!range.node_selection || range.from !== 0 || range.to !== view.state.doc.content.size) throw new Error('完整代码尾行未对应真实区块');
    locateEditorSelection(view, selectionContext, event);
    if (!(view.state.selection instanceof NodeSelection) || !view.state.doc.eq(initialDoc) ||
        JSON.stringify(selectionFromEditorState(view.state, selectionContext)) !== JSON.stringify(event) ||
        !view.dom.querySelector('.ProseMirror-selectednode')) throw new Error('代码块实际定位失败/修改正文');
    const before = view.state;
    const tail = selectionFromProjectedText({...selectionContext, block_id: 10}, '甲\n', 1, 2);
    rejected(() => locateEditorSelection(view, selectionContext, tail));
    if (view.state !== before) throw new Error('尾行部分定位改变状态');
    rejectedCases.push('inverse-partial-synthetic-tail');
    const pair = new EditedSnapshotLedger(ctx, fixtureDraft(ctx, codeSource, [10], 20), view.state).capture(view.state, editTime);
    return {name: 'whole-code-with-tail', event, expected: event, pair, native_round_trip: false, inverse_equal: true,
      projection: new EditorSource(ctx, codeSource).blocks.map(block => ({block_type: block.block_type, plain_text: block.plain_text, section_path: block.section_path}))};
  }));
  const capacity = '😀'.repeat(2001) + '\n';
  await load(capacity, [10], 20);
  records.push(get().editor.action(ctx => {
    const view = ctx.get(editorViewCtx);
    select(view, 1, 4001);
    const event = selectionFromEditorView(view, selectionContext)!;
    if (event.start_offset !== 0 || event.end_offset !== 2000 || event.selected_text !== '😀'.repeat(2000) || event.suffix_text !== '😀') throw new Error('2000码点边界错误');
    locateEditorSelection(view, selectionContext, event);
    if (JSON.stringify(selectionFromEditorView(view, selectionContext)) !== JSON.stringify(event)) throw new Error('容量边界反向定位改变范围');
    const pair = new EditedSnapshotLedger(ctx, fixtureDraft(ctx, capacity, [10], 20), view.state).capture(view.state, editTime);
    select(view, 1, 4003);
    rejected(() => selectionFromEditorView(view, selectionContext));
    rejectedCases.push('2001-not-truncated');
    return {name: 'capacity-2000', event, expected: event, pair, native_round_trip: true, inverse_equal: true,
      projection: new EditorSource(ctx, capacity).blocks.map(block => ({block_type: block.block_type, plain_text: block.plain_text, section_path: block.section_path}))};
  }));
  return {scope: 'Real PM/native DOM endpoints, inverse text/block location and shared codepoint projection; no product component or HTTP acceptance', records, rejected: rejectedCases};
}

export function keyboardSelection(crepe: Crepe) {
  return crepe.editor.action(ctx => {
    const view = ctx.get(editorViewCtx), event = selectionFromEditorView(view, selectionContext);
    locateEditorSelection(view, selectionContext, event!);
    if (JSON.stringify(selectionFromEditorView(view, selectionContext)) !== JSON.stringify(event)) throw new Error('原生键盘反向定位改变选区');
    const markdown = '甲😀乙\n';
    const pair = new EditedSnapshotLedger(ctx, fixtureDraft(ctx, markdown, [10], 20), view.state).capture(view.state, editTime);
    return {name: 'native-keyboard-emoji', event, pair, native_round_trip: true, inverse_equal: true,
      projection: new EditorSource(ctx, markdown).blocks.map(block => ({block_type: block.block_type, plain_text: block.plain_text, section_path: block.section_path}))};
  });
}
