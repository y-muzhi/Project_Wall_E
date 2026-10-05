import { editorViewCtx } from '@milkdown/kit/core';
import { ApiRejected } from '../../src/api/client.ts';
import type { WalleApi } from '../../src/api/walle.ts';
import { require } from '../../src/api/decoding.ts';
import { RequirementEditor } from '../../src/documents/editor.ts';

export async function readLimitsProbe(api: WalleApi) {
  const created = (await api.prepareCreateRequirement({ title: '正式长度边界诊断', requirement_type: 'CHANGE', template_key: 'change-requirement',
    template_version: 'v1', initial_idea: '隔离原生边界诊断，无模型调用', initialization_mode: 'DESIGN' }).submit()).data;
  const requirement = created.requirement.id;
  async function finish(run: number) {
    const due = Date.now() + 10000;
    while (Date.now() < due) {
      const actual = (await api.getGuideRun(run)).data;
      if (actual.status === 'FAILED') { require(actual.error_code === 'CONFIG_INVALID'); return actual; }
      await new Promise(resolve => setTimeout(resolve, 25));
    } throw new Error('Actual boundary run did not finish');
  }
  await finish(created.guide_run_id);
  let current = (await api.getCurrentDocument(requirement)).data;
  await api.prepareCompleteInitialization(requirement, current.content_version).submit();
  const draft = (await api.prepareStartManualDraft(requirement, current.content_version).submit()).data.manual_draft;
  const root = document.createElement('section'); document.body.append(root);
  const host = await RequirementEditor.create(root, draft, false);
  const selected = '选😀', prefix = '😀'.repeat(100), suffix = '后'.repeat(100);
  try {
    host.action(ctx => { const view = ctx.get(editorViewCtx); view.dispatch(view.state.tr.insert(view.state.doc.content.size,
      view.state.schema.nodes.paragraph!.create(null, view.state.schema.text(prefix + selected + suffix)))); }); require(host.valid);
    const ledger = host.ledger!, ticket = ledger.beginSave();
    const saved = (await api.prepareSaveManualDraft(requirement, { expected_version: ticket.expected_version,
      markdown_content: ticket.markdown_content, block_state_json: ticket.block_state_json }).submit()).data;
    ledger.acknowledgeSave(ticket, saved); host.setReadonly(true);
    current = (await api.prepareCompleteManualDraft(requirement, saved.content_version).submit()).data;
  } finally { await host.destroy(); root.remove(); }
  const description = '😀'.repeat(1000);
  const revision = (await api.prepareCreateRevision(requirement, { expected_version: current.content_version, description }).submit()).data;
  require(revision.description === description);
  const history = (await api.getRevision(revision.id)).data; require(history.description === description);
  const versions = (await api.listRevisions(requirement)).data.items; require(versions.some(value => value.id === revision.id && value.description === description));
  async function refuse(operation: Promise<unknown>) {
    try { await operation; throw new Error('Expected actual native length rejection'); }
    catch (error) { require(error instanceof ApiRejected && error.code === 'VALIDATION_FAILED'); }
  }
  await refuse(api.prepareCreateRevision(requirement, { expected_version: current.content_version, description: description + 'x' }).submit());
  const block = current.block_state_json.blocks.at(-1)!;
  const comment = (await api.prepareCreateComment(requirement, { expected_content_version: current.content_version,
    content: '100码点前后文诊断', anchor_type: 'SELECTION', block_id: block.block_id,
    selection: { selected_text: selected, prefix_text: prefix, suffix_text: suffix } }).submit()).data;
  require('prefix_text' in comment.anchor_ref && comment.anchor_ref.prefix_text === prefix && comment.anchor_ref.suffix_text === suffix);
  require((await api.getComment(comment.id)).data.anchor_ref !== null);
  const comments = (await api.listComments(requirement)).data.items, actual = comments.find(value => value.id === comment.id)!;
  require(actual.location.start_offset === 100 && actual.location.end_offset === 102);
  await refuse(api.prepareCreateComment(requirement, { expected_content_version: current.content_version,
    content: '101前文应拒绝', anchor_type: 'SELECTION', block_id: block.block_id,
    selection: { selected_text: selected, prefix_text: prefix + 'x', suffix_text: suffix } }).submit());
  const guided = (await api.prepareCreateGuide(requirement, { expected_version: current.content_version, action_type: 'ASK', instruction: '范围诊断',
    scope_type: 'SELECTION', scope_ref: { block_id: block.block_id, selected_text: selected, prefix_text: prefix, suffix_text: suffix }, source_type: 'USER_INSTRUCTION' }).submit()).data.guide_run;
  const run = await finish(guided.id); require(run.scope.scope_type === 'SELECTION' && run.scope.scope_ref!.prefix_text === prefix && run.scope.scope_ref!.suffix_text === suffix);
  const listed = (await api.listGuideRuns(requirement)).data.items; require(listed.some(value => value.id === run.id && value.scope.scope_type === 'SELECTION'));
  const unchangedVersions = (await api.listRevisions(requirement)).data.items; require(unchangedVersions.length === 2);
  const unchangedComments = (await api.listComments(requirement)).data.items; require(unchangedComments.length === 1);
  return { passed: true, requirement_id: requirement, revision_codepoints: [...history.description!].length,
    prefix_codepoints: [...prefix].length, suffix_codepoints: [...suffix].length, location: actual.location,
    refused: ['revision1001', 'commentPrefix101'], guide_status: run.status,
    scope: 'Real CHANGE creation/template/manual editor/SQLite and API revision summary/detail/list, comment anchors/locations, GuideRun scopes. No Provider; oversized requests actually rejected and create no revision/comment' };
}
