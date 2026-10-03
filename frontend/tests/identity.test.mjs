import assert from 'node:assert/strict';
import test from 'node:test';
import { Schema } from '@milkdown/kit/prose/model';
import { EditorState, TextSelection } from '@milkdown/kit/prose/state';
import { splitBlock, joinBackward } from '@milkdown/kit/prose/commands';
import { history, undo, redo, closeHistory } from '@milkdown/kit/prose/history';
import { bindIdentityDocument, createIdentityPlugin, identityState, topBlockIds, moveTopBlock, joinEmptyParagraphBackward, joinEmptyParagraphForward } from '../src/documents/identity.ts';

const schema = new Schema({nodes: {
  doc: {content: 'block+'},
  paragraph: {content:'text*',group:'block',attrs:{walle_block_id:{default:null}}},
  blockquote: {content:'block+',group:'block',attrs:{walle_block_id:{default:null}}},
  hr: {group:'block',attrs:{walle_block_id:{default:null}}},
  text: {group:'inline'},
}});
const paragraph = text => schema.node('paragraph', null, text ? schema.text(text) : null);
function editor(nodes = [paragraph('甲😀乙'), paragraph('甲😀乙')], ids = [10, 20], next = 30) {
  const doc = bindIdentityDocument(schema.node('doc', null, nodes), ids, next);
  return EditorState.create({doc, plugins:[history(), createIdentityPlugin(ids, next)]});
}
function apply(state, tr) { return state.applyTransaction(tr).state; }
function command(state, action) {
  let result;
  assert.equal(action(state, tr => { result = apply(state, tr); }), true);
  assert.ok(result);
  return result;
}

test('editing identical blocks follows transaction positions, retains IDs and selection', () => {
  let state = editor();
  state = apply(state, state.tr.setSelection(TextSelection.create(state.doc, 2)).insertText('增'));
  assert.deepEqual(topBlockIds(state.doc), [10, 20]);
  assert.equal(state.selection.from, 3);
  assert.equal(identityState(state).next_block_id, 30);
});

test('copied attributes before original get new ID; pasted unknown IDs and nested IDs are removed', () => {
  let state = editor();
  state = apply(state, state.tr.insert(0, state.doc.child(0)));
  assert.deepEqual(topBlockIds(state.doc), [30, 10, 20]);
  assert.equal(identityState(state).next_block_id, 31);
  const foreign = schema.node('blockquote', {walle_block_id: 999}, paragraph('未知'));
  state = apply(state, state.tr.insert(state.doc.content.size, foreign));
  assert.deepEqual(topBlockIds(state.doc), [30, 10, 20, 31]);
  assert.equal(state.doc.lastChild.firstChild.attrs.walle_block_id, null);
});

test('split at middle and at start keeps first part; joining keeps first document ID', () => {
  for (const offset of [1, 2]) {
    let state = editor([paragraph('甲乙')], [10], 30);
    state = apply(state, state.tr.setSelection(TextSelection.create(state.doc, offset)));
    state = command(state, splitBlock);
    assert.deepEqual(topBlockIds(state.doc), [10, 30]);
    const second = state.doc.child(0).nodeSize + 1;
    state = apply(state, state.tr.setSelection(TextSelection.create(state.doc, second)));
    state = command(state, offset === 1 ? joinEmptyParagraphBackward : joinBackward);
    assert.deepEqual(topBlockIds(state.doc), [10]);
    assert.equal(identityState(state).next_block_id, 31);
  }
});

test('forward join of an empty first paragraph keeps first identity and ordinary mid-text deletion is deferred', () => {
  let state = editor([paragraph(''), paragraph('内容')], [10,20], 30);
  state = apply(state, state.tr.setSelection(TextSelection.create(state.doc, 1)));
  state = command(state, joinEmptyParagraphForward);
  assert.deepEqual(topBlockIds(state.doc), [10]);
  assert.equal(state.doc.textContent, '内容');
  state = apply(state, state.tr.setSelection(TextSelection.create(state.doc, 2)));
  assert.equal(joinEmptyParagraphBackward(state, () => { throw new Error('应交给普通删除'); }), false);
});

test('explicit movement preserves origins, including identical content and complete containers', () => {
  let state = editor([paragraph('同'), paragraph('同'), schema.node('blockquote', null, paragraph('内'))], [10, 20, 25], 30);
  state = apply(state, moveTopBlock(state, 0, 2));
  assert.deepEqual(topBlockIds(state.doc), [20, 25, 10]);
  state = apply(state, moveTopBlock(state, 1, 0));
  assert.deepEqual(topBlockIds(state.doc), [25, 20, 10]);
  assert.equal(state.doc.firstChild.firstChild.attrs.walle_block_id, null);
  assert.equal(identityState(state).next_block_id, 30);
});

