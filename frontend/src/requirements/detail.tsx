import {REQUIREMENT_STATUS_LABELS,saveStatusLabel} from '../shared/status-labels.ts';
import {useEffect,useLayoutEffect,useMemo,useRef,useState,useSyncExternalStore} from 'react';
import type {WalleApi} from '../api/walle.ts';
import {RequirementDetailOwner} from './detail-owner.ts';
import {DetailFrame} from './detail-frame.tsx';
import {RequirementHeader} from './header.tsx';
import {OwnedDocumentControls,OwnedDocumentOutline} from './document-controls.tsx';
import {CommentPanel,CommentDocumentTools} from '../comments/panel.tsx';
import {RevisionList,RevisionSaveControl} from '../revisions/components.tsx';
import {GuideConversation} from '../guide/conversation.tsx';
import {Confirmation} from '../shared/confirmation.tsx';
import {ToastViewport} from '../shared/toast.tsx';
import {localTime} from '../shared/time.ts';
import {DocumentRecords} from './document-records.tsx';

function DocumentMount({host}:Readonly<{host:HTMLElement}>){const container=useRef<HTMLDivElement>(null);useLayoutEffect(()=>{container.current!.append(host);return()=>host.remove();},[host]);return <div className="detail-document-host" ref={container}/>;}
function SaveStatus({owner}:Readonly<{owner:RequirementDetailOwner}>){
 const state=useSyncExternalStore(owner.documents.subscribe,owner.documents.getSnapshot);
 const version=state.detail?.current.content_version,identity=state.mode==='HISTORY'?(state.revision?`历史版本 V${state.revision.version_no} · 来源正文 v${state.revision.source_content_version} · 只读`:'历史版本 · 只读'):state.mode==='MANUAL'?`人工草稿 · 基于正式正文 v${version}`:`正式正文 v${version} · 只读`;
 const activity=state.detail?.activity,task=state.mode==='CURRENT'?(activity?.kind==='GUIDE'?(activity.run.status==='WAITING_USER'?'等待补充信息':'AI 运行中'):activity?.kind==='BATCH'?'建议待处理 · 尚未应用':null):null;
 return <div className="document-view-status"><span>{identity}</span>{task&&<span className="task-state">{task}</span>}{state.manual&&<ManualSaveStatus session={state.manual} retained={state.mode==='HISTORY'}/>}</div>;
}
function ManualSaveStatus({session,retained}:Readonly<{session:NonNullable<ReturnType<RequirementDetailOwner['documents']['getSnapshot']>['manual']>;retained:boolean}>){
 const state=useSyncExternalStore(listener=>session.autosave.subscribe(()=>listener()),()=>session.autosave.state),manual=useSyncExternalStore(session.subscribe,session.getSnapshot);
 const recovery=useSyncExternalStore(session.recovery.subscribe,session.recovery.getSnapshot),ending=useSyncExternalStore(session.ending.subscribe,session.ending.getSnapshot);
 return <span role="status">{retained?'保留草稿：':''}{saveStatusLabel(state.status,manual.valid)}{manual.valid&&state.status==='SAVED'?' · '+localTime(state.saved_at):''}{!retained&&ending.phase==='EDITING'&&!['RESTORED','SERVER_SELECTED'].includes(recovery.phase)?recovery.checking?' · 正在检查草稿':recovery.local?' · 待处理恢复内容':' · 编辑恢复受阻':''}</span>;
}
function LoadedDetail({owner,host,back}:Readonly<{owner:RequirementDetailOwner;host:HTMLElement;back():void}>){
 const [documentActionHost,setDocumentActionHost]=useState<HTMLDivElement|null>(null);
 const state=useSyncExternalStore(owner.subscribe,owner.getSnapshot),document=useSyncExternalStore(owner.documents.subscribe,owner.documents.getSnapshot),departure=useSyncExternalStore(owner.departure.subscribe,owner.departure.getSnapshot),regions=owner.regions!;
 const geometry=useSyncExternalStore(regions.layout.subscribe,regions.layout.getSnapshot),viewport=useSyncExternalStore(regions.viewport.subscribe,regions.viewport.getSnapshot),historical=owner.documents.historical;
 const supported=geometry.mode!=='BLOCKED'&&viewport.phase==='SUPPORTED',blocked=!supported||departure.phase!=='IDLE',actual=state.detail!,activity=actual.activity.kind==='GUIDE'?(actual.activity.run.status==='WAITING_USER'?'等待回复':'AI 运行中'):actual.activity.kind==='BATCH'?'待处理建议':null;
 useEffect(()=>{const protect=(event:BeforeUnloadEvent)=>{const session=owner.documents.getSnapshot().manual;if(session&&(session.autosave.state.status!=='SAVED'||!['EDITING','CLOSED'].includes(session.ending.getSnapshot().phase))){event.preventDefault();event.returnValue='';}};window.addEventListener('beforeunload',protect);return()=>window.removeEventListener('beforeunload',protect);},[owner]);
 return <div className="detail-product">
  <DetailFrame layout={regions.layout} viewport={regions.viewport} title={actual.requirement.title} status={<div className="requirement-metadata"><span>{actual.requirement.requirement_no}</span><span>{actual.requirement.requirement_type==='NEW'?'需求新增':'需求改造'}</span><span className="requirement-state-badge" data-state={actual.requirement.status}>{REQUIREMENT_STATUS_LABELS[actual.requirement.status]}</span></div>}
   actions={null} properties={<RequirementHeader documentActions={<div className="requirement-document-actions" ref={setDocumentActionHost}/>} commands={regions.header} ready={state.ready} blocked={blocked||document.busy} history={historical} refresh={owner.refresh} refreshRevisions={async()=>{if(!await owner.documents.revisions.refresh())throw Error('实际版本列表暂时无法读取');}} notifyConfirmed={owner.notifyConfirmed}
    tools={<><dl className="requirement-property-summary"><dt>初始化模式</dt><dd>{actual.requirement.initialization_mode==='IDEATION'?'灵感模式':'设计模式'} · 创建后只读</dd></dl><button className="ui-button" type="button" disabled={blocked||document.busy||state.loading} onClick={()=>void owner.refresh().catch(()=>undefined)}>重新读取详情</button></>}/>}
   outline={<OwnedDocumentOutline owner={owner.documents} heading={false}/>}
   document={<><OwnedDocumentControls actionHost={documentActionHost} showSaveStatus={false} owner={owner.documents} blocked={blocked} auxiliary={document.mode!=='CURRENT'||!owner.documents.currentBinding} notifyConfirmed={owner.notifyConfirmed}/><CommentDocumentTools panel={regions.comments} documents={owner.documents} openPanel={owner.openComments}/>
    {state.error&&<p className="inline-error" role="alert">{state.error}</p>}<DocumentMount host={host}/></>}
   ai={<GuideConversation owner={regions.conversation} documents={owner.documents} toasts={owner.toasts}/>}
   comments={<CommentPanel panel={regions.comments} documents={owner.documents}/>}
   revisions={<DocumentRecords active={supported&&geometry.right_open&&geometry.right_tab==='REVISIONS'} blocked={blocked||document.busy} revisions={owner.documents.revisions} history={regions.conversation.read.history} readRun={owner.readRunRecord}
    versions={<>{state.revisionSave&&<RevisionSaveControl flow={state.revisionSave} ready={state.ready&&state.revisionSave.allowed} blocked={blocked||historical} refreshActual={owner.refresh} saved={receipt=>owner.savedRevision(receipt)}/>}
     <RevisionList flow={owner.documents.revisions} blocked={blocked||document.busy} open={summary=>void owner.openHistory(summary).catch(()=>undefined)}/></>}/>}
   activity={activity} saveStatus={<SaveStatus owner={owner}/>} back={()=>void owner.departure.request(back)} readPanel={(tab,signal)=>owner.readPanel(tab,signal)}/>
  {departure.phase==='SAVING'&&<p className="detail-leave-status" role="status">正在保存草稿，确认后离开…</p>}
  <Confirmation open={departure.phase==='WARNING'} title="仍有未同步的编辑内容" description={departure.local_protected?'后端草稿仍保留，本地最新内容已暂存。可以继续编辑，或明确离开后在此浏览器恢复。':'后端草稿仍保留，但最新本地内容尚未确认能够跨页面恢复。请继续编辑或先复制需要的文字；明确离开可能丢失尚未同步内容。'} busy={false} dangerous confirmLabel="仍然离开" cancelLabel="继续编辑" error={departure.error} confirm={()=>owner.departure.confirmLeave()} cancel={()=>owner.departure.continueEditing()}/>
  <ToastViewport store={owner.toasts}/>
 </div>;
}

