import { snapshotObject } from '../api/client.ts';
import type { GuideRun } from '../api/models.ts';
import type { WalleApi } from '../api/walle.ts';
import type { DetailSnapshot } from '../requirements/detail-read.ts';
import { RequirementSuggestionBatch } from '../suggestions/batch-owner.ts';
import { RequirementAiRead } from './read-owner.ts';
import { RequirementGuideComposer } from './composer.ts';
import { RequirementRunActions } from './run-actions.ts';
import { RequirementCardGroups } from './card-groups.ts';
import { CardDrafts } from './card-drafts.ts';
import { ModelCallCache } from './model-call-reader.ts';

export type ConversationState = Readonly<{
  detail: DetailSnapshot;
  visible: boolean;
  suggestions_visible: boolean;
  review_read_only: boolean;
  enabled: boolean;
  active: boolean;
  lease: string | null;
  batch: RequirementSuggestionBatch | null;
  pendingBatchId: number | null;
  pendingBatchRead: 'IDLE' | 'LOADING' | 'READY' | 'ERROR';
  revision: number;
}>;
const retained = (phase: string) =>
  ['SUBMITTING', 'READING', 'UNKNOWN', 'CONFIRMED'].includes(phase);
/** One requirement's existing real owners. Ordinary text, cards and Run
 * commands share the same receiver and adoption boundary. Retained original
 * requests keep their owner through history selection, hidden views and new
 * actual activity; no refresh or competing button replaces that request. */
