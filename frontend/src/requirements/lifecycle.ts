import { ApiRejected, snapshotObject } from '../api/client.ts';
import type { WalleApi } from '../api/walle.ts';
import { requirementStatuses } from '../api/models.ts';
import type { Requirement } from '../api/models.ts';
import type { DetailSnapshot } from './detail-read.ts';

export type LifecycleOperation = Requirement['status'];
export type LifecycleOutcome = Readonly<{ kind: 'STATUS'; requirement: Requirement }>;
export type LifecycleState = Readonly<{
  phase: 'READY' | 'SUBMITTING' | 'READING' | 'UNKNOWN' | 'ERROR' | 'CONFIRMED';
  actual: Requirement;
  target_status: LifecycleOperation;
  error: string | null;
  outcome: LifecycleOutcome | null;
}>;
type Api = Pick<WalleApi, 'prepareUpdateRequirement'>;
const capture = <T>(value: T): T => snapshotObject(value) as unknown as T;

/** Manual business metadata only. Occupancy, content and draft lifetimes are
 * independent. UNKNOWN replays the exact original action, without rebuilding
 * its body from a later GET or from the currently selected document. */
export class RequirementLifecycle {
  private value: LifecycleState;
  private readonly api: Api;
  private action: ReturnType<Api['prepareUpdateRequirement']> | undefined;
  private pending: Promise<boolean> | undefined;
  private disposed = false;
  private readonly listeners = new Set<() => void>();
  constructor(operation: LifecycleOperation, initial: DetailSnapshot, api: Api) {
    if (!requirementStatuses.includes(operation))
      throw TypeError('A manual business status is required');
    this.api = api;
    this.value = Object.freeze({
      phase: 'READY',
      actual: capture(initial.requirement),
      target_status: operation,
      error: null,
      outcome: null,
    });
  }
  get operation(): LifecycleOperation {
    return this.value.target_status;
  }
  getSnapshot = (): LifecycleState => this.value;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  private publish(changes: Partial<LifecycleState>): void {
    if (this.disposed) return;
    this.value = Object.freeze({ ...this.value, ...changes });
    for (const listener of this.listeners)
      try {
        listener();
      } catch (error) {
        console.error('WALL-E status observer failed', error);
      }
  }
  select(status: LifecycleOperation): Promise<boolean> {
    if (this.disposed || this.pending || !['READY', 'ERROR'].includes(this.value.phase))
      return Promise.resolve(false);
    if (status === this.value.actual.status) return Promise.resolve(false);
    if (!requirementStatuses.includes(status)) throw TypeError('Invalid manual business status');
    this.publish({ target_status: status, error: null });
    return this.submit();
  }
  submit(): Promise<boolean> {
    if (this.disposed || this.value.phase === 'CONFIRMED') return Promise.resolve(false);
    if (this.pending) return this.pending;
    if (!this.action) {
      if (this.value.target_status === this.value.actual.status) return Promise.resolve(false);
      this.action = this.api.prepareUpdateRequirement(this.value.actual.id, {
        expected_metadata_version: this.value.actual.metadata_version,
        changes: { status: this.value.target_status },
      });
    }
    const original = this.action;
    const pending = Promise.resolve()
      .then(async () => {
        if (this.disposed) return false;
        this.publish({ phase: 'SUBMITTING', error: null });
        try {
          const actual = (await original.submit()).data;
          if (this.disposed) return false;
          if (actual.id !== this.value.actual.id || actual.status !== this.value.target_status)
            throw Error('Status receipt does not match the original command');
          const outcome = capture({ kind: 'STATUS' as const, requirement: actual });
          this.publish({ phase: 'CONFIRMED', actual: capture(actual), outcome, error: null });
          this.action = undefined;
          return true;
        } catch (error) {
          if (this.disposed) return false;
          if (error instanceof ApiRejected && error.code !== 'REQUEST_IN_PROGRESS') {
            this.action = undefined;
            this.publish({ phase: 'ERROR', error: error.message });
          } else this.publish({ phase: 'UNKNOWN', error: '状态变更结果待核实，请核实原请求' });
          return false;
        }
      })
      .finally(() => {
        if (this.pending === pending) this.pending = undefined;
      });
    this.pending = pending;
    return pending;
  }
  retryUnknown(): Promise<boolean> {
    return this.value.phase === 'UNKNOWN' && this.action ? this.submit() : Promise.resolve(false);
  }
  dispose(): void {
    this.disposed = true;
    this.listeners.clear();
  }
}
