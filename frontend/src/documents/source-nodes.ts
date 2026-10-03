import type { Crepe } from '@milkdown/crepe';
import type { MarkdownNode } from '@milkdown/kit/transformer';
import { $node, $remark } from '@milkdown/kit/utils';
import {
  remarkHtmlTransformer, remarkInlineLinkPlugin, remarkPreserveEmptyLinePlugin, syncHeadingIdPlugin, codeBlockSchema,
} from '@milkdown/kit/preset/commonmark';
import { uploadPlugin } from '@milkdown/kit/plugin/upload';
import { trailing } from '@milkdown/kit/plugin/trailing';
import { remarkGFMPlugin } from '@milkdown/kit/preset/gfm';
import { remarkWallEGfm } from './autolink-remark.ts';

// A text node, never innerHTML: authored HTML and definitions stay visible,
// including duplicates that remark-inline-links would otherwise discard.
const rawSourceNode = $node('walle_raw_source', () => ({
  group: 'block', content: 'text*', marks: '', code: true, defining: true,
  attrs: { kind: { default: 'html_block' } },
  parseDOM: [{ tag: 'pre[data-walle-raw]', preserveWhitespace: 'full',
    getAttrs: dom => ({kind: dom.getAttribute('data-walle-raw')}) }],
  toDOM: node => ['pre', {'data-walle-raw': node.attrs.kind}, ['code', 0]],
  parseMarkdown: {
    match: node => node.type === 'walleRawSource',
    runner: (state, node, type) => {
      state.openNode(type, {kind: node.kind});
      if (node.value) state.addText(String(node.value));
      state.closeNode();
    },
  },
  toMarkdown: {
    match: node => node.type.name === 'walle_raw_source',
    runner: (state, node) => { state.addNode('html', undefined, node.textContent); },
  },
}));

const sourceCodeNode = codeBlockSchema.extendSchema(previous => ctx => {
  const original = previous(ctx);
  return {...original, attrs: {...original.attrs, walle_code_tail: {default: '\n', validate: 'string'}},
    parseMarkdown: {...original.parseMarkdown, runner: (state, node, type) => {
      state.openNode(type, {language: node.lang ?? '', walle_code_tail: node.walleCodeTail});
      if (node.value) state.addText(String(node.value));
      state.closeNode();
    }},
  };
});

function sourceValue(node: MarkdownNode, source: string, wholeLine = false): string {
  let start = node.position?.start.offset;
  const end = node.position?.end.offset;
  if (start === undefined || end === undefined) throw new Error('原始节点缺少源位置');
  if (wholeLine) while (start > 0 && !'\r\n'.includes(source[start - 1]!)) start--;
  const ending = /^(?:\r\n|\r|\n)/.exec(source.slice(end))?.[0] ?? '';
  return source.slice(start, end) + ending;
}

const sourceRemark = $remark('walle-source-nodes', () => () => (root, file) => {
  const source = String(file.value);
  const definitions = new Map<string, MarkdownNode>();
  const scan = (node: MarkdownNode) => {
    if (node.type === 'definition' && !definitions.has(String(node.identifier))) {
      definitions.set(String(node.identifier), node);
    }
    node.children?.forEach(scan);
  };
  scan(root as MarkdownNode);
  const transform = (node: MarkdownNode, flow: boolean, depth: number) => {
    const originalType = node.type;
    if (originalType === 'definition' || (originalType === 'html' && flow)) {
      node.value = sourceValue(node, source, depth === 1);
      node.kind = originalType === 'definition' ? 'link_definition' : 'html_block';
      node.type = 'walleRawSource';
    } else if (originalType === 'linkReference' || originalType === 'imageReference') {
      const definition = definitions.get(String(node.identifier));
      if (!definition) throw new Error('引用定义解析不一致');
      node.type = originalType === 'linkReference' ? 'link' : 'image';
      node.url = definition.url;
      node.title = definition.title;
    }
    if (node.type === 'image') {
      // Milkdown's image attrs require strings; mdast uses null for no title.
      node.alt = typeof node.alt === 'string' ? node.alt : '';
      node.title = typeof node.title === 'string' ? node.title : '';
    }
    if (node.type === 'code') {
      const raw = sourceValue(node, source);
      const lines = raw.match(/[^\r\n]*(?:\r\n|\r|\n|$)/g)?.filter(Boolean) ?? [];
      const opening = /^( *)(`{3,}|~{3,})/.exec(lines[0] ?? '');
      let body = raw;
      if (opening) {
        body = lines.slice(1).join('');
        const last = lines.at(-1) ?? '';
        const marker = opening[2]!;
        const container = depth === 1 ? '^ {0,3}' : '^(?:[ \\t]*>[ \\t]*)*[ \\t]*';
        const closing = new RegExp(container + marker[0] + '{' + marker.length + ',}[ \\t]*(?:\\r\\n|\\r|\\n)?$');
        if (lines.length > 1 && closing.test(last)) body = lines.slice(1, -1).join('');
      }
      node.walleCodeTail = /(?:\r\n|\r|\n)$/.test(body) ? '\n' : '';
      node.value = String(node.value ?? '').replace(/\r\n|\r/g, '\n');
    }
    const childrenAreFlow = ['root', 'blockquote', 'listItem'].includes(originalType);
    node.children?.forEach(child => transform(child, childrenAreFlow, depth + 1));
  };
  transform(root as MarkdownNode, true, 0);
});

export async function installSourceNodes(crepe: Crepe): Promise<void> {
  // Do this before create(). Upload has no persistent media API in the design;
  // dropping files must never insert a temporary blob URL into saved Markdown.
  await crepe.editor.remove([
    ...remarkGFMPlugin,
    ...remarkInlineLinkPlugin, ...remarkHtmlTransformer,
    ...remarkPreserveEmptyLinePlugin, syncHeadingIdPlugin, uploadPlugin, ...trailing, codeBlockSchema.node,
  ]);
  crepe.editor.use($remark('walle-gfm', () => remarkWallEGfm)).use(sourceCodeNode).use(rawSourceNode).use(sourceRemark);
}
