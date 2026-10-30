/** Only the AI composer uses this mapping; IME confirmation remains native. */
type ComposerKey = Readonly<{
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
  repeat: boolean;
  isComposing: boolean;
  keyCode?: number;
  defaultPrevented?: boolean;
}>;
export function composerShortcut(event: ComposerKey): 'SEND' | 'NEWLINE' | 'IGNORE' | null {
  if (
    event.defaultPrevented ||
    event.isComposing ||
    event.keyCode === 229 ||
    event.key !== 'Enter' ||
    event.altKey
  )
    return null;
  if (event.repeat) return 'IGNORE';
  if (event.ctrlKey || event.metaKey) return 'NEWLINE';
  return event.shiftKey ? null : 'SEND';
}
/** Sending still shares the button's permission and validation gate. */
export function isSendShortcut(event: ComposerKey, canSend: boolean): boolean {
  return canSend && composerShortcut(event) === 'SEND';
}
