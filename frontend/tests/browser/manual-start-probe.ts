import {ApiRejected,ApiUnknown} from '../../src/api/client.ts';
import type {WalleApi} from '../../src/api/walle.ts';
import {require} from '../../src/api/decoding.ts';
import {ManualDraftStart} from '../../src/documents/manual-start.ts';
import {RequirementDetailRead} from '../../src/requirements/detail-read.ts';
function deferred(){let resolve!:()=>void;const promise=new Promise<void>(accept=>{resolve=accept;});return {promise,resolve};}

export async function manualStartProbe(api:WalleApi,identity:number){
  const reader=new RequirementDetailRead(identity,api);require(await reader.refresh());const initial=reader.getSnapshot().confirmed!;
  require(initial.activity.kind==='IDLE');const arrived=deferred(),release=deferred();let prepares=0,submits=0,first=true;
  let created:Awaited<ReturnType<ReturnType<WalleApi['prepareStartManualDraft']>['submit']>>['data']|undefined;
  const flow=new ManualDraftStart(initial.requirement,initial.current,{
    getRequirement:(...args)=>api.getRequirement(...args),getCurrentDocument:(...args)=>api.getCurrentDocument(...args),getManualDraft:(...args)=>api.getManualDraft(...args),
    prepareStartManualDraft:(...args)=>{
      prepares++;const original=api.prepareStartManualDraft(...args);return Object.freeze({submit:async()=>{
        submits++;const result=await original.submit();if(first){first=false;created=result.data;arrived.resolve();await release.promise;throw new ApiUnknown(true);}return result;
      }});
    },
  });
  try{
    const pending=flow.start();require(flow.start()===pending);await arrived.promise;
    require(flow.getSnapshot().phase==='SUBMITTING'&&flow.getSnapshot().receipt===null);
    const received=created!,draft=received.manual_draft;
    // Another page saves this actual draft while the start response is held.
    // Historical idempotent creation v1 must never overwrite the live v2.
    const saved=(await api.prepareSaveManualDraft(identity,{expected_version:draft.content_version,markdown_content:draft.markdown_content,block_state_json:draft.block_state_json}).submit()).data;
    require(saved.content_version===2);release.resolve();require(!await pending&&String(flow.getSnapshot().phase)==='UNKNOWN');require(!await flow.start()&&prepares===1);
    const retry=flow.retryUnknown();require(flow.retryUnknown()===retry);require(await retry);
    require(String(flow.getSnapshot().phase)==='STARTED'&&Number(prepares)===1&&submits===2);
    require(flow.getSnapshot().receipt!.manual_draft.content_version===1&&flow.getSnapshot().observed!.manual_draft!.content_version===2);
    require(await reader.refresh());const latest=reader.getSnapshot().confirmed!;
    require(latest.activity.kind==='MANUAL'&&latest.activity.draft.id===draft.id&&latest.activity.draft.content_version===2);
    require(latest.current.id===initial.current.id&&latest.current.content_version===initial.current.content_version&&latest.current.markdown_content===initial.current.markdown_content);
    await api.prepareCancelManualDraft(identity,saved.content_version).submit();require(await reader.refresh());require(reader.getSnapshot().confirmed!.activity.kind==='IDLE');
    return {passed:true,requirement_id:identity,prepares,submits,creation_receipt_version:1,latest_draft_version:2,current_version:initial.current.content_version,
      scope:'Actual native I09 201 held/discarded, another-page I11 save, I03/I08/I10 then exact original I09 replay and full detail reload; I13 cleanup. No editable session from stale receipt or paid AI'};
  }finally{
    release.resolve();flow.dispose();reader.dispose();
    try{const remaining=(await api.getManualDraft(identity)).data;await api.prepareCancelManualDraft(identity,remaining.content_version).submit();}
    catch(error){if(!(error instanceof ApiRejected&&error.code==='MANUAL_DRAFT_NOT_FOUND'))throw error;}
  }
}
