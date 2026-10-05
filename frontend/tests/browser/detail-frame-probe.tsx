import { useSyncExternalStore, useState } from 'react';
import { createRoot } from 'react-dom/client';
import type { WalleApi } from '../../src/api/walle.ts';
import { require } from '../../src/api/decoding.ts';
import { DetailFrame } from '../../src/requirements/detail-frame.tsx';
import { DetailLayout,DetailViewportGuard,preferencesKey } from '../../src/requirements/detail-layout.ts';
import type { DetailTab } from '../../src/requirements/detail-layout.ts';
import { RequirementEditor } from '../../src/documents/editor.ts';
import { ManualDraftAutosave } from '../../src/documents/autosave.ts';
import { DraftRecoveryStore } from '../../src/documents/recovery-store.ts';

function deferred() {let resolve!:()=>void;const promise=new Promise<void>(accept=>{resolve=accept;});return {promise,resolve};}
export async function mountDetailFrameProbe(api: WalleApi,identity: number) {
  const originalPreference=localStorage.getItem(preferencesKey);localStorage.removeItem(preferencesKey);
  const requirement=(await api.getRequirement(identity)).data,current=(await api.getCurrentDocument(identity)).data;
  const draft=(await api.prepareStartManualDraft(identity,current.content_version).submit()).data.manual_draft;
  const element=document.createElement('section');element.id='native-detail-frame';document.body.append(element);element.scrollIntoView();
  const root=createRoot(element),layout=new DetailLayout(requirement.status,window.innerWidth,localStorage);
  let host:RequirementEditor,autosave:ManualDraftAutosave,cache:DraftRecoveryStore;
  let restoreReads=0,saves=0,holdNext=false,dropNext=false,held=false,release:()=>void=()=>{};
  const panelReads:DetailTab[]=[],events:string[]=[],errors:string[]=[];
  const guard=new DetailViewportGuard(window.innerWidth,{
    async blockAndSave(){
      if(!host)return;const valid=host.flushLocal();host.setReadonly(true);saves++;require(valid);
      if(!await autosave.freezeAndFlush())throw Error('Actual draft not synchronized');
    },
    async readAfterSupport(signal){
      restoreReads++;
      const [r,d,c]=await Promise.all([api.getRequirement(identity,signal),api.getManualDraft(identity,signal),api.getCurrentDocument(identity,signal)]);
      if(holdNext){holdNext=false;held=true;const waiting=deferred();release=waiting.resolve;await waiting.promise;held=false;}
      if(dropNext){dropNext=false;throw Error('Diagnostic discard after actual read');}
      if(signal.aborted)throw Error('Owned read retired');
      require(r.data.document_work_state==='MANUAL_EDITING'&&r.data.active_operation_id===draft.id&&d.data.id===draft.id&&d.data.content_version===autosave.state.confirmed_version);
      require(c.data.content_version===current.content_version&&c.data.markdown_content===current.markdown_content);
      autosave.resumeEditing();host.setReadonly(false);
    },
  });
  let readPanel:(tab:DetailTab,signal:AbortSignal)=>Promise<void>=async()=>{};
  function App(){
    const save=useSyncExternalStore(listener=>autosave ? autosave.subscribe(()=>listener()) : ()=>{},()=>autosave?.state??null);
    const [panels,setPanels]=useState<Record<DetailTab,string>>({AI:'正在读取实际消息…',COMMENTS:'正在读取实际评论…',REVISIONS:'正在读取实际版本…'});
    readPanel=async(tab,signal)=>{
      panelReads.push(tab);
      const text=tab==='AI' ? (await api.listMessages(identity,null,signal)).data.items.map(m=>m.content).join('\n') :
        tab==='COMMENTS' ? (await api.listComments(identity,1,signal)).data.items.map(c=>c.content).join('\n') :
          (await api.listRevisions(identity,1,signal)).data.items.map(r=>r.description).join('\n');
      if(!signal.aborted)setPanels(previous=>({...previous,[tab]:text||'实际接口返回空列表'}));
    };
    return <DetailFrame layout={layout} viewport={guard} title={requirement.title} status={`${requirement.requirement_no} · 布局诊断宿主`}
      actions={<button type="button" onClick={()=>events.push('layout-only')}>布局诊断操作</button>}
      outline={<p>大纲槽位诊断；本单元不实现章节业务。</p>} document={<div id="detail-frame-editor" />}
      ai={<p>{panels.AI}</p>} comments={<p>{panels.COMMENTS}</p>} revisions={<p>{panels.REVISIONS}</p>}
      activity="运行状态诊断提示" saveStatus={<span>{save?.status??'正在载入实际草稿…'}</span>}
      back={()=>events.push('back-intent')} readPanel={(tab,signal)=>readPanel(tab,signal)} />;
  }
  root.render(<App/>);
  for(let i=0;i<100&&!element.querySelector('#detail-frame-editor');i++)await new Promise(resolve=>requestAnimationFrame(resolve));
  const editorRoot=element.querySelector<HTMLElement>('#detail-frame-editor')!;require(editorRoot!==null);
  host=await RequirementEditor.create(editorRoot,draft,false,{change:()=>autosave?.changed(),error:message=>{if(message)errors.push(message);}});
  cache=host.action(ctx=>new DraftRecoveryStore(ctx,{name:'walle-detail-frame-'+crypto.randomUUID()}));
  autosave=new ManualDraftAutosave(draft,host.ledger!,{
    read:async()=> (await api.getManualDraft(identity)).data,
    save:async ticket=>(await api.prepareSaveManualDraft(identity,{expected_version:ticket.expected_version,markdown_content:ticket.markdown_content,block_state_json:ticket.block_state_json}).submit()).data,
  },cache);
  // Trigger the first actual save-state subscription without replacing the host.
  root.render(<App/>);
  return {
    state:()=>({geometry:layout.getSnapshot(),guard:guard.getSnapshot(),save:autosave.state,markdown:host.ledger!.currentSnapshot.markdown_content,
      readonly:host.readonly,saves,restoreReads,panelReads,events,errors,held,editor_connected:editorRoot.isConnected}),
    holdNextRead:()=>{holdNext=true;},dropNextRead:()=>{dropNext=true;},release:()=>release(),
    async inspect(){const actual=(await api.getManualDraft(identity)).data;require(actual.markdown_content===host.ledger!.currentSnapshot.markdown_content);require(JSON.stringify(actual.block_state_json)===JSON.stringify(host.ledger!.currentSnapshot.block_state_json));return {passed:true,version:actual.content_version,markdown:actual.markdown_content};},
    async destroy(){
      release();guard.dispose();require(host.flushLocal());host.setReadonly(true);require(await autosave.freezeAndFlush());await autosave.pauseAndWait();
      await api.prepareCancelManualDraft(identity,autosave.state.confirmed_version).submit();await cache.clearClosedDraft(identity,draft.id);
      autosave.dispose();cache.close();await host.destroy();root.unmount();element.remove();
      if(originalPreference===null)localStorage.removeItem(preferencesKey);else localStorage.setItem(preferencesKey,originalPreference);
      window.scrollTo(0,0);return {closed:true};
    },
  };
}
