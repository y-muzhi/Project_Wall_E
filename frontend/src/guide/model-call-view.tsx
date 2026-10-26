import {createContext,useContext,useEffect,useLayoutEffect,useMemo,useRef,useState,useSyncExternalStore} from 'react';
import type {ReactNode} from 'react';
import type {GuideRun} from '../api/models.ts';
import type {ModelCallDetail} from '../api/model-calls.ts';
import {ModelCallReader,tokenTotal,usageWarning} from './model-call-reader.ts';
import type {ModelCallApi,ModelCallCache} from './model-call-reader.ts';
import {localTime} from '../shared/time.ts';
import {Icon} from '../shared/icon.tsx';
import {operationNames} from './operation-labels.ts';
import {SingleSelect} from '../shared/single-select.tsx';
import {useMotionPresence} from '../shared/motion-react.ts';
import {motionTiming} from '../shared/motion.ts';

const runNames={RUNNING:'运行中',WAITING_USER:'等待回复',COMPLETED:'已完成',FAILED:'失败',CANCELLED:'已取消'};
const callNames={RUNNING:'调用中',SUCCEEDED:'模型已返回',FAILED:'调用失败',CANCELLED:'已取消'};
const number=(value:number|null)=>value===null?'未记录':value.toLocaleString('zh-CN');
const elapsed=(value:number|null)=>value===null?'未记录':`${(value/1000).toLocaleString('zh-CN',{maximumFractionDigits:2})} 秒`;
type Selection=Readonly<{run:number;call:number}>;
type Surface=Readonly<{reader:ModelCallReader;active:boolean;current:GuideRun|null;open(selection:Selection,button:HTMLButtonElement):void}>;
const CallsContext=createContext<Surface|null>(null);

export function ModelCallsProvider({api,requirementId,active,current=null,children,cache}:Readonly<{api:ModelCallApi;requirementId:number;active:boolean;current?:GuideRun|null;children:ReactNode;cache?:ModelCallCache|undefined}>){
 const reader=useMemo(()=>new ModelCallReader(api,requirementId,cache),[api,requirementId,cache]);
 const [selection,setSelection]=useState<Selection|null>(null),returnFocus=useRef<HTMLButtonElement|null>(null);
 const present=useMotionPresence(selection!==null),lastSelection=useRef(selection);if(selection)lastSelection.current=selection;const shown=selection??lastSelection.current;
 useEffect(()=>()=>reader.dispose(),[reader]);useLayoutEffect(()=>reader.setActive(active),[reader,active]);
 const surface=useMemo<Surface>(()=>({reader,active,current,open:(next,button)=>{returnFocus.current=button;setSelection(next);void reader.load(next.run,'open',true);}}),[reader,active,current]);
 const close=()=>{setSelection(null);requestAnimationFrame(()=>returnFocus.current?.isConnected&&returnFocus.current.focus({preventScroll:true}));};
 return <CallsContext.Provider value={surface}><div className="model-calls-surface"><div className="model-calls-underlay" inert={selection!==null} aria-hidden={selection!==null}>{children}</div>
  {present&&shown&&<ModelCallDrawer key={`${shown.run}:${shown.call}`} open={selection!==null} surface={selection?surface:{...surface,active:false}} selection={shown} select={call=>{if(selection)setSelection({...selection,call});}} close={close}/>}</div></CallsContext.Provider>;
}

