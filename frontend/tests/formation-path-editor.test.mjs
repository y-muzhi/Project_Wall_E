import { test } from 'node:test';
import assert from 'node:assert/strict';
import { FormationPathEditor } from '../src/formation/path-editor.ts';
import { FormationDrafts } from '../src/formation/drafts.ts';
const settle = () => new Promise((done) => setImmediate(done));
function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function rig() {
  const memory = new Map(),
    listeners = new Set(),
    reads = [],
    previews = [],
    writes = [];
  let formationVersion = 1,
    discussionVersion = 2,
    contentVersion = 1;
  let state = { phase: 'IDLE', pending: [], receipt: null };
  const owner = {
    requirementId: 1,
    documentId: 2,
    revisionId: 3,
    writeReason: null,
    get discussionVersion() {
      return discussionVersion;
    },
    get contentVersion() {
      return contentVersion;
    },
    read: {
      getSnapshot: () => ({
        selected_step_ref: 's1',
        summary: {
          data: { formation_version: formationVersion, goal: { text: '目标' } },
        },
      }),
    },
    getSnapshot: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    refresh: async () => true,
    api: {
      getFormationStep: (_r, _d, ref, f, signal) => {
        const gate = deferred();
        reads.push({ ref, f, signal, gate });
        return gate.promise;
      },
      previewFormationPath: (_r, _d, body, query, signal) => {
        const gate = deferred();
        previews.push({ body, query, signal, gate });
        return gate.promise;
      },
    },
    execute: (command) => {
      const gate = deferred();
      writes.push({ command, gate });
      return gate.promise;
    },
    selectView: async () => {},
  };
  const drafts = new FormationDrafts(1, 2, 'http://localhost:5173', () => ({
    getItem: (key) => memory.get(key) ?? null,
    setItem: (key, value) => memory.set(key, value),
  }));
  drafts.load();
  const editor = new FormationPathEditor(owner, drafts);
  const rename = () => {
    editor.add('RENAME_STEP');
    const key = editor.getSnapshot().changes.at(-1).local_key;
    editor.update(key, { title: '完整名称' });
    editor.reason('核对设计后的调整');
    return key;
  };
  return {
    editor,
    drafts,
    owner,
    memory,
    reads,
    previews,
    writes,
    rename,
    changeVersion() {
      formationVersion++;
      discussionVersion++;
      contentVersion++;
      for (const listener of listeners) listener();
    },
    setState: (value) => {
      state = value;
    },
    dispose: () => editor.dispose(),
  };
}

test('editing invalidates an in-flight preview and ignores its late response even when fetch ignores abort', async () => {
  const f = rig();
  try {
    const key = f.rename(),
      pending = f.editor.preview();
    assert.equal(f.previews.length, 1);
    f.editor.update(key, { title: '较新的名称' });
    assert.equal(f.previews[0].signal.aborted, true);
    f.previews[0].gate.resolve({ data: { changed: true } });
    assert.equal(await pending, false);
    assert.equal(f.editor.canSave, false);
    assert.equal(f.editor.getSnapshot().changes[0].value.title, '较新的名称');
    assert.equal(f.editor.getSnapshot().preview, null);
  } finally {
    f.dispose();
  }
});

test('actual D/F/V changes preserve raw draft and require explicit rebase plus a new matching preview', async () => {
  const f = rig();
  try {
    f.rename();
    const original = f.editor.command().changes;
    let pending = f.editor.preview();
    f.previews[0].gate.resolve({ data: { changed: true } });
    await pending;
    assert.equal(f.editor.canSave, true);
    f.changeVersion();
    assert.equal(f.editor.getSnapshot().phase, 'STALE');
    assert.equal(f.editor.canSave, false);
    assert.equal(await f.editor.preview(), false);
    assert.deepEqual(f.editor.command().changes, original);
    assert.equal(await f.editor.rebase(), true);
    assert.equal(f.editor.getSnapshot().base_F, 2);
    assert.equal(f.editor.canSave, false);
    pending = f.editor.preview();
    assert.equal(f.previews[1].body.expected_discussion_version, 3);
    f.previews[1].gate.resolve({ data: { changed: true } });
    await pending;
    assert.equal(f.editor.canSave, true);
  } finally {
    f.dispose();
  }
});

test('changing a cancelled step aborts its old full-result read and removes only the old step routes', async () => {
  const f = rig();
  try {
    f.editor.add('CANCEL_STEP');
    const key = f.editor.getSnapshot().changes[0].local_key;
    f.reads[0].gate.resolve({
      data: { expected_results: [{ result_ref: 's1.o1' }, { result_ref: 's1.o2' }] },
    });
    await settle();
    assert.deepEqual(
      f.editor.getSnapshot().result_routes.map((r) => r.from_result_ref),
      ['s1.o1', 's1.o2'],
    );
    f.editor.updateRoute('s1.o1', { disposition: 'NOT_REQUIRED', reason: '原成果不再需要' });
    f.editor.update(key, { step_ref: 's2' });
    assert.equal(f.reads[0].signal.aborted, true);
    assert.deepEqual(f.editor.getSnapshot().result_routes, []);
    f.editor.update(key, { step_ref: 's3' });
    assert.equal(f.reads[1].signal.aborted, true);
    f.reads[1].gate.resolve({ data: { expected_results: [{ result_ref: 's2.o1' }] } });
    f.reads[2].gate.resolve({ data: { expected_results: [{ result_ref: 's3.o1' }] } });
    await settle();
    assert.deepEqual(
      f.editor.getSnapshot().result_routes.map((r) => r.from_result_ref),
      ['s3.o1'],
    );
    f.editor.remove(key);
    assert.deepEqual(f.editor.getSnapshot().result_routes, []);
  } finally {
    f.dispose();
  }
});

