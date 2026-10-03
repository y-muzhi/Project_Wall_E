import type { Node } from '@milkdown/kit/prose/model';
import type { EditorState } from '@milkdown/kit/prose/state';
import { NodeSelection, TextSelection } from '@milkdown/kit/prose/state';
import type { EditorView } from '@milkdown/kit/prose/view';
import { blockProjection, inlineProjection } from './editor-source.ts';
import { identityState } from './identity.ts';
import { SelectionInvalid, selectionFromProjectedText, utf16RangeForSelection, type SelectionEvent } from './selection.ts';

export type DocumentSelectionContext = Readonly<{document_id: number; content_version: number}>;
interface Segment { from: number; to: number; start: number; end: number; linear: boolean; }
function invalid(): never { throw new SelectionInvalid('SELECTION_INVALID'); }
function context(value: DocumentSelectionContext): void {
  if (!value || typeof value !== 'object' || Object.keys(value).sort().join(',') !== 'content_version,document_id' ||
      !Number.isSafeInteger(value.document_id) || value.document_id < 1 ||
      !Number.isSafeInteger(value.content_version) || value.content_version < 1) invalid();
}

// Store text intervals and atom boundaries, not a million-entry position map.
// Structural LF/TAB and code tails belong to the shared projection. They are
// included between selected text endpoints without inventing a DOM character.
function projection(node: Node, position: number): {text: string; at: (position: number) => number; positionAt: (offset: number) => number} {
  const segments: Segment[] = [], parts: string[] = [];
  let size = 0;
  const append = (value: string) => { parts.push(value); size += value.length; };
  function visit(current: Node, from: number): void {
    if (current.isText || current.isInline && current.isLeaf) {
      const text = inlineProjection(current), start = size;
      append(text);
      segments.push({from, to: from + current.nodeSize, start, end: size, linear: current.isText});
      return;
    }
    const name = current.type.name;
    if (name === 'hr') return;
    const textblock = ['paragraph', 'heading', 'walle_raw_source', 'code_block'].includes(name);
    if (!textblock && !['table', 'table_row', 'table_header_row', 'table_cell', 'table_header',
      'blockquote', 'bullet_list', 'ordered_list', 'list_item'].includes(name)) invalid();
    const delimiter = textblock ? '' : name === 'table_row' || name === 'table_header_row' ? '\t' : '\n';
    current.forEach((child, offset, index) => {
      if (index) append(delimiter);
      visit(child, from + 1 + offset);
    });
    if (name === 'code_block') append(String(current.attrs.walle_code_tail));
  }
  visit(node, position);
  const text = parts.join('');
  if (text !== blockProjection(node)) invalid();
  return {text, at(target) {
    if (target === position) return 0;
    if (target === position + node.nodeSize) return text.length;
    const matches = new Set<number>();
    for (const segment of segments) {
      if (target < segment.from || target > segment.to) continue;
      if (segment.linear) matches.add(segment.start + target - segment.from);
      else if (target === segment.from) matches.add(segment.start);
      else if (target === segment.to) matches.add(segment.end);
    }
    if (matches.size !== 1) invalid();
    return matches.values().next().value!;
  }, positionAt(target) {
    const matches = new Set<number>();
    for (const segment of segments) {
      if (target < segment.start || target > segment.end) continue;
      if (segment.linear) matches.add(segment.from + target - segment.start);
      else {
        if (target === segment.start) matches.add(segment.from);
        if (target === segment.end) matches.add(segment.to);
      }
    }
    if (!matches.size && target === 0) return position;
    if (!matches.size && target === text.length) return position + node.nodeSize;
    if (matches.size !== 1) invalid(); // Never guess an interior atom/virtual endpoint.
    return matches.values().next().value!;
  }};
}

export function selectionFromEditorState(state: EditorState, current: DocumentSelectionContext): SelectionEvent | null {
  context(current);
  const selection = state.selection;
  if (selection.$from.doc !== state.doc || selection.$to.doc !== state.doc) invalid();
  if (selection.empty) return null;
  let result: SelectionEvent | undefined;
  state.doc.forEach((node, position) => {
    if (selection.from < position || selection.to > position + node.nodeSize) return;
    const id: unknown = node.attrs.walle_block_id;
    if (typeof id !== 'number' || !Number.isSafeInteger(id) || id < 1 || !identityState(state).known_ids.has(id)) invalid();
    if (result) invalid();
    const map = projection(node, position);
    result = selectionFromProjectedText({...current, block_id: id}, map.text, map.at(selection.from), map.at(selection.to));
  });
  if (!result) invalid(); // No cross-Block search or snapping into another node.
  return result;
}

