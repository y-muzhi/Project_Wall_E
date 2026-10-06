import {validateBlockState} from '../documents/contracts.ts';
import type {RequirementEditor} from '../documents/editor.ts';
import {utf16RangeForSelection} from '../documents/selection.ts';
import type {SelectionEvent} from '../documents/selection.ts';
import type {CommentTarget} from './commands.ts';

/** Creation entry from the actual immutable CURRENT editor. Draft/history
 * callers cannot manufacture a current anchor from their displayed content. */
export function commentTarget(editor:RequirementEditor,blockId:number,selection:SelectionEvent|null=null):CommentTarget{
  const current=editor.loadedDocument;if(!editor.valid||current.document_type!=='CURRENT')throw TypeError('Valid CURRENT editor required');
  return editor.action(ctx=>{
    const {source,state}=validateBlockState(ctx,current.markdown_content,current.block_state_json),index=state.blocks.findIndex(block=>block.block_id===blockId),block=source.blocks[index];if(!block)throw TypeError('Current block required');
    if(selection)utf16RangeForSelection({document_id:current.id,content_version:current.content_version,block_id:blockId},block.plain_text,selection);
    return Object.freeze({document_id:current.id,content_version:current.content_version,block_id:blockId,anchor_type:selection?'SELECTION':'BLOCK',selection,quote:selection?.selected_text??block.markdown});
  });
}
