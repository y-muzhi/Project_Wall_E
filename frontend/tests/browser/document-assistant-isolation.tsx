import { createRoot } from 'react-dom/client';
import { Crepe } from '@milkdown/crepe';
import { ApiClient } from '../../src/api/client.ts';
import { WalleApi } from '../../src/api/walle.ts';
import { RequirementDetail } from '../../src/requirements/detail.tsx';
import type { DiscussionState } from '../../src/api/models.ts';
import type { DiscussionCommand } from '../../src/api/walle.ts';
import type { RequirementDetailOwner } from '../../src/requirements/detail-owner.ts';
import { installSourceNodes } from '../../src/documents/source-nodes.ts';
import '../../src/shared/styles.css';

const at='2026-11-01T00:00:00.000Z',key='00000000-0000-4000-8000-000000000001';
const root={id:1,requirement_no:'REQ000001',title:'文档助手隔离',requirement_type:'NEW',status:'PLANNING',
 metadata_version:1,initial_message_id:1,discussion_version:1,document_work_state:'IDLE',
 active_operation_type:null,active_operation_id:null,created_at:at,updated_at:at,completed_at:null,closed_at:null,state_started_at:null};
const documentVersions = new Map([[1,1],[2,1]]);
const summary=(id:number)=>({id,requirement_id:1,name:(id===1?'文档 A':'文档 B')+(new URLSearchParams(location.search).has('long')?' · 需要完整换行展示的关联文档名称及业务说明'.repeat(2):''),document_kind:'DESIGN',document_type:'CURRENT',
 metadata_version:1,content_version:documentVersions.get(id)??1,current_revision_id:id+((documentVersions.get(id)??1)-1)*100,confirmed_revision_id:null,archived_at:null,updated_at:at,source_status:'UNCHANGED'});
const view=(id:number)=>({...summary(id),markdown_content:'',block_state_json:{schema_version:1,next_block_id:1,blocks:[]},template_ref:null,created_at:at});
const discussion=(id:number):DiscussionState=>({schema_version:2,
 focus_topic_ref:null,topics:[],evidence:[],pending_user_message_ids:[],binding:{target_document_id:id,source_refs:[],scope:null,document_kind:'design'},dispositions:[],last_step:null,counters:{topic:1,evidence:1}});
const message=(id:number)=>({id:100+id,requirement_id:1,document_id:id,guide_run_id:null as number|null,sequence_no:id,role:'ASSISTANT',
 content:id===1?'A 文档专属对话':'B 文档专属对话',message_type:'TEXT',structured_content:null,reply_to_message_id:null,created_at:at,card_state:null,
 phase_ref:'p1',topic_refs:[],document_ids:[],program_receipt:null});
