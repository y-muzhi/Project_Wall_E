import { ApiRejected, positiveInteger, snapshotObject } from '../api/client.ts';
import type { WalleApi } from '../api/walle.ts';
import type {
  Requirement,
  RequirementDetail,
  GuideRun,
  Batch,
  DocumentView,
  ManualDraft,
} from '../api/models.ts';
import { ReadingSelection } from '../documents/reading-selection.ts';

type CommentIndex = Awaited<ReturnType<WalleApi['getCommentIndex']>>['data'];
type ReadApi = Pick<
  WalleApi,
  | 'getRequirementDetail'
  | 'getRequirement'
  | 'getCurrentDocument'
  | 'getManualDraft'
  | 'getGuideRun'
  | 'getBatch'
  | 'getCommentIndex'
> &
  Partial<Pick<WalleApi, 'detailReadEpoch'>>;
export type DetailActivity = Readonly<
  | { kind: 'IDLE' }
  | { kind: 'MANUAL'; draft: ManualDraft; target: DocumentView }
  | { kind: 'GUIDE'; run: GuideRun }
  | { kind: 'BATCH'; batch: Batch }
>;
export type DetailSnapshot = RequirementDetail &
  Readonly<{
    current: DocumentView | null;
    selected_document_id: number | null;
    activity: DetailActivity;
    comment_index: CommentIndex | null;
  }>;
export type DocumentDetailSnapshot = DetailSnapshot & Readonly<{ current: DocumentView }>;
export function assertDocumentDetail(
  value: DetailSnapshot,
): asserts value is DocumentDetailSnapshot {
  if (value.current === null) throw TypeError('An explicitly selected actual document is required');
}
export type DetailReadError = 'MISSING' | 'INCONSISTENT' | 'CHANGED' | 'READ_FAILED';
export type DetailReadState = Readonly<{
  confirmed: DetailSnapshot | null;
  loading: boolean;
  active: boolean;
  error: string | null;
  error_kind: DetailReadError | null;
}>;
export type DetailPhase =
  | 'DETAIL_LOADING'
  | 'DETAIL_MISSING'
  | 'DETAIL_ERROR'
  | 'WORK_STATE_INCONSISTENT'
  | 'CONTENT_VERSION_CONFLICT'
  | 'IDLE_VIEW'
  | 'MANUAL_EDITING'
  | 'GUIDE_RUNNING'
  | 'GUIDE_WAITING'
  | 'BATCH_REVIEW';
class ReadMismatch extends Error {
  readonly kind: 'INCONSISTENT' | 'CHANGED';
  constructor(kind: 'INCONSISTENT' | 'CHANGED') {
    super(
      kind === 'INCONSISTENT' ? '数据状态异常，请重试' : '读取期间当前状态或正文已变化，请重新读取',
    );
    this.kind = kind;
  }
}
const requireRelation = (valid: boolean): void => {
  if (!valid) throw new ReadMismatch('INCONSISTENT');
};
const captured = <T>(value: T): T => snapshotObject(value) as unknown as T;
const occupancy = (value: Requirement) =>
  JSON.stringify([
    value.document_work_state,
    value.active_operation_type,
    value.active_operation_id,
  ]);

/** Complete read bundle owned by one detail lifetime. Each API has its own
 * real transaction; matching references/versions are checks, not a claimed
 * multi-endpoint database snapshot. No partial bundle or fake empty editor. */
