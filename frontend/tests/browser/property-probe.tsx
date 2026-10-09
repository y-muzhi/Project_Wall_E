import {createRoot} from 'react-dom/client';
import {ApiUnknown} from '../../src/api/client.ts';
import type {WalleApi} from '../../src/api/walle.ts';
import {require} from '../../src/api/decoding.ts';
import {RequirementDetailRead} from '../../src/requirements/detail-read.ts';
import {RequirementPropertyEdit} from '../../src/requirements/property-edit.ts';
import {RequirementPropertyControl} from '../../src/requirements/property-control.tsx';
import type {RequirementProperty} from '../../src/requirements/property-edit.ts';
import type {DetailSnapshot} from '../../src/requirements/detail-read.ts';

/** Real title PATCH while holding an actual manual draft. Mode is creation-only.
 * Faults lose received native success only. No business memory stand-in or automatic PATCH replay. */
export async function mountPropertyProbe(api:WalleApi){
  const titleRoot=(await api.getRequirement(2)).data,titleCurrent=(await api.getCurrentDocument(2)).data;require(titleRoot.status==='ACTIVE'&&titleRoot.document_work_state==='IDLE');
  const draft=(await api.prepareStartManualDraft(2,titleCurrent.content_version).submit()).data.manual_draft;
  const element=document.createElement('main');element.id='native-property-controls';element.style.padding='24px';document.body.append(element);const react=createRoot(element);
  const fields=['title'] as const,identities=[2];let stage=0,closed=false,loseReceipt=true,loseRead=false,reads=0;
  let reader:RequirementDetailRead,initial:DetailSnapshot,flow:RequirementPropertyEdit,held=false,release:(()=>void)|undefined;
  const prepares:Partial<Record<RequirementProperty,number>>={},submits:Partial<Record<RequirementProperty,number>>={},firstTimes:Partial<Record<RequirementProperty,string>>={};
  const wrapped=new Proxy(api,{get(target,key){const value=Reflect.get(target,key);if(typeof value!=='function')return value;
    if(key==='getCommentIndex')return async(...args:Parameters<WalleApi['getCommentIndex']>)=>{const actual=await target.getCommentIndex(...args);if(loseRead){loseRead=false;throw new ApiUnknown(false);}return actual;};
    if(key==='prepareUpdateRequirement')return (...args:Parameters<WalleApi['prepareUpdateRequirement']>)=>{const field=Object.keys(args[1])[0] as RequirementProperty;require(field===fields[stage]&&Object.keys(args[1]).length===1);
      prepares[field]=(prepares[field]??0)+1;const original=target.prepareUpdateRequirement(...args);return {submit:async()=>{submits[field]=(submits[field]??0)+1;const actual=await original.submit();
        if(loseReceipt){loseReceipt=false;firstTimes[field]=actual.data.updated_at;held=true;await new Promise<void>(resolve=>{release=resolve;});held=false;release=undefined;throw new ApiUnknown(true);}require(actual.data.updated_at===firstTimes[field]);return actual;}};};return value.bind(target);}});
  async function setup(){reader=new RequirementDetailRead(identities[stage]!,wrapped);require(await reader.refresh());initial=reader.getSnapshot().confirmed!;
    require(initial.activity.kind==='MANUAL'&&initial.activity.draft.id===draft.id);
    flow=new RequirementPropertyEdit(fields[stage]!,initial,wrapped);loseReceipt=true;loseRead=true;
    react.render(<RequirementPropertyControl key={stage} flow={flow} blocked={false} refresh={async()=>{
      reads++;require(await reader.refresh());const actual=reader.getSnapshot().confirmed!;
      require(actual.current.id===initial.current.id&&actual.current.content_version===initial.current.content_version&&actual.current.markdown_content===initial.current.markdown_content&&JSON.stringify(actual.current.block_state_json)===JSON.stringify(initial.current.block_state_json));
      const other='initialization_mode';require(actual.requirement[other]===initial.requirement[other]&&actual.requirement.template_key===initial.requirement.template_key&&actual.requirement.template_version===initial.requirement.template_version);
      require(actual.activity.kind==='MANUAL'&&initial.activity.kind==='MANUAL'&&JSON.stringify(actual.activity.draft)===JSON.stringify(initial.activity.draft));return actual;
    }}/>);
  }
  await setup();
  async function inspectStage(){const state=flow.getSnapshot(),field=fields[stage]!;require(state.phase==='VIEW'&&state.receipt!==null&&prepares[field]===2&&submits[field]===2&&state.receipt.updated_at===firstTimes[field]);
    require(state.actual[field]===state.receipt[field]);return {field,identity:identities[stage],actual_value:state.actual[field],updated_at:state.actual.updated_at,first_written_at:firstTimes[field],work_state:state.actual.document_work_state};}
  const results:Awaited<ReturnType<typeof inspectStage>>[]=[];
  return {state:()=>({stage,phase:flow.getSnapshot().phase,state:flow.getSnapshot(),prepares,submits,reads,receipt_held:held,identity:identities[stage]}),
    releaseReceipt(){require(held&&release!==undefined);release();},
    async advance(){results.push(await inspectStage());flow.dispose();reader.dispose();await api.prepareCancelManualDraft(2,draft.content_version).submit();stage++;react.render(<p role="status">实际标题控件诊断完成</p>);},
    inspect(){require(stage===1&&results.length===1&&reads===3);return {passed:true,prepares,submits,full_reads:reads,results,scope:'Actual React title/manual activity, mode is creation-only, first native PATCH 200 lost, matching GET remains observation, I37 loss/pure retry, explicit new same-value PATCH/no timestamp change, no editor/current/template changes or Provider'};},
    destroy(){closed=true;flow.dispose();reader.dispose();react.unmount();element.remove();},get closed(){return closed;}};
}
