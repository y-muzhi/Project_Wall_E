import {Icon,BusyIndicator} from './icon.tsx';
import { useId, useLayoutEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { registerModal, trapModalTab } from './modal.ts';

let active: HTMLDialogElement | null = null;
export type ConfirmationProps = Readonly<{ open: boolean; title: string; description: string; busy: boolean; error?: string | null;
  confirmLabel?: string; cancelLabel?: string; dangerous?: boolean; confirmDisabled?:boolean; confirm(): void; cancel(): void }>;

/** The parent owns the action, request, inline error and successful closure. */
export function Confirmation(props: ConfirmationProps) {
  const dialog = useRef<HTMLDialogElement>(null), cancel = useRef<HTMLButtonElement>(null), title = useId(), description = useId();
  useLayoutEffect(() => {
    if (!props.open) return;
    const element = dialog.current!;
    if (active && active !== element) throw new Error('Only one confirmation may be open');
    active = element;
    const original = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    element.showModal(); const release = registerModal(element); cancel.current?.focus();
    return () => {
      element.close(); release(); if (active === element) active = null;
      const focus = (candidate: HTMLElement | null) => {
        if (!candidate?.isConnected || candidate.closest('[inert],[hidden]') || candidate.matches(':disabled') || !candidate.getClientRects().length) return false;
        candidate.focus(); return document.activeElement === candidate;
      };
      if (!focus(original)) for (const candidate of document.querySelectorAll<HTMLElement>('[data-focus-fallback], main button:not(:disabled), main a[href]')) {
        if (focus(candidate)) break;
      }
    };
  }, [props.open]);
  if (!props.open) return null;
  return createPortal(<dialog ref={dialog} className="confirmation" tabIndex={-1} aria-labelledby={title} aria-describedby={description}
    onKeyDown={trapModalTab}
    onCancel={event => { event.preventDefault(); if (!props.busy) props.cancel(); }}>
    <header><h2 id={title}>{props.title}</h2><button type="button" className="ui-button icon-button" aria-label="关闭确认弹窗" disabled={props.busy} onClick={props.cancel}><Icon name="close"/></button></header>
    <div className="confirmation-content"><p id={description}>{props.description}</p>{props.error && <p role="alert" className="inline-error">{props.error}</p>}</div>
    <footer><button className="ui-button" type="button" ref={cancel} disabled={props.busy} onClick={props.cancel}>{props.cancelLabel ?? '取消'}</button>
      <button type="button" className={'ui-button '+(props.dangerous ? 'danger' : 'primary')} disabled={props.busy||props.confirmDisabled} onClick={props.confirm}
        aria-busy={props.busy}><BusyIndicator busy={props.busy}/>{props.confirmLabel ?? '确认'}</button></footer>
  </dialog>, document.body);
}
