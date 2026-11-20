import { ApiRejected, snapshotObject } from '../api/client.ts';
import type { ApiAction, CreateGuide, WalleApi } from '../api/walle.ts';
import type { GuideRun, Message, RunReceipt } from '../api/models.ts';
import { sourceRef, runReceipt, scope as decodeScope } from '../api/models.ts';
import type { DetailSnapshot } from '../requirements/detail-read.ts';
import { ordinaryInput } from '../shared/text.ts';
import { ComposerDrafts } from './composer-drafts.ts';
import type { GuideTarget } from './scope.ts';
type Operation = 'DISCUSS' | 'REVISE';
type SendIntent = Pick<ComposerState, 'action' | 'target' | 'parent' | 'instruction'>;
type Submitted = Readonly<
  | { kind: 'CREATE'; body: CreateGuide; raw: string }
  | { kind: 'CONTINUE'; parent: GuideRun; instruction: string; version: number; raw: string }
>;
export type ComposerState = Readonly<{
  detail: DetailSnapshot;
  action: Operation;
  target: GuideTarget | null;
  source_refs: CreateGuide['source_refs'];
  review: GuideRun | null;
  parent: GuideRun | null;
  instruction: string;
  draft_warning: string | null;
  available: boolean;
  phase: 'READY' | 'ERROR' | 'SUBMITTING' | 'UNKNOWN' | 'READING' | 'CONFIRMED';
  submitted: Submitted | null;
  outcome: RunReceipt | null;
  user_message: Message | null;
  error: string | null;
  error_code: string | null;
  needs_refresh: boolean;
  refreshing: boolean;
  active: boolean;
  binding_loaded: boolean;
  observed: Readonly<{
    detail: DetailSnapshot;
    run: GuideRun | null;
    messages: readonly Message[];
  }> | null;
}>;
type Api = Pick<
  WalleApi,
  | 'prepareCreateGuide'
  | 'prepareContinueGuide'
  | 'getGuideRun'
  | 'listMessages'
  | 'getRequirementDetail'
>;
const capture = <T>(value: T): T => snapshotObject(value) as unknown as T;

function discussionTarget(detail: DetailSnapshot): GuideTarget | null {
  const current = detail.current;
  if (current === null || current.id !== (detail.selected_document_id ?? current.id)) return null;
  return {
    document_id: current.id,
    content_version: current.content_version,
    scope: { scope_type: 'DOCUMENT', scope_ref: null },
    label: '整篇文档',
    selection: null,
  };
}
const conflicts = new Set([
  'STATE_CONFLICT',
  'WORK_STATE_CONFLICT',
  'WORK_STATE_INCONSISTENT',
  'DISCUSSION_VERSION_CONFLICT',
  'CONTENT_VERSION_CONFLICT',
  'SOURCE_VERSION_CONFLICT',
  'SOURCE_INVALID',
  'SCOPE_INVALID',
]);
/** One explicit operation, independent of reading selection. A receipt ends
 * the send intention; all later work is actual reads, never another Chat. */
