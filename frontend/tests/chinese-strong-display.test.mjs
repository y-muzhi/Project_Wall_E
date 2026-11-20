import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Schema } from '@milkdown/kit/prose/model';
import { chineseStrongDecorations } from '../src/documents/chinese-strong-display.ts';

const schema = new Schema({
  nodes: {
    doc: { content: 'block+' },
    paragraph: { group: 'block', content: 'text*' },
    code_block: { group: 'block', content: 'text*', code: true },
    text: {},
  },
  marks: { code: { code: true }, strong: {} },
});

test('Chinese closing punctuation creates display decorations without changing the document text', () => {
  const text = '**建议首要使用者：**刚开始。提醒 **注意事项？**继续。';
  const doc = schema.node('doc', null, [schema.node('paragraph', null, schema.text(text))]);
  const decorations = chineseStrongDecorations(doc, [{ markdown: text }]).find();

  assert.deepEqual(
    decorations.map(({ from, to }) => doc.textBetween(from, to)),
    ['**', '建议首要使用者：', '**', '**', '注意事项？', '**'],
  );
  assert.equal(doc.textContent, text);
});

test('escaped or ambiguous source, existing strong marks and code text stay literal', () => {
  const text = '**示例：**后来';
  for (const [type, marks, markdown] of [
    ['paragraph', [], '\\' + text],
    ['paragraph', [], text + ' ' + text],
    ['paragraph', [schema.mark('strong')], text],
    ['paragraph', [schema.mark('code')], text],
    ['code_block', [], text],
    ['paragraph', [], 'unrelated source'],
  ]) {
    const doc = schema.node('doc', null, [schema.node(type, null, schema.text(text, marks))]);
    assert.equal(chineseStrongDecorations(doc, [{ markdown }]).find().length, 0, markdown);
  }
});
