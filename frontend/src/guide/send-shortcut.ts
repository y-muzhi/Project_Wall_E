/** The textarea shortcut shares the button's permission and validation gate.
 * Ordinary Enter and IME confirmation always remain text input. */
export function isSendShortcut(event:Readonly<{
 key:string;ctrlKey:boolean;metaKey:boolean;altKey:boolean;shiftKey:boolean;
 repeat:boolean;isComposing:boolean;keyCode?:number;defaultPrevented?:boolean;
}>,canSend:boolean):boolean{
 return canSend&&!event.defaultPrevented&&!event.repeat&&!event.isComposing&&event.keyCode!==229
  &&event.key==='Enter'&&(event.ctrlKey||event.metaKey)&&!event.altKey&&!event.shiftKey;
}