export class RequirementGuideComposer {
  private value: ComposerState;
  private readonly api: Api;
  private readonly drafts: ComposerDrafts;
  private readonly readActual: () => Promise<DetailSnapshot>;
  private readonly adoptActual: (actual: DetailSnapshot) => Promise<void>;
  private readonly receive: (run: Pick<GuideRun, 'id' | 'requirement_id'>) => Promise<void>;
  private readonly refreshMessages: () => Promise<void>;
  private command: ApiAction<RunReceipt> | undefined;
  private pending: Promise<boolean> | undefined;
  private work: string | undefined;
  private readonly listeners = new Set<() => void>();
  private closed = false;
  private epoch = 0;
  private controller: AbortController | undefined;
  private delivered = false;
  private readonly readAccepted: () => Promise<DetailSnapshot>;
  constructor(
    detail: DetailSnapshot,
    api: Api,
    readActual: () => Promise<DetailSnapshot>,
    adoptActual: (actual: DetailSnapshot) => Promise<void>,
    receive: (run: Pick<GuideRun, 'id' | 'requirement_id'>) => Promise<void>,
    refreshMessages: () => Promise<void>,
    drafts = new ComposerDrafts(
      undefined,
      detail.selected_document_id ?? detail.current?.id ?? null,
    ),
    readAccepted = readActual,
  ) {
    this.readAccepted = readAccepted;
    this.api = api;
    this.readActual = readActual;
    this.adoptActual = adoptActual;
    this.receive = receive;
    this.refreshMessages = refreshMessages;
    this.drafts = drafts;
    const draft = drafts.load(detail.requirement.id);
    this.value = Object.freeze({
      detail: capture(detail),
      action: 'DISCUSS',
      target: discussionTarget(detail),
      source_refs: [],
      review: null,
      parent: null,
      instruction: draft.instruction,
      draft_warning: draft.warning,
      available: false,
      phase: 'READY',
      submitted: null,
      outcome: null,
      user_message: null,
      error: null,
      error_code: null,
      needs_refresh: false,
      refreshing: false,
      active: true,
      binding_loaded: false,
      observed: null,
    });
  }
  getSnapshot = (): ComposerState => this.value;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  private publish(changes: Partial<ComposerState>): void {
    if (this.closed) return;
    this.value = Object.freeze({ ...this.value, ...changes });
    for (const listener of this.listeners)
      try {
        listener();
      } catch (error) {
        console.error('WALL-E composer observer failed', error);
      }
  }
  get editable(): boolean {
    return !this.closed && !this.pending && ['READY', 'ERROR'].includes(this.value.phase);
  }
  get allowed(): boolean {
    return this.allows(this.value);
  }

  private allows({ action, target, parent }: SendIntent): boolean {
    const state = this.value;
    if (
      this.closed ||
      state.detail.current === null ||
      !state.available ||
      state.needs_refresh ||
      state.refreshing ||
      state.detail.requirement.document_work_state !== 'IDLE'
    )
      return false;
    if (parent !== null) return true;
    if (target === null) return action === 'DISCUSS';
    const actual = state.detail.documents.find((document) => document.id === target.document_id);
    return (
      actual !== undefined &&
      actual.id === (state.detail.selected_document_id ?? state.detail.current?.id) &&
      actual.content_version === target.content_version &&
      (action === 'DISCUSS' || actual.archived_at === null)
    );
  }
  adopt(detail: DetailSnapshot): void {
    if (detail.requirement.id !== this.value.detail.requirement.id)
      throw TypeError('Owned actual detail required');
    const changed =
      detail.requirement.discussion_version !== this.value.detail.requirement.discussion_version;
    const target = this.value.target;
    const retargetDiscussion =
      this.value.action === 'DISCUSS' &&
      target?.scope.scope_type === 'DOCUMENT' &&
      target.document_id === detail.current?.id;
    this.publish({
      detail: capture(detail),
      ...(changed ? { binding_loaded: false } : {}),
      ...(retargetDiscussion ? { target: discussionTarget(detail) } : {}),
    });
  }
  private sourcesWithAssociations(refs: CreateGuide['source_refs']): CreateGuide['source_refs'] {
    const documentId = this.value.detail.selected_document_id ?? this.value.detail.current?.id;
    const sources = [
      ...this.value.source_refs.filter((ref) => ref.kind !== 'REVISION'),
      ...refs.filter((ref) => ref.kind !== 'REVISION' || ref.document_id !== documentId),
    ];
    return [...new Map(sources.map((ref) => [JSON.stringify(ref), sourceRef(ref)])).values()];
  }
  syncAssociatedSources(refs: CreateGuide['source_refs']): void {
    if (!this.editable) return;
    this.publish({ source_refs: this.sourcesWithAssociations(refs), binding_loaded: true });
  }
  setAvailable(available: boolean): void {
    if (this.closed || available === this.value.available) return;
    this.epoch++;
    this.publish({ available });
    if (!available) this.controller?.abort();
  }
  change(instruction: string): void {
    if (this.editable)
      this.publish({
        instruction,
        draft_warning: this.drafts.save(this.value.detail.requirement.id, instruction),
        error: null,
        error_code: null,
      });
  }
  choose(action: Operation): void {
    if (this.closed || action === this.value.action) return;
    if (action !== 'DISCUSS' && action !== 'REVISE') return;
    this.publish({
      action,
      target: action === 'DISCUSS' ? discussionTarget(this.value.detail) : null,
      parent: null,
      review: null,
    });
  }

