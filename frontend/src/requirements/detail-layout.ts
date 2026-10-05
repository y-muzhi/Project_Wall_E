export type DetailTab = 'AI' | 'COMMENTS' | 'REVISIONS';
export type DetailPreferences = Readonly<{ schema_version: 1; left_open: boolean; right_open: boolean; right_tab: DetailTab; right_width: number }>;
export type DetailGeometry = Readonly<{ mode: 'DESKTOP' | 'COMPACT' | 'BLOCKED'; left_open: boolean; right_open: boolean;
  right_tab: DetailTab; right_width: number; right_max: number; document_width: number; preferences: DetailPreferences; warning: string | null }>;
export const preferencesKey = 'walle:v1:preferences';
type StoragePort = Pick<Storage, 'getItem' | 'setItem'>;
function dimension(value: number): number { if (!Number.isFinite(value) || value < 0) throw new TypeError('Invalid CSS width'); return value; }
function mode(width: number): DetailGeometry['mode'] { return width < 1024 ? 'BLOCKED' : width < 1280 ? 'COMPACT' : 'DESKTOP'; }
function tab(value: unknown): DetailTab { if (value !== 'AI' && value !== 'COMMENTS' && value !== 'REVISIONS') throw new TypeError('Invalid panel tab'); return value; }
export function decodeDetailPreferences(value: unknown): DetailPreferences {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new TypeError('Invalid preferences');
  const record = value as Record<string, unknown>;
  if (Object.keys(record).sort().join(',') !== 'left_open,right_open,right_tab,right_width,schema_version' || record.schema_version !== 1 ||
    typeof record.left_open !== 'boolean' || typeof record.right_open !== 'boolean' || typeof record.right_width !== 'number' ||
    !Number.isFinite(record.right_width) || record.right_width < 360) throw new TypeError('Invalid preferences');
  return Object.freeze({schema_version: 1, left_open: record.left_open, right_open: record.right_open, right_tab: tab(record.right_tab), right_width: record.right_width});
}

/** Layout is browser preference only. No document/GuideRun mutation capability. */
export class DetailLayout {
  private preferences: DetailPreferences; private width: number; private available: number;
  private compactSide: 'LEFT' | 'RIGHT' | null = null; private warning: string | null = null;
  private readonly storage: StoragePort | null; private readonly listeners = new Set<() => void>(); private value: DetailGeometry;
  constructor(status: 'INITIALIZING' | 'ACTIVE' | 'COMPLETED', width: number, storage: StoragePort | null) {
    this.width = dimension(width); this.available = Math.max(0, width - (width < 1280 ? 16 : 32)); this.storage = storage;
    this.preferences = Object.freeze({schema_version: 1, left_open: true, right_open: status === 'INITIALIZING', right_tab: 'AI', right_width: 420});
    try { if (!storage) throw new Error('Unavailable'); const raw = storage.getItem(preferencesKey); if (raw !== null) this.preferences = decodeDetailPreferences(JSON.parse(raw)); }
    catch { this.warning = '页面偏好暂存不可用，当前布局仍可调整。'; }
    this.selectCompact(); this.value = this.compute();
  }
  getSnapshot = (): DetailGeometry => this.value;
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  private selectCompact(): void { this.compactSide = this.preferences.right_open ? 'RIGHT' : this.preferences.left_open ? 'LEFT' : null; }
  private compute(): DetailGeometry {
    const current = mode(this.width), supported = current !== 'BLOCKED';
    const left = supported && this.preferences.left_open && (current === 'DESKTOP' || this.compactSide === 'LEFT');
    const right = supported && this.preferences.right_open && (current === 'DESKTOP' || this.compactSide === 'RIGHT');
    // Six CSS pixels per displayed separator/gap. Content minimum is reserved
    // before clamping the effective width; preference is never overwritten.
    const available = Math.max(0, this.available - (left ? 206 : 0) - (right ? 6 : 0));
    const maximum = Math.min(available / 2, available - 640);
    const effective = right && maximum >= 360 ? Math.min(Math.max(360, this.preferences.right_width), maximum) : 0;
    return Object.freeze({mode: current, left_open: left, right_open: right && effective > 0, right_tab: this.preferences.right_tab,
      right_width: effective, right_max: Math.max(0, maximum), document_width: available - effective,
      preferences: this.preferences, warning: this.warning});
  }
  private publish(): void { this.value = this.compute(); for (const listener of this.listeners) { try { listener(); } catch (error) { console.error('WALL-E layout observer failed', error); } } }
  viewport(width: number, available?: number): void {
    dimension(width); const previous = mode(this.width); this.width = width;
    this.available = dimension(available ?? Math.max(0, width - (width < 1280 ? 16 : 32)));
    if (mode(width) === 'COMPACT' && previous !== 'COMPACT') this.selectCompact(); this.publish();
  }
  private store(changes: Partial<DetailPreferences>): void {
    this.preferences = decodeDetailPreferences({...this.preferences, ...changes});
    try { if (!this.storage) throw new Error('Unavailable'); this.storage.setItem(preferencesKey, JSON.stringify(this.preferences)); this.warning = null; }
    catch { this.warning = '页面偏好暂存不可用，当前布局仍可调整。'; } this.publish();
  }
  toggleLeft(): void {
    if (this.value.mode === 'BLOCKED') return; const open = !this.value.left_open;
    if (this.value.mode === 'COMPACT') this.compactSide = open ? 'LEFT' : null; this.store({left_open: open});
  }
  toggleRight(): void {
    if (this.value.mode === 'BLOCKED') return; const open = !this.value.right_open;
    if (this.value.mode === 'COMPACT') this.compactSide = open ? 'RIGHT' : null; this.store({right_open: open});
  }
  openTab(value: DetailTab): void {
    if (this.value.mode === 'BLOCKED') return;
    if (this.value.mode === 'COMPACT') this.compactSide = 'RIGHT'; this.store({right_open: true, right_tab: tab(value)});
  }
  resizeRight(width: number): void {
    dimension(width); if (!this.value.right_open) return;
    // Explicit drag writes only the width the current geometry actually allows.
    this.store({right_width: Math.min(Math.max(360, width), this.value.right_max)});
  }
}

