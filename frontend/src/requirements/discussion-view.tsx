import {useEffect,useRef,useState,useSyncExternalStore} from 'react';
import type {RequirementDetailOwner} from './detail-owner.ts';
import {SourceReference} from './source-reference.tsx';
import {SingleSelect} from '../shared/single-select.tsx';
import {Confirmation} from '../shared/confirmation.tsx';
import {phaseKinds} from '../api/models.ts';
import type {DiscussionState} from '../api/models.ts';
import {Icon} from '../shared/icon.tsx';
import {activeModal} from '../shared/modal.ts';
import {progressPresentation,topicRecords,phaseLabels,assessments,evidenceOrigins,evidenceStates,dispositionLabels} from './discussion-presentation.ts';
import type {ProgressTopic} from './discussion-presentation.ts';
import type {DiscussionCommand} from '../api/walle.ts';
import discovery from '../../../backend/resources/v9/guides/collaboration.discovery.v1.json' with {type:'json'};
import solution from '../../../backend/resources/v9/guides/collaboration.solution.v1.json' with {type:'json'};
import specification from '../../../backend/resources/v9/guides/collaboration.specification.v1.json' with {type:'json'};
import review from '../../../backend/resources/v9/guides/collaboration.review.v1.json' with {type:'json'};
const guides={DISCOVERY:discovery,SOLUTION:solution,SPECIFICATION:specification,REVIEW:review};
const natures={FACT:'事实',CONSTRAINT:'约束',PROPOSAL:'建议'};
type Evidence=DiscussionState['evidence'][number];
function EvidenceRecords({items,owner}:{items:readonly Evidence[];owner:RequirementDetailOwner}){
 const documents=owner.getSnapshot().detail!.documents;
 return <ul className="progress-records">{items.map(item=><li key={item.evidence_ref} data-state={item.state}>
  <div className="progress-record-meta"><span data-origin={item.origin}>{evidenceOrigins[item.origin]}</span>{!(item.origin==='AI_PROPOSAL'&&item.nature==='PROPOSAL')&&<span>{natures[item.nature]}</span>}<span>{evidenceStates[item.state]}</span></div>
  <p>{item.assertion}</p>
  <details className="progress-sources"><summary>查看来源 · {item.source_refs.length}</summary><ul>{item.source_refs.map(source=><li key={JSON.stringify(source)}><SourceReference read={signal=>owner.readSource(source,signal)} label={source.kind==='REVISION'?`${documents.find(document=>document.id===source.document_id)?.name??'文档 #'+source.document_id} · 版本记录 #${source.revision_id}`:source.kind==='MESSAGE'?`消息 #${source.message_id}`:source.kind==='CARD_ANSWER'?`正式回答 #${source.message_id} · ${source.card_key}`:source.kind==='RUN_RESULT'?`运行 #${source.guide_run_id} · 分析结果`:`运行 #${source.guide_run_id} · 已保存材料`}/></li>)}</ul></details>
 </li>)}</ul>;
}
function Dispositions({items}:{items:DiscussionState['dispositions']}){
 return <ul className="progress-decisions">{items.map((item,index)=><li key={`${item.message_id}:${index}`}><span>{dispositionLabels[item.kind]}</span><p>{item.summary}</p></li>)}</ul>;
}
function TopicDetails({topic,discussion,owner,locked,focus}:{topic:ProgressTopic;discussion:DiscussionState;owner:RequirementDetailOwner;locked:boolean;focus():void}){
 const current=topic.topic_ref===discussion.focus_topic_ref,records=topicRecords(discussion,topic);
 return <details className="progress-topic" open={current} data-current={current}>
  <summary><span className="progress-chevron"><Icon name="right"/></span><span className="progress-topic-heading"><span className="progress-topic-title">{current&&<span className="progress-current-label">当前</span>}{topic.title}</span><span className="progress-topic-meta">{topic.unresolved_impacts.length>0&&<span>{topic.unresolved_impacts.length} 项待明确</span>}{records.current.length>0&&<span>{records.current.length} 条记录</span>}</span></span><span className="progress-assessment" data-assessment={topic.assessment}>{assessments[topic.assessment]}</span></summary>
  <div className="progress-topic-body">
   {!current&&<p className="progress-topic-purpose">{topic.purpose}</p>}
   {topic.unresolved_impacts.length>0&&<section className="progress-unresolved"><h4>待明确的问题</h4><ul>{topic.unresolved_impacts.map((impact,index)=><li key={index}>{impact}</li>)}</ul></section>}
   <section className="progress-record-section"><h4>已记录内容 <small>AI整理</small></h4>{records.current.length?<EvidenceRecords items={records.current} owner={owner}/>:<p className="progress-empty">暂无已保存的内容依据。</p>}</section>
   <section className="progress-outcomes"><h4>需要形成的成果</h4><ul>{topic.expected_outcomes.map(outcome=><li key={outcome.outcome_ref}><strong>{outcome.text}</strong><p>{outcome.criterion}</p></li>)}</ul></section>
   {records.dispositions.length>0&&<section><h4>用户处置</h4><Dispositions items={records.dispositions}/></section>}
   {topic.dependencies.length>0&&<section className="progress-dependencies"><h4>关联主题</h4><ul>{topic.dependencies.map(ref=><li key={ref}>{discussion.topics.find(item=>item.topic_ref===ref)?.title??'暂不可读取的主题'}</li>)}</ul></section>}
   {records.history.length>0&&<details className="progress-history"><summary>已更新的记录 · {records.history.length}</summary><EvidenceRecords items={records.history} owner={owner}/></details>}
   {!current&&<button type="button" className="ui-button" disabled={locked} onClick={focus}>讨论此主题</button>}
  </div>
 </details>;
}
export function DiscussionProgress({owner,blocked,active,discuss}:{owner:RequirementDetailOwner;blocked:boolean;active:boolean;discuss():void}){
 const flow=owner.regions!.discussion,state=useSyncExternalStore(flow.subscribe,flow.getSnapshot),actual=state.detail,discussion=state.discussion;
 const panel=useRef<HTMLElement>(null),focusCard=useRef<HTMLElement>(null);
 const [target,setTarget]=useState<number|null|undefined>(),[references,setReferences]=useState<readonly number[]|null>(null);
 const [phase,setPhase]=useState<typeof phaseKinds[number]|null>(null),[closure,setClosure]=useState(''),[confirm,setConfirm]=useState(false),[error,setError]=useState<string|null>(null);
 const [subject,setSubject]=useState<string|null>(null),[decision,setDecision]=useState<'DEFER'|'NOT_APPLICABLE'|'DECLINE_DRAFT'>('DEFER'),[description,setDescription]=useState('');
 const locked=blocked||!flow.allowed,selectedTarget=target===undefined?discussion?.binding.target_document_id??null:target;
 const selectedSources=references??discussion?.binding.source_refs.filter(ref=>ref.kind==='REVISION').map(ref=>Number(ref.document_id))??[];
 const send=async(command:DiscussionCommand)=>{setError(null);try{const done=await flow.submit(command);if(done){setTarget(undefined);setReferences(null);setSubject(null);setDescription('');setPhase(null);setClosure('');setConfirm(false);owner.toasts.push('success',command.type==='SET_FOCUS'?'当前讨论主题已更新':command.type==='SET_BINDING'?'讨论目标与来源已保存':command.type==='CHANGE_PHASE'?'讨论阶段已切换':'用户处置已保存');if(command.type==='SET_FOCUS')requestAnimationFrame(()=>{if(!panel.current||panel.current.closest('[hidden],[inert]')||activeModal())return;focusCard.current?.focus({preventScroll:true});panel.current.scrollTop=0;});}}catch(error){setError(error instanceof Error?error.message:'讨论调整失败');}};
 const unresolved=discussion?.topics.filter(topic=>topic.phase_ref===discussion.phase.phase_ref&&topic.assessment!=='SUPPORTED').map(topic=>topic.topic_ref)??[];
 const view=discussion?progressPresentation(discussion,guides[discussion.phase.kind].mainlines):null;
 const stale=discussion!==null&&state.version!==actual.requirement.discussion_version;
 // Observe acknowledged versions only in the visible progress tab; this is not a poller or
 // model request. A failed read stays visible until the user explicitly retries.
 useEffect(()=>{if(!active)return;const current=flow.getSnapshot();if(!current.discussion||(current.version??-1)<actual.requirement.discussion_version)void flow.load();return()=>flow.pauseRead();},[active,actual.requirement.discussion_version,flow]);
 const reread=()=>void owner.refresh().then(()=>{if(panel.current&&!panel.current.closest('[hidden],[inert]')&&!flow.getSnapshot().loading)return flow.load();}).catch(()=>undefined);
 return <section ref={panel} className="discussion-progress" aria-label="大纲与进展">
   <header className="progress-panel-heading"><div><h2>大纲与进展</h2><span className="progress-phase-label">{phaseLabels[actual.discussion_summary.phase_kind]}</span></div><button type="button" className="ui-button" onClick={discuss}>返回对话</button></header>
   <div className="progress-body">
   {state.loading&&<p className="progress-notice" role="status">正在读取讨论进展…</p>}
   {discussion&&view&&<>
    {stale&&<p className="progress-notice" role="status">讨论已变化，以下为保留的进展。<button type="button" className="ui-button" disabled={state.loading} onClick={reread}>重新读取</button></p>}
    {view.focus?<section ref={focusCard} tabIndex={-1} className="progress-focus-card" aria-label="当前重点"><div><span className="progress-eyebrow">当前重点</span><span className="progress-assessment" data-assessment={view.focus.assessment}>{assessments[view.focus.assessment]}</span></div><h3>{view.focus.title}</h3><p>{view.focus.purpose}</p></section>:<p className="progress-empty">{view.topics.length?'尚未选定当前主题。可展开下方主题，选择“讨论此主题”。':'暂无讨论主题。讨论后可在这里查看已保存的主题、依据和待明确问题。'}</p>}
    {view.next&&<section className="progress-next-step" aria-label="下一步建议"><span className="progress-eyebrow">下一步建议</span><strong>{view.next.label}</strong><p>{view.next.reason}</p>{view.next.topic&&view.next.topic.topic_ref!==discussion.focus_topic_ref&&<p className="field-help">关联主题：{view.next.topic.title}</p>}{view.next.impacts.length>0&&<ul>{view.next.impacts.map((impact,index)=><li key={index}>{impact}</li>)}</ul>}</section>}
    <div className="progress-route-heading"><h3>讨论主线</h3><span>{view.topics.length} 个主题{view.reviewCount>0&&` · ${view.reviewCount} 个需复核`}</span></div>
    <ol className="progress-mainlines">{view.groups.map((mainline,index)=><li key={mainline.ref}><details className="progress-mainline" open={mainline.topics.some(topic=>topic.topic_ref===discussion.focus_topic_ref)}>
     <summary><span className="progress-mainline-number">{String(index+1).padStart(2,'0')}</span><strong>{mainline.title}</strong><span className="progress-mainline-count">{mainline.topics.length?`${mainline.topics.length} 个主题`:'尚无主题'}</span><span className="progress-chevron"><Icon name="right"/></span></summary>
     <div className="progress-mainline-body"><p className="progress-mainline-purpose">{mainline.purpose}</p>{mainline.topics.length?mainline.topics.map(topic=><TopicDetails key={topic.topic_ref} topic={topic} discussion={discussion} owner={owner} locked={locked} focus={()=>void send({type:'SET_FOCUS',topic_ref:topic.topic_ref})}/>):<p className="progress-empty">本主线尚未形成讨论主题。</p>}</div>
    </details></li>)}</ol>
    {view.phaseDispositions.length>0&&<section className="progress-phase-decisions"><h3>本阶段用户处置</h3><Dispositions items={view.phaseDispositions}/></section>}
    <details className="progress-settings"><summary><Icon name="settings"/><strong>讨论设置</strong><span>目标、阶段与用户处置</span></summary><div className="progress-settings-body">
    <details className="progress-setting-section"><summary>讨论目标与来源</summary><p className="field-help">指定后续讨论的工作目标与参考文档，不生成或修改正文。</p><label>工作目标<SingleSelect label="工作目标" disabled={locked} value={selectedTarget===null?'NONE':String(selectedTarget)} options={[{value:'NONE',label:'不绑定文档'},...actual.documents.map(document=>({value:String(document.id),label:document.name+(document.archived_at===null?'':'（已归档）')}))]} change={value=>setTarget(value==='NONE'?null:Number(value))}/></label>
     <fieldset disabled={locked}><legend>参考文档</legend>{actual.documents.map(document=><label key={document.id}><input type="checkbox" checked={selectedSources.includes(document.id)} onChange={event=>setReferences(event.currentTarget.checked?[...selectedSources,document.id]:selectedSources.filter(id=>id!==document.id))}/>{document.name} · v{document.content_version}</label>)}</fieldset>
     <button type="button" className="ui-button" disabled={locked} onClick={()=>void send({type:'SET_BINDING',target_document_id:selectedTarget,scope:selectedTarget===discussion.binding.target_document_id?discussion.binding.scope:selectedTarget===null?null:{scope_type:'DOCUMENT',scope_ref:null},source_refs:[...discussion.binding.source_refs.filter(ref=>ref.kind!=='REVISION'),...selectedSources.map(identity=>{const document=actual.documents.find(item=>item.id===identity)!;return {kind:'REVISION',document_id:identity,revision_id:document.current_revision_id,block_ids:null};})]})}>保存讨论绑定</button>
    </details>
    <details className="progress-setting-section"><summary>阶段与用户处置</summary><p className="field-help">阶段切换和用户处置独立于需求业务状态，保留原有主题与历史记录。</p><label>下一阶段<SingleSelect label="下一阶段" disabled={locked} value={phase??discussion.phase.kind} options={phaseKinds.map(value=>({value,label:phaseLabels[value]}))} change={value=>setPhase(value as typeof phaseKinds[number])}/></label>
     <label>收束说明<textarea className="ui-input" disabled={locked} value={closure} onChange={event=>setClosure(event.currentTarget.value)}/></label><p>本阶段尚待讨论或复核的主题：{unresolved.length?discussion.topics.filter(topic=>unresolved.includes(topic.topic_ref)).map(topic=>topic.title).join('、'):'无'}。切换时保留这些未决项。</p>
     <button type="button" className="ui-button" disabled={locked||phase===null||phase===discussion.phase.kind} onClick={()=>setConfirm(true)}>切换阶段</button>
     <label>处置范围<SingleSelect label="处置范围" disabled={locked} value={subject??discussion.phase.phase_ref} options={[{value:discussion.phase.phase_ref,label:'当前阶段'},...discussion.topics.filter(topic=>topic.phase_ref===discussion.phase.phase_ref).map(topic=>({value:topic.topic_ref,label:topic.title}))]} change={setSubject}/></label>
     <label>用户决定<SingleSelect label="用户决定" disabled={locked} value={decision} options={[{value:'DEFER',label:'暂缓'},{value:'NOT_APPLICABLE',label:'不适用'},{value:'DECLINE_DRAFT',label:'暂不出稿'}]} change={value=>setDecision(value as typeof decision)}/></label>
     <label>处置说明<textarea className="ui-input" disabled={locked} value={description} onChange={event=>setDescription(event.currentTarget.value)}/></label><button type="button" className="ui-button" disabled={locked||!description.trim()} onClick={()=>void send({type:'SET_DISPOSITION',subject_ref:subject??discussion.phase.phase_ref,decision,description})}>保存用户处置</button>
    </details>
    </div></details>
   </>}
   {(state.error||error)&&<p className="inline-error progress-notice" role="alert">{error??state.error}<button type="button" className="ui-button" disabled={state.loading||state.phase==='SUBMITTING'} onClick={reread}>重新读取进展</button></p>}
   {state.phase==='UNKNOWN'&&<button type="button" className="ui-button" disabled={blocked} onClick={()=>void flow.retryUnknown()}>核实原请求</button>}
   {state.phase==='CONFIRMED'&&<button type="button" className="ui-button" disabled={blocked||state.loading} onClick={()=>void flow.finish()}>读取保存结果</button>}
   {!discussion&&!state.loading&&<button type="button" className="ui-button" onClick={()=>void flow.load()}>读取讨论进展</button>}
   </div>
  <Confirmation open={confirm} title="切换讨论阶段" description="当前主题和未决项将保留在历史中。此操作保存用户决定，不生成文档。" busy={state.phase==='SUBMITTING'} confirmDisabled={locked||phase===null} error={state.error??error} confirm={()=>{if(phase)void send({type:'CHANGE_PHASE',phase_kind:phase,closure_message:closure.trim()?closure:null,unresolved_refs:unresolved});}} cancel={()=>{if(state.phase!=='SUBMITTING')setConfirm(false);}}/>
 </section>;
}