export class RequirementDetailRead {
  private readonly identity: number;
  private readonly api: ReadApi;
  private value: DetailReadState = Object.freeze({
    confirmed: null,
    loading: false,
    active: true,
    error: null,
    error_kind: null,
  });
  private readonly listeners = new Set<() => void>();
  private generation = 0;
  private closed = false;
  private controller: AbortController | undefined;
  private pending: Promise<boolean> | undefined;
  private selected: number | null | undefined;
  private pendingEpoch = -1;
  private pendingReuse = false;
  private readonly reading: ReadingSelection;
  constructor(
    identity: number,
    api: ReadApi,
    storage?: () => Pick<Storage, 'getItem' | 'setItem'>,
  ) {
    this.identity = positiveInteger(identity);
    this.api = api;
    this.reading = new ReadingSelection(identity, storage);
    this.selected = this.reading.load();
  }
  selectDocument(identity: number | null): Promise<boolean> {
    if (identity !== null) {
      positiveInteger(identity);
      if (!this.value.confirmed?.documents.some((document) => document.id === identity))
        throw TypeError('The document must belong to the actual requirement directory');
    }
    this.selected = identity;
    return this.refresh(true);
  }
  getSnapshot = (): DetailReadState => this.value;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  get writeReady(): boolean {
    return (
      !this.closed &&
      this.value.active &&
      !this.value.loading &&
      !this.value.error &&
      this.value.confirmed !== null
    );
  }
  get phase(): DetailPhase {
    if (this.value.loading || !this.value.active) return 'DETAIL_LOADING';
    if (this.value.error_kind === 'MISSING') return 'DETAIL_MISSING';
    if (this.value.error_kind === 'INCONSISTENT') return 'WORK_STATE_INCONSISTENT';
    if (this.value.error_kind === 'CHANGED') return 'CONTENT_VERSION_CONFLICT';
    if (this.value.error || !this.value.confirmed)
      return this.value.error ? 'DETAIL_ERROR' : 'DETAIL_LOADING';
    const activity = this.value.confirmed.activity;
    return activity.kind === 'IDLE'
      ? 'IDLE_VIEW'
      : activity.kind === 'MANUAL'
        ? 'MANUAL_EDITING'
        : activity.kind === 'BATCH'
          ? 'BATCH_REVIEW'
          : 'GUIDE_RUNNING';
  }
  private publish(changes: Partial<DetailReadState>): void {
    if (this.closed) return;
    this.value = Object.freeze({ ...this.value, ...changes });
    for (const listener of this.listeners) {
      try {
        listener();
      } catch (error) {
        console.error('WALL-E detail read observer failed', error);
      }
    }
  }
  /** Observation may reuse a matching last-known body/index. Explicit and
   * recovery reads still acquire the complete bundle, including comments. */
  observe(): Promise<boolean> {
    return this.refresh(false, true);
  }
  refresh(force = false, reuseContent = false): Promise<boolean> {
    if (this.closed) return Promise.resolve(false);
    const epoch = this.api.detailReadEpoch ?? 0;
    if (
      this.pending &&
      !force &&
      this.pendingEpoch === epoch &&
      (reuseContent || !this.pendingReuse)
    )
      return this.pending;
    this.pendingEpoch = epoch;
    this.pendingReuse = reuseContent;
    const generation = ++this.generation,
      controller = new AbortController();
    this.controller?.abort();
    this.controller = controller;
    let rootConfirmed = false;
    const pending = Promise.resolve()
      .then(async () => {
        if (this.closed || generation !== this.generation) return false;
        try {
          const detail = captured(
              (await this.api.getRequirementDetail(this.identity, controller.signal)).data,
            ),
            root = detail.requirement;
          if (this.closed || generation !== this.generation) return false;
          rootConfirmed = true;
          requireRelation(root.id === this.identity);
          const initialOrEmpty =
            this.value.confirmed === null || this.value.confirmed.documents.length === 0;
          if (
            this.selected === undefined ||
            (initialOrEmpty &&
              (this.selected === null ||
                !detail.documents.some((document) => document.id === this.selected)))
          )
            this.selected =
              detail.documents.find((document) => document.archived_at === null)?.id ?? null;
          const documentId = this.selected;
          if (documentId !== null)
            requireRelation(detail.documents.some((document) => document.id === documentId));
          let current: DocumentView | null = null,
            index: CommentIndex | null = null;
          const previous = this.value.confirmed;
          const reused =
            reuseContent &&
            root.document_work_state !== 'MANUAL_EDITING' &&
            previous?.activity.kind !== 'MANUAL' &&
            previous?.current?.id === documentId &&
            previous.comment_index !== null &&
            JSON.stringify(previous.documents.find((row) => row.id === documentId)) ===
              JSON.stringify(detail.documents.find((row) => row.id === documentId));
          if (reused) {
            current = previous!.current;
            index = previous!.comment_index;
          } else if (documentId !== null) {
            const [documentResponse, indexResponse] = await Promise.all([
              this.api.getCurrentDocument(this.identity, documentId, controller.signal),
              this.api.getCommentIndex(this.identity, documentId, controller.signal),
            ]);
            if (this.closed || generation !== this.generation) return false;
            current = captured(documentResponse.data);
            index = captured(indexResponse.data);
            requireRelation(
              current.id === documentId &&
                current.requirement_id === this.identity &&
                index.document_id === documentId &&
                index.requirement_id === this.identity,
            );
            if (index.content_version !== current.content_version)
              throw new ReadMismatch('CHANGED');
            const ids = new Set(current.block_state_json.blocks.map((block) => block.block_id));
            requireRelation(
              index.blocks.every((block) => ids.has(block.block_id)) &&
                index.comments.every(
                  (comment) =>
                    comment.location.status !== 'ATTACHED' || ids.has(comment.location.block_id!),
                ),
            );
          }
          let activity: DetailActivity;
          switch (root.document_work_state) {
            case 'IDLE':
              activity = Object.freeze({ kind: 'IDLE' });
              break;
            case 'MANUAL_EDITING': {
              const targetId = detail.active_operation?.target_document_id;
              requireRelation(targetId != null);
              if (targetId == null) throw new ReadMismatch('INCONSISTENT');
              const [draftResponse, targetResponse] = await Promise.all([
                this.api.getManualDraft(this.identity, targetId, controller.signal),
                current?.id === targetId
                  ? Promise.resolve({ data: current })
                  : this.api.getCurrentDocument(this.identity, targetId, controller.signal),
              ]);
              const draft = captured(draftResponse.data),
                target = captured(targetResponse.data);
              requireRelation(
                draft.id === root.active_operation_id &&
                  draft.requirement_id === this.identity &&
                  draft.target_document_id === target.id &&
                  target.requirement_id === this.identity,
              );
              if (draft.base_content_version !== target.content_version)
                throw new ReadMismatch('CHANGED');
              activity = Object.freeze({ kind: 'MANUAL', draft, target });
              break;
            }
            case 'GUIDE_ACTIVE': {
              if (root.active_operation_id === null) throw new ReadMismatch('INCONSISTENT');
              const run = captured(
                (await this.api.getGuideRun(root.active_operation_id, controller.signal)).data,
              );
              requireRelation(
                run.id === root.active_operation_id &&
                  run.requirement_id === this.identity &&
                  run.status === 'RUNNING',
              );
              activity = Object.freeze({ kind: 'GUIDE', run });
              break;
            }
            case 'SUGGESTION_REVIEWING': {
              if (root.active_operation_id === null) throw new ReadMismatch('INCONSISTENT');
              const batch = captured(
                (await this.api.getBatch(root.active_operation_id, controller.signal)).data,
              );
              requireRelation(
                batch.requirement_id === this.identity &&
                  batch.id === root.active_operation_id &&
                  batch.status === 'PENDING',
              );
              activity = Object.freeze({ kind: 'BATCH', batch });
              break;
            }
          }
          if (this.closed || generation !== this.generation) return false;
          const latest = captured(
            (await this.api.getRequirementDetail(this.identity, controller.signal)).data,
          );
          if (occupancy(root) !== occupancy(latest.requirement)) throw new ReadMismatch('CHANGED');
          if (
            reused &&
            JSON.stringify(detail.documents.find((row) => row.id === documentId)) !==
              JSON.stringify(latest.documents.find((row) => row.id === documentId))
          )
            throw new ReadMismatch('CHANGED');
          for (const document of [current, activity.kind === 'MANUAL' ? activity.target : null]) {
            if (document !== null) {
              const summary = latest.documents.find((summary) => summary.id === document.id);
              if (
                summary?.content_version !== document.content_version ||
                summary?.metadata_version !== document.metadata_version
              )
                throw new ReadMismatch('CHANGED');
            }
          }
          const confirmed: DetailSnapshot = Object.freeze({
            ...latest,
            current,
            selected_document_id: documentId,
            activity,
            comment_index: index,
          });
          this.reading.save(documentId);
          this.publish({ confirmed, loading: false, error: null, error_kind: null });
          return true;
        } catch (error) {
          if (this.closed || generation !== this.generation) return false;
          const kind: DetailReadError =
            error instanceof ReadMismatch
              ? error.kind
              : error instanceof ApiRejected && error.code === 'NOT_FOUND' && !rootConfirmed
                ? 'MISSING'
                : error instanceof ApiRejected &&
                    ['WORK_STATE_INCONSISTENT', 'MANUAL_DRAFT_NOT_FOUND', 'NOT_FOUND'].includes(
                      error.code,
                    )
                  ? 'INCONSISTENT'
                  : 'READ_FAILED';
          this.publish({
            loading: false,
            error_kind: kind,
            error:
              kind === 'MISSING'
                ? '需求不存在'
                : error instanceof ReadMismatch
                  ? error.message
                  : kind === 'INCONSISTENT'
                    ? '数据状态异常，请重试'
                    : error instanceof ApiRejected
                      ? error.message
                      : '暂时无法读取详情，请重试',
          });
          return false;
        }
      })
      .finally(() => {
        if (this.pending === pending) this.pending = undefined;
        if (this.controller === controller) this.controller = undefined;
      });
    this.pending = pending;
    this.publish({ loading: true, active: true, error: null, error_kind: null });
    return pending;
  }
  pause(): void {
    if (this.closed) return;
    this.generation++;
    this.controller?.abort();
    this.controller = undefined;
    this.pending = undefined;
    this.publish({ loading: false, active: false });
  }
  dispose(): void {
    this.closed = true;
    this.generation++;
    this.controller?.abort();
    this.listeners.clear();
  }
}
