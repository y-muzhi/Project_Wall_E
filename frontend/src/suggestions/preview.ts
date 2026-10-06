import type {Ctx} from '@milkdown/kit/ctx';
import {schemaCtx} from '@milkdown/kit/core';
import {DOMSerializer} from '@milkdown/kit/prose/model';
import {EditorSource} from '../documents/editor-source.ts';

/** A read-only display fragment, never a fake Document/BlockState. The same
 * installed source parser/schema retains inert HTML and GFM semantics. A row
 * has no persisted header, so private empty framing is removed from the DOM. */
export function suggestionMarkdown(ctx:Ctx,markdown:string,rowColumns?:number):DocumentFragment{
 if(rowColumns!==undefined&&(!Number.isInteger(rowColumns)||rowColumns<1||rowColumns>1000))throw TypeError('Actual row width required');
 const framing=rowColumns===undefined?'':'|'+Array(rowColumns).fill(' ').join('|')+'|\n|'+Array(rowColumns).fill(' --- ').join('|')+'|\n';
 const source=new EditorSource(ctx,framing+markdown);
 if(rowColumns!==undefined&&(source.blocks.length!==1||source.blocks[0]!.block_type!=='table'||source.blocks[0]!.node.childCount!==2))throw Error('Original row cannot be rendered without changing its structure');
 const fragment=document.createDocumentFragment();DOMSerializer.fromSchema(ctx.get(schemaCtx)).serializeFragment(source.document.content,{document},fragment);
 if(rowColumns!==undefined)fragment.querySelector('tr')?.remove();
 for(const control of fragment.querySelectorAll<HTMLInputElement|HTMLButtonElement|HTMLTextAreaElement>('input,button,textarea,select'))control.disabled=true;
 for(const editable of fragment.querySelectorAll<HTMLElement>('[contenteditable]'))editable.contentEditable='false';
 return fragment;
}
