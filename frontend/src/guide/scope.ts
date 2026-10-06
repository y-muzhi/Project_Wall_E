import {snapshotObject} from '../api/client.ts';
import {scope as decodeScope} from '../api/models.ts';
import type {RequirementEditor} from '../documents/editor.ts';
import type {DocumentReadModel} from '../documents/contracts.ts';
import {validateBlockState} from '../documents/contracts.ts';
import {utf16RangeForSelection,utf16ToCodepoint} from '../documents/selection.ts';
import type {SelectionEvent} from '../documents/selection.ts';
export type GuideScope=ReturnType<typeof decodeScope>;
export type GuideTarget=Readonly<{document_id:number;content_version:number;scope:GuideScope;label:string;selection:SelectionEvent|null}>;
const capture=<T>(value:T):T=>snapshotObject(value) as unknown as T;
export function documentTarget(current:DocumentReadModel):GuideTarget{
 if(current.document_type!=='CURRENT')throw TypeError('Actual CURRENT required');return capture({document_id:current.id,content_version:current.content_version,scope:{scope_type:'DOCUMENT',scope_ref:null},label:'整篇文档',selection:null});
}
/** Exact shared-anchor matching, including overlapping alternatives. This is
 * only a local preview/validation; the native transaction resolves it again. */
export function uniqueSelectionRange(text:string,ref:Readonly<{selected_text:string;prefix_text:string;suffix_text:string}>):Readonly<{start:number;end:number}>|null{
 decodeScope({scope_type:'SELECTION',scope_ref:{block_id:1,selected_text:ref.selected_text,prefix_text:ref.prefix_text,suffix_text:ref.suffix_text}});let found:{start:number;end:number}|null=null,position=0;
 while(true){const start=text.indexOf(ref.selected_text,position);if(start<0)return found;const end=start+ref.selected_text.length;
  if(start>=ref.prefix_text.length&&text.slice(start-ref.prefix_text.length,start)===ref.prefix_text&&text.slice(end,end+ref.suffix_text.length)===ref.suffix_text){if(found)return null;found={start,end};}position=start+1;
 }
}
/** Every target is bound to the complete source/state of the actual immutable
 * CURRENT editor. Draft/Revision content cannot become a current AI scope. */
export function guideTarget(editor:RequirementEditor,kind:GuideScope['scope_type'],blockId:number|null=null,selection:SelectionEvent|null=null):GuideTarget{
 const current=editor.loadedDocument;if(!editor.valid||current.document_type!=='CURRENT')throw TypeError('Valid actual CURRENT editor required');
 return editor.action(ctx=>{
  const {source,state}=validateBlockState(ctx,current.markdown_content,current.block_state_json);if(kind==='DOCUMENT')return documentTarget(current);
  if(kind==='SELECTION'){if(!selection)throw TypeError('请在同一区块内选择有效文字');blockId=selection.block_id;}
  let index=state.blocks.findIndex(block=>block.block_id===blockId);if(index<0)throw TypeError('请先在当前正文选择区块');
  if(kind==='SECTION'){while(index>=0&&source.blocks[index]!.block_type!=='heading')index--;if(index<0)throw TypeError('当前区块之前没有章节标题');}
  const metadata=state.blocks[index]!,block=source.blocks[index]!,context={document_id:current.id,content_version:current.content_version,block_id:metadata.block_id};
  if(kind==='SELECTION'){
   const range=utf16RangeForSelection(context,block.plain_text,selection!),unique=uniqueSelectionRange(block.plain_text,selection!);if(!unique||unique.start!==range.start||unique.end!==range.end)throw TypeError('选区不能在原区块唯一定位，请重新选择');
  }
  const ref=kind==='SELECTION'?{block_id:metadata.block_id,selected_text:selection!.selected_text,prefix_text:selection!.prefix_text,suffix_text:selection!.suffix_text}:{block_id:metadata.block_id};
  return capture({document_id:current.id,content_version:current.content_version,scope:decodeScope({scope_type:kind,scope_ref:ref}),label:kind==='SECTION'?'章节：'+block.plain_text:kind==='BLOCK'?'区块：'+[...block.plain_text].slice(0,80).join(''): '选区：'+selection!.selected_text,selection:kind==='SELECTION'?selection:null});
 });
}
/** Rebind a completed REVIEW's public scope to the latest CURRENT explicitly;
 * an absent/ambiguous old selection is rejected, never enlarged to DOCUMENT. */
export function reviewTarget(editor:RequirementEditor,reference:GuideScope):GuideTarget{
 const scope=decodeScope(reference);if(scope.scope_type==='DOCUMENT')return guideTarget(editor,'DOCUMENT');
 if(scope.scope_type!=='SELECTION'){if(scope.scope_type==='SECTION'&&!editor.loadedDocument.block_state_json.blocks.some(row=>row.block_id===scope.scope_ref.block_id&&row.block_type==='heading'))throw TypeError('来源检查的章节标题已失效');return guideTarget(editor,scope.scope_type,scope.scope_ref.block_id);}
 const current=editor.loadedDocument,ref=scope.scope_ref;
 const selected=editor.action(ctx=>{const {source,state}=validateBlockState(ctx,current.markdown_content,current.block_state_json),index=state.blocks.findIndex(row=>row.block_id===ref.block_id),block=source.blocks[index];if(!block)throw TypeError('来源检查的区块已不存在');const range=uniqueSelectionRange(block.plain_text,ref);if(!range)throw TypeError('来源检查的选区已失效');
  return {document_id:current.id,content_version:current.content_version,block_id:ref.block_id,start_offset:utf16ToCodepoint(block.plain_text,range.start),end_offset:utf16ToCodepoint(block.plain_text,range.end),selected_text:ref.selected_text,prefix_text:ref.prefix_text,suffix_text:ref.suffix_text};});
 return guideTarget(editor,'SELECTION',ref.block_id,selected);
}
