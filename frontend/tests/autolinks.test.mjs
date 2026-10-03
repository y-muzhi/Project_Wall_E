import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import { remarkWallEGfm } from '../src/documents/autolink-remark.ts';

const processor = unified().use(remarkParse).use(remarkWallEGfm);
const fixtures = JSON.parse(readFileSync(new URL('../../shared/fixtures/autolink-v1.json', import.meta.url), 'utf8'));
const contexts = JSON.parse(readFileSync(new URL('../../shared/fixtures/autolink-context-v1.json', import.meta.url), 'utf8'));
function links(root) {
  const result = [];
  function text(node) { return node.value ?? node.children?.map(text).join('') ?? ''; }
  function walk(node) {
    if (node.type === 'link') result.push({text: text(node), href: node.url});
    node.children?.forEach(walk);
  }
  walk(root);
  return result;
}
test('actual remark tokenizer matches independent GFM literal cases before emphasis/entity decoding', () => {
  for (const entry of fixtures.cases) assert.deepEqual(links(processor.parse(entry.markdown)), entry.links, entry.name);
});
test('actual tokenizer respects independent source, entity, image and container contexts', () => {
  for (const entry of contexts.cases) {
    // Reference resolution belongs to the production source-node transformer,
    // exercised by real Crepe; here only the syntax tokenizer is installed.
    if (entry.name === 'reference-label-no-nested-link') continue;
    assert.deepEqual(links(processor.parse(entry.markdown)), entry.links, entry.name);
  }
});
test('literal links respect inline chunk boundaries in real tables, lists, headings and quotes', () => {
  const url = 'www.example.test/a*b*c';
  const expected = [{text: url, href: 'http://' + url}];
  for (const markdown of [`# ${url}\n`, `> ${url}\n`, `- ${url}\n`, `- [ ] ${url}\n`,
    `| ${url}|标题|\n|---|---|\n| 值|值|\n`, `| 标题|标题|\n|---|---|\n| ${url}|值|\n`]) {
    assert.deepEqual(links(processor.parse(markdown)), expected, markdown);
  }
});
test('long invalid candidates, nested URL paths and link labels keep exact text without repeated path scans', () => {
  assert.deepEqual(links(processor.parse('httpſ://example.test')), []);
  const plain = 'www.invalid_domain.test '.repeat(10000);
  assert.deepEqual(links(processor.parse(plain)), []);
  const path = 'www.example.test/' + 'www.example.test/'.repeat(10000);
  assert.deepEqual(links(processor.parse(path)), [{text: path, href: 'http://' + path}]);
  const label = 'name@example.t2 '.repeat(10000).trimEnd();
  assert.deepEqual(links(processor.parse(`[${label}](/chosen)`)), [{text: label, href: '/chosen'}]);
});