const messages=new Map([[1,[message(1)]],[2,[message(2)]]]);
const versions=new Map([[1,1],[2,1]]);
const discussions = new Map<number,DiscussionState>([[1, {...discussion(1), binding:{target_document_id:null,source_refs:[],scope:null,document_kind:null}}], [2, discussion(2)]]);
let bindingMode: 'NORMAL' | 'UNKNOWN' | 'REJECT' | 'HOLD' = 'NORMAL';
let releaseBinding: (() => void) | undefined;
let failProgress = false;
const bindingReceipts = new Map<string, unknown>();
const requests:{path:string;method:string;body:unknown}[]=[];
let owner:RequirementDetailOwner|undefined,lose=false;
const receipts=new Map<string,{processing:string;guide_run_id:number;user_message_id:number}>();
const runs:Record<string,unknown>[]=[];
const reply=(data:unknown,pagination?:unknown,status=200)=>new Response(JSON.stringify({success:true,data,error:null,meta:{request_id:key,...(pagination?{pagination}:{})}}),{status,headers:{'Content-Type':'application/json'}});
const paged={page:1,page_size:20,total:0,total_pages:0};
const fetchFixture:typeof fetch=async(input,init)=>{
 const url=new URL(String(input),'http://fixture.invalid'),id=Number(url.searchParams.get('document_id'))||1,method=init?.method??'GET';
 const body=init?.body?JSON.parse(String(init.body)):null;requests.push({path:url.pathname+url.search,method,body});
 if(method==='POST' && url.pathname.endsWith('/guide-runs')){
   const receiptKey=String(new Headers(init?.headers).get('Idempotency-Key'));
   let receipt=receipts.get(receiptKey);
   if(!receipt){
    receipt={processing:'MODEL',guide_run_id:50+runs.length,user_message_id:200+runs.length};
    receipts.set(receiptKey,receipt);versions.set(body.document_id,(versions.get(body.document_id)??1)+1);
    runs.push({id:receipt.guide_run_id,requirement_id:1,document_id:body.document_id,action_type:'ASK',function_type:'collaboration_v1',source_type:'USER_INSTRUCTION',source_id:null,scope:null,
     status:'FAILED',current_step:'FINISHED',suggestion_batch_id:null,latest_assistant_message_id:null,error_code:'CONFIG_INVALID',error_message:'隔离夹具未调用模型',cancel_reason:null,retry_of_guide_run_id:null,
     created_at:at,started_at:null,waiting_user_at:null,ended_at:at,updated_at:at,operation:'DISCUSS',parent_guide_run_id:null,target:body.target,discussion_version_snapshot:2,material_summary:null,
     application_result:'NOT_REQUESTED',progress_result:'NOT_REQUESTED',progress_error:null,document_effect:null,final_result:null,returned_responses:[]});
    messages.get(body.document_id)!.push({...message(body.document_id),id:receipt.user_message_id,role:'USER',content:body.instruction,guide_run_id:receipt.guide_run_id,sequence_no:receipt.user_message_id});
   }
   if(lose){lose=false;throw Error('deliberate lost receipt');}
   return reply(receipt,undefined,202);
 }
 if(method==='PATCH' && url.pathname==='/api/v1/requirements/1'){
   const documentId=Number(body.document_id), receiptKey=String(new Headers(init?.headers).get('Idempotency-Key'));
   const mode=bindingMode;bindingMode='NORMAL';
   if(mode==='HOLD') await new Promise<void>(resolve=>{releaseBinding=resolve;});
   if(mode==='REJECT')return new Response(JSON.stringify({success:false,data:null,error:{code:'DISCUSSION_VERSION_CONFLICT',message:'讨论版本已变化，请重新读取进展。',details:null},meta:{request_id:key}}),{status:409,headers:{'Content-Type':'application/json'}});
   let receipt=bindingReceipts.get(receiptKey);
   if(!receipt){
     const command=body.discussion_command as DiscussionCommand;
     if(command.type!=='SET_BINDING'||command.target_document_id!==documentId)throw Error('Fixture requires fixed current document');
     const previous=discussions.get(documentId)!;
     const next:DiscussionState={...previous,binding:{target_document_id:documentId,scope:command.scope,source_refs:command.source_refs,document_kind:'design'}};
     versions.set(documentId,versions.get(documentId)!+1);discussions.set(documentId,next);
     receipt={requirement_id:1,discussion_version:versions.get(documentId),discussion:next};bindingReceipts.set(receiptKey,receipt);
   }
   if(mode==='UNKNOWN')throw Error('deliberate lost binding receipt');
   return reply(receipt);
 }
 if(method!=='GET') throw Error('Unexpected fixture mutation '+url.pathname);
 if(url.pathname==='/api/v1/requirements/1'){
   if(failProgress&&url.searchParams.has('expand')){failProgress=false;throw Error('deliberate progress read failure');}
   const version=versions.get(id)??1;
   return reply({requirement:{...root,discussion_version:version},documents:[summary(1),summary(2)],
    discussion_summary:{discussion_version:version,focus_topic_ref:null,focus_title:null,next_step:null,pending_count:0},
    discussion:url.searchParams.has('expand')?discussions.get(id):null,active_operation:null});
 }
 if(url.pathname.endsWith('/current-document'))return reply(view(id));
 if(url.pathname.endsWith('/comment-index'))return reply({requirement_id:1,document_id:id,content_version:documentVersions.get(id)??1,total_count:0,open_count:0,blocks:[],comments:[]});
 if(url.pathname.endsWith('/messages'))return reply({items:messages.get(id)??[]},{page_size:20,has_more:false,next_cursor:null});
 if(url.pathname.endsWith('/guide-runs')){
  const rows=runs.filter(row=>row.document_id===id).map(({final_result,returned_responses,...value})=>value);
  return reply({items:rows},{...paged,total:rows.length,total_pages:rows.length?1:0});
 }
 if(url.pathname.startsWith('/api/v1/guide-runs/'))return reply(runs.find(row=>row.id===Number(url.pathname.split('/').at(-1))));
 if(url.pathname.endsWith('/comments')||url.pathname.endsWith('/revisions'))return reply({items:[]},paged);
 throw Error('Unhandled fixture GET '+url.pathname);
};
const parser=new Crepe({root:document.querySelector<HTMLElement>('#parser')!,defaultValue:''});
await installSourceNodes(parser);await parser.create();parser.setReadonly(true);
const api=parser.editor.action(ctx=>new WalleApi(new ApiClient(fetchFixture),ctx));
const mounted=createRoot(document.querySelector('#product')!);
mounted.render(<RequirementDetail identity={1} api={api} back={()=>{}} ready={value=>{owner=value;}}/>);
Object.assign(window,{assistantProbe:{
 state:()=>({ready:owner?.getSnapshot().ready,error:owner?.getSnapshot().error,selected:owner?.getSnapshot().detail?.selected_document_id,
 input:owner?.regions?.conversation.composer.getSnapshot().instruction,phase:owner?.regions?.conversation.composer.getSnapshot().phase,
 messageDocs:owner?.regions?.conversation.read.messages.getSnapshot().items?.map(row=>row.document_id),progress:owner?.regions?.discussion.getSnapshot().discussion?.binding.document_kind,requests}),
 select:async(id:number|null)=>{await owner!.selectDocument(id);},
 input:(text:string)=>owner!.regions!.conversation.composer.change(text),
 loseSend:async()=>{lose=true;return owner!.regions!.conversation.composer.submit();},
 recover:()=>owner!.regions!.conversation.composer.recover(),
 refresh:()=>owner!.regions!.conversation.refresh(),
 progress:()=>owner!.regions!.discussion.load(),
 bindingMode:(mode:typeof bindingMode)=>{bindingMode=mode;},
 releaseBinding:()=>{releaseBinding?.();releaseBinding=undefined;},
 failProgress:()=>{failProgress=true;},
 bindingState:()=>owner!.regions!.discussion.getSnapshot(),
 advanceSource:async(id:number)=>{documentVersions.set(id,(documentVersions.get(id)??1)+1);await owner!.refresh();},
 destroy:async()=>{mounted.unmount();await owner?.retire();await parser.destroy();}
}});
