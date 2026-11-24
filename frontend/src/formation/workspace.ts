import { nativeFormationCommand } from '../api/formation-commands.ts';
import type { FormationProposal } from '../api/formation-workflow.ts';
import { FormationPathEditor } from './path-editor.ts';
import { FormationPreferences } from './preferences.ts';
import type { FormationTab } from './preferences.ts';
/** One selected document owns reads, next-round choices and native command reconciliation. */
import { ApiRejected, ApiUnknown, snapshotObject, stableJson } from '../api/client.ts';
import type { ApiSuccess, JsonObject } from '../api/client.ts';
import type { ApiAction, WalleApi } from '../api/walle.ts';
import type { DiscussionState } from '../api/models.ts';
import type { DetailSnapshot } from '../requirements/detail-read.ts';
import { formationSelection, formationProgramReceipt } from '../api/formation-workflow.ts';
import { FormationReadOwner } from './read-owner.ts';
import { FormationCommandRecovery, FormationUnsentError } from './command-recovery.ts';
import { FormationDrafts } from './drafts.ts';
import type { FormationPendingSummary } from './command-store.ts';
export type FormationSelection = ReturnType<typeof formationSelection>;
export type TargetCapture = Readonly<{ selection: FormationSelection; epoch: string }>;
export type FormationWorkspaceState = Readonly<{
  tab: FormationTab;
  show_branches: boolean;
  editor_open: boolean;
  receipt: ReturnType<typeof formationProgramReceipt> | null;
  preference_warning: string | null;
  brief: DiscussionState['progress_brief'] | null;
  previousTopics: readonly Pick<
    DiscussionState['topics'][number],
    'topic_ref' | 'title' | 'updated_by_message_id'
  >[];
  mode: 'UNKNOWN' | 'LEGACY' | 'FORMATION';
  loading: boolean;
  read_error: string | null;
  error: string | null;
  next_target: FormationSelection | null;
  selection_epoch: string;
  draft_warning: string | null;
  target_error: string | null;
  phase: 'IDLE' | 'SENDING' | 'UNKNOWN' | 'CONFIRMED';
  pending: readonly FormationPendingSummary[];
  recovery_error: string | null;
  notice: string | null;
}>;
const capture = <T>(value: T): T => snapshotObject(value) as unknown as T;
export class FormationWorkspace {
  readonly read: FormationReadOwner;
  readonly recovery: FormationCommandRecovery;
  readonly requirementId: number;
  readonly documentId: number;
  private facts: {
    discussion: number;
    content: number;
    revision: number;
    workState: string;
    archived: boolean;
  };
  private value: FormationWorkspaceState;
  private readonly listeners = new Set<() => void>();
  private closed = false;
  private blocked = true;
  private readOnly = false;
  private adjustment:
    | ((
        proposal: { message_id: number; card_key: string },
        purpose: 'STAGED_WRITE' | 'FORMATION_PATH_CHANGE',
        scope: JsonObject | null,
      ) => boolean)
    | null = null;
  private localLease: string | null = null;
  private savedScrollAnchor: string | null = null;
  private pending: Promise<boolean> | null = null;
  private activeCommand: string | null = null;
  private initializing: Promise<boolean> | null = null;
  private controller: AbortController | null = null;
  private supportsBrief = true;
  private readonly drafts: FormationDrafts;
  private readonly preferences: FormationPreferences;
  private readonly readRelease: () => void;
  pathEditor: FormationPathEditor | null = null;
  readonly api: WalleApi;
  private readonly readActual: () => Promise<DetailSnapshot>;
  private readonly adoptActual: (value: DetailSnapshot) => Promise<void>;
  private readonly receive: (value: { id: number; requirement_id: number }) => Promise<void>;
  constructor(
    detail: DetailSnapshot,
    api: WalleApi,
    readActual: () => Promise<DetailSnapshot>,
    adoptActual: (value: DetailSnapshot) => Promise<void>,
    receive: (value: { id: number; requirement_id: number }) => Promise<void>,
    diagnostic?: {
      recovery?: FormationCommandRecovery;
      drafts?: FormationDrafts;
      preferences?: FormationPreferences;
    },
  ) {
    this.api = api;
    this.readActual = readActual;
    this.adoptActual = adoptActual;
    this.receive = receive;
    if (detail.current === null) throw TypeError('Selected document required');
    this.facts = {
      discussion: detail.requirement.discussion_version,
      content: detail.current.content_version,
      revision: detail.current.current_revision_id,
      workState: detail.requirement.document_work_state,
      archived: detail.current.archived_at !== null,
    };
    this.requirementId = detail.requirement.id;
    this.documentId = detail.current.id;
    this.read = new FormationReadOwner(this.requirementId, this.documentId, api);
    this.recovery =
      diagnostic?.recovery ??
      new FormationCommandRecovery(this.requirementId, this.documentId, api);
    this.drafts =
      diagnostic?.drafts ??
      new FormationDrafts(this.requirementId, this.documentId, this.recovery.store.origin);
    const restored = this.drafts.load();
    this.preferences =
      diagnostic?.preferences ?? new FormationPreferences(this.requirementId, this.documentId);
    this.read.restoreDisplay(
      this.preferences.initial.selected_step_ref,
      this.preferences.initial.show_cancelled,
    );
    this.savedScrollAnchor = this.preferences.initial.scroll_anchor;
    this.value = Object.freeze({
      tab: this.preferences.initial.tab,
      show_branches: this.preferences.initial.show_branches,
      editor_open: false,
      receipt: null,
      preference_warning: this.preferences.warning,
      mode: 'UNKNOWN',
      read_error: null,
      brief: null,
      previousTopics: [],
      loading: false,
      error: null,
      next_target: restored.target?.selection ?? null,
      selection_epoch: restored.target?.selection_epoch ?? crypto.randomUUID(),
      draft_warning: restored.warning,
      target_error: null,
      phase: 'IDLE',
      pending: [],
      recovery_error: null,
      notice: null,
    });
    this.readRelease = this.read.subscribe(() => this.publish({}));
  }
  getSnapshot = () => this.value;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  private publish(change: Partial<FormationWorkspaceState>) {
    if (this.closed) return;
    this.value = Object.freeze({ ...this.value, ...change });
    for (const listener of this.listeners) listener();
  }
  adopt(detail: DetailSnapshot): void {
    if (detail.requirement.id !== this.requirementId || detail.current?.id !== this.documentId)
      throw TypeError('Owned document required');
    const changed =
      this.facts.discussion !== detail.requirement.discussion_version ||
      this.facts.revision !== detail.current.current_revision_id;
    this.facts = {
      discussion: detail.requirement.discussion_version,
      content: detail.current.content_version,
      revision: detail.current.current_revision_id,
      workState: detail.requirement.document_work_state,
      archived: detail.current.archived_at !== null,
    };
    if (detail.discussion !== null) this.observeDiscussion(detail.discussion);
    if (changed && !detail.discussion?.progress_brief && this.value.mode === 'FORMATION')
      void this.refresh(false);
  }
  observeDiscussion(discussion: DiscussionState): void {
    if (discussion.formation_summary === undefined) {
      this.publish({ mode: 'LEGACY', brief: null, loading: false, read_error: null, error: null });
      return;
    }
    this.read.observeSummary(discussion.formation_summary);
    const previous = this.value.brief;
    const brief =
      discussion.progress_brief ??
      (previous?.discussion_version === this.facts.discussion &&
      previous.formation_version === discussion.formation_summary.formation_version &&
      previous.revision_id === this.facts.revision
        ? previous
        : null);
    this.publish({
      mode: 'FORMATION',
      brief,
      previousTopics: discussion.formation_summary.exists ? [] : discussion.topics,
      read_error: null,
      loading: false,
      error: null,
    });
  }
  setView(blocked: boolean, readOnly: boolean, localLease: string | null = null): void {
    if (this.blocked === blocked && this.readOnly === readOnly && this.localLease === localLease)
      return;
    this.blocked = blocked;
    this.readOnly = readOnly;
    this.localLease = localLease;
    this.publish({});
  }
  get contentVersion(): number {
    return this.facts.content;
  }
  get discussionVersion(): number {
    return this.facts.discussion;
  }
  get revisionId(): number {
    return this.facts.revision;
  }
  get targetReason(): string | null {
    if (this.blocked) return '当前页面暂不可操作';
    if (this.readOnly) return '正在查看历史内容';
    return this.value.mode === 'FORMATION' ? null : '主线状态尚未就绪';
  }
  get writeReason(): string | null {
    return this.reason(false);
  }
  get composeReason(): string | null {
    return this.reason(true);
  }
  private reason(composing: boolean): string | null {
    if (this.blocked) return '当前页面暂不可操作';
    if (this.readOnly) return '正在查看历史内容';
    if (this.facts.archived) return '文档已归档';
    if (this.value.loading) return '正在读取主线状态';
    if (this.value.phase === 'SENDING') return '正在提交操作';
    if (this.value.phase === 'CONFIRMED') return '操作已确认，请先刷新实际状态';
    if (this.value.pending.length > 0 || this.value.phase === 'UNKNOWN')
      return '有待核实操作，请先处理恢复记录';
    if (this.value.recovery_error !== null) return this.value.recovery_error;
    if (this.localLease === 'RUN') return 'AI运行操作尚未完成核实，请返回AI对话查看进度';
    if (
      this.facts.workState !== 'IDLE' ||
      (this.localLease !== null && !(composing && this.localLease === 'COMPOSER'))
    )
      return '当前正在处理文档操作';
    if (this.value.mode !== 'FORMATION') return '主线状态尚未就绪';
    return null;
  }
  private async pendingRecords(): Promise<void> {
    try {
      const pending = await this.recovery.list();
      this.publish({ pending, recovery_error: null });
    } catch (error) {
      this.publish({
        recovery_error: error instanceof Error ? error.message : '恢复记录暂不可读取',
      });
    }
  }
  ensureInitialized(): Promise<boolean> {
    if (this.value.mode !== 'UNKNOWN') return Promise.resolve(true);
    if (this.initializing !== null) return this.initializing;
    const pending = this.refresh(false).finally(() => {
      if (this.initializing === pending) this.initializing = null;
    });
    this.initializing = pending;
    return pending;
  }
  private async readDiscussion(signal: AbortSignal, limit: number) {
    const read = (progressLimit?: number) =>
      this.api.getRequirementDetail(
        this.requirementId,
        signal,
        true,
        this.documentId,
        progressLimit,
      );
    if (!this.supportsBrief) return read();
    try {
      return await read(limit);
    } catch (error) {
      const fields =
        error instanceof ApiRejected && error.code === 'VALIDATION_FAILED'
          ? error.details?.field_errors
          : null;
      if (
        !Array.isArray(fields) ||
        fields.length === 0 ||
        !fields.every(
          (field) =>
            field !== null &&
            typeof field === 'object' &&
            !Array.isArray(field) &&
            (field.field === 'progress_view' || field.field === 'progress_limit') &&
            field.reason === 'UNKNOWN_FIELD',
        )
      )
        throw error;
      this.supportsBrief = false;
      return read();
    }
  }
  async refresh(loadRows = true, progressLimit = 3): Promise<boolean> {
    if (this.closed) return false;
    this.controller?.abort();
    const controller = new AbortController();
    this.controller = controller;
    this.publish({ loading: true, read_error: null, error: null });
    try {
      const actual = (await this.readDiscussion(controller.signal, progressLimit)).data;
      if (this.closed || this.controller !== controller) return false;
      if (actual.discussion === null) throw new ApiUnknown(false);
      const document = actual.documents.find((row) => row.id === this.documentId);
      if (document === undefined) throw new ApiUnknown(false);
      this.facts = {
        discussion: actual.requirement.discussion_version,
        content: document.content_version,
        revision: document.current_revision_id,
        workState: actual.requirement.document_work_state,
        archived: document.archived_at !== null,
      };
      this.observeDiscussion(actual.discussion);
      await this.pendingRecords();
      if (
        this.value.mode === 'FORMATION' &&
        loadRows &&
        this.read.getSnapshot().summary.data?.exists
      ) {
        const selected = this.read.getSnapshot().selected_step_ref;
        await Promise.all([
          this.read.loadPage(null),
          selected === null ? Promise.resolve(true) : this.read.selectStep(selected),
        ]);
      }
      return true;
    } catch (error) {
      if (!this.closed && this.controller === controller) {
        const message = error instanceof ApiRejected ? error.message : '主线状态暂时无法读取';
        if (error instanceof ApiRejected && error.code === 'NOT_FOUND') {
          this.read.forgetDocument();
          this.publish({
            mode: 'UNKNOWN',
            brief: null,
            previousTopics: [],
            editor_open: false,
            read_error: message,
            error: message,
          });
        } else {
          this.publish({
            read_error: message,
            error: this.value.brief ? message + '。下方显示上次读取的进展。' : message,
          });
        }
      }
      return false;
    } finally {
      if (this.controller === controller) {
        this.controller = null;
        this.publish({ loading: false });
      }
    }
  }
  get selection(): FormationSelection {
    if (this.value.next_target !== null) return this.value.next_target;
    const summary = this.read.getSnapshot().summary;
    if (summary.phase !== 'READY' || summary.data === null)
      throw new FormationUnsentError('请先读取文档主线状态');
    return formationSelection({
      discussion_step_ref: summary.data.current_step_ref,
      discussion_branch_ref: summary.data.active_branch_ref,
      branch_intent: summary.data.active_branch_ref === null ? null : 'ENTER',
      branch_resume_basis: null,
    });
  }
  get targetLabel(): string {
    try {
      const target = this.selection,
        step = target.discussion_step_ref;
      const title = this.read
        .getSnapshot()
        .page.data?.data.items.find((row) => row.step_ref === step)?.title;
      const focus = this.value.brief?.focus;
      const label =
        step === null
          ? '整份文档'
          : (title ?? (focus?.step_ref === step ? focus.title : '步骤 ' + step));
      return target.discussion_branch_ref === null
        ? label
        : label +
            ' · 支线 ' +
            target.discussion_branch_ref +
            (target.branch_intent === 'RESUME' ? '（继续讨论）' : '');
    } catch {
      return '正在读取讨论目标';
    }
  }
  async captureTarget(): Promise<TargetCapture | null> {
    if (this.value.mode === 'UNKNOWN' && !(await this.refresh(false)))
      throw new FormationUnsentError('请先读取主线状态');
    if (this.value.mode === 'LEGACY') return null;
    const selection = capture(this.selection),
      epoch = crypto.randomUUID();
    this.publish({
      selection_epoch: epoch,
      draft_warning: this.drafts.save(this.value.next_target, epoch),
    });
    await this.pendingRecords();
    if (this.composeReason !== null) throw new FormationUnsentError(this.composeReason);
    if (this.value.target_error !== null) throw new FormationUnsentError(this.value.target_error);
    return Object.freeze({ selection, epoch });
  }
  private setTarget(selection: FormationSelection | null): string {
    const epoch = crypto.randomUUID();
    const normalized = selection === null ? null : formationSelection(selection);
    this.publish({
      next_target: normalized,
      selection_epoch: epoch,
      target_error: null,
      draft_warning: this.drafts.save(normalized, epoch),
    });
    return epoch;
  }
  private savePreference(): void {
    const read = this.read.getSnapshot();
    this.publish({
      preference_warning: this.preferences.save({
        ...this.preferences.initial,
        selected_step_ref: read.selected_step_ref,
        show_cancelled: read.show_cancelled,
        show_branches: this.value.show_branches,
        scroll_anchor: this.savedScrollAnchor,
        tab: this.value.tab,
      }),
    });
  }
  get hasPathDraft(): boolean {
    return this.drafts.readPath() !== null;
  }
  openPathEditor(): void {
    if (!this.hasPathDraft) return;
    if (this.targetReason !== null) {
      this.publish({ error: this.targetReason });
      return;
    }
    if (this.read.getSnapshot().summary.data?.exists !== true) {
      this.publish({ error: '文档主线尚未建立，请先讨论文档目标' });
      return;
    }
    if (this.pathEditor?.getSnapshot().phase === 'SAVED') {
      this.pathEditor.dispose();
      this.pathEditor = null;
    }
    this.pathEditor ??= new FormationPathEditor(this, this.drafts);
    this.publish({ editor_open: true });
  }
  closePathEditor(): void {
    this.publish({ editor_open: false });
  }
  bindAdjustment(handler: NonNullable<FormationWorkspace['adjustment']>): void {
    this.adjustment = handler;
  }
  async adjustProposal(proposal: FormationProposal): Promise<void> {
    if (this.writeReason !== null) {
      this.publish({ error: this.writeReason });
      return;
    }
    if (
      this.adjustment === null ||
      !this.adjustment(
        { message_id: proposal.message_id, card_key: proposal.card_key },
        proposal.purpose,
        proposal.purpose === 'STAGED_WRITE' ? snapshotObject(proposal.payload.scope) : null,
      )
    ) {
      this.publish({ error: '当前输入操作尚未结束，请先处理原请求' });
      return;
    }
    const step = proposal.purpose === 'STAGED_WRITE' ? proposal.payload.step_ref : null;
    this.setTarget(
      formationSelection({
        discussion_step_ref: step,
        discussion_branch_ref: null,
        branch_intent: null,
        branch_resume_basis: null,
      }),
    );
    await this.openProposal(proposal.source_run_id);
  }
  async openProposal(sourceRunId: number): Promise<void> {
    try {
      await this.receive({ id: sourceRunId, requirement_id: this.requirementId });
    } catch {
      this.publish({ error: '原提案暂时无法定位，请重试' });
      return;
    }
  }
  selectView(ref: string | null): Promise<boolean> {
    const pending = this.read.selectStep(ref);
    this.savePreference();
    return pending;
  }
  setTab(tab: FormationTab): void {
    this.publish({ tab });
    this.savePreference();
  }
  setShowBranches(value: boolean): void {
    this.publish({ show_branches: value });
    this.savePreference();
  }
  get scrollAnchor(): string | null {
    return this.savedScrollAnchor;
  }
  rememberScrollAnchor(ref: string): void {
    if (this.savedScrollAnchor === ref || this.closed) return;
    this.savedScrollAnchor = ref;
    const read = this.read.getSnapshot();
    const warning = this.preferences.save({
      ...this.preferences.initial,
      selected_step_ref: read.selected_step_ref,
      show_cancelled: read.show_cancelled,
      show_branches: this.value.show_branches,
      tab: this.value.tab,
      scroll_anchor: ref,
    });
    if (warning !== this.value.preference_warning) this.publish({ preference_warning: warning });
  }
  setShowCancelled(value: boolean): Promise<boolean> {
    const pending = this.read.setShowCancelled(value);
    this.savePreference();
    return pending;
  }
  followServerFocus(): void {
    this.setTarget(null);
  }
  accepted(target: FormationSelection, epoch: string): void {
    if (epoch !== this.value.selection_epoch) return;
    if (this.value.next_target !== null)
      this.publish({
        next_target: formationSelection(target),
        draft_warning: this.drafts.save(target, epoch),
        target_error: null,
      });
  }
  completedNext(ref: string, epoch: string): void {
    if (epoch !== this.value.selection_epoch) return;
    this.setTarget(
      formationSelection({
        discussion_step_ref: ref,
        discussion_branch_ref: null,
        branch_intent: null,
        branch_resume_basis: null,
      }),
    );
  }
  durable<T>(action: ApiAction<T>, intentKey?: string): ApiAction<T> {
    const wrapped = this.recovery.wrap(action, intentKey);
    return Object.freeze({
      request: wrapped.request,
      submit: async () => {
        try {
          return await wrapped.submit();
        } finally {
          await this.pendingRecords();
        }
      },
    });
  }
  execute(command: JsonObject): Promise<boolean> {
    const signature = stableJson(command)!;
    if (this.pending !== null)
      return this.activeCommand === signature ? this.pending : Promise.resolve(false);
    if (this.writeReason !== null) {
      this.publish({ error: this.writeReason });
      return Promise.resolve(false);
    }
    let action: ApiAction<ReturnType<typeof formationProgramReceipt>>;
    try {
      action = this.durable(
        this.api.prepareFormationCommand(this.requirementId, {
          expected_discussion_version: this.facts.discussion,
          discussion_command: command,
        }),
      );
    } catch {
      this.publish({ error: '操作内容无法完整核实，请检查后重试' });
      return Promise.resolve(false);
    }
    this.activeCommand = signature;
    const pending = Promise.resolve().then(async () => {
      this.publish({ phase: 'SENDING', error: null, notice: null });
      try {
        const response = await action.submit();
        const receipt = formationProgramReceipt(response.data);
        this.publish({ receipt });
        this.publish({ phase: 'CONFIRMED', notice: '操作已确认' });
        return await this.finish();
      } catch (error) {
        if (error instanceof ApiRejected || error instanceof FormationUnsentError)
          this.publish({ phase: 'IDLE', error: error.message });
        else this.publish({ phase: 'UNKNOWN', error: '操作结果待核实，原请求已保留' });
        return false;
      } finally {
        if (this.pending === pending) {
          this.pending = null;
          this.activeCommand = null;
        }
      }
    });
    this.pending = pending;
    return pending;
  }
  async finish(): Promise<boolean> {
    try {
      const actual = await this.readActual();
      await this.adoptActual(actual);
      this.adopt(actual);
      if (!(await this.refresh())) throw Error('操作已确认，主线内容暂时无法刷新');
      this.publish({ phase: 'IDLE', error: null });
      return true;
    } catch (error) {
      this.publish({
        phase: 'CONFIRMED',
        error: error instanceof Error ? error.message : '操作已确认，请重新读取实际状态',
      });
      return false;
    }
  }
  replay(key: string): Promise<boolean> {
    const signature = 'REPLAY:' + key;
    if (this.pending !== null)
      return this.activeCommand === signature ? this.pending : Promise.resolve(false);
    if (this.closed) return Promise.resolve(false);
    this.activeCommand = signature;
    const pending = Promise.resolve()
      .then(() => this.replayOriginal(key))
      .finally(() => {
        if (this.pending === pending) {
          this.pending = null;
          this.activeCommand = null;
        }
      });
    this.pending = pending;
    return pending;
  }
  private async replayOriginal(key: string): Promise<boolean> {
    this.publish({ phase: 'SENDING', error: null });
    try {
      const original = await this.recovery.store.detail(key);
      const response: ApiSuccess<unknown> = await this.recovery.replay(key);
      const result = snapshotObject(response.data);
      if (result.processing === 'PROGRAM') {
        this.publish({ receipt: formationProgramReceipt(result) });
        if (
          original !== null &&
          original.method === 'PATCH' &&
          original.intent_key === this.value.selection_epoch
        ) {
          const body = snapshotObject(JSON.parse(original.body_text));
          const command = nativeFormationCommand(body.discussion_command);
          if (command.action === 'RESUME_BRANCH' && command.enter_after_resume === true)
            this.accepted(
              formationSelection({
                discussion_step_ref: command.step_ref,
                discussion_branch_ref: command.branch_ref,
                branch_intent: 'ENTER',
                branch_resume_basis: null,
              }),
              original.intent_key,
            );
          if (command.action === 'COMPLETE_STEP' && typeof command.next_step_ref === 'string')
            this.completedNext(command.next_step_ref, original.intent_key);
        }
      }
      if (result.processing === 'MODEL') {
        await this.receive({
          id: result.guide_run_id as number,
          requirement_id: this.requirementId,
        });
        if (
          original !== null &&
          result.accepted_target !== undefined &&
          original.path.endsWith('/guide-runs')
        )
          this.accepted(formationSelection(result.accepted_target), original.intent_key);
      }
      this.publish({ phase: 'CONFIRMED', notice: '原操作已确认' });
      return await this.finish();
    } catch (error) {
      this.publish({
        phase: error instanceof ApiRejected ? 'IDLE' : 'UNKNOWN',
        error: error instanceof Error ? error.message : '原操作仍待核实',
      });
      return false;
    } finally {
      await this.pendingRecords();
    }
  }
  async cancelUnsent(key: string): Promise<void> {
    try {
      await this.recovery.cancelUnsent(key);
      await this.pendingRecords();
    } catch (error) {
      this.publish({ error: error instanceof Error ? error.message : '无法取消未发送操作' });
    }
  }
  dispose(): void {
    this.closed = true;
    this.controller?.abort();
    this.readRelease();
    this.read.dispose();
    this.pathEditor?.dispose();
    this.recovery.dispose();
    this.listeners.clear();
  }
}
