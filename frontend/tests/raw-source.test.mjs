import assert from 'node:assert/strict';
import test from 'node:test';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import { remarkRawSource } from '../src/documents/raw-source-remark.ts';

test('actual flow chunks preserve raw source without reintroducing nested container markers', () => {
  const processor = unified().use(remarkParse).use(remarkRawSource);
  const source = '> - [a]:\r\n>     /chosen\r\n>     "题"\r\n>\r\n> - <div>\r\n>   \t字\t尾\r\n>   </div>\r\n';
  const raw = [];
  function walk(node) {
    if (node.walleRawValue !== undefined) raw.push({type: node.type, raw: node.walleRawValue});
    node.children?.forEach(walk);
  }
  walk(processor.parse(source));
  assert.deepEqual(raw, [{type: 'definition', raw: '[a]:\r\n  /chosen\r\n  "题"'},
    {type: 'html', raw: '<div>\r\n\t字\t尾\r\n</div>'}]);
});
