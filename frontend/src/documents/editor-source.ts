import type { Ctx } from '@milkdown/kit/ctx';
import { remarkCtx, schemaCtx } from '@milkdown/kit/core';
import { ParserState, type MarkdownNode } from '@milkdown/kit/transformer';
import type { Node } from '@milkdown/kit/prose/model';
import { utf16ToCodepoint } from './selection.ts';

export class EditorSourceInvalid extends Error {
  readonly code = 'DOCUMENT_INVALID';
}

export interface EditorSourceBlock {
  readonly block_type: string;
  readonly markdown: string;
  readonly plain_text: string;
  readonly section_path: readonly string[];
  readonly heading_level: number | null;
  readonly start_utf16: number;
  readonly end_utf16: number;
  readonly node: Node;
  readonly raw_sources: readonly RawSourceRange[];
}
interface RawSourceRange {
  readonly path: readonly number[];
  readonly start_utf16: number;
  readonly end_utf16: number;
  readonly first_prefix: string;
  readonly continuation_prefix: string;
}

function sourceLines(value: string): string[] {
  return value.match(/[^\r\n]*(?:\r\n|\r|\n|$)/g)?.filter(Boolean) ?? [];
}
function lineBody(value: string): string { return value.replace(/(?:\r\n|\r|\n)$/, ''); }
function continuationPrefix(first: string): string {
  // Keep quote markers and physical indentation; replace a first-item list
  // marker by its indentation for the following lines of that same item.
  return first.replace(/(^|[ \t>])([*+-]|[0-9]+[.)])([ \t]+)/g,
    (_match, lead: string, marker: string, space: string) => lead + ' '.repeat(marker.length) + space);
}
function sourceMarkup(node: Node): unknown {
  const attrs = {...node.attrs};
  delete attrs.walle_block_id;
  if (node.type.name === 'heading') delete attrs.id;
  return {type: node.type.name, attrs, marks: node.marks.map(mark => mark.toJSON())};
}
function rawRanges(entry: MarkdownNode, node: Node, markdown: string, blockStart: number, blockEnd: number): readonly RawSourceRange[] {
  const ast: MarkdownNode[] = [], actual: {node: Node; path: readonly number[]}[] = [];
  const scanAst = (child: MarkdownNode) => {
    if (child.type === 'walleRawSource') ast.push(child);
    else child.children?.forEach(scanAst);
  };
  const scanNodes = (child: Node, path: readonly number[]) => {
    if (child.type.name === 'walle_raw_source') actual.push({node: child, path});
    else child.forEach((descendant, _offset, index) => scanNodes(descendant, [...path, index]));
  };
  scanAst(entry); scanNodes(node, []);
  if (ast.length !== actual.length) throw new EditorSourceInvalid('原始节点位置与实际树不对应');
  return Object.freeze(ast.map((child, index) => {
    let start = child.position?.start.offset;
    const astEnd = child.position?.end.offset;
    if (start === undefined || astEnd === undefined || actual[index]!.node.textContent !== String(child.value ?? '')) {
      throw new EditorSourceInvalid('原始节点没有同源范围证明');
    }
    const contentStart = start;
    while (start > blockStart && !'\r\n'.includes(markdown[start - 1]!)) start--;
    const ending = /^(?:\r\n|\r|\n)/.exec(markdown.slice(astEnd))?.[0] ?? '';
    const end = astEnd + ending.length;
    if (start < blockStart || end > blockEnd) throw new EditorSourceInvalid('原始节点范围越出区块');
    const prefix = actual[index]!.path.length ? markdown.slice(start, contentStart) : '';
    let continuation = continuationPrefix(prefix);
    const physical = sourceLines(markdown.slice(start, end)), logical = sourceLines(actual[index]!.node.textContent);
    // A real nonblank continuation line gives the exact container prefix,
    // including tabs. Blank separator lines do not establish indentation.
    for (let line = 1; line < Math.min(physical.length, logical.length); line++) {
      const body = lineBody(logical[line]!);
      const raw = lineBody(physical[line]!);
      if (body.trim() && raw.endsWith(body)) { continuation = raw.slice(0, raw.length - body.length); break; }
    }
    return Object.freeze({path: Object.freeze([...actual[index]!.path]), start_utf16: start - blockStart,
      end_utf16: end - blockStart, first_prefix: prefix, continuation_prefix: continuation});
  }));
}

export function inlineProjection(node: Node): string {
  if (node.isText) return node.text!;
  if (node.type.name === 'hardbreak') return '\n';
  if (node.type.name === 'image') return String(node.attrs.alt);
  if (node.type.name === 'html') return String(node.attrs.value);
  let text = '';
  node.forEach(child => { text += inlineProjection(child); });
  return text;
}

export function blockProjection(node: Node): string {
  const name = node.type.name;
  if (name === 'walle_raw_source') return node.textContent;
  if (name === 'hr') return '';
  if (name === 'code_block') return node.textContent + String(node.attrs.walle_code_tail);
  if (name === 'paragraph' || name === 'heading') return inlineProjection(node);
  const parts: string[] = [];
  node.forEach(child => parts.push(blockProjection(child)));
  if (name === 'table_row' || name === 'table_header_row') return parts.join('\t');
  if (name === 'table_cell' || name === 'table_header') return parts.join('\n');
  if (['table', 'blockquote', 'bullet_list', 'ordered_list', 'list_item'].includes(name)) return parts.join('\n');
  throw new EditorSourceInvalid(`未注册编辑器节点 ${name}`);
}

