import {useState,useSyncExternalStore} from 'react';
import type {RequirementDetailOwner} from './detail-owner.ts';
import {SourceReference} from './source-reference.tsx';
import {SingleSelect} from '../shared/single-select.tsx';
import {Confirmation} from '../shared/confirmation.tsx';
import {phaseKinds} from '../api/models.ts';
import type {DiscussionCommand} from '../api/walle.ts';
import discovery from '../../../backend/resources/v9/guides/collaboration.discovery.v1.json' with {type:'json'};
import solution from '../../../backend/resources/v9/guides/collaboration.solution.v1.json' with {type:'json'};
import specification from '../../../backend/resources/v9/guides/collaboration.specification.v1.json' with {type:'json'};
import review from '../../../backend/resources/v9/guides/collaboration.review.v1.json' with {type:'json'};
const guides={DISCOVERY:discovery,SOLUTION:solution,SPECIFICATION:specification,REVIEW:review};
const phaseLabels={DISCOVERY:'需求探索',SOLUTION:'方案设计',SPECIFICATION:'规格整理',REVIEW:'检查与完善'};
const assessments={NOT_STARTED:'尚未开始',DISCUSSING:'讨论中',SUPPORTED:'已有依据',REVIEW_REQUIRED:'需要复核'};
export function DiscussionProgress({owner,blocked}:{owner:RequirementDetailOwner;blocked:boolean}){
 const flow=owner.regions!.discussion,state=useSyncExternalStore(flow.subscribe,flow.getSnapshot),actual=state.detail,discussion=state.discussion;
 const [target,setTarget]=useState<number|null|undefined>(),[references,setReferences]=useState<readonly number[]|null>(null);
 const [phase,setPhase]=useState<typeof phaseKinds[number]|null>(null),[closure,setClosure]=useState(''),[confirm,setConfirm]=useState(false),[error,setError]=useState<string|null>(null);
 const [subject,setSubject]=useState<string|null>(null),[decision,setDecision]=useState<'DEFER'|'NOT_APPLICABLE'|'DECLINE_DRAFT'>('DEFER'),[description,setDescription]=useState('');
 const locked=blocked||!flow.allowed,selectedTarget=target===undefined?discussion?.binding.target_document_id??null:target;
 const selectedSources=references??discussion?.binding.source_refs.filter(ref=>ref.kind==='REVISION').map(ref=>Number(ref.document_id))??[];
 const send=async(command:DiscussionCommand)=>{setError(null);try{const done=await flow.submit(command);if(done){setTarget(undefined);setReferences(null);setSubject(null);setDescription('');setPhase(null);setClosure('');setConfirm(false);}}catch(error){setError(error instanceof Error?error.message:'讨论调整失败');}};
 const unresolved=discussion?.topics.filter(topic=>topic.phase_ref===discussion.phase.phase_ref&&topic.assessment!=='SUPPORTED').map(topic=>topic.topic_ref)??[];
 return <section className="discussion-progress" aria-label="讨论进展">
  <div className="discussion-position"><strong>{phaseLabels[actual.discussion_summary.phase_kind]}</strong><span>{actual.discussion_summary.focus_title??'尚未选定主题'}</span></div>
  <details onToggle={event=>{if(event.currentTarget.open){if(!discussion||state.version!==actual.requirement.discussion_version)void flow.load();}else flow.pauseRead();}}>
   <summary>大纲与进展</summary>
   {state.loading&&<p role="status">正在读取讨论进展…</p>}
   {discussion&&<>
    {state.version!==actual.requirement.discussion_version&&<p role="status">讨论已变化，当前展示保留的进展。<button type="button" className="ui-button" onClick={()=>void owner.refresh().then(()=>flow.load()).catch(()=>undefined)}>重新读取</button></p>}
    {guides[discussion.phase.kind].mainlines.map(mainline=><section key={mainline.ref} className="discussion-mainline"><h3>{mainline.title}</h3><p>{mainline.purpose}</p>
     {discussion.topics.filter(topic=>topic.phase_ref===discussion.phase.phase_ref&&topic.mainline_ref===mainline.ref).map(topic=><details key={topic.topic_ref}><summary>{topic.title} · {assessments[topic.assessment]}</summary><p>{topic.purpose}</p>
      <ul>{topic.expected_outcomes.map(outcome=><li key={outcome.outcome_ref}>{outcome.text}：{outcome.criterion}</li>)}</ul>
      {topic.unresolved_impacts.map((impact,index)=><p key={index}>未决影响：{impact}</p>)}
      {discussion.evidence.filter(item=>topic.evidence_refs.includes(item.evidence_ref)).map(item=><div key={item.evidence_ref}><p>AI 整理：{item.assertion}</p><p className="field-help">{item.origin==='AI_PROPOSAL'?'AI 建议':item.origin==='USER_DECISION'?'用户决定':'用户陈述'} · {item.state}</p><ul>{item.source_refs.map(source=><li key={JSON.stringify(source)}><SourceReference read={signal=>owner.readSource(source,signal)} label={source.kind==='REVISION'?`文档 ${source.document_id} · 版本记录 ${source.revision_id}`:source.kind==='MESSAGE'?`消息 ${source.message_id}`:source.kind==='CARD_ANSWER'?`回答 ${source.message_id} · ${source.card_key}`:`运行 ${source.guide_run_id}`}/></li>)}</ul></div>)}
      {discussion.dispositions.filter(item=>item.scope_refs.includes(topic.topic_ref)).map((item,index)=><p key={index}>用户处置：{item.summary}</p>)}
      <button type="button" className="ui-button" disabled={locked||discussion.focus_topic_ref===topic.topic_ref} onClick={()=>void send({type:'SET_FOCUS',topic_ref:topic.topic_ref})}>讨论此主题</button>
     </details>)}
    </section>)}
    {!discussion.topics.some(topic=>topic.phase_ref===discussion.phase.phase_ref)&&<p className="panel-empty">本阶段尚无主题。</p>}
    <details><summary>讨论目标与来源</summary><label>工作目标<SingleSelect label="工作目标" disabled={locked} value={selectedTarget===null?'NONE':String(selectedTarget)} options={[{value:'NONE',label:'不绑定文档'},...actual.documents.map(document=>({value:String(document.id),label:document.name+(document.archived_at===null?'':'（已归档）')}))]} change={value=>setTarget(value==='NONE'?null:Number(value))}/></label>
     <fieldset disabled={locked}><legend>参考文档</legend>{actual.documents.map(document=><label key={document.id}><input type="checkbox" checked={selectedSources.includes(document.id)} onChange={event=>setReferences(event.currentTarget.checked?[...selectedSources,document.id]:selectedSources.filter(id=>id!==document.id))}/>{document.name} · v{document.content_version}</label>)}</fieldset>
     <button type="button" className="ui-button" disabled={locked} onClick={()=>void send({type:'SET_BINDING',target_document_id:selectedTarget,scope:selectedTarget===discussion.binding.target_document_id?discussion.binding.scope:selectedTarget===null?null:{scope_type:'DOCUMENT',scope_ref:null},source_refs:[...discussion.binding.source_refs.filter(ref=>ref.kind!=='REVISION'),...selectedSources.map(identity=>{const document=actual.documents.find(item=>item.id===identity)!;return {kind:'REVISION',document_id:identity,revision_id:document.current_revision_id,block_ids:null};})]})}>保存讨论绑定</button>
    </details>
    <details><summary>阶段与用户处置</summary><label>下一阶段<SingleSelect label="下一阶段" disabled={locked} value={phase??discussion.phase.kind} options={phaseKinds.map(value=>({value,label:phaseLabels[value]}))} change={value=>setPhase(value as typeof phaseKinds[number])}/></label>
     <label>收束说明<textarea className="ui-input" disabled={locked} value={closure} onChange={event=>setClosure(event.currentTarget.value)}/></label><p>本阶段尚待讨论或复核的主题：{unresolved.length?unresolved.join('、'):'无'}。切换时保留这些未决项。</p>
     <button type="button" className="ui-button" disabled={locked||phase===null||phase===discussion.phase.kind} onClick={()=>setConfirm(true)}>切换阶段</button>
     <label>处置范围<SingleSelect label="处置范围" disabled={locked} value={subject??discussion.phase.phase_ref} options={[{value:discussion.phase.phase_ref,label:'当前阶段'},...discussion.topics.filter(topic=>topic.phase_ref===discussion.phase.phase_ref).map(topic=>({value:topic.topic_ref,label:topic.title}))]} change={setSubject}/></label>
     <label>用户决定<SingleSelect label="用户决定" disabled={locked} value={decision} options={[{value:'DEFER',label:'暂缓'},{value:'NOT_APPLICABLE',label:'不适用'},{value:'DECLINE_DRAFT',label:'暂不出稿'}]} change={value=>setDecision(value as typeof decision)}/></label>
     <label>处置说明<textarea className="ui-input" disabled={locked} value={description} onChange={event=>setDescription(event.currentTarget.value)}/></label><button type="button" className="ui-button" disabled={locked||!description.trim()} onClick={()=>void send({type:'SET_DISPOSITION',subject_ref:subject??discussion.phase.phase_ref,decision,description})}>保存用户处置</button>
    </details>
   </>}
   {(state.error||error)&&<p className="inline-error" role="alert">{error??state.error}<button type="button" className="ui-button" disabled={state.loading||state.phase==='SUBMITTING'} onClick={()=>void owner.refresh().then(()=>flow.load()).catch(()=>undefined)}>重新读取进展</button></p>}
   {state.phase==='UNKNOWN'&&<button type="button" className="ui-button" disabled={blocked} onClick={()=>void flow.retryUnknown()}>核实原请求</button>}
   {state.phase==='CONFIRMED'&&<button type="button" className="ui-button" disabled={blocked||state.loading} onClick={()=>void flow.finish()}>读取保存结果</button>}
   {!discussion&&!state.loading&&<button type="button" className="ui-button" onClick={()=>void flow.load()}>读取讨论进展</button>}
  </details>
  <Confirmation open={confirm} title="切换讨论阶段" description="当前主题和未决项将保留在历史中。此操作保存用户决定，不生成文档。" busy={state.phase==='SUBMITTING'} confirmDisabled={locked||phase===null} error={state.error??error} confirm={()=>{if(phase)void send({type:'CHANGE_PHASE',phase_kind:phase,closure_message:closure.trim()?closure:null,unresolved_refs:unresolved});}} cancel={()=>{if(state.phase!=='SUBMITTING')setConfirm(false);}}/>
 </section>;
}
