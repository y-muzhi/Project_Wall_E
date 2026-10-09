export type MessageAnchor = Readonly<{
  id: string | null; part: string | null; offset: number; top: number; height: number; near: boolean; last: number;
}>;

/** Use the actual scroll port, even when run details and composer share it. */
export function captureMessageAnchor(root: HTMLElement): MessageAnchor {
  const box=root.getBoundingClientRect(),cards=[...root.querySelectorAll<HTMLElement>('[data-message-id]')];
  const visible=cards.find(card=>card.getBoundingClientRect().bottom>box.top&&card.getBoundingClientRect().top<box.bottom);
  const part=visible&&visible.getBoundingClientRect().top<box.top?
    [...visible.querySelectorAll<HTMLElement>('[data-card-key]')].find(card=>card.getBoundingClientRect().bottom>box.top&&card.getBoundingClientRect().top<box.bottom):null;
  const target=part??visible;
  return {id:visible?.dataset.messageId??null,part:part?.dataset.cardKey??null,
    offset:target?target.getBoundingClientRect().top-box.top:0,top:root.scrollTop,height:root.scrollHeight,
    near:root.scrollHeight-root.clientHeight-root.scrollTop<=80,last:Number(cards.at(-1)?.dataset.messageSequence??0)};
}

export function restoreMessageAnchor(root: HTMLElement, previous: MessageAnchor): void {
  const message=previous.id===null?null:root.querySelector<HTMLElement>('[data-message-id="'+previous.id+'"]');
  const part=previous.part===null?null:[...message?.querySelectorAll<HTMLElement>('[data-card-key]')??[]].find(card=>card.dataset.cardKey===previous.part);
  const target=part??message;
  if(target)root.scrollTop+=target.getBoundingClientRect().top-root.getBoundingClientRect().top-previous.offset;
  else root.scrollTop=previous.top+root.scrollHeight-previous.height;
}
