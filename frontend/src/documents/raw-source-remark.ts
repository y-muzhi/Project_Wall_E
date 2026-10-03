import type { Processor } from 'unified';
import type { Extension } from 'mdast-util-from-markdown';
import type { MarkdownNode } from '@milkdown/kit/transformer';

// The actual flow tokenizer has already removed container prefixes. Its
// chunks preserve authored CR/LF, whitespace and escapes; physical span
// slicing would reintroduce quote/list markers on continuation lines.
export function remarkRawSource(this: Processor): void {
  const data = this.data() as {fromMarkdownExtensions?: Extension[]};
  (data.fromMarkdownExtensions ??= []).push({exit: {
    definition(token) {
      const node = this.stack.at(-1) as MarkdownNode;
      node.walleRawValue = this.sliceSerialize(token);
      this.exit(token);
    },
    htmlFlow(token) {
      this.resume(); // Balance the default HTML opener's buffer.
      const node = this.stack.at(-1) as MarkdownNode;
      node.value = node.walleRawValue = this.sliceSerialize(token);
      this.exit(token);
    },
  }});
}
