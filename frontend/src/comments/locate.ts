import type {RequirementEditor} from '../documents/editor.ts';
import type {DocumentNavigation} from '../documents/navigation.ts';
import type {RequirementComments} from './read.ts';

/** Only a confirmed page bound to the same displayed CURRENT may navigate.
 * Read-model offsets use code points; the editor validates exact original
 * text/context before focusing. Never search another block or move the text. */
export function locateComment(comments:RequirementComments,editor:RequirementEditor,navigation:DocumentNavigation,identity:number):boolean{
  const located=comments.located(identity);if(!located||!editor.valid)return false;
  const {current,comment}=located,displayed=editor.loadedDocument;
  if(displayed.document_type!=='CURRENT'||displayed.requirement_id!==current.requirement_id||displayed.id!==current.id||displayed.content_version!==current.content_version||displayed.markdown_content!==current.markdown_content||JSON.stringify(displayed.block_state_json)!==JSON.stringify(current.block_state_json)||navigation.getSnapshot().content?.kind!=='CURRENT')return false;
  try{
    if(comment.anchor_type==='SELECTION'){
      if(!('selected_text' in comment.anchor_ref)||comment.location.start_offset===null||comment.location.end_offset===null)return false;
      editor.locate({document_id:current.id,content_version:current.content_version,block_id:comment.block_id,start_offset:comment.location.start_offset,end_offset:comment.location.end_offset,...comment.anchor_ref});
    }
    return navigation.locate(comment.block_id);
  }catch{return false;}
}
