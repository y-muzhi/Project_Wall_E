import assert from 'node:assert/strict';
import test from 'node:test';
import { DocumentNavigation, headingOutline } from '../src/documents/navigation.ts';
import { DocumentSectionVisibility } from '../src/documents/section-folding.ts';

/** An offline navigation port tests ownership/state, not browser layout. */
function fixture(animations = false) {
  const saved = new Map(), frames = new Map();
  const expose = (key, value) => { saved.set(key, Object.getOwnPropertyDescriptor(globalThis, key)); Object.defineProperty(globalThis, key, { configurable: true, writable: true, value }); };
  let frameId = 0;
  const browser = Object.assign(new EventTarget(), { innerWidth: 1000, innerHeight: 800, CSS: { supports: () => animations }, matchMedia: () => ({ matches: false }), requestAnimationFrame: callback => { frames.set(++frameId, callback); return frameId; }, cancelAnimationFrame: id => frames.delete(id) });
  const styles = [];
  const document = Object.assign(new EventTarget(), { defaultView: browser, activeElement: null, head: { append: style => styles.push(style) }, createElement: () => ({ textContent: '', remove() { styles.splice(styles.indexOf(this), 1); } }) });
  const box = { left: 100, right: 900, top: 80, bottom: 700 };
  const root = Object.assign(new EventTarget(), { ownerDocument: document, classList: { add() {}, remove() {} }, querySelector: () => null, getBoundingClientRect: () => box, getClientRects: () => [box], scrollHeight: 900, clientHeight: 620, scrollTop: 0, clientTop: 0 });
  for (const [key, value] of Object.entries({ window: browser, document, requestAnimationFrame: browser.requestAnimationFrame, cancelAnimationFrame: browser.cancelAnimationFrame, MutationObserver: class { observe() {} disconnect() {} }, ResizeObserver: class { observe() {} disconnect() {} } })) expose(key, value);
  let content = { kind: 'MANUAL_DRAFT', blocks: Array.from({ length: 8 }, (_, index) => ({ block_id: index + 1 })), outline: headingOutline([{ block_id: 1, level: 1, text: '父章' }, { block_id: 3, level: 3, text: '子章' }, { block_id: 5, level: 3, text: '同级子章' }, { block_id: 7, level: 1, text: '下一章' }]) };
  const prepared = [];
  const port = { read: () => content, element: id => ({ getClientRects: () => [{}], getBoundingClientRect: () => ({ left: 160, right: 880, top: 90 + id * 35, bottom: 118 + id * 35 }) }), prepareCollapse: (heading, ids) => prepared.push([heading, [...ids]]) };
  const navigation = new DocumentNavigation(root, port, root);
  return { navigation, prepared, styles, browser, root, flushFrame() { const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(callback => callback()); }, change: next => { content = next; }, content: () => content, close() { navigation.dispose(); for (const [key, descriptor] of saved) { if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key]; } } };
}

test('one navigation fold state synchronizes leaf sections, nested preservation, reveal and visibility lifecycle', () => {
  const f = fixture(), nav = f.navigation;
  try {
    assert(nav.toggleHeading(3));
    assert.deepEqual(nav.getSnapshot().hidden_blocks, [4]);
    assert(nav.toggleHeading(1));
    assert.deepEqual(nav.getSnapshot().hidden_blocks, [2, 3, 4, 5, 6]);
    assert.deepEqual(f.prepared.at(-1), [1, [2, 3, 4, 5, 6]]);
    nav.setVisible(false);
    assert.deepEqual(nav.getSnapshot().heading_controls, []);
    nav.setVisible(true);
    assert.deepEqual(nav.getSnapshot().collapsed_headings, [3, 1]);
    assert(nav.toggleHeading(1));
    assert.deepEqual(nav.getSnapshot().collapsed_headings, [3]);
    assert.deepEqual(nav.getSnapshot().hidden_blocks, [4]);
    assert(nav.locate(4, true));
    assert.deepEqual(nav.getSnapshot().collapsed_headings, []);
    assert.deepEqual(nav.getSnapshot().hidden_blocks, []);
    assert.equal(nav.getSnapshot().selected_block, 4);
    assert.equal(nav.toggleHeading(999), false);
    assert(f.styles.every(style => !style.textContent.includes('display: none')));
  } finally { f.close(); }
  assert.equal(f.styles.length, 0);
});

test('refresh prunes removed or empty headings and folding closes a source view without changing content', () => {
  const f = fixture(), nav = f.navigation;
  try {
    const original = JSON.stringify(f.content());
    nav.source(4);
    assert(nav.toggleHeading(1));
    assert.equal(nav.getSnapshot().source_block, null);
    assert.equal(JSON.stringify(f.content()), original);
    f.change({ ...f.content(), outline: headingOutline([{ block_id: 7, level: 1, text: '仅剩标题' }]) });
    nav.refresh();
    assert.deepEqual(nav.getSnapshot().collapsed_headings, []);
    assert.deepEqual(nav.getSnapshot().hidden_blocks, []);
    assert(nav.toggleHeading(7));
    f.change({ ...f.content(), blocks: f.content().blocks.filter(block => block.block_id !== 8) });
    nav.refresh();
    assert.deepEqual(nav.getSnapshot().foldable_headings, []);
    assert.deepEqual(nav.getSnapshot().collapsed_headings, []);
    assert.equal(nav.toggleHeading(7), false);
  } finally { f.close(); }
});

test('missing displayed elements settle scoped visibility immediately without queued motion', () => {
  const f = fixture();
  let moved = 0;
  const visibility = new DocumentSectionVisibility(f.root, () => moved++);
  try {
    visibility.hide([2]);
    assert.equal(moved, 1);
    assert(f.styles.some(style => style.textContent.includes('display: none')));
    f.flushFrame();
    assert.equal(moved, 1);
    visibility.hide([]);
    assert.equal(moved, 2);
    assert(f.styles.every(style => !style.textContent.includes('display: none')));
    visibility.destroy();
    f.flushFrame();
    assert.equal(moved, 2);
  } finally { visibility.destroy(); f.close(); }
});
