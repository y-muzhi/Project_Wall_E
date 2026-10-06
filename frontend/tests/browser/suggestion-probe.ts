import {editorViewCtx} from '@milkdown/kit/core';
import type {WalleApi} from '../../src/api/walle.ts';
import {ApiUnknown} from '../../src/api/client.ts';
import {require} from '../../src/api/decoding.ts';
import {RequirementEditor} from '../../src/documents/editor.ts';
import {EditorSource} from '../../src/documents/editor-source.ts';
import {RequirementDetailRead} from '../../src/requirements/detail-read.ts';
import {RequirementSuggestionBatch} from '../../src/suggestions/batch-owner.ts';

/** Native API/controller diagnostic, deliberately not a product panel or
 * model-generation/effects test. The named persisted fixture is explicit. */
export async function suggestionProbe(api:WalleApi){
 const canonical=(value:unknown):unknown=>Array.isArray(value)?value.map(canonical):value!==null&&typeof value==='object'?Object.fromEntries(Object.entries(value).sort(([left],[right])=>left.localeCompare(right)).map(([key,value])=>[key,canonical(value)])):value;
 const identity=2,initial=(await api.getCurrentDocument(identity)).data,host=document.createElement('section');document.body.append(host);
 const draft=(await api.prepareStartManualDraft(identity,initial.content_version).submit()).data.manual_draft,edit=await RequirementEditor.create(host,draft,false);
 edit.action(ctx=>{const view=ctx.get(editorViewCtx),table=new EditorSource(ctx,'| key | value |\n| --- | --- |\n| model | 原值😀 |\n| keep | 不改 |\n');view.dispatch(view.state.tr.insert(view.state.doc.content.size,table.document.content));});
 require(edit.valid&&edit.ledger!==null);const ticket=edit.ledger.beginSave(),saved=(await api.prepareSaveManualDraft(identity,{expected_version:ticket.expected_version,markdown_content:ticket.markdown_content,block_state_json:ticket.block_state_json}).submit()).data;edit.ledger.acknowledgeSave(ticket,saved);await api.prepareCompleteManualDraft(identity,saved.content_version).submit();await edit.destroy();host.remove();
 const baseline=(await api.getCurrentDocument(identity)).data,reader=new RequirementDetailRead(identity,api),counts={prepares:0,sends:0,reads:0,adopts:0,frozen_receipts:[] as {field_order_equal:boolean;semantic_equal:boolean}[]};let lose=false,failRead=false,failAdopt=false,owner:RequirementSuggestionBatch|null=null;
 const wrapped=new Proxy(api,{get(target,key){const value=Reflect.get(target,key);if(['prepareDecideSuggestion','prepareCompleteBatch','prepareDiscardBatch'].includes(String(key)))return (...args:unknown[])=>{counts.prepares++;const original=value.apply(target,args);let receipt:string|null=null,sorted:string|null=null;return {submit:async()=>{counts.sends++;const response=await original.submit();if(receipt!==null){const equal=sorted===JSON.stringify(canonical(response.data));counts.frozen_receipts.push({field_order_equal:receipt===JSON.stringify(response.data),semantic_equal:equal});require(equal);}if(lose){lose=false;receipt=JSON.stringify(response.data);sorted=JSON.stringify(canonical(response.data));throw new ApiUnknown(true);}return response;}};};return typeof value==='function'?value.bind(target):value;}});
 const read=async()=>{counts.reads++;if(failRead){failRead=false;throw new ApiUnknown(false);}require(await reader.refresh());return reader.getSnapshot().confirmed!;};
 return {baseline,counts,state:()=>owner!.getSnapshot(),loseNext(){lose=true;},failRead(){failRead=true;},failAdopt(){failAdopt=true;},visible(visible:boolean){owner!.setAvailable(visible);},
  async begin(){owner?.dispose();const current=(await api.getCurrentDocument(identity)).data,created=(await api.prepareCreateGuide(identity,{action_type:'MODIFY',expected_version:current.content_version,scope_type:'DOCUMENT',scope_ref:null,source_type:'USER_INSTRUCTION',source_id:null,instruction:'建议批次前置夹具'}).submit()).data.guide_run;
   let completed=false;for(let attempt=0;attempt<200;attempt++){const run=(await api.getGuideRun(created.id)).data;if(run.status==='COMPLETED'){completed=true;break;}await new Promise(resolve=>setTimeout(resolve,25));}require(completed);const actual=await read();require(actual.activity.kind==='BATCH');owner=new RequirementSuggestionBatch(actual.activity.batch.id,actual,wrapped,read,async()=>{counts.adopts++;if(failAdopt){failAdopt=false;throw new ApiUnknown(false);}});owner.setAvailable(true);require(await owner.refresh());return {batch_id:actual.activity.batch.id,run_id:created.id,current};
  },draft:(id:number,value:string)=>owner!.draft(id,value),decide:(id:number,decision:'ACCEPTED'|'REJECTED'|'EDITED')=>owner!.decide(id,decision),complete:()=>owner!.complete(),discard:()=>owner!.discard(),recover:()=>owner!.recover(),finish:()=>owner!.finish(),current:async()=>(await api.getCurrentDocument(identity)).data,
  async destroy(){owner?.dispose();reader.dispose();return {passed:true,counts};}};
}
