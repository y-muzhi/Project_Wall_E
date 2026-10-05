import type { Ctx } from '@milkdown/kit/ctx';
import { require } from '../../src/api/decoding.ts';
import type { WalleApi } from '../../src/api/walle.ts';
import { DraftRecoveryStore, DraftStorageError, DRAFT_BYTES, recoveryChoice } from '../../src/documents/recovery-store.ts';
import type { LocalDraftSnapshot } from '../../src/documents/recovery-store.ts';
import { GuideRunPolling } from '../../src/guide/polling.ts';

/** Private browser diagnostic uses a real API draft and a separate IndexedDB.
 * Capacity keys are cache fixtures, not additional backend requirements.
 */
export async function recoveryProbe(ctx: Ctx, api: WalleApi, requirement: number, run: number) {
  const owner = (await api.getRequirement(requirement)).data;
  require(owner.document_work_state === 'IDLE');
  const current = (await api.getCurrentDocument(requirement)).data;
  const draft = (await api.prepareStartManualDraft(requirement, current.content_version).submit()).data.manual_draft;
  const name = 'walle-recovery-probe-' + crypto.randomUUID();
  let store = new DraftRecoveryStore(ctx, { name });
  const checks: string[] = [];
  const snapshot: LocalDraftSnapshot = Object.freeze({ schema_version: 1, base_confirmed_version: draft.content_version,
    markdown_content: draft.markdown_content, block_state_json: draft.block_state_json, local_revision: 1, updated_at: new Date().toISOString() });
  async function refuse(operation: Promise<unknown>, reason: DraftStorageError['reason']) {
    try { await operation; throw new Error('Expected storage refusal'); }
    catch (error) { require(error instanceof DraftStorageError && error.reason === reason); }
  }
  function same(value: unknown, expected: unknown) { require(JSON.stringify(value) === JSON.stringify(expected)); }
  try {
    require(await store.put(requirement, draft.id, snapshot));
    same(await store.get(requirement, draft.id), snapshot); store.close();
    store = new DraftRecoveryStore(ctx, { name }); same(await store.get(requirement, draft.id), snapshot);
    require(await store.get(requirement, draft.id + 1) === null);
    checks.push('actual transaction commit / connection reopen / key isolation');
    const newest = { ...snapshot, local_revision: 2 };
    require(await store.put(requirement, draft.id, newest));
    require(!await store.put(requirement, draft.id, snapshot));
    require(!await store.clearIfRevision(requirement, draft.id, 1)); same(await store.get(requirement, draft.id), newest);
    require(recoveryChoice(newest, draft) === 'RESTORE_AVAILABLE');
    require(recoveryChoice({ ...newest, base_confirmed_version: draft.content_version + 1 }, draft) === 'COMPARE_REQUIRED');
    checks.push('older local write / late receipt cannot erase newer / version comparison');
    const oversized = { ...newest, markdown_content: 'x'.repeat(DRAFT_BYTES + 1) };
    await refuse(store.put(requirement, draft.id, oversized), 'CAPACITY');
    await refuse(store.put(requirement, draft.id, { ...newest, markdown_content: 'wrong native pair' }), 'CORRUPT');
    same(await store.get(requirement, draft.id), newest);
    checks.push('8 MiB bound and actual Milkdown pair validation preserve previous record');
    for (let index = 1; index < 20; index++) require(await store.put(requirement, draft.id + index, snapshot));
    await refuse(store.put(requirement, draft.id + 20, snapshot), 'CAPACITY');
    for (let index = 1; index < 20; index++) same(await store.get(requirement, draft.id + index), snapshot);
    require(await store.get(requirement, draft.id + 20) === null);
    require(await store.put(requirement, draft.id, { ...newest, local_revision: 3 }));
    checks.push('twenty real IndexedDB records / twenty-first refused / replacement permitted / no eviction');
    const unavailable = new DraftRecoveryStore(ctx, { name: name + '-unavailable', factory: () => { throw new Error('diagnostic unavailable'); } });
    await refuse(unavailable.put(requirement, draft.id, snapshot), 'UNAVAILABLE'); unavailable.close();
    const raw = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open(name, 1); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    await new Promise<void>((resolve, reject) => {
      const transaction = raw.transaction('draft_snapshots', 'readwrite');
      transaction.objectStore('draft_snapshots').put({ damaged: true }, [requirement + 1, draft.id]);
      transaction.oncomplete = () => resolve(); transaction.onabort = () => reject(transaction.error);
    }); raw.close();
    await refuse(store.get(requirement + 1, draft.id), 'CORRUPT');
    same(await store.get(requirement, draft.id + 1), snapshot);
    checks.push('unavailable factory / persisted damaged record refused without deleting other snapshots');
    const observed = await new Promise<string>((resolve, reject) => {
      const poll = new GuideRunPolling(run, async (identity, signal) => (await api.getGuideRun(identity, signal)).data);
      const timer = setTimeout(() => { poll.dispose(); reject(new Error('Actual terminal query timed out')); }, 5000);
      poll.subscribe(state => {
        if (state.confirmed) { clearTimeout(timer); require(state.confirmed.status === 'FAILED' && state.confirmed.error_code === 'CONFIG_INVALID' && !state.polling);
          const actual = state.confirmed.status; poll.dispose(); resolve(actual); }
      }); poll.setVisible(true);
    });
    checks.push('real production API terminal state read through owned polling controller: ' + observed);
    require(await store.clearIfRevision(requirement, draft.id, 3)); require(await store.get(requirement, draft.id) === null);
    await api.prepareCancelManualDraft(requirement, draft.content_version).submit();
    await store.clearClosedDraft(requirement, draft.id);
    checks.push('matching acknowledged revision clear / actual draft cancel confirmed');
    return { passed: true, name, draft_id: draft.id, checks, capacity_records: 20,
      scope: 'Native IndexedDB with real Crepe/API draft; no restore adoption or autosave, no Provider; capacity keys and unavailable/damaged input explicit diagnostics' };
  } finally { store.close(); }
}
