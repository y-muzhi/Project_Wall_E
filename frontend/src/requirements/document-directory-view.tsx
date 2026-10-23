import {useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import {createPortal} from 'react-dom';
import type {RequirementDetailOwner} from './detail-owner.ts';
import type {DocumentSummary} from '../api/models.ts';
import {documentKinds} from '../api/models.ts';
import {documentKindLabels,documentStructureRefs} from './catalog.ts';
import {OwnedDocumentOutline} from './document-controls.tsx';
import {SingleSelect} from '../shared/single-select.tsx';
import {Confirmation} from '../shared/confirmation.tsx';
import {registerModal,trapModalTab} from '../shared/modal.ts';
import {Icon} from '../shared/icon.tsx';

function CreateDocumentDialog({owner,close}:{owner:RequirementDetailOwner;close():void}){
 const flow=owner.regions!.directory,state=useSyncExternalStore(flow.subscribe,flow.getSnapshot);
 const [name,setName]=useState(''),[kind,setKind]=useState<typeof documentKinds[number]>('REQUIREMENT_BRIEF'),[framework,setFramework]=useState(false),[error,setError]=useState<string|null>(null);
 const dialog=useRef<HTMLDialogElement>(null),composing=useRef(false),pending=useRef(false);
 const locked=['SUBMITTING','UNKNOWN','CONFIRMED'].includes(state.phase);
 useLayoutEffect(()=>{const element=dialog.current!,previous=document.activeElement; element.showModal();const release=registerModal(element);element.querySelector('input')?.focus();return()=>{element.close();release();if(previous instanceof HTMLElement&&previous.isConnected)previous.focus();};},[]);
 const submit=async()=>{if(pending.current||composing.current)return;pending.current=true;setError(null);try{
  const done=state.phase==='UNKNOWN'?await flow.retryUnknown():state.phase==='CONFIRMED'?await flow.finish():await flow.create({name,document_kind:kind,template_ref:framework?documentStructureRefs[kind]!:null});if(done)close();
 }catch(error){setError(error instanceof Error?error.message:'文档暂时无法创建');}finally{pending.current=false;}};
 return createPortal(<dialog ref={dialog} className="create-drawer" aria-label="新建文档" onKeyDown={trapModalTab} onCancel={event=>{event.preventDefault();if(!locked)close();}} onCompositionStart={()=>{composing.current=true;}} onCompositionEnd={()=>{composing.current=false;}}>
  <form noValidate onSubmit={event=>{event.preventDefault();void submit();}}><header><h2>新建文档</h2><button type="button" className="ui-button icon-button" aria-label="关闭新建文档" disabled={locked} onClick={close}><Icon name="close"/></button></header>
   <div className="create-fields"><label>文档名称<input className="ui-input" autoComplete="off" value={name} disabled={locked} onChange={event=>setName(event.currentTarget.value)}/></label>
    <label>文档类型<SingleSelect label="文档类型" value={kind} disabled={locked} options={documentKinds.map(value=>({value,label:documentKindLabels[value]}))} change={value=>setKind(value as typeof kind)}/></label>
    <label>初始内容<SingleSelect label="初始内容" value={framework?'FRAMEWORK':'EMPTY'} disabled={locked} options={[{value:'EMPTY',label:'空白文档'},{value:'FRAMEWORK',label:'固定框架'}]} change={value=>setFramework(value==='FRAMEWORK')}/></label>
    <p className="field-help">创建空白或框架文档，不调用 AI。</p>{(error||state.error)&&<p role="alert" className="inline-error">{error??state.error}</p>}
   </div><footer><button type="button" className="ui-button" disabled={locked} onClick={close}>取消</button><button className="ui-button primary" type="submit" disabled={state.phase==='SUBMITTING'}>{state.phase==='UNKNOWN'?'核实创建结果':state.phase==='CONFIRMED'?'重新读取已创建文档':'创建文档'}</button></footer>
  </form>
 </dialog>,document.body);
}

export function DocumentDirectory({owner}:{owner:RequirementDetailOwner}){
 const state=useSyncExternalStore(owner.subscribe,owner.getSnapshot),flow=owner.regions!.directory;
 useSyncExternalStore(flow.subscribe,flow.getSnapshot);
 const [tab,setTab]=useState<'DOCUMENTS'|'OUTLINE'>('DOCUMENTS'),[error,setError]=useState<string|null>(null),actual=state.detail;
 if(!actual)return null;
 const select=async(identity:number)=>{setError(null);try{await owner.selectDocument(identity);}catch(error){setError(error instanceof Error?error.message:'文档暂时无法读取');}};
 const rows=(items:readonly DocumentSummary[])=>items.map(document=><li key={document.id}><button className="ui-button document-directory-item" type="button" aria-current={actual.selected_document_id===document.id?'page':undefined} title={document.name} onClick={()=>void select(document.id)} disabled={state.loading}>
  <span>{document.name}</span><small>{documentKindLabels[document.document_kind]} · V{document.content_version}{document.confirmed_revision_id===document.current_revision_id?' · 已确认':' · 未确认'}{document.source_status==='UPDATED'?' · 来源已有更新':document.source_status==='UNAVAILABLE'?' · 来源不可用':''}</small>
 </button></li>);
 return <section className="document-directory" aria-label="文档导航">
  <div className="document-directory-tabs" role="group" aria-label="导航视图"><button className="ui-button" aria-pressed={tab==='DOCUMENTS'} onClick={()=>setTab('DOCUMENTS')}>文档</button><button className="ui-button" aria-pressed={tab==='OUTLINE'} onClick={()=>setTab('OUTLINE')}>大纲</button></div>
  <NewDocumentButton owner={owner}/>
  {error&&<p role="alert" className="inline-error">{error}</p>}
  {tab==='OUTLINE'?actual.current===null?<p>请先选择文档。</p>:<OwnedDocumentOutline owner={owner.documents} heading={false}/>:<>
   {actual.documents.length===0&&<p>尚无文档</p>}<ul>{rows(actual.documents.filter(document=>document.archived_at===null))}</ul>
   {actual.documents.some(document=>document.archived_at!==null)&&<details><summary>已归档文档</summary><ul>{rows(actual.documents.filter(document=>document.archived_at!==null))}</ul></details>}
  </>}
 </section>;
}

export function NewDocumentButton({owner}:{owner:RequirementDetailOwner}){
 const flow=owner.regions!.directory;useSyncExternalStore(flow.subscribe,flow.getSnapshot);
 const [creating,setCreating]=useState(false);
 return <><button className="ui-button" type="button" disabled={!flow.allowed} onClick={()=>setCreating(true)}>新建文档</button>{creating&&<CreateDocumentDialog owner={owner} close={()=>setCreating(false)}/>}</>;
}

export function DocumentMetadataBar({owner}:{owner:RequirementDetailOwner}){
 const detail=useSyncExternalStore(owner.subscribe,owner.getSnapshot).detail,flow=owner.regions!.directory,state=useSyncExternalStore(flow.subscribe,flow.getSnapshot);
 const [renaming,setRenaming]=useState<DocumentSummary|null>(null),[name,setName]=useState(''),[archive,setArchive]=useState<DocumentSummary|null>(null),[error,setError]=useState<string|null>(null),pending=useRef(false);
 const current=detail?.current;
 const execute=async(work:()=>Promise<boolean>)=>{if(pending.current)return;pending.current=true;setError(null);try{if(await work()){setRenaming(null);setArchive(null);}}catch(error){setError(error instanceof Error?error.message:'文档操作暂时无法完成');}finally{pending.current=false;}};
 return <section className="document-metadata-bar" aria-label="当前阅读文档">
  {current?<><strong>{current.name}</strong><span>{documentKindLabels[current.document_kind]} · V{current.content_version} · {current.confirmed_revision_id===current.current_revision_id?'已确认':'未确认'}{current.archived_at!==null?' · 已归档':''}</span>
   {current.archived_at===null?<><button className="ui-button" disabled={!flow.allowed} onClick={()=>{setRenaming(current);setName(current.name);}}>改名</button><button className="ui-button" disabled={!flow.allowed||current.confirmed_revision_id===current.current_revision_id} onClick={()=>void execute(()=>flow.metadata(current,{type:'CONFIRM',expected_content_version:current.content_version,revision_id:current.current_revision_id}))}>确认当前版本</button><button className="ui-button" disabled={!flow.allowed} onClick={()=>setArchive(current)}>归档</button></>:<button className="ui-button" disabled={!flow.allowed} onClick={()=>void execute(()=>flow.metadata(current,{type:'RESTORE'}))}>恢复文档</button>}
  </>:<p>尚未选择文档</p>}
  {detail?.activity.kind==='MANUAL'&&<p role="status">正在编辑：{detail.activity.target.name} · V{detail.activity.target.content_version}</p>}
  {renaming&&<form onSubmit={event=>{event.preventDefault();void execute(()=>flow.metadata(renaming,{type:'RENAME',name}));}} onKeyDown={event=>{if(event.key==='Escape'&&flow.allowed){event.preventDefault();setRenaming(null);}}}><label>新名称<input className="ui-input" value={name} disabled={!flow.allowed} onChange={event=>setName(event.currentTarget.value)}/></label><button className="ui-button" disabled={!flow.allowed}>保存名称</button><button className="ui-button" type="button" disabled={!flow.allowed} onClick={()=>setRenaming(null)}>取消</button></form>}
  {(error||state.error)&&<p className="inline-error" role="alert">{error??state.error}</p>}
  {state.phase==='UNKNOWN'&&state.intent?.kind==='METADATA'&&<button className="ui-button" onClick={()=>void execute(()=>flow.retryUnknown())}>核实文档操作</button>}
  {state.phase==='CONFIRMED'&&<button className="ui-button" onClick={()=>void execute(()=>flow.finish())}>重新读取已保存结果</button>}
  <Confirmation open={archive!==null} title="归档文档？" description={`“${archive?.name??''}”归档后可继续阅读和查看历史。`} busy={state.phase==='SUBMITTING'} confirmDisabled={!flow.allowed&&!['UNKNOWN','CONFIRMED'].includes(state.phase)} error={error??state.error} confirmLabel={state.phase==='UNKNOWN'?'核实原操作':state.phase==='CONFIRMED'?'重新读取结果':'归档'} cancel={()=>{if(state.phase!=='SUBMITTING')setArchive(null);}} confirm={()=>{if(archive)void execute(()=>state.phase==='UNKNOWN'?flow.retryUnknown():state.phase==='CONFIRMED'?flow.finish():flow.metadata(archive,{type:'ARCHIVE'}));}}/>
 </section>;
}
