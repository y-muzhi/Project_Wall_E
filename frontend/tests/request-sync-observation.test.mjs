import {test} from 'node:test';
import assert from 'node:assert/strict';
import {RequirementAiRead} from '../src/guide/read-owner.ts';
const flush=async()=>{for(let i=0;i<200;i++)await Promise.resolve();};

test('fixed 0/10/30-second tasks keep one-second observation without amplifying resource refreshes',async()=>{
 for(const duration of [0,10000,30000]){
  let now=0;const jobs=[],counts={runs:0,parents:0,messages:0,history:0};
  const run=()=>({id:8,requirement_id:1,status:now<duration?'RUNNING':'FAILED',created_at:'2026-10-26T00:00:00.000Z',
   updated_at:'2026-10-26T00:00:00.000Z',current_step:now<duration?'CALLING_MODEL':'FINISHED',latest_assistant_message_id:null,
   suggestion_batch_id:null,final_result:null,application_result:now<duration?null:'NOT_REQUESTED',progress_result:now<duration?null:'NOT_REQUESTED',progress_error:null,document_effect:null});
  const detail=()=>({requirement:{id:1},current:null,activity:now<duration?{kind:'GUIDE',run:run()}:{kind:'IDLE'}});
  const timing={schedule(callback,ms){assert.equal(ms,1000);const job={at:now+ms,callback,cancelled:false};jobs.push(job);return()=>{job.cancelled=true;};}};
  const api={getGuideRun:async()=>{counts.runs++;return {data:run()};},
   listMessages:async()=>{counts.messages++;return {data:{items:[]},meta:{pagination:{page_size:20,has_more:false,next_cursor:null}}};},
   listGuideRuns:async()=>{counts.history++;return {data:{items:[run()]},meta:{pagination:{page:1,page_size:20,total:1,total_pages:1}}};}};
  const owner=new RequirementAiRead(detail(),api,async()=>{counts.parents++;return detail();},async()=>{},()=>{},timing);
  await owner.receive({id:8,requirement_id:1});await flush();
  for(let limit=0;limit<40;limit++){
   const job=jobs.find(job=>!job.cancelled);if(!job)break;job.cancelled=true;now=job.at;job.callback();await flush();
  }
  assert.equal(counts.runs,duration/1000+1);assert(counts.parents<=3);assert(counts.messages<=3);assert.equal(counts.history,1);
  assert.equal(owner.getSnapshot().run.status,'FAILED');assert(!owner.getSnapshot().polling);assert.equal(jobs.filter(job=>!job.cancelled).length,0);
  console.log(`fixed-clock ${duration/1000}s: run=${counts.runs}, detailCycles=${counts.parents}, messages=${counts.messages}, history=${counts.history}`);owner.dispose();
 }
});

test('real application/progress effect changes invalidate observers even when the older run signature fields are identical',async()=>{
 const base={id:8,requirement_id:1,status:'RUNNING',latest_assistant_message_id:null,suggestion_batch_id:null,final_result:null,
  application_result:null,progress_result:null,progress_error:null,document_effect:null};let actual=base,parents=0;
 const api={getGuideRun:async()=>({data:actual}),listMessages:async()=>({data:{items:[]},meta:{pagination:{page_size:20,has_more:false,next_cursor:null}}}),listGuideRuns:async()=>({data:{items:[]},meta:{pagination:{page:1,page_size:20,total:0,total_pages:0}}})};
 const detail={requirement:{id:1},current:null,activity:{kind:'IDLE'}};
 const owner=new RequirementAiRead(detail,api,async()=>{parents++;return detail;},async()=>{},()=>{},{schedule:()=>()=>{}});
 await owner.receive({id:8,requirement_id:1});await flush();let before=parents;
 actual={...base,application_result:'APPLIED',document_effect:{document_id:2,before_content_version:1,after_content_version:2,revision_id:7,result:'UPDATED'}};
 owner.readRun();await flush();assert(parents>before);before=parents;
 actual={...actual,progress_result:'REJECTED',progress_error:'保留原进展'};owner.readRun();await flush();assert(parents>before);owner.dispose();
});
