import { acceptedReplyTarget } from '../src/formation/accepted-target.ts';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { RequirementGuideComposer } from '../src/guide/composer.ts';
import { ComposerDrafts } from '../src/guide/composer-drafts.ts';
import { FormationWorkspace } from '../src/formation/workspace.ts';
import { FormationDrafts } from '../src/formation/drafts.ts';
import { FormationPreferences } from '../src/formation/preferences.ts';
import { FormationUnsentError } from '../src/formation/command-recovery.ts';
import { ApiRejected, ApiUnknown } from '../src/api/client.ts';
const origin = 'http://localhost:5173';
const selection = (step) => ({
  discussion_step_ref: step,
  discussion_branch_ref: null,
  branch_intent: null,
  branch_resume_basis: null,
});
const summary = () => ({
  document_id: 2,
  view_schema: 'formation_read_v21_1',
  exists: true,
  formation_version: 1,
  goal: { version: 1, text: '设计目标', source_refs: [] },
  current_step_ref: 's1',
  active_branch_ref: null,
  counts: {
    steps: { PLANNED: 2, IN_PROGRESS: 0, PAUSED: 0, COMPLETED: 0, CANCELLED: 0 },
    branches: { OPEN: 0, RESOLVED: 1, DEFERRED: 0, DROPPED: 0 },
    issues: { OPEN: 0, RESOLVED: 0, DEFERRED: 0, DROPPED: 0 },
    proposals: { PENDING: 0, DEFERRED: 0, APPLIED: 0, SUPERSEDED: 0 },
    pending_review_artifacts: 0,
  },
  availability: [],
});
const store = () => {
  const values = new Map();
  return {
    values,
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
};
const settle = () => new Promise((resolve) => setImmediate(resolve));
function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
const storedBranch = {
  discussion_step_ref: 's1', discussion_branch_ref: 'b1', branch_intent: 'RESUME',
  branch_resume_basis: { expected_branch_status: 'RESOLVED', expected_branch_event_id: 23 },
};
function rig(initialTarget = null) {
  const storage = store(),
    gate = deferred(),
    calls = [],
    actual = {
      requirement: {
        id: 1,
        discussion_version: 3,
        document_work_state: 'IDLE',
        status: 'PLANNING',
      },
      selected_document_id: 2,
      current: {
        id: 2,
        name: '设计',
        content_version: 1,
        current_revision_id: 1,
        archived_at: null,
      },
      documents: [
        { id: 2, name: '设计', content_version: 1, current_revision_id: 1, archived_at: null },
      ],
      activity: { kind: 'IDLE' },
      discussion: null,
    };
  let lose = false,
    unsent = false;
  let lastIntent = null;
  const api = {
    getRequirementDetail: async () => ({
      data: {
        ...actual,
        discussion: { binding: { source_refs: [] }, formation_summary: summary() },
      },
    }),
    prepareFormationDiscuss: (_id, body) => {
      const frozen = structuredClone(body);
      calls.push(frozen);
      return {
        submit: async () => {
          await gate.promise;
          if (lose) {
            lose = false;
            throw new ApiUnknown(true);
          }
          return {
            data: {
              processing: 'MODEL',
              guide_run_id: 9,
              user_message_id: 10,
              accepted_target: {
                ...frozen.target,
                branch_intent:
                  frozen.target.branch_intent === 'RESUME' ? 'ENTER' : frozen.target.branch_intent,
                branch_resume_basis: null,
              },
            },
            status: 202,
            meta: {},
          };
        },
      };
    },
    prepareCreateGuide: () => assert.fail('formation used legacy target'),
    prepareFormationCommand: () => assert.fail('draft target dispatched an idle command'),
    getGuideRun: async () => ({
      data: {
        id: 9,
        requirement_id: 1,
        document_id: 2,
        operation: 'DISCUSS',
        parent_guide_run_id: null,
        status: 'FAILED',
        ...(calls[0] === undefined
          ? {}
          : {
              accepted_target: {
                ...calls[0].target,
                branch_intent:
                  calls[0].target.branch_intent === 'RESUME'
                    ? 'ENTER'
                    : calls[0].target.branch_intent,
                branch_resume_basis: null,
              },
            }),
      },
    }),
    listMessages: async () => ({ data: { items: [] } }),
  };
  const recovery = {
    store: { origin },
    list: async () => [],
    wrap: (action, intent) => {
      lastIntent = intent;
      return {
        submit: () => {
          if (unsent) throw new FormationUnsentError('storage unavailable; never sent');
          return action.submit();
        },
      };
    },
    dispose: () => {},
  };
  const drafts = new FormationDrafts(1, 2, origin, () => storage),
    preferences = new FormationPreferences(1, 2, () => storage);
  if (initialTarget) drafts.save(initialTarget,crypto.randomUUID());
  const workspace = new FormationWorkspace(
    actual,
    api,
    async () => actual,
    async () => {},
    async () => {},
    { recovery, drafts, preferences },
  );
  workspace.setView(false, false);
  const composer = new RequirementGuideComposer(
    actual,
    api,
    async () => actual,
    async () => {},
    async () => {},
    async () => {},
    new ComposerDrafts(() => storage, 2),
  );
  composer.attachFormation(workspace);
  composer.setAvailable(true);
  return {
    workspace,
    composer,
    gate,
    calls,
    storage,
    actual,
    api,
    recovery,
    lastIntent: () => lastIntent,
    lose: () => {
      lose = true;
    },
    unsent: () => {
      unsent = true;
    },
    dispose: () => {
      composer.dispose();
      workspace.dispose();
    },
  };
}
test('accepted old target and reconciliation cannot erase newer next-target or newly typed input', async () => {
  const f = rig();
  try {
    f.composer.change('原轮输入');
    const sending = f.composer.submit();
    await settle();
    assert.equal(f.composer.getSnapshot().phase, 'SUBMITTING');
    assert.deepEqual(f.calls[0].target, selection('s1'));
    f.workspace.setView(false, false, 'COMPOSER');
    f.workspace.completedNext('s2', f.workspace.getSnapshot().selection_epoch);
    f.composer.change('下一轮新输入');
    f.gate.resolve();
    assert(await sending);
    assert.equal(f.composer.getSnapshot().instruction, '下一轮新输入');
    assert.deepEqual(f.workspace.getSnapshot().next_target, selection('s2'));
    const frozenRun = (await f.api.getGuideRun(9)).data;
    assert.deepEqual(frozenRun.accepted_target, selection('s1'));
    assert.equal(acceptedReplyTarget(frozenRun), '本条回复：步骤 s1');
    assert.match(f.storage.getItem('walle:v1.5:document-composer:1:2'), /下一轮新输入/);
  } finally {
    f.dispose();
  }
});
test('persisted RESUME proof is consumed on accepted receipt even when the model run then fails', async () => {
  const f = rig(storedBranch);
  try {
    f.workspace.observeDiscussion({ formation_summary: summary() });
    f.workspace.setView(false, false, 'COMPOSER');
    f.composer.change('继续支线');
    const sending = f.composer.submit();
    await settle();
    assert.equal(f.calls[0].target.branch_intent, 'RESUME');
    assert.deepEqual(f.calls[0].target.branch_resume_basis, {
      expected_branch_status: 'RESOLVED',
      expected_branch_event_id: 23,
    });
    f.gate.resolve();
    assert(await sending);
    assert.equal(f.workspace.selection.branch_intent, 'ENTER');
    assert.equal(f.workspace.selection.branch_resume_basis, null);
    assert.equal(f.calls.length, 1);
  } finally {
    f.dispose();
  }
});
test('unknown replay preserves original prepared target while next-round choices and text remain independent', async () => {
  const f = rig();
  try {
    f.lose();
    f.composer.change('冻结原轮');
    const first = f.composer.submit();
    await settle();
    f.gate.resolve();
    assert.equal(await first, false);
    assert.equal(f.composer.getSnapshot().phase, 'UNKNOWN');
    f.workspace.setView(false, false, 'COMPOSER');
    f.workspace.completedNext('s2', f.workspace.getSnapshot().selection_epoch);
    f.composer.change('后续草稿');
    assert(await f.composer.recover());
    assert.equal(f.calls.length, 1);
    assert.deepEqual(f.calls[0].target, selection('s1'));
    assert.deepEqual(f.workspace.selection, selection('s2'));
    assert.equal(f.composer.getSnapshot().instruction, '后续草稿');
  } finally {
    f.dispose();
  }
});
test('switching to write during formation preflight keeps the original discussion and the next draft', async () => {
  const f = rig();
  try {
    const binding = await f.api.getRequirementDetail();
    f.workspace.observeDiscussion(binding.data.discussion);
    const pendingBinding = deferred();
    f.api.getRequirementDetail = () => pendingBinding.promise;

    f.composer.change('原讨论指令');
    const sending = f.composer.submit();
    await settle();
    f.composer.choose('REVISE');
    f.composer.change('下一轮写入草稿');
    pendingBinding.resolve(binding);
    f.gate.resolve();

    assert.equal(await sending, true);
    assert.equal(f.calls.length, 1);
    assert.equal(f.calls[0].operation, 'DISCUSS');
    assert.equal(f.calls[0].instruction, '原讨论指令');
    assert.deepEqual(f.calls[0].target, selection('s1'));
    assert.equal(f.composer.getSnapshot().action, 'REVISE');
    assert.equal(f.composer.getSnapshot().instruction, '下一轮写入草稿');
  } finally {
    f.dispose();
  }
});
test('pre-send durable refusal remains unsent ERROR and preserves the message rather than inventing UNKNOWN', async () => {
  const f = rig();
  try {
    f.unsent();
    f.composer.change('不能丢的输入');
    const sending = f.composer.submit();
    await settle();
    assert.equal(await sending, false);
    assert.equal(f.composer.getSnapshot().phase, 'ERROR');
    assert.equal(f.composer.getSnapshot().instruction, '不能丢的输入');
    assert.equal(f.calls.length, 1);
  } finally {
    f.dispose();
  }
});
test('corrupt local drafts and preferences are retained, never overwritten by a new in-memory selection', () => {
  const memory = store(),
    key = 'walle:v2.1:formation-draft:1:2',
    preference = 'walle:v2.1:formation-view:1:2';
  const raw = '{"schema_version":999,"private_user_input":"keep"}';
  memory.setItem(key, raw);
  memory.setItem(preference, raw);
  const drafts = new FormationDrafts(1, 2, origin, () => memory);
  assert.equal(drafts.load().target, null);
  assert.notEqual(drafts.save(selection('s2'), crypto.randomUUID()), null);
  assert.equal(memory.getItem(key), raw);
  const prefs = new FormationPreferences(1, 2, () => memory);
  assert.notEqual(prefs.warning, null);
  assert.notEqual(prefs.save({ ...prefs.initial, selected_step_ref: 's2' }), null);
  assert.equal(memory.getItem(preference), raw);
});

for (const laterChoice of [false, true])
  test(
    'cold recovery only consumes its persisted intent; later follows current focus=' + laterChoice,
    async () => {
      const f = rig(storedBranch);
      let cold;
      try {
        f.workspace.observeDiscussion({ formation_summary: summary() });
        f.workspace.setView(false, false, 'COMPOSER');
        f.lose();
        f.composer.change('继续原支线');
        const sending = f.composer.submit();
        await settle();
        f.gate.resolve();
        await sending;
        const epoch = f.workspace.getSnapshot().selection_epoch;
        assert.equal(epoch, f.lastIntent());
        if (laterChoice) f.workspace.followServerFocus();
        const persistedEpoch = f.workspace.getSnapshot().selection_epoch;
        assert.equal(persistedEpoch === epoch, !laterChoice);
        const accepted = {
          ...f.calls[0].target,
          branch_intent: 'ENTER',
          branch_resume_basis: null,
        };
        const recovery = {
          store: {
            origin,
            detail: async () => ({ intent_key: epoch, path: '/api/v1/requirements/1/guide-runs' }),
          },
          list: async () => [],
          replay: async () => ({
            data: {
              processing: 'MODEL',
              guide_run_id: 9,
              user_message_id: 10,
              accepted_target: accepted,
            },
          }),
          dispose: () => {},
        };
        cold = new FormationWorkspace(
          f.actual,
          f.api,
          async () => f.actual,
          async () => {},
          async () => {},
          {
            recovery,
            drafts: new FormationDrafts(1, 2, origin, () => f.storage),
            preferences: new FormationPreferences(1, 2, () => f.storage),
          },
        );
        cold.setView(false, false);
        cold.observeDiscussion({ formation_summary: summary() });

        if (laterChoice) assert.notEqual(cold.getSnapshot().selection_epoch, epoch);
        else assert.equal(cold.getSnapshot().selection_epoch, persistedEpoch);
        const replayKey = crypto.randomUUID();
        const first = cold.replay(replayKey);
        assert.equal(cold.replay(replayKey), first);
        assert.equal(await cold.replay(crypto.randomUUID()), false);
        assert(await first);
        assert.equal(cold.selection.branch_intent, laterChoice ? null : 'ENTER');
        assert.deepEqual(
          cold.selection.branch_resume_basis,
          null,
        );
      } finally {
        cold?.dispose();
        f.dispose();
      }
    },
  );

test('completion next-target only replaces the captured selection, leaving a later explicit choice intact', async () => {
  const f = rig();
  try {
    f.workspace.observeDiscussion({ formation_summary: summary() });
    f.workspace.setView(false, false, 'COMPOSER');
    const original = f.workspace.getSnapshot().selection_epoch;
    f.workspace.completedNext('s2', original);
    assert.equal(f.workspace.selection.discussion_step_ref, 's2');
    const captured = f.workspace.getSnapshot().selection_epoch;
    f.workspace.completedNext('s3', f.workspace.getSnapshot().selection_epoch);
    f.workspace.completedNext('s2', captured);
    assert.equal(f.workspace.selection.discussion_step_ref, 's3');
    assert.equal(f.calls.length, 0);
  } finally {
    f.dispose();
  }
});
test('adjusting an original section proposal preserves input and binds the current document to that original section', () => {
  const f = rig();
  try {
    f.composer.change('保留用户的后续说明');
    assert(
      f.composer.adjustProposal({ message_id: 8, card_key: 'proposal-1' }, 'STAGED_WRITE', {
        scope_type: 'SECTION',
        scope_ref: { heading_block_id: 12 },
      }),
    );
    const state = f.composer.getSnapshot();
    assert.equal(state.instruction, '保留用户的后续说明');
    assert.deepEqual(state.target.scope, { scope_type: 'SECTION', scope_ref: { block_id: 12 } });
    assert.equal(state.target.document_id, 2);
    assert.deepEqual(state.formation_proposal, {
      proposal: { message_id: 8, card_key: 'proposal-1' },
      intent: 'ADJUST_WRITE',
    });
    assert.equal(f.calls.length, 0);
    f.composer.clearProposalSelection();
    assert.equal(f.composer.getSnapshot().instruction, '保留用户的后续说明');
  } finally {
    f.dispose();
  }
});

test('an uninitialized formation selects the whole document locally without an invalid SWITCH_STEP write', async () => {
  const f = rig();
  try {
    f.workspace.observeDiscussion({
      formation_summary: {
        ...summary(),
        exists: false,
        formation_version: null,
        goal: null,
        current_step_ref: null,
        active_branch_ref: null,
      },
    });
    assert.equal(f.workspace.getSnapshot().mode, 'FORMATION');
    assert.deepEqual(f.workspace.selection, selection(null));
    assert.equal(f.workspace.getSnapshot().phase, 'IDLE');
    assert.equal(f.calls.length, 0);
    assert.deepEqual((await f.workspace.captureTarget()).selection, selection(null));
  } finally {
    f.dispose();
  }
});

for (const kind of ['RESUME_BRANCH', 'COMPLETE_STEP'])
  for (const laterChoice of [false, true])
    test(
      'cold native selection receipt ' + kind + ' preserves later choice=' + laterChoice,
      async () => {
        const f = rig(storedBranch);
        let cold;
        try {
          f.workspace.observeDiscussion({ formation_summary: summary() });
          f.workspace.setView(false, false, 'COMPOSER');
          const epoch = f.workspace.getSnapshot().selection_epoch;
          if (laterChoice) f.workspace.completedNext('s3', f.workspace.getSnapshot().selection_epoch);
          const command =
            kind === 'RESUME_BRANCH'
              ? {
                  type: 'FORMATION',
                  action: kind,
                  step_ref: 's1',
                  branch_ref: 'b1',
                  expected_branch_status: 'RESOLVED',
                  expected_branch_event_id: 23,
                  enter_after_resume: true,
                }
              : {
                  type: 'FORMATION',
                  action: kind,
                  step_ref: 's1',
                  expected_definition_version: 1,
                  expected_goal_version: 1,
                  expected_content_version: 1,
                  result_dispositions: [],
                  issue_dispositions: [],
                  branch_dispositions: [],
                  next_step_ref: 's2',
                };
          const recovery = {
            store: {
              origin,
              detail: async () => ({
                intent_key: epoch,
                method: 'PATCH',
                path: '/api/v1/requirements/1',
                body_text: JSON.stringify({
                  document_id: 2,
                  expected_discussion_version: 3,
                  discussion_command: command,
                }),
              }),
            },
            list: async () => [],
            dispose: () => {},
            replay: async () => ({
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
                user_message_id: 10,
                effects: {
                  content_changed: false,
                  revision_id: null,
                  formation_changed: true,
                  proposal_disposition: null,
                },
                event_ids: [24],
                reference_map: [],
              },
            }),
          };
          cold = new FormationWorkspace(
            f.actual,
            f.api,
            async () => f.actual,
            async () => {},
            async () => {},
            {
              recovery,
              drafts: new FormationDrafts(1, 2, origin, () => f.storage),
              preferences: new FormationPreferences(1, 2, () => f.storage),
            },
          );
          cold.setView(false, false);
          cold.observeDiscussion({ formation_summary: summary() });
          assert(await cold.replay(crypto.randomUUID()));
          if (laterChoice) assert.deepEqual(cold.selection, selection('s3'));
          else if (kind === 'RESUME_BRANCH') {
            assert.equal(cold.selection.branch_intent, 'ENTER');
            assert.equal(cold.selection.branch_resume_basis, null);
          } else assert.deepEqual(cold.selection, selection('s2'));
        } finally {
          cold?.dispose();
          f.dispose();
        }
      },
    );

test('progress uses the legacy read only when the server rejects the new projection fields', async () => {
  const h = rig();
  const original = h.api.getRequirementDetail;
  const limits = [];
  let unsupported = false;
  h.api.getRequirementDetail = async (...args) => {
    limits.push(args[4]);
    if (args[4] === undefined) return original(...args);
    if (!unsupported) throw new ApiUnknown(false);
    throw new ApiRejected('VALIDATION_FAILED', '未知查询参数', {
      field_errors: [{field: 'progress_limit', reason: 'UNKNOWN_FIELD', message: '参数未登记'}],
    }, 'test', 422);
  };
  try {
    assert.equal(await h.workspace.refresh(false), false);
    assert.deepEqual(limits, [3]);
    unsupported = true;
    assert.equal(await h.workspace.refresh(false), true);
    assert.deepEqual(limits, [3, 3, undefined]);
    assert.equal(h.workspace.getSnapshot().mode, 'FORMATION');
    assert.equal(h.workspace.getSnapshot().brief, null);
    assert.equal(await h.workspace.refresh(false), true);
    assert.equal(limits.at(-1), undefined);
  } finally {
    h.dispose();
  }
});