export function RequestCallRecord({runId,messageId=null}:Readonly<{runId:number;messageId?:number|null}>){
 const surface=useContext(CallsContext);if(!surface)return null;
 return <LoadedRequestRecord surface={surface} runId={runId} messageId={messageId}/>;
}
function useCallList(surface:Surface,run:number){
 const state=useSyncExternalStore(surface.reader.subscribe,()=>surface.reader.get(run));
 const version=surface.current?.id===run?surface.current.updated_at:'initial';
 useEffect(()=>{if(surface.active)void surface.reader.load(run,version);},[surface.reader,surface.active,run,version,state.loading]);
 return state;
}
function LoadedRequestRecord({surface,runId,messageId}:Readonly<{surface:Surface;runId:number;messageId:number|null}>){
 const state=useCallList(surface,runId),data=state.data;
 const calls=data?.items.filter(call=>messageId===null||call.user_message_id===messageId)??[];
 const last=calls.at(-1),unknown=data?.items.some(call=>call.user_message_id===null);
 return <section className="model-request-record" aria-label={`请求记录 · 运行 ${runId}`} aria-busy={state.loading}>
  <div className="model-request-heading"><strong>{data?`${operationNames[data.operation]} · ${runNames[data.status]}`:'请求记录'}</strong>{last&&<><time dateTime={last.started_at}>{localTime(last.started_at)}</time><span className="model-name" title={last.model_name}>{last.model_name}</span><span>{callNames[last.call_status]}</span></>}
   {calls.length>0&&<button className="model-context-trigger" type="button" onClick={event=>surface.open({run:runId,call:last!.id},event.currentTarget)}><Icon name="panel"/>查看上下文</button>}
   {!calls.length&&unknown&&<button className="model-context-trigger" type="button" onClick={event=>surface.open({run:runId,call:data!.items.at(-1)!.id},event.currentTarget)}>查看运行上下文</button>}
  </div>
  {calls.length>0?<><div className="model-token-line"><span>输入 <b>{number(tokenTotal(calls,'input_tokens'))}</b></span><span>输出 <b>{number(tokenTotal(calls,'output_tokens'))}</b></span><span>合计 <b>{number(tokenTotal(calls,'total_tokens'))}</b></span><span title="缓存命中属于输入的一部分，不额外计入合计">缓存命中 <b>{number(tokenTotal(calls,'cached_tokens'))}</b></span><span>耗时 {elapsed(tokenTotal(calls,'duration_ms'))}</span></div>
   {calls.length>1&&<details className="model-call-attempts"><summary>{calls.length} 次调用／尝试 · 查看逐次用量</summary>{calls.map(call=><div key={call.id}><span>调用 {call.call_no} · 尝试 {call.attempt_no} · {callNames[call.call_status]}</span><span>输入 {number(call.input_tokens)} · 输出 {number(call.output_tokens)} · 合计 {number(call.total_tokens)} · 缓存 {number(call.cached_tokens)} · {elapsed(call.duration_ms)}</span><button className="ui-button" type="button" onClick={event=>surface.open({run:runId,call:call.id},event.currentTarget)}>上下文</button></div>)}</details>}
  </>:<p className="model-no-call">{!data?state.loading?'正在读取调用记录…':'调用记录尚未读取':data.program_processed?'程序已处理，未调用模型':data.status==='RUNNING'?'正在准备请求，模型用量尚未返回':unknown?'旧调用未记录关联消息，可在运行记录中查看':data.status==='CANCELLED'?'请求已取消，未记录模型调用':data.status==='FAILED'?'运行失败，未记录模型调用':'未记录与此消息关联的模型调用'}</p>}
  {calls.some(call=>usageWarning(call)!==null)&&<p className="inline-error" role="status">本次调用的供应方用量记录缺失或不一致，已保留原始数值。</p>}
  {calls.length>0&&messageId!==null&&unknown&&<p className="field-help">另有旧调用未记录输入消息身份；完整运行用量可在“文档记录 → 运行记录”查看。</p>}
  {state.error&&<p className="inline-error" role="status">{state.error} <button className="ui-button" type="button" disabled={!surface.active||state.loading} onClick={()=>void surface.reader.load(runId,'retry',true)}>重读</button></p>}
 </section>;
}

