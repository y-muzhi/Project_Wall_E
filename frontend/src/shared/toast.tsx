import { useEffect, useLayoutEffect, useState, useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import { ToastStore, type Toast } from './toast-store.ts';
import { activeModal, subscribeModal } from './modal.ts';

const fadeMilliseconds = 150;
type VisibleToast = { toast: Toast; expiresAt: number | null };

export function ToastViewport({ store }: { store: ToastStore }) {
  const entries = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
  const modal = useSyncExternalStore(subscribeModal, activeModal, () => null);
  const [visible, setVisible] = useState<VisibleToast[]>(() => entries.map(toast => ({ toast, expiresAt: null })));
  useLayoutEffect(() => {
    const now = performance.now();
    setVisible(previous => [
      ...entries.map(toast => ({ toast, expiresAt: null })),
      ...previous.filter(item => !entries.some(toast => toast.id === item.toast.id))
        .map(item => ({ ...item, expiresAt: item.expiresAt ?? now + fadeMilliseconds }))
        .filter(item => item.expiresAt > now),
    ].slice(0, 3));
  }, [entries]);
  useEffect(() => {
    const deadlines = visible.flatMap(item => item.expiresAt === null ? [] : [item.expiresAt]);
    if (!deadlines.length) return;
    const timer = setTimeout(() => {
      const now = performance.now();
      setVisible(previous => previous.filter(item => item.expiresAt === null || item.expiresAt > now));
    }, Math.max(0, Math.min(...deadlines) - performance.now()));
    return () => clearTimeout(timer);
  }, [visible]);
  // Only the visual shell survives dismissal; business timing stays in ToastStore.
  return createPortal(<div className="toast-viewport" aria-label="操作结果提示">{visible.map(({ toast: entry, expiresAt }) => <article key={entry.id}
    className={'toast toast-' + entry.type + (expiresAt === null ? '' : ' toast-leaving')}
    style={{ animationDuration: `${fadeMilliseconds}ms` }} aria-hidden={expiresAt !== null || undefined}
    role={expiresAt === null ? (entry.type === 'error' ? 'alert' : 'status') : undefined}
    onMouseEnter={() => store.pause(entry.id, 'hover')} onMouseLeave={() => store.resume(entry.id, 'hover')}
    onFocusCapture={() => store.pause(entry.id, 'focus')} onBlurCapture={event => { if (!event.currentTarget.contains(event.relatedTarget)) store.resume(entry.id, 'focus'); }}>
    <span aria-hidden="true" className="toast-icon">{entry.type === 'success' ? '✓' : entry.type === 'error' ? '!' : 'i'}</span>
    <span>{entry.message}</span><button type="button" className="icon-button" aria-label="关闭提示" disabled={expiresAt !== null} onClick={() => store.dismiss(entry.id)}>×</button>
  </article>)}</div>, modal ?? document.body);
}