export type ViewportState = Readonly<{ phase: 'SUPPORTED' | 'BLOCKED' | 'RESTORING' | 'RESTORE_FAILED'; saving: boolean; save_failed: boolean }>;
export interface ViewportActions { blockAndSave(): Promise<void>; readAfterSupport(signal: AbortSignal): Promise<void>; }
/** Parent freezes editor synchronously in blockAndSave and preserves its own
 * actual local draft. Only its read is abortable, never the save or AI command. */
export class DetailViewportGuard {
  private readonly actions: ViewportActions; private value: ViewportState;
  private active = false; private closed = false; private blocked: boolean; private generation = 0;
  private save: Promise<void> = Promise.resolve(); private saveTicket = 0; private controller: AbortController | undefined;
  private readonly listeners = new Set<() => void>();
  constructor(width: number, actions: ViewportActions) {
    this.blocked = dimension(width) < 1024; this.actions = actions;
    this.value = Object.freeze({phase: this.blocked ? 'BLOCKED' : 'SUPPORTED', saving: false, save_failed: false});
  }
  getSnapshot = (): ViewportState => this.value;
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  private publish(changes: Partial<ViewportState>): void {
    if (this.closed) return; this.value = Object.freeze({...this.value,...changes});
    for (const listener of this.listeners) { try { listener(); } catch(error) { console.error('WALL-E viewport observer failed',error); } }
  }
  activate(): void { if (this.active || this.closed) return; this.active = true; if (this.blocked) this.enterBlocked(); }
  viewport(width: number): void {
    const blocked = dimension(width) < 1024; if (this.closed || blocked === this.blocked) return;
    this.blocked = blocked; if (!this.active) { this.publish({phase: blocked ? 'BLOCKED' : 'SUPPORTED'}); return; }
    if (blocked) this.enterBlocked(); else this.restore();
  }
  private enterBlocked(): void {
    this.generation++; this.controller?.abort(); this.controller = undefined;
    this.publish({phase: 'BLOCKED', saving: true, save_failed: false});
    // Deliberately call before Promise resolution so parent can freeze input now.
    let saving: Promise<void>; try { saving = this.actions.blockAndSave(); } catch(error) { saving = Promise.reject(error); }
    const ticket = ++this.saveTicket;
    this.save = Promise.resolve(saving).then(() => { if (ticket === this.saveTicket) this.publish({saving: false}); }, () => {
      if (ticket === this.saveTicket) this.publish({saving: false, save_failed: true});
    });
  }
  private restore(): void {
    const generation = ++this.generation, controller = new AbortController(); this.controller?.abort(); this.controller = controller;
    this.publish({phase: 'RESTORING'});
    void this.save.then(async () => {
      if (this.closed || this.blocked || generation !== this.generation) return;
      try {
        await this.actions.readAfterSupport(controller.signal);
        if (!this.closed && !this.blocked && generation === this.generation) this.publish({phase: 'SUPPORTED', saving: false});
      } catch { if (!this.closed && !this.blocked && generation === this.generation) this.publish({phase: 'RESTORE_FAILED', saving: false}); }
    });
  }
  retry(): void { if (!this.closed && !this.blocked && this.value.phase === 'RESTORE_FAILED') this.restore(); }
  dispose(): void { this.closed = true; this.generation++; this.controller?.abort(); this.listeners.clear(); }
}
