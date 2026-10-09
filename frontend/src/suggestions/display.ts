import type {Suggestion} from '../api/models.ts';

export function visibleSuggestions(items:readonly Suggestion[],pendingOnly:boolean,editing:ReadonlySet<number>,protectedId:number|null):readonly number[]{
  return items.filter(item=>!pendingOnly||item.status==='PENDING'||editing.has(item.id)||item.id===protectedId).map(item=>item.id);
}
export function nextPendingSuggestion(items:readonly Suggestion[],after:number|null):number|null{
  const pending=items.filter(item=>item.status==='PENDING');if(!pending.length)return null;
  const index=pending.findIndex(item=>item.id===after);return pending[(index+1)%pending.length]!.id;
}