test('the original save is immutable and cannot clear edits made while its result was pending', async () => {
  const f = rig();
  try {
    const key = f.rename();
    const preview = f.editor.preview();
    f.previews[0].gate.resolve({ data: { changed: true } });
    await preview;
    const saving = f.editor.save();
    assert.equal(f.writes[0].command.changes[0].title, '完整名称');
    f.editor.update(key, { title: '保存期间编辑的新名称' });
    f.writes[0].gate.resolve(true);
    assert.equal(await saving, true);
    assert.equal(f.editor.getSnapshot().phase, 'STALE');
    assert.equal(f.editor.getSnapshot().changes[0].value.title, '保存期间编辑的新名称');
    assert.equal(f.drafts.readPath().changes[0].title, '保存期间编辑的新名称');
    assert.equal(f.writes[0].command.changes[0].title, '完整名称');
  } finally {
    f.dispose();
  }
});

test('a cold raw draft restores incomplete business fields but cannot reuse a previous preview or save', () => {
  const f = rig();
  let cold;
  try {
    f.editor.add('ADD_STEP');
    cold = new FormationPathEditor(f.owner, f.drafts);
    assert.equal(cold.getSnapshot().phase, 'STALE');
    assert.equal(cold.getSnapshot().changes[0].value.title, '');
    assert.notEqual(cold.validation, null);
    assert.equal(cold.canSave, false);
    assert.equal(cold.getSnapshot().preview, null);
    assert.equal(f.writes.length, 0);
  } finally {
    cold?.dispose();
    f.dispose();
  }
});

test('disposing the editor aborts its own cancellation reads and does not mutate the retained draft', async () => {
  const f = rig();
  f.editor.add('CANCEL_STEP');
  const bytes = [...f.memory.values()][0];
  f.dispose();
  assert.equal(f.reads[0].signal.aborted, true);
  f.reads[0].gate.resolve({ data: { expected_results: [{ result_ref: 's1.o1' }] } });
  await settle();
  assert.equal([...f.memory.values()][0], bytes);
});

test('switching a second cancellation preserves routes still owned by the first operation', async () => {
  const f = rig();
  try {
    f.editor.add('CANCEL_STEP');
    const first = f.editor.getSnapshot().changes[0].local_key;
    f.reads[0].gate.resolve({ data: { expected_results: [{ result_ref: 's1.o1' }] } });
    await settle();
    f.editor.updateRoute('s1.o1', { disposition: 'NOT_REQUIRED', reason: '已核对的第一项去向' });
    f.editor.add('CANCEL_STEP');
    const second = f.editor.getSnapshot().changes[1].local_key;
    f.reads[1].gate.resolve({ data: { expected_results: [{ result_ref: 's1.o1' }] } });
    await settle();
    f.editor.update(second, { step_ref: 's2' });
    assert.equal(f.editor.getSnapshot().result_routes[0]?.reason, '已核对的第一项去向');
    f.reads[2].gate.resolve({ data: { expected_results: [{ result_ref: 's2.o1' }] } });
    await settle();
    assert.deepEqual(
      f.editor.getSnapshot().result_routes.map((row) => row.from_result_ref),
      ['s1.o1', 's2.o1'],
    );
    f.editor.remove(second);
    assert.deepEqual(
      f.editor.getSnapshot().result_routes.map((row) => row.from_result_ref),
      ['s1.o1'],
    );
    assert.equal(f.editor.getSnapshot().cancellations[second], undefined);
    f.editor.remove(first);
    assert.deepEqual(f.editor.getSnapshot().result_routes, []);
  } finally {
    f.dispose();
  }
});
test('removing a draft duplicate and clearing a target retains other choices and clears obsolete target facts', async () => {
  const f = rig();
  try {
    f.editor.add('CANCEL_STEP');
    const first = f.editor.getSnapshot().changes[0].local_key;
    f.reads[0].gate.resolve({ data: { expected_results: [{ result_ref: 's1.o1' }] } });
    await settle();
    f.editor.updateRoute('s1.o1', { disposition: 'NOT_REQUIRED', reason: '保留用户说明' });
    f.editor.add('CANCEL_STEP');
    const second = f.editor.getSnapshot().changes[1].local_key;
    f.editor.remove(second);
    assert.equal(f.editor.getSnapshot().result_routes[0]?.reason, '保留用户说明');
    f.reads[1].gate.resolve({ data: { expected_results: [{ result_ref: 's1.o99' }] } });
    await settle();
    assert.equal(f.editor.getSnapshot().cancellations[second], undefined);
    f.editor.update(first, { step_ref: '' });
    assert.equal(f.editor.getSnapshot().cancellations[first]?.step, null);
    assert.deepEqual(f.editor.getSnapshot().result_routes, []);
  } finally {
    f.dispose();
  }
});
