import {editorViewCtx} from '@milkdown/kit/core';
import type {CurrentDocumentBinding} from '../requirements/document-owner.ts';
import type {RequirementSuggestionBatch} from './batch-owner.ts';

/** Temporary target indication belongs to the real CURRENT DOM, not the
 * proposed preview. No text, identity or server metadata is changed. */
export class SuggestionTargetLocator{
 private highlighted:HTMLElement|null=null;private timer:ReturnType<typeof setTimeout>|undefined;private closed=false;private readonly release:()=>void;
 constructor(private readonly owner:RequirementSuggestionBatch,private readonly binding:()=>CurrentDocumentBinding|null){this.release=owner.subscribe(()=>{const state=owner.getSnapshot();if(!state.active||!state.available||this.highlighted&&!this.highlighted.isConnected)this.clear();});}
 private clear():void{if(this.timer!==undefined)clearTimeout(this.timer);this.timer=undefined;this.highlighted?.classList.remove('suggestion-target-highlight');this.highlighted=null;}
 locate(identity:number):boolean{
  const state=this.owner.getSnapshot(),binding=this.binding(),item=state.batch?.suggestions.find(item=>item.id===identity),current=state.detail.current;if(this.closed||!state.available||state.loading||!binding||!item||!binding.editor.valid)return false;
  const displayed=binding.editor.loadedDocument;if(displayed.document_type!=='CURRENT'||displayed.id!==current.id||displayed.requirement_id!==current.requirement_id||displayed.content_version!==current.content_version||displayed.markdown_content!==current.markdown_content||JSON.stringify(displayed.block_state_json)!==JSON.stringify(current.block_state_json)||binding.navigation.getSnapshot().content?.kind!=='CURRENT')return false;
  try{const targets:HTMLElement[]=[];binding.editor.action(ctx=>{const view=ctx.get(editorViewCtx);view.state.doc.forEach((node,position)=>{if(node.attrs.walle_block_id===item.target_ref.block_id){const element=view.nodeDOM(position);if(element instanceof HTMLElement)targets.push(element);}});});const target=targets[0]??null;
   if(!target||!binding.navigation.locate(item.target_ref.block_id))return false;this.clear();this.highlighted=target;this.highlighted.classList.add('suggestion-target-highlight');this.timer=setTimeout(()=>this.clear(),2000);return true;
  }catch{return false;}
 }
 dispose():void{if(this.closed)return;this.closed=true;this.release();this.clear();}
}
