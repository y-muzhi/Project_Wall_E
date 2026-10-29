import {createContext,useContext,useId,useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import {createPortal} from 'react-dom';
import type {RequirementDetailOwner} from './detail-owner.ts';
import type {DocumentSummary} from '../api/models.ts';
import {documentKinds} from '../api/models.ts';
import {documentKindLabels,documentStructureRefs} from './catalog.ts';
import {OwnedDocumentOutline} from './document-controls.tsx';
import {SingleSelect} from '../shared/single-select.tsx';
import {Confirmation} from '../shared/confirmation.tsx';
import {activeModal,registerModal,trapModalTab} from '../shared/modal.ts';
import {Icon} from '../shared/icon.tsx';
import {ordinaryInput} from '../shared/text.ts';
import {useMotionPresence} from '../shared/motion-react.ts';

const DocumentCreationContext=createContext<(()=>void)|null>(null);
export function DocumentCreationProvider({owner,children}:{owner:RequirementDetailOwner;children:import('react').ReactNode}){
 const [state,setState]=useState({open:false,identity:0}),present=useMotionPresence(state.open);
 return <DocumentCreationContext.Provider value={()=>setState(previous=>previous.open?previous:{open:true,identity:previous.identity+1})}>{children}{present&&<CreateDocumentDialog key={state.identity} owner={owner} open={state.open} close={()=>setState(previous=>({...previous,open:false}))}/>}</DocumentCreationContext.Provider>;
}
function CreateDocumentDialog({owner,open,close}:{owner:RequirementDetailOwner;open:boolean;close():void}){
 const flow=owner.regions!.directory,state=useSyncExternalStore(flow.subscribe,flow.getSnapshot);
 const [name,setName]=useState(''),[kind,setKind]=useState<typeof documentKinds[number]>('REQUIREMENT_BRIEF'),[framework,setFramework]=useState(false),[error,setError]=useState<string|null>(null);
 const [invalidName,setInvalidName]=useState(false);
 const [discard,setDiscard]=useState(false);
 const dialog=useRef<HTMLDialogElement>(null),composing=useRef(false),pending=useRef(false);
 const id=useId();
 const locked=!open||['SUBMITTING','UNKNOWN','CONFIRMED'].includes(state.phase);
 const requestClose=()=>{if(locked)return;if(name.length>0||kind!=='REQUIREMENT_BRIEF'||framework)setDiscard(true);else close();};
 useLayoutEffect(()=>{if(!open)return;const element=dialog.current!,previous=document.activeElement,surface=document.querySelector<HTMLElement>(`.detail-product[data-requirement-id="${owner.getSnapshot().detail!.requirement.id}"]`);element.showModal();const release=registerModal(element);element.querySelector('input')?.focus();return()=>{element.close();release();requestAnimationFrame(()=>{if(!surface?.isConnected||activeModal())return;const focused=globalThis.document.activeElement;if(focused instanceof HTMLElement&&focused!==globalThis.document.body&&focused!==previous&&!element.contains(focused)&&!focused.closest('[inert],[hidden]'))return;if(previous instanceof HTMLElement&&previous.isConnected&&!previous.closest('[inert],[hidden]'))previous.focus();else surface.querySelector<HTMLElement>('.document-metadata-bar > strong')?.focus({preventScroll:true});});};},[open]);
 const submit=async()=>{if(pending.current||composing.current)return;
  if(!locked){try{ordinaryInput(name,'文档名称',1,80,false);setInvalidName(false);}catch(error){setError(error instanceof Error?error.message:'请填写文档名称');setInvalidName(true);dialog.current?.querySelector('input')?.focus();return;}}
  pending.current=true;setError(null);try{
  const done=state.phase==='UNKNOWN'?await flow.retryUnknown():state.phase==='CONFIRMED'?await flow.finish():await flow.create({name,document_kind:kind,template_ref:framework?documentStructureRefs[kind]!:null});if(done){owner.toasts.push('success','文档已创建');close();}
 }catch(error){setError(error instanceof Error?error.message:'文档暂时无法创建');}finally{pending.current=false;}};
 return <>{createPortal(<dialog ref={dialog} className="create-drawer" tabIndex={-1} inert={!open} aria-hidden={!open} aria-label="新建文档" onKeyDown={trapModalTab} onCancel={event=>{event.preventDefault();requestClose();}} onCompositionStart={()=>{composing.current=true;}} onCompositionEnd={()=>{composing.current=false;}}>
  <form noValidate onSubmit={event=>{event.preventDefault();void submit();}}><header><h2>新建文档</h2><button type="button" className="ui-button icon-button" aria-label="关闭新建文档" disabled={locked} onClick={requestClose}><Icon name="close"/></button></header>
   <div className="create-fields"><div><label htmlFor={id+'-name'}>文档名称</label><input id={id+'-name'} className="ui-input" aria-required="true" aria-invalid={invalidName} aria-describedby={id+'-name-help'+(invalidName?' '+id+'-error':'')} autoComplete="off" value={name} disabled={locked} onChange={event=>{setName(event.currentTarget.value);setInvalidName(false);setError(null);}}/><small id={id+'-name-help'}>1～80 个字符</small></div>
    <div><label htmlFor={id+'-kind'}>文档类型</label><SingleSelect id={id+'-kind'} label="文档类型" value={kind} disabled={locked} options={documentKinds.map(value=>({value,label:documentKindLabels[value]}))} change={value=>setKind(value as typeof kind)}/></div>
    <div><label htmlFor={id+'-content'}>初始内容</label><SingleSelect id={id+'-content'} label="初始内容" value={framework?'FRAMEWORK':'EMPTY'} disabled={locked} options={[{value:'EMPTY',label:'空白文档'},{value:'FRAMEWORK',label:'固定框架'}]} change={value=>setFramework(value==='FRAMEWORK')}/></div>
    <p className="field-help">{framework?'预置所选类型的章节，创建后可继续填写正文。':'从空白正文开始，创建后可直接编辑。'}此操作不调用 AI。</p>{(error||state.error)&&<p id={id+'-error'} role="alert" className="inline-error">{error??state.error}</p>}
   </div><footer><button type="button" className="ui-button" disabled={locked} onClick={requestClose}>取消</button><button className="ui-button primary" type="submit" disabled={state.phase==='SUBMITTING'}>{state.phase==='UNKNOWN'?'核实创建结果':state.phase==='CONFIRMED'?'重新读取已创建文档':'创建文档'}</button></footer>
  </form>
 </dialog>,document.body)}<Confirmation open={open&&discard} title="放弃新建文档？" description="已填写的名称和内容设置将被清空。" busy={false} dangerous confirmLabel="放弃创建" cancelLabel="继续填写" cancel={()=>setDiscard(false)} confirm={close}/></>;
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
  {error&&<p role="alert" className="inline-error">{error}</p>}
  {tab==='OUTLINE'?actual.current===null?<p>请先选择文档。</p>:<OwnedDocumentOutline owner={owner.documents} heading={false}/>:<>
   {actual.documents.length===0&&<p>尚无文档</p>}<ul>{rows(actual.documents.filter(document=>document.archived_at===null))}</ul>
   {actual.documents.some(document=>document.archived_at!==null)&&<details><summary>已归档文档</summary><ul>{rows(actual.documents.filter(document=>document.archived_at!==null))}</ul></details>}
  </>}
 </section>;
}

export function NewDocumentButton({owner,label='新建文档',iconOnly=false}:{owner:RequirementDetailOwner;label?:string;iconOnly?:boolean}){
 const flow=owner.regions!.directory;useSyncExternalStore(flow.subscribe,flow.getSnapshot);
 const editing=useSyncExternalStore(owner.documents.subscribe,owner.documents.getSnapshot).mode==='MANUAL';
 const create=useContext(DocumentCreationContext);
 if(editing)return null;
 return <button className={'ui-button'+(iconOnly?' icon-button document-create-trigger':'')} type="button" aria-label={label} title={iconOnly?label:undefined} disabled={!flow.allowed||create===null} onClick={()=>create?.()}>{iconOnly?<Icon name="plus"/>:label}</button>;
}

export function DocumentMetadataBar({owner,navigation}:{owner:RequirementDetailOwner;navigation?:import('react').ReactNode}){
 const detail=useSyncExternalStore(owner.subscribe,owner.getSnapshot).detail,flow=owner.regions!.directory,state=useSyncExternalStore(flow.subscribe,flow.getSnapshot);
 const editing=useSyncExternalStore(owner.documents.subscribe,owner.documents.getSnapshot).mode==='MANUAL';
 const [renaming,setRenaming]=useState<DocumentSummary|null>(null),[name,setName]=useState(''),[archive,setArchive]=useState<DocumentSummary|null>(null),[error,setError]=useState<string|null>(null),pending=useRef(false);
 const renameInput=useRef<HTMLInputElement>(null),composing=useRef(false);
 useLayoutEffect(()=>{if(!renaming)return;const previous=globalThis.document.activeElement;renameInput.current?.focus();renameInput.current?.select();return()=>{if(previous instanceof HTMLElement&&previous.isConnected&&!previous.closest('[inert]'))previous.focus();};},[renaming]);
 const current=detail?.current;
 const execute=async(work:()=>Promise<boolean>,message?:string)=>{if(pending.current)return;pending.current=true;setError(null);try{if(await work()){setRenaming(null);setArchive(null);owner.toasts.push('success',message??'文档操作已保存');}}catch(error){setError(error instanceof Error?error.message:'文档操作暂时无法完成');}finally{pending.current=false;}};
 return <section className="document-metadata-bar" aria-label="当前阅读文档">
  {current?<strong tabIndex={-1}>{current.name}</strong>:detail?.documents.length?<p>尚未选择文档</p>:null}
  {(current||detail?.activity.kind==='MANUAL')&&<div className="document-metadata-row">
   {current&&<div className="document-metadata-summary">{navigation}<span>{documentKindLabels[current.document_kind]} · V{current.content_version} · {current.confirmed_revision_id===current.current_revision_id?'已确认':'未确认'}{current.archived_at!==null?' · 已归档':''}</span></div>}
   {detail?.activity.kind==='MANUAL'&&<p className="document-editing-status" role="status">正在进行人工编辑</p>}
   {current&&!editing&&<span className="document-metadata-actions">{current.archived_at===null?<><button className="ui-button" disabled={!flow.allowed} onClick={()=>{setRenaming(current);setName(current.name);}}>改名</button><button className="ui-button" disabled={!flow.allowed||current.confirmed_revision_id===current.current_revision_id} onClick={()=>void execute(()=>flow.metadata(current,{type:'CONFIRM',expected_content_version:current.content_version,revision_id:current.current_revision_id}),'当前版本已确认')}>确认当前版本</button><button className="ui-button" disabled={!flow.allowed} onClick={()=>setArchive(current)}>归档</button></>:<button className="ui-button" disabled={!flow.allowed} onClick={()=>void execute(()=>flow.metadata(current,{type:'RESTORE'}),'文档已恢复')}>恢复文档</button>}</span>}
  </div>}
  {renaming&&<form className="document-rename-form" onCompositionStart={()=>{composing.current=true;}} onCompositionEnd={()=>{composing.current=false;}} onSubmit={event=>{event.preventDefault();if(!composing.current)void execute(()=>flow.metadata(renaming,{type:'RENAME',name}),'文档名称已保存');}} onKeyDown={event=>{if(event.key==='Escape'&&!event.nativeEvent.isComposing&&flow.allowed){event.preventDefault();setRenaming(null);}}}><label>新名称<input ref={renameInput} className="ui-input" value={name} disabled={!flow.allowed} onChange={event=>setName(event.currentTarget.value)}/></label><button className="ui-button primary" disabled={!flow.allowed}>保存名称</button><button className="ui-button" type="button" disabled={!flow.allowed} onClick={()=>setRenaming(null)}>取消</button></form>}
  {(error||state.error)&&<p className="inline-error" role="alert">{error??state.error}</p>}
  {state.phase==='UNKNOWN'&&state.intent?.kind==='METADATA'&&<button className="ui-button" onClick={()=>void execute(()=>flow.retryUnknown())}>核实文档操作</button>}
  {state.phase==='CONFIRMED'&&<button className="ui-button" onClick={()=>void execute(()=>flow.finish())}>重新读取已保存结果</button>}
  <Confirmation open={archive!==null} title="归档文档？" description={`“${archive?.name??''}”归档后仍可阅读和查看历史，需要时可从文档导航的“已归档文档”中恢复。`} busy={state.phase==='SUBMITTING'} confirmDisabled={!flow.allowed&&!['UNKNOWN','CONFIRMED'].includes(state.phase)} error={error??state.error} confirmLabel={state.phase==='UNKNOWN'?'核实原操作':state.phase==='CONFIRMED'?'重新读取结果':'归档'} cancel={()=>{if(state.phase!=='SUBMITTING')setArchive(null);}} confirm={()=>{if(archive)void execute(()=>state.phase==='UNKNOWN'?flow.retryUnknown():state.phase==='CONFIRMED'?flow.finish():flow.metadata(archive,{type:'ARCHIVE'}),'文档已归档，可从文档导航中恢复');}}/>
 </section>;
}
