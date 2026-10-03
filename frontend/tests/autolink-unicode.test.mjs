import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import { remarkWallEGfm } from '../src/documents/autolink-remark.ts';
import { isUrlDomainAlphanumeric } from '../src/documents/url-domain-unicode.ts';

const fixtures = JSON.parse(readFileSync(new URL('../../shared/fixtures/autolink-unicode-v1.json', import.meta.url), 'utf8'));
test('actual literal tokenizer handles Unicode and astral letters in URL domains without widening email rules', () => {
  const processor = unified().use(remarkParse).use(remarkWallEGfm);
  for (const entry of fixtures.cases) {
    const links = [];
    function walk(node) {
      if (node.type === 'link') links.push({text: node.children.map(child => child.value ?? '').join(''), href: node.url});
      node.children?.forEach(walk);
    }
    walk(processor.parse(entry.markdown));
    assert.deepEqual(links, entry.links, entry.name);
  }
});
test('all Unicode codepoints match the shared selected-backend profile, including ranges and astral boundaries', () => {
  const profile = JSON.parse(readFileSync(new URL('../../shared/markdown/url-domain-unicode-v1.json', import.meta.url), 'utf8'));
  let range = 0;
  for (let point = 0; point < 0x110000; point++) {
    while (range < profile.ranges.length && point > profile.ranges[range][1]) range++;
    const expected = range < profile.ranges.length && point >= profile.ranges[range][0];
    assert.equal(isUrlDomainAlphanumeric(point), expected, `U+${point.toString(16)}`);
  }
  // This character has a category only in Node's newer profile. It must not
  // silently widen the accepted URL domains beyond the actual backend.
  assert.equal(isUrlDomainAlphanumeric(0x1c89), false);
  for (const point of [NaN, Infinity, -1, 0x110000, 1.5]) assert.equal(isUrlDomainAlphanumeric(point), false);
});
