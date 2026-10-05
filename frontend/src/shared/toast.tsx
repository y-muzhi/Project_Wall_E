import { useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import { ToastStore } from './toast-store.ts';
import { activeModal, subscribeModal } from './modal.ts';

export function ToastViewport({ store }: { store: ToastStore }) {
  const entries = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
  const modal = useSyncExternalStore(subscribeModal, activeModal, () => null);
  return createPortal(<div className="toast-viewport" aria-label="操作结果提示">{entries.map(entry => <article key={entry.id}
    className={'toast toast-' + entry.type} role={entry.type === 'error' ? 'alert' : 'status'}
    onMouseEnter={() => store.pause(entry.id, 'hover')} onMouseLeave={() => store.resume(entry.id, 'hover')}
    onFocusCapture={() => store.pause(entry.id, 'focus')} onBlurCapture={event => { if (!event.currentTarget.contains(event.relatedTarget)) store.resume(entry.id, 'focus'); }}>
    <span aria-hidden="true" className="toast-icon">{entry.type === 'success' ? '✓' : entry.type === 'error' ? '!' : 'i'}</span>
    <span>{entry.message}</span><button type="button" className="icon-button" aria-label="关闭提示" onClick={() => store.dismiss(entry.id)}>×</button>
  </article>)}</div>, modal ?? document.body);
}