/** Route-local lifetime. Required real reads precede any editable document.
 * The actual owned host moves into the single main region after initialization. */
export function RequirementDetail({identity,api,back,ready}:Readonly<{identity:number;api:WalleApi;back():void;ready?:(owner:RequirementDetailOwner)=>void}>){
 const host=useMemo(()=>{const element=document.createElement('div');element.className='requirement-owned-document';return element;},[identity,api]);
 const [owner,setOwner]=useState<RequirementDetailOwner|null>(null),callbacks=useRef({back,ready});callbacks.current={back,ready};
 useEffect(()=>{let storage:Storage|null=null;try{storage=window.localStorage;}catch{}
  const owned=new RequirementDetailOwner(identity,api,host,()=>window.innerWidth,storage,host);setOwner(owned);callbacks.current.ready?.(owned);void owned.refresh().catch(()=>undefined);
  return()=>{void owned.retire().catch(error=>console.error('WALL-E detail retirement failed',error));host.remove();};
 },[identity,api,host]);
 return owner?<DetailSurface owner={owner} host={host} back={()=>callbacks.current.back()}/>:<main aria-busy="true"><p role="status">正在读取需求与正文…</p><DocumentMount host={host}/></main>;
}
function DetailSurface({owner,host,back}:Readonly<{owner:RequirementDetailOwner;host:HTMLElement;back():void}>){
 const state=useSyncExternalStore(owner.subscribe,owner.getSnapshot);if(owner.regions)return <LoadedDetail owner={owner} host={host} back={back}/>;
 return <main className="detail-initial-state" aria-busy={state.loading}><button className="ui-button" type="button" onClick={()=>void owner.departure.request(back)}>返回需求工作台</button><h1>需求详情</h1>{state.loading?<p role="status">正在读取需求、正文与实际活动…</p>:state.error?<><p role="alert">{state.error}</p>{owner.read.getSnapshot().error_kind!=='MISSING'&&<button className="ui-button" type="button" onClick={()=>void owner.refresh().catch(()=>undefined)}>重新读取详情</button>}</>:<p role="status">正在展示正式正文…</p>}<div hidden inert><DocumentMount host={host}/></div></main>;
}
