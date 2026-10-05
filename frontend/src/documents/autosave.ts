import { ApiRejected } from '../api/client.ts';
import type { DocumentReadModel } from './contracts.ts';
import type { EditedSnapshot, ManualDraftSubmission } from './edited-snapshot.ts';
import type { LocalDraftSnapshot } from './recovery-store.ts';
import type { PollClock } from '../guide/polling.ts';

export interface DraftSaveLedger {
  readonly currentSnapshot: EditedSnapshot; readonly savedVersion: number;
  beginSave(): ManualDraftSubmission;
  acknowledgeSave(submission: ManualDraftSubmission, input: unknown): EditedSnapshot;
  suspendSave(submission: ManualDraftSubmission): void;
  rejectSave(submission: ManualDraftSubmission): void;
}
export interface DraftSaveApi {
  save(submission: ManualDraftSubmission): Promise<DocumentReadModel>;
  read(): Promise<DocumentReadModel>;
}
export interface DraftCache {
  put(requirement: number, draft: number, value: LocalDraftSnapshot): Promise<boolean>;
  clearIfRevision(requirement: number, draft: number, revision: number): Promise<boolean>;
}
export type SaveStatus = 'SAVED' | 'DIRTY' | 'SAVING' | 'RETRYING' | 'UNKNOWN' | 'VALIDATION_ERROR' | 'CONFLICT' | 'CLOSED';
export type SaveState = Readonly<{ status: SaveStatus; confirmed_version: number; local_revision: number; saved_at: string;
  error: string | null; server_conflict: DocumentReadModel | null; local_storage_error: boolean; accepting_input: boolean }>;
const realClock: PollClock = { schedule(callback, delay) { const timer = setTimeout(callback, delay); return () => clearTimeout(timer); } };
const backoff = [2000, 5000, 10000, 30000] as const;
function same(left: EditedSnapshot, right: EditedSnapshot): boolean {
  return left.markdown_content === right.markdown_content && JSON.stringify(left.block_state_json) === JSON.stringify(right.block_state_json);
}
function corresponds(submission: ManualDraftSubmission, document: DocumentReadModel): boolean {
  return document.content_version === submission.expected_version + 1 && document.markdown_content === submission.markdown_content &&
    document.block_state_json.next_block_id === submission.block_state_json.next_block_id &&
    document.block_state_json.blocks.length === submission.block_state_json.blocks.length &&
    document.block_state_json.blocks.every((block, index) => block.block_id === submission.block_state_json.blocks[index]!.block_id);
}

/** Serial I11 controller. The real editor ledger proves every acknowledgement;
 * native API/database remain authoritative. Unknown submissions are evidence,
 * never a queue of intermediate content to resend.
 */
