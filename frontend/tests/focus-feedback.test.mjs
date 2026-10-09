import {test} from 'node:test';
import assert from 'node:assert/strict';
import {installFocusFeedback} from '../src/shared/focus-feedback.ts';

function fixture(previous = null) {
  const attributes = new Map(previous === null ? [] : [['data-focus-input', previous]]);
  const document = new EventTarget();
  document.documentElement = {
    getAttribute: name => attributes.get(name) ?? null,
    setAttribute: (name, value) => attributes.set(name, value),
    removeAttribute: name => attributes.delete(name),
  };
  const key = (value, options = {}) => document.dispatchEvent(Object.assign(new Event('keydown'), {
    key: value, isComposing: false, altKey: false, ctrlKey: false, metaKey: false, ...options,
  }));
  return {document, key, mode: () => attributes.get('data-focus-input')};
}

test('pointer focus and typing stay quiet; keyboard navigation restores the ring before focus moves', () => {
  const f = fixture(), release = installFocusFeedback(f.document);
  assert.equal(f.mode(), 'keyboard');
  f.document.dispatchEvent(new Event('pointerdown'));
  assert.equal(f.mode(), 'pointer');
  f.key('a');
  f.key('Enter', {isComposing: true});
  f.key('Tab', {ctrlKey: true});
  assert.equal(f.mode(), 'pointer');
  f.key('Tab', {shiftKey: true});
  assert.equal(f.mode(), 'keyboard');
  release();
});

test('keyboard dialog commands restore the ring; cleanup restores previous state and removes listeners', () => {
  const f = fixture('previous'), release = installFocusFeedback(f.document);
  f.document.dispatchEvent(new Event('pointerdown'));
  f.key('Escape');
  assert.equal(f.mode(), 'keyboard');
  release();
  assert.equal(f.mode(), 'previous');
  f.document.dispatchEvent(new Event('pointerdown'));
  f.key('Enter');
  assert.equal(f.mode(), 'previous');
  const fresh = fixture(), dispose = installFocusFeedback(fresh.document);
  dispose();
  assert.equal(fresh.mode(), undefined);
});
