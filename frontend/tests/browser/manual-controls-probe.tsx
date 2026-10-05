import {createRoot} from 'react-dom/client';
import {ApiRejected,ApiUnknown} from '../../src/api/client.ts';
import type {WalleApi} from '../../src/api/walle.ts';
import {require} from '../../src/api/decoding.ts';
import {RequirementDetailRead} from '../../src/requirements/detail-read.ts';
import {RequirementEditor} from '../../src/documents/editor.ts';
import {DraftRecoveryStore} from '../../src/documents/recovery-store.ts';
import {ManualDraftAutosave} from '../../src/documents/autosave.ts';
import {ManualDraftStart} from '../../src/documents/manual-start.ts';
import {ManualDraftEnd} from '../../src/documents/manual-end.ts';
import {ManualDraftRecovery} from '../../src/documents/manual-recovery.ts';
import {ManualStartControl,ManualDraftControls} from '../../src/documents/manual-controls.tsx';
import {editorViewCtx} from '@milkdown/kit/core';
import type {DocumentReadModel} from '../../src/documents/contracts.ts';
import '../../src/shared/styles.css';

/** Native API/SQLite/IndexedDB/editor and actual React controls. Only explicitly
 * selected successful transport receipts are lost after the real HTTP call.
 * Explicit flush clock isolates UI states from the separate 2s/10s diagnostic. */