export interface EditorSelectionRange {
  readonly from: number;
  readonly to: number;
  readonly node_selection: boolean;
}

export function editorRangeForSelection(state: EditorState, current: DocumentSelectionContext, event: SelectionEvent): EditorSelectionRange {
  context(current);
  if (!event || typeof event !== 'object' || !Number.isSafeInteger(event.block_id) || event.block_id < 1) invalid();
  let result: EditorSelectionRange | undefined;
  state.doc.forEach((node, position) => {
    if (node.attrs.walle_block_id !== event.block_id) return;
    if (result || !identityState(state).known_ids.has(event.block_id)) invalid();
    const map = projection(node, position);
    const range = utf16RangeForSelection({...current, block_id: event.block_id}, map.text, event);
    const from = map.positionAt(range.start), to = map.positionAt(range.end);
    if (from >= to || map.at(from) !== range.start || map.at(to) !== range.end) invalid();
    const textEndpoints = state.doc.resolve(from).parent.inlineContent && state.doc.resolve(to).parent.inlineContent;
    if (!textEndpoints && (range.start !== 0 || range.end !== map.text.length)) invalid();
    result = Object.freeze(textEndpoints ? {from, to, node_selection: false} :
      {from: position, to: position + node.nodeSize, node_selection: true});
  });
  if (!result) throw new SelectionInvalid('STALE_SELECTION');
  return result;
}

// Validation completes before changing selection, focus or scroll. A whole
// block whose projection contains a synthetic code tail uses NodeSelection;
// partial synthetic/atom interiors have no exact text endpoint and fail.
export function locateEditorSelection(view: EditorView, current: DocumentSelectionContext, event: SelectionEvent): void {
  const range = editorRangeForSelection(view.state, current, event);
  const selection = range.node_selection ? NodeSelection.create(view.state.doc, range.from) :
    TextSelection.create(view.state.doc, range.from, range.to);
  if (selection.from !== range.from || selection.to !== range.to) invalid();
  view.dispatch(view.state.tr.setSelection(selection).scrollIntoView());
  view.focus();
}

interface DomPoint { node: globalThis.Node; offset: number; }
function boundary(point: DomPoint, root: HTMLElement): DomPoint {
  let {node, offset} = point;
  if (node !== root && !root.contains(node)) invalid();
  const length = node.nodeType === 3 ? node.textContent!.length : node.childNodes.length;
  if (!Number.isSafeInteger(offset) || offset < 0 || offset > length) invalid();
  while (node !== root) {
    const limit = node.nodeType === 3 ? node.textContent!.length : node.childNodes.length;
    if (offset !== 0 && offset !== limit) break;
    const parent = node.parentNode;
    if (!parent) invalid();
    const index = Array.prototype.indexOf.call(parent.childNodes, node) as number;
    offset = index + (offset === 0 ? 0 : 1);
    node = parent;
  }
  return {node, offset};
}

function domPosition(view: EditorView, node: globalThis.Node, offset: number): number {
  const expected = boundary({node, offset}, view.dom);
  const positions = new Set<number>();
  for (const bias of [-1, 1]) {
    const position = view.posAtDOM(node, offset, bias);
    for (const side of [-1, 1]) {
      const actual = boundary(view.domAtPos(position, side), view.dom);
      if (actual.node === expected.node && actual.offset === expected.offset) positions.add(position);
    }
  }
  if (positions.size !== 1) invalid(); // Partial HTML atom text has no exact PM endpoint.
  return positions.values().next().value!;
}

// Call after the view has applied the native selection transaction. DOM
// endpoints must round-trip exactly through the real view, and must describe
// that same EditorState. Partial atom selections and stale DOM are rejected.
export function selectionFromEditorView(view: EditorView, current: DocumentSelectionContext): SelectionEvent | null {
  context(current);
  const selection = view.dom.ownerDocument.getSelection();
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return null;
  if (selection.rangeCount !== 1 || !selection.anchorNode || !selection.focusNode) invalid();
  const anchor = domPosition(view, selection.anchorNode, selection.anchorOffset);
  const focus = domPosition(view, selection.focusNode, selection.focusOffset);
  if (Math.min(anchor, focus) !== view.state.selection.from || Math.max(anchor, focus) !== view.state.selection.to) {
    throw new SelectionInvalid('STALE_SELECTION');
  }
  return selectionFromEditorState(view.state, current);
}