export class ManualDraftAutosave {
  private readonly ledger: DraftSaveLedger; private readonly api: DraftSaveApi; private readonly cache: DraftCache; private readonly clock: PollClock;
  private confirmed: DocumentReadModel; private observed: EditedSnapshot;
  private readonly tickets = new Map<ManualDraftSubmission, number>();
  private readonly listeners = new Set<(state: SaveState) => void>();
  private value: SaveState;
  private idle: (() => void) | undefined; private maximum: (() => void) | undefined; private retry: (() => void) | undefined;
  private pending: Promise<void> | undefined; private requested = false; private failures = 0; private closed = false; private paused = false;
  constructor(draft: DocumentReadModel, ledger: DraftSaveLedger, api: DraftSaveApi, cache: DraftCache, clock: PollClock = realClock) {
    if (draft.document_type !== 'MANUAL_DRAFT' || ledger.savedVersion !== draft.content_version || !same(ledger.currentSnapshot, draft)) throw new TypeError('Actual loaded draft/ledger required');
    this.confirmed = draft; this.ledger = ledger; this.api = api; this.cache = cache; this.clock = clock; this.observed = ledger.currentSnapshot;
    this.value = Object.freeze({ status: 'SAVED', confirmed_version: draft.content_version, local_revision: 0, saved_at: draft.updated_at,
      error: null, server_conflict: null, local_storage_error: false, accepting_input: true });
  }
  get state(): SaveState { return this.value; }
  get localSnapshot(): EditedSnapshot { return this.observed; }
  subscribe(listener: (state: SaveState) => void): () => void { this.listeners.add(listener); listener(this.value); return () => this.listeners.delete(listener); }
  private publish(changes: Partial<SaveState>): void {
    if (this.closed) return;
    this.value = Object.freeze({ ...this.value, ...changes });
    for (const listener of this.listeners) {
      // An observer bug must not convert an actual save success into a network
      // failure or break another observer's delivery.
      try { listener(this.value); } catch (error) { console.error('WALL-E save observer failed', error); }
    }
  }
  private clearTimers(): void { this.idle?.(); this.maximum?.(); this.retry?.(); this.idle = this.maximum = this.retry = undefined; }
  private dirty(): boolean { return !same(this.observed, this.confirmed); }
  private persist(): void {
    if (!this.value.local_revision) return;
    const revision = this.value.local_revision;
    const record: LocalDraftSnapshot = Object.freeze({ schema_version: 1, base_confirmed_version: this.confirmed.content_version,
      ...this.observed, local_revision: revision, updated_at: new Date().toISOString() });
    void this.cache.put(this.confirmed.requirement_id, this.confirmed.id, record).then(stored => {
      if (revision === this.value.local_revision) this.publish({ local_storage_error: !stored });
    }, () => this.publish({ local_storage_error: true }));
  }
  /** Call after the exact editor preparation has been accepted/displayed. */
  changed(): void {
    if (this.closed || !this.value.accepting_input) throw new Error('Editing is frozen');
    const pair = this.ledger.currentSnapshot;
    if (same(pair, this.observed)) return;
    if (this.value.local_revision >= Number.MAX_SAFE_INTEGER) throw new Error('Local revision capacity exhausted');
    this.observed = pair;
    this.publish({ local_revision: this.value.local_revision + 1, ...(this.value.status === 'CONFLICT' ? {} : { error: null }) }); this.persist();
    if (this.value.status === 'CONFLICT') return;
    if (this.pending) { this.requested = true; return; }
    if (this.retry) return; // A typing event never bypasses the failure backoff.
    this.publish({ status: this.dirty() || this.tickets.size ? 'DIRTY' : 'SAVED' });
    this.idle?.(); this.idle = this.clock.schedule(() => { this.idle = undefined; void this.flush(); }, 2000);
    this.maximum ??= this.clock.schedule(() => { this.maximum = undefined; void this.flush(); }, 10000);
  }
  /** Explicit recovery on a newly loaded real baseline. Continue the stored
   * revision counter so later cache writes/receipts cannot erase or lose it. */
  restoreLocal(local:LocalDraftSnapshot,apply:()=>EditedSnapshot):void {
    if(this.closed||this.paused||this.pending||this.tickets.size||this.value.status!=='SAVED'||this.value.local_revision!==0||
      !this.value.accepting_input||local.base_confirmed_version!==this.confirmed.content_version||!Number.isSafeInteger(local.local_revision)||local.local_revision<1||local.local_revision>=Number.MAX_SAFE_INTEGER)throw new TypeError('Fresh same-base recovery required');
    const pair=apply();if(!same(pair,local)||!same(pair,this.ledger.currentSnapshot))throw new TypeError('Recovery pair was not accepted by actual ledger');
    this.publish({local_revision:local.local_revision});this.changed();
    if(!this.dirty())void this.cache.clearIfRevision(this.confirmed.requirement_id,this.confirmed.id,local.local_revision).catch(()=>this.publish({local_storage_error:true}));
  }
  /** Blur/visibility-hidden/explicit save; no write abort on hiding. */
  flush(): Promise<void> {
    if (this.closed || this.paused || this.value.status === 'CONFLICT' || this.value.status === 'VALIDATION_ERROR') return this.pending ?? Promise.resolve();
    this.clearTimers(); this.requested = true;
    if (this.pending) return this.pending;
    this.pending = Promise.resolve().then(() => this.drive()).finally(() => { this.pending = undefined; });
    return this.pending;
  }
  private later(status: 'RETRYING' | 'UNKNOWN', message: string): void {
    this.requested = false; this.clearTimers(); this.publish({ status, error: message });
    if (!this.paused && !this.closed) this.retry = this.clock.schedule(() => { this.retry = undefined; void this.flush(); }, backoff[Math.min(this.failures++, backoff.length - 1)]!);
  }
  private validIdentity(document: DocumentReadModel): boolean {
    return document.document_type === 'MANUAL_DRAFT' && document.id === this.confirmed.id && document.requirement_id === this.confirmed.requirement_id && document.created_at === this.confirmed.created_at;
  }
  private acknowledge(ticket: ManualDraftSubmission, document: DocumentReadModel): void {
    if (!this.validIdentity(document)) throw new TypeError('Another draft receipt');
    this.observed = this.ledger.acknowledgeSave(ticket, document); this.confirmed = document; this.tickets.clear(); this.failures = 0;
    this.publish({ confirmed_version: document.content_version, saved_at: document.updated_at, error: null, server_conflict: null, status: this.dirty() ? 'DIRTY' : 'SAVED' });
    if (this.dirty()) { this.persist(); this.requested = true; }
    else if (this.value.local_revision) {
      const revision = this.value.local_revision;
      void this.cache.clearIfRevision(document.requirement_id, document.id, revision).catch(() => this.publish({ local_storage_error: true }));
    }
  }
  private conflict(document: DocumentReadModel | null): void {
    this.clearTimers(); this.requested = false;
    this.publish({ status: 'CONFLICT', error: '草稿已被其他页面更新，请保留本地内容并对照处理', server_conflict: document });
  }
  /** Reading the old version does not prove an earlier HTTP write cannot
   * still commit. Retain its proof and never advance the expected version.
   */
  private async reconcile(): Promise<'OLD' | 'ACK' | 'STOP'> {
    let document: DocumentReadModel;
    try { document = await this.api.read(); }
    catch { if (!this.closed) this.later('UNKNOWN', '保存结果待核实，正在重新读取草稿'); return 'STOP'; }
    if (this.closed) return 'STOP';
    if (!this.validIdentity(document)) { this.conflict(null); return 'STOP'; }
    if (document.content_version === this.confirmed.content_version && same(document, this.confirmed)) return 'OLD';
    const ticket = [...this.tickets.keys()].find(value => corresponds(value, document));
    if (ticket) {
      try { this.acknowledge(ticket, document); return 'ACK'; }
      catch { this.conflict(document); return 'STOP'; }
    }
    this.conflict(document); return 'STOP';
  }
  private async drive(): Promise<void> {
    while (this.requested && !this.closed && !this.paused) {
      this.requested = false;
      if (this.tickets.size) {
        const result = await this.reconcile();
        if (result === 'STOP') return;
        if (result === 'ACK') { if (this.requested) continue; return; }
      }
      if (!this.dirty() && !this.tickets.size) { this.publish({ status: 'SAVED' }); return; }
      let ticket: ManualDraftSubmission;
      try { ticket = this.ledger.beginSave(); }
      catch { this.publish({ status: 'VALIDATION_ERROR', error: '编辑快照无法提交，请保留内容并修正' }); return; }
      this.tickets.set(ticket, this.value.local_revision); this.publish({ status: 'SAVING', error: null });
      try {
        const document = await this.api.save(ticket);
        if (this.closed) return;
        this.acknowledge(ticket, document);
      } catch (error) {
        if (this.closed) return;
        if (error instanceof ApiRejected) {
          this.ledger.rejectSave(ticket); this.tickets.delete(ticket);
          if (error.code === 'CONTENT_VERSION_CONFLICT') {
            const result = await this.reconcile();
            if (result === 'ACK' && this.requested) continue;
            if (result === 'OLD') this.conflict(null);
            return;
          }
          this.clearTimers(); this.requested = false;
          this.publish({ status: ['VALIDATION_FAILED', 'DOCUMENT_INVALID', 'TEMPLATE_INVALID'].includes(error.code) ? 'VALIDATION_ERROR' : 'CONFLICT', error: error.message }); return;
        }
        // Transport/projection/receipt failure might follow a native commit.
        // Release only the active slot, not the submitted evidence.
        this.ledger.suspendSave(ticket);
        this.publish({ status: 'UNKNOWN', error: '保存结果待核实' });
        const result = await this.reconcile();
        if (result === 'ACK' && this.requested) continue;
        if (result === 'OLD') this.later('RETRYING', '保存失败，正在重试');
        return;
      }
    }
  }
  /** Parent completes only when this returns true and then uses this confirmed
   * draft version. If false it keeps the editor frozen or explicitly resumes.
   */
  async freezeAndFlush(): Promise<boolean> {
    this.publish({ accepting_input: false }); await this.flush();
    return !this.closed && this.value.status === 'SAVED' && !this.dirty() && !this.tickets.size;
  }
  resumeEditing(): void { if (!this.closed) { this.paused = false; this.publish({ accepting_input: true }); } }
  /** Parent has confirmed discard. Stop new saves and await the owned request
   * before reading actual occupancy/version and issuing cancellation.
   */
  async pauseAndWait(): Promise<void> { this.paused = true; this.requested = false; this.clearTimers(); this.publish({ accepting_input: false }); await this.pending; }
  dispose(): void {
    this.closed = true; this.paused = true; this.requested = false; this.clearTimers(); this.listeners.clear();
    this.value = Object.freeze({ ...this.value, status: 'CLOSED', accepting_input: false });
    // A page lifetime ending is not evidence that its native write rolled back.
  }
}
