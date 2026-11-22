/** Read-only document owner. Server focus, displayed selection and AI targets stay separate. */
import { ApiRejected, ApiUnknown, positiveInteger } from '../api/client.ts';
import type { WalleApi } from '../api/walle.ts';
import { stepRef } from '../api/formation-values.ts';
import type { FormationSummary, FormationStepDetail } from '../api/formation-values.ts';
type Port = Pick<WalleApi, 'getFormationSummary' | 'getFormationSteps' | 'getFormationStep'>;
type StepPage = Awaited<ReturnType<WalleApi['getFormationSteps']>>;
export type ReadBox<T> = Readonly<{
  phase: 'IDLE' | 'LOADING' | 'READY' | 'ERROR';
  data: T | null;
  error: string | null;
}>;
export type FormationReadState = Readonly<{
  summary: ReadBox<FormationSummary>;
  page: ReadBox<StepPage>;
  detail: ReadBox<FormationStepDetail>;
  selected_step_ref: string | null;
  show_cancelled: boolean;
  page_cursor: string | null;
}>;
const idle = <T>(): ReadBox<T> => Object.freeze({ phase: 'IDLE', data: null, error: null });
const loading = <T>(previous: ReadBox<T>): ReadBox<T> =>
  Object.freeze({ ...previous, phase: 'LOADING', error: null });
const ready = <T>(data: T): ReadBox<T> => Object.freeze({ phase: 'READY', data, error: null });
const failed = <T>(previous: ReadBox<T>, message: string): ReadBox<T> =>
  Object.freeze({ ...previous, phase: 'ERROR', error: message });
const stale = (error: unknown) =>
  error instanceof ApiRejected &&
  error.code === 'STATE_CONFLICT' &&
  (error.details?.reason === 'PATH_CHANGED' ||
    error.details?.reason === 'FORMATION_NOT_INITIALIZED');
const message = (error: unknown, fallback: string) =>
  error instanceof ApiRejected ? error.message : fallback;

export class FormationReadOwner {
  private value: FormationReadState = Object.freeze({
    summary: idle<FormationSummary>(),
    page: idle<StepPage>(),
    detail: idle<FormationStepDetail>(),
    selected_step_ref: null,
    show_cancelled: false,
    page_cursor: null,
  });
  private readonly listeners = new Set<() => void>();
  private readonly requirementId: number;
  private readonly documentId: number;
  private readonly api: Port;
  private generation = 0;
  private pageEpoch = 0;
  private detailEpoch = 0;
  private closed = false;
  private summaryController: AbortController | null = null;
  private pageController: AbortController | null = null;
  private detailController: AbortController | null = null;
  private recovery: Promise<boolean> | null = null;

