import { ApiRejected, snapshotObject } from '../api/client.ts';
import type { ApiAction, DiscussionCommand, WalleApi } from '../api/walle.ts';
import { discussionState } from '../api/models.ts';
import type { DiscussionState, RequirementDetail } from '../api/models.ts';
type Result = Awaited<
  ReturnType<ReturnType<WalleApi['prepareUpdateDiscussion']>['submit']>
>['data'];
type Api = Pick<WalleApi, 'getRequirementDetail' | 'prepareUpdateDiscussion'>;
export type DiscussionViewState = Readonly<{
  detail: RequirementDetail;
  discussion: DiscussionState | null;
  version: number | null;
  loading: boolean;
  phase: 'READY' | 'SUBMITTING' | 'UNKNOWN' | 'CONFIRMED' | 'ERROR';
  command: DiscussionCommand | null;
  receipt: Result | null;
  error: string | null;
}>;
/** Lazy read and one retained program command; never prepares a GuideRun. */
export class RequirementDiscussion {
  private value: DiscussionViewState;
  private readonly api: Api;
  private readonly refresh: () => Promise<RequirementDetail>;
  private action: ApiAction<Result> | undefined;
  private pending: Promise<boolean> | undefined;
  private finishing: Promise<boolean> | undefined;
  private controller: AbortController | undefined;
  private generation = 0;
  private closed = false;
  private readonly listeners = new Set<() => void>();
  constructor(detail: RequirementDetail, api: Api, refresh: () => Promise<RequirementDetail>) {
    this.api = api;
    this.refresh = refresh;
    this.value = Object.freeze({
      detail,
      discussion: null,
      version: null,
      loading: false,
      phase: 'READY',
      command: null,
      receipt: null,
      error: null,
    });
  }
  getSnapshot = (): DiscussionViewState => this.value;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  get allowed(): boolean {
    return (
      !this.closed &&
      !this.pending &&
      !this.value.loading &&
      ['READY', 'ERROR'].includes(this.value.phase) &&
      this.value.detail.requirement.document_work_state === 'IDLE' &&
      this.value.version === this.value.detail.requirement.discussion_version
    );
  }
  private publish(changes: Partial<DiscussionViewState>): void {
    if (this.closed) return;
    this.value = Object.freeze({ ...this.value, ...changes });
    for (const listener of this.listeners)
      try {
        listener();
      } catch (error) {
        console.error('WALL-E discussion observer failed', error);
      }
  }
  adopt(detail: RequirementDetail): void {
    if (detail.requirement.id !== this.value.detail.requirement.id)
      throw TypeError('Actual owned detail required');
    this.publish({ detail });
  }
  async load(): Promise<boolean> {
    if (this.closed) return false;
    const generation = ++this.generation,
      controller = new AbortController();
    this.controller?.abort();
    this.controller = controller;
    this.publish({ loading: true, error: null });
    try {
      const actual = (
        await this.api.getRequirementDetail(
          this.value.detail.requirement.id,
          controller.signal,
          true,
        )
      ).data;
      if (this.closed || generation !== this.generation) return false;
      if (actual.requirement.id !== this.value.detail.requirement.id || actual.discussion === null)
        throw Error('Actual expanded discussion required');
      if (actual.requirement.discussion_version < this.value.detail.requirement.discussion_version)
        throw Error('Stale expanded read');
      this.publish({
        discussion: discussionState(actual.discussion),
        version: actual.requirement.discussion_version,
        loading: false,
        error: null,
      });
      return true;
    } catch {
      if (!this.closed && generation === this.generation)
        this.publish({ loading: false, error: '讨论进展读取失败，已显示内容仍保留。' });
      return false;
    }
  }
  pauseRead(): void {
    this.generation++;
    this.controller?.abort();
    this.publish({ loading: false });
  }
  submit(command: DiscussionCommand): Promise<boolean> {
    if (!this.allowed) return Promise.resolve(false);
    const captured = snapshotObject(command) as unknown as DiscussionCommand;
    this.action = this.api.prepareUpdateDiscussion(this.value.detail.requirement.id, {
      expected_discussion_version: this.value.version!,
      discussion_command: captured,
    });
    this.publish({ command: captured, receipt: null, error: null });
    return this.send();
  }
  private send(): Promise<boolean> {
    if (this.closed || !this.action) return Promise.resolve(false);
    if (this.pending) return this.pending;
    const action = this.action;
    const pending = Promise.resolve()
      .then(async () => {
        this.publish({ phase: 'SUBMITTING', error: null });
        try {
          const receipt = (await action.submit()).data;
          if (this.closed) return false;
          this.action = undefined;
          this.publish({
            phase: 'CONFIRMED',
            receipt,
            discussion: receipt.discussion,
            version: receipt.discussion_version,
          });
          return await this.finish();
        } catch (error) {
          if (this.closed) return false;
          if (this.value.phase === 'CONFIRMED')
            this.publish({ error: '讨论调整已保存，暂时无法读取最新详情。' });
          else if (error instanceof ApiRejected && error.code !== 'REQUEST_IN_PROGRESS') {
            this.action = undefined;
            this.publish({ phase: 'ERROR', error: error.message });
          } else
            this.publish({ phase: 'UNKNOWN', error: '讨论调整结果待核实，原请求与输入已保留。' });
          return false;
        }
      })
      .finally(() => {
        if (this.pending === pending) {
          this.pending = undefined;
          this.publish({});
        }
      });
    this.pending = pending;
    return pending;
  }
  retryUnknown(): Promise<boolean> {
    return this.value.phase === 'UNKNOWN' ? this.send() : Promise.resolve(false);
  }
  finish(): Promise<boolean> {
    if (this.finishing) return this.finishing;
    if (this.closed || this.value.phase !== 'CONFIRMED') return Promise.resolve(false);
    const pending = Promise.resolve()
      .then(async () => {
        try {
          const actual = await this.refresh();
          if (this.closed) return false;
          this.adopt(actual);
          if (!(await this.load())) return false;
          this.publish({ phase: 'READY', command: null, receipt: null, error: null });
          return true;
        } catch {
          this.publish({ error: '讨论调整已保存，暂时无法读取最新详情。' });
          return false;
        }
      })
      .finally(() => {
        if (this.finishing === pending) this.finishing = undefined;
      });
    this.finishing = pending;
    return pending;
  }
  dispose(): void {
    this.closed = true;
    this.generation++;
    this.controller?.abort();
    this.listeners.clear();
  }
}
