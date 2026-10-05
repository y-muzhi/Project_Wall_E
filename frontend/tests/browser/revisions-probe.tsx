import {createRoot} from 'react-dom/client';
import {useLayoutEffect,useSyncExternalStore} from 'react';
import {ApiUnknown} from '../../src/api/client.ts';
import {require} from '../../src/api/decoding.ts';
import type {WalleApi} from '../../src/api/walle.ts';
import {RequirementDetailRead} from '../../src/requirements/detail-read.ts';
import {RequirementEditor} from '../../src/documents/editor.ts';
import {RequirementRevisionSave} from '../../src/revisions/save.ts';
import {RequirementRevisions} from '../../src/revisions/read.ts';
import {RevisionSaveControl,RevisionList,RevisionHistory} from '../../src/revisions/components.tsx';
import type {RevisionViewer} from '../../src/revisions/viewer.ts';

export async function mountRevisionsProbe(api:WalleApi){
  const element=document.createElement('main');element.id='native-revisions';element.style.padding='24px';const currentRegion=document.createElement('section'),currentHost=document.createElement('div'),commentHost=document.createElement('div');
  currentHost.className='detail-document-content';commentHost.id='native-current-comments';currentRegion.append(currentHost,commentHost);const controls=document.createElement('div');element.append(currentRegion,controls);document.body.append(element);
  const react=createRoot(controls);let lostReceipt=true,lostList=false,lostActual=false,lostRestore=true,prepares=0,submits=0,adoptions=0,restorations=0,viewer:RevisionViewer|undefined,viewerEvidence:unknown;
  const wrapped=new Proxy(api,{get(target,key){const value=Reflect.get(target,key);if(typeof value!=='function')return value;
    if(key==='listRevisions')return async(...args:Parameters<WalleApi['listRevisions']>)=>{const actual=await target.listRevisions(...args);if(lostList){lostList=false;throw new ApiUnknown(false);}return actual;};
    if(key==='getCommentIndex')return async(...args:Parameters<WalleApi['getCommentIndex']>)=>{const actual=await target.getCommentIndex(...args);if(lostActual){lostActual=false;throw new ApiUnknown(false);}return actual;};
    if(key==='prepareCreateRevision')return (...args:Parameters<WalleApi['prepareCreateRevision']>)=>{prepares++;const original=target.prepareCreateRevision(...args);return {submit:async()=>{submits++;const actual=await original.submit();if(lostReceipt){lostReceipt=false;throw new ApiUnknown(true);}lostList=true;return actual;}};};return value.bind(target);}});
  const reader=new RequirementDetailRead(2,wrapped);require(await reader.refresh());const initial=reader.getSnapshot().confirmed!;require(initial.activity.kind==='IDLE'&&initial.requirement.status==='ACTIVE');
  await api.prepareCreateComment(2,{expected_content_version:initial.current.content_version,content:'CURRENT评论不进入历史',anchor_type:'BLOCK',block_id:initial.current.block_state_json.blocks[0]!.block_id}).submit();
  require(await reader.refresh());const comments=(await api.listComments(2)).data.items;require(comments.length===1);for(const item of comments){const p=document.createElement('p');p.textContent=item.content;commentHost.append(p);}
  const currentEditor=await RequirementEditor.create(currentHost,initial.current,true),list=new RequirementRevisions(2,wrapped);require(await list.refresh());const initialRevisionTotal=list.getSnapshot().list!.pagination.total;
  const flow=new RequirementRevisionSave(reader.getSnapshot().confirmed!,wrapped);
  const readActual=async()=>{require(await reader.refresh());return reader.getSnapshot().confirmed!;};
  function View(){const history=useSyncExternalStore(list.subscribe,list.getSnapshot).history;useSyncExternalStore(reader.subscribe,reader.getSnapshot);
    useLayoutEffect(()=>{currentRegion.hidden=history.phase!=='CLOSED';currentRegion.inert=history.phase!=='CLOSED';},[history.phase]);
    return <><RevisionSaveControl flow={flow} ready={reader.writeReady} blocked={history.phase!=='CLOSED'} refreshActual={readActual} saved={async receipt=>{require(receipt.source_content_version===initial.current.content_version);require(await list.refresh());adoptions++;}}/>
      <RevisionList flow={list} blocked={false} open={summary=>void list.open(summary)}/>
      <RevisionHistory flow={list} refreshActual={readActual} ready={actual=>{viewer=actual;}} restored={async actual=>{
        if(lostRestore){lostRestore=false;throw Error('Deliberate parent restoration loss');}
        require(actual.current.id===initial.current.id&&actual.current.content_version===initial.current.content_version&&actual.current.markdown_content===initial.current.markdown_content&&JSON.stringify(actual.current.block_state_json)===JSON.stringify(initial.current.block_state_json));
        require((await api.listComments(2)).data.items.length===1);restorations++;
      }}/></>;
  }
  react.render(<View/>);
  return {state:()=>({save:flow.getSnapshot(),list:list.getSnapshot(),prepares,submits,adoptions,restorations,viewer_ready:viewer!==undefined,current_hidden:currentRegion.hidden}),
    async seedPages(){for(let index=0;index<20;index++)await api.prepareCreateRevision(2,{expected_version:initial.current.content_version,description:'真实分页验证 '+index}).submit();require(await list.refresh(1));},
    captureViewer(){require(viewer!==undefined&&viewer.unchanged&&JSON.stringify(viewer.blockIds)===JSON.stringify(viewer.snapshot.block_state_json.blocks.map(block=>block.block_id)));require(!Object.hasOwn(viewer.snapshot,'document_type')&&!Object.hasOwn(viewer.snapshot,'content_version')&&Object.keys(viewer.snapshot).length===9);
      viewerEvidence={revision_id:viewer.snapshot.id,version_no:viewer.snapshot.version_no,source_content_version:viewer.snapshot.source_content_version,requirement_id:viewer.snapshot.requirement_id,block_ids:viewer.blockIds,unchanged:true,field_count:9};return viewerEvidence;},
    async completeAndFailExit(){await api.prepareCompleteRequirement(2,initial.current.content_version).submit();lostActual=true;},
    async inspect(){require(prepares===1&&submits===2&&adoptions===1&&restorations===1&&viewerEvidence!==undefined&&list.getSnapshot().history.phase==='CLOSED'&&list.getSnapshot().history.restored?.requirement.status==='COMPLETED');
      const [current,root,revisions]=await Promise.all([api.getCurrentDocument(2),api.getRequirement(2),api.listRevisions(2)]);require(root.data.status==='COMPLETED'&&current.data.content_version===initial.current.content_version&&current.data.markdown_content===initial.current.markdown_content&&JSON.stringify(current.data.block_state_json)===JSON.stringify(initial.current.block_state_json));
      const pagination=revisions.meta.pagination!;require('page' in pagination&&pagination.total===initialRevisionTotal+21);return {passed:true,prepares,submits,adoptions,restorations,viewer:viewerEvidence,current_document_id:current.data.id,current_version:current.data.content_version,initial_revision_total:initialRevisionTotal,revision_total:pagination.total,actual_status:root.data.status,
        scope:'Native save 201 loss/original replay/real list-read loss/pure retry, actual 22-row pagination and I25 baseline Revision viewer, native readonly keyboard/no current comment, actual completion during history, exit GET loss and parent restoration loss retain history until fresh actual adoption; no product route/session or Provider'};},
    async destroy(){flow.dispose();list.dispose();reader.dispose();react.unmount();await viewer?.destroy();await currentEditor.destroy();element.remove();}};
}
