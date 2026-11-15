import assert from 'node:assert/strict';
import test from 'node:test';
import { readWorkspaceRoute, workspacePath } from '../src/code-tasks/workspace-route.ts';

test('a file route round-trips the exact Unicode path and fixed comparison identity', () => {
  const filePath = 'src/历史 +%.txt';
  for (const route of [
    { tab: 'code', candidateId: 201, filePath },
    { tab: 'delivery', planId: 41, filePath },
  ]) {
    const url = new URL(workspacePath(31, route), 'http://localhost');
    assert.equal(url.pathname, '/code-tasks/31');
    assert.equal(url.searchParams.get('path'), filePath);
    assert.deepEqual(readWorkspaceRoute(url.search), route);
  }
});

test('file routes reject conflicting identities and unsafe paths', () => {
  const fixed = '?tab=code&candidate_id=201';
  for (const query of [
    '?tab=execution&operation_id=1&path=a.txt',
    '?tab=delivery&candidate_id=201&path=a.txt',
    fixed + '&path=a.txt&path=b.txt',
    fixed + '&candidate_id=202&path=a.txt',
    fixed + '&path=',
    ...['../a', '/a', 'c:/secret', 'a\\\\b', 'src/.git/config', 'src/COM1.txt'].map(
      (path) => fixed + '&path=' + encodeURIComponent(path),
    ),
  ]) {
    assert.equal(readWorkspaceRoute(query), null, query);
  }
});

test('the owner page is optional, canonical and compatible with fixed file scope', () => {
  assert.deepEqual(readWorkspaceRoute('?tab=execution&page=2&operation_id=9'), {
    tab: 'execution', page: 2, operationId: 9,
  });
  const file = { tab: 'delivery', planId: 41, filePath: 'src/first.ts', page: 4 };
  const url = new URL(workspacePath(31, file), 'http://localhost');
  assert.deepEqual(readWorkspaceRoute(url.search), file);
  assert.deepEqual(readWorkspaceRoute('?tab=usage&page=1'), {tab: 'usage'});
  assert.deepEqual(readWorkspaceRoute('?tab=code&path=a.txt'), {tab: 'code', filePath: 'a.txt'});
  assert.deepEqual(readWorkspaceRoute('?tab=delivery&path=a.txt'), {tab: 'delivery', filePath: 'a.txt'});
  for (const query of [
    '?tab=usage&page=01',
    '?tab=usage&page=0',
    '?tab=usage&page=1&page=2',
    '?tab=usage&page=9007199254740992',
    '?tab=testing&test_report_id=71&page=2',
  ]) assert.equal(readWorkspaceRoute(query), null);
});