export async function mountManualControlsProbe(api:WalleApi,identity:number,operation:'COMPLETE'|'CANCEL',localMode:'AVAILABLE'|'COMPARE'|'NONE'){
  const section=document.createElement('main');section.id='native-manual-controls';section.style.padding='24px';document.body.append(section);
  const controls=document.createElement('section'),editor=document.createElement('section');editor.id='native-manual-controls-editor';section.append(controls,editor);
  const react=createRoot(controls),cacheName='walle-controls-'+crypto.randomUUID();let host:RequirementEditor|undefined,autosave:ManualDraftAutosave|undefined,cache:DraftRecoveryStore|undefined,recovery:ManualDraftRecovery|undefined,ending:ManualDraftEnd|undefined;
  let startPrepares=0,startSubmits=0,endPrepares=0,endSubmits=0,readAttempts=0,endedReads=0,serverReads=0,startLoss=true,endLoss=true,dropRead=false,closed=false;
  const readerApi=new Proxy(api,{get(target,key){const value=Reflect.get(target,key);if(typeof value!=='function')return value;
    if(key==='getCommentIndex')return async(...args:Parameters<WalleApi['getCommentIndex']>)=>{const result=await target.getCommentIndex(...args);if(dropRead){dropRead=false;throw new ApiUnknown(true);}return result;};
    return value.bind(target);}});
  const reader=new RequirementDetailRead(identity,readerApi);require(await reader.refresh());const initial=reader.getSnapshot().confirmed!;require(initial.activity.kind==='IDLE');
  const flow=new ManualDraftStart(initial.requirement,initial.current,{getRequirement:(...args)=>api.getRequirement(...args),getCurrentDocument:(...args)=>api.getCurrentDocument(...args),getManualDraft:(...args)=>api.getManualDraft(...args),
    prepareStartManualDraft:(...args)=>{startPrepares++;const original=api.prepareStartManualDraft(...args);return {submit:async()=>{startSubmits++;const result=await original.submit();if(startLoss){startLoss=false;throw new ApiUnknown(true);}return result;}};}});
  const read=async()=>{readAttempts++;if(!await reader.refresh())throw new Error('Actual detail read not confirmed');return reader.getSnapshot().confirmed!;};
  const render=()=>{if(closed)return;if(!ending||!autosave||!recovery||!host){react.render(<ManualStartControl flow={flow} disabled={false} started={started}/>);return;}
    react.render(<ManualDraftControls autosave={autosave} ending={ending} recovery={recovery} valid={host.valid} blocked={false}
      serverSelected={async server=>{const actual=await read();require(actual.activity.kind==='MANUAL'&&actual.activity.draft.id===server.id&&actual.activity.draft.content_version===server.content_version);serverReads++;}}
      ended={async(outcome,cleanupError)=>{const actual=await read();require(actual.activity.kind==='IDLE'&&!cleanupError);
        require(outcome.kind==='CANCELLED'?actual.current.content_version===initial.current.content_version:actual.current.id===initial.current.id&&actual.current.content_version===initial.current.content_version+1);
        endedReads++;react.render(<p role="status">实际详情已重新读取 · {outcome.kind==='COMPLETED'?'完成编辑':'取消编辑'}</p>);}}/>);
  };
  const create=async(draft:DocumentReadModel)=>{
    host=await RequirementEditor.create(editor,draft,true,{change:()=>{autosave?.changed();render();},validity:()=>render()});
    cache=host.action(ctx=>new DraftRecoveryStore(ctx,{name:cacheName}));
    autosave=new ManualDraftAutosave(draft,host.ledger!,{read:async()=>(await api.getManualDraft(identity)).data,save:async ticket=>(await api.prepareSaveManualDraft(identity,{expected_version:ticket.expected_version,markdown_content:ticket.markdown_content,block_state_json:ticket.block_state_json}).submit()).data},cache,{schedule:()=>()=>{}});
  };
  async function started(){
    if(host)return;const actual=await read();require(actual.activity.kind==='MANUAL');let draft=actual.activity.draft;await create(draft);
    if(localMode!=='NONE'){
      host!.setReadonly(false);host!.action(ctx=>{const view=ctx.get(editorViewCtx);view.dispatch(view.state.tr.insert(view.state.doc.content.size,view.state.schema.nodes.paragraph!.create(null,view.state.schema.text('实际本地待恢复内容😀'))));});
      const local={schema_version:1 as const,base_confirmed_version:draft.content_version,...autosave!.localSnapshot,local_revision:autosave!.state.local_revision,updated_at:new Date().toISOString()};require(await cache!.put(identity,draft.id,local));
      if(localMode==='COMPARE')draft=(await api.prepareSaveManualDraft(identity,{expected_version:draft.content_version,markdown_content:draft.markdown_content,block_state_json:draft.block_state_json}).submit()).data;
      autosave!.dispose();await host!.destroy();cache!.close();
      await create(draft);
    }
    recovery=new ManualDraftRecovery(actual.requirement,actual.current,draft,api,host!,autosave!,cache!);
    const port={getRequirement:(...args:Parameters<WalleApi['getRequirement']>)=>api.getRequirement(...args),getCurrentDocument:(...args:Parameters<WalleApi['getCurrentDocument']>)=>api.getCurrentDocument(...args),getManualDraft:(...args:Parameters<WalleApi['getManualDraft']>)=>api.getManualDraft(...args),
      prepareCompleteManualDraft:(...args:Parameters<WalleApi['prepareCompleteManualDraft']>)=>{endPrepares++;const original=api.prepareCompleteManualDraft(...args);return {submit:async()=>{endSubmits++;const result=await original.submit();if(endLoss){endLoss=false;throw new ApiUnknown(true);}return result;}};},
      prepareCancelManualDraft:(...args:Parameters<WalleApi['prepareCancelManualDraft']>)=>{endPrepares++;const original=api.prepareCancelManualDraft(...args);return {submit:async()=>{endSubmits++;const result=await original.submit();if(endLoss){endLoss=false;throw new ApiUnknown(true);}return result;}};}};
    ending=new ManualDraftEnd(actual.current,draft,port,host!,autosave!,cache!);render();await recovery.inspect();
  }
  render();
  return {state:()=>({operation,localMode,start:flow.getSnapshot(),recovery:recovery?.getSnapshot(),end:ending?.getSnapshot(),save:autosave?.state,readonly:host?.readonly,valid:host?.valid,startPrepares,startSubmits,endPrepares,endSubmits,readAttempts,endedReads,serverReads}),
    flush:async()=>{require(host!.flushLocal());await autosave!.flush();require(autosave!.state.status==='SAVED');},dropNextRead:()=>{dropRead=true;},
    composition:(start:boolean)=>editor.querySelector('.ProseMirror')!.dispatchEvent(new CompositionEvent(start?'compositionstart':'compositionend',{bubbles:true})),
    async inspect(){const root=(await api.getRequirement(identity)).data,current=(await api.getCurrentDocument(identity)).data;require(root.document_work_state==='IDLE'&&endedReads===1&&startPrepares===1&&startSubmits===2&&endPrepares===1&&endSubmits===2);
      require(await cache!.get(identity,flow.getSnapshot().receipt!.manual_draft.id)===null);
      require(current.content_version===initial.current.content_version+(operation==='COMPLETE'?1:0));return {passed:true,operation,localMode,startPrepares,startSubmits,endPrepares,endSubmits,endedReads,serverReads,readAttempts,current_version:current.content_version};},
    async destroy(){closed=true;flow.dispose();reader.dispose();ending?.dispose();recovery?.dispose();autosave?.dispose();react.unmount();await host?.destroy();cache?.close();section.remove();
      try{const draft=(await api.getManualDraft(identity)).data;await api.prepareCancelManualDraft(identity,draft.content_version).submit();}catch(error){if(!(error instanceof ApiRejected&&error.code==='MANUAL_DRAFT_NOT_FOUND'))throw error;}}
  };
}
