import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ApiUnknown } from '../src/api/client.ts';
import { RepositoryRegistrationOwner } from '../src/code-tasks/settings/repository-registration-owner.ts';

const key = '00000000-0000-4000-8000-000000000001';
const path = '/api/v1/code-repositories';
const fields = { name: '仓库', root_path: 'C:\\owned' };
const accepted = {
  original_receipt: {
    original_http_status: 202,
    original_outcome: { success: true, data: {
      resource_kind: 'REPOSITORY', resource_id: 9, operation_id: 4, operation_status: 'PENDING',
    } },
    operation_id: 4, task_id: null, testing_task_id: null,
  },
};
const operation = (status, changes = {}) => ({
  id: 4, resource_id: 9, idempotency_key: key, operation_type: 'REGISTER_REPOSITORY', status,
  ...changes,
});

function make(options = {}) {
  const writes = [];
  const lookup = [];
  const values = new Map();
  const recovery = {
    store: {
      origin: 'http://localhost:5173',
      receipt: options.receipt ?? (async () => null),
    },
    stageIntent: async (target, input) => {
      writes.push([target, input]);
      return { kind: 'PREPARED', record: { key, record_revision: 1 } };
    },
    send: options.send ?? (async () => accepted),
  };
  const api = {
    repositoryOperation: async (id, signal) => {
      lookup.push([id, signal]);
      return { data: options.read?.() ?? operation('SUCCEEDED') };
    },
  };
  const storage = { getItem: (id) => values.get(id) ?? null, setItem: (id, value) => values.set(id, value) };
  const owner = new RepositoryRegistrationOwner(api, recovery, storage);
  owner.resume();
  owner.edit('name', fields.name);
  owner.edit('root_path', fields.root_path);
  return { owner, writes, lookup, api, recovery, storage };
}

test('202 binds the original without clearing its draft or opening the reserved repository', async () => {
  const { owner, writes, lookup } = make();
  await owner.submit();
  assert.deepEqual(writes, [[path, fields]]);
  assert.deepEqual(owner.getSnapshot().fields, fields);
  assert.deepEqual(owner.getSnapshot().original, { key, operationId: 4, repositoryId: 9 });
  assert.equal(owner.getSnapshot().operation, null);
  assert.deepEqual(lookup, []);
  await owner.submit();
  assert.equal(writes.length, 1);
  assert.throws(() => owner.observeOperation(operation('SUCCEEDED', { resource_id: 17 })));
  assert.equal(owner.getSnapshot().commandKey, key);
  await owner.read(null);
  assert.equal(owner.getSnapshot().operation.status, 'SUCCEEDED');
  assert.deepEqual(owner.getSnapshot().fields, { name: '', root_path: '' });
  owner.edit('name', '后来输入');
  owner.observeOperation(operation('SUCCEEDED'));
  assert.equal(owner.getSnapshot().fields.name, '后来输入');
});

test('after reload a late local receipt from the hidden section cannot publish or read; the new visibility can', async () => {
  let resolve;
  let first = true;
  const terminal = { path, key, operation_id: 4, http_status: 202 };
  const fixture = make({
    send: async () => { throw new ApiUnknown(true); },
    receipt: () => {
      if (!first) return Promise.resolve(terminal);
      first = false;
      return new Promise((done) => { resolve = done; });
    },
    read: () => operation('FAILED'),
  });
  await fixture.owner.submit();
  assert.equal(fixture.owner.getSnapshot().original, null);
  fixture.owner.dispose();
  const resumed = new RepositoryRegistrationOwner(fixture.api, fixture.recovery, fixture.storage);
  resumed.resume();
  const retired = resumed.restoreCompletion([]);
  resumed.pause();
  resumed.resume();
  resolve(terminal);
  await retired;
  assert.deepEqual(fixture.lookup, []);
  assert.deepEqual(resumed.getSnapshot().fields, fields);
  await resumed.restoreCompletion([]);
  assert.equal(fixture.lookup.length, 1);
  assert.equal(resumed.getSnapshot().operation.status, 'FAILED');
  assert.equal(resumed.getSnapshot().commandKey, null);
  assert.deepEqual(resumed.getSnapshot().fields, fields);
});
