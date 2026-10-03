import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import { remarkWallEGfm } from '../src/documents/autolink-remark.ts';

const fixtures = JSON.parse(readFileSync(new URL('../../shared/fixtures/strikethrough-v1.json', import.meta.url), 'utf8'));
function text(node) { return node.type === 'break' ? '\n' : node.value ?? node.children?.map(text).join('') ?? ''; }
test('installed production remark extension implements independent GFM single/double/width cases', () => {
  const processor = unified().use(remarkParse).use(remarkWallEGfm);
  for (const entry of fixtures.cases) {
    const actual = [];
    function walk(node, inside = false) {
      if (node.type === 'delete' && !inside) actual.push(text(node));
      node.children?.forEach(child => walk(child, inside || node.type === 'delete'));
    }
    walk(processor.parse(entry.markdown));
    assert.deepEqual(actual, entry.deleted, entry.name);
  }
});
