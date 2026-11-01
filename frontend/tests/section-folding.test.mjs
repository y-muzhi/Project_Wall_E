import assert from 'node:assert/strict';
import test from 'node:test';
import { Schema } from '@milkdown/kit/prose/model';
import { EditorState, TextSelection } from '@milkdown/kit/prose/state';
import { headingSections, foldedBlockIds, foldedTransactionEffect } from '../src/documents/section-folding.ts';
import { visibleOutline } from '../src/documents/outline-display.ts';

test('sections keep their own title and stop before the next same or higher heading', () => {
  const blocks = [10, 20, 30, 40, 50, 60, 70, 80, 90];
  const outline = [{ block_id: 20, level: 2, depth: 0 }, { block_id: 40, level: 4, depth: 1 }, { block_id: 60, level: 2, depth: 0 }, { block_id: 80, level: 1, depth: 0 }];
  const sections = headingSections(blocks, outline);
  assert.deepEqual(sections, [{ block_id: 20, from: 1, to: 5 }, { block_id: 40, from: 3, to: 5 }, { block_id: 60, from: 5, to: 7 }, { block_id: 80, from: 7, to: 9 }]);
  assert.deepEqual(foldedBlockIds(blocks, sections, new Set([20])), [30, 40, 50]);
  assert.deepEqual(foldedBlockIds(blocks, sections, new Set([60])), [70]);
  assert.deepEqual(foldedBlockIds(blocks, sections, new Set([80])), [90]);
  assert.deepEqual(visibleOutline(outline, new Set([20])), [true, false, true, true]);
  assert.equal(Object.isFrozen(sections), true);
});

test('nested folds retain child state after parent expansion; repeated labels and leaf content use actual IDs', () => {
  const blocks = [1, 2, 3, 4, 5, 6], headings = [{ block_id: 1, level: 1 }, { block_id: 3, level: 2 }, { block_id: 5, level: 2 }, { block_id: 6, level: 1 }];
  const sections = headingSections(blocks, headings);
  assert.deepEqual(foldedBlockIds(blocks, sections, new Set([1, 3])), [2, 3, 4, 5]);
  assert.deepEqual(foldedBlockIds(blocks, sections, new Set([3])), [4]);
  assert.deepEqual(foldedBlockIds(blocks, sections, new Set([5, 6, 999])), []);
  assert.deepEqual(foldedBlockIds(blocks, sections, new Set()), []);
  assert.deepEqual(headingSections([1, 2], []), []);
});

const schema = new Schema({ nodes: { doc: { content: 'block+' }, paragraph: { group: 'block', content: 'text*', attrs: { walle_block_id: { default: null } } }, heading: { group: 'block', content: 'text*', attrs: { walle_block_id: { default: null }, level: { default: 1 } } }, text: {} }, marks: { strong: {} } });
const node = (id, text, heading = false) => schema.nodes[heading ? 'heading' : 'paragraph'].create({ walle_block_id: id }, schema.text(text));
function fixture() {
  const doc = schema.nodes.doc.create(null, [node(1, '标题', true), node(2, '隐藏正文'), node(3, '同级标题', true), node(4, '可见正文')]);
  const positions = new Map();
  doc.forEach((child, position) => positions.set(child.attrs.walle_block_id, position));
  return { state: EditorState.create({ doc }), positions };
}

test('hidden text edits, marks, deletion and moves reveal first without accepting the change', () => {
  const { state, positions } = fixture(), start = positions.get(2), end = positions.get(3), hidden = new Set([2]);
  const transactions = [state.tr.insertText('新', start + 1), state.tr.delete(start, end), state.tr.addMark(start + 1, end - 1, schema.marks.strong.create()), state.tr.delete(start, end).insert(0, state.doc.child(1))];
  for (const transaction of transactions) {
    const effect = foldedTransactionEffect(state, transaction, hidden);
    assert.equal(effect.reject, true);
    assert.deepEqual(effect.reveal, [2]);
    assert.equal(state.doc.child(1).textContent, '隐藏正文');
  }
});

test('visible edits remain writable, and hidden/cross-block selection only reveals its actual ancestors', () => {
  const { state, positions } = fixture(), hidden = new Set([2]);
  assert.deepEqual(foldedTransactionEffect(state, state.tr.insertText('新', positions.get(4) + 1), hidden), { reveal: [], reject: false });
  const selected = state.tr.setSelection(TextSelection.create(state.doc, positions.get(2) + 1));
  assert.deepEqual(foldedTransactionEffect(state, selected, hidden), { reveal: [2], reject: false });
  const across = state.tr.setSelection(TextSelection.create(state.doc, 1, positions.get(4) + 2));
  assert.deepEqual(foldedTransactionEffect(state, across, hidden), { reveal: [2], reject: false });
});
