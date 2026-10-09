/** Document-level tracking also covers dialogs and toasts rendered in portals.
 * Typing in an editable field keeps pointer feedback; keyboard navigation and
 * commands restore the visible ring before their default focus action runs. */
export function installFocusFeedback(document: Document): () => void {
  const root = document.documentElement;
  const previous = root.getAttribute('data-focus-input');
  root.setAttribute('data-focus-input', 'keyboard');
  const pointer = () => root.setAttribute('data-focus-input', 'pointer');
  const navigationKeys = new Set(['Tab', 'Enter', ' ', 'Escape', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End', 'PageUp', 'PageDown']);
  const keyboard = (event: KeyboardEvent) => {
    if (!event.isComposing && !event.altKey && !event.ctrlKey && !event.metaKey && navigationKeys.has(event.key)) {
      root.setAttribute('data-focus-input', 'keyboard');
    }
  };
  const capture = {capture: true};
  document.addEventListener('pointerdown', pointer, capture);
  document.addEventListener('keydown', keyboard, capture);
  return () => {
    document.removeEventListener('pointerdown', pointer, capture);
    document.removeEventListener('keydown', keyboard, capture);
    if (previous === null) root.removeAttribute('data-focus-input');
    else root.setAttribute('data-focus-input', previous);
  };
}
