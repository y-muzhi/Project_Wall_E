import {createRoot} from 'react-dom/client';
import {ApiUnknown} from '../../src/api/client.ts';
import type {WalleApi} from '../../src/api/walle.ts';
import {require} from '../../src/api/decoding.ts';
import {RequirementDetailRead} from '../../src/requirements/detail-read.ts';
import {RequirementLifecycle} from '../../src/requirements/lifecycle.ts';
import {RequirementLifecycleControl} from '../../src/requirements/lifecycle-control.tsx';
import type {LifecycleOperation} from '../../src/requirements/lifecycle.ts';
const operations=['INITIALIZATION','COMPLETE','REACTIVATE'] as const;

/** Actual untouched initializing requirement from the previously created
 * native workbench. No extra requirement/Run or fabricated baseline. */
export async function mountLifecycleProbe(api:WalleApi){
  const list=await api.listRequirements({status:['INITIALIZING']});let identity=0;
  for(const row of list.data.items){const candidate=(await api.getRequirement(row.id)).data;if(candidate.document_work_state==='IDLE'){identity=row.id;break;}}
  require(identity>0);const element=document.createElement('main');element.id='native-lifecycle-controls';element.style.padding='24px';document.body.append(element);const react=createRoot(element);
  let stage=0,flow:RequirementLifecycle,loseReceipt=true,loseDetailRead=true,closed=false,adoptions=0;
  const prepares:Partial<Record<LifecycleOperation,number>>={},submits:Partial<Record<LifecycleOperation,number>>={};
  const wrapped=new Proxy(api,{get(target,key){const value=Reflect.get(target,key);if(typeof value!=='function')return value;
    if(key==='getCommentIndex')return async(...args:Parameters<WalleApi['getCommentIndex']>)=>{const actual=await target.getCommentIndex(...args);if(loseDetailRead){loseDetailRead=false;throw new ApiUnknown(true);}return actual;};
    const operation=key==='prepareCompleteInitialization'?'INITIALIZATION':key==='prepareCompleteRequirement'?'COMPLETE':key==='prepareReactivateRequirement'?'REACTIVATE':null;
    if(operation)return (...args:unknown[])=>{prepares[operation]=(prepares[operation]??0)+1;const original=value.apply(target,args);return {submit:async()=>{submits[operation]=(submits[operation]??0)+1;const actual=await original.submit();if(loseReceipt){loseReceipt=false;throw new ApiUnknown(true);}return actual;}};};return value.bind(target);}});
  // First read occurs before fault selection; losses only affect post-command
  // actual full reads, not an invented failed resource.
  loseDetailRead=false;const reader=new RequirementDetailRead(identity,wrapped);require(await reader.refresh());const initial=reader.getSnapshot().confirmed!;
  const previous=(await api.listRevisions(identity)).meta.pagination!;require('page' in previous);const initialTotal=previous.total;let baselineId:number|null=null;
  function render(){if(closed)return;if(stage===operations.length){react.render(<p role="status">实际详情已重新读取 · 已完成全部生命周期诊断</p>);return;}
    const op=operations[stage]!;
    react.render(<RequirementLifecycleControl key={op} flow={flow} blocked={false} changed={async outcome=>{
      require(outcome.kind===op);if(!await reader.refresh())throw Error('Actual full read lost');const actual=reader.getSnapshot().confirmed!;
      require(actual.activity.kind==='IDLE'&&actual.requirement.status===(op==='COMPLETE'?'COMPLETED':'ACTIVE')&&actual.current.id===initial.current.id&&actual.current.content_version===initial.current.content_version&&
        actual.current.markdown_content===initial.current.markdown_content&&JSON.stringify(actual.current.block_state_json)===JSON.stringify(initial.current.block_state_json));
      if(outcome.kind==='INITIALIZATION'){baselineId=outcome.result.baseline_revision.id;const revision=(await api.getRevision(baselineId)).data;
        require(revision.revision_type==='BASELINE'&&revision.version_no===1&&revision.description==='初始化基线'&&revision.source_content_version===initial.current.content_version&&
          revision.markdown_content===initial.current.markdown_content&&JSON.stringify(revision.block_state_json)===JSON.stringify(initial.current.block_state_json));}
      adoptions++;stage++;flow.dispose();if(stage<operations.length){loseReceipt=true;loseDetailRead=true;flow=new RequirementLifecycle(operations[stage]!,actual,wrapped);}render();
    }}/>);
  }
  loseDetailRead=true;flow=new RequirementLifecycle(operations[0],initial,wrapped);render();
  return {state:()=>({identity,stage,phase:flow.getSnapshot().phase,state:flow.getSnapshot(),prepares,submits,adoptions,source_current_version:initial.current.content_version}),
    async inspect(){require(stage===3&&adoptions===3&&baselineId!==null);const [root,current,revisions]=await Promise.all([api.getRequirement(identity),api.getCurrentDocument(identity),api.listRevisions(identity)]);
      require(root.data.status==='ACTIVE'&&root.data.document_work_state==='IDLE'&&current.data.content_version===initial.current.content_version&&current.data.markdown_content===initial.current.markdown_content);
      const pagination=revisions.meta.pagination!;require('page' in pagination&&pagination.total===initialTotal+1);
      for(const op of operations)require(prepares[op]===1&&submits[op]===2);
      return {passed:true,identity,prepares,submits,adoptions,baseline_id:baselineId,source_current_version:initial.current.content_version,revision_count_before:initialTotal,revision_count_after:pagination.total,
        scope:'Native existing initializing requirement, actual React controls/confirmations, real I05/I06/I07 receipts lost then original replay, each post-confirmation I37 dropped and pure read retry, actual BASELINE full pair and unchanged CURRENT; no Provider or complete product page'};
    },destroy(){closed=true;flow.dispose();reader.dispose();react.unmount();element.remove();}};
}
