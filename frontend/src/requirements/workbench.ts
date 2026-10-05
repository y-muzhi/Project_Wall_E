import type { WalleApi } from '../api/walle.ts';
import type { RequirementSummary } from '../api/models.ts';
import { requirementStatuses, requirementTypes } from '../api/models.ts';
import { ApiRejected, positiveInteger, snapshotObject } from '../api/client.ts';
import type { PagePagination } from '../api/client.ts';
import { ordinaryInput } from '../shared/text.ts';

export type WorkbenchQuery = Readonly<{ keyword: string; status: readonly (typeof requirementStatuses[number])[];
  requirement_type: readonly (typeof requirementTypes[number])[]; page: number }>;
export type WorkbenchResult = Readonly<{ items: readonly RequirementSummary[]; pagination: PagePagination }>;
export type WorkbenchState = Readonly<{ requested: WorkbenchQuery; confirmed: WorkbenchQuery | null; result: WorkbenchResult | null; loading: boolean; error: string | null; field_error: string | null }>;
export const defaultWorkbenchQuery: WorkbenchQuery = Object.freeze({ keyword: '', status: requirementStatuses, requirement_type: requirementTypes, page: 1 });
function enumeration<T extends string>(value: readonly T[], allowed: readonly T[]): readonly T[] {
  if (!Array.isArray(value) || !value.length || new Set(value).size !== value.length || value.some(item => !allowed.includes(item))) throw new TypeError('Invalid selected values');
  return Object.freeze(allowed.filter(item => value.includes(item)));
}
export function workbenchQuery(value: WorkbenchQuery): WorkbenchQuery {
  const captured = snapshotObject(value);
  if (Object.keys(captured).sort().join(',') !== 'keyword,page,requirement_type,status') throw new TypeError('Invalid query fields');
  const page = positiveInteger(captured.page); if (page > 100000) throw new TypeError('Invalid page');
  return Object.freeze({ keyword: ordinaryInput(captured.keyword as string, 'keyword', 0, 100, false),
    status: enumeration(captured.status as WorkbenchQuery['status'], requirementStatuses),
    requirement_type: enumeration(captured.requirement_type as WorkbenchQuery['requirement_type'], requirementTypes), page });
}
const same = (left: WorkbenchQuery, right: WorkbenchQuery) => JSON.stringify(left) === JSON.stringify(right);
export type WorkbenchPhase = 'LOADING' | 'READY' | 'EMPTY' | 'NO_MATCH' | 'OUT_OF_RANGE' | 'REFRESHING' | 'ERROR' | 'REFRESH_ERROR';

export class RequirementWorkbench {
  private readonly api: Pick<WalleApi, 'listRequirements'>;
  private readonly listeners = new Set<(state: WorkbenchState) => void>();
  private value: WorkbenchState;
  private generation = 0; private controller: AbortController | undefined; private pending: Promise<void> | undefined; private closed = false;
  constructor(api: Pick<WalleApi, 'listRequirements'>, restored: WorkbenchQuery = defaultWorkbenchQuery) {
    this.api = api; this.value = Object.freeze({ requested: workbenchQuery(restored), confirmed: null, result: null, loading: false, error: null, field_error: null });
  }
  get state(): WorkbenchState { return this.value; }
  get phase(): WorkbenchPhase {
    if (!this.value.result) return this.value.error ? 'ERROR' : 'LOADING';
    if (this.value.loading) return 'REFRESHING'; if (this.value.error) return 'REFRESH_ERROR';
    const { pagination, items } = this.value.result;
    if (pagination.total && pagination.page > pagination.total_pages) return 'OUT_OF_RANGE';
    if (items.length) return 'READY';
    const query = this.value.confirmed!;
    return query.keyword || query.status.length < requirementStatuses.length || query.requirement_type.length < requirementTypes.length ? 'NO_MATCH' : 'EMPTY';
  }
  subscribe(listener: (state: WorkbenchState) => void): () => void { this.listeners.add(listener); listener(this.value); return () => this.listeners.delete(listener); }
  private publish(changes: Partial<WorkbenchState>): void {
    if (this.closed) return; this.value = Object.freeze({ ...this.value, ...changes });
    for (const listener of this.listeners) { try { listener(this.value); } catch (error) { console.error('WALL-E workbench observer failed', error); } }
  }
  query(input: WorkbenchQuery = this.value.requested, force = false): Promise<void> {
    if (this.closed) return Promise.resolve();
    const query = workbenchQuery(input);
    if (!force && same(query, this.value.requested)) {
      if (this.pending) return this.pending;
      if (this.value.result && this.value.confirmed && same(query, this.value.confirmed) && !this.value.error) return Promise.resolve();
    }
    const generation = ++this.generation; this.controller?.abort();
    const controller = new AbortController(); this.controller = controller;
    const pending = Promise.resolve().then(async () => {
      if (this.closed || generation !== this.generation) return;
      try {
        const response = await this.api.listRequirements({ ...(query.keyword ? { keyword: query.keyword } : {}),
          ...(query.status.length === requirementStatuses.length ? {} : { status: query.status }),
          ...(query.requirement_type.length === requirementTypes.length ? {} : { requirement_type: query.requirement_type }), page: query.page }, controller.signal);
        if (this.closed || generation !== this.generation) return;
        const pagination = response.meta.pagination;
        if (!pagination || !('page' in pagination) || pagination.page !== query.page) throw new TypeError('Actual matching page required');
        this.publish({ confirmed: query, result: Object.freeze({ items: response.data.items, pagination: Object.freeze({ ...pagination }) }), loading: false, error: null, field_error: null });
      } catch (error) {
        if (this.closed || generation !== this.generation) return;
        this.publish({ loading: false, error: error instanceof ApiRejected ? error.message : '暂时无法读取需求，请重试',
          field_error: error instanceof ApiRejected && error.code === 'VALIDATION_FAILED' ? error.message : null });
      }
    }).finally(() => { if (this.pending === pending) this.pending = undefined; });
    this.pending = pending; this.publish({ requested: query, loading: true, error: null, field_error: null }); return pending;
  }
  refresh(): Promise<void> { return this.query(this.value.requested, true); }
  /** Stop only this page's read, retaining the last confirmed list for return. */
  pause(): void { if(this.closed)return;this.generation++;this.controller?.abort();this.controller=undefined;this.pending=undefined;this.publish({loading:false}); }
  dispose(): void { this.closed = true; this.generation++; this.controller?.abort(); this.listeners.clear(); }
}
