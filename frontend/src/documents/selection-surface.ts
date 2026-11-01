import { selectionToolbarPosition } from './selection-toolbar-position.ts';

/** Reading and editing wait for the same native gesture to finish. Observing
 * selection never dispatches an editor transaction or changes its DOM. */
export function observeDocumentSelection(root: HTMLElement, changed: () => void) {
  const document = root.ownerDocument,
    browser = document.defaultView!,
    capture = { capture: true };
  let pointer: number | null = null,
    frame: number | null = null;
  function schedule() {
    if (frame !== null) return;
    frame = browser.requestAnimationFrame(() => {
      frame = null;
      changed();
    });
  }
  function start(event: PointerEvent) {
    if (event.button !== 0 || !event.isPrimary) return;
    pointer = event.pointerId;
    changed();
  }
  function finish(event: PointerEvent) {
    if (pointer !== event.pointerId) return;
    pointer = null;
    schedule();
  }
  function blur() {
    pointer = null;
    changed();
  }
  root.addEventListener('pointerdown', start, capture);
  document.addEventListener('pointerup', finish, capture);
  document.addEventListener('pointercancel', finish, capture);
  document.addEventListener('selectionchange', schedule);
  document.addEventListener('focusin', schedule);
  document.addEventListener('scroll', schedule, capture);
  browser.addEventListener('resize', schedule);
  browser.addEventListener('blur', blur);
  return {
    get selecting() {
      return pointer !== null;
    },
    destroy() {
      if (frame !== null) browser.cancelAnimationFrame(frame);
      root.removeEventListener('pointerdown', start, capture);
      document.removeEventListener('pointerup', finish, capture);
      document.removeEventListener('pointercancel', finish, capture);
      document.removeEventListener('selectionchange', schedule);
      document.removeEventListener('focusin', schedule);
      document.removeEventListener('scroll', schedule, capture);
      browser.removeEventListener('resize', schedule);
      browser.removeEventListener('blur', blur);
    },
  };
}

/** Native range geometry works for forward, backward and cross-block selection.
 * Both surfaces clip to the document scrollport and keep clear of its toolbar. */
export function documentSelectionToolbarPosition(root: HTMLElement, width: number, height: number) {
  const document = root.ownerDocument,
    browser = document.defaultView!,
    selection = document.getSelection();
  if (
    root.closest('[hidden],[inert]') ||
    !selection ||
    selection.rangeCount !== 1 ||
    selection.isCollapsed ||
    !selection.toString().trim()
  )
    return null;
  const range = selection.getRangeAt(0),
    editor = root.querySelector('.ProseMirror');
  if (!editor?.contains(range.commonAncestorContainer)) return null;
  const port = (root.closest('.requirement-owned-document') ?? root).getBoundingClientRect(),
    toolbar = root.querySelector('.editor-format-toolbar')?.getBoundingClientRect();
  return selectionToolbarPosition(
    range.getBoundingClientRect(),
    {
      left: Math.max(8, port.left),
      right: Math.min(browser.innerWidth - 8, port.right),
      top: Math.max(8, port.top, toolbar?.bottom ?? 0),
      bottom: Math.min(browser.innerHeight - 8, port.bottom),
    },
    width,
    height,
  );
}
