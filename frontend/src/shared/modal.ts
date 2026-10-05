import type { KeyboardEvent } from 'react';
const stack: HTMLDialogElement[] = [];
const observers = new Set<() => void>();
let originalOverflow = '';
export const activeModal = () => stack.at(-1) ?? null;
export const subscribeModal = (listener: () => void) => { observers.add(listener); return () => { observers.delete(listener); }; };
function announce() { for (const listener of observers) listener(); }
export function registerModal(element: HTMLDialogElement): () => void {
  if (stack.includes(element)) throw new Error('Modal already registered');
  if (!stack.length) { originalOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden'; }
  stack.push(element); announce();
  return () => { const index = stack.indexOf(element); if (index < 0) return; stack.splice(index, 1);
    if (!stack.length) document.body.style.overflow = originalOverflow; announce(); };
}
export function trapModalTab(event: KeyboardEvent<HTMLDialogElement>): void {
  if (event.key !== 'Tab') return;
  const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])')].filter(element => element.getClientRects().length > 0);
  const first = controls[0], last = controls.at(-1), focused = document.activeElement;
  if (!first || !last) { event.preventDefault(); event.currentTarget.focus(); }
  else if (event.shiftKey && (focused === first || focused === event.currentTarget)) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && (focused === last || focused === event.currentTarget)) { event.preventDefault(); first.focus(); }
}