test('undo/redo restore same allocated IDs while high water never decreases', () => {
  let state = editor([paragraph('甲乙')], [10], 30);
  state = apply(state, closeHistory(state.tr).setSelection(TextSelection.create(state.doc, 2)));
  state = command(state, splitBlock);
  assert.deepEqual(topBlockIds(state.doc), [10, 30]);
  state = command(state, undo);
  assert.deepEqual(topBlockIds(state.doc), [10]);
  assert.equal(identityState(state).next_block_id, 31);
  state = command(state, redo);
  assert.deepEqual(topBlockIds(state.doc), [10, 30]);
  assert.equal(identityState(state).next_block_id, 31);
});

test('removed identity is only restored by actual local history, never a later pasted copy', () => {
  let state = editor();
  const removed = state.doc.firstChild;
  state = apply(state, state.tr.delete(0, removed.nodeSize));
  state = apply(state, closeHistory(state.tr).insert(0, removed));
  assert.deepEqual(topBlockIds(state.doc), [30, 20]);
  state = command(state, undo);
  assert.deepEqual(topBlockIds(state.doc), [20]);
  state = command(state, undo);
  assert.deepEqual(topBlockIds(state.doc), [10, 20]);
  assert.equal(identityState(state).next_block_id, 31);
});

test('atom blocks retain ID when typing elsewhere; whole unknown replacements receive new ID', () => {
  let state = editor([schema.node('hr'), paragraph('文')], [10, 20], 30);
  state = apply(state, state.tr.insertText('增', 2));
  assert.deepEqual(topBlockIds(state.doc), [10, 20]);
  state = apply(state, state.tr.replaceWith(0, 1, schema.node('hr', {walle_block_id:10})));
  assert.deepEqual(topBlockIds(state.doc), [30, 20]);
});

test('empty caret has no business ID; deletion does not recycle IDs and undo restores old one', () => {
  let state = editor([paragraph('')], [], 50);
  state = apply(state, state.tr.insertText('甲', 1));
  assert.deepEqual(topBlockIds(state.doc), [50]);
  state = apply(state, closeHistory(state.tr).delete(1, 2));
  assert.deepEqual(topBlockIds(state.doc), [null]);
  assert.equal(identityState(state).next_block_id, 51);
  state = command(state, undo);
  assert.deepEqual(topBlockIds(state.doc), [50]);
});

test('a new empty gap paragraph consumes no ID until actual text appears', () => {
  let state = editor([paragraph('甲')], [10], 30);
  state = apply(state, state.tr.insert(state.doc.content.size, paragraph('')));
  assert.deepEqual(topBlockIds(state.doc), [10,null]);
  assert.equal(identityState(state).next_block_id, 30);
  const moved = apply(state, moveTopBlock(state, 0, 1));
  assert.deepEqual(topBlockIds(moved.doc), [null,10]);
  assert.equal(identityState(moved).next_block_id, 30);
  state = apply(state, state.tr.insertText('新', state.doc.firstChild.nodeSize + 1));
  assert.deepEqual(topBlockIds(state.doc), [10,30]);
  assert.equal(identityState(state).next_block_id, 31);
});

test('capacity rejects entire transaction with original document/high-water untouched', () => {
  const state = editor([paragraph('原文')], [10], Number.MAX_SAFE_INTEGER);
  assert.throws(() => apply(state, state.tr.insert(0, paragraph('新增'))), {code:'CAPACITY_EXCEEDED'});
  assert.deepEqual(topBlockIds(state.doc), [10]);
  assert.equal(identityState(state).next_block_id, Number.MAX_SAFE_INTEGER);
  assert.equal(state.doc.textContent, '原文');
});

test('10000-block boundary keeps unrelated nodes and selections; further block insertion fails atomically', () => {
  const ids = Array.from({length:10_000}, (_, index) => index + 1);
  let state = editor(ids.map(() => paragraph('同')), ids, 10_001);
  const untouched = state.doc.firstChild;
  state = apply(state, state.tr.insertText('改', state.doc.content.size - 2));
  assert.equal(state.doc.firstChild, untouched);
  assert.deepEqual(topBlockIds(state.doc), ids);
  assert.equal(identityState(state).next_block_id, 10_001);
  assert.throws(() => apply(state, state.tr.insert(0, paragraph('超额'))), {code:'DOCUMENT_INVALID'});
  assert.equal(state.doc.childCount, 10_000);
});

test('invalid initial identities fail; changing an ID attr cannot steal another block ID', () => {
  for (const ids of [[10,10], [0,20], [1.5,20], [30,20]]) assert.throws(() => editor(undefined, ids, 30), {code:'DOCUMENT_INVALID'});
  let state = editor();
  state = apply(state, state.tr.setNodeMarkup(0, undefined, {walle_block_id:20}));
  assert.deepEqual(topBlockIds(state.doc), [10,20]);
  const copy = identityState(state);
  copy.known_ids.clear();
  assert.equal(identityState(state).known_ids.has(10), true);
});