function kind(node: Node): string {
  const name = node.type.name;
  if (name === 'walle_raw_source') return String(node.attrs.kind);
  if (name === 'hr') return 'thematic_break';
  if (name === 'bullet_list' || name === 'ordered_list') {
    let tasks = false;
    node.forEach(item => { if (item.attrs.checked !== null) tasks = true; });
    return tasks ? 'task_list' : name;
  }
  if (['heading', 'paragraph', 'blockquote', 'code_block', 'table'].includes(name)) return name;
  throw new EditorSourceInvalid(`未注册顶层节点 ${name}`);
}

// This layer binds the raw source to nodes only at initial parse. It does not
// infer identities from text, serialize edits or manufacture BlockState fields.
export class EditorSource {
  readonly markdown: string;
  readonly document: Node;
  readonly blocks: readonly EditorSourceBlock[];
  readonly parts: readonly string[];

  constructor(ctx: Ctx, markdown: string) {
    let length: number;
    try { length = utf16ToCodepoint(markdown, markdown.length); }
    catch { throw new EditorSourceInvalid('Markdown包含非法Unicode'); }
    if (length > 1_000_000) throw new EditorSourceInvalid('完整Markdown超过容量');
    const remark = ctx.get(remarkCtx);
    const tree = remark.runSync(remark.parse(markdown), markdown) as MarkdownNode;
    const document = new ParserState(ctx.get(schemaCtx)).next(tree).toDoc();
    const entries = tree.children ?? [];
    // An empty PM document needs one caret paragraph. It is not a business Block.
    if (entries.length > 10_000 || (entries.length && entries.length !== document.childCount)) {
      throw new EditorSourceInvalid('编辑器丢失或新增了源区块');
    }
    const blocks: EditorSourceBlock[] = [];
    const parts: string[] = [];
    const headings: {level: number; text: string}[] = [];
    let cursor = 0;
    entries.forEach((entry, index) => {
      const astStart = entry.position?.start.offset;
      const astEnd = entry.position?.end.offset;
      if (astStart === undefined || astEnd === undefined) throw new EditorSourceInvalid('源区块没有位置');
      let start = astStart;
      while (start > 0 && !'\r\n'.includes(markdown[start - 1]!)) start--;
      let end = astEnd;
      if (end < markdown.length) {
        // Markdown block spans include their final source newline; blank
        // separators remain in parts, and CRLF is never normalized.
        const ending = /^(?:\r\n|\r|\n)/.exec(markdown.slice(end))?.[0];
        if (ending) end += ending.length;
      }
      if (start < cursor || end < start) throw new EditorSourceInvalid('源区块位置重叠');
      const node = document.child(index);
      const type = kind(node);
      const plain = blockProjection(node);
      const level = type === 'heading' ? Number(node.attrs.level) : null;
      if (level !== null) {
        while (headings.length && headings.at(-1)!.level >= level) headings.pop();
        headings.push({level, text: plain});
      }
      const raw = markdown.slice(start, end);
      parts.push(markdown.slice(cursor, start), raw);
      blocks.push(Object.freeze({block_type: type, markdown: raw, plain_text: plain,
        section_path: Object.freeze(headings.map(heading => heading.text)), heading_level: level,
        start_utf16: start, end_utf16: end, node, raw_sources: rawRanges(entry, node, markdown, start, end)}));
      cursor = end;
    });
    parts.push(markdown.slice(cursor));
    this.markdown = markdown;
    this.document = document;
    this.blocks = Object.freeze(blocks);
    this.parts = Object.freeze(parts);
  }

  unchangedMarkdown(document: Node): string {
    if (!document.eq(this.document)) throw new EditorSourceInvalid('编辑后必须经过区块身份及源码适配器');
    return this.markdown;
  }

  rewriteRawBlock(index: number, before: Node, after: Node): string {
    const block = this.blocks[index];
    if (!block) throw new EditorSourceInvalid('原始节点缺少同快照源码区块');
    const changed = new Map<string, string>();
    const compare = (original: Node, pending: Node, path: readonly number[], allowRaw: boolean) => {
      if (JSON.stringify(sourceMarkup(original)) !== JSON.stringify(sourceMarkup(pending))) throw new EditorSourceInvalid('原始节点编辑同时改变了其他节点结构或标记');
      if (allowRaw && original.type.name === 'walle_raw_source') {
        if (original.textContent !== pending.textContent) changed.set(path.join('/'), pending.textContent);
        return;
      }
      if (original.text !== pending.text || original.childCount !== pending.childCount) throw new EditorSourceInvalid('原始节点编辑同时改变了其他正文');
      original.forEach((child, _offset, childIndex) => compare(child, pending.child(childIndex), [...path, childIndex], allowRaw));
    };
    compare(block.node, before, [], false);
    compare(before, after, [], true);
    let raw = block.markdown;
    const ranges = block.raw_sources.filter(range => changed.has(range.path.join('/'))).toSorted((a,b) => b.start_utf16 - a.start_utf16);
    if (ranges.length !== changed.size) throw new EditorSourceInvalid('原始节点编辑没有逐节点源范围');
    for (const range of ranges) {
      const value = changed.get(range.path.join('/'))!;
      const lines = sourceLines(value);
      const replacement = lines.length ? lines.map((line, lineIndex) =>
        (lineIndex ? range.continuation_prefix : range.first_prefix) + line).join('') :
        range.first_prefix + (/(?:\r\n|\r|\n)$/.exec(raw.slice(range.start_utf16, range.end_utf16))?.[0] ?? '');
      raw = raw.slice(0, range.start_utf16) + replacement + raw.slice(range.end_utf16);
    }
    return raw;
  }
}
