import type { Processor } from 'unified';
import type { Construct, Extension as SyntaxExtension } from 'micromark-util-types';
import type { Extension as AstExtension } from 'mdast-util-from-markdown';
import type { Options as MarkdownOptions } from 'mdast-util-to-markdown';
import { gfmTable } from 'micromark-extension-gfm-table';
import { gfmStrikethrough } from 'micromark-extension-gfm-strikethrough';
import { gfmTaskListItem } from 'micromark-extension-gfm-task-list-item';
import { gfmTableFromMarkdown, gfmTableToMarkdown } from 'mdast-util-gfm-table';
import { gfmStrikethroughFromMarkdown, gfmStrikethroughToMarkdown } from 'mdast-util-gfm-strikethrough';
import { gfmTaskListItemFromMarkdown, gfmTaskListItemToMarkdown } from 'mdast-util-gfm-task-list-item';
import { gfmAutolinkLiteralToMarkdown } from 'mdast-util-gfm-autolink-literal';
import { AutolinkIndex, type LiteralLink } from './autolink-lexemes.ts';

declare module 'micromark-util-types' {
  interface TokenTypeMap {
    walleLiteralAutolink: 'walleLiteralAutolink';
    walleLiteralText: 'walleLiteralText';
  }
}

// Replace only the bundled GFM parser plugin. Keep the approved table/task/
// strikethrough syntax and serializer escaping, omit unregistered footnotes,
// and do literal links before entities/emphasis, not on decoded AST text.
export function remarkWallEGfm(this: Processor): void {
  const processor = this;
  const data = processor.data() as {
    micromarkExtensions?: SyntaxExtension[];
    fromMarkdownExtensions?: AstExtension[];
    toMarkdownExtensions?: MarkdownOptions[];
  };
  let active: AutolinkIndex | undefined;
  const construct: Construct = {
    name: 'walleLiteralAutolink',
    tokenize(effects, ok, nok) {
      const context = this;
      let link: LiteralLink;
      let previous: string | null;
      return start;
      function start(code: number | null) {
        const offset = context.now().offset;
        if (!active?.starts.has(offset)) return nok(code);
        // Use this pinned micromark version's actual label stack. Scanning all
        // earlier events for each address makes long link labels quadratic.
        if (context._labelStarts?.findLast(token => !token._balanced)) return nok(code);
        previous = context.previous === null ? null : context.previous < 0 ? '\n' : String.fromCharCode(context.previous);
        const matched = active.match(offset, active.source.length, previous);
        if (!matched) return nok(code);
        link = matched;
        // A table cell is an inline input chunk whose EOF can precede the
        // physical source line's end. Probe with automatic rollback, then
        // match within that actual boundary before consuming final tokens.
        return effects.check({tokenize: probe}, begin, nok)(code);
      }
      function probe(probeEffects: Parameters<Construct['tokenize']>[0], probeOk: Parameters<Construct['tokenize']>[1], probeNok: Parameters<Construct['tokenize']>[2]) {
        probeEffects.enter('walleLiteralText');
        return scan;
        function finish(code: number | null) {
          probeEffects.exit('walleLiteralText');
          return probeOk(code);
        }
        function scan(code: number | null) {
          const offset = context.now().offset;
          if (offset === link.end) return finish(code);
          if (code === null || code < 0) {
            const bounded = active!.match(link.start, offset, previous);
            if (!bounded) return probeNok(code);
            link = bounded;
            return finish(code);
          }
          if (offset > link.end) return probeNok(code);
          probeEffects.consume(code);
          return scan;
        }
      }
      function begin(code: number | null) {
        effects.enter('walleLiteralAutolink');
        effects.enter('walleLiteralText');
        return consume(code);
      }
      function consume(code: number | null) {
        if (context.now().offset === link.end) {
          effects.exit('walleLiteralText');
          effects.exit('walleLiteralAutolink');
          return ok(code);
        }
        if (code === null || code < 0 || context.now().offset > link.end) return nok(code);
        effects.consume(code);
        return consume;
      }
    },
  };
  const text = Object.fromEntries([...'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.+_-'].map(char => [char.charCodeAt(0), construct]));
  const ast: AstExtension = {
    enter: {
      walleLiteralAutolink(token) {
        const index = active;
        if (!index) throw new Error('自动链接解析上下文缺失');
        const raw = this.sliceSerialize(token);
        const prefix = this.stack.some(node => node.type === 'tableCell') ? raw.replace(/\\\|/g, '|') : raw;
        const protocol = /^(?:www\.|mailto:|xmpp:|https?:\/\/)/i.exec(prefix)?.[0].toLowerCase();
        const href = protocol === 'www.' ? 'http://' + prefix : ['mailto:', 'xmpp:'].includes(protocol ?? '') ? prefix :
          protocol?.startsWith('http') ? prefix : 'mailto:' + prefix;
        this.enter({type: 'link', title: null, url: href.replace(/\0/g, '\ufffd'), children: []}, token);
      },
      walleLiteralText(token) { this.enter({type: 'text', value: ''}, token); },
    },
    exit: {
      walleLiteralText(token) {
        const node = this.stack.at(-1);
        if (node?.type !== 'text') throw new Error('自动链接文本栈不一致');
        const raw = this.sliceSerialize(token);
        node.value = this.stack.some(parent => parent.type === 'tableCell') ? raw.replace(/\\\|/g, '|') : raw;
        this.exit(token);
      },
      walleLiteralAutolink(token) { this.exit(token); },
    },
  };
  (data.micromarkExtensions ??= []).push(gfmTable(), gfmStrikethrough(), gfmTaskListItem(), {text});
  (data.fromMarkdownExtensions ??= []).push(gfmTableFromMarkdown(), gfmStrikethroughFromMarkdown(), gfmTaskListItemFromMarkdown(), ast);
  (data.toMarkdownExtensions ??= []).push(gfmTableToMarkdown(), gfmStrikethroughToMarkdown(), gfmTaskListItemToMarkdown(), gfmAutolinkLiteralToMarkdown());
  const parser = processor.parser;
  if (!parser) throw new Error('Markdown基础解析器未安装');
  processor.parser = (document, file) => {
    const previous = active;
    active = new AutolinkIndex(document);
    try { return parser(document, file); }
    finally { active = previous; }
  };
}
