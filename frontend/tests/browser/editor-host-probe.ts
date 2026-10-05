import { editorViewCtx } from '@milkdown/kit/core';
import type { WalleApi } from '../../src/api/walle.ts';
import { require } from '../../src/api/decoding.ts';
import { RequirementEditor } from '../../src/documents/editor.ts';
import { ManualDraftAutosave } from '../../src/documents/autosave.ts';
import { DraftRecoveryStore } from '../../src/documents/recovery-store.ts';

export function editorHostProbe(api: WalleApi, identity: () => number) {
  let host: RequirementEditor | undefined, autosave: ManualDraftAutosave | undefined, cache: DraftRecoveryStore | undefined;
  let requirement = 0, draftId = 0;
  const errors: string[] = [];
  const root = document.createElement('section'); root.id = 'native-editor-host';
  return {
    async prepare() {
      requirement = identity(); const current = (await api.getCurrentDocument(requirement)).data;
      const draft = (await api.prepareStartManualDraft(requirement, current.content_version).submit()).data.manual_draft; draftId = draft.id;
      document.body.append(root);
      host = await RequirementEditor.create(root, draft, false, { change: () => autosave?.changed(), error: message => { if (message) errors.push(message); },
        blur: () => { if (host?.flushLocal()) void autosave?.flush(); } });
      cache = host.action(ctx => new DraftRecoveryStore(ctx, { name: 'walle-host-probe-' + crypto.randomUUID() }));
      autosave = new ManualDraftAutosave(draft, host.ledger!, { read: async () => (await api.getManualDraft(requirement)).data,
        save: async ticket => (await api.prepareSaveManualDraft(requirement, { expected_version: ticket.expected_version,
          markdown_content: ticket.markdown_content, block_state_json: ticket.block_state_json }).submit()).data }, cache);
      return { ready: true, draft_id: draftId };
    },
    status() { return { ...autosave!.state, markdown: host!.ledger!.currentSnapshot.markdown_content, valid: host!.valid }; },
    async inspect() {
      const actual = (await api.getManualDraft(requirement)).data;
      require(host!.valid && !errors.length && actual.markdown_content === host!.ledger!.currentSnapshot.markdown_content);
      require(JSON.stringify(actual.block_state_json) === JSON.stringify(host!.ledger!.currentSnapshot.block_state_json));
      return { passed: true, actual_version: actual.content_version, markdown: actual.markdown_content, errors };
    },
    readonly(value: boolean) { host!.setReadonly(value); return { readonly: host!.readonly, markdown: host!.ledger!.currentSnapshot.markdown_content }; },
    async composition() {
      host!.setReadonly(false); const revision = autosave!.state.local_revision;
      const editable = root.querySelector<HTMLElement>('.ProseMirror')!;
      editable.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true, data: '' }));
      host!.action(ctx => { const view = ctx.get(editorViewCtx); view.dispatch(view.state.tr.insertText('组合输入诊断', 1)); });
      require(!host!.valid && !host!.flushLocal() && autosave!.state.local_revision === revision);
      editable.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '组合输入诊断' }));
      await Promise.resolve(); require(host!.valid && autosave!.state.local_revision > revision);
      await autosave!.flush(); return { passed: true, scope: 'Synthetic composition lifecycle with actual native editor transactions; not Windows IME acceptance' };
    },
    async close() {
      require(host!.flushLocal()); host!.setReadonly(true); require(await autosave!.freezeAndFlush()); await autosave!.pauseAndWait();
      const version = autosave!.state.confirmed_version;
      await api.prepareCancelManualDraft(requirement, version).submit(); await cache!.clearClosedDraft(requirement, draftId);
      autosave!.dispose(); cache!.close(); await host!.destroy(); root.remove();
      return { closed: true, version };
    },
  };
}