export class RequirementConversation {
  get modelCallApi(): Pick<WalleApi, 'listModelCalls' | 'getModelCall'> {
    return this.api;
  }
  readonly modelCalls: ModelCallCache;
  readonly read: RequirementAiRead;
  readonly composer: RequirementGuideComposer;
  readonly runs: RequirementRunActions;
  readonly cards: RequirementCardGroups;
  private value: ConversationState;
  private readonly listeners = new Set<() => void>();
  private readonly releases: (() => void)[] = [];
  private readonly batches = new Map<
    number,
    { owner: RequirementSuggestionBatch; release: () => void }
  >();
  private readonly api: WalleApi;
  private readonly readActual: () => Promise<DetailSnapshot>;
  private readonly adoptActual: (actual: DetailSnapshot) => Promise<void>;
  private closed = false;
  private reconciling = false;
  private again = false;
  private runSignature = '';
  private batchVisibility = 0;
  private batchRead = '';
  private selectedBatch: number | null = null;
  private pendingBatchRequest: AbortController | null = null;
  constructor(
    detail: DetailSnapshot,
    api: WalleApi,
    readActual: () => Promise<DetailSnapshot>,
    adoptActual: (actual: DetailSnapshot) => Promise<void>,
    openPanel: () => void | Promise<void>,
    drafts = new CardDrafts(
      undefined,
      undefined,
      detail.selected_document_id ?? detail.current?.id ?? null,
    ),
    observeActual = readActual,
  ) {
    if (
      detail.current !== null &&
      detail.current !== null &&
      (detail.current.document_type !== 'CURRENT' ||
        detail.current.requirement_id !== detail.requirement.id)
    )
      throw TypeError('Actual owned CURRENT required');
    this.api = api;
    this.modelCalls = new ModelCallCache(detail.requirement.id);
    this.readActual = readActual;
    this.adoptActual = adoptActual;
    this.value = Object.freeze({
      detail: snapshotObject(detail) as unknown as DetailSnapshot,
      visible: false,
      suggestions_visible: false,
      review_read_only: false,
      enabled: true,
      active: true,
      lease: null,
      batch: null,
      pendingBatchId: null,
      pendingBatchRead: 'IDLE',
      revision: 0,
    });
    const adopt = async (actual: DetailSnapshot) => {
      if (this.closed) throw Error('Conversation is retired');
      await this.adoptActual(actual);
      if (this.closed) throw Error('Conversation is retired');
      this.adopt(actual);
    };
    this.read = new RequirementAiRead(detail, api, observeActual, adopt, openPanel);
    const refreshMessages = async () => {
      if (!(await this.read.messages.refresh())) throw Error('实际消息暂时无法读取');
    };
    this.composer = new RequirementGuideComposer(
      detail,
      api,
      readActual,
      adopt,
      this.read.receive,
      refreshMessages,
      undefined,
      observeActual,
    );
    this.runs = new RequirementRunActions(
      detail,
      api,
      readActual,
      adopt,
      this.read.receive,
      observeActual,
    );
    this.cards = new RequirementCardGroups(
      this.read,
      api,
      drafts,
      readActual,
      adopt,
      this.read.receive,
      refreshMessages,
      (owner) => this.permitted('CARD:' + owner.getSnapshot().message.id),
      observeActual,
    );
    for (const owner of [this.read, this.composer, this.runs, this.cards])
      this.releases.push(owner.subscribe(() => this.reconcile()));
    this.reconcile();
  }
  getSnapshot = (): ConversationState => this.value;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  private publish(changes: Partial<ConversationState>): void {
    if (this.closed) return;
    this.value = Object.freeze({ ...this.value, ...changes, revision: this.value.revision + 1 });
    for (const listener of this.listeners)
      try {
        listener();
      } catch (error) {
        console.error('WALL-E conversation observer failed', error);
      }
  }
  private permitted(key: string): boolean {
    return (
      !this.closed &&
      (key.startsWith('BATCH:')
        ? this.value.suggestions_visible && (this.value.enabled || this.value.review_read_only)
        : this.value.visible && this.value.enabled) &&
      (this.value.lease === null || this.value.lease === key)
    );
  }
  private protectedOwners(): string[] {
    return [
      retained(this.composer.getSnapshot().phase) ? 'COMPOSER' : null,
      retained(this.runs.getSnapshot().phase) ? 'RUN' : null,
      ...this.cards
        .retainedOwners()
        .filter((owner) => retained(owner.getSnapshot().phase))
        .map((owner) => 'CARD:' + owner.getSnapshot().message.id),
      ...[...this.batches]
        .filter(([, entry]) => retained(entry.owner.getSnapshot().phase))
        .map(([id]) => 'BATCH:' + id),
    ].filter((key): key is string => key !== null);
  }
  openBatch(identity: number): void {
    if (this.closed || !Number.isSafeInteger(identity) || identity < 1) return;
    this.selectedBatch = identity;
    this.cancelPendingBatchRead();
    this.publish({ pendingBatchRead: 'IDLE' });
    this.reconcile();
  }
  private cancelPendingBatchRead(): void {
    this.pendingBatchRequest?.abort();
    this.pendingBatchRequest = null;
  }
  refreshPendingBatch = async (): Promise<void> => {
    const { detail, suggestions_visible, enabled, review_read_only } = this.value;
    const documentId = detail.selected_document_id;
    if (
      this.closed ||
      !suggestions_visible ||
      !(enabled || review_read_only) ||
      documentId === null ||
      this.selectedBatch !== null ||
      this.pendingBatchRequest !== null
    )
      return;
    const request = new AbortController();
    this.pendingBatchRequest = request;
    this.publish({ pendingBatchRead: 'LOADING' });
    try {
      const { data } = await this.api.getPendingDocumentBatch(
        detail.requirement.id,
        documentId,
        request.signal,
      );
      if (request.signal.aborted) return;
      this.publish({ pendingBatchId: data.batch_id, pendingBatchRead: 'READY' });
      this.reconcile();
    } catch {
      if (!request.signal.aborted) this.publish({ pendingBatchRead: 'ERROR' });
    } finally {
      if (this.pendingBatchRequest === request) this.pendingBatchRequest = null;
    }
  };
  private batchOwner(id: number): RequirementSuggestionBatch {
    const retained = this.batches.get(id);
    if (retained) return retained.owner;
    const owner = new RequirementSuggestionBatch(
      id,
      this.value.detail,
      this.api,
      this.readActual,
      async (actual) => {
        if (this.closed) throw Error('Conversation is retired');
        await this.adoptActual(actual);
        if (this.closed) throw Error('Conversation is retired');
        this.adopt(actual);
      },
    );
    this.batches.set(id, { owner, release: owner.subscribe(() => this.reconcile()) });
    return owner;
  }
  private reconcile(): void {
    if (this.closed) return;
    if (this.reconciling) {
      this.again = true;
      return;
    }
    this.reconciling = true;
    try {
      do {
        this.again = false;
        const protectedKeys = this.protectedOwners(),
          lease =
            this.value.lease && protectedKeys.includes(this.value.lease)
              ? this.value.lease
              : (protectedKeys[0] ?? null);
        if (lease !== this.value.lease) this.publish({ lease });
        const parent = this.read.getSnapshot(),
          signature = JSON.stringify([this.value.detail, parent.run]);
        if (signature !== this.runSignature) {
          this.runSignature = signature;
          this.runs.adopt(this.value.detail, parent.run);
        }
        const active = this.value.detail.activity;
        const activeBatch =
          this.value.pendingBatchRead !== 'READY' &&
          active.kind === 'BATCH' &&
          active.batch.target_document_id === this.value.detail.selected_document_id
            ? active.batch.id
            : null;
        const selected = lease?.startsWith('BATCH:')
          ? Number(lease.slice(6))
          : (this.selectedBatch ?? this.value.pendingBatchId ?? activeBatch);
        const batch = selected === null ? null : this.batchOwner(selected);
        if (batch !== this.value.batch) this.publish({ batch });
        const view = this.value.visible && this.value.enabled,
          batchView =
            this.value.suggestions_visible && (this.value.enabled || this.value.review_read_only);
        this.read.setVisible(view);
        this.composer.setAvailable(this.permitted('COMPOSER'));
        this.runs.setAvailable(this.permitted('RUN'));
        this.cards.setAvailable(view);
        this.cards.reconcilePermissions();
        for (const [id, entry] of this.batches) {
          entry.owner.setReadOnly(this.value.review_read_only);
          entry.owner.setAvailable(entry.owner === batch && this.permitted('BATCH:' + id));
        }
        // A newly arrived batch may still be excluded by the original send lease.
        // Do not consume its first read until that actual owner can perform it.
        const key = selected === null ? '' : selected + ':' + this.batchVisibility;
        if (batchView && batch && batch.getSnapshot().available && key !== this.batchRead) {
          this.batchRead = key;
          if (['READY', 'ERROR'].includes(batch.getSnapshot().phase)) void batch.refresh();
        }
      } while (this.again);
      this.publish({});
    } finally {
      this.reconciling = false;
    }
  }
  /** Transient document-adoption busy does not invalidate a command's own
   * confirmed reconciliation. The view may separately disable busy inputs. */
  setView(
    visible: boolean,
    enabled = this.value.enabled,
    suggestionsVisible = false,
    reviewReadOnly = false,
    reviewTabSelected = suggestionsVisible,
  ): void {
    if (
      this.closed ||
      (visible === this.value.visible &&
        enabled === this.value.enabled &&
        suggestionsVisible === this.value.suggestions_visible &&
        reviewReadOnly === this.value.review_read_only)
    )
      return;
    const wasReviewing = this.value.suggestions_visible;
    const mayReadReview = enabled || reviewReadOnly;
    const didReadReview = this.value.enabled || this.value.review_read_only;
    const leavingReview = wasReviewing && !suggestionsVisible;
    if (leavingReview && !reviewTabSelected) this.selectedBatch = null;
    if (!suggestionsVisible || !mayReadReview) this.cancelPendingBatchRead();
    if (suggestionsVisible !== wasReviewing || mayReadReview !== didReadReview)
      this.batchVisibility++;
    this.publish({
      visible,
      enabled,
      suggestions_visible: suggestionsVisible,
      review_read_only: reviewReadOnly,
      ...(leavingReview ? { pendingBatchId: null, pendingBatchRead: 'IDLE' as const } : {}),
    });
    if (suggestionsVisible && mayReadReview && (!wasReviewing || !didReadReview))
      void this.refreshPendingBatch();
    this.reconcile();
  }
  adopt(actual: DetailSnapshot): void {
    if (this.closed) return;
    if (
      actual.selected_document_id !== this.value.detail.selected_document_id ||
      actual.requirement.id !== this.value.detail.requirement.id ||
      (actual.current !== null &&
        (actual.current.document_type !== 'CURRENT' ||
          actual.current.requirement_id !== actual.requirement.id))
    )
      throw TypeError('Actual owned detail required');
    const previous = this.reconciling;
    this.reconciling = true;
    try {
      this.publish({ detail: snapshotObject(actual) as unknown as DetailSnapshot });
      this.composer.adopt(actual);
      this.read.adopt(actual);
      for (const entry of this.batches.values()) entry.owner.adopt(actual);
    } finally {
      this.reconciling = previous;
    }
    if (!previous) this.reconcile();
    else this.again = true;
  }
  receive = (run: Pick<GuideRun, 'id' | 'requirement_id'>): Promise<void> => this.read.receive(run);
  batch(identity: number): RequirementSuggestionBatch | null {
    return this.batches.get(identity)?.owner ?? null;
  }
  async refresh(): Promise<void> {
    if (this.closed || !this.value.visible || !this.value.enabled)
      throw Error('Conversation is hidden');
    await this.read.refresh();
  }
  dispose(): void {
    if (this.closed) return;
    this.publish({ active: false, visible: false, suggestions_visible: false, enabled: false });
    this.closed = true;
    this.cancelPendingBatchRead();
    for (const release of this.releases) release();
    for (const entry of this.batches.values()) {
      entry.release();
      entry.owner.dispose();
    }
    this.modelCalls.clear();
    this.cards.dispose();
    this.runs.dispose();
    this.composer.dispose();
    this.read.dispose();
    this.listeners.clear();
  }
}
