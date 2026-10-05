import { positiveInteger } from '../api/client.ts';
import type { GuideRun } from '../api/models.ts';

export type PollingState = Readonly<{ confirmed: GuideRun | null; querying: boolean; connection_error: boolean; polling: boolean }>;
export interface PollClock { schedule: (callback: () => void, milliseconds: number) => () => void; }
const clock: PollClock = { schedule(callback, milliseconds) { const timer = setTimeout(callback, milliseconds); return () => clearTimeout(timer); } };
const delays = [2000, 5000, 10000, 30000] as const;

/** One owned read at a time. Visibility/lifetime never cancels AI business. */
export class GuideRunPolling {
  private readonly identity: number; private readonly read: (identity: number, signal: AbortSignal) => Promise<GuideRun>;
  private readonly clock: PollClock;
  private visible = false; private disposed = false; private generation = 0; private failures = 0;
  private cancelTimer: (() => void) | undefined; private controller: AbortController | undefined;
  private pending: Promise<void> | undefined; private refreshRequested = false;
  private value: PollingState = Object.freeze({ confirmed: null, querying: false, connection_error: false, polling: false });
  private readonly listeners = new Set<(state: PollingState) => void>();
  constructor(identity: number, read: (identity: number, signal: AbortSignal) => Promise<GuideRun>, timing: PollClock = clock) {
    this.identity = positiveInteger(identity); this.read = read; this.clock = timing;
  }
  get state(): PollingState { return this.value; }
  subscribe(listener: (state: PollingState) => void): () => void { this.listeners.add(listener); listener(this.value); return () => this.listeners.delete(listener); }
  private publish(changes: Partial<PollingState>): void { this.value = Object.freeze({ ...this.value, ...changes }); for (const listener of this.listeners) listener(this.value); }
  setVisible(visible: boolean): void {
    if (this.disposed || visible === this.visible) return;
    this.visible = visible; this.generation++; this.cancelTimer?.(); this.cancelTimer = undefined;
    if (!visible) { this.refreshRequested = false; this.controller?.abort(); this.publish({ querying: false, polling: false }); }
    else { this.failures = 0; this.refresh(); }
  }
  /** Called after accepted continuation/re-entry; STOP states are read afresh. */
  refresh(): void {
    if (!this.visible || this.disposed) return;
    this.cancelTimer?.(); this.cancelTimer = undefined;
    if (this.pending) { this.refreshRequested = true; return; }
    this.startRead();
  }
  private schedule(milliseconds: number): void {
    const generation = this.generation;
    this.cancelTimer = this.clock.schedule(() => {
      this.cancelTimer = undefined;
      if (this.visible && !this.disposed && generation === this.generation) this.refresh();
    }, milliseconds);
  }
  private startRead(): void {
    const generation = this.generation, controller = new AbortController(); this.controller = controller;
    // Enter a microtask so pending is installed before even a synchronous read
    // fixture or subscribed callback can request another poll.
    this.pending = Promise.resolve().then(async () => {
      let next: number | null = null;
      try {
        if (generation !== this.generation || this.disposed || !this.visible) return;
        this.publish({ querying: true, polling: true });
        const result = await this.read(this.identity, controller.signal);
        if (generation !== this.generation || this.disposed || !this.visible) return;
        if (result.id !== this.identity) throw new TypeError('Status belongs to another run');
        this.failures = 0; next = result.status === 'RUNNING' ? 1000 : null;
        this.publish({ confirmed: result, querying: false, connection_error: false, polling: next !== null });
      } catch {
        if (generation !== this.generation || this.disposed || !this.visible) return;
        next = delays[Math.min(this.failures++, delays.length - 1)]!;
        this.publish({ querying: false, connection_error: true, polling: true });
      } finally {
        this.pending = undefined; if (this.controller === controller) this.controller = undefined;
        if (!this.visible || this.disposed) return;
        if (this.refreshRequested || generation !== this.generation) { this.refreshRequested = false; this.startRead(); }
        else if (next !== null) this.schedule(next);
      }
    });
  }
  dispose(): void {
    if (this.disposed) return;
    this.disposed = true; this.visible = false; this.generation++; this.cancelTimer?.(); this.cancelTimer = undefined;
    this.refreshRequested = false; this.controller?.abort(); this.listeners.clear();
    this.value = Object.freeze({ ...this.value, querying: false, polling: false });
  }
}
