import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient } from '../src/api/client.ts';
import {
  freezeFormation,
  formationPending,
  formationReceipt,
  verifyFormationFrozen,
  formationPendingSize,
} from '../src/formation/command-model.ts';
import { nativeFormationCommand } from '../src/api/formation-commands.ts';
import { WalleApi } from '../src/api/walle.ts';
const origin = 'http://localhost:5173',
  key = '00000000-0000-4000-8000-000000000001';
async function pending(
  body = {
    document_id: 2,
    expected_discussion_version: 3,
    discussion_command: { type: 'FORMATION', action: 'SWITCH_STEP', step_ref: null },
  },
) {
  const client = new ApiClient(
    () => assert.fail('offline'),
    () => key,
  );
  const request = client.exportPrepared(
    client.prepare('PATCH', '/api/v1/requirements/1', body, {
      idempotent: true,
      success_status: 200,
    }),
  );
  const frozen = await freezeFormation(request, 1, 2, key, origin);
  return {
    ...frozen,
    schema_version: 5,
    recovery_mode: 'REPLAY_ORIGINAL',
    status: 'PREPARED',
    created_at: '2026-11-16T10:00:00.000Z',
    updated_at: '2026-11-16T10:00:00.000Z',
    submitted_at: null,
    dispatch_count: 0,
    dispatch_owner_id: null,
    record_revision: 1,
  };
}
test('record5 is a strict FORMATION branch; code-task semantics and malformed observations are refused', async () => {
  const row = await pending();
  assert.equal(formationPending(row, origin).status, 'PREPARED');
  for (const change of [
    { schema_version: 4 },
    { owner_module: 'CODING' },
    { task_id: null },
    { operation_id: 1 },
    { status: 'ACCEPTED' },
    { recovery_mode: 'QUERY_ONLY' },
    { dispatch_count: 1 },
    { record_revision: 0 },
    { origin: 'http://different.invalid' },
    { path: '/api/v1/code-tasks/1/start' },
    { method: 'POST' },
    { intent_key: 'PATCH /api/v1/requirements/1' },
    { updated_at: '2026-02-31T00:00:00.000Z' },
  ])
    assert.throws(() => formationPending({ ...row, ...change }, origin), TypeError);
});
test('body limit and metadata limit are separate; original bytes, identity and document binding are checked', async () => {
  const row = await pending({ document_id: 2, payload: '中'.repeat(30000) });
  assert.ok(formationPendingSize(row) > 65536);
  const fields = [
    'owner_module',
    'origin',
    'key',
    'method',
    'path',
    'identity_sha256',
    'body_sha256',
    'intent_key',
    'requirement_id',
    'document_id',
    'body_text',
  ];
  const frozen = Object.fromEntries(fields.map((k) => [k, row[k]]));
  await verifyFormationFrozen(frozen, origin);
  for (const change of [
    { body_text: row.body_text + ' ' },
    { body_sha256: 'a'.repeat(64) },
    { identity_sha256: 'b'.repeat(64) },
    { document_id: 3 },
  ])
    await assert.rejects(verifyFormationFrozen({ ...frozen, ...change }, origin), TypeError);
});
test('only known responses and never-sent cancellation form terminal receipts', async () => {
  const row = await pending();
  const fields = [
    'owner_module',
    'origin',
    'key',
    'method',
    'path',
    'identity_sha256',
    'body_sha256',
    'intent_key',
    'requirement_id',
    'document_id',
  ];
  const receipt = {
    ...Object.fromEntries(fields.map((k) => [k, row[k]])),
    schema_version: 5,
    final_state: 'CONFIRMED',
    http_status: 202,
    result_code: null,
    guide_run_id: 9,
    user_message_id: 10,
    event_ids: [],
    resolved_at: row.updated_at,
  };
  assert.equal(formationReceipt(receipt, origin).guide_run_id, 9);
  for (const change of [
    { final_state: 'CLOSED_UNEXECUTED' },
    { final_state: 'REJECTED' },
    { http_status: 500 },
    { task_id: 1 },
    { event_ids: [2, 2] },
    { event_ids: Array.from({ length: 15000 }, (_, n) => n + 1) },
    { final_state: 'CANCELLED_UNSENT', http_status: null },
    { final_state: 'KNOWN_REJECTED', http_status: 409, result_code: 'REQUEST_IN_PROGRESS' },
  ])
    assert.throws(() => formationReceipt({ ...receipt, ...change }, origin), TypeError);
});
test('native commands stay program-only and COMPLETE_STEP defaults permit empty dispositions', () => {
  const complete = {
    type: 'FORMATION',
    action: 'COMPLETE_STEP',
    step_ref: 's1',
    expected_definition_version: 2,
    expected_goal_version: 1,
    expected_content_version: 3,
    result_dispositions: [],
    issue_dispositions: [],
    branch_dispositions: [],
    next_step_ref: null,
  };
  assert.deepEqual(nativeFormationCommand(complete), complete);
  for (const command of [
    { ...complete, reason: 'extra' },
    { ...complete, step_ref: 'new_step_1' },
    { type: 'FORMATION', action: 'START_STEP', step_ref: null },
    {
      type: 'FORMATION',
      action: 'RESUME_BRANCH',
      step_ref: 's1',
      branch_ref: 'b1',
      expected_branch_status: 'OPEN',
      expected_branch_event_id: 2,
      enter_after_resume: true,
    },
  ])
    assert.throws(() => nativeFormationCommand(command));
});
test('restored API preparation reuses the original key and exact body without minting a new command', async () => {
  const row = await pending();
  let sends = 0;
  const client = new ApiClient(
    async (_path, init) => {
      sends++;
      assert.equal(init.body, row.body_text);
      assert.equal(new Headers(init.headers).get('Idempotency-Key'), key);
      return new Response(
        JSON.stringify({
          success: true,
          data: {
            schema: 'formation_program_receipt_v21_1',
            processing: 'PROGRAM',
            requirement_id: 1,
            document_id: 2,
            discussion_version: 4,
            formation_version: 2,
            content_version: 1,
            operation: 'NATIVE_FORMATION',
            result: 'APPLIED',
            user_message_id: 5,
            effects: {
              content_changed: false,
              revision_id: null,
              formation_changed: true,
              proposal_disposition: null,
            },
            event_ids: [2],
            reference_map: [],
          },
          error: null,
          meta: { request_id: key },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    },
    () => assert.fail('restore minted a new key'),
  );
  const api = new WalleApi(client, null).forDocumentAssistant(2);
  const body = JSON.parse(row.body_text);
  const request = { method: row.method, path: row.path, key: row.key, body: row.body_text };
  await api
    .prepareFormationCommand(
      1,
      { expected_discussion_version: 3, discussion_command: body.discussion_command },
      request,
    )
    .submit();
  assert.equal(sends, 1);
  assert.throws(() =>
    api.prepareFormationCommand(
      1,
      { expected_discussion_version: 4, discussion_command: body.discussion_command },
      request,
    ),
  );
});