  selectDocument(identity: number): void {
    if (!this.editable) return;
    const owner = this.value.detail.selected_document_id ?? this.value.detail.current?.id;
    if (identity !== owner) throw TypeError('请先切换到目标文档，再使用该文档的AI助手');
    const document = this.value.detail.documents.find((item) => item.id === identity);
    if (!document) throw TypeError('Actual target document required');
    this.publish({
      target: {
        document_id: identity,
        content_version: document.content_version,
        label: document.name,
        scope: { scope_type: 'DOCUMENT', scope_ref: null },
        selection: null,
      },
      error: null,
      error_code: null,
    });
  }
  select(target: GuideTarget): boolean {
    if (!this.editable) return false;
    try {
      const current = this.value.detail.current;
      if (
        current === null ||
        target.document_id !== current.id ||
        target.content_version !== current.content_version
      )
        throw Error('Stale scope');
      decodeScope(target.scope);
      this.publish({ target: capture(target), error: null, error_code: null });
      return true;
    } catch {
      this.rejectScope();
      return false;
    }
  }
  rejectScope(): void {
    if (this.editable)
      this.publish({
        error: '范围无法定位，请重新选择；原输入仍保留。',
        error_code: 'SCOPE_INVALID',
      });
  }
  selectChapter(target: GuideTarget): boolean {
    if (target.scope.scope_type !== 'SECTION' || !this.select(target)) return false;
    this.publish({ action: 'REVISE', parent: null, review: null });
    return true;
  }
  useReview(run: GuideRun, target: GuideTarget): boolean {
    if (
      !this.editable ||
      run.requirement_id !== this.value.detail.requirement.id ||
      run.action_type !== 'REVIEW' ||
      run.status !== 'COMPLETED' ||
      !this.select(target)
    )
      return false;
    this.publish({
      action: 'REVISE',
      parent: null,
      review: capture(run),
      source_refs: [
        ...this.value.source_refs.filter((ref) => ref.kind !== 'RUN_RESULT'),
        sourceRef({ kind: 'RUN_RESULT', guide_run_id: run.id }),
      ],
    });
    return true;
  }
  continueFrom(run: GuideRun | null): void {
    if (!this.editable) return;
    if (
      run &&
      (run.requirement_id !== this.value.detail.requirement.id || run.status === 'RUNNING')
    )
      throw TypeError('Owned ended parent required');
    this.choose('DISCUSS');
    this.publish({ parent: run ? capture(run) : null });
  }
  async loadBinding(): Promise<boolean> {
    if (
      this.closed ||
      !(
        ['READY', 'ERROR'].includes(this.value.phase) ||
        (this.work === 'SEND' && this.value.phase === 'READING')
      ) ||
      this.value.binding_loaded
    )
      return false;
    const controller = new AbortController();
    this.controller = controller;
    const epoch = this.epoch;
    try {
      const actual = (
        await this.api.getRequirementDetail(
          this.value.detail.requirement.id,
          controller.signal,
          true,
        )
      ).data;
      if (this.closed || epoch !== this.epoch) return false;
      if (
        actual.requirement.discussion_version !==
          this.value.detail.requirement.discussion_version ||
        actual.discussion === null
      )
        throw Error('Discussion changed');
      const binding = snapshotObject(actual.discussion.binding);
      const refs = binding.source_refs;
      if (!Array.isArray(refs)) throw Error('Invalid sources');
      this.publish({
        source_refs: this.sourcesWithAssociations(refs.map(sourceRef)),
        binding_loaded: true,
      });
      return true;
    } catch {
      if (!this.closed && epoch === this.epoch)
        this.publish({
          error: '讨论绑定暂时无法读取，请重新读取状态；当前输入保留。',
          needs_refresh: true,
        });
      return false;
    } finally {
      if (this.controller === controller) this.controller = undefined;
    }
  }
  private enqueue(kind: string, job: () => Promise<boolean>): Promise<boolean> {
    if (this.closed) return Promise.resolve(false);
    if (this.pending) return this.work === kind ? this.pending : Promise.resolve(false);
    const pending = Promise.resolve()
      .then(job)
      .finally(() => {
        if (this.pending === pending) {
          this.pending = undefined;
          this.publish({});
        }
      });
    this.pending = pending;
    this.work = kind;
    return pending;
  }
  submit(): Promise<boolean> {
    if (!['READY', 'ERROR'].includes(this.value.phase)) return Promise.resolve(false);
    // A mode change prepares the next round; capture this round before any reads await.
    const { action, target, parent, instruction } = this.value;
    const intent = { action, target, parent, instruction };
    const version = this.value.detail.requirement.discussion_version;
    return this.enqueue('SEND', async () => {
      if (!parent && !this.value.binding_loaded) {
        if (!this.allows(intent)) return false;
        this.publish({ phase: 'READING', error: null });
        const loaded = await this.loadBinding();
        if (!loaded) {
          this.publish({ phase: 'ERROR' });
          return false;
        }
        this.publish({ phase: 'READY' });
      }
      if (!this.allows(intent) || this.value.detail.requirement.discussion_version !== version) {
        this.publish({ phase: 'ERROR', error: '请核对讨论版本、工作占用及明确目标。' });
        return false;
      }
      try {
        const state = this.value;
        ordinaryInput(instruction, 'AI 指令', 1, 10000);
        if ([...instruction].length > 10000) throw Error('消息不能超过10000字符');
        this.delivered = false;
        if (parent) {
          this.publish({
            submitted: capture({
              kind: 'CONTINUE',
              parent,
              instruction,
              version,
              raw: instruction,
            }),
            outcome: null,
          });
          this.command = this.api.prepareContinueGuide(parent.id, instruction, version);
        } else {
          const scope = target?.scope;
          const wire =
            scope === undefined
              ? null
              : scope.scope_type === 'SECTION'
                ? {
                    scope_type: 'SECTION',
                    scope_ref: { heading_block_id: scope.scope_ref.block_id },
                  }
                : scope;
          const body: CreateGuide = {
            expected_discussion_version: version,
            operation: action,
            instruction,
            target:
              target === null
                ? null
                : {
                    kind: 'EXISTING',
                    document_id: target.document_id,
                    expected_content_version: target.content_version,
                  },
            scope: wire,
            source_refs: state.source_refs,
            proposal_ref: null,
            acknowledge_source_changes: false,
          };
          this.publish({
            submitted: capture({ kind: 'CREATE', body, raw: instruction }),
            outcome: null,
          });
          this.command = this.api.prepareCreateGuide(state.detail.requirement.id, body);
        }
      } catch (error) {
        this.publish({
          phase: 'ERROR',
          error: error instanceof Error ? error.message : '无法准备发送。',
          error_code: 'INVALID_INPUT',
        });
        return false;
      }
      return (await this.send()) ? this.finishWork() : false;
    });
  }
  private async send(): Promise<boolean> {
    this.publish({ phase: 'SUBMITTING', error: null, error_code: null });
    try {
      const receipt = runReceipt((await this.command!.submit()).data);
      if (this.closed) return false;
      this.command = undefined;
      this.publish({
        phase: 'CONFIRMED',
        outcome: capture(receipt),
        draft_warning: this.drafts.clear(this.value.detail.requirement.id),
      });
      return true;
    } catch (error) {
      if (this.closed) return false;
      if (error instanceof ApiRejected && error.code !== 'REQUEST_IN_PROGRESS') {
        this.command = undefined;
        this.publish({
          phase: 'ERROR',
          error: error.message,
          error_code: error.code,
          needs_refresh: conflicts.has(error.code),
        });
      } else this.publish({ phase: 'UNKNOWN', error: '发送结果待核实，原请求与输入已保留。' });
      return false;
    }
  }
  private async observe() {
    const epoch = this.epoch,
      controller = new AbortController(),
      alive = () => !this.closed && epoch === this.epoch && this.value.available;
    this.controller = controller;
    try {
      if (!alive()) throw Error('View hidden');
      const detail = await this.readActual();
      if (!alive()) throw Error('View hidden');
      if (detail.requirement.id !== this.value.detail.requirement.id)
        throw Error('Foreign actual requirement');
      const messages = (await this.api.listMessages(detail.requirement.id, null, controller.signal))
        .data.items;
      if (!alive()) throw Error('View hidden');
      if (messages.some((message) => message.requirement_id !== detail.requirement.id))
        throw Error('Foreign actual message');
      return capture({ detail, run: null, messages });
    } finally {
      if (this.controller === controller) this.controller = undefined;
    }
  }
  recover(): Promise<boolean> {
    if (this.value.phase !== 'UNKNOWN' || !this.command || !this.value.available)
      return Promise.resolve(false);
    return this.enqueue('RECOVER', async () => {
      this.publish({ phase: 'READING', error: null });
      try {
        this.publish({ observed: await this.observe() });
      } catch {
        this.publish({ phase: 'UNKNOWN', error: '实际资源暂时无法读取，原请求和输入仍保留。' });
        return false;
      }
      return (await this.send()) ? this.finishWork() : false;
    });
  }
  refresh(): Promise<boolean> {
    if (!this.value.available || !['READY', 'ERROR'].includes(this.value.phase))
      return Promise.resolve(false);
    return this.enqueue('REFRESH', async () => {
      this.publish({ refreshing: true });
      try {
        const observed = await this.observe();
        await this.adoptActual(observed.detail);
        this.publish({
          detail: observed.detail,
          observed,
          needs_refresh: false,
          error: null,
          error_code: null,
        });
        return true;
      } catch {
        this.publish({ error: '实际状态暂时无法读取，输入与配置仍保留。' });
        return false;
      } finally {
        this.publish({ refreshing: false });
      }
    });
  }
  finish(): Promise<boolean> {
    if (this.value.phase !== 'CONFIRMED' || !this.value.available) return Promise.resolve(false);
    return this.enqueue('FINISH', () => this.finishWork());
  }
  private async finishWork(): Promise<boolean> {
    const epoch = this.epoch,
      alive = () => !this.closed && this.value.available && epoch === this.epoch;
    this.publish({ refreshing: true });
    try {
      if (!alive()) throw Error('消息已接受，恢复面板后读取实际结果。');
      const receipt = this.value.outcome!,
        submitted = this.value.submitted!;
      const run = (await this.api.getGuideRun(receipt.guide_run_id)).data;
      if (!alive()) throw Error('View hidden');
      if (
        run.requirement_id !== this.value.detail.requirement.id ||
        (submitted.kind === 'CONTINUE' && run.parent_guide_run_id !== submitted.parent.id) ||
        (submitted.kind === 'CREATE' && run.operation !== submitted.body.operation)
      )
        throw Error('运行与原操作不一致。');
      if (!this.delivered) {
        await this.receive(run);
        this.delivered = true;
      }
      if (!alive()) throw Error('View hidden');
      const actual = await this.readAccepted();
      if (!alive()) throw Error('View hidden');
      await this.adoptActual(actual);
      await this.refreshMessages();
      if (!alive()) throw Error('View hidden');
      this.publish({
        detail: capture(actual),
        phase: 'READY',
        instruction: '',
        submitted: null,
        outcome: null,
        user_message: null,
        parent: null,
        observed: null,
        error: null,
        error_code: null,
        needs_refresh: false,
      });
      return true;
    } catch (error) {
      this.publish({
        error: error instanceof Error ? error.message : '已接受发送，实际资源暂时无法读取。',
      });
      return false;
    } finally {
      this.publish({ refreshing: false });
    }
  }
  dispose(): void {
    if (this.closed) return;
    this.publish({ active: false, available: false });
    this.closed = true;
    this.epoch++;
    this.controller?.abort();
    this.listeners.clear();
  }
}
