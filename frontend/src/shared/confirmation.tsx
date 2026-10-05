import { useId, useLayoutEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

let active: HTMLDialogElement | null = null;
const observers = new Set<() => void>();
export const activeConfirmation = () => active;
export const subscribeConfirmation = (listener: () => void) => { observers.add(listener); return () => { observers.delete(listener); }; };
function announce() { for (const listener of observers) listener(); }
export type ConfirmationProps = Readonly<{ open: boolean; title: string; description: string; busy: boolean; error?: string | null;
  confirmLabel?: string; cancelLabel?: string; dangerous?: boolean; confirm(): void; cancel(): void }>;

/** The parent owns the action, request, inline error and successful closure. */
export function Confirmation(props: ConfirmationProps) {
  const dialog = useRef<HTMLDialogElement>(null), cancel = useRef<HTMLButtonElement>(null), title = useId(), description = useId();
  useLayoutEffect(() => {
    if (!props.open) return;
    const element = dialog.current!;
    if (active && active !== element) throw new Error('Only one confirmation may be open');
    active = element;
    const original = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden'; element.showModal(); cancel.current?.focus(); announce();
    return () => {
      element.close(); document.body.style.overflow = overflow; if (active === element) active = null; announce();
      if (original?.isConnected && !original.closest('[inert]')) original.focus();
      else document.querySelector<HTMLElement>('[data-focus-fallback], main button:not(:disabled), main a[href]')?.focus();
    };
  }, [props.open]);
  if (!props.open) return null;
  return createPortal(<dialog ref={dialog} className="confirmation" tabIndex={-1} aria-labelledby={title} aria-describedby={description}
    onKeyDown={event => {
      if (event.key !== 'Tab') return;
      const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])')].filter(element => element.getClientRects().length > 0);
      const first = controls[0], last = controls.at(-1), focused = document.activeElement;
      if (!first || !last) { event.preventDefault(); event.currentTarget.focus(); }
      else if (event.shiftKey && (focused === first || focused === event.currentTarget)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (focused === last || focused === event.currentTarget)) { event.preventDefault(); first.focus(); }
    }}
    onCancel={event => { event.preventDefault(); if (!props.busy) props.cancel(); }}>
    <header><h2 id={title}>{props.title}</h2><button type="button" className="icon-button" aria-label="关闭确认弹窗" disabled={props.busy} onClick={props.cancel}>×</button></header>
    <div className="confirmation-content"><p id={description}>{props.description}</p>{props.error && <p role="alert" className="inline-error">! {props.error}</p>}</div>
    <footer><button type="button" ref={cancel} disabled={props.busy} onClick={props.cancel}>{props.cancelLabel ?? '取消'}</button>
      <button type="button" className={props.dangerous ? 'danger' : 'primary'} disabled={props.busy} onClick={props.confirm}
        aria-busy={props.busy}><span className="busy-slot" aria-hidden="true">{props.busy ? '◌' : ''}</span>{props.confirmLabel ?? '确认'}</button></footer>
  </dialog>, document.body);
}