  constructor(requirementId: number, documentId: number, api: Port) {
    this.requirementId = positiveInteger(requirementId);
    this.documentId = positiveInteger(documentId);
    this.api = api;
  }
  getSnapshot = (): FormationReadState => this.value;
  subscribe = (listener: () => void): (() => void) => {
    if (this.closed) return () => {};
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  private publish(update: Partial<FormationReadState>): void {
    if (this.closed) return;
    this.value = Object.freeze({ ...this.value, ...update });
    for (const listener of this.listeners) listener();
  }
  private live(generation: number): boolean {
    return !this.closed && generation === this.generation;
  }
  restoreDisplay(selected: string | null, showCancelled: boolean): void {
    if (selected !== null) stepRef(selected);
    if (this.value.summary.phase !== 'IDLE') throw TypeError('Initial display restoration only');
    this.publish({ selected_step_ref: selected, show_cancelled: showCancelled });
  }
  observeSummary(summary: FormationSummary): void {
    if (this.closed) return;
    if (summary.document_id !== this.documentId)
      throw TypeError('Owned formation summary required');
    this.generation++;
    this.pageEpoch++;
    this.detailEpoch++;
    this.summaryController?.abort();
    this.pageController?.abort();
    this.detailController?.abort();
    const changed = summary.formation_version !== this.value.summary.data?.formation_version;
    this.publish({
      summary: ready(summary),
      ...(changed
        ? { page: idle<StepPage>(), page_cursor: null, detail: idle<FormationStepDetail>() }
        : {}),
    });
  }
  refresh(): Promise<boolean> {
    return this.readSummary(true);
  }
  private async readSummary(allowRecovery: boolean): Promise<boolean> {
    if (this.closed) return false;
    const generation = ++this.generation;
    this.pageEpoch++;
    this.detailEpoch++;
    this.summaryController?.abort();
    this.pageController?.abort();
    this.detailController?.abort();
    const controller = new AbortController();
    this.summaryController = controller;
    const oldF = this.value.summary.data?.formation_version;
    this.publish({ summary: loading(this.value.summary), page: loading(this.value.page) });
    try {
      const response = await this.api.getFormationSummary(
        this.requirementId,
        this.documentId,
        controller.signal,
      );
      if (!this.live(generation)) return false;
      const summary = response.data;
      if (summary.document_id !== this.documentId) throw new ApiUnknown(false);
      const cursor = oldF === summary.formation_version ? this.value.page_cursor : null;
      this.publish({ summary: ready(summary), page_cursor: cursor });
      if (!summary.exists) {
        this.publish({ page: idle<StepPage>(), detail: idle<FormationStepDetail>() });
        return true;
      }
      const page = this.readPage(cursor, allowRecovery);
      const selected = this.value.selected_step_ref;
      const detail =
        selected === null ? Promise.resolve(true) : this.readDetail(selected, allowRecovery);
      const [pageLoaded, detailLoaded] = await Promise.all([page, detail]);
      return pageLoaded && detailLoaded;
    } catch (error) {
      if (!this.live(generation)) return false;
      this.publish({
        summary: failed(this.value.summary, message(error, '暂时无法读取主线，请重试')),
        page: failed(this.value.page, '主线摘要未能刷新，已保留上次读取的内容'),
        ...(this.value.selected_step_ref === null
          ? {}
          : { detail: failed(this.value.detail, '主线摘要未能刷新，已保留上次读取的详情') }),
      });
      return false;
    } finally {
      if (this.summaryController === controller) this.summaryController = null;
    }
  }
  async loadPage(cursor: string | null): Promise<boolean> {
    if (cursor !== null && (!cursor.length || cursor.length > 4096))
      throw new TypeError('Invalid cursor');
    return this.readPage(cursor, true);
  }
  async revealStep(ref: string): Promise<boolean> {
    stepRef(ref);
    if (
      this.value.page.phase === 'READY' &&
      this.value.page.data?.data.items.some((step) => step.step_ref === ref)
    )
      return true;
    return this.readPage(null, false, ref);
  }
  async setShowCancelled(value: boolean): Promise<boolean> {
    if (typeof value !== 'boolean') throw new TypeError('Invalid display preference');
    if (value === this.value.show_cancelled) return true;
    this.publish({ show_cancelled: value, page_cursor: null });
    return this.readPage(null, true);
  }
  private recover(generation: number): Promise<boolean> {
    if (!this.live(generation)) return Promise.resolve(false);
    if (this.recovery !== null) return this.recovery;
    const pending = this.readSummary(false);
    this.recovery = pending;
    void pending.finally(() => {
      if (this.recovery === pending) this.recovery = null;
    });
    return pending;
  }
  private async readPage(
    cursor: string | null,
    allowRecovery: boolean,
    reveal: string | null = null,
  ): Promise<boolean> {
    const summary = this.value.summary.data;
    if (this.closed || summary === null || !summary.exists || summary.formation_version === null)
      return false;
    const generation = this.generation,
      epoch = ++this.pageEpoch;
    this.pageController?.abort();
    const controller = new AbortController();
    this.pageController = controller;
    const filter = this.value.show_cancelled;
    this.publish({
      page: loading(this.value.page),
      ...(reveal === null ? { page_cursor: cursor } : {}),
    });
    const visited = new Set<string | null>();
    let next = cursor;
    try {
      while (!visited.has(next)) {
        visited.add(next);
        const response = await this.api.getFormationSteps(
          this.requirementId,
          this.documentId,
          {
            limit: 20,
            known_f: summary.formation_version,
            include_cancelled: filter,
            ...(next === null ? {} : { cursor: next }),
          },
          controller.signal,
        );
        if (!this.live(generation) || epoch !== this.pageEpoch) return false;
        if (
          response.data.document_id !== this.documentId ||
          response.data.formation_version !== summary.formation_version
        )
          throw new ApiUnknown(false);
        if (reveal === null || response.data.items.some((step) => step.step_ref === reveal)) {
          this.publish({ page: ready(response), page_cursor: next });
          return true;
        }
        if (response.meta.pagination.next_cursor === null) break;
        next = response.meta.pagination.next_cursor;
      }
      this.publish({ page: failed(this.value.page, '当前路线中未找到该步骤，请刷新主线') });
      return false;
    } catch (error) {
      if (!this.live(generation) || epoch !== this.pageEpoch) return false;
      if (stale(error) && allowRecovery) return this.recover(generation);
      this.publish({ page: failed(this.value.page, message(error, '暂时无法读取步骤，请重试')) });
      return false;
    } finally {
      if (this.pageController === controller) this.pageController = null;
    }
  }
  async selectStep(ref: string | null): Promise<boolean> {
    if (ref !== null) stepRef(ref);
    if (this.closed) return false;
    const same = ref === this.value.selected_step_ref;
    this.detailEpoch++;
    this.detailController?.abort();
    this.publish({
      selected_step_ref: ref,
      detail: same ? this.value.detail : idle<FormationStepDetail>(),
    });
    if (ref === null) return true;
    if (this.value.summary.phase !== 'READY') return this.readSummary(true);
    if (this.value.summary.data?.exists !== true) {
      this.publish({ detail: failed(this.value.detail, '该文档尚未形成主线，无法读取所选步骤') });
      return false;
    }
    return this.readDetail(ref, true);
  }
  private async readDetail(ref: string, allowRecovery: boolean): Promise<boolean> {
    const summary = this.value.summary.data;
    if (summary?.formation_version == null || !summary.exists || this.closed) return false;
    const generation = this.generation,
      epoch = ++this.detailEpoch;
    this.detailController?.abort();
    const controller = new AbortController();
    this.detailController = controller;
    this.publish({ detail: loading(this.value.detail) });
    try {
      const response = await this.api.getFormationStep(
        this.requirementId,
        this.documentId,
        ref,
        summary.formation_version,
        controller.signal,
      );
      if (
        !this.live(generation) ||
        epoch !== this.detailEpoch ||
        this.value.selected_step_ref !== ref
      )
        return false;
      if (response.data.step_ref !== ref) throw new ApiUnknown(false);
      this.publish({ detail: ready(response.data) });
      return true;
    } catch (error) {
      if (!this.live(generation) || epoch !== this.detailEpoch) return false;
      if (stale(error) && allowRecovery) return this.recover(generation);
      this.publish({
        detail: failed(this.value.detail, message(error, '暂时无法读取所选步骤，请重试')),
      });
      return false;
    } finally {
      if (this.detailController === controller) this.detailController = null;
    }
  }
  dispose(): void {
    if (this.closed) return;
    this.closed = true;
    this.generation++;
    this.summaryController?.abort();
    this.pageController?.abort();
    this.detailController?.abort();
    this.listeners.clear();
  }
}
