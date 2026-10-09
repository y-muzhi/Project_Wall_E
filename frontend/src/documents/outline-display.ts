import type {OutlineEntry} from './navigation.ts';

/** Folding affects visibility only; the authoritative outline stays intact. */
export function visibleOutline(outline:readonly OutlineEntry[],collapsed:ReadonlySet<number>):readonly boolean[]{
  const ancestors:number[]=[];
  return outline.map((item,index)=>{
    while(ancestors.length&&outline[ancestors.at(-1)!]!.depth>=item.depth)ancestors.pop();
    const visible=!ancestors.some(parent=>collapsed.has(outline[parent]!.block_id));ancestors.push(index);return visible;
  });
}
