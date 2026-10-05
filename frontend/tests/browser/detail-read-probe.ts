import type {WalleApi} from '../../src/api/walle.ts';
import {require} from '../../src/api/decoding.ts';
import {RequirementDetailRead} from '../../src/requirements/detail-read.ts';
function deferred(){let resolve!:()=>void;const promise=new Promise<void>(accept=>{resolve=accept;});return {promise,resolve};}
/** Actual API/SQLite reads; hold/discard happen only after actual successful
 * responses. No manufactured activity or successful Provider result. */
export async function detailReadProbe(api:WalleApi,identity:number){
  let hold=false,drop=false,waiting=deferred(),arrived=deferred();
  const reader=new RequirementDetailRead(identity,{
    getRequirement:(...args)=>api.getRequirement(...args),getCurrentDocument:(...args)=>api.getCurrentDocument(...args),
    getManualDraft:(...args)=>api.getManualDraft(...args),getGuideRun:(...args)=>api.getGuideRun(...args),getBatch:(...args)=>api.getBatch(...args),
    async getCommentIndex(...args){const result=await api.getCommentIndex(...args);if(hold){hold=false;arrived.resolve();await waiting.promise;}if(drop){drop=false;throw Error('Diagnostic discard after actual index GET');}return result;},
  });
  function holdIndex(){hold=true;waiting=deferred();arrived=deferred();}
  let draftId:number|null=null;
  try{
    require(await reader.refresh());require(String(reader.phase)==='IDLE_VIEW'&&reader.writeReady);
    const initial=reader.getSnapshot().confirmed!;require(initial.comment_index.total_count===1&&initial.current.document_type==='CURRENT');
    holdIndex();const titleRead=reader.refresh();await arrived.promise;
    const title=(await api.prepareUpdateRequirement(identity,{title:'详情读取后最新标题'}).submit()).data;waiting.resolve();require(await titleRead);
    require(reader.getSnapshot().confirmed!.requirement.title===title.title);
    const before=reader.getSnapshot().confirmed;
    holdIndex();const changing=reader.refresh();await arrived.promise;
    const draft=(await api.prepareStartManualDraft(identity,initial.current.content_version).submit()).data.manual_draft;draftId=draft.id;
    waiting.resolve();require(!await changing);require(String(reader.phase)==='CONTENT_VERSION_CONFLICT'&&!reader.writeReady&&reader.getSnapshot().confirmed===before);
    require(await reader.refresh());const manual=reader.getSnapshot().confirmed!;
    require(String(reader.phase)==='MANUAL_EDITING'&&manual.activity.kind==='MANUAL'&&manual.activity.draft.id===draft.id&&manual.current.id!==draft.id);
    require(manual.activity.kind==='MANUAL'&&manual.activity.draft.content_version===1&&manual.current.content_version===initial.current.content_version);
    drop=true;require(!await reader.refresh());require(String(reader.phase)==='DETAIL_ERROR'&&reader.getSnapshot().confirmed===manual&&!reader.writeReady);
    require(await reader.refresh());holdIndex();const paused=reader.refresh();await arrived.promise;reader.pause();waiting.resolve();require(!await paused&&!reader.writeReady);
    require(await reader.refresh());await api.prepareCancelManualDraft(identity,1).submit();draftId=null;
    require(await reader.refresh());require(String(reader.phase)==='IDLE_VIEW'&&reader.getSnapshot().confirmed!.current.markdown_content===initial.current.markdown_content);
    const missing=new RequirementDetailRead(9999,api);try{require(!await missing.refresh()&&missing.phase==='DETAIL_MISSING'&&missing.getSnapshot().confirmed===null);}finally{missing.dispose();}
    return {passed:true,requirement_id:identity,current_version:initial.current.content_version,draft_version:1,index_count:initial.comment_index.total_count,
      native_title:title.title,phases:['IDLE_VIEW','CONTENT_VERSION_CONFLICT','MANUAL_EDITING','DETAIL_ERROR','DETAIL_MISSING'],
      scope:'Actual I03/I08/I10/I37, I04 update and I09/I12 cancel on isolated SQLite; index hold/discard is explicit local injection. No native RUNNING/WAITING_USER/successful batch or full detail product claim'};
  }finally{
    waiting.resolve();reader.dispose();
    if(draftId!==null){const current=(await api.getManualDraft(identity)).data;await api.prepareCancelManualDraft(identity,current.content_version).submit();}
  }
}
