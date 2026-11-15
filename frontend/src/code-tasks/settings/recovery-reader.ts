/** A page-owned reader of durable original commands. It cannot dispatch mutations. */
import { ApiRejected, ApiUnknown } from '../../api/client.ts';
import { CommandStorageError } from '../command-recovery-store.ts';
import type { CommandRecovery, RecoveryLookup } from '../command-recovery.ts';
import type { CommandRecoveryStore } from '../command-recovery-store.ts';
import type { PendingSummary } from '../command-recovery-model.ts';

export type RecoveryReaderPort = Pick<CommandRecovery, 'lookup' | 'reconcileOperation'> & {
  store: Pick<CommandRecoveryStore, 'list'>;
};
export type RecoveryListState = Readonly<{
  records: readonly PendingSummary[] | null;
  loading: boolean;
  error: string | null;
  rowErrors: Readonly<Record<string, string>>;
}>;
function message(error: unknown): string {
  if (
    error instanceof CommandStorageError ||
    error instanceof ApiRejected ||
    error instanceof ApiUnknown
  )
    return error.message;
  return '暂时无法核对原结果，请保留记录后重试';
}
export class RecoveryListReader {
  private value: RecoveryListState = Object.freeze({
    records: null,
    loading: false,
    error: null,
    rowErrors: Object.freeze({}),
  });
  private readonly listeners = new Set<() => void>();
  private readonly recovery: RecoveryReaderPort;
  private readonly onResult?: (
    record: PendingSummary,
    result: RecoveryLookup,
    signal: AbortSignal,
  ) => Promise<void>;
  private request: AbortController | null = null;
  private epoch = 0;
  private closed = false;
  constructor(
    recovery: RecoveryReaderPort,
    onResult?: (
      record: PendingSummary,
      result: RecoveryLookup,
      signal: AbortSignal,
    ) => Promise<void>,
  ) {
    this.recovery = recovery;
    if (onResult) this.onResult = onResult;
  }
  getSnapshot = (): RecoveryListState => this.value;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  private publish(changes: Partial<RecoveryListState>) {
    if (this.closed) return;
    this.value = Object.freeze({ ...this.value, ...changes });
    for (const listener of this.listeners) listener();
  }
  async refresh(): Promise<void> {
    if (this.closed || this.request !== null) return;
    const request = new AbortController();
    this.request = request;
    const epoch = ++this.epoch;
    const current = () => !this.closed && epoch === this.epoch && !request.signal.aborted;
    this.publish({ loading: true, error: null });
    try {
      const records = await this.recovery.store.list();
      if (!current()) return;
      this.publish({ records, rowErrors: Object.freeze({}) });
      const errors: Record<string, string> = {};
      for (const record of records) {
        if (!current()) return;
        try {
          const result = await this.recovery.lookup(record.key, request.signal);
          if (!current()) return;
          await this.onResult?.(record, result, request.signal);
          if (!current()) return;
          const local = result.local;
          if (local !== null && !('final_state' in local) && local.status === 'ACCEPTED')
            await this.recovery.reconcileOperation(record.key, request.signal);
        } catch (error) {
          if (!current()) return;
          errors[record.key] = message(error);
        }
      }
      const latest = await this.recovery.store.list();
      if (current()) this.publish({ records: latest, rowErrors: Object.freeze(errors) });
    } catch (error) {
      if (current()) this.publish({ error: message(error) });
    } finally {
      if (current()) this.publish({ loading: false });
      if (this.request === request) this.request = null;
    }
  }
  pause(): void {
    ++this.epoch;
    this.request?.abort();
    this.request = null;
    this.publish({ loading: false });
  }
  dispose(): void {
    this.pause();
    this.closed = true;
    this.listeners.clear();
  }
}
