import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Confirmation } from '../../src/shared/confirmation.tsx';
import { ToastStore } from '../../src/shared/toast-store.ts';
import { ToastViewport } from '../../src/shared/toast.tsx';
import { MultiFilter, SearchInput } from '../../src/shared/filter.tsx';
import { Pagination } from '../../src/shared/pagination.tsx';
import type { PagePagination } from '../../src/api/client.ts';
import '../../src/shared/styles.css';

let now = 0;
const timers: { at: number; callback: () => void; cancelled: boolean }[] = [];
const store = new ToastStore({ now: () => now, schedule(callback, delay) { const timer = { at: now + delay, callback, cancelled: false }; timers.push(timer); return () => { timer.cancelled = true; }; } });
function advance(milliseconds: number) {
  const target = now + milliseconds;
  for (;;) {
    const next = timers.filter(timer => !timer.cancelled && timer.at <= target).sort((left, right) => left.at - right.at)[0];
    if (!next) break; now = next.at; next.cancelled = true; next.callback();
  } now = target;
}
const options = [{ value: 0, label: '零' }, { value: 1, label: '一' }];
const events: { kind: string; value: unknown }[] = [];
function App() {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const [values, setValues] = useState<readonly number[]>([0,1]);
  const [draft, setDraft] = useState('未提交草稿'), [submitted, setSubmitted] = useState('旧关键词');
  const [pagination, setPagination] = useState<PagePagination>({ page: 6, page_size: 20, total: 210, total_pages: 11 });
  Object.assign(window, { componentsProbe: {
    state: () => ({ open, busy, error, values, draft, submitted, pagination, events: [...events], toasts: store.getSnapshot() }),
    complete: (message: string | null) => { setBusy(false); setError(message); if (!message) setOpen(false); },
    restoreFilters: setValues, restorePagination: setPagination,
    toast: (type: 'info' | 'success' | 'error', message: string) => store.push(type, message), advance,
    destroy: () => { store.dispose(); root.unmount(); },
  } });
  return <main style={{ padding: 32, minHeight: 1000 }}><h1>公共组件诊断</h1><p>受控父级事件夹具，无业务HTTP；Toast使用可控时间。</p>
    <div style={{ display: 'flex', gap: 16, marginBottom: 32 }}>
      <button type="button" onClick={() => { setError(null); setOpen(true); }}>打开确认</button><button type="button" data-focus-fallback>返回入口</button>
    </div>
    <div style={{ display: 'flex', gap: 16 }}><SearchInput value={draft} submitted={submitted} placeholder="诊断搜索" draft={setDraft}
      submit={value => { events.push({ kind: 'search', value }); setSubmitted(value); setDraft(value); }} />
      <MultiFilter name="数字类型" options={options} value={values} change={(value, all) => { events.push({ kind: 'filter', value: { value, all } }); setValues(value); }} />
    </div>
    <Pagination value={pagination} loading={false} change={page => { events.push({ kind: 'page', value: page }); setPagination({ ...pagination, page }); }} />
    <Confirmation open={open} title="确认诊断操作" description={'确认焦点、关闭限制和内联错误。\n本组件不发业务请求。'} busy={busy} error={error}
      confirmLabel="执行诊断" cancel={() => setOpen(false)} confirm={() => { events.push({ kind: 'confirm', value: true }); setBusy(true); }} />
    <ToastViewport store={store} />
  </main>;
}
const root = createRoot(document.querySelector('#components-root')!); root.render(<App />);
