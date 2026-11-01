import assert from 'node:assert/strict';
import test from 'node:test';
import { observeDocumentSelection, documentSelectionToolbarPosition } from '../src/documents/selection-surface.ts';
import { DocumentBlockHighlight } from '../src/documents/block-highlight.ts';

function gestureFixture() {
  const frames = new Map();
  let identity = 0;
  const browser = Object.assign(new EventTarget(), {
    requestAnimationFrame(callback) { frames.set(++identity, callback); return identity; },
    cancelAnimationFrame(id) { frames.delete(id); },
  });
  const document = Object.assign(new EventTarget(), { defaultView: browser });
  const root = Object.assign(new EventTarget(), { ownerDocument: document });
  const snapshots = [];
  const surface = observeDocumentSelection(root, () => snapshots.push(surface.selecting));
  const send = (target, type, properties = {}) => target.dispatchEvent(Object.assign(new Event(type), properties));
  const flush = () => { const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(callback => callback()); };
  return { root, document, browser, surface, snapshots, send, flush, frames };
}

test('native drag stays suppressed through selection changes and finishes after an outside release', () => {
  const f = gestureFixture();
  f.send(f.root, 'pointerdown', { button: 0, isPrimary: true, pointerId: 4 });
  assert.deepEqual(f.snapshots, [true]);
  f.send(f.document, 'selectionchange');
  f.send(f.document, 'selectionchange');
  assert.equal(f.frames.size, 1);
  f.flush();
  assert.equal(f.snapshots.at(-1), true);
  f.send(f.document, 'pointerup', { pointerId: 9 });
  assert.equal(f.surface.selecting, true);
  f.send(f.document, 'pointerup', { pointerId: 4 });
  assert.equal(f.surface.selecting, false);
  assert.equal(f.snapshots.at(-1), true);
  f.flush();
  assert.equal(f.snapshots.at(-1), false);
  f.surface.destroy();
});

test('keyboard selection, cancellation, focus loss and disposal leave no stuck gesture or callback', () => {
  const f = gestureFixture();
  f.send(f.root, 'pointerdown', { button: 2, isPrimary: true, pointerId: 1 });
  assert.equal(f.surface.selecting, false);
  f.send(f.document, 'selectionchange');
  f.flush();
  assert.deepEqual(f.snapshots, [false]);
  f.send(f.root, 'pointerdown', { button: 0, isPrimary: true, pointerId: 1 });
  f.send(f.document, 'pointercancel', { pointerId: 1 });
  f.flush();
  assert.equal(f.surface.selecting, false);
  f.send(f.root, 'pointerdown', { button: 0, isPrimary: true, pointerId: 2 });
  f.send(f.browser, 'blur');
  assert.equal(f.surface.selecting, false);
  f.send(f.document, 'scroll');
  f.surface.destroy();
  const count = f.snapshots.length;
  f.flush();
  f.send(f.document, 'selectionchange');
  f.send(f.root, 'pointerdown', { button: 0, isPrimary: true, pointerId: 3 });
  assert.equal(f.snapshots.length, count);
  assert.equal(f.frames.size, 0);
});

test('reading and editing use the native range, scroll viewport and fixed toolbar boundary', () => {
  const inside = {}, outside = {};
  const range = { commonAncestorContainer: inside, getBoundingClientRect: () => ({ left: 250, right: 550, top: 250, bottom: 280 }) };
  const selection = { rangeCount: 1, isCollapsed: false, toString: () => '选中文字', getRangeAt: () => range };
  const port = { getBoundingClientRect: () => ({ left: 100, right: 900, top: 80, bottom: 600 }) };
  const toolbar = { getBoundingClientRect: () => ({ bottom: 130 }) };
  let hidden = false;
  const root = {
    ownerDocument: { defaultView: { innerWidth: 1000, innerHeight: 700 }, getSelection: () => selection },
    closest: selector => selector.includes('hidden') ? (hidden ? {} : null) : port,
    querySelector: selector => selector === '.ProseMirror' ? { contains: node => node === inside } : toolbar,
  };
  assert.deepEqual(documentSelectionToolbarPosition(root, 300, 40), { left: 250, top: 202 });
  toolbar.getBoundingClientRect = () => ({ bottom: 220 });
  assert.equal(documentSelectionToolbarPosition(root, 300, 40), null);
  toolbar.getBoundingClientRect = () => ({ bottom: 130 });
  range.commonAncestorContainer = outside;
  assert.equal(documentSelectionToolbarPosition(root, 300, 40), null);
  range.commonAncestorContainer = inside;
  selection.isCollapsed = true;
  assert.equal(documentSelectionToolbarPosition(root, 300, 40), null);
  selection.isCollapsed = false;
  hidden = true;
  assert.equal(documentSelectionToolbarPosition(root, 300, 40), null);
});

test('block feedback is scoped per host and never writes into editable block nodes', () => {
  const styles = [], classes = new Set();
  const root = {
    classList: { add: value => classes.add(value), remove: value => classes.delete(value) },
    ownerDocument: {
      head: { append: element => styles.push(element) },
      createElement: () => ({ textContent: '', remove() { styles.splice(styles.indexOf(this), 1); } }),
    },
  };
  const first = new DocumentBlockHighlight(root), second = new DocumentBlockHighlight(root);
  first.hover(7);
  second.hover(8);
  assert.equal(classes.size, 2);
  assert.match(styles[0].textContent, /data-block-id="7"/);
  assert.doesNotMatch(styles[0].textContent, /data-block-id="8"/);
  first.locate(7);
  assert.match(styles[0].textContent, /outline:/);
  first.hover(null);
  assert.doesNotMatch(styles[0].textContent, /background-color/);
  first.locate(null);
  assert.equal(styles[0].textContent, '');
  first.destroy();
  assert.equal(styles.length, 1);
  assert.equal(classes.size, 1);
  second.destroy();
  assert.equal(styles.length, 0);
  assert.equal(classes.size, 0);
});
