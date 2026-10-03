/** D-004 projected-text offsets. These functions do not map DOM/ProseMirror
 * positions to the shared Markdown projection; that editor adapter is separate.
 * No trim, normalization, snapping, cross-block search or truncation occurs.
 */
const MAX_SAFE = 9_007_199_254_740_991;

export class SelectionInvalid extends Error {
  readonly code: 'SELECTION_INVALID' | 'STALE_SELECTION';
  constructor(code: 'SELECTION_INVALID' | 'STALE_SELECTION') {
    super(code === 'STALE_SELECTION' ? '选区不属于当前文档快照' : '选区位置或文本不合法');
    this.code = code;
  }
}

export type SelectionContext = Readonly<{
  document_id: number;
  content_version: number;
  block_id: number;
}>;

export type SelectionEvent = Readonly<SelectionContext & {
  start_offset: number;
  end_offset: number;
  selected_text: string;
  prefix_text: string;
  suffix_text: string;
}>;

function invalid(): never { throw new SelectionInvalid('SELECTION_INVALID'); }
function integer(value: unknown, minimum: number): asserts value is number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < minimum || value > MAX_SAFE) invalid();
}

function boundaries(text: string): number[] {
  if (typeof text !== 'string') invalid();
  const result = [0];
  let offset = 0;
  while (offset < text.length) {
    const first = text.charCodeAt(offset);
    if (first >= 0xd800 && first <= 0xdbff) {
      const second = text.charCodeAt(offset + 1);
      if (!(second >= 0xdc00 && second <= 0xdfff)) invalid();
      offset += 2;
    } else {
      if (first >= 0xdc00 && first <= 0xdfff) invalid();
      offset += 1;
    }
    result.push(offset);
  }
  return result;
}

export function utf16ToCodepoint(text: string, offset: number): number {
  integer(offset, 0);
  const index = boundaries(text).indexOf(offset);
  if (index === -1) invalid();
  return index;
}

export function codepointToUtf16(text: string, offset: number): number {
  integer(offset, 0);
  const result = boundaries(text)[offset];
  if (result === undefined) invalid();
  return result;
}

function context(value: SelectionContext): void {
  if (value === null || typeof value !== 'object' || Object.keys(value).sort().join(',') !== 'block_id,content_version,document_id') invalid();
  integer(value.document_id, 1);
  integer(value.content_version, 1);
  integer(value.block_id, 1);
}

export function selectionFromProjectedText(current: SelectionContext, text: string, startUtf16: number, endUtf16: number): SelectionEvent {
  context(current);
  integer(startUtf16, 0);
  integer(endUtf16, 0);
  const positions = boundaries(text);
  const start = positions.indexOf(startUtf16);
  const end = positions.indexOf(endUtf16);
  if (start < 0 || end <= start || end - start > 2000) invalid();
  return Object.freeze({ ...current, start_offset: start, end_offset: end, selected_text: text.slice(startUtf16, endUtf16), prefix_text: text.slice(positions[Math.max(0, start - 100)], startUtf16), suffix_text: text.slice(endUtf16, positions[Math.min(positions.length - 1, end + 100)]) });
}

export function utf16RangeForSelection(current: SelectionContext, text: string, selection: SelectionEvent): Readonly<{ start: number; end: number }> {
  context(current);
  if (selection === null || typeof selection !== 'object' || Object.keys(selection).sort().join(',') !== 'block_id,content_version,document_id,end_offset,prefix_text,selected_text,start_offset,suffix_text') invalid();
  for (const field of ['document_id', 'content_version', 'block_id'] as const) {
    integer(selection[field], 1);
    if (selection[field] !== current[field]) throw new SelectionInvalid('STALE_SELECTION');
  }
  integer(selection.start_offset, 0);
  integer(selection.end_offset, 0);
  const positions = boundaries(text);
  const start = positions[selection.start_offset];
  const end = positions[selection.end_offset];
  if (start === undefined || end === undefined || end <= start || selection.end_offset - selection.start_offset > 2000) invalid();
  const prefixSize = boundaries(selection.prefix_text).length - 1;
  const suffixSize = boundaries(selection.suffix_text).length - 1;
  if (prefixSize > 100 || suffixSize > 100 || prefixSize > selection.start_offset || suffixSize > positions.length - 1 - selection.end_offset) invalid();
  if (typeof selection.selected_text !== 'string' || text.slice(start, end) !== selection.selected_text || text.slice(positions[selection.start_offset - prefixSize], start) !== selection.prefix_text || text.slice(end, positions[selection.end_offset + suffixSize]) !== selection.suffix_text) throw new SelectionInvalid('STALE_SELECTION');
  return Object.freeze({ start, end });
}
