import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { codepointToUtf16, selectionFromProjectedText, SelectionInvalid, utf16RangeForSelection, utf16ToCodepoint } from '../src/documents/selection.ts';

const current = Object.freeze({ document_id: 201, content_version: 7, block_id: 2 });
const invalid = fn => assert.throws(fn, error => error instanceof SelectionInvalid && error.code === 'SELECTION_INVALID');
const stale = fn => assert.throws(fn, error => error instanceof SelectionInvalid && error.code === 'STALE_SELECTION');

test('shared independent Markdown projection and selection fixtures', () => {
  const fixture = JSON.parse(readFileSync(new URL('../../shared/fixtures/selection-v1.json', import.meta.url), 'utf8'));
  for (const item of fixture.cases) {
    const event = selectionFromProjectedText(current, item.plain_text, item.start_utf16, item.end_utf16);
    assert.deepEqual(event, { ...current, start_offset: item.start_offset, end_offset: item.end_offset, selected_text: item.selected_text, prefix_text: item.prefix_text, suffix_text: item.suffix_text }, item.name);
    assert.deepEqual(utf16RangeForSelection(current, item.plain_text, event), { start: item.start_utf16, end: item.end_utf16 });
  }
});

test('Unicode offsets count codepoints including combining marks, ZWJ and CRLF', () => {
  const text = '甲😀e\u0301👩‍💻\r\n乙';
  const expected = [0, 1, 3, 4, 5, 7, 8, 10, 11, 12, 13];
  for (let index = 0; index < expected.length; index++) {
    assert.equal(codepointToUtf16(text, index), expected[index]);
    assert.equal(utf16ToCodepoint(text, expected[index]), index);
  }
  assert.equal(codepointToUtf16('', 0), 0);
  assert.equal(utf16ToCodepoint('', 0), 0);
});

test('surrogate interiors, invalid Unicode and coerced integers are rejected', () => {
  for (const value of [2, -1, 0.5, '1', true, null, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) invalid(() => utf16ToCodepoint('甲😀乙', value));
  for (const value of [-1, 4, '1', true]) invalid(() => codepointToUtf16('甲😀乙', value));
  for (const text of ['\ud800', '\udc00', 'x\ud800y']) invalid(() => codepointToUtf16(text, 0));
});

test('selection keeps raw text and immediate context, binds snapshot identity', () => {
  const text = '甲😀e\u0301乙\r\n尾';
  const event = selectionFromProjectedText(current, text, 1, 5);
  assert.deepEqual(event, { ...current, start_offset: 1, end_offset: 4, selected_text: '😀e\u0301', prefix_text: '甲', suffix_text: '乙\r\n尾' });
  assert.deepEqual(utf16RangeForSelection(current, text, event), { start: 1, end: 5 });
  assert.equal(Object.isFrozen(event), true);
  for (const key of ['document_id', 'content_version', 'block_id']) stale(() => utf16RangeForSelection({ ...current, [key]: current[key] + 1 }, text, event));
  stale(() => utf16RangeForSelection(current, text.replace('甲', '前'), event));
});

test('100-codepoint context boundaries do not split emoji or normalize content', () => {
  const text = '😀'.repeat(120) + ' \t选区\t ' + '😀'.repeat(130);
  const event = selectionFromProjectedText(current, text, 240, 246);
  assert.equal(event.selected_text, ' \t选区\t ');
  assert.equal(event.prefix_text, '😀'.repeat(100));
  assert.equal(event.suffix_text, '😀'.repeat(100));
  assert.deepEqual(utf16RangeForSelection(current, text, event), { start: 240, end: 246 });
});

test('2000-codepoint selection is accepted; 2001 never truncated', () => {
  const text = '😀'.repeat(2001);
  const event = selectionFromProjectedText(current, text, 0, 4000);
  assert.equal(event.selected_text.length, 4000);
  assert.equal(event.end_offset, 2000);
  assert.equal(event.suffix_text, '😀');
  invalid(() => selectionFromProjectedText(current, text, 0, 4002));
});

test('collapsed, reversed, extra fields and wrong snapshot values cannot form selection', () => {
  for (const range of [[0, 0], [2, 1], [0, 4], [0, 1.1]]) invalid(() => selectionFromProjectedText(current, '正文', ...range));
  for (const bad of [{ ...current, block_id: 0 }, { ...current, document_id: true }, { ...current, extra: 1 }]) invalid(() => selectionFromProjectedText(bad, '正文', 0, 1));
  const event = selectionFromProjectedText(current, '正文', 0, 1);
  invalid(() => utf16RangeForSelection(current, '正文', { ...event, unknown: true }));
  invalid(() => utf16RangeForSelection(current, '正文', { ...event, end_offset: 0 }));
  stale(() => utf16RangeForSelection(current, '正文', { ...event, selected_text: '伪造' }));
});