function CopyButton({content}:Readonly<{content:string}>){
 const [result,setResult]=useState('');
 return <span className="model-copy"><button className="ui-button" type="button" onClick={()=>{void Promise.resolve().then(()=>navigator.clipboard.writeText(content)).then(()=>setResult('已复制'),()=>setResult('复制失败，请选中文字复制'));}}>复制</button><span role="status">{result}</span></span>;
}
function json(value:string):unknown{try{return JSON.parse(value);}catch{return null;}}
function pretty(value:string){const parsed=json(value);return parsed===null?value:JSON.stringify(parsed,null,2);}
function ContextText({section,detail}:Readonly<{section:ModelCallDetail['sections'][number];detail:ModelCallDetail}>){
 const value=json(section.content);
 if(detail.context_strategy==='collaboration_context_v1'){
  if(value===null&&section.content==='null'||Array.isArray(value)&&value.length===0)return <p>未携带</p>;
  if(section.key==='documents'&&Array.isArray(value))return <div className="model-context-documents">{value.map((item,index)=>{
   const document=item as {name:string;document_id:number;content_version:number;roles:string[];blocks:{block_id:number;markdown_content:string}[]};
   return <article key={index}><h4>{document.name} · 文档 #{document.document_id} · V{document.content_version}</h4><p>{document.roles.map(role=>role==='TARGET'?'修改目标':'参考来源').join('、')} · 实际 {document.blocks.length} 个区块</p>{document.blocks.map((block,index)=><details key={index}><summary>区块 #{block.block_id}</summary><pre className="model-context-text">{block.markdown_content??JSON.stringify(block,null,2)}</pre></details>)}<details><summary>实际文档字段</summary><pre className="model-context-text">{JSON.stringify(item,null,2)}</pre></details></article>;
  })}</div>;
 }
 if(value&&typeof value==='object'&&!Array.isArray(value)){
  const part=value as Record<string,unknown>;
  if(section.key.endsWith(':template')&&typeof part.markdown_content==='string')return <pre className="model-context-text">{part.markdown_content}</pre>;
  if((section.key.endsWith(':current_document')||section.key.endsWith(':document_context'))&&Array.isArray(part.read_blocks)){
   const request=json(detail.raw_request_json??'') as {messages?:{role:string;content:string}[]}|null;
   const wire=json(request?.messages?.find(message=>message.role==='user')?.content??'') as {request_metadata?:{read_block_metadata?:{block_id:number;section_path?:string[]}[]}}|null;
   return <div className="model-context-blocks">{part.read_blocks.map((item,index)=>{if(!item||typeof item!=='object')return <pre className="model-context-text" key={index}>{JSON.stringify(item,null,2)}</pre>;const block=item as {block_id?:number;section_path?:string[];markdown_content?:string;plain_text?:string;metadata?:{block_id:number;section_path?:string[]}};
    const metadata=block.metadata??wire?.request_metadata?.read_block_metadata?.[index];const identity=metadata?.block_id??block.block_id;return <details key={index}><summary>{identity===undefined?`区块 ${index+1}`:`区块 #${identity}`} · {metadata?.section_path?.at(-1)??block.section_path?.at(-1)??block.plain_text?.slice(0,65)??'正文'}</summary><pre className="model-context-text">{block.markdown_content??JSON.stringify(item,null,2)}</pre><details><summary>实际发送的区块字段</summary><pre className="model-context-text">{JSON.stringify(item,null,2)}</pre></details></details>;})}</div>;
  }
 }
 if(section.key.endsWith(':history')&&Array.isArray(value))return <div className="model-context-history">{value.map((item,index)=>{if(!item||typeof item!=='object')return <pre className="model-context-text" key={index}>{JSON.stringify(item,null,2)}</pre>;const message=item as {role?:string;message_type?:string;content?:string};return <article key={index}><strong>{detail.included_history_ids[index]?`消息 #${detail.included_history_ids[index]}`:`历史 ${index+1}`} · {message.role==='USER'?'用户':message.role==='ASSISTANT'?'助手':message.role} · {message.message_type}</strong><pre className="model-context-text">{message.content??JSON.stringify(item,null,2)}</pre></article>;})}</div>;
 return <pre className="model-context-text">{pretty(section.content)}</pre>;
}
function ContextSection({section,detail,search}:Readonly<{section:ModelCallDetail['sections'][number];detail:ModelCallDetail;search:string}>){
 const [expanded,setExpanded]=useState(false),present=useMotionPresence(expanded,motionTiming.disclosure);
 const documentPart=section.key==='documents'||section.key.endsWith(':current_document')||section.key.endsWith(':document_context');
 const headings=useMemo(()=>{if(!documentPart)return null;const part=json(section.content) as {read_blocks?:{heading_level?:number|null;block_type?:string}[]}|null;const blocks=part?.read_blocks;if(!Array.isArray(blocks))return null;return blocks.filter(block=>block&&(block.block_type==='heading'||typeof block.heading_level==='number'&&block.heading_level>0)).length;},[documentPart,section.content]);
 const unit=documentPart?'个区块':section.key==='recent_history'||section.key.endsWith(':history')||section.key.endsWith(':recent_history')?'条历史':'项';
 const index=search?section.content.toLocaleLowerCase().indexOf(search.toLocaleLowerCase()):-1;
 return <details className="model-context-section" onToggle={event=>setExpanded(event.currentTarget.open)}><summary><strong>{section.title}</strong><span>{headings===null?'':`${headings} 个章节标题 · `}{section.item_count===null?'':`${section.item_count} ${unit} · `}{number(section.characters)} 字符</span>{index>=0&&<span className="model-search-excerpt">{section.content.slice(Math.max(0,index-70),index+search.length+100)}</span>}</summary>
  {present&&<div inert={!expanded} aria-hidden={!expanded}><div className="model-section-tools"><CopyButton content={section.content}/></div><ContextText section={section} detail={detail}/></div>}
 </details>;
}
function TokenDetails({detail}:Readonly<{detail:ModelCallDetail}>){
 const call=detail.call,preflight=detail.preflight,budget=preflight.budget;
 const names=detail.context_strategy==='collaboration_context_v1'?['系统规则与阶段指引','完整Wire输入','本轮输入（分项计数）','文档结构（分项计数）','文档内容（分项计数）','历史消息（分项计数）','需求与已确认内容（分项计数）','项目进展与当前主题（分项计数）']:['系统提示词与输出约束','上下文内容','本轮输入（分项计数）','来源信息（分项计数）','完整模板（分项计数）','历史消息（分项计数）'];
 return <section className="model-detail-section"><h3>Token 用量</h3><h4>实际用量（模型返回）</h4><dl className="model-property-grid"><dt>输入</dt><dd>{number(call.input_tokens)}</dd><dt>输出</dt><dd>{number(call.output_tokens)}</dd><dt>合计</dt><dd>{number(call.total_tokens)}</dd><dt>缓存命中</dt><dd>{number(call.cached_tokens)}</dd></dl><p className="field-help">单位：token。缓存命中量已计入输入用量，不重复计入合计。缺失数据标记为“未记录”。</p>
  <h4>请求预检</h4><dl className="model-property-grid"><dt>预检输入（含预留量）</dt><dd>{number(preflight.input_tokens)}</dd><dt>输入上限</dt><dd>{number(budget?.input_tokens??null)}</dd><dt>输出上限</dt><dd>{number(budget?.output_tokens??null)}</dd><dt>输入与输出总上限</dt><dd>{number(budget?.total_tokens??null)}</dd>{names.map((name,index)=><div className="model-property-pair" key={name}><dt>{name}</dt><dd>{number(preflight.counts[index]??null)}</dd></div>)}</dl><p className="field-help">预检计数用于发送前预算校验，不代表实际用量。本轮输入、来源、模板和历史消息的分项计数已包含在上下文内容中，不可重复累加。</p>
 </section>;
}
function ModelCallDrawer({surface,selection,open,select,close}:Readonly<{surface:Surface;selection:Selection;open:boolean;select(call:number):void;close():void}>){
 const list=useCallList(surface,selection.run),[detail,setDetail]=useState<ModelCallDetail|null>(null),[error,setError]=useState<string|null>(null),[retry,setRetry]=useState(0),[loading,setLoading]=useState(false),[search,setSearch]=useState(''),[rawOpen,setRawOpen]=useState(false),[formatted,setFormatted]=useState(true),closeButton=useRef<HTMLButtonElement|null>(null);
 const rawPresent=useMotionPresence(rawOpen,motionTiming.disclosure);
 useEffect(()=>{if(open)closeButton.current?.focus({preventScroll:true});},[open]);
 const callVersion=JSON.stringify(list.data?.items.find(call=>call.id===selection.call)??null);
 useEffect(()=>{if(!surface.active)return;const controller=new AbortController();setLoading(true);setError(null);
  void surface.reader.api.getModelCall(selection.call,controller.signal).then(result=>{if(controller.signal.aborted)return;const data=result.data;if(data.call.id!==selection.call||data.call.guide_run_id!==selection.run||data.requirement_id!==surface.reader.requirementId)throw Error('调用身份不一致');setDetail(data);},()=>{if(!controller.signal.aborted)setError('上下文读取失败，重试不会调用模型');}).catch(()=>{if(!controller.signal.aborted)setError('上下文身份不一致，请重新读取');}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
  return()=>controller.abort();
 },[surface.reader,surface.active,selection.run,selection.call,retry,callVersion]);
 const sections=useMemo(()=>detail?.sections.filter(section=>!search||section.title.toLocaleLowerCase().includes(search.toLocaleLowerCase())||section.content.toLocaleLowerCase().includes(search.toLocaleLowerCase()))??[],[detail,search]);
 const raw=detail?.raw_request_json??null,rawContent=useMemo(()=>raw===null?null:formatted?pretty(raw):raw,[raw,formatted]);
 return <section className="model-call-drawer" role="dialog" inert={!open} aria-hidden={!open} data-motion-open={open} aria-modal="false" aria-label="模型请求详情" onKeyDown={event=>{if(event.key==='Escape'){event.stopPropagation();close();}}}>
  <header className="model-drawer-heading"><div><strong>模型请求详情</strong><span>运行 #{selection.run} · 调用记录 #{selection.call}</span></div><button ref={closeButton} className="ui-button icon-button" type="button" aria-label="关闭请求详情，返回对话" onClick={close}><Icon name="close"/></button></header>
  <div className="model-drawer-body" aria-busy={loading}><div className="model-call-picker"><SingleSelect label="选择调用" value={String(selection.call)} disabled={!surface.active||!list.data} change={value=>select(Number(value))} options={(list.data?.items??[]).map(call=>({value:String(call.id),label:`调用 ${call.call_no} · 尝试 ${call.attempt_no} · ${localTime(call.started_at)} · ${callNames[call.call_status]}`}))}/></div>
   {loading&&<p role="status">正在读取保存的请求快照…</p>}{error&&<p role="alert" className="inline-error">{error} <button type="button" className="ui-button" disabled={!surface.active||loading} onClick={()=>setRetry(value=>value+1)}>重读详情</button></p>}
   {detail&&<><section className="model-detail-section"><h3>调用概览</h3><dl className="model-property-grid"><dt>操作</dt><dd>{operationNames[detail.operation]}</dd><dt>模型</dt><dd>{detail.call.model_name}</dd><dt>状态</dt><dd>{callNames[detail.call.call_status]}</dd><dt>开始</dt><dd>{localTime(detail.call.started_at)}</dd><dt>结束</dt><dd>{detail.call.ended_at?localTime(detail.call.ended_at):detail.call.call_status==='RUNNING'?'尚未结束':'未记录'}</dd><dt>耗时</dt><dd>{elapsed(detail.call.duration_ms)}</dd><dt>提示词版本</dt><dd>{detail.prompt_reference??'未记录'}</dd><dt>上下文版本</dt><dd>{detail.context_reference??'未记录'}</dd><dt>采用正文版本</dt><dd>{detail.call.document_version===null?'未记录':`v${detail.call.document_version}`}</dd><dt>结果处理</dt><dd>解析：{detail.call.parse_status==='NOT_STARTED'?'尚未开始':detail.call.parse_status==='SUCCEEDED'?'完成':'失败'} · 校验：{detail.call.validation_status==='NOT_STARTED'?'尚未开始':detail.call.validation_status==='SUCCEEDED'?'完成':'失败'}</dd></dl></section>
    <section className="model-detail-section"><h3>请求上下文</h3><p className="field-help">内容来源于本次请求快照，不受后续文档修改影响。</p><label className="model-context-search">搜索上下文<input className="ui-input" type="search" value={search} onChange={event=>setSearch(event.target.value)} placeholder="搜索文字、问题或区块编号"/></label>
     <p className="model-history-references">历史消息编号：{detail.included_history_ids.length?detail.included_history_ids.map(id=>`#${id}`).join('、'):detail.context_strategy==='collaboration_context_v1'?'未携带':'未记录'}</p>{detail.budget_removed_history_ids.length>0&&<p>预算裁剪的历史消息：{detail.budget_removed_history_ids.map(id=>`#${id}`).join('、')}</p>}
     {search&&<p role="status">匹配 {sections.length} 个上下文部分</p>}{sections.map(section=><ContextSection key={section.key} section={section} detail={detail} search={search}/>)}</section>
    {detail.selection_summary&&'selected_materials' in detail.selection_summary&&<details className="model-detail-section"><summary>材料选择与资源版本</summary><p>计数批次：{number(detail.selection_summary.count_attempts)} · 期望输入目标：{number(detail.selection_summary.soft_input_target)}</p><h4>已携带材料</h4><pre className="model-context-text">{JSON.stringify(detail.selection_summary.selected_materials,null,2)}</pre><h4>省略材料与原因</h4><pre className="model-context-text">{JSON.stringify(detail.selection_summary.omitted_materials,null,2)}</pre><h4>资源版本</h4><pre className="model-context-text">{JSON.stringify(detail.selection_summary.resource_refs,null,2)}</pre></details>}
    {usageWarning(detail.call)&&<p className="inline-error" role="status">{usageWarning(detail.call)}</p>}
    <TokenDetails detail={detail}/><details className="model-detail-section model-raw-request" onToggle={event=>setRawOpen(event.currentTarget.open)}><summary>原始请求</summary>{rawPresent&&<div inert={!rawOpen} aria-hidden={!rawOpen}>{rawContent===null?<p>此记录未保存可读取的请求对象。</p>:<><div className="model-section-tools"><label><input type="checkbox" checked={formatted} onChange={event=>setFormatted(event.target.checked)}/>格式化 JSON</label><CopyButton content={rawContent}/></div><pre className="model-context-text">{rawContent}</pre></>}</div>}</details>
   </>}
  </div>
 </section>;
}
