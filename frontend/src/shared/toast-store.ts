export type ToastType = 'success' | 'error' | 'info';
/** Call only with the original positive command outcome, never a GET match. */
export type ConfirmedNotice = (receipt: object, message: string) => void;
export type Toast = Readonly<{ id: number; type: ToastType; message: string }>;
export interface ToastClock { now(): number; schedule(callback: () => void, milliseconds: number): () => void; }
const realClock: ToastClock = { now: () => performance.now(), schedule(callback, delay) { const timer = setTimeout(callback, delay); return () => clearTimeout(timer); } };
type Entry = { toast: Toast; remaining: number; started: number; paused: Set<string>; cancel?: () => void };

/** Display only: no business callback, guessed result or HTTP retry. */
export class ToastStore {
  private readonly clock: ToastClock; private entries: Entry[] = []; private next = 1; private closed = false;
  private snapshot: readonly Toast[] = Object.freeze([]);
  private readonly listeners = new Set<() => void>();
  constructor(clock: ToastClock = realClock) { this.clock = clock; }
  getSnapshot = (): readonly Toast[] => this.snapshot;
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  private publish(): void { this.snapshot = Object.freeze(this.entries.map(entry => entry.toast)); for (const listener of this.listeners) listener(); }
  private start(entry: Entry): void {
    entry.cancel?.(); delete entry.cancel; entry.started = this.clock.now();
    if (!entry.paused.size) entry.cancel = this.clock.schedule(() => {
      entry.remaining -= Math.max(0, this.clock.now() - entry.started);
      if (entry.remaining <= 0) this.dismiss(entry.toast.id); else this.start(entry);
    }, Math.min(entry.remaining, 2_147_483_647));
  }
  push(type: ToastType, message: string, milliseconds = type === 'error' ? 5000 : 3000): number {
    if (this.closed || !['success', 'error', 'info'].includes(type) || !message.trim() || !Number.isFinite(milliseconds) || milliseconds <= 0) throw new TypeError('Invalid toast');
    const duplicate = this.entries.find(entry => entry.toast.type === type && entry.toast.message === message);
    if (duplicate) { duplicate.remaining = milliseconds; this.start(duplicate); this.publish(); return duplicate.toast.id; }
    if (this.next >= Number.MAX_SAFE_INTEGER) throw new Error('Toast identifier capacity exhausted');
    const entry: Entry = { toast: Object.freeze({ id: this.next++, type, message }), remaining: milliseconds, started: this.clock.now(), paused: new Set() };
    this.entries.unshift(entry);
    while (this.entries.length > 3) this.entries.pop()!.cancel?.();
    this.start(entry); this.publish(); return entry.toast.id;
  }
  pause(id: number, reason: 'hover' | 'focus'): void {
    const entry = this.entries.find(item => item.toast.id === id); if (!entry || entry.paused.has(reason)) return;
    if (!entry.paused.size) { entry.remaining = Math.max(0, entry.remaining - Math.max(0, this.clock.now() - entry.started)); entry.cancel?.(); delete entry.cancel; }
    entry.paused.add(reason);
  }
  resume(id: number, reason: 'hover' | 'focus'): void {
    const entry = this.entries.find(item => item.toast.id === id); if (!entry || !entry.paused.delete(reason) || entry.paused.size) return;
    if (entry.remaining <= 0) this.dismiss(id); else this.start(entry);
  }
  dismiss(id: number): void {
    const entry = this.entries.find(item => item.toast.id === id); if (!entry) return;
    entry.cancel?.(); this.entries = this.entries.filter(item => item !== entry); this.publish();
  }
  dispose(): void { this.closed = true; for (const entry of this.entries) entry.cancel?.(); this.entries = []; this.publish(); this.listeners.clear(); }
}
