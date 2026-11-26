import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readOperationDetail } from '../src/guide/saved-operation.ts';

const receipt = { run_id: 53, state: 'SAVED', document_id: 17, base_content_version: 1, saved_content_version: 2 };
const effect = { document_id: 17, before_content_version: 1, after_content_version: 2, revision_id: 22 };
const owner = (id, source_content_version) => ({ id, source_content_version, requirement_id: 5, document_id: 17 });
const heading = { id: 4, markdown: '# 节\n', section: [] };
const adjacent = { id: 6, markdown: '# 相邻节\n', section: [] };

function fixture() {
  const requested = [];
  const api = {
    async getGuideRun(id) {
      assert.equal(id, 53);
      return { data: { id, requirement_id: 5, application_result: 'APPLIED', document_effect: effect } };
    },
    async getRevision(id) {
      requested.push(id);
      if (id === 22) return { data: owner(id, 2) };
      assert.equal(id, 20);
      return { data: owner(id, 1) };
    },
    async listRevisions(req, doc, page) {
      assert.equal(req, 5);
      assert.equal(doc, 17);
      return {
        data: { items: page === 1 ? [owner(28, 8), owner(22, 2)] : [owner(20, 1)] },
        meta: { pagination: { page, total_pages: 2 } },
      };
    },
    revisionBlocks(revision) {
      return [heading, { id: 5, markdown: revision.id === 22 ? '已填写\n' : '占位\n', section: ['节'] }, adjacent];
    },
  };
  return { api, requested };
}

test('reads the exact saved run revisions through pagination, even after new versions exist', async () => {
  const { api, requested } = fixture();
  const result = await readOperationDetail(api, 5, receipt, 'COMPARE', new AbortController().signal);
  assert.deepEqual(requested, [22, 20]);
  assert.deepEqual(result.changes, [{ section: ['节'], removed: '占位', added: '已填写' }]);
});

test('saved receipt refuses a mismatched document or version', async () => {
  const { api } = fixture();
  api.getRevision = async () => ({ data: { ...owner(22, 2), document_id: 18 } });
  await assert.rejects(readOperationDetail(api, 5, receipt, 'VERSION', new AbortController().signal), /版本归属/);
});
