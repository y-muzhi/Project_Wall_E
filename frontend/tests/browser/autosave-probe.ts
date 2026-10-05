import { Crepe } from '@milkdown/crepe';
import { editorViewCtx } from '@milkdown/kit/core';
import { ApiUnknown, ApiRejected } from '../../src/api/client.ts';
import type { WalleApi } from '../../src/api/walle.ts';
import { require } from '../../src/api/decoding.ts';
import { installSourceNodes } from '../../src/documents/source-nodes.ts';
import { installIdentityAttributes, installIdentityState } from '../../src/documents/identity.ts';
import { EditedSnapshotLedger } from '../../src/documents/edited-snapshot.ts';
import { ManualDraftAutosave } from '../../src/documents/autosave.ts';
import { DraftRecoveryStore } from '../../src/documents/recovery-store.ts';

function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(accept => { resolve = accept; }); return { promise, resolve }; }
export async function autosaveProbe(api: WalleApi, requirement: number) {
  const current = (await api.getCurrentDocument(requirement)).data;
  const draft = (await api.prepareStartManualDraft(requirement, current.content_version).submit()).data.manual_draft;
  const root = document.createElement('div'); root.id = 'autosave-editor'; document.body.append(root);
  const editor = new Crepe({ root, defaultValue: draft.markdown_content, features: {
    [Crepe.Feature.CodeMirror]: false, [Crepe.Feature.ListItem]: false, [Crepe.Feature.LinkTooltip]: false, [Crepe.Feature.Cursor]: false,
    [Crepe.Feature.ImageBlock]: false, [Crepe.Feature.BlockEdit]: false, [Crepe.Feature.Toolbar]: false, [Crepe.Feature.Placeholder]: false,
    [Crepe.Feature.Table]: false, [Crepe.Feature.Latex]: false, [Crepe.Feature.TopBar]: false, [Crepe.Feature.AI]: false,
  } });
  await installSourceNodes(editor); installIdentityAttributes(editor);
  installIdentityState(editor, draft.block_state_json.blocks.map(block => block.block_id), draft.block_state_json.next_block_id);
  await editor.create();
  const ledger = editor.editor.action(ctx => new EditedSnapshotLedger(ctx, draft, ctx.get(editorViewCtx).state));
  const cache = editor.editor.action(ctx => new DraftRecoveryStore(ctx, { name: 'walle-autosave-probe-' + crypto.randomUUID() }));
  const firstCommitted = deferred<void>(), release = deferred<void>();
  const sent: { version: number; markdown: string }[] = []; let active = 0, peak = 0, loseResponse = false;
  const controller = new ManualDraftAutosave(draft, ledger, {
    read: async () => (await api.getManualDraft(requirement)).data,
    save: async ticket => {
      active++; peak = Math.max(active, peak); sent.push({ version: ticket.expected_version, markdown: ticket.markdown_content });
      try {
        const result = (await api.prepareSaveManualDraft(requirement, { expected_version: ticket.expected_version,
          markdown_content: ticket.markdown_content, block_state_json: ticket.block_state_json }).submit()).data;
        if (sent.length === 1) { firstCommitted.resolve(); await release.promise; }
        if (loseResponse) { loseResponse = false; throw new ApiUnknown(true); } // actual native commit already happened
        return result;
      } finally { active--; }
    },
  }, cache);
  const states: string[] = []; controller.subscribe(state => states.push(state.status));
  let editingClock = Math.max(Date.now(), Date.parse(draft.updated_at) + 1);
  function edit(text: string, notify = true) {
    editor.editor.action(ctx => {
      const view = ctx.get(editorViewCtx);
      view.dispatch(view.state.tr.insert(view.state.doc.content.size, view.state.schema.nodes.paragraph!.create(null, view.state.schema.text(text))));
      const prepared = ledger.prepare(view.state, new Date(editingClock = Math.max(editingClock + 1, Date.now(), Date.parse(controller.state.saved_at) + 1)).toISOString());
      view.updateState(prepared.state); ledger.accept(prepared, view.state);
    }); if (notify) controller.changed();
  }
  try {
    edit('第一份真实编辑'); const pending = controller.flush(); await firstCommitted.promise;
    edit('中间编辑无需单独保存'); edit('最新真实编辑😀'); release.resolve(); await pending;
    require(peak === 1 && sent.length === 2 && sent[0]!.version === 1 && sent[1]!.version === 2);
    require(controller.state.status === 'SAVED' && controller.state.confirmed_version === 3);
    let actual = (await api.getManualDraft(requirement)).data;
    require(actual.markdown_content === controller.localSnapshot.markdown_content && actual.markdown_content.includes('最新真实编辑😀'));
    require(JSON.stringify(actual.block_state_json) === JSON.stringify(controller.localSnapshot.block_state_json));
    loseResponse = true; edit('真实提交后丢失响应'); await controller.flush();
    require(Number(sent.length) === 3 && Number(controller.state.confirmed_version) === 4 && controller.state.status === 'SAVED' && states.includes('UNKNOWN'));
    actual = (await api.getManualDraft(requirement)).data; require(actual.content_version === 4 && actual.markdown_content === controller.localSnapshot.markdown_content);
    require(JSON.stringify(actual.block_state_json) === JSON.stringify(controller.localSnapshot.block_state_json));
    const unchanged = (await api.getCurrentDocument(requirement)).data;
    require(unchanged.content_version === current.content_version && unchanged.markdown_content === current.markdown_content);
    require(await controller.freezeAndFlush());
    await controller.pauseAndWait(); controller.dispose();
    // Native version guard plus two exact ledger proofs: the older suspended
    // submission wins, the newer actual request is rejected, and its prepared
    // proof must be retired rather than later accepted as a receipt.
    edit('旧请求尚待确认', false); const older = ledger.beginSave(); ledger.suspendSave(older);
    edit('新输入保留等待接续', false); const newer = ledger.beginSave();
    const olderReceipt = (await api.prepareSaveManualDraft(requirement, { expected_version: older.expected_version,
      markdown_content: older.markdown_content, block_state_json: older.block_state_json }).submit()).data;
    try { await api.prepareSaveManualDraft(requirement, { expected_version: newer.expected_version,
      markdown_content: newer.markdown_content, block_state_json: newer.block_state_json }).submit(); throw new Error('Expected native version conflict'); }
    catch (error) { require(error instanceof ApiRejected && error.code === 'CONTENT_VERSION_CONFLICT'); }
    const preserved = ledger.acknowledgeSave(older, olderReceipt);
    require(preserved.markdown_content === newer.markdown_content && ledger.savedVersion === 5);
    let retired = false; try { ledger.acknowledgeSave(newer, olderReceipt); } catch { retired = true; } require(retired);
    const last = ledger.beginSave();
    const lastReceipt = (await api.prepareSaveManualDraft(requirement, { expected_version: last.expected_version,
      markdown_content: last.markdown_content, block_state_json: last.block_state_json }).submit()).data;
    const final = ledger.acknowledgeSave(last, lastReceipt);
    require(lastReceipt.content_version === 6 && final.markdown_content === newer.markdown_content);
    require(JSON.stringify(final.block_state_json) === JSON.stringify(lastReceipt.block_state_json));
    await api.prepareCancelManualDraft(requirement, ledger.savedVersion).submit();
    await cache.clearClosedDraft(requirement, draft.id);
    return { passed: true, writes: sent, peak_inflight: peak, confirmed_draft_version: actual.content_version, states,
      native_cohort: { older_version: olderReceipt.content_version, final_version: lastReceipt.content_version, newer_request: 'CONTENT_VERSION_CONFLICT', retired_proof_refused: retired },
      scope: 'Real Crepe edits/ledger, production API and native SQLite, real IndexedDB. Receipt deliberately held and third actual committed response dropped locally; no Provider/product-page acceptance' };
  } finally { controller.dispose(); ledger.dispose(); cache.close(); await editor.destroy(); root.remove(); }
}
