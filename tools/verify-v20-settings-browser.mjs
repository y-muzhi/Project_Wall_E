/** Actual SPA and isolated browser storage under the existing owned CLI lifecycle. */
import {readFile,readdir,stat,writeFile,mkdir} from 'node:fs/promises';
import {resolve,join,extname} from 'node:path';
import {pathToFileURL} from 'node:url';
import {createServer} from 'node:http';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {randomUUID} from 'node:crypto';

export async function verifySettingsPage(root,work,entry,mode="settings"){
 const repairSettled=mode==='repair-settled-reconciliation';
 if(repairSettled)mode='repair-reconciliation';
 const repairCreation=mode==='repair-creation-reconciliation';
 if(repairCreation)mode='repair-reconciliation';
 const roleCreation=mode==='role-creation-reconciliation';
 if(roleCreation)mode='role-reconciliation';
 const liveConfiguration=mode==='coding-live-configuration';
 const reportLinkOnly=mode==='coding-report-link';
 const codingDelivery=mode==='coding-delivery';
 const codingRecords=mode==='coding-records';
 if(reportLinkOnly||codingDelivery||codingRecords||liveConfiguration)mode='tasks';
 const exec=promisify(execFile),{build}=await import(pathToFileURL(resolve(root,'frontend/node_modules/vite/dist/node/index.js')));
 const dist=join(work,'application'),seed=join(work,'seed');await mkdir(dist);await mkdir(seed);
 await build({root:join(root,'frontend'),configFile:join(root,'frontend/vite.config.ts'),logLevel:'error',build:{outDir:dist,emptyOutDir:false}});
 await build({root:join(root,'frontend'),configFile:false,logLevel:'error',build:{outDir:seed,emptyOutDir:false,minify:false,
  lib:{entry:join(root,'frontend/tests/browser/v20-settings-page-probe.ts'),formats:['es'],fileName:()=> 'seed.js'}}});
 const files=new Map();
 for(const name of await readdir(dist,{recursive:true})){
  if((await stat(join(dist,name))).isFile())files.set('/'+name.replaceAll('\\','/'),await readFile(join(dist,name)));
 }
 files.set('/seed.js',await readFile(join(seed,'seed.js')));
 const registeredOptions=JSON.parse(await readFile(join(root,'backend/resources/code/code20-r3/options.json'),'utf8')).items;
 const contentPolicy=registeredOptions.find(item=>item.kind==='CONTENT_POLICY');
 const managedScopes=registeredOptions.filter(item=>item.kind==='SCOPE');
 if(!contentPolicy||managedScopes.length!==2)throw Error('Actual catalogue fixtures are missing');

 let scenario='ready';const requests=[],recordReads=[];
 const testingProfilePath='/api/v1/testing-profile-versions',testingAuthPath='/api/v1/testing-authorizations';
 const testingWrites=[],testingProfiles=[],planWrites=[];
 const plans=[];
 const testPlansPath='/api/v1/test-plans',testPlanVersionPath='/api/v1/test-plan-versions';
 let planControlReceipt=null,draftConflictReceipt=null,draftReceipt=null,draftAvailable=false;
 const draftWrites=[],packWrites=[];
 let packSaved=null,packKey=null,sealKey=null;
 const sealWrites=[];
 const sealReceipt={operation_id:34,test_pack_version_id:29,validation_id:null};
 const sealHash='c'.repeat(64);
 let planVersion={id:11,plan_id:2,version:1,requirement_id:1,document_id:41,design_revision_id:24,
  material_refs:[],behaviors:[{behavior_id:'original',name:'固定行为',basis_refs:[{document_id:41,revision_id:24,quote:'固定设计原文'}],
   stages:['ACCEPTANCE'],importance:'CRITICAL',mode:'MANUAL',case_ids:[],explanation:'对照固定原文'}],
  cases:[],unresolved_questions:[],status:'DRAFT',state_version:1,created_at:'2026-11-10T00:00:00.000Z',
  published_at:null,revoked_at:null,revocation_reason:null};

 let testingAuthorization=null,testingTaskDraft=null,testingStopKey=null,testingStopped=false;
 const testingTaskWrites=[],testingStopWrites=[],findingWrites=[],executionWrites=[],planModelWrites=[];
 let reviewRecord=null;
 const findingPath='/api/v1/testing-findings/44/review';
 const reportPath='/api/v1/test-reports/17';
 const findingView=()=>({id:44,test_report_id:17,item_id:62,case_id:'public',actual_behavior:'命令返回非零退出码',
  expected_behavior:'命令应按固定设计退出成功',basis_ref:{document_id:41,revision_id:24,quote:'固定设计原文'},
  classification:reviewRecord?.input.classification??'UNCLASSIFIED',state_version:reviewRecord?2:1,
  review_reason:reviewRecord?.input.reason??null,review_operation_id:reviewRecord?46:null,created_at});
 const taskTestingPath='/api/v1/testing-tasks';
 const testingTaskResult={testing_task_id:1,state_version:1};
 const testingStopResult={testing_task_id:1,state_version:2,operation_id:37};
 const taskTestingView=()=>{
  const status=testingStopped?'TERMINATED':testingStopKey?'STOPPING':'DRAFT';
  const terminal=status==='TERMINATED';
  const actionNames=['DRAFT_PLAN','ATTACH_ASSETS','RUN_TEST','INCREASE_TEST_BUDGET','RESUME','RECONCILE','TERMINATE'];
  const fixedReasons=['MODEL_NOT_READY',null,'ASSET_NOT_READY',null,'TASK_STATE','OPERATION_UNKNOWN',null];
  return {...testingTaskDraft.input,id:1,kind:'PRODUCT',status,phase:terminal?'FINISHED':'PLAN',
   state_version:terminal?3:testingStopKey?2:1,control_generation:testingStopKey?2:1,
   current_verification_id:null,draft_plan_operation_id:null,active_operation_id:status==='STOPPING'?37:null,
   report_id:null,validation_id:null,stop_requested_at:testingStopKey?created_at:null,
   stopped_at:terminal?created_at:null,created_at,ended_at:terminal?created_at:null,
   available_actions:actionNames.map((action,index)=>({action,enabled:status==='DRAFT'&&fixedReasons[index]===null,
    reason_code:status==='DRAFT'?fixedReasons[index]:'TASK_STATE'})),
   runtime:{environment_status:'NOT_PREPARED',activity_status:'NOT_STARTED',stop_status:terminal?'VERIFIED':testingStopKey?'REQUESTED':'NONE',
    cleanup_status:terminal?'VERIFIED':'NOT_STARTED',reason_codes:[],active_process_count:terminal?0:null,
    observed_at:terminal?created_at:null},
   budget:{budget_limit_cny:'0.000000',settled_cny:'0.000000',reserved_cny:'0.000000',available_cny:'0.000000',model_request_count:0,request_limit:2},
   termination_operation_id:testingStopKey?37:null,draft_plan_result:null};
 };
 const planModelOperation=(entry)=>{
  const done=scenario==='testing-planning-done';
  const fixed=entry.input, id=entry.data.operation_id;
  const sequence=['BUILD_CONTEXT','RESERVE','CALL_MODEL','SAVE_DRAFT'];
  return {id,task_id:null,testing_task_id:1,resource_kind:'TESTING_TASK',resource_id:1,session_id:null,content_capture:null,
   operation_type:'DRAFT_PLAN',idempotency_key:entry.key,expected_state_version:fixed.expected_state_version,
   fixed_input:fixed,control_generation:1,status:done?'SUCCEEDED':'RUNNING',
   created_at,started_at:created_at,ended_at:done?created_at:null,failure_code:null,
   steps:sequence.map((step_type,index)=>{
    const complete=done||index<2, pending=!done&&index===3;
    return {operation_id:id,step_no:index+1,step_type,status:complete?'SUCCEEDED':pending?'PENDING':'RUNNING',
     external_identity:null,fixed_input:fixed,result_ref:done&&index===3?{plan_id:5,plan_version_id:11}:null,
     started_at:pending?null:created_at,ended_at:complete?created_at:null,last_observed_at:pending?null:created_at};
   })};
 };
 const executionResults={run:45,resume:46,reconcile:47};
 const executionTask=()=>{
  const waiting=scenario==='testing-execution-wait'&&!executionWrites.some(row=>row.action==='resume');
  const running=executionWrites.length>0;
  const status=waiting?'WAITING':running?'RUNNING':'READY';
  const enabled=new Set(['TERMINATE',...(waiting?['RESUME','RECONCILE']:running?['RECONCILE']:['RUN_TEST'])]);
  return {...taskTestingView(),status,phase:running?'EXECUTE':'PREPARE',control_generation:1,
   state_version:executionWrites.some(row=>row.action==='resume')?4:waiting?3:running?2:1,
   plan_version_id:11,test_pack_version_id:29,current_verification_id:running?32:null,
   active_operation_id:running?45:null,termination_operation_id:null,stop_requested_at:null,stopped_at:null,ended_at:null,
   available_actions:taskTestingView().available_actions.map(({action})=>({
    action,enabled:enabled.has(action),reason_code:enabled.has(action)?null:'TASK_STATE'})),
   runtime:{environment_status:'VERIFIED',activity_status:waiting?'UNKNOWN':running?'ACTIVE':'NOT_STARTED',
    stop_status:waiting?'UNKNOWN':'NONE',cleanup_status:waiting?'UNKNOWN':'NOT_STARTED',
    reason_codes:[],active_process_count:null,observed_at:null}};
 };
 const executionOperation=(entry)=>{
  const run=entry.action==='run', waiting=run&&executionTask().status==='WAITING';
  const id=executionResults[entry.action];
  const fixed_input=run?{...entry.input,input_fingerprint:sealHash}:entry.input;
  const steps=run?['FIX_INPUT','MATERIALIZE','PREPARE','EXECUTE','STOP','VERIFY_INPUT','CLEANUP','SAVE_REPORT']:
   entry.action==='resume'?['RECONCILE','CHECK_CONDITIONS','CONTINUE_OR_OBSERVE']:['QUERY','COMPARE','RECORD'];
  return {id,task_id:null,testing_task_id:1,resource_kind:'TESTING_TASK',resource_id:1,session_id:null,content_capture:null,
   operation_type:run?'RUN_TEST':entry.action.toUpperCase(),idempotency_key:entry.key,expected_state_version:entry.input.expected_state_version,
   fixed_input,control_generation:1,status:run?(waiting?'UNKNOWN':'RUNNING'):'SUCCEEDED',
   created_at,started_at:created_at,ended_at:run?null:created_at,failure_code:waiting?'EXECUTION_NOT_STOPPED':null,
   steps:steps.map((step_type,index)=>{
    const complete=!run||index<3, pending=run&&index>3;
    return {operation_id:id,step_no:index+1,step_type,status:complete?'SUCCEEDED':pending?'PENDING':waiting?'UNKNOWN':'RUNNING',
     external_identity:null,fixed_input,result_ref:run?null:{operation_id:45,observed_status:entry.action==='resume'?'UNKNOWN':'RUNNING'},
     started_at:pending?null:created_at,ended_at:complete?created_at:null,last_observed_at:pending?null:created_at};
   })};
 };
 const testingOptions={
  RUNNER:{runner_ref:'fixture-runner',protocol_version:'CHECK20-1',capabilities:[],protected_input_refs:[]},
  RUNTIME:{runtime_ref:'fixture-runtime',runtime_kind:'NODE',version:'fixture-version'},
  CAPABILITY:{capability_code:'Q20-CHECKS',evidence_ref:'fixture-admission'},
 };
 const testingLabels={RUNNER:'固定运行器',RUNTIME:'固定环境',CAPABILITY:'固定准入依据'};
 const testingTime='2026-11-10T00:00:00.000Z';

 const repository={id:23,name:'隔离登记仓库',object_format:'sha1',created_at:'2026-11-07T00:00:00.000Z',root_path:null,
  latest_observation:{id:33,status:'UNKNOWN',observed_at:'2026-11-07T00:10:00.000Z'}};

 const authorizationLimits=Object.fromEntries([
  'max_model_requests','max_output_tokens','max_consecutive_failures','max_active_seconds','max_file_bytes',
  'max_snapshot_bytes','max_snapshot_files','max_capture_entries','max_capture_seconds','max_manifest_bytes',
  'max_git_seconds','max_git_output_bytes','max_delivery_window_seconds','max_check_output_bytes','max_check_cases',
  'max_case_steps','max_case_payload_bytes','query_timeout_seconds','send_timeout_seconds','queue_wait_seconds',
  'graceful_stop_seconds','force_stop_wait_seconds',
 ].map(field=>[field,20]));
 const authorizationScope={read_roots:['scope:source'],write_workspace_only:true,allowed_command_ids:[],
  network_targets:[],model_profile_refs:['deepseek-v2'],allow_local_delivery:false,limits:authorizationLimits};
 const authorizations=[
  {id:87,task_id:null,profile_version_id:17,scope:authorizationScope,status:'APPROVED_UNBOUND',
   approved_at:'2026-11-07T00:00:00.000Z',actor_ref:'owned-test-actor'},
  {id:85,task_id:31,profile_version_id:17,scope:authorizationScope,status:'EFFECTIVE',
   approved_at:'2026-11-07T00:00:00.000Z',actor_ref:'owned-test-actor'},
 ];
 const originalChecks={id:7,name:'基线检查配置',latest_version_id:18};
 const originalProfile={id:9,name:'隔离执行配置',latest_version_id:19};
 const created_at='2026-11-07T00:00:00.000Z';
 const checkVersion={id:17,check_set_id:7,version:1,owner_module:'CODING',protocol_version:'CHECK20-CONTROL-1',
  items:[],coverage_plan:[],created_at,ready:false,unresolved_capability_codes:['Q20-CHECKS']};
 const secondCheckVersion={...checkVersion,id:18,version:2,ready:true,unresolved_capability_codes:[],
  items:[{check_id:'check-unit',name:'离线单元检查',stages:['BACKEND'],required:true,check_kind:'PROJECT_COMMAND',
   command_id:'command-unit',runner_ref:'runner-unit',case_pack_ref:null,expected_exit_codes:[0],environment_refs:[],
   protected_input_refs:[],target:null,timeout_seconds:20,evidence_rule:{kind:'PROCESS_EXIT'}}],
  coverage_plan:[{coverage_id:'requirement-coverage',stages:['BACKEND'],mode:'MANUAL',check_ids:[],
   explanation:'核对原验收依据',basis_refs:[{document_id:41,revision_id:25,quote:'原始验收条目'}]}]};
 const modelBinding={native_model_id:'walle-code',purpose:'CODE',model_profile_ref:'deepseek-v2',
  model_snapshot_ref:'isolated-model-snapshot',price_version_id:12,input_cap_tokens:1000,context_cap_tokens:2000,
  output_cap_tokens:20,admission_ref:'isolated-admission'};
 const profileVersion={id:19,profile_id:9,version:1,created_at,ready:false,unresolved_capability_codes:['Q20-MODEL'],
  executor:{version:'1.19.5',binary_ref:'isolated-executor',adapter_contract_version:'isolated-adapter',
   runtime_bundle_ref:'isolated-executor-runtime',configuration_policy_version:'OC20-CONFIG-1',
   runtime_policy_version:'WIN20-ISOLATION-1'},
  git:{version:'2.56.0.windows.4',binary_ref:'isolated-git',runtime_bundle_ref:'isolated-git-runtime',
   source_commit:'581291682ad5a238c08c93d1f5bd4518382a3230',protocol_version:'GIT20-LOCAL-1'},
  models:{primary_profile_ref:'deepseek-v2',auxiliary_profile_refs:[],protocol_version:'OC20-MODEL-1',
   bindings:[modelBinding,{...modelBinding,native_model_id:'walle-compaction',purpose:'COMPACTION'}]},
  environment:{python_ref:null,node_ref:null,package_manager_refs:[],secret_refs:['isolated-secret-ref']},
  commands:[],capture_rules:{content_policy_version:'CONTENT20-STORE-1',product_include_paths:['src/'],
   nonproduct_exclude_paths:[],new_file_mode:'100644',secret_policy_ref:'isolated-secret-policy'},
  delivery:null,check_set_version_id:18,limits:authorizationLimits,capability_evidence_refs:[]};
 const checks=[originalChecks], profiles=[], identityReceipts=new Map(), originalKeys=new Map(), mutations=[], recoveryWrites=[];
 const registrations=new Map();
 const registrationWrites=[];
 const refreshes=new Map(),refreshWrites=[],refreshPath='/api/v1/code-repositories/26/refresh';
 const observationPath='/api/v1/code-repositories/26/observations/35';
 const commit='1'.repeat(40);
 function refreshOperation(entry,status){
  const fixed_input={repository_id:26};
  const terminal=status==='SUCCEEDED';
  const steps=['READ_REPOSITORY','SAVE_OBSERVATION'].map((step_type,index)=>({
   operation_id:entry.result.operation_id,step_no:index+1,step_type,
   status:index===0?status:terminal?'SUCCEEDED':'PENDING',
   external_identity:null,fixed_input,started_at:index===0||terminal?created_at:null,
   ended_at:terminal?created_at:null,last_observed_at:created_at,
   result_ref:index===1&&terminal?{observation_id:35}:null,
  }));
  return {id:entry.result.operation_id,task_id:null,testing_task_id:null,resource_kind:'REPOSITORY',
   resource_id:26,session_id:null,operation_type:'REFRESH_REPOSITORY',
   idempotency_key:entry.key,expected_state_version:null,fixed_input,control_generation:null,status,
   created_at,started_at:created_at,ended_at:terminal?created_at:null,
   failure_code:status==='UNKNOWN'?'EXTERNAL_RESULT_UNKNOWN':null,steps,content_capture:null};
 }

 function registrationOperation(entry,status){
  const fixed_input={name:entry.name};
  const terminal=status==='FAILED'||status==='SUCCEEDED';
  const steps=['VALIDATE','SAVE_FACT'].map((step_type,index)=>({
   operation_id:entry.result.operation_id,step_no:index+1,step_type,
   status:index===0?status:status==='SUCCEEDED'?'SUCCEEDED':'PENDING',
   external_identity:null,fixed_input,started_at:index===0||status==='SUCCEEDED'?created_at:null,
   ended_at:index===0&&terminal||status==='SUCCEEDED'?created_at:null,last_observed_at:null,
   result_ref:index===1&&status==='SUCCEEDED'?{repository_id:entry.result.resource_id}:null,
  }));
  return {id:entry.result.operation_id,task_id:null,testing_task_id:null,resource_kind:'REPOSITORY',
   resource_id:entry.result.resource_id,session_id:null,operation_type:'REGISTER_REPOSITORY',
   idempotency_key:entry.key,expected_state_version:null,fixed_input,control_generation:null,status,
   created_at,started_at:created_at,ended_at:terminal?created_at:null,
   failure_code:status==='FAILED'?'SOURCE_UNSUPPORTED':null,steps,content_capture:null};
 }
 function savedRegistration(entry,detail=false){
  return {id:entry.result.resource_id,name:entry.name,object_format:'sha1',created_at,
   root_path:detail?entry.root_path:null,latest_observation:null};
 }

 const taskPath='/api/v1/documents/41/code-tasks', taskViewPath='/api/v1/code-tasks/31';
 const taskWrites=[], taskOperations=new Map();
 const configurationPath=taskViewPath+'/configuration',configurationWrites=[];
 let configurationSaved=null;
 const replacementProfile={...profileVersion,id:20,version:2};
 const replacementGrant={...authorizations[0],id:89,profile_version_id:20};
 function configurationOperation(done) {
  const {key,data,input}=configurationSaved;
  const fixed_input={task_id:31,...input},at=created_at;
  const unknown=liveConfiguration&&scenario==='task-configuration-unknown';
  const status=done?'SUCCEEDED':unknown?'UNKNOWN':'RUNNING';
  return {id:data.operation_id,task_id:31,testing_task_id:null,resource_kind:'TASK',resource_id:31,session_id:liveConfiguration?8:null,
   operation_type:'APPLY_CONFIGURATION',idempotency_key:key,expected_state_version:input.expected_state_version,
   fixed_input,control_generation:1,status,created_at:at,started_at:at,
   ended_at:done?at:null,failure_code:unknown?'EXTERNAL_RESULT_UNKNOWN':null,content_capture:null,
   steps:['BLOCK_NEW','QUIESCE_IF_REQUIRED','APPLY_PAIR','VERIFY_EFFECTIVE'].map((step_type,index)=>{
    const succeeded=(liveConfiguration?index===0:index<3)||done;
    const observed=unknown&&index===1;
    const refs=[{state_version:data.state_version},{scope:liveConfiguration?'CURRENT_SESSION':'NO_INSTANCE'},
      {configuration_application_id:92},{configuration_application_id:92,start_operation_id:120}];
    return {operation_id:data.operation_id,step_no:index+1,step_type,status:succeeded?'SUCCEEDED':observed?'UNKNOWN':'PENDING',
     external_identity:null,fixed_input,result_ref:succeeded?refs[index]:null,started_at:succeeded||observed?at:null,
     ended_at:succeeded?at:null,last_observed_at:succeeded||observed?at:null};
   })};
 }
 function liveConfigurationTask(){
  const applied=scenario==='task-configuration-applied',unknown=scenario==='task-configuration-unknown';
  const waiting=Boolean(configurationSaved)&&!applied;
  const data=startedTask(false,{},configurationSaved?applied?20:19:18);
  return {...data,status:waiting?'WAITING':'VERIFYING',phase:'BACKEND',resume_phase:waiting?'BACKEND':null,
   current_candidate_id:202,active_session_id:8,execution_profile_version_id:applied?20:19,authorization_id:applied?89:87,
   current_refs:{verification_id:72,test_report_id:null,delivery_plan_id:null,delivery_id:null},
   runtime:{...data.runtime,activity_status:waiting?'UNKNOWN':'QUIESCENT',active_process_count:waiting?null:1,observed_at:created_at},
   configuration_application:configurationSaved?{id:92,status:applied?'APPLIED':unknown?'UNKNOWN':'PENDING',
    new_profile_version_id:20,authorization_id:89,evidence_result:applied?'VERIFIED':null,difference_kinds:[],
    observed_at:applied?created_at:null}:null,
   verification_purposes:data.verification_purposes.map(item=>({...item,reason_code:waiting?'TASK_STATE':'RESOURCE_NOT_READY'})),
   waiting_items:waiting?[{id:18,task_id:31,testing_task_id:null,kind:'CONFIGURATION',source_kind:'OPERATION',
    source_id:119,resume_phase:'BACKEND',status:'OPEN',created_at,resolved_at:null,resolution_ref:null}]:[],
   active_operations:waiting?[{id:119,operation_type:'APPLY_CONFIGURATION',status:unknown?'UNKNOWN':'RUNNING'}]:[],
   available_actions:data.available_actions.map(item=>item.action==='APPLY_CONFIGURATION'
    ?{...item,enabled:!waiting,related_id:waiting?119:null,reason_code:waiting?'OPERATION_IN_PROGRESS':null}:item)};
 }
 let taskSaved=null, snapshotReady=false, baselineResends=0;
 const taskDoc={id:41,requirement_id:1,name:'隔离设计文档',document_kind:'DESIGN',document_type:'CURRENT',
  metadata_version:1,content_version:2,current_revision_id:25,confirmed_revision_id:24,archived_at:null,
  updated_at:created_at,source_status:'UNCHANGED'};
 const taskDocument={...taskDoc,markdown_content:'',block_state_json:{schema_version:1,next_block_id:1,blocks:[]},
  created_at,template_ref:null};
 const taskRevision={id:24,requirement_id:1,document_id:41,version_no:1,source_content_version:1,
  created_at,change_summary:null,source_refs:[],markers:[]};
 const recentTaskRevision={...taskRevision,id:25,version_no:2,source_content_version:2};
 const taskReq={id:1,requirement_no:'REQ000001',title:'隔离编码需求',requirement_type:'NEW',status:'READY',
  metadata_version:1,initial_message_id:1,discussion_version:1,document_work_state:'IDLE',active_operation_type:null,
  active_operation_id:null,created_at,updated_at:created_at,completed_at:null,closed_at:null,state_started_at:null};
 const taskDetail={requirement:taskReq,documents:[taskDoc],
  discussion_summary:{discussion_version:1,focus_topic_ref:null,focus_title:null,next_step:null,pending_count:0},
  discussion:null,active_operation:null};
 const taskSummary={id:31,document_id:41,status:'PENDING',phase:'PREPARING',state_version:1,
  created_at,updated_at:created_at,current_candidate_id:null};
 const taskActions=['START','RESUME','ANSWER_QUESTION','DECIDE_PERMISSION','APPLY_CONFIGURATION','INCREASE_BUDGET',
  'PREPARE_HANDOFF','LINK_HANDOFF','REGISTER_DEFECT','VERIFY_CANDIDATE','CAPTURE_AND_CHECK','REPAIR','HANDOFF_ROLE',
  'PREPARE_DELIVERY','ACCEPT','SUBMIT_FOR_TESTING','LINK_TEST_REPORT','TERMINATE','RECONCILE'];
 const enabledTaskActions=new Set(['APPLY_CONFIGURATION','INCREASE_BUDGET','TERMINATE','RECONCILE']);
 function taskView(input){
  const {budget_limit_cny,...fixed}=input;
  const [whole,fraction='']=budget_limit_cny.split('.');
  const amount=whole+'.'+fraction.padEnd(6,'0');
  return {...taskSummary,...fixed,requirement_id:1,control_generation:1,workspace_id:null,active_session_id:null,
   resume_phase:null,started_at:null,ended_at:null,stop_requested_at:null,stopped_at:null,last_observed_at:null,
   current_refs:{verification_id:null,test_report_id:null,delivery_plan_id:null,delivery_id:null},
   configuration_application:null,runtime:{isolation_mode:'WINDOWS_LPAC',environment_status:'NOT_PREPARED',
    activity_status:'NOT_STARTED',stop_status:'NONE',cleanup_status:'NOT_STARTED',reason_codes:[],active_process_count:null,observed_at:null},
   waiting_items:[],active_operations:[],budget:{limit_cny:amount,settled_cny:'0.000000',reserved_cny:'0.000000',
    available_cny:amount,unresolved_call_count:0},current_basis_difference:[{document_id:41,fixed_revision_id:24,current_revision_id:25}],
   available_actions:taskActions.map(action=>({action,related_id:null,enabled:enabledTaskActions.has(action),
    reason_code:enabledTaskActions.has(action)?null:action==='START'?'CONFIG_NOT_READY':action==='LINK_HANDOFF'?'PRECONDITION_FAILED':'INVALID_STATE'})),
   termination_operation_id:null,verification_purposes:['CAPTURE_AND_CHECK','VERIFY_CANDIDATE']
    .map(action=>({action,purpose:'HANDOFF',enabled:false,reason_code:'TASK_STATE'}))};
 }

 const verifyPath=taskViewPath+'/candidates/202/verifications';
 const publicationPath=taskViewPath+'/testing-publication';
 const reportLinkPath=taskViewPath+'/test-reports',reportLinkWrites=[];
 const defectPath=taskViewPath+'/defects',defectWrites=[];
 const importedFinding={id:84,test_report_id:72,item_id:62,case_id:'public',
  actual_behavior:'独立检查原失败',expected_behavior:'按原设计保留输出',
  basis_ref:{document_id:41,revision_id:24,quote:'固定设计原文。'},
  classification:'PRODUCT',state_version:2,review_reason:'已核对',review_operation_id:85,created_at};
 let codingReportLink=null,deliveryAcceptance=null,repairAcceptance=null;
 const deliveryRecord=()=>({id:43,task_id:31,acceptance_id:42,delivery_plan_id:41,operation_id:111,
  status:'PENDING',git_write_status:'NOT_DISPATCHED',postcheck_status:'NOT_RUN',created_at,
  current_window_id:44,commit_input_sha256:null,observed_target_commit:null,delivered_at:null,
  last_reconciled_at:null,planned_commit_oid:null,failure_code:null,candidate_id:202,test_report_id:71,
  manual_risk_accepted:true,delivery_window:{state:'REQUIRED',confirmed_at:created_at,expires_at:created_at}});
 const repairReconciliation=mode==='repair-reconciliation';
 const roleReconcilePath=taskViewPath+'/reconcile',roleReconcileId=105,roleReconcileWrites=[];
 let roleReconcile=null;
 function savedRoleReconciliation(done){
  const fixed_input=roleReconcile.input,status=done?'SUCCEEDED':'PENDING';
  return {id:roleReconcileId,task_id:31,testing_task_id:null,resource_kind:'TASK',resource_id:31,
   session_id:8,operation_type:'RECONCILE',idempotency_key:roleReconcile.key,
   expected_state_version:fixed_input.expected_state_version,fixed_input,control_generation:2,
   status,created_at,started_at:done?created_at:null,ended_at:done?created_at:null,
   failure_code:null,content_capture:null,
   steps:['QUERY','COMPARE','RECORD'].map((step_type,index)=>({operation_id:roleReconcileId,step_no:index+1,
    step_type,status,external_identity:null,fixed_input,result_ref:done?{operation_id:104,original_status:repairReconciliation||roleCreation?'RUNNING':'SUCCEEDED'}:null,
    started_at:done?created_at:null,ended_at:done?created_at:null,last_observed_at:done?created_at:null}))};
 }

 function savedReconciledSource(){
  const common={id:104,task_id:31,testing_task_id:null,resource_kind:'TASK',resource_id:31,session_id:8,
   idempotency_key:roleReconcile.key,control_generation:repairReconciliation?2:1,
   created_at,started_at:created_at,ended_at:null,failure_code:null,content_capture:null};
  if(repairReconciliation){
   const fixed_input={expected_state_version:18,candidate_id:202,defect_ids:[1]};
   return {...common,operation_type:'REPAIR',expected_state_version:18,fixed_input,status:repairSettled?'SUCCEEDED':'RUNNING',ended_at:repairSettled?created_at:null,
    steps:['RESTORE_SOURCE','SEND_REPAIR','OBSERVE','CAPTURE_RESULT'].map((step_type,index)=>({
     operation_id:104,step_no:index+1,step_type,status:repairSettled?'SUCCEEDED':repairCreation?(index===0?'RUNNING':'PENDING'):(index<2?'SUCCEEDED':index===2?'RUNNING':'PENDING'),
     fixed_input,external_identity:null,result_ref:null,started_at:index<3?created_at:null,
     ended_at:repairSettled||index<2?created_at:null,last_observed_at:repairSettled||index<3?created_at:null}))};
  }
  const fixed_input={source_session_id:8,candidate_id:202,verification_id:72,target_role:'FRONTEND',expected_state_version:18};
  const refs=[{quiesce_observation_id:1},{session_id:8,control_generation:2},{verification_id:72},{session_id:9},null];
  return {...common,operation_type:'HANDOFF_ROLE',expected_state_version:18,fixed_input,status:'RUNNING',
   steps:['QUIESCE','REVOKE','CHECK','CREATE_SESSION','SEND_HANDOFF'].map((step_type,index)=>({
    operation_id:104,step_no:index+1,step_type,status:index<4?'SUCCEEDED':'PENDING',
    fixed_input,external_identity:null,result_ref:refs[index],started_at:index<4?created_at:null,
    ended_at:index<4?created_at:null,last_observed_at:index<4?created_at:null}))};
 }

 let taskPublication=null;
 const publicationWrites=[];
 const diffPath=taskViewPath+'/candidates/202/diff';
 const splitText=Buffer.concat([Buffer.alloc(65534,65),Buffer.from('😀\n')]);
 const changedFiles=[
  {path:'a-empty.txt',change:'ADD',before_size:null,after_size:0,before_mode:null,after_mode:'100644',binary:false},
  {path:'binary.bin',change:'MODIFY',before_size:2,after_size:3,before_mode:'100644',after_mode:'100644',binary:true},
  {path:'src/多字节.ts',change:'MODIFY',before_size:4,after_size:splitText.length,before_mode:'100644',after_mode:'100644',binary:false},
 ];
 let diffFileReads=0;
 let originalFileReads=0;
 const checkWrites=[];
 let caseReads=0;
 let taskCheck=null;
 const checkOperationId=101;
 function checkVerification(id){
  const passed=id===72;
  const verification={
   id,task_id:31,owner_kind:'CODING',testing_task_id:null,candidate_id:202,snapshot_id:null,
   purpose:'HANDOFF',role:'BACKEND',check_set_version_id:18,profile_version_id:19,
   testing_profile_version_id:null,environment_record_id:81,operation_id:passed?checkOperationId:99,
   scope_stages:['BACKEND'],selected_check_ids:['backend-project-check','backend-content-integrity'],
   status:'FINISHED',stop_status:'VERIFIED',cleanup_status:'VERIFIED',source_integrity_status:'VERIFIED',
   created_at,ended_at:created_at,backend_handoff_operation_id:null,frontend_handoff_operation_id:null,
   environment_record:{id:81,task_id:31,testing_task_id:null,runtime_refs:[],dependency_refs:[],
    runner_refs:['original-runner'],effective_config_application_id:91,testing_profile_version_id:null,
    check_resource_refs:['original-runner:sha256:'+'c'.repeat(64)],scope_key:'a'.repeat(64),observed_at:created_at},
   eligible:passed,ineligibility_reason_codes:passed?[]:['REQUIRED_NOT_PASSED'],
   items:['backend-project-check','backend-content-integrity'].map((check_id,index)=>({
    id:id*10+index,verification_id:id,check_id,required:true,
    check_kind:index?'CONTROLLED_ASSERTION':'PROJECT_COMMAND',
    evidence_kind:index?'CONTENT_INTEGRITY':'PROCESS_EXIT',
    command_execution_id:index?null:id*20,result:index||passed?'PASSED':'FAILED',
    reason_code:index||passed?null:'COMMAND_FAILED',expected_case_count:null,executed_case_count:null,
    passed_case_count:null,failed_case_count:null,reused_from_item_id:null,
    evidence_summary:index?null:JSON.stringify({exit_code:passed?0:7,stdout:{byte_count:20,sha256:'b'.repeat(64)},stderr:{byte_count:0,sha256:'c'.repeat(64)}}),
    started_at:created_at,ended_at:created_at,
   })),
  };
  if(passed){
   verification.selected_check_ids.push('original-controlled-case');
   verification.items.push({
    ...verification.items[1],id:722,check_id:'original-controlled-case',required:false,
    evidence_kind:'CONTROLLED_CASES',result:'FAILED',reason_code:'ASSERTION_FAILED',
    expected_case_count:22,executed_case_count:21,passed_case_count:20,failed_case_count:1,
   });
  }
  return verification;
 }
 function savedCheck(done){
  const fixed_input={...taskCheck.input,candidate_id:202};
  return {id:checkOperationId,task_id:31,testing_task_id:null,resource_kind:'TASK',resource_id:31,
   session_id:8,operation_type:'VERIFY_CANDIDATE',idempotency_key:taskCheck.key,
   expected_state_version:fixed_input.expected_state_version,fixed_input,control_generation:1,
   status:done?'SUCCEEDED':'RUNNING',created_at,started_at:created_at,ended_at:done?created_at:null,
   failure_code:null,content_capture:null,steps:['CHECK_CONDITIONS','RESTORE_CHECK_COPY','CHECK'].map((step_type,index)=>({
    operation_id:checkOperationId,step_no:index+1,step_type,status:index<2||done?'SUCCEEDED':'RUNNING',
    external_identity:null,fixed_input,result_ref:index<2?{candidate_id:202}:done?{verification_id:72}:null,
    started_at:created_at,ended_at:index<2||done?created_at:null,last_observed_at:created_at,
   }))};
 }
 const stopPath=taskViewPath+'/terminate',stopOperationId=82,stopWrites=[];
 let taskStop=null;
 const budgetPath=taskViewPath+'/budget',budgetWrites=[];
 let taskBudget=null;
 const resumePath=taskViewPath+'/resume',resumeWrites=[],resumeOperationId=96;
 let taskResume=null;
 const answerPath=taskViewPath+'/questions/1/responses',answerId=97,answerWrites=[];
 let taskAnswer=null;
 const handoffWritePath=taskViewPath+'/questions/4/handoff',handoffReadPath=taskViewPath+'/handoffs/17';
 const handoffLinkPath=handoffReadPath+'/links',handoffWrites=[],handoffLinkWrites=[];
 let taskHandoff=null,taskHandoffLink=null;
 function handoffQuestion(){
  return {id:4,task_id:31,session_id:8,instance_id:7,control_generation:1,status:'OPEN',observed_at:created_at,
   resolved_at:null,native_question_id:'que_handoff',questions:[
    {index:0,header:'待移交的固定问题',text:'请核对原设计约束。',options:[],multiple:false,custom:true}],
   handoffs:taskHandoff?[{id:17,target_document_id:41,created_at}]:[],
   available_actions:[{action:'ANSWER_QUESTION',enabled:false,reason_code:'CONFIG_NOT_READY',related_id:4},
    {action:'PREPARE_HANDOFF',enabled:true,reason_code:null,related_id:4}]};
 }
 const permissionPath=taskViewPath+'/permissions/2/responses',permissionId=98,permissionWrites=[];
 let taskPermission=null;
 function savedPermission(partial){
  const fixed_input={task_id:31,permission_id:2,...taskPermission.input};
  const states=partial?['SUCCEEDED','UNKNOWN','PENDING']:['PENDING','PENDING','PENDING'];
  return {id:permissionId,task_id:31,testing_task_id:null,resource_kind:'TASK',resource_id:31,
   session_id:8,operation_type:'DECIDE_PERMISSION',idempotency_key:taskPermission.key,
   expected_state_version:taskPermission.input.expected_state_version,fixed_input,control_generation:1,status:partial?'UNKNOWN':'PENDING',
   created_at,started_at:partial?created_at:null,ended_at:null,
   failure_code:partial?'EXTERNAL_RESULT_UNKNOWN':null,content_capture:null,
   steps:['READ_NATIVE','SEND_RESPONSE','CONFIRM_NATIVE'].map((step_type,index)=>({
    operation_id:permissionId,step_no:index+1,step_type,status:states[index],fixed_input,
    external_identity:partial&&index===1?{}:null,
    started_at:partial&&index<2?created_at:null,ended_at:partial&&index===0?created_at:null,
    last_observed_at:partial&&index<2?created_at:null,
    result_ref:!partial||index===2?null:index===0?{permission_ids:[2,3]}:
      {confirmed_permission_ids:[2],pending_permission_ids:[3]},
   }))};
 }
 function savedAnswer(done){
  const fixed_input={task_id:31,question_id:1,...taskAnswer.input};
  const states=done?['SUCCEEDED','SUCCEEDED','SUCCEEDED']:['PENDING','PENDING','PENDING'];
  return {id:answerId,task_id:31,testing_task_id:null,resource_kind:'TASK',resource_id:31,session_id:8,
   operation_type:'ANSWER_QUESTION',idempotency_key:taskAnswer.key,expected_state_version:9,fixed_input,
   control_generation:1,status:done?'SUCCEEDED':'PENDING',created_at,started_at:done?created_at:null,
   ended_at:done?created_at:null,failure_code:null,content_capture:null,
   steps:['READ_NATIVE','SEND_RESPONSE','CONFIRM_NATIVE'].map((step_type,index)=>({
    operation_id:answerId,step_no:index+1,step_type,status:states[index],
    external_identity:done&&index===1?{}:null,fixed_input,
    started_at:done?created_at:null,ended_at:done?created_at:null,last_observed_at:done?created_at:null,
    result_ref:done&&index!==1?{question_id:1}:null,
   }))};
 }
 const startPath=taskViewPath+'/start',startWrites=[];
 let taskStart=null;
 function startedTask(waiting,budget,version,task=taskSaved.view){
  return {...task,budget:{...task.budget,...budget},status:waiting?'WAITING':'RUNNING',
   phase:'BACKEND',state_version:version,workspace_id:19,active_session_id:8,
   resume_phase:waiting?'BACKEND':null,
   waiting_items:waiting?[{id:1,task_id:31,testing_task_id:null,kind:'BUDGET',source_kind:'OPERATION',
    source_id:91,resume_phase:'BACKEND',status:'OPEN',created_at,resolved_at:null,resolution_ref:null}]:[],
   started_at:created_at,last_observed_at:created_at,runtime:{...task.runtime,environment_status:'VERIFIED',
    activity_status:'UNKNOWN',observed_at:created_at},
   active_operations:waiting&&taskResume?[{id:resumeOperationId,operation_type:'RESUME',status:'UNKNOWN'}]:[],
   available_actions:task.available_actions.map(({action})=>{
    if(waiting&&action==='RESUME')return taskResume
     ?{action,enabled:false,reason_code:'EXTERNAL_RESULT_UNKNOWN',related_id:resumeOperationId}
     :{action,enabled:true,reason_code:null,related_id:91};
    const enabled=['TERMINATE','INCREASE_BUDGET'].includes(action);
    return {action,enabled,reason_code:enabled?null:'INVALID_STATE',related_id:null};
   })};
 }
 function savedResume(done){
  const fixed_input={task_id:31,...taskResume.input};
  return {id:resumeOperationId,task_id:31,testing_task_id:null,resource_kind:'TASK',resource_id:31,
   session_id:8,operation_type:'RESUME',idempotency_key:taskResume.key,expected_state_version:6,
   fixed_input,control_generation:1,status:done?'SUCCEEDED':'UNKNOWN',created_at,started_at:created_at,
   ended_at:done?created_at:null,failure_code:done?null:'EXTERNAL_RESULT_UNKNOWN',content_capture:null,
   steps:['RECONCILE','CHECK_CONDITIONS','CONTINUE_OR_OBSERVE'].map((step_type,index)=>({
    operation_id:resumeOperationId,step_no:index+1,step_type,status:index===2&&!done?'UNKNOWN':'SUCCEEDED',
    external_identity:index===2?{}:null,fixed_input,started_at:created_at,
    ended_at:index===2&&!done?null:created_at,last_observed_at:created_at,
    result_ref:index===0?{operation_id:91}:index===2&&done?{session_id:8}:null,
   }))};
 }
 function savedDeliveryCleanupResume(){
  const fixed_input={task_id:31,...taskResume.input};
  const refs=[{operation_id:111},null,{delivery_id:43}];
  return {id:resumeOperationId,task_id:31,testing_task_id:null,resource_kind:'TASK',resource_id:31,
   session_id:10,operation_type:'RESUME',idempotency_key:taskResume.key,expected_state_version:37,
   fixed_input,control_generation:4,status:'SUCCEEDED',created_at,started_at:created_at,
   ended_at:created_at,failure_code:null,content_capture:null,
   steps:['RECONCILE','CHECK_CONDITIONS','CONTINUE_OR_OBSERVE'].map((step_type,index)=>({
    operation_id:resumeOperationId,step_no:index+1,step_type,status:'SUCCEEDED',external_identity:null,
    fixed_input,started_at:created_at,ended_at:created_at,last_observed_at:created_at,result_ref:refs[index],
   }))};
 }
 function savedStart(failed,completed=false){
  const fixed_input={task_id:31,expected_state_version:1};
  const stages=['RESTORE_WORKSPACE','PREPARE_BASIS','CHECK_CONDITIONS','START_INSTANCE','CREATE_SESSION','SEND_INITIAL'];
  if(completed){
   const refs=[{workspace_id:19},{document_count:1},{fixed_content_verified:true,system_config_clear:true,capability_codes:[]},
    {instance_id:7},{session_id:8},{session_id:8}];
   return {id:91,task_id:31,testing_task_id:null,resource_kind:'TASK',resource_id:31,session_id:8,
    operation_type:'START',idempotency_key:taskStart.key,expected_state_version:1,fixed_input,
    control_generation:1,status:'SUCCEEDED',created_at,started_at:created_at,ended_at:created_at,
    failure_code:null,content_capture:null,
    steps:stages.map((step_type,index)=>({operation_id:91,step_no:index+1,step_type,status:'SUCCEEDED',
     external_identity:index===2?null:{},fixed_input,started_at:created_at,ended_at:created_at,
     last_observed_at:created_at,result_ref:refs[index]}))};
  }
  return {id:91,task_id:31,testing_task_id:null,resource_kind:'TASK',resource_id:31,session_id:null,
   operation_type:'START',idempotency_key:taskStart.key,expected_state_version:1,fixed_input,
   control_generation:1,status:failed?'FAILED':'PENDING',created_at:created_at,
   started_at:failed?created_at:null,ended_at:failed?created_at:null,failure_code:failed?'CONFIG_NOT_READY':null,
   content_capture:null,steps:stages.map((step_type,index)=>({operation_id:91,step_no:index+1,step_type,
    status:failed?(index<2?'SUCCEEDED':index===2?'FAILED':'PENDING'):'PENDING',
    external_identity:failed&&index<2?{}:null,fixed_input,
    started_at:failed&&index<3?created_at:null,ended_at:failed&&index<3?created_at:null,
    last_observed_at:failed&&index<3?created_at:null,
    result_ref:failed?(index===0?{workspace_id:19}:index===1?{document_count:1}:index===2?{
     fixed_content_verified:true,system_config_clear:true,capability_codes:['Q20-WINDOWS']
    }:null):null}))};
 }
 const stopAt='2026-11-07T00:15:00.000Z',cleanAt='2026-11-07T00:16:00.000Z';
 const stopStepNames=['BLOCK_NEW','REVOKE_GATEWAY','ABORT_IF_APPLICABLE','STOP_OWNED_ACTIVITY','RECONCILE_WRITES','CLEANUP'];
 function savedStop(finished){
  const owned=taskStop.inputVersion>=4,stopped=scenario==='task-stop-cleaning';
  const fixed_input={task_id:31,expected_state_version:taskStop.inputVersion};
  return {id:stopOperationId,task_id:31,testing_task_id:null,resource_kind:'TASK',resource_id:31,
   session_id:owned?8:null,operation_type:'TERMINATE',idempotency_key:taskStop.key,
   expected_state_version:taskStop.inputVersion,fixed_input,control_generation:2,
   status:finished?'SUCCEEDED':stopped?'RUNNING':'PENDING',created_at:stopAt,
   started_at:finished&&!owned?cleanAt:finished||stopped?stopAt:null,
   ended_at:finished?cleanAt:null,failure_code:null,content_capture:null,
   steps:stopStepNames.map((step_type,index)=>{
    const succeeded=finished||(stopped&&index<4);
    const at=succeeded?(owned&&index<4?stopAt:cleanAt):null;
    return {operation_id:stopOperationId,step_no:index+1,step_type,
     status:succeeded?'SUCCEEDED':'PENDING',external_identity:null,fixed_input,
     started_at:at,ended_at:at,last_observed_at:at,
     result_ref:finished&&index===3?{stop_observation_id:1,cleanup_observation_id:2}:null};
   })};
 }
 function taskAfterStop(finished){
  const task=taskSaved.view,owned=taskStop.inputVersion>=4;
  const stopped=finished||['task-stop-cleaning','task-runtime-cleaning','task-runtime-cleanup-unknown'].includes(scenario);
  const observed=finished?cleanAt:stopped?stopAt:owned?created_at:null;
  return {...task,status:finished?'TERMINATED':'STOPPING',phase:finished?'FINISHED':owned?'BACKEND':'PREPARING',
   state_version:taskStop.inputVersion+(finished?2:1),control_generation:2,stop_requested_at:stopAt,
   workspace_id:owned?19:null,active_session_id:owned&&!finished?8:null,started_at:owned?created_at:null,
   ended_at:finished?cleanAt:null,stopped_at:finished?cleanAt:null,last_observed_at:observed,
   updated_at:finished?cleanAt:stopAt,termination_operation_id:stopOperationId,
   runtime:{...task.runtime,stop_status:stopped?'VERIFIED':'REQUESTED',
    cleanup_status:finished?'VERIFIED':stopped&&owned?'CLEANING':'NOT_STARTED',
    environment_status:owned?'UNKNOWN':task.runtime.environment_status,
    activity_status:owned?'UNKNOWN':task.runtime.activity_status,
    active_process_count:stopped?0:null,observed_at:observed},
   active_operations:finished?[]:[{id:stopOperationId,operation_type:'TERMINATE',status:stopped?'RUNNING':'PENDING'}],
   available_actions:task.available_actions.map(({action})=>{
    const enabled=action==='RECONCILE'||(!finished&&action==='TERMINATE');
    return {action,enabled,related_id:action==='TERMINATE'?stopOperationId:null,
     reason_code:enabled?null:finished?'TASK_ENDED':'INVALID_STATE'};
   })};
 }
 const callPath=taskViewPath+'/model-calls',callId=77;
 const callSummary={
  id:callId,execution_session_id:8,operation_id:91,call_no:1,attempt_no:1,
  model_name:'deepseek-v2',protocol_version:'OC20-MODEL-1',call_purpose:'CODE',
  call_status:'CANCELLED',transport_status:'INTERRUPTED',capture_status:'INCOMPLETE',
  started_at:created_at,ended_at:stopAt,input_tokens:17,output_tokens:null,
  cached_tokens:0,duration_ms:123,usage_status:'PARTIAL',
 };
 const callDetail={
  ...callSummary,task_id:31,retry_of_llm_use_id:null,
  request_snapshot:{native_request:{model:'walle-code',messages:[{role:'user',content:'fixture prompt'}]},
   supplier_request:{model:'deepseek-v2'},model:{model_name:'deepseek-v2'},
   window:{task_id:31,execution_session_id:8,operation_id:91,control_generation:1,instance_id:2}},
  response_snapshot:{frames:[{seq:1,received_at:stopAt,frame_json:{kind:'DATA',text:'partial'},
   capture_status:'REDACTED'}],frame_count:1,captured_bytes:32,complete:false},
  finish_reason:null,provider_request_id:'opaque: 0012',error_code:'MODEL_RESULT_UNKNOWN',
  reservation_id:78,reservation_status:'UNKNOWN',reserved_cny:'0.001200',settled_cny:null,
  settlement_basis:null,
 };
 const server=createServer(async(request,response)=>{
  const url=new URL(request.url,'http://127.0.0.1');response.setHeader('Cache-Control','no-store');
  if(url.pathname==='/__scenario'){scenario=url.searchParams.get('state');response.end('ok');return;}
  if(url.pathname==='/__task-summary-reads'){
   response.setHeader('Content-Type','application/json');
   response.end(JSON.stringify(requests.filter(row=>row==='GET '+taskViewPath).length));return;
  }
  if(url.pathname.startsWith('/api/')){
   requests.push(request.method+' '+url.pathname);response.setHeader('Content-Type','application/json; charset=utf-8');
   if(request.method==='GET'&&url.pathname==='/api/v1/requirements'&&!['tasks','testing-plan-editor','testing-task-workspace'].includes(mode)){
    response.end(JSON.stringify({success:true,error:null,data:[],meta:{request_id:randomUUID(),
      pagination:{page:1,page_size:20,total:0,total_pages:0}}}));return;
   }

   const success=(data,status=200,pagination)=>{
    response.statusCode=status;
    response.end(JSON.stringify({success:true,error:null,data,meta:{request_id:randomUUID(),...(pagination?{pagination}:{})}}));
   };
   const list=(items)=>{
    const page=Number(url.searchParams.get('page')??1);
    success({items:items.slice((page-1)*20,page*20)},200,{page,page_size:20,total:items.length,total_pages:Math.ceil(items.length/20)});
   };


   if(['testing-settings','testing-plan-editor','testing-task-workspace'].includes(mode)){
    const fail=(status,code,message,details=null)=>{
     response.statusCode=status;
     response.end(JSON.stringify({success:false,data:null,error:{code,message,details},meta:{request_id:randomUUID()}}));
    };
    if(['testing-plan-editor','testing-task-workspace'].includes(mode)){
     if(request.method==='GET'&&url.pathname==='/api/v1/requirements'){
      list([{id:1,requirement_no:'REQ000001',title:'隔离编码需求',requirement_type:'NEW',status:'READY',updated_at:created_at}]);return;
     }
     if(request.method==='GET'&&url.pathname==='/api/v1/requirements/1'){success(taskDetail);return;}
     if(request.method==='GET'&&url.pathname==='/api/v1/documents/41/code-design-revisions'){
      list([{requirement_id:1,document_id:41,revision_id:24,version_no:1,is_current:false,
       confirmation_event_id:13,confirmed_at:created_at,eligible:true,reason_code:null}]);return;
     }
     if(request.method==='GET'&&url.pathname==='/api/v1/revisions/24'){
      const paragraph={block_id:1,block_type:'paragraph',section_path:[],
       created_by_type:'SYSTEM',created_source_type:'TEMPLATE',created_source_id:null,created_at,
       last_modified_by_type:'SYSTEM',last_modified_source_type:'TEMPLATE',last_modified_source_id:null,last_modified_at:created_at};
      success({...taskRevision,markdown_content:'固定设计原文。',
       block_state_json:{schema_version:1,next_block_id:2,blocks:[paragraph]}});return;
     }
     if(request.method==='GET'&&url.pathname===testPlansPath+'/2'){
      success({...plans[0],versions_count:draftAvailable?1:0});return;
     }
     if(request.method==='GET'&&url.pathname===testPlansPath+'/2/versions'){list(draftAvailable?[planVersion]:[]);return;}
     const creating=url.pathname===testPlansPath+'/2/versions',saving=url.pathname===testPlanVersionPath+'/11/draft';
     if(request.method==='POST'&&(creating||saving)){
      let raw='';for await(const chunk of request)raw+=chunk;
      const input=JSON.parse(raw),key=request.headers['idempotency-key'];
      draftWrites.push({key,input,path:url.pathname});
      if(creating&&!draftAvailable){
       draftAvailable=true;
       planVersion={...planVersion,...input.plan_content};
       success(planVersion,201);return;
      }
      if(saving&&scenario==='draft-conflict'){
       planVersion={...planVersion,state_version:2,unresolved_questions:['并行修改']};
       const details={task_id:null,current_state_version:2,related_operation_id:null,
        related_entity_kind:'PLAN',related_entity_id:11};
       draftConflictReceipt={key,error:{code:'VERSION_CONFLICT',message:'任务已更新，请重新核对',details}};
       fail(409,'VERSION_CONFLICT',draftConflictReceipt.error.message,details);return;
      }
      if(saving&&scenario==='draft-lost'&&input.expected_state_version===2){
       planVersion={...planVersion,...input.plan_content,state_version:3};
       draftReceipt={key,version:planVersion};
       response.writeHead(200,{'Content-Length':1000});response.write('{');
       setTimeout(()=>response.destroy(),100);return;
      }
      fail(500,'INTERNAL_ERROR','Unexpected Testing draft write');return;
     }
     if(request.method==='GET'&&url.pathname===testPlanVersionPath+'/11'&&['draft-history','draft-pack-recover','draft-pack-foreign','seal-lost','seal-running','seal-complete','references-error','references-ready'].includes(scenario)){
      success({...planVersion,status:'PUBLISHED',published_at:planVersion.created_at,state_version:4,unresolved_questions:[]});return;
     }
    }
    if(mode==='testing-task-workspace'){
     if(scenario.startsWith('testing-planning-')){
      const taskPath=taskTestingPath+'/1', done=scenario==='testing-planning-done';
      const draft=planModelWrites[0];
      if(request.method==='GET'&&url.pathname===taskPath){
       const original=taskTestingView(), running=Boolean(draft)&&!done;
       const enabled=scenario==='testing-planning-ready'&&!draft;
       success({...original,status:running?'PLANNING':'DRAFT',phase:'PLAN',control_generation:1,
        state_version:done?3:running?2:1,plan_version_id:null,test_pack_version_id:null,
        draft_plan_operation_id:draft?49:null,active_operation_id:running?49:null,
        draft_plan_result:done?{operation_id:49,plan_id:5,plan_version_id:11}:null,
        stop_requested_at:null,stopped_at:null,ended_at:null,termination_operation_id:null,
        available_actions:original.available_actions.map(row=>row.action==='DRAFT_PLAN'?
         {...row,enabled,reason_code:enabled?null:running?'TASK_STATE':'MODEL_NOT_READY'}:row)});
       return;
      }
      if(request.method==='GET'&&url.pathname===taskPath+'/operations'){list(draft?[planModelOperation(draft)]:[]);return;}
      if(request.method==='GET'&&url.pathname===taskPath+'/operations/49'&&draft){success(planModelOperation(draft));return;}
      if(request.method==='GET'&&url.pathname.startsWith(taskPath+'/operations/')){
       const original=executionWrites.find(row=>url.pathname===taskPath+'/operations/'+row.data.operation_id);
       if(original){success(executionOperation(original));return;}
      }
      if(request.method==='POST'&&url.pathname===taskPath+'/draft-plan'){
       let raw='';for await(const chunk of request)raw+=chunk;
       const input=JSON.parse(raw),key=request.headers['idempotency-key'];
       planModelWrites.push({input,key,data:{testing_task_id:1,operation_id:49,state_version:2}});
       response.writeHead(202,{'Content-Length':1000});response.write('{');
       setTimeout(()=>response.destroy(),100);return;
      }
     }
     if(scenario.startsWith('testing-execution-')){
      const taskPath=taskTestingPath+'/1';
      if(request.method==='GET'&&url.pathname===taskPath){success(executionTask());return;}
      if(request.method==='GET'&&url.pathname.startsWith(taskPath+'/operations')){
       const items=executionWrites.map(executionOperation);
       if(url.pathname===taskPath+'/operations')list(items);
       else{
        const row=items.find(item=>url.pathname===taskPath+'/operations/'+item.id);
        if(row)success(row);else fail(404,'NOT_FOUND','资源不存在');
       }
       return;
      }
      if(request.method==='POST'&&Object.keys(executionResults).some(action=>url.pathname===taskPath+'/'+action)){
       let raw='';for await(const chunk of request)raw+=chunk;
       const action=url.pathname.split('/').at(-1),input=JSON.parse(raw),key=request.headers['idempotency-key'];
       const data={testing_task_id:1,operation_id:executionResults[action],state_version:input.expected_state_version+Number(action==='run')};
       executionWrites.push({action,input,key,data});
       if(action==='run'){
        response.writeHead(202,{'Content-Length':1000});response.write('{');
        setTimeout(()=>response.destroy(),100);return;
       }
       success(data,202);return;
      }
     }
     if(scenario==='testing-stop-done')testingStopped=true;
     if(scenario.startsWith('testing-report')){
      const handoff=scenario.startsWith('testing-report-handoff');
      if(handoff&&request.method==='GET'&&url.pathname===taskViewPath){
       const base=taskView({design_revision_id:24,repository_id:23,base_snapshot_id:52,
        execution_profile_version_id:19,authorization_id:87,material_refs:[],
        target_branch:'refs/heads/main',budget_limit_cny:'0.125'});
       const data=startedTask(false,{},32,base);
       success({...data,status:'AWAITING_TESTING',phase:'TESTING',active_session_id:10,
        control_generation:3,current_candidate_id:scenario.endsWith('historical')?203:202,
        current_refs:{...data.current_refs,verification_id:72},
        runtime:{...data.runtime,activity_status:'QUIESCENT',active_process_count:1},
        available_actions:data.available_actions.map(item=>item.action==='REGISTER_DEFECT'
         ?{...item,enabled:true,reason_code:null}:item)});return;
      }
      if(handoff&&request.method==='POST'&&url.pathname===defectPath){
       let raw='';for await(const chunk of request)raw+=chunk;
       const data={defect_id:9,task_id:31,candidate_id:202};
       defectWrites.push({input:JSON.parse(raw),key:request.headers['idempotency-key'],data});
       response.writeHead(201,{'Content-Length':1000});response.write('{');
       setTimeout(()=>response.destroy(),80);return;
      }
      if(handoff&&request.method==='GET'&&url.pathname==='/api/v1/code-command-receipts'&&url.searchParams.get('path')===defectPath){
       const original=defectWrites.find(item=>item.key===url.searchParams.get('request_key'));
       if(!original){fail(404,'NOT_FOUND','资源不存在');return;}
       success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:201,
        original_outcome:{success:true,data:original.data,error:null},task_id:31,testing_task_id:null,operation_id:null});return;
      }
      const reportTask=taskTestingPath+'/1',verificationPath=reportTask+'/verifications/32';
      const verifyReasons=['REQUIRED_NOT_PASSED'];
      if(request.method==='GET'&&url.pathname===reportTask){
       const original=taskTestingView();
       success({...original,...(handoff?{target_kind:'CANDIDATE',candidate_id:202,snapshot_id:null}:{}),status:'COMPLETED',phase:'FINISHED',current_verification_id:32,report_id:17,
        plan_version_id:11,test_pack_version_id:29,stop_requested_at:null,stopped_at:null,termination_operation_id:null});return;
      }
      if(request.method==='GET'&&url.pathname===reportTask+'/model-calls'){
       list(scenario==='testing-report-usage-empty'?[]:[{id:58,testing_task_id:1,operation_id:51,call_no:1,attempt_no:1,
        function_type:'TEST_PLAN_DRAFT',model_name:'固定测试模型',call_status:'FAILED',parse_status:'FAILED',
        validation_status:'PENDING',started_at:created_at,ended_at:created_at,input_tokens:0,output_tokens:null,
        usage_status:'PARTIAL',provider_request_id:null}]);return;
      }
      if(request.method==='GET'&&url.pathname===reportTask+'/model-calls/58'){
       success({id:58,testing_task_id:1,operation_id:51,call_no:1,attempt_no:1,function_type:'TEST_PLAN_DRAFT',
        model_name:'固定测试模型',call_status:'FAILED',parse_status:'FAILED',validation_status:'PENDING',
        started_at:created_at,ended_at:created_at,input_tokens:0,output_tokens:null,usage_status:'PARTIAL',provider_request_id:null,
        request_snapshot:{request:{model:'fixed-model'}},response_snapshot:null,parsed_output:null,trusted_output:null,
        reservation_id:9,reserved_cny:'0.125000',settled_cny:null,settlement_basis:null});return;
      }
      if(request.method==='GET'&&url.pathname===reportTask+'/report'){
       const original=taskTestingView(),reasons=['RESULT_NOT_PASSED'];
       if(scenario==='testing-report-revoked')reasons.push('TEST_ASSET_REVOKED');
       success({id:17,testing_task_id:1,verification_id:32,plan_version_id:11,test_pack_version_id:29,
        input_fingerprint:sealHash,result:'FAILED',scope_stages:['ACCEPTANCE'],manual_coverage_ids:['manual'],
        uncovered_behavior_ids:[],created_at,eligible:false,delivery_eligible:false,ineligibility_reason_codes:reasons,
        delivery_ineligibility_reason_codes:[...reasons,...(handoff?[]:['NOT_CODING_CANDIDATE']),'NOT_ACCEPTANCE'],
        provenance:{requirement_id:1,document_id:41,design_revision_id:24,material_refs:[],
         target_kind:handoff?'CANDIDATE':'SNAPSHOT',candidate_id:handoff?202:null,snapshot_id:handoff?null:25,profile_version_id:original.profile_version_id,
         purpose:original.purpose,source_code_task_id:handoff?31:null}});return;
      }
      if(request.method==='GET'&&url.pathname===reportPath+'/findings'){
       if(scenario==='testing-report-findings-error'){fail(503,'STORAGE_UNAVAILABLE','暂时无法读取数据',{capability_codes:['DATABASE']});return;}
       list([findingView()]);return;
      }
      if(request.method==='POST'&&url.pathname===findingPath){
       let raw='';for await(const chunk of request)raw+=chunk;
       reviewRecord={key:request.headers['idempotency-key'],input:JSON.parse(raw)};
       findingWrites.push(reviewRecord);
       response.writeHead(200,{'Content-Length':1000});response.write('{');
       setTimeout(()=>response.destroy(),100);return;
      }
      if(request.method==='GET'&&url.pathname===verificationPath){
       const item={id:62,verification_id:32,check_id:'controlled-1',required:true,check_kind:'CONTROLLED_ASSERTION',
        evidence_kind:'CONTROLLED_CASES',command_execution_id:null,result:'FAILED',reason_code:'ASSERTION_FAILED',
        expected_case_count:2,executed_case_count:1,passed_case_count:0,failed_case_count:1,reused_from_item_id:null,
        evidence_summary:null,started_at:created_at,ended_at:created_at};
       const integrity={...item,id:61,check_id:'content-integrity',evidence_kind:'CONTENT_INTEGRITY',result:'PASSED',
        reason_code:null,expected_case_count:null,executed_case_count:null,passed_case_count:null,failed_case_count:null};
       success({id:32,task_id:null,owner_kind:'TESTING',testing_task_id:1,candidate_id:null,snapshot_id:25,
        purpose:'DIAGNOSTIC',role:null,check_set_version_id:41,profile_version_id:null,testing_profile_version_id:1,
        environment_record_id:56,operation_id:45,scope_stages:['ACCEPTANCE'],selected_check_ids:['content-integrity','controlled-1'],
        status:'FINISHED',stop_status:'VERIFIED',cleanup_status:'VERIFIED',source_integrity_status:'VERIFIED',
        created_at,ended_at:created_at,backend_handoff_operation_id:null,frontend_handoff_operation_id:null,items:[integrity,item],
        environment_record:{id:56,task_id:null,testing_task_id:1,runtime_refs:['runtime:test'],dependency_refs:[],runner_refs:[],
         effective_config_application_id:null,testing_profile_version_id:1,check_resource_refs:[],scope_key:sealHash,observed_at:created_at},
        eligible:false,ineligibility_reason_codes:verifyReasons});return;
      }
      if(request.method==='GET'&&url.pathname===verificationPath+'/items/62/cases'){
       list([{case_id:'public',name:'原受控用例',result:'FAILED',expected_assertion_count:2,passed_assertion_count:0,
        failed_assertion_count:1,capture_status:'INCOMPLETE',summary:'已记录失败断言，部分证据缺失。',observed_at:created_at}]);return;
      }
     }
     if(request.method==='GET'&&url.pathname==='/api/v1/code-snapshots/25'){
      success({id:25,repository_id:23,registration_operation_id:81,content_profile_version_id:5,
       commit_oid:'1'.repeat(40),content_tree_oid:'2'.repeat(40),content_policy_version:'GIT20-BASELINE-1',
       registered_at:created_at,created_at,ready:true,reason_codes:[]});return;
     }
     if(request.method==='GET'&&url.pathname===taskTestingPath){
      if(scenario==='testing-task-read-error'){fail(503,'STORAGE_UNAVAILABLE','暂时无法读取数据',{capability_codes:['DATABASE']});return;}
      const keys=['id','requirement_id','document_id','target_kind','candidate_id','snapshot_id','purpose','status','phase','created_at','report_id'];
      const record=testingTaskDraft?Object.fromEntries(Object.entries(taskTestingView()).filter(([key])=>keys.includes(key))):null;
      list(record&&Object.entries(record).every(([key,value])=>!url.searchParams.has(key)||String(value)===url.searchParams.get(key))?[record]:[]);return;
     }
     if(request.method==='GET'&&url.pathname===taskTestingPath+'/1'&&testingTaskDraft){success(taskTestingView());return;}
     if(request.method==='GET'&&url.pathname.startsWith(taskTestingPath+'/')&&url.pathname!==taskTestingPath+'/1'&&!url.pathname.includes('/operations')){
      fail(404,'NOT_FOUND','资源不存在');return;
     }
     if(request.method==='POST'&&url.pathname===taskTestingPath){
      let raw='';for await(const chunk of request)raw+=chunk;
      const input=JSON.parse(raw),key=request.headers['idempotency-key'];
      testingTaskDraft={key,input};testingTaskWrites.push(testingTaskDraft);
      response.writeHead(201,{'Content-Length':1000});response.write('{');
      setTimeout(()=>response.destroy(),100);return;
     }
     if(request.method==='POST'&&url.pathname===taskTestingPath+'/1/terminate'){
      let raw='';for await(const chunk of request)raw+=chunk;
      testingStopKey=request.headers['idempotency-key'];testingStopWrites.push(JSON.parse(raw));
      success(testingStopResult,202);return;
     }
     if(request.method==='GET'&&url.pathname.startsWith(taskTestingPath+'/1/operations')){
      if(!testingStopKey){list([]);return;}
      if(![taskTestingPath+'/1/operations',taskTestingPath+'/1/operations/37'].includes(url.pathname)){
       fail(404,'NOT_FOUND','资源不存在');return;
      }
      const expected={expected_state_version:1};
      const original={id:37,task_id:null,testing_task_id:1,resource_kind:'TESTING_TASK',resource_id:1,
       session_id:null,operation_type:'TERMINATE',idempotency_key:testingStopKey,expected_state_version:1,
       fixed_input:expected,control_generation:2,status:testingStopped?'SUCCEEDED':'RUNNING',
       created_at,started_at:created_at,ended_at:testingStopped?created_at:null,failure_code:null,content_capture:null,
       steps:['FENCE','STOP_OWN_ACTIVITIES','VERIFY_STOP','CLEANUP','SAVE_TERMINATED'].map((step_type,index)=>{
        const done=testingStopped||index===0;
        return {operation_id:37,step_no:index+1,step_type,status:done?'SUCCEEDED':'PENDING',external_identity:null,
         fixed_input:expected,result_ref:testingStopped&&index===1?{stop_observation_id:8,cleanup_observation_id:9}:null,
         started_at:done?created_at:null,ended_at:done?created_at:null,last_observed_at:done?created_at:null};
       })};
      if(url.pathname.endsWith('/37'))success(original);else list([original]);
      return;
     }
    }
    if(request.method==='GET'&&url.pathname==='/api/v1/testing-reference-sets'){
     if(scenario==='references-error'){fail(503,'STORAGE_UNAVAILABLE','暂时无法读取数据',{capability_codes:['DATABASE']});return;}
     list(scenario==='references-ready'?[{reference_set_ref:'reference:ready',basis_fingerprint:'f'.repeat(64),positive_count:1,
      negative_count:2,repeat_count:3,ready:false,reason_codes:['CONTENT_NOT_READY']}]:[]);return;
    }
    if(request.method==='GET'&&url.pathname===testPlansPath){
     if(scenario==='plan-list-error'){
      fail(503,'STORAGE_UNAVAILABLE','暂时无法读取数据',{capability_codes:['DATABASE']});return;
     }
     list(plans);return;
    }
    if(request.method==='POST'&&url.pathname===testPlansPath){
     let raw='';for await(const chunk of request)raw+=chunk;
     const key=request.headers['idempotency-key'],input=JSON.parse(raw);
     planWrites.push({key,input});
     plans.push({id:2,name:input.name,created_at:testingTime,versions_count:0});
     success({plan_id:2},201);return;
    }
    if(request.method==='GET'&&url.pathname===testPlansPath+'/2'){
     success({...plans[0],versions_count:scenario.startsWith('plan-version')||scenario==='plan-foreign'?1:0});return;
    }
    if(request.method==='GET'&&url.pathname===testPlansPath+'/2/versions'){
     list(scenario.startsWith('plan-version')||scenario==='plan-foreign'?[planVersion]:[]);return;
    }
    if(request.method==='POST'&&[testPlanVersionPath+'/11/publish',testPlanVersionPath+'/11/revoke'].includes(url.pathname)){
     let raw='';for await(const chunk of request)raw+=chunk;
     const key=request.headers['idempotency-key'],input=JSON.parse(raw),publish=url.pathname.endsWith('/publish');
     if(input.expected_state_version!==planVersion.state_version){
      fail(500,'INTERNAL_ERROR','Unexpected plan version');return;
     }
     planWrites.push({key,input,path:url.pathname});
     if(publish){
      planVersion={...planVersion,state_version:2,status:'PUBLISHED',published_at:'2026-11-10T00:01:00.000Z'};
      success(planVersion);return;
     }
     planVersion={...planVersion,state_version:3,status:'REVOKED',revoked_at:'2026-11-10T00:02:00.000Z',revocation_reason:input.reason};
     planControlReceipt={key,version:planVersion};
     response.writeHead(200,{'Content-Length':1000});response.write('{');
     setTimeout(()=>response.destroy(),100);return;
    }
    if(request.method==='GET'&&url.pathname===testPlanVersionPath+'/11/packs'){list(packSaved?[packSaved]:[]);return;}
    if(mode==='testing-plan-editor'&&request.method==='POST'&&url.pathname===testPlanVersionPath+'/11/packs'){
     let raw='';for await(const chunk of request)raw+=chunk;
     packWrites.push(JSON.parse(raw));
     packKey=request.headers['idempotency-key'];
     packSaved={id:29,plan_version_id:11,version:1,check_set_version_id:null,sha256:null,status:'DRAFT',validation_id:null,state_version:1,
      created_at:planVersion.created_at,published_at:null,revoked_at:null,revocation_reason:null,ready:false,reason_codes:['PACK_NOT_SEALED']};
     response.writeHead(201,{'Content-Length':1000});response.write('{');
     setTimeout(()=>response.destroy(),100);return;
    }
    if(mode==='testing-plan-editor'&&request.method==='GET'&&url.pathname==='/api/v1/test-pack-versions/29'&&packSaved){
     success(scenario==='draft-pack-foreign'?{...packSaved,plan_version_id:12}:packSaved);return;
    }
    if(mode==='testing-plan-editor'&&request.method==='POST'&&url.pathname==='/api/v1/test-pack-versions/29/seal'){
     let raw='';for await(const chunk of request)raw+=chunk;
     sealKey=request.headers['idempotency-key'];sealWrites.push(JSON.parse(raw));
     response.writeHead(202,{'Content-Length':1000});response.write('{');
     setTimeout(()=>response.destroy(),100);return;
    }
    if(mode==='testing-plan-editor'&&request.method==='GET'&&url.pathname==='/api/v1/testing-operations/34'&&sealKey){
     const at=planVersion.created_at,fixed={expected_state_version:1},complete=scenario==='seal-complete'||packSaved.status==='SEALED';
     if(complete)packSaved={...packSaved,check_set_version_id:38,sha256:sealHash,status:'SEALED',state_version:2,reason_codes:['PACK_NOT_PUBLISHED','REFERENCE_SET_NOT_REGISTERED']};
     success({id:34,task_id:null,testing_task_id:null,resource_kind:'TEST_PACK_VERSION',resource_id:29,
      session_id:null,operation_type:'SEAL_PACK',idempotency_key:sealKey,expected_state_version:1,
      fixed_input:fixed,control_generation:null,status:complete?'SUCCEEDED':'RUNNING',created_at:at,
      started_at:at,ended_at:complete?at:null,failure_code:null,content_capture:null,
      steps:['VALIDATE_PLAN','COMPILE','SEAL','SAVE_PACK'].map((type,index)=>{
       const done=complete||index<2,pending=!complete&&index===3;
       const results=[{plan_version_id:11},{sha256:sealHash},{sha256:sealHash},
        {test_pack_version_id:29,check_set_version_id:38}];
       return {operation_id:34,step_no:index+1,step_type:type,status:done?'SUCCEEDED':pending?'PENDING':'RUNNING',
        external_identity:null,fixed_input:fixed,result_ref:done?results[index]:null,
        started_at:pending?null:at,ended_at:done?at:null,last_observed_at:pending?null:at};
      })});return;
    }
    if(request.method==='GET'&&url.pathname===testPlanVersionPath+'/11'){
     success(scenario==='plan-foreign'?{...planVersion,plan_id:3}:planVersion);return;
    }
    if(request.method==='GET'&&url.pathname===testingProfilePath){
     if(scenario==='testing-list-error'){
      fail(503,'STORAGE_UNAVAILABLE','暂时无法读取数据',{capability_codes:['DATABASE']});return;
     }
     const name=url.searchParams.get('name');
     list(testingProfiles.filter(row=>name===null||row.name===name));return;
    }
    if(request.method==='GET'&&url.pathname.startsWith(testingProfilePath+'/')){
     const row=testingProfiles.find(row=>url.pathname===testingProfilePath+'/'+row.id);
     if(row)success(row);else fail(404,'NOT_FOUND','资源不存在');
     return;
    }
    if(request.method==='GET'&&url.pathname==='/api/v1/code-configuration-options'){
     const kind=url.searchParams.get('kind'),value=testingOptions[kind];
     list(scenario==='testing-no-resources'||!value?[]:[{kind,option_id:'fixture:'+kind,label:testingLabels[kind],
      ready:false,unresolved_capability_codes:['Q20-CHECKS'],value}]);return;
    }
    if(request.method==='POST'&&[testingProfilePath,testingAuthPath].includes(url.pathname)){
     let raw='';for await(const chunk of request)raw+=chunk;
     const input=JSON.parse(raw),key=request.headers['idempotency-key'];
     testingWrites.push({path:url.pathname,input,key});
     if(url.pathname===testingProfilePath){
      const row={id:1,version:1,created_at:testingTime,...input.profile_content,ready:false,reason_codes:['Q20-CHECKS']};
      testingProfiles.push(row);success(row,201);
     }else if(mode==='testing-task-workspace'){
      testingAuthorization={key,row:{id:7,testing_task_id:null,profile_version_id:1,scope_kind:'TASK',
       validation_id:null,status:'APPROVED_UNBOUND',budget_limit_cny:'0.000000',actor_ref:'fixture-actor',
       approved_at:testingTime,ready:false,reason_codes:['Q20-CHECKS']}};
      success(testingAuthorization.row,201);
     }else{
      testingAuthorization={key,row:{id:7,testing_task_id:null,profile_version_id:1,scope_kind:'PACK_VALIDATION',
       validation_id:null,status:'APPROVED_UNBOUND',budget_limit_cny:'0.000000',actor_ref:'fixture-actor',
       approved_at:testingTime,ready:false,reason_codes:['Q20-CHECKS']}};
      response.writeHead(201,{'Content-Length':1000});response.write('{');
      setTimeout(()=>response.destroy(),100);
     }
     return;
    }
    if(request.method==='GET'&&url.pathname==='/api/v1/testing-command-receipts'){
     const found=scenario==='testing-auth-recover'&&testingAuthorization?.key===url.searchParams.get('request_key');
     const association={task_id:null,testing_task_id:null,operation_id:null};
     if(mode==='testing-task-workspace'&&scenario==='testing-task-recover'&&testingTaskDraft?.key===url.searchParams.get('request_key')){
      success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:201,
       original_outcome:{success:true,data:testingTaskResult,error:null},...association,testing_task_id:1});return;
     }
     if(scenario==='testing-report-recover'&&reviewRecord?.key===url.searchParams.get('request_key')){
      success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:200,
       original_outcome:{success:true,data:findingView(),error:null},...association});return;
     }
     if(scenario==='testing-report-review-lost'&&reviewRecord?.key===url.searchParams.get('request_key')){
      success({lookup_status:'UNKNOWN',record_status:'PROCESSING',original_http_status:null,original_outcome:null,...association});return;
     }
     const plan=planModelWrites.find(row=>row.key===url.searchParams.get('request_key'));
     if(mode==='testing-task-workspace'&&plan){
      if(scenario==='testing-planning-ready'){
       success({lookup_status:'UNKNOWN',record_status:'PROCESSING',original_http_status:null,original_outcome:null,...association});return;
      }
      success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:202,
       original_outcome:{success:true,data:plan.data,error:null},...association,testing_task_id:1,operation_id:49});return;
     }
     const execution=executionWrites.find(row=>row.key===url.searchParams.get('request_key'));
     if(mode==='testing-task-workspace'&&execution){
      if(execution.action==='run'&&scenario==='testing-execution-ready'){
       success({lookup_status:'UNKNOWN',record_status:'PROCESSING',original_http_status:null,original_outcome:null,...association});return;
      }
      success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:202,
       original_outcome:{success:true,data:execution.data,error:null},...association,testing_task_id:1,operation_id:execution.data.operation_id});return;
     }
     if(mode==='testing-task-workspace'&&testingStopKey===url.searchParams.get('request_key')){
      success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:202,
       original_outcome:{success:true,data:testingStopResult,error:null},...association,testing_task_id:1,operation_id:37});return;
     }
     if(draftConflictReceipt?.key===url.searchParams.get('request_key')){
      success({lookup_status:'FOUND',record_status:'REJECTED',original_http_status:409,
       original_outcome:{success:false,data:null,error:draftConflictReceipt.error},...association});return;
     }
     if(['seal-running','seal-complete'].includes(scenario)&&sealKey===url.searchParams.get('request_key')){
      success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:202,
       original_outcome:{success:true,data:sealReceipt,error:null},...association,operation_id:34});return;
     }
     if(scenario==='draft-pack-recover'&&packKey===url.searchParams.get('request_key')){
      success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:201,
       original_outcome:{success:true,data:{test_pack_version_id:29},error:null},...association});return;
     }
     if(scenario==='draft-recover'&&draftReceipt?.key===url.searchParams.get('request_key')){
      success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:200,
       original_outcome:{success:true,data:draftReceipt.version,error:null},...association});return;
     }
     if(scenario==='plan-version-recover'&&planControlReceipt?.key===url.searchParams.get('request_key')){
      success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:200,
       original_outcome:{success:true,data:planControlReceipt.version,error:null},...association});return;
     }
     success(found?{lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:201,
      original_outcome:{success:true,data:testingAuthorization.row,error:null},...association}:
      {lookup_status:'NOT_FOUND',record_status:null,original_http_status:null,original_outcome:null,...association});
     return;
    }
    if(request.method==='GET'&&url.pathname===testingAuthPath+'/7'&&testingAuthorization){
     success(testingAuthorization.row);return;
    }
    if(request.method==='GET'&&url.pathname.startsWith(testingAuthPath+'/')){
     fail(404,'NOT_FOUND','资源不存在');return;
    }
    if(request.method==='GET'&&url.pathname==='/api/v1/code-repositories'){
     list([]);return;
    }
    fail(500,'INTERNAL_ERROR','Unexpected isolated testing settings request');return;
   }

   if(mode==='tasks'||mode==='role-reconciliation'||repairReconciliation){
    const fail=(status,code,message,details=null)=>{
     response.statusCode=status;
     response.end(JSON.stringify({success:false,data:null,error:{code,message,details},meta:{request_id:randomUUID()}}));
    };
    const bodyRequest=(receive)=>{let body='';request.on('data',part=>body+=part);request.on('end',()=>{
     const key=request.headers['idempotency-key'];
     if(typeof key!=='string'){fail(500,'INTERNAL_ERROR','Missing original key');return;}
     receive(key,JSON.parse(body));
    });};
    const taskRepo=23,base=52,observationId=45,profileId=19,authorizationId=87;
    const repoPath='/api/v1/code-repositories/'+taskRepo;
    if(request.method==='GET'&&url.pathname==='/api/v1/requirements'){
     const {id,requirement_no,title,requirement_type,status,updated_at}=taskReq;
     list([{id,requirement_no,title,requirement_type,status,updated_at}]);return;
    }
    if(request.method==='GET'&&url.pathname==='/api/v1/requirements/1/current-document'){
     if(url.searchParams.get('document_id')==='41')success(taskDocument);
     else fail(404,'NOT_FOUND','当前文档不存在');
     return;
    }
    if(request.method==='GET'&&url.pathname==='/api/v1/requirements/1'){success(taskDetail);return;}
    if(request.method==='GET'&&url.pathname==='/api/v1/requirements/1/comment-index'){
     success({requirement_id:1,document_id:41,content_version:2,total_count:0,open_count:0,blocks:[],comments:[]});return;
    }
    if(request.method==='GET'&&url.pathname==='/api/v1/requirements/1/messages'){
     success({items:[]},200,{has_more:false,next_cursor:null});return;
    }
    if(request.method==='GET'&&url.pathname==='/api/v1/requirements/1/guide-runs'){list([]);return;}
    if(request.method==='GET'&&url.pathname==='/api/v1/requirements/1/revisions'){list([recentTaskRevision,taskRevision]);return;}
    if(request.method==='GET'&&url.pathname==='/api/v1/revisions/24'){
     const answering=scenario==='task-native-issues-answer'||scenario.startsWith('task-publication-defect');
     const paragraph={block_id:1,block_type:'paragraph',section_path:[],
      created_by_type:'SYSTEM',created_source_type:'TEMPLATE',created_source_id:null,created_at,
      last_modified_by_type:'SYSTEM',last_modified_source_type:'TEMPLATE',last_modified_source_id:null,last_modified_at:created_at};
     success({...taskRevision,markdown_content:answering?'固定设计原文。':'',
      block_state_json:{schema_version:1,next_block_id:answering?2:1,blocks:answering?[paragraph]:[]}});return;
    }
    if(request.method==='GET'&&url.pathname==='/api/v1/documents/41/code-design-revisions'){
     const choice={requirement_id:1,document_id:41};
     list([
      {...choice,revision_id:25,version_no:2,is_current:true,confirmation_event_id:null,confirmed_at:null,eligible:false,reason_code:'UNCONFIRMED'},
      {...choice,revision_id:24,version_no:1,is_current:false,confirmation_event_id:11,confirmed_at:created_at,eligible:true,reason_code:null},
     ]);return;
    }

    if(request.method==='POST'&&url.pathname===startPath){
     bodyRequest((key,input)=>{
      startWrites.push({key,input});
      if(!taskSaved||input.expected_state_version!==1||taskStart){
       fail(500,'INTERNAL_ERROR','Unexpected new start request');return;
      }
      taskStart={key,data:{task_id:31,operation_id:91,operation_status:'PENDING',task_status:'PENDING',state_version:2}};
      response.writeHead(202,{'Content-Length':1000});response.write('{');
      setTimeout(()=>response.destroy(),80);
     });return;
    }
    if(request.method==='GET'&&url.pathname==='/api/v1/code-operations/91'&&taskStart){
     success(savedStart(scenario==='task-conditions-blocked',scenario==='task-start-completed'));return;
    }
    if(request.method==='POST'&&url.pathname===budgetPath){
     bodyRequest((key,input)=>{
      budgetWrites.push({key,input});
      if(!taskSaved||!taskStart||taskBudget||scenario!=='task-model-waiting'||
        input.expected_state_version!==5||input.new_budget_limit_cny!=='0.25'||input.reason!=='继续原模型工作'){
       fail(500,'INTERNAL_ERROR','Unexpected new budget request');return;
      }
      const data=startedTask(true,{limit_cny:'0.250000',available_cny:'0.250000'},6);
      taskBudget={key,data};
      taskSaved.view={...taskSaved.view,budget:data.budget};
      response.writeHead(200,{'Content-Length':1000});response.write('{');
      setTimeout(()=>response.destroy(),80);
     });return;
    }
    if(request.method==='POST'&&url.pathname===resumePath){
     bodyRequest((key,input)=>{
      resumeWrites.push({key,input});
      if(codingDelivery&&scenario==='task-delivery-cleanup'){
       if(taskResume||input.expected_state_version!==37||input.operation_id!==111||
        JSON.stringify(input.waiting_item_ids)!=='[30]'||Object.keys(input).length!==3){
        fail(500,'INTERNAL_ERROR','Unexpected original cleanup resume');return;
       }
       taskResume={key,input,data:{task_id:31,operation_id:resumeOperationId,operation_status:'PENDING',
        task_status:'WAITING',state_version:38}};
       response.writeHead(202,{'Content-Length':1000});response.write('{');
       setTimeout(()=>response.destroy(),80);return;
      }
      if(!taskBudget||taskResume||scenario!=='task-model-waiting'||input.expected_state_version!==6||
        input.operation_id!==91||JSON.stringify(input.waiting_item_ids)!=='[1]'){
       fail(500,'INTERNAL_ERROR','Unexpected new resume request');return;
      }
      taskResume={key,input,data:{task_id:31,operation_id:resumeOperationId,operation_status:'PENDING',
       task_status:'WAITING',state_version:7}};
      response.writeHead(202,{'Content-Length':1000});response.write('{');
      setTimeout(()=>response.destroy(),80);
     });return;
    }
    if(request.method==='GET'&&url.pathname==='/api/v1/code-operations/'+resumeOperationId&&taskResume){
     success(codingDelivery&&scenario==='task-delivery-cleanup'
      ?savedDeliveryCleanupResume():savedResume(scenario!=='task-model-waiting'));return;
    }
    if(request.method==='POST'&&url.pathname===answerPath){
     bodyRequest((key,input)=>{
      answerWrites.push({key,input});
      const [first,second]=input.answers??[];
      if(taskAnswer||scenario!=='task-native-issues-answer'||input.expected_state_version!==9||input.session_id!==8||
        input.answers.length!==2||first.index!==0||first.action!=='CITE_FIXED_BASIS'||first.clarification!==null||
        first.basis_refs?.length!==1||first.basis_refs[0].document_id!==41||
        first.basis_refs[0].revision_id!==24||first.basis_refs[0].quote!=='固定设计原文。'||
        second.index!==1||second.action!=='CLARIFY_FACTS'||second.clarification?.text!=='隔离浏览器补充的原问题事实'){
       console.log('ANSWER_FIXTURE_MISMATCH',scenario,input.expected_state_version,input.session_id,input.answers?.map(item=>item.action));
       fail(500,'INTERNAL_ERROR','Unexpected original answer request');return;
      }
      taskAnswer={key,input,data:{task_id:31,operation_id:answerId,operation_status:'PENDING',task_status:'WAITING',state_version:10}};
      response.writeHead(202,{'Content-Length':1000});response.write('{');
      setTimeout(()=>response.destroy(),80);
     });return;
    }
    if(request.method==='POST'&&url.pathname===handoffWritePath){
     bodyRequest((key,input)=>{
      handoffWrites.push({key,input});
      if(taskHandoff||input.expected_state_version!==12||input.target_document_id!==41||
        JSON.stringify(input.evidence_refs)!=='[{"kind":"OPERATION","id":91}]'){
       fail(500,'INTERNAL_ERROR','Unexpected original handoff input');return;
      }
      taskHandoff={key,input,data:{handoff_id:17,task_id:31,question_id:4,target_document_id:41}};
      response.writeHead(201,{'Content-Length':1000});response.write('{');
      setTimeout(()=>response.destroy(),80);
     });return;
    }
    if(request.method==='POST'&&url.pathname===handoffLinkPath){
     bodyRequest((key,input)=>{
      handoffLinkWrites.push({key,input});
      if(taskHandoffLink||input.expected_state_version!==13||input.kind!=='REVISION_LINKED'||
        input.revision_id!==24||input.guide_run_id!==null||input.message_id!==null){
       fail(500,'INTERNAL_ERROR','Unexpected original handoff link input');return;
      }
      taskHandoffLink={key,input,data:{handoff_event_id:2,handoff_id:17}};
      success(taskHandoffLink.data,201);
     });return;
    }
    if(request.method==='GET'&&url.pathname===handoffReadPath&&taskHandoff){
     const eventBase={handoff_id:17,guide_run_id:null,message_id:null,revision_id:null,created_at};
     const page=Number(url.searchParams.get('page')??1);
     const events=[...(taskHandoffLink?[{...eventBase,id:2,kind:'REVISION_LINKED',revision_id:24}]:[]),
       {...eventBase,id:1,kind:'PREPARED'}];
     success({id:17,task_id:31,question_id:4,target_document_id:41,operation_id:95,created_at,
      evidence_refs:taskHandoff.input.evidence_refs,source_question:handoffQuestion(),
      events:page===1?events:[]},200,{page,page_size:20,total:events.length,total_pages:1});return;
    }
    if(request.method==='POST'&&url.pathname===permissionPath){
     bodyRequest((key,input)=>{
      permissionWrites.push({key,input});
      if(taskPermission||scenario!=='task-native-permission'||input.expected_state_version!==14||
        input.session_id!==8||input.decision!=='DENY'){
       fail(500,'INTERNAL_ERROR','Unexpected original permission request');return;
      }
      taskPermission={key,input,data:{task_id:31,operation_id:permissionId,operation_status:'PENDING',
       task_status:'WAITING',state_version:15}};
      response.writeHead(202,{'Content-Length':1000});response.write('{');
      setTimeout(()=>response.destroy(),80);
     });return;
    }
    if(request.method==='POST'&&url.pathname===stopPath){
     bodyRequest((key,input)=>{
      stopWrites.push({key,input});
      if(!taskSaved||input.expected_state_version!==(taskPermission?16:taskAnswer?11:taskResume?8:taskBudget?6:4)||taskStop){
       fail(500,'INTERNAL_ERROR','Unexpected new stop request');return;
      }
      taskStop={key,inputVersion:input.expected_state_version,data:{task_id:31,operation_id:stopOperationId,operation_status:'PENDING',task_status:'STOPPING',state_version:input.expected_state_version+1}};
      if(scenario==='task-stop-lost'){
       response.writeHead(202,{'Content-Length':1000});response.write('{');
       setTimeout(()=>response.destroy(),80);
      }else success(taskStop.data,202);
     });return;
    }
    if(request.method==='GET'&&url.pathname==='/api/v1/code-operations/'+stopOperationId&&taskStop){
     success(savedStop(scenario==='task-stop-verified'));return;
    }
    const issuePath=taskViewPath+'/';
    if(request.method==='GET'&&[issuePath+'questions',issuePath+'permissions'].includes(url.pathname)){
     if(scenario==='task-native-issues-error'){fail(503,'STORAGE_UNAVAILABLE','数据暂时无法访问，请稍后核对',{capability_codes:['DATABASE']});return;}
     const question=url.pathname.endsWith('/questions'),id=question?1:2;
     if(question&&scenario==='task-native-handoff'){
      list([handoffQuestion()]);return;
     }
     if(!question&&scenario.startsWith('task-native-permission')){
      const partial=scenario==='task-native-permission-partial';
      const entries=[3,2].map((id)=>{
       const status=partial?(id===2?'REJECTED':'UNKNOWN'):taskPermission?'ANSWERING':'OPEN';
       return {id,task_id:31,session_id:8,instance_id:7,control_generation:1,status,observed_at:created_at,
        resolved_at:status==='REJECTED'?created_at:null,native_permission_id:'per_fixture'+id,
        tool_name:id===2?'bash':'read',patterns:[id===2?'echo fixture':'src/main.ts'],
        object_refs:id===2?[]:[{kind:'WORKSPACE_PATH',path:'src/main.ts'}],
        requested_action:id===2?'EXECUTE':'READ',tool_ref:null,
        available_actions:['ALLOW_ONCE','DENY'].map((action)=>{
         const enabled=status==='OPEN'&&(action==='DENY'||id===3);
         return {action,enabled,related_id:id,reason_code:enabled?null:status==='OPEN'?'PERMISSION_NOT_GRANTED':
           status==='REJECTED'?'QUESTION_NOT_OPEN':'EXTERNAL_RESULT_UNKNOWN'};
        })};
      });
      list(entries.filter((item)=>!url.searchParams.has('status')||item.status===url.searchParams.get('status')));return;
     }
     const done=scenario==='task-native-issues-answer-done';
     const status=question&&taskAnswer?(done?'RESOLVED':'ANSWERING'):scenario==='task-native-issues-unknown'?'UNKNOWN':'OPEN';
     if((url.searchParams.has('status')&&url.searchParams.get('status')!==status)||
       scenario==='task-native-issues-empty'){list([]);return;}
     const available_actions=(question?['ANSWER_QUESTION','PREPARE_HANDOFF']:['ALLOW_ONCE','DENY'])
      .map(action=>{
       const enabled=action==='ANSWER_QUESTION'&&scenario==='task-native-issues-answer'&&!taskAnswer;
       const reason=enabled?null:status==='OPEN'?'CONFIG_NOT_READY':status==='RESOLVED'?'QUESTION_NOT_OPEN':'EXTERNAL_RESULT_UNKNOWN';
       return {action,enabled,reason_code:reason,related_id:id};
      });
     const common={id,task_id:31,session_id:8,instance_id:7,control_generation:1,status,observed_at:created_at,
      resolved_at:status==='RESOLVED'?created_at:null,available_actions};
     list(question?[{...common,native_question_id:'que_fixture',questions:[
      {index:0,header:'固定原生问题',text:'请核对原设计约束。',options:[{label:'原选项',description:'保留说明'}],multiple:false,custom:true},
      {index:1,header:'第二题',text:'保留原次序。',options:[],multiple:true,custom:false}],handoffs:[]}]:
      [{...common,native_permission_id:'per_fixture',tool_name:'bash',patterns:['echo '+('x'.repeat(100))],
       object_refs:[],requested_action:'EXECUTE',tool_ref:{messageID:'msg_fixture',callID:'tool_fixture'}}]);return;
    }
    if(request.method==='GET'&&url.pathname===taskViewPath+'/records'){
     const page=Number(url.searchParams.get('page')??1),session=url.searchParams.get('session_id');
     recordReads.push({page,session});
     const follow=/^task-start-record-count-(\d+)$/.exec(scenario);
     if(follow){
      const rows=Array.from({length:Number(follow[1])},(_,index)=>({
       id:index+1,task_id:31,instance_id:7,control_generation:1,kind:'COMMAND_OUTPUT',
       text:'原命令输出 '+(index+1),observed_at:created_at,session_id:8,native_event_id:null,
       source_kind:'COMMAND',source_id:45,
      }));
      list(rows.filter(row=>!session||String(row.session_id)===session));return;
     }
     if(scenario==='task-start-record-error'){
      fail(503,'STORAGE_UNAVAILABLE','数据暂时无法访问，请稍后核对',{capability_codes:['DATABASE']});return;
     }
     const records=[8,6].flatMap((owner,index)=>Array.from({length:index?1:21},(_,row)=>({
      id:index?22:row+1,task_id:31,instance_id:7,control_generation:1,kind:'CONTROL',
      text:owner===8?'当前会话记录 '+(row+1):'历史会话记录',observed_at:created_at,
      session_id:owner,native_event_id:null,source_kind:'OPERATION',source_id:91,
     })));
     list(scenario==='task-start-record-empty'?[]:records.filter(row=>!session||String(row.session_id)===session));return;
    }
    const historyPath=taskViewPath+'/operations';
    if(codingRecords&&request.method==='GET'&&url.pathname.startsWith(historyPath+'/')){
     if(url.pathname===historyPath+'/91'&&taskStart)success(savedStart(false,true));
     else fail(404,'NOT_FOUND','资源不存在');
     return;
    }
    if(request.method==='GET'&&url.pathname===historyPath){
     if(scenario==='task-history-error'){fail(503,'STORAGE_UNAVAILABLE','数据暂时无法访问，请稍后核对',{capability_codes:['DATABASE']});return;}
     list(scenario==='task-history-empty'?[]:[savedResume(true),savedStart(false,true)]);return;
    }
    if(request.method==='GET'&&url.pathname===historyPath+'/'+checkOperationId&&taskCheck){
     success(savedCheck(scenario==='task-check-done'));return;
    }
    if(request.method==='GET'&&url.pathname===historyPath+'/'+permissionId&&taskPermission){
     success(savedPermission(scenario==='task-native-permission-partial'));return;
    }
    if(request.method==='GET'&&url.pathname===historyPath+'/'+answerId&&taskAnswer){
     success(savedAnswer(scenario==='task-native-issues-answer-done'));return;
    }
    if(request.method==='GET'&&url.pathname===historyPath+'/'+resumeOperationId){
     if(scenario==='task-history-detail-error'){fail(503,'STORAGE_UNAVAILABLE','数据暂时无法访问，请稍后核对',{capability_codes:['DATABASE']});return;}
     success(savedResume(true));return;
    }
    if(request.method==='GET'&&url.pathname===taskPath){
     const statuses=url.searchParams.getAll('status'),rev=url.searchParams.get('design_revision_id');
     if(scenario==='task-list-error'&&!statuses.length){fail(503,'STORAGE_UNAVAILABLE','数据暂时无法访问，请稍后核对',{capability_codes:['DATABASE']});return;}
     const status=taskStop?(scenario==='task-stop-verified'?'TERMINATED':'STOPPING'):'PENDING';
     const found=taskSaved&&(!statuses.length||statuses.includes(status))&&(rev===null||rev==='24');
     const phase=status==='TERMINATED'?'FINISHED':'PREPARING';
     list(found?[{...taskSummary,status,phase,state_version:status==='PENDING'?1:status==='STOPPING'?2:3}]:[]);return;
    }
    if(request.method==='GET'&&url.pathname===callPath){
     if(scenario==='task-usage-error'){
      fail(503,'STORAGE_UNAVAILABLE','数据暂时无法访问，请稍后核对',{capability_codes:['DATABASE']});return;
     }
     list(scenario==='task-usage-empty'?[]:[callSummary]);return;
    }
    if(request.method==='GET'&&url.pathname===callPath+'/'+callId){
     if(scenario==='task-usage-detail-error'){
      fail(503,'STORAGE_UNAVAILABLE','数据暂时无法访问，请稍后核对',{capability_codes:['DATABASE']});return;
     }
     success(callDetail);return;
    }
    const candidatePath=taskViewPath+'/candidates';
    const fixtureCandidate=(id)=>({
      id,task_id:31,base_snapshot_id:base,capture_operation_id:99,
      content_tree_oid:'2'.repeat(40),parent_candidate_id:id===202?201:null,role:'BACKEND',
      control_generation:1,content_policy_version:'CONTENT20-STORE-1',manifest_sha256:'a'.repeat(64),
      captured_at:created_at,published_for_testing_at:null,publication_operation_id:null,
      file_count:2,byte_count:51,created_at,
    });
    if(request.method==='GET'&&url.pathname===candidatePath){
     const candidates=scenario==='task-candidate-updated'?[203,202,201]:[202,201];
     list(scenario.startsWith('task-candidate-')?candidates.map(fixtureCandidate):[]);return;
    }
    if(request.method==='POST'&&url.pathname===roleReconcilePath){
     bodyRequest((key,input)=>{
      if(roleReconcile||input.expected_state_version!==22||input.operation_id!==104){
       fail(500,'INTERNAL_ERROR','Unexpected role observation');return;
      }
      roleReconcile={key,input};roleReconcileWrites.push(roleReconcile);
      success({task_id:31,operation_id:roleReconcileId,operation_status:'PENDING',task_status:'WAITING',state_version:23},202);
     });return;
    }
    if(request.method==='GET'&&url.pathname===taskViewPath+'/operations/104'&&roleReconcile){
     success(savedReconciledSource());return;
    }
    if(request.method==='GET'&&url.pathname===taskViewPath+'/operations/'+roleReconcileId&&roleReconcile){
     success(savedRoleReconciliation(scenario==='task-role-confirmed'));return;
    }
    if(codingDelivery&&scenario.startsWith('task-publication-delivery-repair')){
     const cancelled=scenario.endsWith('-cancelled');
     const sourceUnknown=scenario.endsWith('-source-unknown');
     const repair=taskViewPath+'/repairs';
     if(cancelled&&repairAcceptance&&request.method==='GET'&&url.pathname===taskViewPath+'/operations/112'){
      const fixed=repairAcceptance.input;
      success({id:112,task_id:31,testing_task_id:null,resource_kind:'TASK',resource_id:31,session_id:10,
       operation_type:'REPAIR',idempotency_key:repairAcceptance.key,expected_state_version:50,fixed_input:fixed,
       control_generation:3,status:'CANCELLED',created_at,started_at:created_at,ended_at:created_at,
       failure_code:null,content_capture:null,
       steps:['RESTORE_SOURCE','SEND_REPAIR','OBSERVE','CAPTURE_RESULT'].map((step_type,index)=>({
        operation_id:112,step_no:index+1,step_type,status:index<2?'SUCCEEDED':'CANCELLED',
        external_identity:null,fixed_input:fixed,result_ref:null,started_at:index<3?created_at:null,
        ended_at:created_at,last_observed_at:created_at,
       }))});return;
     }
     if(request.method==='GET'&&url.pathname===defectPath){
      list([{id:1,task_id:31,candidate_id:202,actual_behavior:'原输出不完整',expected_behavior:'按设计保留输出',
       basis_ref:{document_id:41,revision_id:24,quote:'固定设计原文。'},evidence_refs:[],testing_finding_id:null,
       created_at,actor_ref:'fixture'}]);return;
     }
     const item={id:45,task_id:31,defect_ids:[1],source_candidate_id:202,operation_id:112,
      status:cancelled?'CANCELLED':sourceUnknown?'UNKNOWN':'PENDING',created_at,result_candidate_id:null,ended_at:cancelled?created_at:null,failure_code:sourceUnknown?'EXTERNAL_RESULT_UNKNOWN':null};
     if(request.method==='GET'&&url.pathname===repair){list(repairAcceptance?[item]:[]);return;}
     if(request.method==='GET'&&url.pathname===repair+'/45'&&repairAcceptance){success(item);return;}
     if(request.method==='POST'&&url.pathname===repair){
      bodyRequest((key,input)=>{
       if(repairAcceptance||input.expected_state_version!==50||input.candidate_id!==202||
         JSON.stringify(input.defect_ids)!=='[1]'){
        fail(500,'INTERNAL_ERROR','Unexpected repair intent');return;
       }
       repairAcceptance={key,input};
       success({task_id:31,operation_id:112,operation_status:'PENDING',task_status:'WAITING',state_version:51},202);
      });return;
     }
    }
    if(request.method==='GET'&&url.pathname===defectPath){
     list(defectWrites.map(entry=>entry.record));return;
    }
    if(request.method==='GET'&&url.pathname.startsWith(defectPath+'/')){
     const found=defectWrites.find(entry=>url.pathname===defectPath+'/'+entry.data.defect_id);
     if(found)success(found.record);else fail(404,'NOT_FOUND','资源不存在');
     return;
    }
    if(scenario.startsWith('task-publication-defect')){
     if(request.method==='POST'&&url.pathname===defectPath){
      bodyRequest((key,input)=>{
       const id=defectWrites.length+1, imported=input.testing_finding_id===84;
       const facts=imported?{actual_behavior:importedFinding.actual_behavior,
        expected_behavior:importedFinding.expected_behavior,basis_ref:importedFinding.basis_ref,evidence_refs:[]}:input;
       const record={id,task_id:31,candidate_id:202,actual_behavior:facts.actual_behavior,
        expected_behavior:facts.expected_behavior,basis_ref:facts.basis_ref,evidence_refs:facts.evidence_refs,
        testing_finding_id:imported?84:null,created_at,actor_ref:'owned-fixture'};
       const data={defect_id:id,task_id:31,candidate_id:202};
       defectWrites.push({input,key,data,record});
       if(id===1){
        response.writeHead(201,{'Content-Length':1000});response.write('{');setTimeout(()=>response.destroy(),80);
       }else success(data,201);
      });return;
     }
     if(request.method==='GET'&&url.pathname==='/api/v1/test-reports/72'){
      success({id:72,testing_task_id:10,verification_id:55,plan_version_id:11,test_pack_version_id:29,
       input_fingerprint:sealHash,result:'FAILED',scope_stages:['BACKEND','FRONTEND','INTEGRATION','ACCEPTANCE'],
       manual_coverage_ids:[],uncovered_behavior_ids:[],created_at,eligible:false,delivery_eligible:false,
       ineligibility_reason_codes:['RESULT_NOT_PASSED'],delivery_ineligibility_reason_codes:['RESULT_NOT_PASSED'],
       provenance:{requirement_id:1,document_id:41,design_revision_id:24,material_refs:[],
        target_kind:'CANDIDATE',candidate_id:202,snapshot_id:null,profile_version_id:1,purpose:'ACCEPTANCE',source_code_task_id:31}});
      return;
     }
     if(request.method==='GET'&&url.pathname==='/api/v1/test-reports/72/findings'){list([importedFinding]);return;}
    }


    if(codingDelivery){
     const plan=taskViewPath+'/delivery-plans/41',history=taskViewPath+'/deliveries';
     if(request.method==='GET'&&url.pathname===plan){
      if(scenario.endsWith('-error')){fail(503,'STORAGE_UNAVAILABLE','固定预览暂不可读',{capability_codes:['DATABASE']});return;}
      const removed={path:'target-only.txt',change:'DELETE',before_size:11,after_size:null,before_mode:'100644',after_mode:null,binary:false};
      const items=scenario==='task-publication-delivery-history-page'
       ? [...Array.from({length:20},(_,index)=>({...removed,path:'preview-'+String(index+1).padStart(2,'0')+'.txt'})),removed]
       : [removed];
      const page=Number(url.searchParams.get('page')??1);
      success({id:41,task_id:31,candidate_id:202,test_report_id:71,repository_id:23,target_branch:'refs/heads/target',
       expected_target_commit:'8'.repeat(40),target_tree_oid:'9'.repeat(40),target_manifest_sha256:'b'.repeat(64),
       result_tree_oid:'d'.repeat(40),operation_id:110,created_at,target_observed_at:created_at,
       target_diff_items:items.slice((page-1)*20,page*20)},
       200,{page,page_size:20,total:items.length,total_pages:Math.ceil(items.length/20)});return;
     }
     if(request.method==='GET'&&url.pathname===plan+'/file'){
      const path=url.searchParams.get('path'),side=url.searchParams.get('side'),exists=side==='BEFORE';
      if(!['target-only.txt','outside-page.txt'].includes(path)){fail(404,'NOT_FOUND','资源不存在');return;}
      const bytes=Buffer.from(path==='target-only.txt'?'target only':'from fixed plan');
      success({candidate_id:202,delivery_plan_id:41,path,side,exists,offset:0,
       length:exists?bytes.length:0,total_bytes:exists?bytes.length:null,
       content_base64:exists?bytes.toString('base64'):null,next_offset:null});return;
     }
     if(request.method==='GET'&&url.pathname===history){list(deliveryAcceptance?[deliveryRecord()]:[]);return;}
     if(request.method==='GET'&&url.pathname===history+'/43'&&deliveryAcceptance){success(deliveryRecord());return;}
     if(request.method==='POST'&&url.pathname===taskViewPath+'/accept'){
      bodyRequest((key,input)=>{
       const expected={expected_state_version:33,candidate_id:202,test_report_id:71,delivery_plan_id:41,
        expected_target_commit:'8'.repeat(40),repository_quiescent_confirmed:true,manual_risk_accepted:true};
       if(deliveryAcceptance||Object.keys(input).length!==Object.keys(expected).length||
        Object.entries(expected).some(([field,value])=>input[field]!==value)){
        fail(500,'INTERNAL_ERROR','Unexpected delivery acceptance input');return;
       }
       deliveryAcceptance={key,input};
       success({task_id:31,operation_id:111,operation_status:'PENDING',task_status:'AWAITING_ACCEPTANCE',
        state_version:34,acceptance_id:42,delivery_id:43},202);
      });return;
     }
    }
    if(scenario.startsWith('task-publication-')){
     if(request.method==='GET'&&url.pathname==='/api/v1/testing-tasks'&&url.searchParams.get('candidate_id')==='202'){
      list([
       {id:9,requirement_id:1,document_id:41,target_kind:'CANDIDATE',candidate_id:202,snapshot_id:null,
        purpose:'ACCEPTANCE',status:'DRAFT',phase:'PLAN',created_at,report_id:null},
       {id:10,requirement_id:1,document_id:41,target_kind:'CANDIDATE',candidate_id:202,snapshot_id:null,
        purpose:'ACCEPTANCE',status:'COMPLETED',phase:'FINISHED',created_at,report_id:71},
      ]);return;
     }
     if(request.method==='GET'&&url.pathname===candidatePath+'/202'){
      success({...fixtureCandidate(202),role:'INTEGRATION',control_generation:3,
       published_for_testing_at:created_at,publication_operation_id:109});return;
     }
     if(request.method==='GET'&&(url.pathname==='/api/v1/test-reports/71'||
       (reportLinkOnly&&url.pathname==='/api/v1/test-reports/73'))){
      const revoked=scenario==='task-publication-linked-revoked';
      const foreign=url.pathname.endsWith('/73');
      success({id:foreign?73:71,testing_task_id:10,verification_id:55,plan_version_id:11,test_pack_version_id:29,
       input_fingerprint:sealHash,result:'PASSED',scope_stages:['BACKEND','FRONTEND','INTEGRATION','ACCEPTANCE'],
       manual_coverage_ids:codingDelivery?['manual-review']:[],uncovered_behavior_ids:[],created_at,eligible:!revoked,delivery_eligible:!revoked,
       ineligibility_reason_codes:revoked?['TEST_ASSET_REVOKED']:[],delivery_ineligibility_reason_codes:revoked?['TEST_ASSET_REVOKED']:[],
       provenance:{requirement_id:1,document_id:41,design_revision_id:24,material_refs:[],
        target_kind:'CANDIDATE',candidate_id:202,snapshot_id:null,profile_version_id:1,purpose:'ACCEPTANCE',source_code_task_id:foreign?99:31}});return;
     }
     if(request.method==='POST'&&url.pathname===reportLinkPath){
      bodyRequest((key,input)=>{
       if(codingReportLink||input.expected_state_version!==31||input.candidate_id!==202||input.test_report_id!==71){
        fail(500,'INTERNAL_ERROR','Unexpected report link intent');return;
       }
       codingReportLink={key,input,data:{task_id:31,candidate_id:202,test_report_id:71,state_version:32}};
       reportLinkWrites.push(codingReportLink);
       response.writeHead(200,{'Content-Length':1000});response.write('{');
       setTimeout(()=>response.destroy(),80);
      });return;
     }
    }
    if(request.method==='POST'&&url.pathname===publicationPath){
     bodyRequest((key,input)=>{
      if(taskPublication||input.expected_state_version!==30||input.candidate_id!==202||input.verification_id!==72){
       fail(500,'INTERNAL_ERROR','Unexpected publication intent');return;
      }
      taskPublication={key,input,data:{task_id:31,candidate_id:202,test_report_id:null,state_version:31}};
      publicationWrites.push(taskPublication);
      response.writeHead(200,{'Content-Length':1000});response.write('{');
      setTimeout(()=>response.destroy(),80);
     });return;
    }
    if(request.method==='POST'&&url.pathname===verifyPath){
     let raw='';
     for await(const chunk of request) raw+=chunk;
     const input=JSON.parse(raw);
     const key=request.headers['idempotency-key'];
     if(taskCheck||input.expected_state_version!==17||input.purpose!=='HANDOFF'||!key)throw Error('Unexpected verification write');
     taskCheck={key,input,data:{task_id:31,operation_id:checkOperationId,operation_status:'PENDING',task_status:'VERIFYING',state_version:18}};
     checkWrites.push(taskCheck);
     response.statusCode=202;
     response.setHeader('Content-Length','500');
     response.write('{"success":');
     setTimeout(()=>response.destroy(),80);
     return;
    }
    if(request.method==='GET'&&url.pathname.startsWith(candidatePath+'/')&&url.pathname.endsWith('/verifications')){
     if(scenario==='task-check-list-error'){
      fail(503,'STORAGE_UNAVAILABLE','数据暂时无法访问，请稍后核对',{capability_codes:['DATABASE']});return;
     }
     list(url.pathname!==verifyPath||scenario==='task-check-empty'||!scenario.startsWith('task-check-')
      ?[]:scenario==='task-check-done'?[checkVerification(72),checkVerification(71)]:[checkVerification(71)]);return;
    }
    if(request.method==='GET'&&url.pathname===taskViewPath+'/verifications/72/items/722/cases'){
     caseReads++;
     if(caseReads===1){
      fail(503,'CONFIG_NOT_READY','原用例资源暂不可读',{capability_codes:['Q20-CHECKS']});return;
     }
     list(Array.from({length:21},(_,index)=>({
      case_id:'controlled-'+String(index+1).padStart(2,'0'),name:'受控用例 '+(index+1),
      result:index===20?'FAILED':'PASSED',expected_assertion_count:2,
      passed_assertion_count:index===20?1:2,failed_assertion_count:index===20?1:0,
      capture_status:index===20?'REDACTED':'FULL',summary:index===20?'部分诊断信息已脱敏。':null,
      observed_at:created_at,
     })));return;
    }
    if(request.method==='GET'&&url.pathname.startsWith(taskViewPath+'/verifications/')){
     const id=Number(url.pathname.split('/').at(-1));
     if(![71,72].includes(id)){fail(404,'NOT_FOUND','资源不存在');return;}
     success(checkVerification(id));return;
    }
    if(request.method==='GET'&&url.pathname.startsWith(candidatePath+'/')&&url.pathname.endsWith('/diff')){
     if(codingRecords&&scenario==='task-candidate-history-page'&&url.pathname===diffPath){
      const added=Array.from({length:20},(_,index)=>({...changedFiles[0],path:'page-'+String(index+1).padStart(2,'0')+'.txt'}));
      list([...added,changedFiles[2]]);return;
     }
     list(url.pathname===diffPath?changedFiles:[]);return;
    }
    if(codingRecords&&request.method==='GET'&&url.pathname===candidatePath+'/201/diff/file'){
     const file=url.searchParams.get('path'),side=url.searchParams.get('side');
     if(file!=='src/历史 +%.txt'){fail(404,'NOT_FOUND','资源不存在');return;}
     originalFileReads++;
     if(originalFileReads===1){
      fail(409,'CONTENT_NOT_READY','固定内容暂时不可读取',{
       task_id:null,current_state_version:null,related_operation_id:null,related_entity_kind:null,related_entity_id:null,
      });return;
     }
     const bytes=side==='AFTER'?null:Buffer.from('来自原候选');
     success({candidate_id:201,delivery_plan_id:null,side,path:file,exists:bytes!==null,offset:0,
      length:bytes?.length??0,total_bytes:bytes?.length??null,content_base64:bytes?.toString('base64')??null,
      next_offset:null});return;
    }
    if(request.method==='GET'&&url.pathname===diffPath+'/file'){
     diffFileReads++;
     const file=url.searchParams.get('path'),side=url.searchParams.get('side');
     const offset=Number(url.searchParams.get('offset')),limit=Number(url.searchParams.get('length'));
     if(diffFileReads===1&&!codingRecords){
      fail(409,'CONTENT_NOT_READY','固定内容暂时不可读取',{
       task_id:null,current_state_version:null,related_operation_id:null,related_entity_kind:null,related_entity_id:null,
      });return;
     }
     const bytes=file==='a-empty.txt'?(side==='BEFORE'?null:Buffer.alloc(0)):
      file==='src/多字节.ts'?(side==='BEFORE'?Buffer.from('old\n'):splitText):null;
     const data=bytes?.subarray(offset,offset+limit);
     const next=offset+(data?.length??0);
     success({candidate_id:202,delivery_plan_id:null,side,path:file,exists:bytes!==null,offset,
      length:data?.length??0,total_bytes:bytes?.length??null,content_base64:data?.toString('base64')??null,
      next_offset:bytes!==null&&next<bytes.length?next:null});return;
    }
    if(request.method==='GET'&&url.pathname.startsWith(candidatePath+'/')){
     if(scenario==='task-candidate-error'){
      fail(409,'CONTENT_NOT_READY','固定内容暂时不可读取',{
       task_id:null,current_state_version:null,related_operation_id:null,related_entity_kind:null,related_entity_id:null,
      });return;
     }
     const id=Number(url.pathname.split('/').at(-1));
     if(![201,202].includes(id)&&!(scenario==='task-candidate-updated'&&id===203)){
      fail(404,'NOT_FOUND','资源不存在');return;
     }
     success(fixtureCandidate(id));return;
    }
    if(request.method==='POST'&&url.pathname===configurationPath&&scenario==='task-configuration'){
     bodyRequest((key,input)=>{
      configurationWrites.push({key,input});
      if(configurationSaved||input.expected_state_version!==(liveConfiguration?18:1)||input.execution_profile_version_id!==20||
         input.authorization_id!==89||input.reason!=='核对后更换配置'){
       fail(500,'INTERNAL_ERROR','Original configuration inputs differ');return;
      }
      const data={task_id:31,operation_id:119,operation_status:'RUNNING',task_status:liveConfiguration?'WAITING':'PENDING',state_version:liveConfiguration?19:2};
      configurationSaved={key,input,data};
      response.writeHead(202,{'Content-Length':1000});response.write('{');
      setTimeout(()=>response.destroy(),80);
     });return;
    }
    if(request.method==='GET'&&url.pathname===taskViewPath+'/operations/119'&&configurationSaved){
     success(configurationOperation(scenario==='task-configuration-applied'));return;
    }
    if(request.method==='GET'&&url.pathname===taskViewPath){
     if(liveConfiguration&&scenario.startsWith('task-configuration')){
      success(liveConfigurationTask());return;
     }
     if(codingRecords&&scenario.startsWith('task-runtime-')&&taskStop){
      const stage=scenario.replace('task-runtime-','');
      const current=taskAfterStop(stage==='verified');
      if(stage==='verified'){success(current);return;}
      const facts={
       aborting:['ABORTING','NOT_STARTED','RUNNING'],
       terminating:['TERMINATING','NOT_STARTED','RUNNING'],
       cleaning:['VERIFIED','CLEANING','RUNNING'],
       'cleanup-unknown':['VERIFIED','UNKNOWN','UNKNOWN'],
      }[stage];
      success({...current,runtime:{...current.runtime,stop_status:facts[0],cleanup_status:facts[1]},
       active_operations:[{...current.active_operations[0],status:facts[2]}]});return;
     }
     if(scenario.startsWith('task-configuration')&&configurationSaved){
      const applied=scenario==='task-configuration-applied';
      const data=taskSaved.view;
      success({...data,execution_profile_version_id:20,authorization_id:89,state_version:2,
       configuration_application:{id:92,status:applied?'APPLIED':'PENDING',new_profile_version_id:20,
        authorization_id:89,evidence_result:applied?'VERIFIED':null,difference_kinds:[],observed_at:applied?created_at:null},
      });return;
     }
     if(codingDelivery&&scenario==='task-delivery-cleanup'){
      const data=startedTask(false,{},taskResume?38:37);
      success({...data,status:'WAITING',phase:'DELIVERY',resume_phase:'DELIVERY',
       active_session_id:10,control_generation:4,current_candidate_id:202,
       current_refs:{verification_id:72,test_report_id:71,delivery_plan_id:41,delivery_id:43},
       active_operations:[{id:111,operation_type:'DELIVER',status:'RUNNING'}],
       waiting_items:[{id:30,task_id:31,testing_task_id:null,kind:'DELIVERY_RESULT',source_kind:'DELIVERY',
        source_id:43,resume_phase:'DELIVERY',status:'OPEN',created_at,resolved_at:null,resolution_ref:null}],
       runtime:{...data.runtime,environment_status:'UNKNOWN',stop_status:'VERIFIED',active_process_count:0,
        cleanup_status:taskResume?'NOT_STARTED':'UNKNOWN'},
       available_actions:data.available_actions.map(item=>item.action==='RESUME'&&!taskResume
        ?{...item,enabled:true,related_id:111,reason_code:null}
        :{...item,enabled:item.action==='TERMINATE',reason_code:item.action==='TERMINATE'?null:'INVALID_STATE'}),
      });return;
     }
     if(codingDelivery&&scenario.startsWith('task-publication-delivery-repair')){
      const cancelled=scenario.endsWith('-cancelled');
      const waiting=!cancelled&&(Boolean(repairAcceptance)||scenario.endsWith('-busy'));
      const data=startedTask(false,{},cancelled?52:waiting?51:50);
      success({...data,status:cancelled?'VERIFYING':waiting?'WAITING':'AWAITING_TESTING',
       phase:cancelled||waiting?'INTEGRATION':'TESTING',resume_phase:waiting?'INTEGRATION':null,
       active_session_id:10,control_generation:3,current_candidate_id:202,
       current_refs:{...data.current_refs,verification_id:cancelled||waiting?null:72},
       active_operations:waiting?[{id:112,operation_type:'REPAIR',status:'PENDING'}]:[],
       waiting_items:waiting?[{id:29,task_id:31,testing_task_id:null,kind:'OPERATION_RESULT',
        source_kind:'OPERATION',source_id:112,resume_phase:'INTEGRATION',status:'OPEN',created_at,
        resolved_at:null,resolution_ref:null}]:[],
       runtime:{...data.runtime,activity_status:waiting?'UNKNOWN':'QUIESCENT',
        active_process_count:waiting?null:1},
       available_actions:data.available_actions.map(item=>item.action==='REPAIR'
        ?{...item,enabled:!waiting,reason_code:waiting?'OPERATION_CONFLICT':null}:item),
      });return;
     }
     if(codingDelivery&&scenario.startsWith('task-publication-delivery')){
      const data=startedTask(false,{},deliveryAcceptance?34:33);
      success({...data,status:'AWAITING_ACCEPTANCE',phase:'ACCEPTANCE',active_session_id:10,control_generation:3,
       current_candidate_id:202,current_refs:{...data.current_refs,verification_id:72,test_report_id:71,
        delivery_plan_id:41,delivery_id:deliveryAcceptance?43:null},
       active_operations:deliveryAcceptance?[{id:111,operation_type:'DELIVER',status:'PENDING'}]:[],
       runtime:{...data.runtime,activity_status:deliveryAcceptance?'UNKNOWN':'QUIESCENT',
        active_process_count:deliveryAcceptance?null:1,observed_at:deliveryAcceptance?null:created_at},
       available_actions:data.available_actions.map(item=>item.action==='ACCEPT'
        ?{...item,enabled:!deliveryAcceptance,reason_code:deliveryAcceptance?'OPERATION_CONFLICT':null}:item),
      });return;
     }
     if(scenario==='task-role-unknown'||scenario==='task-role-confirmed'){
      const done=scenario==='task-role-confirmed';
      const data=startedTask(false,{},done?24:roleReconcile?23:22);
      success({...data,status:done?(roleCreation?'VERIFYING':repairCreation?'WAITING':'RUNNING'):'WAITING',phase:done&&!repairReconciliation&&!roleCreation?'FRONTEND':'BACKEND',resume_phase:done&&!repairCreation?null:'BACKEND',
       control_generation:2,active_session_id:repairReconciliation?8:done&&!roleCreation?9:null,current_candidate_id:202,
       current_refs:{...data.current_refs,verification_id:repairReconciliation?null:72},
       waiting_items:done&&!repairCreation?[]:[{id:18,task_id:31,testing_task_id:null,kind:'OPERATION_RESULT',source_kind:'OPERATION',
        source_id:104,resume_phase:'BACKEND',status:'OPEN',created_at,resolved_at:null,resolution_ref:null}],
       active_operations:done?(roleCreation?[{id:104,operation_type:'HANDOFF_ROLE',status:'RUNNING'}]:repairCreation?[{id:104,operation_type:'REPAIR',status:'RUNNING'}]:[]):[{id:104,operation_type:repairReconciliation?'REPAIR':'HANDOFF_ROLE',status:'UNKNOWN'}],
       available_actions:data.available_actions.map(item=>item.action==='RECONCILE'
        ?{...item,enabled:!done&&!roleReconcile,related_id:done?null:104,
          reason_code:done?'INVALID_STATE':roleReconcile?'OPERATION_IN_PROGRESS':null}:item),
      });return;
     }
     if(scenario==='task-role-running'){
      const data=startedTask(false,{},21);
      success({...data,status:'VERIFYING',phase:'BACKEND',active_session_id:null,current_candidate_id:202,
       current_refs:{...data.current_refs,verification_id:72},
       active_operations:[{id:104,operation_type:'HANDOFF_ROLE',status:'RUNNING'}],
      });return;
     }
     if(scenario.startsWith('task-publication-')){
      const linked=scenario.startsWith('task-publication-linked');
      const published=scenario!=='task-publication-ready';
      const defects=scenario.startsWith('task-publication-defect');
      const data=startedTask(false,{},defects?31+defectWrites.length:linked?32:published?31:30);
      success({...data,status:linked?'AWAITING_ACCEPTANCE':published?'AWAITING_TESTING':'VERIFYING',
       phase:linked?'ACCEPTANCE':published?'TESTING':'INTEGRATION',
       active_session_id:10,control_generation:3,current_candidate_id:202,
       current_refs:{...data.current_refs,verification_id:72,test_report_id:linked?71:null},
       runtime:{...data.runtime,activity_status:'QUIESCENT',active_process_count:1},
       available_actions:data.available_actions.map(item=>item.action==='SUBMIT_FOR_TESTING'
        ?{...item,enabled:!published,reason_code:published?'INVALID_STATE':null}
        :item.action==='LINK_TEST_REPORT'?{...item,enabled:published,reason_code:published?null:'INVALID_STATE'}
        :item.action==='REGISTER_DEFECT'&&defects?{...item,enabled:true,reason_code:null}:item),
      });return;
     }
     if(scenario.startsWith('task-check-')){
      const done=scenario==='task-check-done';
      const pending=taskCheck!==null&&!done;
      const ready=scenario!=='task-check-empty'&&!pending;
      const data=startedTask(false,{},taskCheck?18:17);
      success({...data,status:'VERIFYING',current_candidate_id:202,
       active_operations:pending?[{id:checkOperationId,operation_type:'VERIFY_CANDIDATE',status:'RUNNING'}]:[],
       current_refs:{...data.current_refs,verification_id:scenario==='task-check-empty'?null:done?72:71},
       runtime:{...data.runtime,activity_status:'QUIESCENT',active_process_count:1},
       configuration_application:{id:91,status:'APPLIED',new_profile_version_id:data.execution_profile_version_id,
        authorization_id:data.authorization_id,evidence_result:'VERIFIED',difference_kinds:[],observed_at:created_at},
       available_actions:data.available_actions.map(item=>['CAPTURE_AND_CHECK','VERIFY_CANDIDATE'].includes(item.action)
        ?{...item,enabled:ready,reason_code:ready?null:pending?'WRITER_ACTIVE':'CONFIG_NOT_READY'}:item),
       verification_purposes:data.verification_purposes.map(item=>({...item,enabled:ready,
        reason_code:ready?null:pending?'WRITER_ACTIVE':'RESOURCE_NOT_READY'})),
      });return;
     }
     if(scenario.startsWith('task-candidate-')){
      const updated=scenario==='task-candidate-updated';
      const data=startedTask(false,{},updated?18:17);
      success({...data,status:'VERIFYING',current_candidate_id:updated?203:202,
       active_operations:[{id:99,operation_type:'CAPTURE_AND_CHECK',status:'RUNNING'}],
       runtime:{...data.runtime,activity_status:'QUIESCENT',active_process_count:1},
       verification_purposes:data.verification_purposes.map(item=>({...item,reason_code:'RESOURCE_NOT_READY'})),
      });return;
     }
     if(scenario==='task-native-handoff'){
      const saved=startedTask(true,{},taskHandoffLink?14:taskHandoff?13:12);
      success({...saved,active_operations:[],waiting_items:[{id:14,task_id:31,testing_task_id:null,resume_phase:'BACKEND',
       status:'OPEN',created_at,resolved_at:null,resolution_ref:null,kind:'QUESTION',source_kind:'QUESTION',source_id:4}],
       available_actions:saved.available_actions.map((action)=>action.action==='RESUME'
        ?{...action,related_id:null,reason_code:'INVALID_STATE'}:action)});return;
     }
     if(scenario.startsWith('task-native-permission')){
      const partial=scenario==='task-native-permission-partial';
      const saved=startedTask(true,{},partial?16:taskPermission?15:14);
      const wait={task_id:31,testing_task_id:null,resume_phase:'BACKEND',status:'OPEN',created_at,
       resolved_at:null,resolution_ref:null,kind:'PERMISSION',source_kind:'PERMISSION'};
      success({...saved,active_operations:taskPermission?[{id:permissionId,operation_type:'DECIDE_PERMISSION',status:partial?'UNKNOWN':'PENDING'}]:[],
       waiting_items:[...(partial?[]:[{...wait,id:11,source_id:2}]),{...wait,id:12,source_id:3}],
       available_actions:saved.available_actions.map((action)=>action.action==='RESUME'
        ?{...action,related_id:null,reason_code:'INVALID_STATE'}:action)});return;
     }
     if(scenario.startsWith('task-native-issues')){
      const done=scenario==='task-native-issues-answer-done';
      const saved=startedTask(true,{},taskAnswer?(done?11:10):9);
      const wait={task_id:31,testing_task_id:null,resume_phase:'BACKEND',status:'OPEN',created_at,
       resolved_at:null,resolution_ref:null};
      success({...saved,active_operations:taskAnswer&&!done?[{id:answerId,operation_type:'ANSWER_QUESTION',status:'PENDING'}]:[],waiting_items:[
       ...(done?[]:[{...wait,id:10,kind:'QUESTION',source_kind:'QUESTION',source_id:1}]),
       {...wait,id:11,kind:'PERMISSION',source_kind:'PERMISSION',source_id:2},
      ],available_actions:saved.available_actions.map((action)=>action.action==='RESUME'
       ?{...action,related_id:null,reason_code:'INVALID_STATE'}:action)});return;
     }
     if(scenario==='task-summary-error'){
      fail(503,'STORAGE_UNAVAILABLE','数据暂时无法访问，请稍后核对',{capability_codes:['DATABASE']});return;
     }
     if(!taskSaved||scenario==='task-missing'){fail(404,'NOT_FOUND','资源不存在');return;}
     if(scenario==='task-start-lost'){
      const task=taskSaved.view;
      success({...task,available_actions:task.available_actions.map(item=>item.action==='START'
       ?{...item,enabled:true,reason_code:null}:item)});return;
     }
     if(scenario==='task-start-completed'||scenario.startsWith('task-start-record-')||scenario==='task-model-waiting'||scenario.startsWith('task-usage-')||(!taskStop&&taskStart&&scenario==='task-stop-lost')){
      const waiting=scenario==='task-model-waiting';
      success(startedTask(waiting,{},taskPermission&&!waiting?16:taskAnswer&&!waiting?11:taskResume?(waiting?7:8):taskBudget?6:waiting?5:4));return;
     }
     if(['task-start-running','task-start-ready','task-start-unknown','task-basis-unknown','task-basis-failed','task-conditions-blocked'].includes(scenario)){
      const task=taskSaved.view,ready=['task-start-ready','task-basis-unknown','task-basis-failed','task-conditions-blocked'].includes(scenario);
      const unknown=['task-start-unknown','task-basis-unknown'].includes(scenario),failed=scenario==='task-basis-failed'||scenario==='task-conditions-blocked';
      success({...task,state_version:ready?3:2,workspace_id:ready?19:null,
       runtime:{...task.runtime,environment_status:ready?'NOT_PREPARED':unknown?'UNKNOWN':'PREPARING',
        activity_status:ready?'NOT_STARTED':'UNKNOWN'},
       active_operations:failed?[]:[{id:91,operation_type:'START',status:unknown?'UNKNOWN':'RUNNING'}],
       available_actions:task.available_actions.map(item=>item.action==='START'
        ?{...item,related_id:91,reason_code:failed?(scenario==='task-conditions-blocked'?'CONFIG_NOT_READY':'CONTENT_NOT_READY'):unknown?'EXTERNAL_RESULT_UNKNOWN':'OPERATION_IN_PROGRESS'}:item)});
      return;
     }
     success(taskStop?taskAfterStop(scenario==='task-stop-verified'):taskSaved.view);return;
    }
    if(request.method==='GET'&&url.pathname==='/api/v1/code-repositories'){list([repository]);return;}
    if(request.method==='GET'&&url.pathname===repoPath){success({...repository,root_path:'C:\\owned\\coding-test'});return;}
    if(request.method==='GET'&&url.pathname===repoPath+'/observations/'+observationId){
     success({id:observationId,repository_id:taskRepo,operation_id:80,head_commit:commit,local_branches:[
      {full_ref:'refs/heads/main',commit_oid:commit},{full_ref:'refs/heads/checked-out',commit_oid:commit}],
      worktrees:[{canonical_path:'C:\\owned\\coding-test',head_commit:commit,branch_ref:'refs/heads/checked-out'}],
      observed_at:created_at,status:'READABLE'});return;
    }
    if(request.method==='GET'&&url.pathname==='/api/v1/code-execution-profiles'){list([originalProfile]);return;}
    if(request.method==='GET'&&url.pathname==='/api/v1/code-execution-profile-versions/'+profileId){success(profileVersion);return;}
    if(scenario.startsWith('task-configuration')){
     if(request.method==='GET'&&url.pathname==='/api/v1/code-execution-profiles/9/versions'){list([replacementProfile,profileVersion]);return;}
     if(request.method==='GET'&&url.pathname==='/api/v1/code-execution-profile-versions/20'){success(replacementProfile);return;}
     if(request.method==='GET'&&url.pathname==='/api/v1/code-authorizations'){list([replacementGrant]);return;}
     if(request.method==='GET'&&url.pathname==='/api/v1/code-authorizations/89'){
      success(scenario==='task-configuration-applied'
       ?{...replacementGrant,task_id:31,status:'EFFECTIVE'}:replacementGrant);return;
     }
    }
    if(request.method==='GET'&&url.pathname==='/api/v1/code-authorizations'){list([{...authorizations[0],profile_version_id:profileId}]);return;}
    if(request.method==='GET'&&url.pathname==='/api/v1/code-authorizations/'+authorizationId){
     success({...authorizations[0],profile_version_id:profileId});return;
    }
    if(request.method==='GET'&&url.pathname==='/api/v1/code-snapshots/'+base){
     success({id:base,repository_id:taskRepo,registration_operation_id:81,content_profile_version_id:profileId,
      commit_oid:commit,content_tree_oid:'2'.repeat(40),content_policy_version:'GIT20-BASELINE-1',
      registered_at:created_at,created_at,ready:snapshotReady,reason_codes:snapshotReady?[]:['CONTENT_NOT_READY']});return;
    }
    if(request.method==='GET'&&url.pathname==='/api/v1/code-snapshots/'+base+'/files'){
     list([{path:'src/main.py',mode:'100644',blob_oid:'3'.repeat(40),byte_count:51}]);return;
    }
    if(request.method==='POST'&&[repoPath+'/refresh',repoPath+'/snapshots'].includes(url.pathname)){
     bodyRequest((key,input)=>{
      const baseline=url.pathname.endsWith('/snapshots'),id=baseline?81:80;
      if(baseline&&(input.commit_oid!==commit||input.execution_profile_version_id!==profileId)){
       fail(500,'INTERNAL_ERROR','Baseline input mismatch');return;
      }
      const prior=taskOperations.get(id);
      if(prior){
       if(!baseline||prior.data.idempotency_key!==key||
          JSON.stringify(prior.data.fixed_input)!==JSON.stringify({repository_id:taskRepo,...input})){
        fail(500,'INTERNAL_ERROR','Original observation identity changed');return;
       }
       baselineResends++;
       prior.data.status='SUCCEEDED';
       prior.data.failure_code=null;
       prior.data.steps.forEach((step,index)=>{
        step.status='SUCCEEDED';
        if(index===prior.data.steps.length-1)step.result_ref={snapshot_id:base};
       });
       snapshotReady=true;
       success(prior.accepted,202);return;
      }
      const fixed_input=baseline?{repository_id:taskRepo,...input}:{repository_id:taskRepo};
      const types=baseline?['VALIDATE_COMMIT','PIN_COMMIT','VERIFY_PINNED_OBJECTS','SAVE_BASELINE']:['READ_REPOSITORY','SAVE_OBSERVATION'];
      const accepted={resource_kind:'REPOSITORY',resource_id:taskRepo,operation_id:id,operation_status:'PENDING'};
      taskOperations.set(id,{path:url.pathname,accepted,data:{id,task_id:null,testing_task_id:null,resource_kind:'REPOSITORY',
       resource_id:taskRepo,session_id:null,operation_type:baseline?'REGISTER_BASE':'REFRESH_REPOSITORY',
       idempotency_key:key,expected_state_version:null,fixed_input,control_generation:null,status:baseline?'UNKNOWN':'SUCCEEDED',
       created_at,started_at:created_at,ended_at:created_at,failure_code:baseline?'EXTERNAL_RESULT_UNKNOWN':null,content_capture:null,
       steps:types.map((step_type,index)=>({operation_id:id,step_no:index+1,step_type,status:baseline?['SUCCEEDED','UNKNOWN','PENDING','PENDING'][index]:'SUCCEEDED',
        external_identity:{},fixed_input,started_at:created_at,ended_at:created_at,last_observed_at:created_at,
        result_ref:!baseline&&index===types.length-1?{observation_id:observationId}:null}))}});
      success(accepted,202);
     });return;
    }
    if(request.method==='GET'&&url.pathname.startsWith('/api/v1/code-operations/')){
     const record=taskOperations.get(Number(url.pathname.split('/').at(-1)));
     if(record){success(record.data);return;}
    }
    if(request.method==='POST'&&url.pathname===taskPath){
     bodyRequest((key,input)=>{
      taskWrites.push({key,input});
      if(taskSaved){fail(409,'OPERATION_CONFLICT','重复创建',{task_id:null,current_state_version:null,
        related_operation_id:null,related_entity_kind:null,related_entity_id:null});return;}
      taskSaved={key,view:taskView(input)};
      if(scenario==='task-lost'){
       response.writeHead(201,{'Content-Length':1000});response.write('{');
       setTimeout(()=>response.destroy(),80);
      }else success(taskSaved.view,201);
     });return;
    }
    if(request.method==='GET'&&url.pathname==='/api/v1/code-command-receipts'){
     const key=url.searchParams.get('request_key'),path=url.searchParams.get('path');
     const repositoryRecord=[...taskOperations.values()].find(row=>row.path===path&&row.data.idempotency_key===key);
     if(repositoryRecord){
      success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:202,
       original_outcome:{success:true,data:repositoryRecord.accepted,error:null},task_id:null,testing_task_id:null,
       operation_id:repositoryRecord.data.id});return;
     }
     if(path===configurationPath&&configurationSaved?.key===key){
      success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:202,
       original_outcome:{success:true,data:configurationSaved.data,error:null},task_id:31,testing_task_id:null,
       operation_id:configurationSaved.data.operation_id});return;
     }
     if(path===defectPath){
      const stored=defectWrites.find(entry=>entry.key===key);
      if(stored){
       success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:201,
        original_outcome:{success:true,data:stored.data,error:null},task_id:31,testing_task_id:null,operation_id:null});
       return;
      }
     }
     if(path===reportLinkPath&&codingReportLink?.key===key){
      if(scenario.startsWith('task-publication-linked')){
       success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:200,
        original_outcome:{success:true,data:codingReportLink.data,error:null},task_id:31,testing_task_id:null,operation_id:null});return;
      }
      success({lookup_status:'UNKNOWN',record_status:'PROCESSING',original_http_status:null,
       original_outcome:null,task_id:31,testing_task_id:null,operation_id:null});return;
     }
     if(path===publicationPath&&taskPublication?.key===key){
      success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:200,
       original_outcome:{success:true,data:taskPublication.data,error:null},task_id:31,testing_task_id:null,operation_id:null});return;
     }
     if(path===verifyPath&&taskCheck?.key===key){
      success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:202,
       original_outcome:{success:true,data:taskCheck.data,error:null},task_id:31,testing_task_id:null,
       operation_id:checkOperationId});return;
     }
     if(path===startPath&&taskStart?.key===key){
      success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:202,
       original_outcome:{success:true,data:taskStart.data,error:null},task_id:31,testing_task_id:null,
       operation_id:91});return;
     }
     if(path===handoffWritePath&&taskHandoff?.key===key){
      success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:201,
       original_outcome:{success:true,data:taskHandoff.data,error:null},task_id:31,testing_task_id:null,
       operation_id:null});return;
     }
     if(path===permissionPath&&taskPermission?.key===key){
      success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:202,
       original_outcome:{success:true,data:taskPermission.data,error:null},task_id:31,testing_task_id:null,
       operation_id:permissionId});return;
     }
     if(path===answerPath&&taskAnswer?.key===key){
      success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:202,
       original_outcome:{success:true,data:taskAnswer.data,error:null},task_id:31,testing_task_id:null,
       operation_id:answerId});return;
     }
     if(path===resumePath&&taskResume?.key===key){
      success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:202,
       original_outcome:{success:true,data:taskResume.data,error:null},task_id:31,testing_task_id:null,
       operation_id:resumeOperationId});return;
     }
     if(path===budgetPath&&taskBudget?.key===key){
      success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:200,
       original_outcome:{success:true,data:taskBudget.data,error:null},task_id:31,testing_task_id:null,
       operation_id:null});return;
     }
     if(path===stopPath&&taskStop?.key===key){
      success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:202,
       original_outcome:{success:true,data:taskStop.data,error:null},task_id:31,testing_task_id:null,
       operation_id:stopOperationId});return;
     }
     if(path===taskPath&&taskSaved?.key===key){
      success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:201,
       original_outcome:{success:true,data:taskSaved.view,error:null},task_id:31,testing_task_id:null,operation_id:null});return;
     }
    }
   }
   if(request.method==='GET'&&url.pathname==='/api/v1/code-repositories'){
    if(scenario==='repository-failed'){
     response.statusCode=503;
     response.end(JSON.stringify({success:false,data:null,error:{code:'STORAGE_UNAVAILABLE',message:'暂时无法读取仓库',details:{capability_codes:['DATABASE']}},meta:{request_id:randomUUID()}}));
    }else list([
     ...(scenario==='repository-ready'?[repository]:[]),
     ...[...registrations.values()].filter(entry=>entry.terminal==='SUCCEEDED').map(entry=>savedRegistration(entry)),
    ]);
    return;
   }
   const registrationOperationPath=/^\/api\/v1\/code-operations\/([0-9]+)$/.exec(url.pathname);
   if(request.method==='GET'&&registrationOperationPath){
    const refresh=[...refreshes.values()].find(item=>item.result.operation_id===Number(registrationOperationPath[1]));
    if(refresh){
     if(scenario==='refresh-saved')refresh.saved=true;
     const status=refresh.saved?'SUCCEEDED':scenario==='refresh-unknown'?'UNKNOWN':'RUNNING';
     success(refreshOperation(refresh,status));return;
    }
    const entry=[...registrations.values()].find(item=>item.result.operation_id===Number(registrationOperationPath[1]));
    if(entry){
     if(scenario==='registration-read-failed'){
      response.statusCode=503;
      response.end(JSON.stringify({success:false,data:null,error:{code:'STORAGE_UNAVAILABLE',message:'数据暂时无法访问，请稍后核对',
       details:{capability_codes:['DATABASE']}},meta:{request_id:randomUUID()}}));
     }else{
      if(entry.terminal===null&&scenario==='registration-failed')entry.terminal='FAILED';
      if(entry.terminal===null&&scenario==='registration-saved')entry.terminal='SUCCEEDED';
      success(registrationOperation(entry,entry.terminal??'RUNNING'));
     }
     return;
    }
   }
   const registeredRepositoryPath=/^\/api\/v1\/code-repositories\/([0-9]+)$/.exec(url.pathname);
   if(request.method==='GET'&&registeredRepositoryPath){
    const entry=[...registrations.values()].find(item=>item.result.resource_id===Number(registeredRepositoryPath[1]));
    if(entry?.terminal==='SUCCEEDED'){success(savedRegistration(entry,true));return;}
   }
   if(request.method==='GET'&&url.pathname==='/api/v1/code-repositories/23'){
    success({...repository,root_path:'C:\\test\\owned-repository'});return;
   }
   if(request.method==='GET'&&url.pathname==='/api/v1/code-repositories/23/observations/33'){
    success({id:33,repository_id:23,operation_id:51,head_commit:null,local_branches:[],worktrees:[],
      observed_at:repository.latest_observation.observed_at,status:'UNKNOWN'});return;
   }

   if(request.method==='GET'&&url.pathname===observationPath){
    success({id:35,repository_id:26,operation_id:83,head_commit:commit,
     local_branches:[{full_ref:'refs/heads/main',commit_oid:commit}],
     worktrees:[],observed_at:created_at,status:'READABLE'});return;
   }
   if(request.method==='POST'&&url.pathname===refreshPath){
    let body='';
    request.setEncoding('utf8');request.on('data',chunk=>{body+=chunk;});
    request.on('end',()=>{
     const key=request.headers['idempotency-key'];
     if(scenario!=='refresh-lost'||typeof key!=='string'||refreshes.has(key)||body!=='{}'){
      response.statusCode=400;response.end('Invalid refresh command');return;
     }
     const result={resource_kind:'REPOSITORY',resource_id:26,operation_id:83,operation_status:'PENDING'};
     refreshes.set(key,{key,result,saved:false});refreshWrites.push({key,body});
     response.writeHead(202,{'Content-Length':1000});response.write('{');
     setTimeout(()=>response.destroy(),250);
    });
    return;
   }

   if(request.method==='GET'&&url.pathname==='/api/v1/code-authorizations'){
    if(scenario==='authorization-failed'){
     response.statusCode=503;
     response.end(JSON.stringify({success:false,data:null,error:{code:'STORAGE_UNAVAILABLE',message:'授权读取暂不可用',details:{capability_codes:['DATABASE']}},meta:{request_id:randomUUID()}}));
    }else{
     const task=url.searchParams.get('task_id'),status=url.searchParams.get('status');
     list(authorizations.filter(item=>(task===null||String(item.task_id)===task)&&(status===null||item.status===status)));
    }
    return;
   }
   if(request.method==='GET'&&url.pathname==='/api/v1/code-authorizations/87'){
    success(authorizations[0]);return;
   }
   if(request.method==='GET'&&url.pathname==='/api/v1/code-configuration-options'){
    const kind=url.searchParams.get('kind');
    if(scenario==='catalog-failed'&&kind==='GIT'){
     response.statusCode=503;
     response.end(JSON.stringify({success:false,data:null,error:{code:'STORAGE_UNAVAILABLE',message:'资源目录暂不可读',details:{capability_codes:['DATABASE']}},meta:{request_id:randomUUID()}}));
    }else if(kind==='GIT'){
     list([{kind:'GIT',option_id:'git:mingit-2.56.0.windows.4',label:'登记的 MinGit',
      ready:false,unresolved_capability_codes:['Q20-GIT','Q20-WINDOWS'],
      value:{version:'2.56.0.windows.4',source_commit:'581291682ad5a238c08c93d1f5bd4518382a3230',
       protocol_version:'GIT20-LOCAL-1',binary_ref:'git-binary:sha256:'+'a'.repeat(64),
       runtime_bundle_ref:'git-bundle:sha256:4e888e998f1f08e8b78559c212d30c51aaa3cc30e85b9cdafcf7b44249a4e215'}}]);
    }else if(kind==='SCOPE'){
     if(scenario==='catalog-scope-failed'){
      response.statusCode=503;
      response.end(JSON.stringify({success:false,data:null,error:{code:'CONFIG_NOT_READY',message:'执行范围暂不可读',details:{capability_codes:['Q20-CONFIG']}},meta:{request_id:randomUUID()}}));
     }else if(scenario==='catalog-scope-empty')list([]);
     else if(scenario==='catalog-scope-loading')setTimeout(()=>list(managedScopes),800);
     else list(managedScopes);
    }else if(kind==='CONTENT_POLICY'){
     list([contentPolicy]);
    }else if(kind==='MODEL'){
     list([{kind:'MODEL',option_id:'model:deepseek-v2',label:'已登记模型',
      ready:false,unresolved_capability_codes:['Q20-MODEL'],value:{model_profile_ref:'deepseek-v2'}}]);
    }else list([]);
    return;
   }
   if(request.method==='GET'&&url.pathname==='/api/v1/code-execution-profiles'){
    list(scenario==='version-details'?[originalProfile,...profiles]:profiles);return;
   }
   if(request.method==='GET'&&url.pathname==='/api/v1/code-execution-profiles/9/versions'){
    list([profileVersion]);return;
   }
   if(request.method==='GET'&&url.pathname==='/api/v1/code-check-sets'){
    if(scenario==='identity-failed'){
     response.statusCode=503;
     response.end(JSON.stringify({success:false,data:null,error:{code:'STORAGE_UNAVAILABLE',message:'暂时无法读取配置，连接恢复后请重试',details:{capability_codes:['DATABASE']}},meta:{request_id:randomUUID()}}));
    }else list(checks);
    return;
   }
   const versionMatch=/^\/api\/v1\/code-check-sets\/([0-9]+)\/versions$/.exec(url.pathname);
   if(request.method==='GET'&&versionMatch){
    const id=Number(versionMatch[1]);
    if(!checks.some(row=>row.id===id)){response.statusCode=404;response.end();return;}
    if(scenario==='version-failed'){
     response.statusCode=503;
     response.end(JSON.stringify({success:false,data:null,error:{code:'STORAGE_UNAVAILABLE',message:'版本暂不可读',details:{capability_codes:['DATABASE']}},meta:{request_id:randomUUID()}}));
    }else list(id===7?[secondCheckVersion,checkVersion]:[]);
    return;
   }
   if(request.method==='POST'&&url.pathname==='/api/v1/code-check-sets'){
    let body='';
    request.setEncoding('utf8');request.on('data',chunk=>{body+=chunk;});
    request.on('end',()=>{
     const key=request.headers['idempotency-key'],input=JSON.parse(body);
     if(typeof key!=='string'||identityReceipts.has(key)||typeof input.name!=='string'||Object.keys(input).length!==1){
      response.statusCode=400;response.end('Invalid isolated identity request');return;
     }
     mutations.push({key,body});
     const id=41+mutations.length,result={resource_kind:'CHECK_SET',resource_id:id};
     checks.unshift({id,name:input.name,latest_version_id:null});
     identityReceipts.set(key,result);
     if(scenario==='identity-lost'){
      response.writeHead(201,{'Content-Length':1000});
      response.write('{');
      setTimeout(()=>response.destroy(),80);
     }
     else setTimeout(()=>success(result,201),1200);
    });
    return;
   }

   if(request.method==='POST'&&url.pathname==='/api/v1/code-execution-profiles'){
    let body='';
    request.setEncoding('utf8');request.on('data',chunk=>{body+=chunk;});
    request.on('end',()=>{
     const key=request.headers['idempotency-key'];
     if(key!==originalKeys.get(url.pathname)||body!=='{"name":"NOT_VISIBLE_BODY"}'){
      response.statusCode=400;response.end('Original replay identity or body changed');return;
     }
     recoveryWrites.push({action:'replay',key,body});
     const result={resource_kind:'EXECUTION_PROFILE',resource_id:90};
     identityReceipts.set(key,result);
     profiles.unshift({id:90,name:'恢复的执行配置',latest_version_id:null});
     success(result,201);
    });
    return;
   }
   if(request.method==='POST'&&url.pathname==='/api/v1/code-repositories'){
    let body='';
    request.setEncoding('utf8');request.on('data',chunk=>{body+=chunk;});
    request.on('end',()=>{
     const key=request.headers['idempotency-key'];
     if(scenario==='registration-create'||scenario==='registration-lost'){
      const expected=scenario==='registration-create'
       ?{name:'待修正仓库',root_path:'C:\\test\\wrong-git'}:{name:'新登记仓库',root_path:'C:\\test\\saved-git'};
      if(typeof key!=='string'||key===originalKeys.get(url.pathname)||registrations.has(key)||body!==JSON.stringify(expected)){
       response.statusCode=400;response.end('Invalid new registration command');return;
      }
      const result={resource_kind:'REPOSITORY',resource_id:25+registrations.size,
       operation_id:81+registrations.size,operation_status:'PENDING'};
      registrations.set(key,{...expected,key,result,terminal:null});
      registrationWrites.push({key,body});
      if(scenario==='registration-lost'){
       response.writeHead(202,{'Content-Length':1000});response.write('{');
       setTimeout(()=>response.destroy(),80);
      }else setTimeout(()=>success(result,202),500);
      return;
     }
     if(key!==originalKeys.get(url.pathname)||body!==JSON.stringify({name:'NOT_VISIBLE_BODY',root_path:'C:\\isolated-repository'})){
      response.statusCode=400;response.end('Original registration key or body changed');return;
     }
     recoveryWrites.push({action:'register',key,body});
     response.statusCode=503;
     response.end(JSON.stringify({success:false,data:null,error:{code:'CONFIG_NOT_READY',message:'所需执行配置尚未就绪',
      details:{capability_codes:['Q20-WINDOWS','Q20-GIT']}},meta:{request_id:randomUUID()}}));
    });
    return;
   }
   if(request.method==='POST'&&url.pathname==='/api/v1/command-intents/close'){
    let body='';
    request.setEncoding('utf8');request.on('data',chunk=>{body+=chunk;});
    request.on('end',()=>{
     const key=request.headers['idempotency-key'],path='/api/v1/code-repositories';
     if(key!==originalKeys.get(path)||body!=='{"method":"POST","path":"/api/v1/code-repositories"}'){
      response.statusCode=400;response.end('Original close identity or body changed');return;
     }
     recoveryWrites.push({action:'close',key,body});
     if(recoveryWrites.filter(row=>row.action==='close').length===1){
      response.writeHead(200,{'Content-Length':1000});
      response.write('{');
      setTimeout(()=>response.destroy(),80);
      return;
     }
     success({close_status:'CLOSED',original_receipt:{
      lookup_status:'FOUND',record_status:'CLOSED',original_http_status:409,
      original_outcome:{success:false,data:null,error:{code:'COMMAND_CLOSED',message:'原请求已关闭，不再执行',
       details:{method:'POST',path,closed_at:'2026-11-07T00:00:00.000Z'}}},
      task_id:null,testing_task_id:null,operation_id:null,
     }});
    });
    return;
   }
   if(request.method!=='GET'||url.pathname!=='/api/v1/code-command-receipts'){response.statusCode=500;response.end('Unexpected product request');return;}
   const send=()=>{
    const key=url.searchParams.get('request_key'),path=url.searchParams.get('path');
    if(!originalKeys.has(path))originalKeys.set(path,key);
    const refresh=refreshes.get(key);
    if(refresh&&path===refreshPath&&url.searchParams.get('method')==='POST'){
     success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:202,
      original_outcome:{success:true,data:refresh.result,error:null},task_id:null,testing_task_id:null,
      operation_id:refresh.result.operation_id});return;
    }
    const registration=registrations.get(key);
    if(registration&&path==='/api/v1/code-repositories'&&url.searchParams.get('method')==='POST'){
     success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:202,
      original_outcome:{success:true,data:registration.result,error:null},task_id:null,testing_task_id:null,
      operation_id:registration.result.operation_id});return;
    }
    const identity=identityReceipts.get(key);
    if(identity&&['/api/v1/code-check-sets','/api/v1/code-execution-profiles'].includes(path)&&url.searchParams.get('method')==='POST'){
     success({lookup_status:'FOUND',record_status:'SUCCEEDED',original_http_status:201,
      original_outcome:{success:true,data:identity,error:null},task_id:null,testing_task_id:null,operation_id:null});return;
    }
    if(scenario==='failed'){
     response.statusCode=503;response.end(JSON.stringify({success:false,data:null,error:{code:'STORAGE_UNAVAILABLE',
      message:'原结果暂时无法读取，请保留原请求并在连接恢复后重新核对。这是一条用于窄窗口检查的多行提示。',
      details:{capability_codes:['DATABASE']}},meta:{request_id:randomUUID()}}));
    }else response.end(JSON.stringify({success:true,error:null,meta:{request_id:randomUUID()},data:{
     lookup_status:'NOT_FOUND',record_status:null,original_http_status:null,original_outcome:null,
     task_id:null,testing_task_id:null,operation_id:null,
    }}));
   };
   if(scenario==='delayed')setTimeout(send,1600);else send();return;
  }
  const path=url.pathname==='/'||['/settings/code','/settings/testing','/testing','/testing/plans'].includes(url.pathname)||/^\/testing\/tasks\/[0-9]+$/.test(url.pathname)||(url.pathname==='/requirements'||/^\/requirements\/[0-9]+(?:\/documents\/[0-9]+\/code-tasks)?$|^\/code-tasks\/[0-9]+$/.test(url.pathname))?'/index.html':url.pathname,body=files.get(path);
  if(!body){response.statusCode=404;response.end();return;}
  response.setHeader('Content-Type',({'.js':'text/javascript','.css':'text/css','.html':'text/html','.svg':'image/svg+xml'})[extname(path)]??'application/octet-stream');response.end(body);
 });
 await new Promise((done,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',done);});
 const origin='http://127.0.0.1:'+server.address().port,session='w20-settings-'+randomUUID().slice(0,8);
 const config=join(work,'settings-cli.json');await mkdir(join(work,'temp'),{recursive:true});
 await writeFile(config,JSON.stringify({browser:{browserName:'chromium',isolated:true,launchOptions:{
  executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,
  args:['--disable-background-networking','--disable-component-update','--disable-sync']},
 contextOptions:{serviceWorkers:'block',viewport:{width:1280,height:800}}},outputDir:join(work,'artifacts'),outputMode:'stdout'}),{flag:'wx'});
 const env={...process.env,PWTEST_DAEMON_SESSION_DIR:join(work,'daemon'),TEMP:join(work,'temp'),TMP:join(work,'temp')};
 async function cli(...commands){
  const result=await exec(process.execPath,[entry,'-s='+session,...commands],{cwd:work,env,windowsHide:true,timeout:60000,maxBuffer:4*1024*1024,encoding:'utf8'});
  if(result.stdout.includes('### Error'))throw Error(result.stdout);return result.stdout;
 }
 async function code(source){
  try{
   const output=await cli('run-code',source);
   if(!/"passed"\s*:\s*true/.test(output))throw Error(output);return output;
  }catch(error){
   if(['tasks','testing-settings','testing-plan-editor','testing-task-workspace','role-reconciliation','repair-reconciliation'].includes(mode))console.log('BROWSER_PROBE_REQUESTS',requests.slice(-22),await cli('snapshot').catch(()=> 'snapshot unavailable'));
   throw error;
  }
 }
 async function refresh(){
  const snapshot=await cli('snapshot'),match=/button "重新核对".*\[ref=([a-z0-9]+)\]/.exec(snapshot);
  if(!match)throw Error('Current refresh control missing\n'+snapshot);
  await cli('click',match[1]);
 }

 try{

  if(mode==='testing-task-workspace'){
   const rootTask=origin+'/testing',state=JSON.stringify(origin+'/__scenario?state=');
   const limits=Object.fromEntries(['max_model_requests','max_active_seconds','max_check_output_bytes','max_check_cases','max_case_steps','max_case_payload_bytes','max_input_bytes','query_timeout_seconds','send_timeout_seconds','graceful_stop_seconds','force_stop_wait_seconds'].map(key=>[key,2]));
   testingProfiles.push({id:1,version:1,name:'独立隔离配置',runner_refs:['fixture-runner'],environment_refs:['fixture-runtime'],
    commands:[],model_binding:null,limits,admission_refs:['fixture-admission'],created_at:testingTime,ready:false,reason_codes:['Q20-CHECKS']});
   await cli('open',rootTask,'--config',config,'--idle-timeout=30000');
   await cli('resize','1024','850');
   await code("async(page)=>{page.setDefaultTimeout(12000);await page.getByText('当前没有测试任务',{exact:true}).waitFor();await page.getByRole('button',{name:'新建测试任务',exact:true}).click();const dialog=page.getByRole('dialog',{name:'创建独立测试任务',exact:true});if(!await dialog.getByRole('button',{name:'创建测试任务',exact:true}).isDisabled())throw Error('Blank Testing task can submit');await dialog.getByRole('combobox',{name:'依据需求',exact:true}).selectOption('1');await dialog.getByRole('combobox',{name:'主设计文档',exact:true}).selectOption('41');await dialog.getByRole('combobox',{name:'固定主 Revision',exact:true}).selectOption('24');await dialog.getByRole('textbox',{name:'已登记快照编号',exact:true}).fill('25');await dialog.getByRole('button',{name:'取消',exact:true}).click();await page.getByRole('button',{name:'新建测试任务',exact:true}).click();if(await dialog.getByRole('textbox',{name:'已登记快照编号',exact:true}).inputValue()!=='25')throw Error('Cancel lost Testing draft');await dialog.getByRole('button',{name:'核对固定来源',exact:true}).click();await dialog.getByText(/固定来源 #25/).waitFor();await dialog.getByRole('combobox',{name:'独立测试配置',exact:true}).selectOption('1');await dialog.getByRole('button',{name:'批准独立测试授权',exact:true}).click();const approve=page.getByRole('dialog',{name:'批准独立测试授权',exact:true});await approve.getByRole('button',{name:'确认批准',exact:true}).click();await dialog.getByText(/授权 #7/).waitFor();await dialog.getByRole('button',{name:'创建测试任务',exact:true}).click();await dialog.getByRole('alert').filter({hasText:'本次操作结果待核实'}).waitFor();await dialog.getByRole('button',{name:'取消',exact:true}).click();return {passed:true};}");
   await cli('resize','1280','850');
   await code("async(page)=>{page.setDefaultTimeout(12000);await page.request.get("+state+"+'testing-task-recover');await page.getByRole('button',{name:'核对独立任务原请求',exact:true}).click();await page.getByRole('button',{name:'打开测试任务 #1',exact:true}).click();await page.getByRole('heading',{name:'独立测试任务 #1',exact:true}).waitFor();await page.getByRole('heading',{name:'待准备',exact:true}).waitFor();await page.getByRole('button',{name:'报告',exact:true}).click();await page.getByText('此任务尚无测试报告',{exact:true}).waitFor();await page.getByRole('button',{name:'概览',exact:true}).click();await page.getByRole('button',{name:'终止测试任务',exact:true}).click();const dialog=page.getByRole('dialog',{name:'终止测试任务',exact:true});await dialog.getByRole('button',{name:'确认',exact:true}).click();await page.getByRole('heading',{name:'正在终止',exact:true}).waitFor();await page.getByRole('heading',{name:'终止 #37 · 处理中',exact:true}).waitFor();await page.request.get("+state+"+'testing-stop-done');await page.getByRole('heading',{name:'已终止',exact:true}).waitFor();await page.getByRole('heading',{name:'终止 #37 · 已完成',exact:true}).waitFor();return {passed:true};}");
   await cli('resize','1920','950');
   await code("async(page)=>{page.setDefaultTimeout(12000);await page.getByRole('button',{name:'返回测试任务列表',exact:true}).click();const list=page.getByRole('region',{name:'测试任务目录',exact:true});await list.getByRole('button',{name:'测试任务 #1',exact:true}).waitFor();await list.getByRole('combobox',{name:'状态',exact:true}).selectOption('DRAFT');await list.getByRole('button',{name:'应用筛选',exact:true}).click();await list.getByText('没有符合当前筛选的测试任务',{exact:true}).waitFor();await list.getByRole('button',{name:'清除筛选',exact:true}).click();await list.getByRole('button',{name:'测试任务 #1',exact:true}).waitFor();await page.goto("+JSON.stringify(rootTask+'/tasks/1?operation_id=99')+");await page.getByRole('region',{name:'独立任务原操作',exact:true}).getByRole('alert').waitFor();if(await page.getByRole('heading',{name:'终止 #37 · 已完成',exact:true}).count())throw Error('Foreign operation fell back to another operation');return {passed:true};}");
   await cli('resize','360','820');
   await code("async(page)=>{page.setDefaultTimeout(12000);await page.request.get("+state+"+'testing-report-findings-error');await page.goto("+JSON.stringify(rootTask+'/tasks/1?tab=report&report_id=17')+");await page.getByRole('heading',{name:'报告 #17 · 失败',exact:true}).waitFor();const findings=page.getByRole('region',{name:'测试发现项',exact:true});await findings.getByRole('alert').waitFor();if(await findings.getByText('此报告没有已记录的发现项',{exact:true}).count())throw Error('Finding load failure displayed as empty');await page.request.get("+state+"+'testing-report-review-lost');await findings.getByRole('button',{name:'重试读取',exact:true}).click();await findings.getByRole('button',{name:'编辑发现项 #44 归因',exact:true}).click();await findings.getByRole('combobox',{name:'归因分类',exact:true}).selectOption('PRODUCT');await findings.getByRole('textbox',{name:'归因理由',exact:true}).fill('核对固定原文和真实失败');await page.reload();await findings.getByRole('button',{name:'编辑发现项 #44 归因',exact:true}).click();if(await findings.getByRole('textbox',{name:'归因理由',exact:true}).inputValue()!=='核对固定原文和真实失败')throw Error('Reload lost finding draft');await findings.getByRole('button',{name:'提交归因',exact:true}).click();const modal=page.getByRole('dialog',{name:'确认测试发现项归因',exact:true});await modal.getByRole('button',{name:'保存归因',exact:true}).click();await findings.getByRole('alert').filter({hasText:'本次操作结果待核实'}).waitFor();await page.request.get("+state+"+'testing-report-recover');await findings.getByRole('button',{name:'核对独立任务原请求',exact:true}).click();await findings.getByRole('heading',{name:'发现项 #44 · 产品实现偏差',exact:true}).waitFor();return {passed:true};}");
   await cli('resize','1280','850');
   await code("async(page)=>{page.setDefaultTimeout(12000);await page.request.get("+state+"+'testing-report-revoked');await page.getByRole('button',{name:'核对当前报告资格',exact:true}).click();await page.getByRole('list',{name:'独立测试资格原因',exact:true}).getByText('原测试资产已撤销',{exact:true}).waitFor();await page.getByRole('heading',{name:'报告 #17 · 失败',exact:true}).waitFor();await page.getByRole('button',{name:'查看原验证 #32',exact:true}).click();await page.getByRole('heading',{name:'原验证 #32 · 已结束',exact:true}).waitFor();await page.getByRole('button',{name:'查看用例详情',exact:true}).click();await page.getByText('原受控用例',{exact:true}).waitFor();await page.getByText('已记录失败断言，部分证据缺失。',{exact:true}).waitFor();await page.goto("+JSON.stringify(rootTask+'/tasks/1?tab=report&report_id=999')+");await page.getByRole('alert').filter({hasText:'所选报告或验证不属于此任务'}).waitFor();return {passed:true};}");
   await code("async(page)=>{page.setDefaultTimeout(12000);await page.request.get("+state+"+'testing-report-usage-empty');await page.goto("+JSON.stringify(rootTask+'/tasks/1?tab=usage')+");const usage=page.getByRole('region',{name:'独立模型用量',exact:true});await usage.getByText('此任务尚无模型调用记录',{exact:true}).waitFor();await page.request.get("+state+"+'testing-report-usage');await usage.getByRole('button',{name:'核对模型调用',exact:true}).click();await usage.getByText('输入 0 · 输出 未记录',{exact:true}).waitFor();await usage.getByRole('button',{name:'查看调用 #58',exact:true}).click();const detail=usage.getByRole('region',{name:'原调用 #58',exact:true});await detail.getByText('原预留 0.125000 元 · 结算尚无记录',{exact:true}).waitFor();await detail.getByText('原请求',{exact:true}).click();if(!(await detail.getByRole('textbox',{name:'原请求',exact:true}).inputValue()).includes('fixed-model'))throw Error('Original Testing request missing');await detail.getByRole('button',{name:'关闭调用详情',exact:true}).click();if(await detail.count())throw Error('Original audit drawer retained');return {passed:true};}");
   await cli('resize','360','820');
   const executionHome=JSON.stringify(rootTask+'/tasks/1');
   await code("async(page)=>{page.setDefaultTimeout(12000);await page.request.get("+state+"+'testing-execution-ready');await page.goto("+executionHome+");const run=page.getByRole('button',{name:'开始独立测试',exact:true});const resume=page.getByRole('button',{name:'继续原测试',exact:true});await page.getByRole('heading',{name:'就绪',exact:true}).waitFor();if(!await resume.isDisabled())throw Error('Ready task offered resume');await run.click();let modal=page.getByRole('dialog',{name:'开始独立测试',exact:true});await modal.getByText('执行固定计划版本 #11 与测试包 #29。',{exact:true}).waitFor();await modal.getByRole('button',{name:'取消',exact:true}).click();await run.click();await modal.getByRole('button',{name:'确认',exact:true}).click();await page.getByRole('alert').filter({hasText:'本次操作结果待核实'}).waitFor();await page.request.get("+state+"+'testing-execution-wait');await page.getByRole('button',{name:'核对独立任务原请求',exact:true}).click();await page.getByRole('heading',{name:'独立测试 #45 · 待核对',exact:true}).waitFor();if(!await run.isDisabled())throw Error('Unknown original allowed another RUN');if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Narrow task actions overflow');return {passed:true};}");
   await cli('resize','1280','850');
   await code("async(page)=>{page.setDefaultTimeout(12000);await page.getByRole('button',{name:'继续原测试',exact:true}).click();await page.getByRole('dialog',{name:'继续原测试',exact:true}).getByRole('button',{name:'确认',exact:true}).click();await page.getByRole('heading',{name:'继续测试 #46 · 已完成',exact:true}).waitFor();await page.goto("+JSON.stringify(rootTask+'/tasks/1?operation_id=45')+");await page.getByRole('heading',{name:'独立测试 #45 · 处理中',exact:true}).waitFor();await page.getByRole('button',{name:'核对原操作',exact:true}).click();const modal=page.getByRole('dialog',{name:'核对原操作',exact:true});await modal.getByText('核对原操作 #45 的已保存状态。',{exact:true}).waitFor();await modal.getByRole('button',{name:'确认',exact:true}).click();await page.getByRole('heading',{name:'核对原操作 #47 · 已完成',exact:true}).waitFor();return {passed:true};}");
   await cli('resize','360','820');
   await code("async(page)=>{page.setDefaultTimeout(12000);await page.request.get("+state+"+'testing-planning-blocked');await page.goto("+executionHome+");const action=page.getByRole('button',{name:'AI 起草计划',exact:true});await action.waitFor();if(!await action.isDisabled())throw Error('Missing model admission offered AI draft');await page.request.get("+state+"+'testing-planning-ready');await page.getByRole('button',{name:'核对任务状态',exact:true}).click();await action.click();const modal=page.getByRole('dialog',{name:'AI 起草计划',exact:true});await modal.getByText(/按此任务的模型预算记账/).waitFor();await modal.getByRole('button',{name:'取消',exact:true}).click();await action.click();await modal.getByRole('button',{name:'确认',exact:true}).click();await page.getByRole('alert').filter({hasText:'本次操作结果待核实'}).waitFor();await page.request.get("+state+"+'testing-planning-running');await page.getByRole('button',{name:'核对独立任务原请求',exact:true}).click();await page.getByRole('heading',{name:'AI 起草计划 #49 · 处理中',exact:true}).waitFor();if(!await action.isDisabled())throw Error('Original AI draft can be repeated while active');if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Narrow AI draft control overflows');return {passed:true};}");
   await cli('resize','1280','850');
   await code("async(page)=>{page.setDefaultTimeout(12000);await page.request.get("+state+"+'testing-planning-done');await page.goto("+JSON.stringify(rootTask+'/tasks/1?operation_id=49')+");await page.getByRole('heading',{name:'AI 起草计划 #49 · 已完成',exact:true}).waitFor();await page.getByRole('button',{name:'计划',exact:true}).click();await page.getByText('原起草结果 · 计划版本 #11',{exact:true}).waitFor();await page.getByText('此任务尚未绑定测试计划和测试包',{exact:true}).waitFor();return {passed:true};}");
   if(planModelWrites.length!==1||JSON.stringify(planModelWrites[0].input)!==JSON.stringify({expected_state_version:1}))
    throw Error('Original AI draft input was missing or repeated');
   if(executionWrites.length!==3||executionWrites.map(row=>row.action).join(',')!=='run,resume,reconcile'||
      executionWrites[0].input.expected_state_version!==1||executionWrites[1].input.operation_id!==45||
      executionWrites[1].input.expected_state_version!==3||executionWrites[2].input.operation_id!==45||
      executionWrites[2].input.expected_state_version!==4)throw Error('Testing original execution inputs differ');
   await code("async(page)=>{page.setDefaultTimeout(12000);await page.setViewportSize({width:360,height:800});await page.request.get("+state+"+'testing-report-handoff-historical');await page.goto("+JSON.stringify(rootTask+'/tasks/1?tab=report&report_id=17')+");const findings=page.getByRole('region',{name:'测试发现项',exact:true});const start=findings.getByRole('button',{name:'交给 Coding',exact:true});await start.click();const panel=findings.getByRole('region',{name:'交给 Coding',exact:true});await panel.getByText('该报告的候选或固定设计已非当前来源',{exact:true}).waitFor();if(!await panel.getByRole('button',{name:'保存到 Coding 缺陷报告',exact:true}).isDisabled())throw Error('Historical source can be imported');await page.request.get("+state+"+'testing-report-handoff-ready');await page.setViewportSize({width:1280,height:850});await page.reload();await start.click();await panel.getByRole('button',{name:'保存到 Coding 缺陷报告',exact:true}).click();const dialog=page.getByRole('dialog',{name:'交给 Coding',exact:true});await dialog.getByRole('button',{name:'取消',exact:true}).click();await panel.getByRole('button',{name:'保存到 Coding 缺陷报告',exact:true}).click();await dialog.getByRole('button',{name:'确认登记',exact:true}).click();await findings.getByRole('alert').filter({hasText:'本次操作结果待核实'}).waitFor();await page.reload();await findings.getByRole('button',{name:'核对原缺陷请求',exact:true}).click();await findings.getByText('缺陷 #9',{exact:true}).waitFor();if(await findings.evaluate(e=>e.scrollWidth>e.clientWidth+1))throw Error('Finding handoff overflow');return {passed:true};}");
   if(defectWrites.length!==1||JSON.stringify(defectWrites[0].input)!==JSON.stringify({candidate_id:202,expected_state_version:32,testing_finding_id:44}))
    throw Error('Finding handoff did not preserve the original Coding intent');
   if(findingWrites.length!==1||findingWrites[0].input.expected_state_version!==1||findingWrites[0].input.classification!=='PRODUCT')
    throw Error('Finding original was missing or repeated');
   if(testingTaskWrites.length!==1||testingStopWrites.length!==1||testingWrites.length!==1||
      testingTaskWrites[0].input.snapshot_id!==25||testingTaskWrites[0].input.candidate_id!==null||
      testingTaskWrites[0].input.design_revision_id!==24||testingTaskWrites[0].input.authorization_id!==7||
      testingStopWrites[0].expected_state_version!==1||requests.filter(item=>item.startsWith('POST /api/v1/code-tasks')).join()!=='POST '+defectPath)
    throw Error('Independent Testing wrote a duplicate or Coding command');
   console.log('V20_TESTING_TASK_WORKSPACE_PASSED '+JSON.stringify({creates:testingTaskWrites.length,stops:testingStopWrites.length,reviews:findingWrites.length,execution:executionWrites.length,drafts:planModelWrites.length,defects:defectWrites.length,widths:[360,1024,1280,1920]}));
   return;
  }

  if(mode==='testing-plan-editor'){
   plans.push({id:2,name:'隔离编辑计划',created_at:testingTime,versions_count:0});
   const rootPlan=origin+'/testing/plans?plan_id=2';
   const state=JSON.stringify(origin+'/__scenario?state=');
   await cli('open',rootPlan,'--config',config,'--idle-timeout=30000');
   await cli('resize','360','820');
   await code("async(page)=>{page.setDefaultTimeout(12000);await page.getByText('新建计划草稿',{exact:true}).click();const editor=page.locator('form').filter({has:page.getByRole('button',{name:'创建计划版本',exact:true})});const save=editor.getByRole('button',{name:'创建计划版本',exact:true});if(!await save.isDisabled())throw Error('Blank basis was submittable');await editor.getByRole('combobox',{name:'依据需求',exact:true}).selectOption('1');await editor.getByRole('combobox',{name:'主设计文档',exact:true}).selectOption('41');await editor.getByRole('combobox',{name:'固定主 Revision',exact:true}).selectOption('24');await editor.getByRole('button',{name:'添加行为',exact:true}).click();await editor.getByText(/行为 1 · 待填写/).click();await editor.getByRole('textbox',{name:'行为名称',exact:true}).fill('原文要求的命令行为');await editor.getByRole('checkbox',{name:'验收',exact:true}).check();await editor.getByRole('combobox',{name:'覆盖方式',exact:true}).selectOption('AUTO');await editor.getByRole('combobox',{name:'引用来源',exact:true}).selectOption('24');const quote=editor.getByRole('textbox',{name:'原文选段',exact:true});await quote.focus();await quote.press('Control+a');await editor.getByRole('button',{name:'加入所选原文',exact:true}).click();await editor.locator('blockquote').filter({hasText:'固定设计原文。'}).waitFor();return {passed:true};}");
   await code("async(page)=>{page.setDefaultTimeout(12000);const editor=page.locator('form').filter({has:page.getByRole('button',{name:'创建计划版本',exact:true})});await editor.getByRole('button',{name:'添加用例',exact:true}).click();await editor.getByText(/用例 1 · 待填写/).click();await editor.getByRole('textbox',{name:'用例名称',exact:true}).fill('保留 HTTP 用例');await editor.getByRole('combobox',{name:'公开范围',exact:true}).selectOption('HELD_OUT');await editor.getByRole('combobox',{name:'固定 Driver',exact:true}).selectOption('HTTP');await editor.getByRole('textbox',{name:'用例超时（秒）',exact:true}).fill('15');await editor.getByRole('checkbox',{name:'原文要求的命令行为',exact:true}).check();await editor.getByRole('button',{name:'添加步骤',exact:true}).click();await editor.getByRole('textbox',{name:'受管端点标识',exact:true}).fill('fixed-http');await editor.getByRole('textbox',{name:'受管相对路径',exact:true}).fill('/ok');await editor.getByRole('button',{name:'确认步骤',exact:true}).click();await editor.getByRole('button',{name:'添加断言',exact:true}).click();await editor.getByRole('combobox',{name:'对应请求步骤',exact:true}).selectOption({label:'步骤 1'});await editor.getByRole('textbox',{name:'预期值',exact:true}).fill('200');await editor.getByRole('button',{name:'确认断言',exact:true}).click();await editor.getByRole('button',{name:'编辑断言 1',exact:true}).click();await editor.getByRole('textbox',{name:'预期值',exact:true}).fill('204');await editor.getByRole('button',{name:'确认断言',exact:true}).click();if(await editor.evaluate(e=>e.scrollWidth>e.clientWidth+1))throw Error('Narrow draft editor overflows');return {passed:true};}");
   await cli('goto',rootPlan);
   await cli('resize','1280','850');
   await code("async(page)=>{page.setDefaultTimeout(12000);await page.getByText('新建计划草稿 · 有本地输入',{exact:true}).click();await page.getByText(/用例 1 · 保留 HTTP 用例/).waitFor();await page.getByRole('button',{name:'创建计划版本',exact:true}).click();await page.getByText('计划草稿已创建',{exact:true}).waitFor();if(!page.url().includes('plan_version_id=11'))throw Error('Created original version was not selected');return {passed:true};}");
   await code("async(page)=>{page.setDefaultTimeout(12000);await page.getByText('编辑计划草稿',{exact:true}).click();const current=page.getByRole('form',{name:'当前计划版本草稿',exact:true});await current.getByRole('button',{name:'添加待解决问题',exact:true}).click();const value=current.getByRole('textbox',{name:'待解决问题 1',exact:true});await value.fill('本地输入须保留');await page.request.get("+state+"+'draft-conflict');await page.getByRole('button',{name:'保存计划草稿',exact:true}).click();await page.getByRole('region',{name:'草稿版本冲突'}).waitFor();if(await value.inputValue()!=='本地输入须保留')throw Error('Conflict erased current draft');await page.getByRole('button',{name:'保留本地输入并采用当前版本号',exact:true}).click();await page.request.get("+state+"+'draft-lost');await page.getByRole('button',{name:'保存计划草稿',exact:true}).click();await page.getByRole('alert').filter({hasText:'本次操作结果待核实'}).waitFor();return {passed:true};}");
   await cli('goto',rootPlan+'&plan_version_id=11');
   await cli('resize','1920','950');
   await code("async(page)=>{page.setDefaultTimeout(12000);await page.request.get("+state+"+'draft-recover');const saved=page.getByRole('region',{name:'固定测试计划版本',exact:true});await saved.getByText('本地输入须保留',{exact:true}).waitFor();const pending=page.getByRole('button',{name:'核对原计划请求',exact:true});if(await pending.count())await pending.click();await page.getByText('编辑计划草稿',{exact:true}).waitFor();await page.request.get("+state+"+'draft-history');await page.reload();await saved.getByText('已发布',{exact:true}).waitFor();if(await page.getByText('编辑计划草稿',{exact:true}).count())throw Error('Published plan became writable');return {passed:true};}");
   await code("async(page)=>{page.setDefaultTimeout(12000);const packs=page.getByRole('region',{name:'测试包目录',exact:true});await packs.getByText('所选计划尚无测试包',{exact:true}).waitFor();const add=packs.getByRole('button',{name:'登记测试包草稿',exact:true});await add.click();const dialog=page.getByRole('dialog',{name:'登记测试包草稿'});await dialog.getByRole('button',{name:'取消',exact:true}).click();await add.click();await dialog.getByRole('button',{name:'确认登记',exact:true}).click();await packs.getByRole('alert').filter({hasText:'本次操作结果待核实'}).waitFor();await page.request.get("+state+"+'draft-pack-recover');await page.getByRole('button',{name:'核对原计划请求',exact:true}).click();await packs.getByRole('button',{name:'测试包 1 · 草稿',exact:true}).click();await packs.getByText('测试包尚未封存',{exact:true}).waitFor();if(!page.url().includes('pack_id=29'))throw Error('Pack deep-link lacks fixed ancestry');await page.request.get("+state+"+'draft-pack-foreign');await page.reload();await packs.getByRole('alert').waitFor();if(await packs.getByRole('region',{name:'所选测试包'}).count())throw Error('A pack crossed the fixed plan scope');return {passed:true};}");
   await code("async(page)=>{page.setDefaultTimeout(12000);await page.request.get("+state+"+'seal-lost');await page.reload();const panel=page.getByRole('region',{name:'测试包封存',exact:true});const button=panel.getByRole('button',{name:'编译并封存测试包',exact:true});await button.click();const dialog=page.getByRole('dialog',{name:'编译并封存测试包',exact:true});await dialog.getByRole('button',{name:'取消',exact:true}).click();await button.click();await dialog.getByRole('button',{name:'确认封存',exact:true}).click();await panel.getByRole('alert').filter({hasText:'本次操作结果待核实'}).waitFor();await page.request.get("+state+"+'seal-running');await page.getByRole('button',{name:'核对原计划请求',exact:true}).click();await panel.getByRole('heading',{name:'原封存操作 #34',exact:true}).waitFor();await panel.getByText('封存原测试资源 · 处理中',{exact:true}).waitFor();if(!await button.isDisabled())throw Error('Active seal was submittable');await page.request.get("+state+"+'seal-complete');await panel.getByText('保存封存版本 · 已完成',{exact:true}).waitFor();const selected=page.getByRole('region',{name:'所选测试包',exact:true});await selected.getByRole('heading',{name:'测试包 1 · 已封存',exact:true}).waitFor();await page.reload();await panel.getByRole('heading',{name:'原封存操作 #34',exact:true}).waitFor();return {passed:true};}");
   await code("async(page)=>{page.setDefaultTimeout(12000);const panel=page.getByRole('region',{name:'预登记参考集',exact:true});await panel.getByText('尚无预登记参考集',{exact:true}).waitFor();if(await panel.count()!==1||await page.getByRole('region',{name:'测试包封存',exact:true}).count()!==1)throw Error('Asset panels were duplicated');await page.getByText('该固定设计尚无预登记参考集',{exact:true}).waitFor();await page.request.get("+state+"+'references-error');await page.reload();await panel.getByRole('alert').waitFor();if(await panel.getByText('尚无预登记参考集',{exact:true}).count())throw Error('Reference fetch error became an empty state');await page.request.get("+state+"+'references-ready');await panel.getByRole('button',{name:'重试读取',exact:true}).click();await panel.getByText('reference:ready',{exact:true}).waitFor();await panel.getByText('正向样本 1 · 缺陷对照 2 · 每个样本重复 3 次',{exact:true}).waitFor();await panel.getByText('登记的固定内容暂时不可读取',{exact:true}).waitFor();return {passed:true};}");
   if(sealWrites.length!==1||Object.keys(sealWrites[0]).length!==1||sealWrites[0].expected_state_version!==1)throw Error('The seal lost its original request');
   if(packWrites.length!==1||Object.keys(packWrites[0]).length)throw Error('Pack registration changed the original empty request');
   const [created,conflict,saved]=draftWrites;
   const check=created?.input.plan_content;
   if(draftWrites.length!==3||new Set(draftWrites.map(row=>row.key)).size!==3||
      check?.design_revision_id!==24||check.behaviors[0].basis_refs[0].quote!=='固定设计原文。'||
      check.cases[0].visibility!=='HELD_OUT'||check.cases[0].assertions[0].expected!==204||
      check.cases[0].assertions[0].step_id!==check.cases[0].steps[0].step_id||
      conflict.input.expected_state_version!==1||saved.input.expected_state_version!==2||
      requests.some(row=>row.startsWith('POST /api/v1/testing-tasks')))throw Error('Draft command or fixed scope differs');
   console.log('V20_TESTING_PLAN_EDITOR_PASSED '+JSON.stringify({writes:draftWrites.length,seals:sealWrites.length,widths:[360,1280,1920]}));
   return;
  }

  if(mode==='testing-settings'){
   const testing=origin+'/settings/testing';
   await cli('open',testing,'--config',config,'--idle-timeout=30000');
   await code("async(page)=>{page.setDefaultTimeout(12000);await page.getByRole('heading',{name:'测试配置与恢复',exact:true}).waitFor();await page.getByText('当前没有测试配置',{exact:true}).waitFor();await page.getByText('当前没有待核对操作',{exact:true}).waitFor();if(!await page.getByRole('button',{name:'批准授权',exact:true}).isDisabled())throw Error('Unselected profile allowed authorization');return {passed:true};}");
   await cli('resize','360','800');
   await code("async(page)=>{page.setDefaultTimeout(12000);const state="+JSON.stringify(origin+'/__scenario?state=')+";await page.request.get(state+'testing-no-resources');const form=page.getByText('新建测试配置版本',{exact:true});await form.click();await page.getByText('当前没有已登记的运行器',{exact:true}).waitFor();const publish=page.getByRole('button',{name:'发布测试配置',exact:true});if(!await publish.isDisabled())throw Error('Unregistered resources can be submitted');if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Narrow settings overflow');await page.getByRole('textbox',{name:'新配置名称'}).fill('待恢复配置');await page.reload();await form.click();await page.getByText('当前没有已登记的运行器',{exact:true}).waitFor();if(await page.getByRole('textbox',{name:'新配置名称'}).inputValue()!=='待恢复配置')throw Error('Draft was not restored');await form.click();await page.request.get(state+'testing-options');await form.click();await page.getByRole('checkbox',{name:/固定运行器/}).check();await page.getByRole('checkbox',{name:/固定环境/}).check();await page.getByRole('checkbox',{name:/固定准入依据/}).check();await page.getByRole('textbox',{name:'新配置名称'}).fill('隔离测试配置');const fields=page.getByRole('group',{name:'执行限制'}).getByRole('textbox');for(const input of await fields.all())await input.fill('12');await publish.click();const dialog=page.getByRole('dialog',{name:'发布测试配置版本'});await dialog.getByRole('button',{name:'取消',exact:true}).click();if(await page.getByRole('textbox',{name:'新配置名称'}).inputValue()!=='隔离测试配置')throw Error('Cancel cleared input');await publish.click();await dialog.getByRole('button',{name:'确认发布',exact:true}).click();await page.getByText('已保存测试配置版本',{exact:true}).waitFor();await page.getByRole('region',{name:'所选测试配置',exact:true}).waitFor();return {passed:true};}");
   await cli('resize','1280','800');
   await code("async(page)=>{page.setDefaultTimeout(12000);const state="+JSON.stringify(origin+'/__scenario?state=')+";await page.request.get(state+'testing-list-error');await page.getByRole('button',{name:'重新读取',exact:true}).click();await page.getByText('显示上次读取的配置',{exact:true}).waitFor();await page.request.get(state+'testing-options');await page.getByRole('textbox',{name:'配置名称',exact:true}).fill('无匹配');await page.getByRole('button',{name:'筛选',exact:true}).click();await page.getByText('没有符合筛选条件的测试配置',{exact:true}).waitFor();await page.getByRole('combobox',{name:'授权范围'}).selectOption('PACK_VALIDATION');await page.getByText('测试包验证预算固定为 0 元。',{exact:true}).waitFor();await page.getByRole('button',{name:'批准授权',exact:true}).click();await page.getByRole('dialog',{name:'批准独立测试授权'}).getByRole('button',{name:'确认批准',exact:true}).click();await page.getByRole('alert').filter({hasText:'本次操作结果待核实'}).waitFor();await page.getByRole('region',{name:'待核对操作'}).getByRole('heading',{name:'批准独立测试授权'}).waitFor();return {passed:true};}");
   await cli('goto',testing);
   await cli('resize','360','800');
   await code("async(page)=>{page.setDefaultTimeout(12000);await page.request.get("+JSON.stringify(origin+'/__scenario?state=testing-auth-recover')+");await page.getByRole('button',{name:'重新核对',exact:true}).click();await page.getByText('已核实原独立测试授权 #7',{exact:true}).waitFor();await page.getByText('待绑定 · 0.000000 元',{exact:true}).waitFor();await page.getByText('当前没有待核对操作',{exact:true}).waitFor();if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Narrow recovered authorization overflow');await page.getByRole('button',{name:'代码设置',exact:true}).click();await page.getByRole('heading',{name:'代码设置',exact:true}).waitFor();await page.getByRole('button',{name:'测试配置与恢复',exact:true}).click();await page.getByRole('heading',{name:'测试配置与恢复',exact:true}).waitFor();return {passed:true};}");
   await code("async(page)=>{page.setDefaultTimeout(12000);await page.getByRole('button',{name:'测试计划与资源管理',exact:true}).click();await page.getByText('当前没有测试计划',{exact:true}).waitFor();const planName=page.getByRole('textbox',{name:'新计划名称'});const create=page.getByRole('button',{name:'创建测试计划',exact:true});await planName.fill('😀'.repeat(200));if(await create.isDisabled())throw Error('Two-unit Unicode characters were truncated by the wrong limit');await planName.fill('😀'.repeat(201));if(!await create.isDisabled())throw Error('Plan name exceeded the code-point limit');await planName.fill('隔离测试计划');await create.click();await page.getByText('测试计划已创建',{exact:true}).waitFor();await page.getByText('此计划尚无版本',{exact:true}).waitFor();if(!page.url().endsWith('plan_id=2'))throw Error('Created plan identity did not become selected');return {passed:true};}");
   await cli('resize','1280','800');
   await code("async(page)=>{page.setDefaultTimeout(12000);const state="+JSON.stringify(origin+'/__scenario?state=')+";await page.request.get(state+'plan-version-ready');await page.reload();await page.getByRole('button',{name:'版本 1 · 草稿',exact:true}).click();const detail=page.getByRole('region',{name:'固定测试计划版本',exact:true});await detail.getByText('需求 #1 · 文档 #41 · 固定设计版本 #24',{exact:true}).waitFor();await detail.getByText('固定行为 · 人工检查',{exact:true}).click();await detail.getByText('固定设计原文',{exact:true}).waitFor();await page.getByRole('button',{name:'发布测试计划',exact:true}).click();const publish=page.getByRole('dialog',{name:'发布固定测试计划'});await publish.getByRole('button',{name:'取消',exact:true}).click();await page.getByRole('button',{name:'发布测试计划',exact:true}).click();await publish.getByRole('button',{name:'确认发布',exact:true}).click();await detail.getByText('已发布',{exact:true}).waitFor();const revoke=page.getByRole('button',{name:'撤销测试计划',exact:true});if(!await revoke.isDisabled())throw Error('Revocation was enabled without a reason');await page.getByRole('textbox',{name:'撤销原因',exact:true}).fill('保留原计划内容');await revoke.click();await page.getByRole('dialog',{name:'撤销测试计划资格'}).getByRole('button',{name:'确认撤销',exact:true}).click();await page.getByRole('alert').filter({hasText:'本次操作结果待核实'}).waitFor();await page.request.get(state+'plan-version-recover');await page.getByRole('button',{name:'核对原计划请求',exact:true}).click();await page.getByText('已核实原计划控制结果',{exact:true}).waitFor();await detail.getByText('已撤销',{exact:true}).waitFor();await detail.getByText('撤销原因 保留原计划内容',{exact:true}).waitFor();await page.request.get(state+'plan-foreign');await page.reload();await page.getByRole('alert').waitFor();if(await detail.count())throw Error('Foreign Testing plan version was displayed');return {passed:true};}");
   await cli('goto',origin+'/testing/plans?plan_version_id=11');
   await cli('resize','360','800');
   await code("async(page)=>{page.setDefaultTimeout(12000);await page.getByRole('alert').filter({hasText:'测试计划定位无效'}).waitFor();await page.getByRole('button',{name:'返回测试计划目录',exact:true}).click();await page.getByRole('button',{name:/隔离测试计划/}).waitFor();if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Testing plan navigation overflows');return {passed:true};}");
   for(const width of [1024,1920]){
    await cli('resize',String(width),'850');
    await code("async(page)=>{const area=page.getByRole('region',{name:'测试计划目录'});await area.getByRole('button',{name:/隔离测试计划/}).waitFor();if(await area.evaluate(node=>{const input=node.querySelector('input').getBoundingClientRect(),button=node.querySelector('button[type=submit]').getBoundingClientRect();return document.documentElement.scrollWidth>innerWidth+1||button.right>innerWidth||(input.left<button.right&&button.left<input.right&&input.top<button.bottom&&button.top<input.bottom)}))throw Error('Plan creation controls overlap');return {passed:true};}");
   }
   if(planWrites.length!==3||planWrites[0].input.name!=='隔离测试计划'||
      planWrites[1].input.expected_state_version!==1||planWrites[2].input.expected_state_version!==2||
      new Set(planWrites.map(row=>row.key)).size!==3)throw Error('Plan command identity or input changed');
   if(testingWrites.length!==2||testingWrites[0].path!==testingProfilePath||testingWrites[1].path!==testingAuthPath||
     testingWrites[1].input.budget_limit_cny!=='0'||testingWrites[0].key===testingWrites[1].key||
     requests.some(row=>row.startsWith('POST /api/v1/testing-tasks')))throw Error('Testing settings changed original request or created a task');
   console.log('V20_TESTING_SETTINGS_PASSED '+JSON.stringify({widths:[360,1024,1280,1920],writes:testingWrites.length,states:['success-empty','missing-resources','session-profile-draft','complete-profile','cancel','approval-zero','read-error-retains','filter-empty','lost-original-approval','navigation','plan-create','fixed-version','manual-publish','original-revoke-recovery','foreign-version-rejected','invalid-plan-selection']}));
   return;
  }

  async function exerciseExecutionRecords(){
   await code("async(page)=>{page.setDefaultTimeout(12000);const records=page.getByRole('region',{name:'执行记录',exact:true});await records.getByText('当前会话记录 1',{exact:true}).waitFor();await records.getByRole('button',{name:'下一页',exact:true}).click();await records.getByText('历史会话记录',{exact:true}).waitFor();await records.getByRole('combobox',{name:'会话范围',exact:true}).selectOption('current');await records.getByText('当前会话记录 1',{exact:true}).waitFor();await records.getByRole('button',{name:'下一页',exact:true}).click();await records.getByText('当前会话记录 21',{exact:true}).waitFor();if(await records.getByText('历史会话记录',{exact:true}).count())throw Error('Historical record crossed current session');await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-start-record-error')+");await records.getByRole('alert').waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-start-completed')+");await records.getByRole('alert').waitFor({state:'hidden'});await records.getByText('当前会话记录 21',{exact:true}).waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-start-record-empty')+");await records.getByText('当前页没有执行记录',{exact:true}).waitFor();await records.getByRole('button',{name:'上一页',exact:true}).click();await records.getByText('暂无执行记录',{exact:true}).waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-start-completed')+");await records.getByText('当前会话记录 1',{exact:true}).waitFor();if(await records.evaluate(e=>e.scrollWidth>e.clientWidth+1))throw Error('Execution records overflow');return {passed:true};}");
  }
  async function exerciseReportLink(recoverPublication){
   await code("async(page)=>{page.setDefaultTimeout(15000);const region=page.getByRole('region',{name:'独立测试',exact:true});"+(recoverPublication?"await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-publication-done')+");await region.getByRole('button',{name:'核对原发布请求',exact:true}).click();":"")+"await region.getByText('代码 #202 已发布供独立测试。',{exact:true}).waitFor();await region.getByText('尚未关联独立测试报告',{exact:true}).waitFor();if(await region.evaluate(e=>e.scrollWidth>e.clientWidth+1))throw Error('Publication controls overflow');await region.getByRole('button',{name:'从此候选创建独立测试',exact:true}).click();const draft=page.getByRole('dialog',{name:'创建独立测试任务',exact:true});await draft.getByText('Coding 任务 #31 · 固定候选 #202',{exact:true}).waitFor();await draft.getByText(/固定来源 #202/).waitFor();if(await draft.getByRole('combobox',{name:'用途',exact:true}).inputValue()!=='ACCEPTANCE')throw Error('Missing candidate acceptance default');if(!await draft.getByRole('button',{name:'创建测试任务',exact:true}).isDisabled())throw Error('Candidate draft bypassed approval');await draft.getByRole('button',{name:'取消',exact:true}).click();await region.getByRole('button',{name:'选择已有报告',exact:true}).click();if(!await region.getByRole('button',{name:'报告尚未生成',exact:true}).isDisabled())throw Error('Missing report can be selected');await region.getByRole('button',{name:'查看报告 #71',exact:true}).click();await region.getByRole('button',{name:'选择此报告',exact:true}).click();const modal=page.getByRole('dialog',{name:'关联独立测试报告',exact:true});await modal.getByRole('button',{name:'确认关联',exact:true}).click();await region.getByRole('alert').filter({hasText:'本次操作结果待核实'}).waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-publication-linked')+");await region.getByRole('button',{name:'核对原报告关联请求',exact:true}).click();const linked=region.getByRole('region',{name:'已关联的独立报告',exact:true});await linked.getByRole('heading',{name:'报告 #71 · 通过',exact:true}).waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-publication-linked-revoked')+");await linked.getByRole('button',{name:'核对报告资格',exact:true}).click();await linked.getByRole('list',{name:'Coding 交付资格原因',exact:true}).getByText('原测试资产已撤销',{exact:true}).waitFor();await linked.getByRole('heading',{name:'报告 #71 · 通过',exact:true}).waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-start-completed')+");await page.goto("+JSON.stringify(origin+'/code-tasks/31?tab=execution')+");await page.getByText('首条执行消息已接收，任务已进入后端阶段。',{exact:true}).waitFor();return {passed:true};}");
  }
  if(codingRecords){
   taskSaved={view:taskView({design_revision_id:24,repository_id:23,base_snapshot_id:52,
    execution_profile_version_id:19,authorization_id:87,material_refs:[],target_branch:'refs/heads/main',budget_limit_cny:'0.125'})};
   const pageUrl=origin+'/code-tasks/31?tab=execution';
   const countUrl=JSON.stringify(origin+'/__scenario?state=task-start-record-count-');
   scenario='task-start-record-count-40';
   await cli('open',pageUrl,'--config',config,'--idle-timeout=30000');
   await cli('resize','360','800');
   await code(`async(page)=>{
    page.setDefaultTimeout(10000);
    const records=page.getByRole('region',{name:'执行记录',exact:true});
    const follow=records.getByRole('button',{name:'跟随最新',exact:true});
    await records.getByText('原命令输出 1',{exact:true}).waitFor();
    if(await follow.getAttribute('aria-pressed')!=='false')throw Error('Follow enabled without user action');
    return {passed:true};
   }`);
   if(!recordReads.length||recordReads.some(row=>row.page!==1))
    throw Error('First read fetched record history beyond page one');
   await code(`async(page)=>{
    page.setDefaultTimeout(12000);
    const records=page.getByRole('region',{name:'执行记录',exact:true});
    const follow=records.getByRole('button',{name:'跟随最新',exact:true});
    const viewport=records.getByRole('group',{name:'记录内容',exact:true});
    const scope=records.getByRole('combobox',{name:'会话范围',exact:true});
    const row=(id)=>records.getByText('原命令输出 '+id,{exact:true});
    const pageLabel=(id)=>records.getByText('第 '+id+' 页',{exact:true});
    const count=(total)=>page.request.get(${countUrl}+total);
    const position=()=>viewport.evaluate(node=>({top:node.scrollTop,end:node.scrollHeight-node.clientHeight}));
    await follow.click();
    await pageLabel(2).waitFor();
    await row(40).waitFor();
    if((await position()).end-(await position()).top>4)throw Error('Latest did not land at the bottom');
    if(await follow.getAttribute('aria-pressed')!=='true')throw Error('Follow did not persist');
    await count(41);
    await pageLabel(3).waitFor();
    await row(41).waitFor();

    await row(41).evaluate(node=>{
     const range=document.createRange();range.selectNodeContents(node);
     const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);
    });
    await count(100);
    const latest=records.getByRole('button',{name:'查看最新（59 条新增）',exact:true});
    await latest.waitFor();
    await pageLabel(3).waitFor();
    if(await page.evaluate(()=>String(getSelection()))!=='原命令输出 41'||await row(100).count())
     throw Error('Text selection lost its original record');
    await latest.click();
    await pageLabel(5).waitFor();
    await row(100).waitFor();

    await viewport.evaluate(node=>{node.scrollTop=0;});
    await count(101);
    await records.getByRole('button',{name:'查看最新（1 条新增）',exact:true}).waitFor();
    await pageLabel(5).waitFor();
    if((await position()).top!==0)throw Error('Latest interrupted reading above the bottom');
    await viewport.evaluate(node=>{node.scrollTop=node.scrollHeight;});
    await pageLabel(6).waitFor();
    await row(101).waitFor();

    await scope.focus();
    await count(102);
    await records.getByRole('button',{name:'查看最新（1 条新增）',exact:true}).waitFor();
    if(await row(102).count()||!(await scope.evaluate(node=>node===document.activeElement)))
     throw Error('Form focus did not hold the record view');
    await scope.evaluate(node=>node.blur());
    await row(102).waitFor();
    if(await records.evaluate(node=>node.scrollWidth>node.clientWidth+1))
     throw Error('Record toolbar overflowed at narrow width');
    return {passed:true};
   }`);
   if(recordReads.some(row=>row.page===4))
    throw Error('Explicit latest action read an intermediate history page');
   await cli('resize','1280','850');
   await code(`async(page)=>{
    const records=page.getByRole('region',{name:'执行记录',exact:true});
    await records.getByText('原命令输出 102',{exact:true}).waitFor();
    if(await records.evaluate(node=>node.scrollWidth>node.clientWidth+1))
     throw Error('Record toolbar overflowed at wide width');
    return {passed:true};
   }`);
   scenario='task-start-completed';
   await code('async(page)=>{await page.goto('+JSON.stringify(pageUrl)+');return {passed:true};}');
   await exerciseExecutionRecords();
   taskStart={key:randomUUID()};
   const operationUrl=JSON.stringify(pageUrl+'&operation_id=');
   await code(`async(page)=>{
    page.setDefaultTimeout(10000);
    const records=page.getByRole('region',{name:'执行记录',exact:true});
    const original=records.getByRole('link',{name:'原操作 #91',exact:true}).first();
    const detail=page.getByRole('region',{name:'原操作 #91',exact:true});
    await original.click();
    await detail.getByText('开始任务 · 已确认',{exact:true}).waitFor();
    if(new URL(page.url()).searchParams.get('operation_id')!=='91')
     throw Error('Original detail is not addressable');
    await detail.getByRole('button',{name:'关闭操作详情',exact:true}).click();
    if(!(await original.evaluate(node=>node===document.activeElement)))
     throw Error('Closing original detail did not restore record focus');
    await original.click();
    await page.reload();
    await detail.getByText('开始任务 · 已确认',{exact:true}).waitFor();
    await page.goto(${operationUrl}+999);
    await page.getByRole('region',{name:'原操作 #999',exact:true}).getByRole('alert').waitFor();
    if(await detail.count())throw Error('Missing original showed a different operation');
    await page.goto(${operationUrl}+'00091');
    await page.getByRole('alert').filter({hasText:'代码任务页面参数无效。'}).waitFor();
    return {passed:true};
   }`);
   await cli('resize','1920','900');
   await code(`async(page)=>{
    const records=page.getByRole('region',{name:'执行记录',exact:true});
    const issues=page.getByRole('region',{name:'原生问题和权限',exact:true});
    await page.goto(${JSON.stringify(pageUrl)});
    await records.getByText('当前会话记录 1',{exact:true}).waitFor();
    const recordBox=await records.boundingBox(),issueBox=await issues.boundingBox();
    if(!recordBox||!issueBox||recordBox.width<640||issueBox.width!==360||issueBox.x-recordBox.x-recordBox.width<15)
     throw Error('Wide execution areas did not share the available workspace');
    return {passed:true};
   }`);
   await cli('resize','360','800');
   await code(`async(page)=>{
    const records=page.getByRole('region',{name:'执行记录',exact:true});
    const issues=page.getByRole('region',{name:'原生问题和权限',exact:true});
    const recordBox=await records.boundingBox(),issueBox=await issues.boundingBox();
    if(!recordBox||!issueBox||recordBox.y<issueBox.y+issueBox.height)
     throw Error('Narrow execution did not put waiting inputs first');
    return {passed:true};
   }`);
   const stateUrl=JSON.stringify(origin+'/__scenario?state=');
   const candidateUrl=JSON.stringify(origin+'/code-tasks/31?tab=code');
   await code(`async(page)=>{
    page.setDefaultTimeout(12000);
    const choose=(state)=>page.request.get(${stateUrl}+state);
    const original=(id)=>page.getByRole('region',{name:'代码 #'+id+' 详情',exact:true});
    await choose('task-candidate-ready');
    await page.goto(${candidateUrl});
    await original(202).getByText('代码 #201',{exact:true}).waitFor();
    await page.getByRole('button',{name:'代码 #201 · 历史',exact:true}).click();
    await original(201).getByText('历史代码，仅供查看',{exact:true}).waitFor();
    await page.reload();
    await original(201).getByText('起点 Git 版本 #52',{exact:true}).waitFor();
    await choose('task-candidate-updated');
    const current=original(201).getByRole('button',{name:'查看当前代码 #203',exact:true});
    await current.waitFor();
    await original(201).getByText('历史代码，仅供查看',{exact:true}).waitFor();
    await current.click();
    await original(203).getByText('起点 Git 版本 #52',{exact:true}).waitFor();
    if(new URL(page.url()).searchParams.has('candidate_id'))
     throw Error('Following current preserved an older route selection');
    await page.goto(${candidateUrl}+'&candidate_id=999');
    await original(999).getByRole('alert').waitFor();
    if(await original(203).count())throw Error('Missing historical candidate fell back to current');
    return {passed:true};
   }`);
   await code(`async(page)=>{
    page.setDefaultTimeout(12000);
    await page.request.get(${stateUrl}+'task-candidate-ready');
    await page.goto(${candidateUrl}+'&path=a-empty.txt');
    const preview=page.getByRole('region',{name:'所选文件内容',exact:true});
    await preview.getByText('此文件为空。',{exact:true}).waitFor();
    if(new URL(page.url()).searchParams.get('candidate_id')!=='202')
     throw Error('Original task reference was not pinned');
    await page.request.get(${stateUrl}+'task-candidate-updated');
    await page.getByRole('region',{name:'代码 #202 详情',exact:true}).getByText('历史代码，仅供查看',{exact:true}).waitFor();
    await preview.getByText('此文件为空。',{exact:true}).waitFor();
    if(new URL(page.url()).searchParams.get('candidate_id')!=='202')
     throw Error('An updated current candidate changed the previously pinned file');
    return {passed:true};
   }`);
   const firstFixedFileRead=requests.length;
   await code(`async(page)=>{
    page.setDefaultTimeout(12000);
    await page.request.get(${stateUrl}+'task-candidate-updated');
    const base=${candidateUrl}+'&candidate_id=201';
    const exact=base+'&path='+encodeURIComponent('src/历史 +%.txt');
    await page.goto(exact);
    const preview=page.getByRole('region',{name:'所选文件内容',exact:true});
    await preview.getByRole('alert').filter({hasText:'固定代码暂不可用，请核对原操作'}).waitFor();
    await preview.getByRole('button',{name:'重试读取文件',exact:true}).click();
    await preview.getByText('该比较版本中没有此文件。',{exact:true}).waitFor();
    await preview.getByRole('button',{name:'起点 Git 版本',exact:true}).click();
    await preview.getByText('来自原候选',{exact:true}).waitFor();
    if(await page.getByRole('region',{name:'代码 #203 详情',exact:true}).count())
     throw Error('Historical path fell back to the current candidate');
    await page.reload();
    await preview.getByRole('heading',{name:'src/历史 +%.txt',exact:true}).waitFor();
    await page.goto(base+'&path=missing.txt');
    await preview.getByRole('alert').filter({hasText:'所选路径不在这份固定差异中'}).waitFor();
    await page.goBack();
    await preview.getByRole('heading',{name:'src/历史 +%.txt',exact:true}).waitFor();
    await page.goForward();
    await preview.getByRole('heading',{name:'missing.txt',exact:true}).waitFor();
    await page.goto(base+'&path='+encodeURIComponent('../outside.txt'));
    await page.getByRole('alert').filter({hasText:'代码任务页面参数无效'}).waitFor();
    if(await preview.count())throw Error('Invalid file path mounted a reader');
    return {passed:true};
   }`);
   const fixedFileTraffic=requests.slice(firstFixedFileRead);
   if(originalFileReads<4||fixedFileTraffic.some(row=>row.includes('/candidates/203/')||row.startsWith('POST /api/')))
    throw Error('Historical file did not remain on its original read-only scope');
   await code(`async(page)=>{
    page.setDefaultTimeout(12000);
    await page.request.get(${stateUrl}+'task-candidate-history-page');
    const address=${candidateUrl}+'&candidate_id=202&page=2';
    await page.goto(address);
    const diff=page.getByRole('region',{name:'固定代码差异',exact:true});
    const file=diff.getByRole('button',{name:'src/多字节.ts',exact:true});
    const preview=page.getByRole('region',{name:'所选文件内容',exact:true});
    await file.click();
    if(new URL(page.url()).searchParams.get('page')!=='2')throw Error('File dropped its original page');
    await preview.getByRole('heading',{name:'src/多字节.ts',exact:true}).waitFor();
    await page.getByRole('navigation',{name:'任务工作区',exact:true}).getByRole('button',{name:'用量',exact:true}).click();
    await page.getByRole('region',{name:'模型用量',exact:true}).waitFor();
    await page.goBack();
    await file.waitFor();
    await preview.getByRole('heading',{name:'src/多字节.ts',exact:true}).waitFor();
    await page.goBack();
    await file.waitFor();
    if(await preview.count())throw Error('Back did not restore the page before file selection');
    await page.goForward();
    await preview.getByRole('heading',{name:'src/多字节.ts',exact:true}).waitFor();
    await diff.getByRole('button',{name:'上一页',exact:true}).click();
    await diff.getByRole('button',{name:'page-01.txt',exact:true}).waitFor();
    await preview.getByRole('heading',{name:'src/多字节.ts',exact:true}).waitFor();
    return {passed:true};
   }`);
   const checksUrl=JSON.stringify(origin+'/code-tasks/31?tab=checks&verification_id=');
   const firstCheckRead=requests.length;
   await code(`async(page)=>{
    page.setDefaultTimeout(10000);
    await page.request.get(${stateUrl}+'task-check-done');
    const detail=page.getByRole('region',{name:'自检 #71 详情',exact:true});
    await page.goto(${checksUrl}+71);
    await detail.getByText('指定自检记录，仅供查看',{exact:true}).waitFor();
    await detail.getByText('#202',{exact:true}).waitFor();
    if(await page.getByRole('button',{name:'重新自检',exact:true}).count())
     throw Error('Original read-only verification mounted current check control');
    await page.reload();
    await detail.getByText('指定自检记录，仅供查看',{exact:true}).waitFor();
    await page.goto(${checksUrl}+999);
    await page.getByRole('region',{name:'自检 #999 详情',exact:true}).getByRole('alert').waitFor();
    if(await detail.count())throw Error('Missing verification showed another scope');
    return {passed:true};
   }`);
   if(requests.slice(firstCheckRead).some(row=>row.endsWith('/candidates/202/verifications')||
      row.endsWith('/verifications/72')))throw Error('Direct verification prefetched current verification or history');
   await code(`async(page)=>{
    const selected=page.getByRole('region',{name:'指定开发自检',exact:true});
    await selected.getByRole('button',{name:'返回当前开发自检',exact:true}).click();
    await page.getByRole('region',{name:'开发自检',exact:true}).getByRole('button',{name:'重新自检',exact:true}).waitFor();
    return {passed:true};
   }`);
   taskStop={key:randomUUID(),inputVersion:4};
   scenario='task-runtime-aborting';
   await code(`async(page)=>{
    page.setDefaultTimeout(10000);
    await page.goto(${JSON.stringify(pageUrl)});
    const facts=page.locator('.code-task-facts').first();
    const choose=(state)=>page.request.get(${stateUrl}+'task-runtime-'+state);
    await facts.getByText('正在停止会话',{exact:true}).waitFor();
    await facts.getByText('进程数量待核对',{exact:true}).waitFor();
    await choose('terminating');
    await facts.getByText('正在结束相关进程',{exact:true}).waitFor();
    await choose('cleaning');
    await facts.getByText('正在回收运行资源',{exact:true}).waitFor();
    await facts.getByText('0',{exact:true}).waitFor();
    await choose('cleanup-unknown');
    await facts.getByText('资源回收待核对',{exact:true}).waitFor();
    await choose('verified');
    await facts.getByText('运行资源已回收',{exact:true}).waitFor();
    if(await facts.getByText('当前阶段已静止',{exact:true}).count())
     throw Error('Stop was mistaken for stage quiescence');
    return {passed:true};
   }`);
   if(requests.includes('GET '+taskViewPath+'/operations')||
      requests.some(row=>row.startsWith('POST /api/')))
    throw Error('Read-only task workspace prefetched operation history or sent a write');
   console.log('V20_CODING_RECORDS_PASSED '+JSON.stringify({widths:[360,1280,1920],historyPagesRead:[...new Set(recordReads.map(row=>row.page))],writes:0}));
   return;
  }
  if(codingDelivery){
   taskSaved={view:taskView({design_revision_id:24,repository_id:23,base_snapshot_id:52,
    target_branch:'refs/heads/target',execution_profile_version_id:19,authorization_id:87,
    budget_limit_cny:'0.2',material_refs:[]})};
   scenario='task-publication-delivery-error';
   await cli('open',origin+'/code-tasks/31?tab=delivery','--config='+config);
   const switchTo=JSON.stringify(origin+'/__scenario?state=task-publication-delivery-ready');
   await code(`async(page)=>{
    const work=page.getByRole('region',{name:'接收与交付',exact:true});
    await work.getByRole('alert').waitFor();
    await page.request.get(${switchTo});
    await page.reload();
    const accept=work.getByRole('button',{name:'接收此候选',exact:true});
    await work.getByRole('heading',{name:'交付预览 #41',exact:true}).waitFor();
    if(!await accept.isDisabled())throw Error('Delivery bypassed the two confirmations');
    await work.getByRole('button',{name:'查看 target-only.txt',exact:true}).click();
    await work.getByText('target only',{exact:true}).waitFor();
    await work.getByRole('button',{name:'候选结果',exact:true}).click();
    await work.getByText('候选结果中无此文件。',{exact:true}).waitFor();
    const risk=work.getByRole('checkbox',{name:'已阅读并确认人工验证范围的风险',exact:true});
    const pause=work.getByRole('checkbox',{name:'交付期间暂停此仓库的其他 Git 写操作',exact:true});
    await pause.check();
    if(!await accept.isDisabled())throw Error('Delivery skipped manual risk');
    await risk.check();
    await accept.click();
    const dialog=page.getByRole('dialog',{name:'接收代码候选',exact:true});
    await dialog.getByRole('button',{name:'取消',exact:true}).click();
    if(!await risk.isChecked()||!await pause.isChecked())throw Error('Cancel lost fixed confirmation');
    for(const width of [360,1024,1280,1920]){
     await page.setViewportSize({width,height:850});
     if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Delivery overflows '+width);
    }
    await accept.click();
    await dialog.getByRole('button',{name:'确认接收',exact:true}).click();
    await work.getByRole('button',{name:'查看交付 #43',exact:true}).click();
    await work.getByText('需确认本次合作窗口',{exact:true}).waitFor();
    if(await work.getByText('已交付',{exact:true}).count())throw Error('Acceptance displayed as delivery');
    if(!await accept.isDisabled())throw Error('Accepted delivery allowed duplicate submission');
    return {passed:true};
   }`);
   if(!deliveryAcceptance)throw Error('No original delivery request');

   await code(`async(page)=>{
    await page.request.get(${JSON.stringify(origin+'/__scenario?state=task-publication-delivery-repair-busy')});
    await page.goto(${JSON.stringify(origin+'/code-tasks/31?tab=testing')});
    {
     const area=page.getByRole('region',{name:'缺陷修复',exact:true});
     const button=area.getByRole('button',{name:'按所选报告修复',exact:true});
     await area.getByText('任务中有其他操作，请完成或核对后再发起修复',{exact:true}).waitFor();
     if(!await button.isDisabled())throw Error('An active operation did not fence repair');
     for(const width of [360,1280]){
      await page.setViewportSize({width,height:850});
      if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Blocked repair overflows '+width);
     }
    }
    await page.request.get(${JSON.stringify(origin+'/__scenario?state=task-publication-delivery-repair')});
    await page.goto(${JSON.stringify(origin+'/code-tasks/31?tab=testing')});
    const area=page.getByRole('region',{name:'缺陷修复',exact:true});
    const start=area.getByRole('button',{name:'按所选报告修复',exact:true});
    await start.waitFor();
    if(!await start.isDisabled())throw Error('Repair did not require a defect choice');
    await page.getByRole('checkbox',{name:'选择缺陷 #1 用于修复',exact:true}).check();
    await start.click();
    const dialog=page.getByRole('dialog',{name:'发起缺陷修复',exact:true});
    await dialog.getByRole('button',{name:'取消',exact:true}).click();
    await start.click();
    await dialog.getByRole('button',{name:'发起修复',exact:true}).click();
    await area.getByRole('button',{name:'查看修复 #45',exact:true}).click();
    await area.getByRole('region',{name:'原修复 #45',exact:true}).getByText('#202',{exact:true}).waitFor();
    if(!await start.isDisabled())throw Error('Another repair was enabled while the original is pending');
    return {passed:true};
   }`);
   if(!repairAcceptance)throw Error('No original repair request');
   await code(`async(page)=>{
    await page.request.get(${JSON.stringify(origin+'/__scenario?state=task-publication-delivery-repair-source-unknown')});
    await page.goto(${JSON.stringify(origin+'/code-tasks/31?tab=testing')});
    const area=page.getByRole('region',{name:'缺陷修复',exact:true});
    await area.getByRole('button',{name:'查看修复 #45',exact:true}).click();
    const history=area.getByRole('region',{name:'原修复 #45',exact:true});
    await history.getByText('原修复操作结果待核对。',{exact:true}).waitFor();
    if((await history.textContent()).includes('原修复消息结果待核对'))throw Error('Unknown creation was shown as a message');
    if(!await area.getByRole('button',{name:'按所选报告修复',exact:true}).isDisabled())throw Error('Unknown source creation enabled another repair');
    for(const width of [360,1280]){
     await page.setViewportSize({width,height:850});
     if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Unknown repair history overflows '+width);
    }
    return {passed:true};
   }`);

   await code(`async(page)=>{
    await page.request.get(${JSON.stringify(origin+'/__scenario?state=task-publication-delivery-repair-cancelled')});
    await page.goto(${JSON.stringify(origin+'/code-tasks/31?tab=testing')});
    const area=page.getByRole('region',{name:'缺陷修复',exact:true});
    const read=area.getByRole('button',{name:'读取原修复进度',exact:true});
    await read.click();
    await read.waitFor({state:'detached'});
    await area.getByRole('button',{name:'查看修复 #45',exact:true}).click();
    const history=area.getByRole('region',{name:'原修复 #45',exact:true});
    await history.getByText('已取消',{exact:true}).waitFor();
    if((await history.textContent()).includes('本次修复未发送'))throw Error('A sent cancelled repair was shown as unsent');
    await page.getByRole('checkbox',{name:'选择缺陷 #1 用于修复',exact:true}).check();
    await area.getByRole('button',{name:'按所选报告修复',exact:true}).click();
    const dialog=page.getByRole('dialog',{name:'发起缺陷修复',exact:true});
    await dialog.getByRole('button',{name:'取消',exact:true}).click();
    for(const width of [360,1280]){
     await page.setViewportSize({width,height:850});
     if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Cancelled repair history overflows '+width);
    }
    return {passed:true};
   }`);
   await cli('resize','360','800');
   await code(`async(page)=>{
    await page.request.get(${JSON.stringify(origin+'/__scenario?state=task-delivery-cleanup')});
    await page.goto(${JSON.stringify(origin+'/code-tasks/31?tab=execution')});
    const resume=page.getByRole('region',{name:'继续代码任务',exact:true});
    const button=resume.getByRole('button',{name:'继续原交付收尾',exact:true});
    await button.click();
    const dialog=page.getByRole('dialog',{name:'继续原交付收尾',exact:true});
    await dialog.getByText('核对已交付事实，仅继续本任务尚未完成的停止或清理。',{exact:true}).waitFor();
    await dialog.getByRole('button',{name:'取消',exact:true}).click();
    await button.click();
    await dialog.getByRole('button',{name:'确认继续',exact:true}).click();
    await resume.getByRole('alert').waitFor();
    await page.reload();
    await resume.getByRole('button',{name:'核对原继续请求',exact:true}).click();
    await resume.getByText('已恢复原交付收尾，正在等待停止和清理证据。',{exact:true}).waitFor();
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Cleanup controls overflow');
    return {passed:true};
   }`);
   if(resumeWrites.length!==1||resumeWrites[0].input.repository_quiescent_confirmed!==undefined)
    throw Error('Cleanup requested a new Git window or repeated the command');
   scenario='task-publication-delivery-ready';
   const firstHistoricalRead=requests.length;
   const planUrl=JSON.stringify(origin+'/code-tasks/31?tab=delivery&plan_id=');
   await code(`async(page)=>{
    page.setDefaultTimeout(10000);
    await page.goto(${planUrl}+41);
    const original=page.getByRole('region',{name:'指定交付预览 #41',exact:true});
    await original.getByText('指定交付预览，仅供查看',{exact:true}).waitFor();
    if(await page.getByRole('button',{name:'接收此候选',exact:true}).count())
     throw Error('Historical preview mounted current acceptance control');
    await original.getByRole('button',{name:'查看 target-only.txt',exact:true}).click();
    await original.getByText('target only',{exact:true}).waitFor();
    await original.getByRole('button',{name:'候选结果',exact:true}).click();
    await original.getByText('候选结果中无此文件。',{exact:true}).waitFor();
    await page.reload();
    await original.getByText('指定交付预览，仅供查看',{exact:true}).waitFor();
    await original.getByText('target only',{exact:true}).waitFor();
    await page.goto(${planUrl}+41+'&path=outside-page.txt');
    await original.getByText('from fixed plan',{exact:true}).waitFor();
    await page.goto(${planUrl}.replace('plan_id=','path=')+'target-only.txt');
    await original.getByText('target only',{exact:true}).waitFor();
    if(new URL(page.url()).searchParams.get('plan_id')!=='41')
     throw Error('Path-only delivery did not pin the observed plan');
    await page.goto(${planUrl}+41+'&path=missing.txt');
    await original.getByRole('alert').filter({hasText:'所选路径不在这份固定差异中'}).waitFor();
    await page.goBack();
    await original.getByText('target only',{exact:true}).waitFor();
    await page.goto(${planUrl}+999);
    await page.getByRole('region',{name:'指定交付预览 #999',exact:true}).getByRole('alert').waitFor();
    if(await original.count())throw Error('Missing historical preview showed the current plan');
    return {passed:true};
   }`);
   const fileRoute=taskViewPath+'/delivery-plans/41/file';
   const beforePaging=requests.filter(row=>row==='GET '+fileRoute).length;
   scenario='task-publication-delivery-history-page';
   await code(`async(page)=>{
    page.setDefaultTimeout(12000);
    await page.goto(${planUrl}+41+'&path=target-only.txt&page=2');
    const original=page.getByRole('region',{name:'指定交付预览 #41',exact:true});
    await original.getByText('target only',{exact:true}).waitFor();
    await original.getByRole('button',{name:'上一页',exact:true}).click();
    await original.getByRole('button',{name:'查看 preview-01.txt',exact:true}).waitFor();
    await original.getByText('target only',{exact:true}).waitFor();
    if(new URL(page.url()).searchParams.get('path')!=='target-only.txt')
     throw Error('Paging replaced the original fixed file');
    await page.goBack();
    await original.getByRole('button',{name:'查看 target-only.txt',exact:true}).waitFor();
    await original.getByText('target only',{exact:true}).waitFor();
    return {passed:true};
   }`);
   if(requests.filter(row=>row==='GET '+fileRoute).length!==beforePaging+1)
    throw Error('Plan pagination remounted or reloaded the selected immutable file');
   if(requests.slice(firstHistoricalRead).some(row=>row.startsWith('POST /api/')||
      row.includes('/deliveries')||row.includes('/test-reports/')))
    throw Error('Historical preview sent a command or prefetched current delivery');
   console.log('V20_CODING_DELIVERY_PASSED '+JSON.stringify({widths:[360,1024,1280,1920],writes:1}));
   return;
  }
  if(reportLinkOnly){
   taskSaved={view:taskView({design_revision_id:24,repository_id:23,base_snapshot_id:52,
    execution_profile_version_id:19,authorization_id:87,material_refs:[],target_branch:'refs/heads/main',budget_limit_cny:'0.125'})};
   scenario='task-publication-done';
   await cli('open',origin+'/code-tasks/31?tab=testing','--config',config,'--idle-timeout=30000');
   await cli('resize','360','820');
   await exerciseReportLink(false);
   await exerciseExecutionRecords();
   const defectsPage=JSON.stringify(origin+'/code-tasks/31?tab=testing');
   const defectScenario=JSON.stringify(origin+'/__scenario?state=task-publication-defect');
   await code("async(page)=>{page.setDefaultTimeout(12000);await page.request.get("+defectScenario+");await page.goto("+defectsPage+");const area=page.getByRole('region',{name:'缺陷报告',exact:true});await area.getByText('此任务尚未登记缺陷报告',{exact:true}).waitFor();await area.getByRole('button',{name:'登记人工缺陷',exact:true}).click();await area.getByRole('textbox',{name:'实际行为',exact:true}).fill('原检查未保留输出');await area.getByRole('textbox',{name:'预期行为',exact:true}).fill('应保留输出');await area.getByRole('button',{name:'关闭',exact:true}).click();await page.reload();await area.getByRole('button',{name:'登记人工缺陷',exact:true}).click();if(await area.getByRole('textbox',{name:'实际行为',exact:true}).inputValue()!=='原检查未保留输出')throw Error('Defect draft was lost after reload');await area.getByRole('combobox',{name:'固定版本',exact:true}).selectOption('24');const basis=area.getByRole('textbox',{name:'固定原文',exact:true});await basis.press('Control+a');await area.getByRole('button',{name:'引用选中原文',exact:true}).click();await area.getByRole('button',{name:'保存缺陷报告',exact:true}).click();const confirm=page.getByRole('dialog',{name:'保存缺陷报告',exact:true});await confirm.getByRole('button',{name:'取消',exact:true}).click();await area.getByRole('button',{name:'保存缺陷报告',exact:true}).click();await confirm.getByRole('button',{name:'确认',exact:true}).click();await area.getByRole('alert').filter({hasText:'本次操作结果待核实'}).waitFor();await area.getByRole('button',{name:'核对原缺陷请求',exact:true}).click();await area.getByRole('region',{name:'原缺陷 #1',exact:true}).getByText('原检查未保留输出',{exact:true}).waitFor();if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Defect controls overflow');return {passed:true};}");
   await cli('resize','1280','850');
   await code("async(page)=>{page.setDefaultTimeout(12000);const area=page.getByRole('region',{name:'缺陷报告',exact:true});await area.getByRole('button',{name:'导入独立测试发现项',exact:true}).click();await area.getByRole('textbox',{name:'独立测试报告编号',exact:true}).fill('72');await area.getByRole('button',{name:'核对原测试报告',exact:true}).click();await area.getByRole('combobox',{name:'原产品发现项',exact:true}).selectOption('84');await area.getByText('独立检查原失败',{exact:true}).waitFor();await area.getByRole('button',{name:'保存缺陷报告',exact:true}).click();await page.getByRole('dialog',{name:'保存缺陷报告',exact:true}).getByRole('button',{name:'确认',exact:true}).click();await area.getByRole('region',{name:'原缺陷 #2',exact:true}).getByText('独立测试发现项 #84',{exact:true}).waitFor();return {passed:true};}");
   if(defectWrites.length!==2||defectWrites[0].input.basis_ref.quote!=='固定设计原文。'||
      JSON.stringify(defectWrites[1].input)!==JSON.stringify({candidate_id:202,expected_state_version:32,testing_finding_id:84}))
    throw Error('Defect manual or imported original body differed');
   if(reportLinkWrites.length!==1||publicationWrites.length!==0||
      requests.some(row=>row.startsWith('POST /api/v1/testing-tasks')))
    throw Error('Report selection repeated a write or created a Testing task');
   scenario='task-publication-linked';
   const startHistorical=requests.length;
   const reportUrl=JSON.stringify(origin+'/code-tasks/31?tab=testing&test_report_id=');
   await code(`async(page)=>{
    page.setDefaultTimeout(10000);
    await page.goto(${reportUrl}+71);
    const original=page.getByRole('region',{name:'指定独立测试报告 #71',exact:true});
    await original.getByText('指定独立测试报告，仅供查看',{exact:true}).waitFor();
    await original.getByRole('heading',{name:'报告 #71 · 通过',exact:true}).waitFor();
    if(await page.getByRole('button',{name:'选择已有报告',exact:true}).count())
     throw Error('Historical report mounted the association control');
    await page.reload();
    await original.getByRole('heading',{name:'报告 #71 · 通过',exact:true}).waitFor();
    await page.goto(${reportUrl}+73);
    const foreign=page.getByRole('region',{name:'指定独立测试报告 #73',exact:true});
    await foreign.getByRole('alert').filter({hasText:'此报告不属于当前 Coding 任务。'}).waitFor();
    if(await foreign.getByRole('heading',{name:'报告 #73 · 通过',exact:true}).count())
     throw Error('Foreign Testing report exposed its facts');
    return {passed:true};
   }`);
   if(requests.slice(startHistorical).some(row=>row.startsWith('POST /api/')||row.startsWith('GET /api/v1/testing-tasks')))
    throw Error('Historical report read prefetched Testing tasks or sent a write');
   console.log('V20_CODING_REPORT_LINK_PASSED '+JSON.stringify({widths:[360,1280],links:reportLinkWrites.length,defects:defectWrites.length}));
   return;
  }

  if(mode==='role-reconciliation'){
   taskSaved={view:taskView({design_revision_id:24,repository_id:23,base_snapshot_id:52,
    execution_profile_version_id:19,authorization_id:87,material_refs:[],target_branch:'refs/heads/main',budget_limit_cny:'0.125'})};
   scenario='task-role-unknown';
   await cli('open',origin+'/code-tasks/31','--config',config,'--idle-timeout=30000');
   await cli('resize','360','800');
   await code(`async(page)=>{
    page.setDefaultTimeout(15000);
    const state=${JSON.stringify(origin+'/__scenario?state=')};
    await page.request.get(state+'task-role-unknown');
    const box=page.getByRole('region',{name:'原角色操作核对'});
    const button=box.getByRole('button',{name:'核对原角色操作',exact:true});
    await button.click();
    const dialog=page.getByRole('dialog',{name:'核对原角色操作'});
    await dialog.getByRole('button',{name:'取消',exact:true}).click();
    await button.click();
    await dialog.getByRole('button',{name:'开始核对',exact:true}).click();
    const read=box.getByRole('button',{name:'读取本次核对结果',exact:true});
    await read.waitFor();
    if(await box.getByText('已确认原消息接收，角色交接已完成。',{exact:true}).count())throw Error('Acceptance was shown as completion');
    await page.request.get(state+'task-role-confirmed');
    await read.click();
    const expected=${JSON.stringify(roleCreation?'原会话创建已核实，角色交接仍在继续。':'已确认原消息接收，角色交接已完成。')};
    await box.getByText(expected,{exact:true}).waitFor();
    if(${roleCreation} && await box.getByText('已确认原消息接收，角色交接已完成。',{exact:true}).count())throw Error('Creation was shown as message delivery');
    for(const width of [360,1280]){
     await page.setViewportSize({width,height:850});
     if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Role result overflows '+width);
    }
    return {passed:true};
   }`);
   if(roleReconcileWrites.length!==1)throw Error('Role reconciliation issued duplicate mutation');
   console.log((roleCreation?'V20_ORIGINAL_ROLE_CREATION_RECONCILIATION_PASSED ':'V20_ORIGINAL_ROLE_RECONCILIATION_PASSED ')+JSON.stringify({widths:[360,1280],writes:roleReconcileWrites.length}));
   return;
  }

  if(repairReconciliation){
   taskSaved={view:taskView({design_revision_id:24,repository_id:23,base_snapshot_id:52,
    execution_profile_version_id:19,authorization_id:87,material_refs:[],target_branch:'refs/heads/main',budget_limit_cny:'0.125'})};
   scenario='task-role-unknown';
   await cli('open',origin+'/code-tasks/31','--config',config,'--idle-timeout=30000');
   await cli('resize','360','800');
   const expectedRepair=repairSettled?'原修复已完成，请查看新候选和后续检查。':repairCreation?'原修复会话创建已核实，修复尚未发送。':'已确认原修复消息，修复结果仍在等待。';
   await code(`async(page)=>{
    page.setDefaultTimeout(15000);
    const state=${JSON.stringify(origin+'/__scenario?state=')};
    await page.request.get(state+'task-role-unknown');
    const box=page.getByRole('region',{name:'原修复核对'});
    const button=box.getByRole('button',{name:'核对原修复结果',exact:true});
    await button.click();
    const dialog=page.getByRole('dialog',{name:'核对原修复结果'});
    await dialog.getByRole('button',{name:'取消',exact:true}).click();
    await button.click();
    await dialog.getByRole('button',{name:'开始核对',exact:true}).click();
    const read=box.getByRole('button',{name:'读取本次核对结果',exact:true});
    await read.waitFor();
    const expected=${JSON.stringify(expectedRepair)};
    if(await box.getByText(expected,{exact:true}).count())throw Error('Acceptance was shown as repair confirmation');
    await page.request.get(state+'task-role-confirmed');
    await read.click();
    await box.getByText(expected,{exact:true}).waitFor();
    if(${repairCreation} && await box.getByText('已确认原修复消息，修复结果仍在等待。',{exact:true}).count())throw Error('Repair create was shown as message confirmation');
    for(const width of [360,1280]){
     await page.setViewportSize({width,height:850});
     if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Repair reconciliation overflows '+width);
    }
    return {passed:true};
   }`);
   if(roleReconcileWrites.length!==1)throw Error('Repair reconciliation issued duplicate mutation');
   console.log((repairSettled?'V20_ORIGINAL_REPAIR_SETTLED_RECONCILIATION_PASSED':repairCreation?'V20_ORIGINAL_REPAIR_CREATION_RECONCILIATION_PASSED':'V20_ORIGINAL_REPAIR_RECONCILIATION_PASSED')+' widths=360,1280 writes=1');
   return;
  }

  if(liveConfiguration){
   taskSaved={view:taskView({design_revision_id:24,repository_id:23,base_snapshot_id:52,
    execution_profile_version_id:19,authorization_id:87,material_refs:[],target_branch:'refs/heads/main',budget_limit_cny:'0.125'})};
   scenario='task-configuration';
   await cli('open',origin+'/code-tasks/31','--config',config,'--idle-timeout=30000');
   await cli('resize','360','800');
   await code(`async(page)=>{
    page.setDefaultTimeout(15000);
    const state=${JSON.stringify(origin+'/__scenario?state=')};
    const open=page.getByRole('button',{name:'更换任务配置',exact:true});
    await open.click();
    const form=page.getByRole('form',{name:'选择任务配置'});
    await form.getByLabel('新执行配置').selectOption('9');
    await form.getByLabel('新配置版本').selectOption('20');
    await form.getByLabel('新适用授权').selectOption('89');
    await form.getByLabel('变更说明').fill('核对后更换配置');
    await form.getByRole('button',{name:'取消',exact:true}).click();
    await open.click();
    if(await form.getByLabel('变更说明').inputValue()!=='核对后更换配置')throw Error('Cancelled control draft was lost');
    await form.getByRole('button',{name:'应用配置',exact:true}).click();
    const lookup=page.getByRole('button',{name:'核对原配置请求',exact:true});
    await lookup.waitFor();
    await page.reload();
    await lookup.click();
    await page.getByText(/配置版本 #20.*待核对生效/).waitFor();
    if(await page.getByText(/配置版本 #20.*已核实生效/).count())throw Error('Live acceptance was shown as effective');
    await page.request.get(state+'task-configuration-unknown');
    const read=page.getByRole('button',{name:'读取原应用进度',exact:true});
    await read.click();
    await page.getByText(/配置版本 #20.*配置结果待核对/).waitFor();
    if(await page.getByText(/配置版本 #20.*已核实生效/).count())throw Error('Unknown control pair was shown as effective');
    await page.request.get(state+'task-configuration-applied');
    const effective=page.getByText(/配置版本 #20.*已核实生效/);
    try{
     await read.click({timeout:1500});
    }catch(error){
     if(!await effective.isVisible())throw error;
    }
    await effective.waitFor();
    for(const width of [360,1280]){
     await page.setViewportSize({width,height:850});
     if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Live controls overflow '+width);
    }
    return {passed:true};
   }`);
   if(configurationWrites.length!==1)throw Error('Live control request was duplicated');
   console.log('V20_LIVE_CONFIGURATION_PASSED widths=360,1280 writes=1 pending,unknown,applied');
   return;
  }

  if(mode==='tasks'){
   const listPath='/requirements/1/documents/41/code-tasks';
   await cli('open',origin+'/requirements','--config',config,'--idle-timeout=30000');
   await cli('resize','360','800');
   await code("async(page)=>{page.setDefaultTimeout(10000);const coding=page.getByRole('button',{name:'代码开发',exact:true});await coding.click();const hint=page.getByText('选择需求和文档以进入代码任务',{exact:true});await hint.waitFor();if(!await coding.evaluate(element=>{const box=element.getBoundingClientRect();return box.left>=0&&box.right<=innerWidth&&box.height>=40;}))throw Error('Coding navigation overflows');await page.reload();await hint.waitFor();return {passed:true};}");
   await cli('resize','1024','800');
   await code("async(page)=>{page.setDefaultTimeout(10000);await page.getByRole('link',{name:'隔离编码需求',exact:true}).click();const open=page.getByRole('button',{name:'展开文档导航',exact:true});await page.getByRole('button',{name:'更多操作',exact:true}).waitFor();if(await open.isVisible())await open.click();const tasks=page.getByRole('button',{name:'隔离设计文档的代码任务',exact:true});await tasks.waitFor();if(!await tasks.evaluate(element=>{const box=element.getBoundingClientRect();return box.left>=0&&box.right<=innerWidth&&box.height>0;}))throw Error('Document Coding action overflows');await tasks.click();await page.getByText('当前文档尚无代码任务',{exact:true}).waitFor();await page.goBack();await page.getByRole('button',{name:'更多操作',exact:true}).waitFor();await page.goBack();await page.getByText('选择需求和文档以进入代码任务',{exact:true}).waitFor();return {passed:true};}");
   if(requests.some(row=>!row.startsWith('GET ')))throw Error('Global Coding navigation issued a business write');
   console.log('V20_GLOBAL_CODING_NAVIGATION_PASSED widths=360,1024');
   await cli('resize','1280','800');
   await cli('goto',origin+'/requirements/1');
   await code("async(page)=>{page.setDefaultTimeout(10000);await page.getByRole('button',{name:'更多操作',exact:true}).click();await page.getByRole('button',{name:'代码任务',exact:true}).click();await page.getByText('当前文档尚无代码任务',{exact:true}).waitFor();return {passed:true};}");
   await code("async(page)=>{page.setDefaultTimeout(10000);await page.getByText('当前文档尚无代码任务',{exact:true}).waitFor();return {passed:true};}");
   let snapshot=await cli('snapshot');
   const create=/button "创建任务".*\[ref=([a-z0-9]+)\]/.exec(snapshot);
   if(!create)throw Error(snapshot);
   await cli('click',create[1]);
   await code("async(page)=>{page.setDefaultTimeout(10000);const dialog=page.getByRole('dialog',{name:'创建代码任务'});await dialog.waitFor();await dialog.getByLabel('固定设计版本').selectOption('24');await dialog.getByLabel('仓库',{exact:true}).selectOption('23');await dialog.getByLabel('执行配置',{exact:true}).selectOption('9');await dialog.getByLabel('执行配置版本',{exact:true}).selectOption('19');await dialog.getByRole('button',{name:'读取仓库信息',exact:true}).click();await dialog.getByText('已读取本次仓库信息。',{exact:true}).waitFor();await dialog.getByLabel('来源提交',{exact:true}).fill('"+commit+"');await dialog.getByRole('button',{name:'登记代码起点',exact:true}).click();await dialog.getByRole('button',{name:'继续核对原登记',exact:true}).click();await dialog.getByText('已登记起点 #52 · 可用',{exact:true}).waitFor();await dialog.getByLabel('目标分支').selectOption('refs/heads/main');await dialog.getByLabel('未绑定授权').selectOption('87');await dialog.getByLabel('人民币预算').fill('0.125');return {passed:true};}");
   await cli('resize','360','800');
   await code("async(page)=>{page.setDefaultTimeout(10000);const dialog=page.getByRole('dialog',{name:'创建代码任务'});const create=dialog.getByRole('button',{name:'创建任务',exact:true});await create.waitFor();const fits=await dialog.evaluate(d=>{const b=d.getBoundingClientRect();return b.left>=0&&b.right<=innerWidth+1&&b.bottom<=innerHeight+1;});if(!fits)throw Error('Drawer overflows narrow viewport');await dialog.getByRole('button',{name:'取消',exact:true}).click();return {passed:true};}");
   await cli('resize','1280','800');
   await code("async(page)=>{page.setDefaultTimeout(10000);await page.getByRole('button',{name:'创建任务',exact:true}).click();const dialog=page.getByRole('dialog',{name:'创建代码任务'});await dialog.waitFor();if(await dialog.getByLabel('人民币预算').inputValue()!=='0.125')throw Error('Draft lost after closing');await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-lost')+");await dialog.getByRole('button',{name:'创建任务',exact:true}).click();await dialog.getByRole('button',{name:'核对原请求',exact:true}).waitFor();return {passed:true};}");
   await cli('goto',origin+listPath);
   await code("async(page)=>{page.setDefaultTimeout(10000);await page.getByRole('button',{name:'核对原创建请求',exact:true}).click();const dialog=page.getByRole('dialog',{name:'创建代码任务'});await dialog.getByRole('button',{name:'核对原请求',exact:true}).click();await page.getByRole('heading',{name:'代码任务 #31',exact:true}).waitFor();await page.getByText('任务已创建，尚未开始执行',{exact:true}).waitFor();await page.getByRole('button',{name:'代码',exact:true}).click();await page.getByText('src/main.py',{exact:true}).waitFor();await page.getByText('尚未形成待验收代码',{exact:true}).waitFor();await page.getByRole('button',{name:'返回任务列表',exact:true}).click();await page.getByRole('button',{name:'查看任务 #31',exact:true}).waitFor();return {passed:true};}");
   await cli('resize','360','800');
   await code("async(page)=>{page.setDefaultTimeout(10000);await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-configuration')+");await page.goto("+JSON.stringify(origin+'/code-tasks/31')+");const open=page.getByRole('button',{name:'更换任务配置',exact:true});await open.click();const form=page.getByRole('form',{name:'选择任务配置'});await form.getByLabel('新执行配置').selectOption('9');await form.getByLabel('新配置版本').selectOption('20');await form.getByLabel('新适用授权').selectOption('89');await form.getByText('允许模型',{exact:true}).waitFor();await form.getByLabel('变更说明').fill('核对后更换配置');await form.getByRole('button',{name:'取消',exact:true}).click();await open.click();if(await form.getByLabel('变更说明').inputValue()!=='核对后更换配置')throw Error('Configuration cancellation discarded the draft');const apply=form.getByRole('button',{name:'应用配置',exact:true});if(!await apply.evaluate(element=>{const box=element.getBoundingClientRect();return box.left>=0&&box.right<=innerWidth+1;}))throw Error('Configuration button overflows');await apply.click();await page.getByRole('button',{name:'核对原配置请求',exact:true}).waitFor();return {passed:true};}");
   await cli('resize','1280','800');
   await code("async(page)=>{page.setDefaultTimeout(10000);await page.reload();await page.getByRole('button',{name:'核对原配置请求',exact:true}).click();await page.getByText(/配置版本 #20.*待启动核对/).waitFor();if(await page.getByText(/配置版本 #20.*已核实生效/).count())throw Error('Configuration acceptance was presented as effective');await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-configuration-applied')+");await page.getByRole('button',{name:'读取原应用进度',exact:true}).click();await page.getByText(/配置版本 #20.*已核实生效/).waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-lost')+");await page.goto("+JSON.stringify(origin+listPath)+");await page.getByRole('button',{name:'查看任务 #31',exact:true}).waitFor();return {passed:true};}");
   if(configurationWrites.length!==1)throw Error('Original configuration request was duplicated');
   console.log('V20_C39_CONFIGURATION_PASSED widths=360,1280 writes=1');
   await code("async(page)=>{page.setDefaultTimeout(10000);await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-missing')+");await page.getByRole('button',{name:'查看任务 #31',exact:true}).click();await page.getByText('代码任务不存在',{exact:true}).waitFor();if(!page.url().endsWith("+JSON.stringify(listPath)+"))throw Error('Missing task replaced list');await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-lost')+");await page.getByLabel('固定版本').selectOption('25');await page.getByText('没有符合筛选条件的任务',{exact:true}).waitFor();const create=page.getByRole('button',{name:'创建任务',exact:true});if(!await create.isDisabled())throw Error('Filtered list opened occupied slot');await page.getByRole('button',{name:'清除筛选',exact:true}).click();await page.getByRole('button',{name:'查看任务 #31',exact:true}).waitFor();return {passed:true};}");
   await code("async(page)=>{page.setDefaultTimeout(10000);await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-list-error')+");await page.getByLabel('固定版本').selectOption('24');await page.getByRole('alert').filter({hasText:'数据暂时无法访问，请稍后核对'}).waitFor();if(!await page.getByRole('button',{name:'查看任务 #31',exact:true}).isVisible())throw Error('List error discarded last known rows');await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-lost')+");await page.getByRole('button',{name:'重试读取',exact:true}).click();await page.getByRole('alert').filter({hasText:'数据暂时无法访问，请稍后核对'}).waitFor({state:'hidden'});return {passed:true};}");

   await cli('resize','360','800');
   await code("async(page)=>{page.setDefaultTimeout(10000);await page.getByRole('button',{name:'查看任务 #31',exact:true}).click();const stop=page.getByRole('button',{name:'停止任务',exact:true});await stop.click();const confirm=page.getByRole('dialog',{name:'停止代码任务'});await confirm.waitFor();if(!await confirm.evaluate(d=>{const b=d.getBoundingClientRect();return b.left>=0&&b.right<=innerWidth+1&&b.bottom<=innerHeight+1;}))throw Error('Stop confirmation overflows narrow viewport');await confirm.getByRole('button',{name:'取消',exact:true}).click();await page.getByText('任务已创建，尚未开始执行',{exact:true}).waitFor();return {passed:true};}");
   if(stopWrites.length!==0)throw Error('Cancel sent a stop request');
   await code("async(page)=>{page.setDefaultTimeout(10000);await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-start-running')+");await page.reload();await page.getByText('正在准备工作区 · 操作 #91',{exact:true}).waitFor();const refresh=page.getByRole('button',{name:'刷新执行进度',exact:true});if(!await refresh.evaluate(d=>{const b=d.getBoundingClientRect();return b.left>=0&&b.right<=innerWidth+1;}))throw Error('Workspace progress control overflows');await page.getByRole('button',{name:'停止任务',exact:true}).click({trial:true});await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-start-unknown')+");await refresh.click();await page.getByText('工作区准备结果待核对 · 操作 #91',{exact:true}).waitFor();return {passed:true};}");
   await cli('resize','1280','800');
   await code("async(page)=>{page.setDefaultTimeout(10000);await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-start-ready')+");await page.getByRole('button',{name:'刷新执行进度',exact:true}).click();await page.getByText('工作区已核验，等待后续准备 · 操作 #91',{exact:true}).waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-basis-unknown')+");await page.getByRole('button',{name:'刷新执行进度',exact:true}).click();await page.getByText('任务启动结果待核对 · 操作 #91',{exact:true}).waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-basis-failed')+");await page.getByRole('button',{name:'刷新执行进度',exact:true}).click();await page.getByText('固定代码、设计或材料暂不可用 · 操作 #91',{exact:true}).waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-conditions-blocked')+");await page.getByRole('button',{name:'刷新执行进度',exact:true}).click();await page.getByText('执行环境尚未就绪 · 操作 #91',{exact:true}).waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-lost')+");await page.getByRole('button',{name:'刷新执行进度',exact:true}).click();await page.getByText('任务已创建，尚未开始执行',{exact:true}).waitFor();return {passed:true};}");
   await code("async(page)=>{page.setDefaultTimeout(10000);const start=page.getByRole('button',{name:'开始任务',exact:true});if(!await start.isDisabled())throw Error('Unavailable task was startable');await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-start-lost')+");await page.reload();await start.click();await page.getByRole('button',{name:'核对原开始请求',exact:true}).waitFor();await page.getByRole('alert').filter({hasText:'本次操作结果待核实'}).waitFor();return {passed:true};}");
   await cli('goto',origin+'/code-tasks/31');
   await code("async(page)=>{page.setDefaultTimeout(10000);const lookup=page.getByRole('button',{name:'核对原开始请求',exact:true});await lookup.waitFor();if(!await page.getByRole('button',{name:'开始任务',exact:true}).isDisabled())throw Error('Lost start allowed another submit');await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-start-running')+");await lookup.click();await page.getByText('正在准备工作区 · 操作 #91',{exact:true}).waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-start-completed')+");await page.getByRole('button',{name:'刷新执行进度',exact:true}).click();await page.getByText('首条执行消息已接收，任务已进入后端阶段。',{exact:true}).waitFor();if(!await page.getByRole('button',{name:'开始任务',exact:true}).isDisabled())throw Error('Completed original start was replayable');await page.getByRole('button',{name:'停止任务',exact:true}).click({trial:true});return {passed:true};}");
   await code("async(page)=>{page.setDefaultTimeout(10000);await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-usage-empty')+");await page.getByRole('button',{name:'用量',exact:true}).click();await page.getByText('任务尚无模型调用',{exact:true}).waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-usage-error')+");await page.getByRole('button',{name:'刷新模型调用',exact:true}).click();await page.getByRole('alert').filter({hasText:'数据暂时无法访问，请稍后核对'}).waitFor();if(await page.getByText('任务尚无模型调用',{exact:true}).count())throw Error('Read error became empty');await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-usage-row')+");await page.getByRole('button',{name:'刷新模型调用',exact:true}).click();await page.getByRole('button',{name:'查看调用 #77',exact:true}).waitFor();await page.getByText(/输出 未记录 · 缓存 0/).waitFor();return {passed:true};}");
   if(requests.some(request=>request==='GET '+callPath+'/'+callId))throw Error('Model detail was prefetched');
   await cli('resize','360','800');
   await code("async(page)=>{page.setDefaultTimeout(10000);await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-usage-detail-error')+");await page.getByRole('button',{name:'查看调用 #77',exact:true}).click();const detail=page.getByRole('region',{name:'模型调用 #77',exact:true});await detail.getByRole('alert').waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-usage-row')+");await detail.getByRole('button',{name:'重试读取详情',exact:true}).click();await detail.getByText('opaque: 0012',{exact:true}).waitFor();await detail.getByText('响应记录不完整，以下为已保存内容。',{exact:true}).waitFor();await detail.getByText('实际请求',{exact:true}).click();await detail.getByRole('button',{name:'格式化 JSON',exact:true}).click();await detail.getByRole('searchbox',{name:'搜索实际请求',exact:true}).fill('fixture prompt');await detail.getByRole('button',{name:'查找下一处',exact:true}).click();await detail.getByText('已选中匹配内容',{exact:true}).waitFor();const area=detail.getByRole('textbox',{name:'实际请求内容',exact:true});const selected=await area.evaluate(e=>e.value.slice(e.selectionStart,e.selectionEnd));if(selected!=='fixture prompt')throw Error('Search did not select the stored text');const fit=await detail.evaluate(e=>e.getBoundingClientRect().right<=innerWidth+1);if(!fit)throw Error('Call detail overflows narrow viewport');await detail.getByRole('button',{name:'关闭详情',exact:true}).click();if(await page.evaluate(()=>document.activeElement?.textContent)!=='查看调用 #77')throw Error('Detail did not restore focus');await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-start-completed')+");await page.getByRole('button',{name:'执行',exact:true}).click();return {passed:true};}");
   await cli('resize','1280','800');
   await code("async(page)=>{page.setDefaultTimeout(10000);const counter="+JSON.stringify(origin+'/__task-summary-reads')+";await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'));});await page.waitForTimeout(150);const hiddenCount=await (await page.request.get(counter)).json();await page.waitForTimeout(1250);if(await (await page.request.get(counter)).json()!==hiddenCount)throw Error('Hidden workspace kept polling');const visibleRead=page.waitForResponse(r=>r.url().endsWith('/api/v1/code-tasks/31'));await page.evaluate(()=>{delete document.hidden;document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('focus'));});await visibleRead;await page.waitForTimeout(150);if(await (await page.request.get(counter)).json()!==hiddenCount+1)throw Error('Focus and visibility repeated the same task read');return {passed:true};}");
   await code("async(page)=>{page.setDefaultTimeout(10000);await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-summary-error')+");await page.getByText('当前状态尚未核实。',{exact:false}).waitFor();if(!await page.getByRole('button',{name:'停止任务',exact:true}).isDisabled())throw Error('Stale state allowed control');await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-model-waiting')+");await page.getByText('模型预算或调用额度需要处理。',{exact:true}).waitFor();await page.getByRole('button',{name:'停止任务',exact:true}).click({trial:true});await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-start-completed')+");await page.getByText('首条执行消息已接收，任务已进入后端阶段。',{exact:true}).waitFor();return {passed:true};}");
   await cli('resize','360','800');
   await code("async(page)=>{page.setDefaultTimeout(10000);await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-model-waiting')+");await page.getByText('模型预算或调用额度需要处理。',{exact:true}).waitFor();const trigger=page.getByRole('button',{name:'增加预算',exact:true});await trigger.click();const form=page.getByRole('form',{name:'追加任务预算'}),amount=form.getByRole('textbox',{name:'新预算总额（元）'}),reason=form.getByRole('textbox',{name:'调整说明'}),submit=form.getByRole('button',{name:'保存新预算'});await amount.fill('0.100');await reason.fill('继续原模型工作');if(!await submit.isDisabled())throw Error('Budget below original limit accepted');if(!await form.evaluate(e=>e.scrollWidth<=e.clientWidth+1))throw Error('Budget form overflows narrow viewport');await form.getByRole('button',{name:'取消调整'}).click();if(!await trigger.evaluate(e=>document.activeElement===e))throw Error('Budget cancel did not restore focus');await trigger.click();await amount.fill('0.25');await reason.fill('继续原模型工作');await submit.click();await page.getByRole('button',{name:'核对原预算请求'}).waitFor();await page.getByRole('alert').filter({hasText:'本次操作结果待核实'}).waitFor();return {passed:true};}");
   await cli('goto',origin+'/code-tasks/31');
   await code("async(page)=>{page.setDefaultTimeout(10000);const lookup=page.getByRole('button',{name:'核对原预算请求'});await lookup.waitFor();if(!await page.getByRole('button',{name:'增加预算',exact:true}).isDisabled())throw Error('Uncertain budget admitted a new request');await lookup.click();await page.getByText('预算总额已更新。',{exact:true}).waitFor();await page.waitForFunction(()=>document.activeElement?.textContent==='增加预算');await page.getByText('模型预算或调用额度需要处理。',{exact:true}).waitFor();await page.getByRole('button',{name:'增加预算',exact:true}).click();await page.getByText(/当前预算总额 ¥0.250000/).waitFor();await page.getByRole('button',{name:'取消调整',exact:true}).click();await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-start-completed')+");await page.getByText('首条执行消息已接收，任务已进入后端阶段。',{exact:true}).waitFor();return {passed:true};}");
   if(budgetWrites.length!==1)throw Error('Budget original request was sent more than once');
   await code("async(page)=>{page.setDefaultTimeout(10000);await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-model-waiting')+");await page.getByText('模型预算或调用额度需要处理。',{exact:true}).waitFor();const trigger=page.getByRole('button',{name:'继续原操作',exact:true});await trigger.click();const dialog=page.getByRole('dialog',{name:'继续原代码操作'});await dialog.getByRole('button',{name:'取消',exact:true}).click();if(!await trigger.evaluate(e=>document.activeElement===e))throw Error('Resume cancel did not restore focus');await trigger.click();await dialog.getByRole('button',{name:'确认继续',exact:true}).click();await page.getByRole('alert').filter({hasText:'本次操作结果待核实'}).waitFor();return {passed:true};}");
   await cli('goto',origin+'/code-tasks/31');
   await code("async(page)=>{page.setDefaultTimeout(10000);await page.getByRole('button',{name:'核对原继续请求',exact:true}).click();await page.getByText('继续消息的接收结果待核对。',{exact:true}).waitFor();if(!await page.getByRole('button',{name:'继续原操作',exact:true}).isDisabled())throw Error('Unknown native resume allowed another submit');await page.getByText('模型预算或调用额度需要处理。',{exact:true}).waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-start-completed')+");await page.getByRole('button',{name:'核对继续操作 #96',exact:true}).click();await page.getByText('原会话已接收继续消息。',{exact:true}).waitFor();await page.getByText('首条执行消息已接收，任务已进入后端阶段。',{exact:true}).waitFor();return {passed:true};}");
   if(resumeWrites.length!==1)throw Error('Resume original request was sent more than once');
   if(requests.some(request=>request.startsWith('GET '+taskViewPath+'/operations')))throw Error('Task history was fetched before opening');
   await code("async(page)=>{page.setDefaultTimeout(10000);const set=async(state)=>page.request.get("+JSON.stringify(origin+'/__scenario?state=')+"+state);const history=page.getByRole('region',{name:'任务操作历史'});await set('task-history-empty');await history.getByRole('button',{name:'操作历史',exact:true}).click();await history.getByText('任务尚无操作记录',{exact:true}).waitFor();await set('task-history-error');await history.getByRole('button',{name:'刷新操作历史'}).click();await history.getByRole('alert').waitFor();if(await history.getByText('任务尚无操作记录',{exact:true}).count())throw Error('Read failure became empty');await set('task-start-completed');await history.getByRole('button',{name:'刷新操作历史'}).click();await history.getByRole('button',{name:'查看继续任务操作 #96'}).waitFor();return {passed:true};}");
   if(requests.some(request=>request==='GET '+taskViewPath+'/operations/'+resumeOperationId))throw Error('Operation detail was prefetched');
   await code("async(page)=>{page.setDefaultTimeout(10000);const set=async(state)=>page.request.get("+JSON.stringify(origin+'/__scenario?state=')+"+state);const item=page.getByRole('button',{name:'查看继续任务操作 #96'});await set('task-history-detail-error');await item.click();const detail=page.getByRole('region',{name:'原操作 #96'});await detail.getByRole('alert').waitFor();await set('task-start-completed');await detail.getByRole('button',{name:'重试操作详情'}).click();await detail.getByText('核对继续消息 · 已确认',{exact:true}).waitFor();await detail.getByRole('button',{name:'关闭操作详情'}).click();if(!await item.evaluate(e=>document.activeElement===e))throw Error('Operation detail did not restore focus');return {passed:true};}");
   await code("async(page)=>{page.setDefaultTimeout(10000);const set=async(state)=>page.request.get("+JSON.stringify(origin+'/__scenario?state=')+"+state);await set('task-native-issues-empty');await page.getByText('请先核对待处理的原生问题或权限请求',{exact:true}).waitFor();const region=page.getByRole('region',{name:'原生问题和权限',exact:true});await region.getByRole('button',{name:'原生问题',exact:true}).click();const questions=region.getByRole('region',{name:'原生问题列表'});await questions.getByText('任务尚无原生问题',{exact:true}).waitFor();await set('task-native-issues');await questions.getByRole('button',{name:'刷新原生问题'}).click();await questions.getByRole('heading',{name:'固定原生问题'}).waitFor();await questions.getByText('原选项 · 保留说明',{exact:true}).waitFor();await questions.getByRole('combobox',{name:'请求状态'}).selectOption('REJECTED');await questions.getByText('当前筛选没有原生问题',{exact:true}).waitFor();await questions.getByRole('combobox',{name:'请求状态'}).selectOption('');await set('task-native-issues-unknown');await questions.getByRole('button',{name:'刷新原生问题'}).click();await questions.getByRole('heading',{name:/结果待核对/}).waitFor();if(!await questions.getByRole('button',{name:'答复原问题'}).isDisabled())throw Error('Unknown issue was answerable');await region.getByRole('button',{name:'权限请求',exact:true}).click();const permission=region.getByRole('region',{name:'权限请求列表'});await permission.getByText('工具 bash · 执行',{exact:true}).waitFor();if(!await permission.getByRole('button',{name:'拒绝本会话待批权限'}).isDisabled())throw Error('Read-only scope enabled permission write');if(await permission.evaluate(e=>e.scrollWidth>e.clientWidth+1))throw Error('Permission details overflow narrow viewport');await set('task-native-issues-error');await permission.getByRole('button',{name:'刷新权限请求'}).click();await permission.getByRole('alert').waitFor();await set('task-start-completed');await page.getByText('首条执行消息已接收，任务已进入后端阶段。',{exact:true}).waitFor();await region.getByRole('button',{name:'权限请求',exact:true}).click();return {passed:true};}");
   await code("async(page)=>{page.setDefaultTimeout(15000);const set=async(state)=>page.request.get("+JSON.stringify(origin+'/__scenario?state=')+"+state);await set('task-native-issues-answer');await page.getByText('原生问题需要处理或核对。',{exact:true}).waitFor();const issues=page.getByRole('region',{name:'原生问题和权限',exact:true});await issues.getByRole('button',{name:'原生问题',exact:true}).click();const response=issues.getByRole('region',{name:'答复原生问题 #1',exact:true});const trigger=response.getByRole('button',{name:'答复原问题',exact:true});await trigger.click();const form=response.getByRole('form',{name:'逐题答复'});if(!await form.getByRole('button',{name:'提交答复'}).isDisabled())throw Error('Incomplete questionnaire was submittable');if(!await form.getByRole('heading',{name:'逐题答复'}).evaluate(e=>e===document.activeElement))throw Error('Answer did not focus original questionnaire');const first=form.getByRole('group',{name:/第 1 题/});const firstAction=first.getByRole('combobox',{name:'答复方式'});await firstAction.selectOption('USE_FIXED_BASIS');await firstAction.selectOption('CITE_FIXED_BASIS');await first.getByRole('combobox',{name:'固定版本'}).selectOption('24');const original=first.getByRole('textbox',{name:'固定原文'});await original.waitFor();await original.focus();await original.press('Control+a');if(await original.evaluate(e=>e.value.slice(e.selectionStart,e.selectionEnd))!=='固定设计原文。')throw Error('Keyboard selection did not target fixed source');await first.getByRole('button',{name:'引用选中原文'}).click();const second=form.getByRole('group',{name:/第 2 题/});await second.getByRole('combobox',{name:'答复方式'}).selectOption('CLARIFY_FACTS');await second.getByRole('textbox',{name:'事实说明'}).fill('隔离浏览器补充的原问题事实');if(await form.evaluate(e=>e.scrollWidth>e.clientWidth+1))throw Error('Question answer form overflows narrow viewport');await form.getByRole('button',{name:'提交答复'}).click();await response.getByRole('alert').filter({hasText:'本次操作结果待核实'}).waitFor();return {passed:true};}");
   await cli('goto',origin+'/code-tasks/31');
   await code("async(page)=>{page.setDefaultTimeout(15000);const issues=page.getByRole('region',{name:'原生问题和权限',exact:true});await issues.getByRole('button',{name:'原生问题',exact:true}).click();const response=issues.getByRole('region',{name:'答复原生问题 #1',exact:true});await response.getByRole('button',{name:'查看原答复内容'}).click();await response.getByRole('heading',{name:'原答复内容'}).waitFor();const facts=response.getByRole('textbox',{name:'事实说明'});if(await facts.inputValue()!=='隔离浏览器补充的原问题事实'||!await facts.isDisabled())throw Error('Original read-only answer was not restored');await response.getByText('恢复选项',{exact:true}).click();await response.getByText('当前入口暂不支持按原请求恢复',{exact:true}).waitFor();if(await response.getByRole('button',{name:'按原请求恢复',exact:true}).count())throw Error('Unknown answer exposed a resend');await response.getByRole('button',{name:'核对原答复请求'}).click();await response.getByText('答复请求已接收，等待原生确认。',{exact:true}).waitFor();if(!await response.getByRole('button',{name:'答复原问题',exact:true}).isDisabled())throw Error('202 allowed a duplicate answer');await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-native-issues-answer-done')+");await response.getByRole('button',{name:'核对答复操作 #97'}).click();await response.getByText('原答复已由执行器确认。',{exact:true}).waitFor();await page.getByText('原权限请求需要处理或核对。',{exact:true}).waitFor();await page.getByRole('heading',{name:'原生问题 #1 · 已处理',exact:true}).waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-start-completed')+");await page.getByText('首条执行消息已接收，任务已进入后端阶段。',{exact:true}).waitFor();return {passed:true};}");
   if(answerWrites.length!==1)throw Error('Original question was answered more than once');
   const writesBeforeHandoff=requests.filter((entry)=>entry.startsWith('POST /api/v1/guide-runs')).length;
   await code("async(page)=>{page.setDefaultTimeout(15000);await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-native-handoff')+");await page.getByText('原生问题需要处理或核对。',{exact:true}).waitFor();const issues=page.getByRole('region',{name:'原生问题和权限',exact:true});const panel=issues.getByRole('region',{name:'文档移交 #4',exact:true});await panel.getByRole('button',{name:'移交文档',exact:true}).click();const form=panel.getByRole('form',{name:'准备文档移交',exact:true});await form.getByRole('combobox',{name:'目标文档'}).selectOption('41');await form.getByRole('textbox',{name:'已保存证据编号'}).fill('91');await form.getByRole('button',{name:'添加同任务证据'}).click();await form.getByRole('button',{name:'保存移交',exact:true}).click();await panel.getByRole('alert').filter({hasText:'本次操作结果待核实'}).waitFor();if(await form.evaluate(e=>e.scrollWidth>e.clientWidth+1))throw Error('Handoff form overflows narrow viewport');await panel.getByRole('button',{name:'核对原移交请求',exact:true}).click();await panel.getByRole('button',{name:'去文档讨论',exact:true}).waitFor();return {passed:true};}");
   await cli('resize','1280','800');
   await code("async(page)=>{page.setDefaultTimeout(15000);const open=page.getByRole('button',{name:'去文档讨论',exact:true});await open.click();await page.waitForURL(/requirements[/]1[?]document_id=41&code_task_id=31&code_handoff_id=17/);const panel=page.getByRole('region',{name:'来源代码任务移交',exact:true});await panel.getByText('请核对原设计约束。',{exact:true}).waitFor();const editor=page.getByRole('textbox',{name:'给 AI 的消息'});await editor.fill('已有讨论草稿');await panel.getByRole('button',{name:'填入讨论输入',exact:true}).click();const draft=await editor.inputValue();if(!draft.startsWith('已有讨论草稿')||!draft.includes('原操作 #91'))throw Error('Handoff replaced existing draft or lost evidence');if(!await panel.getByRole('button',{name:'填入讨论输入',exact:true}).isDisabled())throw Error('Handoff could be inserted twice');const form=panel.getByRole('form',{name:'关联已有文档结果'});await form.getByRole('combobox',{name:'关联类型'}).selectOption('REVISION_LINKED');await form.getByRole('textbox',{name:'已保存版本编号'}).fill('24');await form.getByRole('button',{name:'保存已有结果关联'}).click();await panel.getByText(/已关联版本.*版本 #24/).waitFor();await page.reload();const again=page.getByRole('region',{name:'来源代码任务移交',exact:true});await again.getByText(/已关联版本.*版本 #24/).waitFor();if(!await again.getByRole('button',{name:'填入讨论输入',exact:true}).isDisabled()||await page.getByRole('textbox',{name:'给 AI 的消息'}).inputValue()!==draft)throw Error('Handoff reload duplicated or lost the draft');return {passed:true};}");
   if(handoffWrites.length!==1||handoffLinkWrites.length!==1||
      requests.filter((entry)=>entry.startsWith('POST /api/v1/guide-runs')).length!==writesBeforeHandoff)
    throw Error('Handoff changed a document workflow or repeated a request');
   await cli('goto',origin+'/code-tasks/31');
   await cli('resize','360','800');
   await code("async(page)=>{page.setDefaultTimeout(15000);await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-native-permission')+");await page.getByText('原权限请求需要处理或核对。',{exact:true}).first().waitFor();const issues=page.getByRole('region',{name:'原生问题和权限',exact:true});await issues.getByRole('button',{name:'权限请求',exact:true}).click();const list=issues.getByRole('region',{name:'权限请求列表'});const selected=list.getByRole('region',{name:'决定权限请求 #2',exact:true});const peer=list.getByRole('region',{name:'决定权限请求 #3',exact:true});await selected.getByText(/需先调整授权/).waitFor();if(!await selected.getByRole('button',{name:'允许一次',exact:true}).isDisabled())throw Error('Unauthorized operation enabled');await peer.getByRole('button',{name:'允许一次',exact:true}).click();const allow=page.getByRole('dialog',{name:'允许一次',exact:true});await allow.getByRole('button',{name:'取消',exact:true}).click();await selected.getByText(/#2、#3/).waitFor();const trigger=selected.getByRole('button',{name:'拒绝本会话待批权限',exact:true});await trigger.click();const dialog=page.getByRole('dialog',{name:'拒绝本会话待批权限',exact:true});await dialog.getByText('将拒绝本会话中当前待批的权限请求，任务不会因此自动终止。',{exact:true}).waitFor();await dialog.getByRole('button',{name:'确认拒绝',exact:true}).click();await selected.getByRole('alert').filter({hasText:'本次操作结果待核实'}).waitFor();if(await list.evaluate(e=>e.scrollWidth>e.clientWidth+1))throw Error('Permission actions overflow narrow viewport');return {passed:true};}");
   await cli('goto',origin+'/code-tasks/31');
   await code("async(page)=>{page.setDefaultTimeout(15000);const issues=page.getByRole('region',{name:'原生问题和权限',exact:true});await issues.getByRole('button',{name:'权限请求',exact:true}).click();const selected=issues.getByRole('region',{name:'决定权限请求 #2',exact:true});await selected.getByRole('button',{name:'核对原权限决定',exact:true}).click();await selected.getByText(/请求已接收，等待原生确认/).waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-native-permission-partial')+");await selected.getByRole('button',{name:'核对权限操作 #98',exact:true}).click();await selected.getByText(/处理结果待核对，请查看各项权限状态/).waitFor();await issues.getByRole('heading',{name:'权限请求 #2 · 已拒绝',exact:true}).waitFor();await issues.getByRole('heading',{name:'权限请求 #3 · 结果待核对',exact:true}).waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-start-completed')+");await page.getByText('首条执行消息已接收，任务已进入后端阶段。',{exact:true}).waitFor();return {passed:true};}");
   if(permissionWrites.length!==1)throw Error('Original permission was decided more than once');
   await code("async(page)=>{page.setDefaultTimeout(10000);await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-candidate-ready')+");await page.getByRole('button',{name:'代码',exact:true}).click();const list=page.getByRole('region',{name:'待验收代码',exact:true});await list.getByRole('button',{name:'代码 #202 · 当前',exact:true}).waitFor();const historical=list.getByRole('button',{name:'代码 #201 · 历史',exact:true});await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-candidate-error')+");await historical.click();const detail=list.getByRole('region',{name:'代码 #201 详情',exact:true});await detail.getByRole('alert').filter({hasText:'固定代码暂不可用，请核对原操作'}).waitFor();if(!await historical.isVisible())throw Error('Candidate error discarded the list');await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-candidate-ready')+");await detail.getByRole('button',{name:'重试读取详情',exact:true}).click();await detail.getByText('起点 Git 版本 #52',{exact:true}).waitFor();if(await list.evaluate(e=>e.scrollWidth>e.clientWidth+1))throw Error('Candidate section overflows narrow viewport');return {passed:true};}");
   await cli('resize','1280','800');
   await code("async(page)=>{page.setDefaultTimeout(10000);const list=page.getByRole('region',{name:'待验收代码',exact:true});await list.getByRole('button',{name:'代码 #202 · 当前',exact:true}).click();const detail=list.getByRole('region',{name:'代码 #202 详情',exact:true});await detail.getByText('代码 #201',{exact:true}).waitFor();await detail.getByText('2 个文件 · 51 字节',{exact:true}).waitFor();const diff=detail.getByRole('region',{name:'固定代码差异'});await diff.getByText('请选择差异文件',{exact:true}).waitFor();await diff.getByRole('button',{name:'src/多字节.ts',exact:true}).click();const file=diff.getByRole('region',{name:'所选文件内容'});await file.getByRole('alert').filter({hasText:'固定代码暂不可用，请核对原操作'}).waitFor();await file.getByRole('button',{name:'重试读取文件',exact:true}).click();await file.getByText('仅显示已加载部分',{exact:true}).waitFor();await file.getByRole('button',{name:'继续读取',exact:true}).click();await file.getByLabel('待验收代码的原文').filter({hasText:'😀'}).waitFor();await file.getByRole('button',{name:'起点 Git 版本',exact:true}).click();await file.getByLabel('起点 Git 版本的原文').filter({hasText:'old'}).waitFor();await file.getByRole('button',{name:'完整行差异',exact:true}).click();await file.getByLabel('完整行差异').waitFor();await diff.getByRole('button',{name:'a-empty.txt',exact:true}).click();await file.getByText('此文件为空。',{exact:true}).waitFor();await file.getByRole('button',{name:'起点 Git 版本',exact:true}).click();await file.getByText('该比较版本中没有此文件。',{exact:true}).waitFor();await diff.getByRole('button',{name:'binary.bin',exact:true}).click();await file.getByText('二进制文件 · 3 字节',{exact:true}).waitFor();if(await diff.evaluate(e=>e.scrollWidth>e.clientWidth+1))throw Error('Fixed comparison overflow');await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-start-completed')+");await page.getByRole('button',{name:'执行',exact:true}).click();await page.getByText('首条执行消息已接收，任务已进入后端阶段。',{exact:true}).waitFor();return {passed:true};}");
   if(diffFileReads!==6||requests.some(entry=>entry.startsWith('POST '+taskViewPath+'/candidates')))throw Error('Candidate comparison emitted unexpected requests');
   await cli('resize','360','800');
   await code("async(page)=>{page.setDefaultTimeout(15000);await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-check-empty')+");await page.getByRole('button',{name:'开发自检',exact:true}).click();const region=page.getByRole('region',{name:'开发自检',exact:true});await region.getByText('当前没有开发自检记录',{exact:true}).waitFor();if(!await region.getByRole('button',{name:'重新自检',exact:true}).isDisabled())throw Error('Unready check was enabled');await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-check-list-error')+");await page.getByRole('button',{name:'执行',exact:true}).click();await page.getByRole('button',{name:'开发自检',exact:true}).click();const list=page.getByRole('region',{name:'代码 #202 的开发自检',exact:true});await list.getByRole('alert').waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-check-ready')+");await list.getByRole('button',{name:'重试读取记录',exact:true}).click();await region.getByText('当前不满足开发交接条件',{exact:true}).waitFor();await region.getByText(/实际退出码 7/).waitFor();if(await region.evaluate(e=>e.scrollWidth>e.clientWidth+1))throw Error('Checks overflow narrow viewport');const button=region.getByRole('button',{name:'重新自检',exact:true});await button.click();let dialog=page.getByRole('dialog',{name:'重新自检',exact:true});await dialog.getByRole('button',{name:'取消',exact:true}).click();await button.click();dialog=page.getByRole('dialog',{name:'重新自检',exact:true});await dialog.getByRole('button',{name:'确认重新自检',exact:true}).click();await region.getByRole('alert').filter({hasText:'本次操作结果待核实'}).waitFor();return {passed:true};}");
   await cli('goto',origin+'/code-tasks/31?tab=checks');
   await cli('resize','1280','800');
   await code("async(page)=>{page.setDefaultTimeout(15000);const region=page.getByRole('region',{name:'开发自检',exact:true});await region.getByRole('button',{name:'核对原自检请求',exact:true}).click();await region.getByText('正在执行开发自检。',{exact:true}).waitFor();if(!await region.getByRole('button',{name:'重新自检',exact:true}).isDisabled())throw Error('Active original check did not disable a second write');await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-check-done')+");await region.getByText('当前开发自检合格',{exact:true}).waitFor();await region.getByText(/实际退出码 0/).waitFor();if(await region.evaluate(e=>e.scrollWidth>e.clientWidth+1))throw Error('Checks overflow wide viewport');if(await region.getByRole('region',{name:'original-controlled-case 的用例详情'}).count())throw Error('Case details opened before request');await region.getByRole('button',{name:'查看用例详情',exact:true}).click();const cases=region.getByRole('region',{name:'original-controlled-case 的用例详情'});await cases.getByRole('alert').waitFor();await cases.getByRole('button',{name:'重试读取用例',exact:true}).click();await cases.getByText('受控用例 1',{exact:true}).waitFor();await cases.getByRole('button',{name:'下一页',exact:true}).click();await cases.getByText('受控用例 21',{exact:true}).waitFor();await cases.getByText('部分诊断信息已脱敏。',{exact:true}).waitFor();await region.getByRole('button',{name:'收起用例详情',exact:true}).click();await cases.waitFor({state:'detached'});await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-start-completed')+");await page.getByRole('button',{name:'执行',exact:true}).click();await page.getByText('首条执行消息已接收，任务已进入后端阶段。',{exact:true}).waitFor();return {passed:true};}");
   if(checkWrites.length!==1||caseReads!==3)throw Error('Original verification write or lazy case reads differed');
   await code("async(page)=>{page.setDefaultTimeout(15000);await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-role-running')+");await page.getByText('正在交接下一角色 · 操作 #104',{exact:true}).waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-publication-ready')+");await page.getByRole('button',{name:'独立测试',exact:true}).click();const region=page.getByRole('region',{name:'独立测试',exact:true});const button=region.getByRole('button',{name:'发布供独立测试',exact:true});await button.click();const confirm=page.getByRole('dialog',{name:'发布供独立测试',exact:true});await confirm.getByRole('button',{name:'取消',exact:true}).click();await button.click();await confirm.getByRole('button',{name:'确认发布',exact:true}).click();await region.getByRole('alert').filter({hasText:'本次操作结果待核实'}).waitFor();return {passed:true};}");
   await cli('goto',origin+'/code-tasks/31?tab=testing');
   await cli('resize','360','800');
   await exerciseReportLink(true);
   if(publicationWrites.length!==1||reportLinkWrites.length!==1||requests.some(entry=>entry.startsWith('POST /api/v1/testing-tasks')))throw Error('Publication retried or created a test task');

   await cli('resize','1280','800');
   if(startWrites.length!==1||JSON.stringify(startWrites[0].input)!=='{\"expected_state_version\":1}')throw Error('Original start was sent more than once or changed');
   await code("async(page)=>{page.setDefaultTimeout(10000);await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-stop-lost')+");await page.getByRole('button',{name:'停止任务',exact:true}).click();const confirm=page.getByRole('dialog',{name:'停止代码任务'});await confirm.getByRole('button',{name:'确认停止',exact:true}).click();await page.getByRole('alert').filter({hasText:'本次操作结果待核实'}).waitFor();return {passed:true};}");
   await cli('goto',origin+'/code-tasks/31');
   await cli('resize','360','800');
   await code("async(page)=>{page.setDefaultTimeout(10000);await page.getByRole('button',{name:'核对原停止请求',exact:true}).click();await page.getByText('正在核对停止范围',{exact:true}).waitFor();if(await page.getByText('停止和清理已核实。',{exact:true}).count())throw Error('202 implied successful cleanup');await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-stop-cleaning')+");await page.getByText('原执行已停止，正在核对资源回收。',{exact:true}).waitFor();if(!await page.getByRole('button',{name:'停止任务',exact:true}).isDisabled())throw Error('Stopped task accepted a duplicate');await page.request.get("+JSON.stringify(origin+'/__scenario?state=task-stop-verified')+");await page.getByRole('button',{name:'核对停止操作 #82',exact:true}).click();await page.getByText('停止和清理已核实。',{exact:true}).waitFor();await page.getByText('任务已终止，原执行资源已回收',{exact:true}).waitFor();if(!await page.getByRole('button',{name:'增加预算',exact:true}).isDisabled())throw Error('Terminated task allowed budget change');await page.getByRole('button',{name:'返回任务列表',exact:true}).click();await page.getByRole('button',{name:'查看任务 #31',exact:true}).waitFor();const create=page.getByRole('button',{name:'创建任务',exact:true});await create.click({trial:true});return {passed:true};}");
   if(stopWrites.length!==1||stopWrites[0].input.expected_state_version!==16)throw Error('Original stop was sent more than once');
   await cli('goto',origin+'/requirements/1/documents/99/code-tasks');
   await code("async(page)=>{page.setDefaultTimeout(10000);await page.getByRole('alert').filter({hasText:'当前文档不存在或不属于此需求'}).waitFor();if(await page.getByText('当前文档尚无代码任务',{exact:true}).count())throw Error('Missing document became empty');return {passed:true};}");
   if(taskWrites.length!==1||taskOperations.size!==2||baselineResends!==1||taskWrites[0].input.budget_limit_cny!=='0.125'||
      taskWrites[0].input.base_snapshot_id!==52||taskWrites[0].input.design_revision_id!==24||
      taskWrites[0].input.authorization_id!==87)throw Error('Unexpected original task mutation '+JSON.stringify({count:taskWrites.length,operations:taskOperations.size,baselineResends,inputs:taskWrites.map(row=>row.input)}));
   console.log('V20_TASK_PAGE_PASSED '+JSON.stringify({creates:taskWrites.length,repositoryOperations:taskOperations.size,baselineResends,budgets:budgetWrites.length,resumes:resumeWrites.length,starts:startWrites.length,stops:stopWrites.length,
    widths:[1280,360],states:['empty','nonempty','missing','filter-empty','occupied','draft-restored','list-retry','lost-original-recovered','baseline-files','candidate-history-and-recovery','fixed-comparison-chunks-and-utf8','check-controls-read-and-original-recovery','scoped-case-read-retry-and-pagination','role-and-original-publication','start-preparing','start-unknown','start-workspace-ready','start-basis-unknown','start-basis-failed','start-conditions-blocked','lost-start-recovered','on-demand-model-audit','model-audit-retry-and-search','model-budget-waiting','budget-original-recovered','resume-original-recovered','scoped-operation-history','original-native-issues','original-question-answer','document-handoff','original-permission-partial','task-poll-hidden-focus-and-recovery','cancel-stop','lost-stop-recovered','owned-stop-observed-before-cleanup','verified-stop-releases-slot']}));
   return;
  }
  console.log('OWNED_SETTINGS_ORIGIN '+origin);
  await cli('open',origin+'/settings/code','--config',config,'--idle-timeout=30000');
  await code("async(page)=>{await page.getByText('当前没有待核对操作',{exact:true}).waitFor();if(await page.getByRole('heading',{name:'代码设置',exact:true}).count()!==1)throw Error('Normal route missing');return {passed:true};}");
  await code("async(page)=>{await page.getByText('暂无已登记仓库',{exact:true}).waitFor();return {passed:true};}");
  if(requests.length!==1||requests[0]!=='GET /api/v1/code-repositories')throw Error('Empty ledger triggered an original request query');
  await cli('goto',origin+'/requirements');
  await code("async(page)=>{await page.getByRole('heading',{name:'需求工作台',exact:true}).waitFor();return {passed:true};}");
  const navigation=await cli('snapshot'),settings=/button "设置".*\[ref=([a-z0-9]+)\]/.exec(navigation);
  if(!settings)throw Error(navigation);
  await cli('click',settings[1]);
  await code("async(page)=>{await page.getByText('当前没有待核对操作',{exact:true}).waitFor();return {passed:true};}");
  await code("async(page)=>{await page.evaluate(async()=>{const probe=await import('/seed.js');await probe.seedSettingsRecovery();});return {passed:true};}");
  await refresh();
  await code("async(page)=>{await page.waitForFunction(()=>document.querySelectorAll('.code-settings-pending>li').length===2);if(await page.getByText('NOT_VISIBLE_BODY').count())throw Error('Frozen body leaked');return {passed:true};}");
  for(const [width,height] of [[1280,800],[360,800]]){
   await cli('resize',String(width),String(height));
   await code("async(page)=>{const measured=await page.evaluate(()=>{const a=document.querySelector('.code-settings-section-heading button').getBoundingClientRect(),b=document.querySelector('.code-settings-section-heading h2').getBoundingClientRect();if(document.documentElement.scrollWidth>innerWidth+1||a.left<0||a.right>innerWidth)throw Error('Settings overflow');if(a.left<b.right&&b.left<a.right&&a.top<b.bottom&&b.top<a.bottom)throw Error('Heading/control overlap');return {width:innerWidth,buttonHeight:a.height};});return {passed:true,measured};}");
  }
  await code("async(page)=>{await page.request.get("+JSON.stringify(origin+'/__scenario?state=delayed')+");return {passed:true};}");
  await refresh();
  await code("async(page)=>{const control=page.getByRole('button',{name:'正在核对…',exact:true});if(!await control.isDisabled()||await control.getAttribute('title')!=='正在核对原请求')throw Error('Busy state missing');await page.getByRole('button',{name:'重新核对',exact:true}).waitFor();return {passed:true};}");
  await code("async(page)=>{await page.request.get("+JSON.stringify(origin+'/__scenario?state=failed')+");return {passed:true};}");
  await refresh();
  await code("async(page)=>{await page.waitForFunction(()=>document.querySelectorAll('.code-settings-pending [role=alert]').length===2);const checks=await page.evaluate(()=>({empty:document.querySelectorAll('.code-settings-recovery .empty-state').length,overflow:document.documentElement.scrollWidth>innerWidth+1}));if(checks.empty||checks.overflow)throw Error('Error display failed');return {passed:true};}");
  await code("async(page)=>{await page.request.get("+JSON.stringify(origin+'/__scenario?state=ready')+");return {passed:true};}");
  await refresh();
  await code("async(page)=>{await page.waitForFunction(()=>document.querySelectorAll('.code-settings-pending [role=alert]').length===0);return {passed:true};}");
  await cli('goto',origin+'/settings/code?section=invalid');
  await code("async(page)=>{await page.getByText('设置分区无效，请返回代码设置。',{exact:false}).waitFor();if(await page.locator('.code-settings-recovery').count())throw Error('Invalid section defaulted');return {passed:true};}");
  const snapshot=await cli('snapshot'),reset=/button "返回代码设置".*\[ref=([a-z0-9]+)\]/.exec(snapshot);if(!reset)throw Error(snapshot);
  await cli('click',reset[1]);
  await code("async(page)=>{await page.waitForFunction(()=>document.querySelectorAll('.code-settings-pending>li').length===2);return {passed:true};}");

  if(requests.some(request=>!request.startsWith('GET ')))throw Error('Read-only recovery dispatched a mutation');
  const recoveryReads=requests.length;

  await code("async(page)=>{await page.getByText('暂无已登记仓库',{exact:true}).waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=repository-ready')+");await page.getByRole('button',{name:'重新读取仓库列表',exact:true}).click();const row=page.getByRole('button',{name:'查看仓库 隔离登记仓库',exact:true});await row.waitFor();if(await page.getByText('本地路径',{exact:true}).count())throw Error('List exposed detail fields');await row.click();const detail=page.getByRole('region',{name:'仓库详情',exact:true});await detail.getByText('本地路径',{exact:true}).waitFor();const path=await detail.locator('dd code').textContent();if(!path.endsWith('owned-repository'))throw Error('Selected detail path missing');await detail.getByRole('button',{name:'查看已保存观察',exact:true}).click();const observation=detail.getByRole('region',{name:'已保存观察',exact:true});await observation.getByText('上次观察结果待核对',{exact:false}).waitFor();if(await observation.getByText('本地分支',{exact:true}).count())throw Error('Unknown observation exposed empty branches');if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Repository detail overflows narrow viewport');return {passed:true};}");
  await code("async(page)=>{await page.request.get("+JSON.stringify(origin+'/__scenario?state=repository-failed')+");await page.getByRole('button',{name:'重新读取仓库列表',exact:true}).click();const list=page.getByRole('region',{name:'已登记仓库',exact:true});await list.getByRole('alert').waitFor();if(!await list.getByRole('button',{name:'查看仓库 隔离登记仓库',exact:true}).isVisible())throw Error('Read failure removed saved row');await page.request.get("+JSON.stringify(origin+'/__scenario?state=repository-ready')+");await list.getByRole('button',{name:'重试读取',exact:true}).click();await list.getByRole('alert').waitFor({state:'hidden'});await page.request.get("+JSON.stringify(origin+'/__scenario?state=ready')+");return {passed:true};}");
  await code("async(page)=>{const select=page.getByRole('combobox',{name:'设置分区'});await select.click();await page.getByRole('option',{name:'执行配置',exact:true}).click();await page.getByText('暂无执行配置',{exact:true}).waitFor();const button=page.getByRole('button',{name:'创建执行配置',exact:true});if(!await button.isDisabled())throw Error('Existing intent did not block creation');await page.getByText('已有原请求待核对，请在待核对操作区域查询原结果',{exact:true}).waitFor();return {passed:true};}");
  await cli('resize','1280','800');
  await code("async(page)=>{const nav=page.getByRole('navigation',{name:'设置分区'});await nav.getByRole('button',{name:'检查配置',exact:true}).click();const row=page.getByRole('button',{name:'查看检查配置 基线检查配置',exact:true});await row.click();await page.getByText('待准备条件　Q20-CHECKS',{exact:true}).waitFor();const name=page.getByLabel('新配置名称');await name.fill('隔离检查草稿');await nav.getByRole('button',{name:'仓库',exact:true}).click();await nav.getByRole('button',{name:'检查配置',exact:true}).click();if(await page.getByLabel('新配置名称').inputValue()!=='隔离检查草稿')throw Error('Draft lost on section switch');return {passed:true};}");
  await code("async(page)=>{const region=page.getByRole('region',{name:'检查配置版本',exact:true});const empty=region.getByText('版本 1 详情',{exact:true}),complete=region.getByText('版本 2 详情',{exact:true});await empty.waitFor();if(await region.locator('blockquote').count())throw Error('Collapsed version mounted content');await empty.focus();await page.keyboard.press('Enter');await region.getByText('此版本未配置检查项',{exact:true}).waitFor();await region.getByText('此版本未配置覆盖方案',{exact:true}).waitFor();await complete.click();await region.getByText('离线单元检查 · check-unit',{exact:true}).waitFor();await region.getByText('文档 #41 · 修订 #25',{exact:true}).waitFor();await region.getByText('原始验收条目',{exact:true}).waitFor();if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Version details overflow wide viewport');return {passed:true};}");
  await cli('resize','360','800');
  await code("async(page)=>{const region=page.getByRole('region',{name:'检查配置版本',exact:true});await region.getByText('原始验收条目',{exact:true}).waitFor();if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Version details overflow narrow viewport');await page.request.get("+JSON.stringify(origin+'/__scenario?state=version-failed')+");await region.getByRole('button',{name:'重新读取版本',exact:true}).click();await region.getByRole('alert').waitFor();await region.getByText('原始验收条目',{exact:true}).waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=ready')+");await region.getByRole('button',{name:'重新读取版本',exact:true}).click();await region.getByRole('alert').waitFor({state:'hidden'});await region.getByText('原始验收条目',{exact:true}).waitFor();return {passed:true};}");
  await cli('resize','1280','800');
  await code("async(page)=>{await page.request.get("+JSON.stringify(origin+'/__scenario?state=version-details')+");await page.getByRole('navigation',{name:'设置分区'}).getByRole('button',{name:'执行配置',exact:true}).click();const list=page.getByRole('region',{name:'执行配置列表',exact:true});await list.getByRole('button',{name:'查看执行配置 隔离执行配置',exact:true}).click();await page.getByText('待准备条件　Q20-MODEL',{exact:true}).waitFor();return {passed:true};}");
  const beforeVersionOpen=requests.length;
  await code("async(page)=>{const region=page.getByRole('region',{name:'执行配置版本',exact:true});await region.getByText('版本 1 详情',{exact:true}).click();await region.getByText('1.19.5 · isolated-executor',{exact:true}).waitFor();await region.getByText('2.56.0.windows.4 · isolated-git',{exact:true}).waitFor();await region.getByText('检查集版本 ID',{exact:true}).waitFor();await region.getByText('isolated-model-snapshot',{exact:true}).first().waitFor();await region.getByText('此版本未配置登记命令',{exact:true}).waitFor();if(await region.getByText('isolated-secret-ref',{exact:false}).count())throw Error('Secret reference exposed');return {passed:true};}");
  if(requests.length!==beforeVersionOpen)throw Error('Opening a version detail sent a request');
  await code("async(page)=>{await page.request.get("+JSON.stringify(origin+'/__scenario?state=ready')+");return {passed:true};}");
  const beforeCatalogRead=requests.filter((entry)=>entry==='GET /api/v1/code-configuration-options').length;
  await code("async(page)=>{const region=page.getByRole('region',{name:'配置资源目录',exact:true});await region.getByText('请选择要查看的资源类型',{exact:true}).waitFor();return {passed:true};}");
  if(requests.filter((entry)=>entry==='GET /api/v1/code-configuration-options').length!==beforeCatalogRead)throw Error('Unselected catalogue sent a read');
  await cli('resize','360','800');
  await code("async(page)=>{const region=page.getByRole('region',{name:'配置资源目录',exact:true});const choice=region.getByRole('combobox',{name:'资源类型'});await choice.click();await page.getByRole('option',{name:'执行器',exact:true}).click();await region.getByText('暂无已登记的执行器',{exact:true}).waitFor();await choice.click();await page.getByRole('option',{name:'模型',exact:true}).click();await region.getByText('已登记模型',{exact:true}).waitFor();await choice.click();await page.getByRole('option',{name:'内容策略',exact:true}).click();await region.getByText('CONTENT20-STORE-1 · CONTENT20-SECRETS-1',{exact:true}).waitFor();await choice.click();await page.getByRole('option',{name:'Git 工具',exact:true}).click();await region.getByText('登记的 MinGit',{exact:true}).waitFor();await region.getByText('待准备条件　Q20-GIT、Q20-WINDOWS',{exact:true}).waitFor();if(await region.getByText('已登记模型',{exact:true}).count())throw Error('Catalogue mixed kinds');const overflow=await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1?null:{width:innerWidth,scroll:document.documentElement.scrollWidth,nodes:[...document.querySelectorAll('body *')].filter(node=>node.getBoundingClientRect().right>innerWidth+1).slice(0,20).map(node=>[node.tagName,node.getAttribute('class'),Math.round(node.getBoundingClientRect().right),node.textContent.slice(0,60)])});if(overflow)throw Error('Narrow page overflow '+JSON.stringify(overflow));return {passed:true};}");
  await cli('resize','1280','800');
  await code("async(page)=>{await page.request.get("+JSON.stringify(origin+'/__scenario?state=catalog-failed')+");const region=page.getByRole('region',{name:'配置资源目录',exact:true});const choice=region.getByRole('combobox',{name:'资源类型'});await choice.click();await page.getByRole('option',{name:'模型',exact:true}).click();await region.getByText('已登记模型',{exact:true}).waitFor();await choice.click();await page.getByRole('option',{name:'Git 工具',exact:true}).click();await region.getByRole('alert').waitFor();if(await region.getByText('暂无已登记的Git 工具',{exact:true}).count()||await region.getByText('已登记模型',{exact:true}).count())throw Error('Catalogue failure replaced or mixed state');await page.request.get("+JSON.stringify(origin+'/__scenario?state=ready')+");await region.getByRole('button',{name:'重试读取资源',exact:true}).click();await region.getByText('登记的 MinGit',{exact:true}).waitFor();return {passed:true};}");
  await code(`async(page)=>{
   const region=page.getByRole('region',{name:'配置资源目录',exact:true});
   const choice=region.getByRole('combobox',{name:'资源类型'});
   async function select(name){await choice.click();await page.getByRole('option',{name,exact:true}).click();}
   const stateStatus=(await page.request.get(${JSON.stringify(origin+'/__scenario?state=catalog-scope-loading')})).status();
   if(stateStatus!==200)throw Error('Cannot prepare isolated scope state');
   await select('执行范围');
   await region.getByText('正在读取资源…',{exact:true}).waitFor();
   await region.getByText('任务工作区',{exact:true}).waitFor();
   await region.getByText('任务固定依据',{exact:true}).waitFor();
   await region.getByText('READ20-WORKSPACE-1',{exact:true}).waitFor();
   await region.getByText('READ20-BASIS-1',{exact:true}).waitFor();
   if(await region.getByText('尚未就绪',{exact:true}).count()!==2)throw Error('Scope registration implied admission');
   if(await region.getByText('可用',{exact:true}).count())throw Error('Unadmitted scope shown as available');
   if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Managed scopes overflow narrow layout');
   await page.request.get(${JSON.stringify(origin+'/__scenario?state=catalog-scope-empty')});
   await select('Git 工具');await select('执行范围');
   await region.getByText('暂无已登记的执行范围',{exact:true}).waitFor();
   if(await region.getByText('任务工作区',{exact:true}).count())throw Error('Empty scope response retained old content');
   await page.request.get(${JSON.stringify(origin+'/__scenario?state=catalog-scope-failed')});
   await select('Git 工具');await select('执行范围');
   await region.getByRole('alert').waitFor();
   if(await region.getByText('暂无已登记的执行范围',{exact:true}).count())throw Error('Scope failure shown as empty');
   await page.request.get(${JSON.stringify(origin+'/__scenario?state=ready')});
   await region.getByRole('button',{name:'重试读取资源',exact:true}).click();
   await region.getByText('任务工作区',{exact:true}).waitFor();
   await region.getByRole('alert').waitFor({state:'hidden'});
   return {passed:true};
  }`);
  await cli('goto',origin+'/settings/code?section=checks');
  await code("async(page)=>{await page.getByRole('button',{name:'查看检查配置 基线检查配置',exact:true}).waitFor();if(await page.getByLabel('新配置名称').inputValue()!=='隔离检查草稿')throw Error('Session draft was not restored');return {passed:true};}");
  await code("async(page)=>{await page.request.get("+JSON.stringify(origin+'/__scenario?state=identity-failed')+");await page.getByRole('button',{name:'重新读取列表',exact:true}).click();const list=page.getByRole('region',{name:'检查配置列表',exact:true});await list.getByRole('alert').waitFor();if(!await list.getByRole('button',{name:'查看检查配置 基线检查配置',exact:true}).isVisible()||await list.getByText('暂无检查配置',{exact:true}).count())throw Error('Read failure replaced existing data');return {passed:true};}");
  await code("async(page)=>{await page.request.get("+JSON.stringify(origin+'/__scenario?state=ready')+");const list=page.getByRole('region',{name:'检查配置列表',exact:true});await list.getByRole('button',{name:'重试读取',exact:true}).click();await list.getByRole('alert').waitFor({state:'hidden'});return {passed:true};}");
  await cli('resize','360','800');
  await code("async(page)=>{const form=page.getByRole('form',{name:'创建检查配置',exact:true});await form.getByRole('button',{name:'创建检查配置',exact:true}).click();const busy=form.getByRole('button',{name:'正在创建…',exact:true});await busy.waitFor();if(!await busy.isDisabled()||!await form.getByLabel('新配置名称').isDisabled())throw Error('In-flight controls active');const layout=await form.evaluate(node=>{const button=node.querySelector('button').getBoundingClientRect(),hint=node.querySelector('[role=status]').getBoundingClientRect();return {overflow:document.documentElement.scrollWidth>innerWidth+1||button.right>innerWidth,overlap:button.left<hint.right&&hint.left<button.right&&button.top<hint.bottom&&hint.top<button.bottom};});if(layout.overflow||layout.overlap)throw Error('Narrow form overlap');await page.getByRole('heading',{name:'检查配置版本 · 配置 #42',exact:true}).waitFor();await page.getByText('此配置暂无发布版本',{exact:true}).waitFor();if(await form.getByLabel('新配置名称').inputValue()!=='')throw Error('Confirmed draft was not cleared');return {passed:true};}");
  await code("async(page)=>{await page.request.get("+JSON.stringify(origin+'/__scenario?state=identity-lost')+");const form=page.getByRole('form',{name:'创建检查配置',exact:true});await form.getByLabel('新配置名称').fill('原回执核对配置');await form.getByRole('button',{name:'创建检查配置',exact:true}).click();await page.getByRole('heading',{name:'检查配置版本 · 配置 #43',exact:true}).waitFor();await page.getByText('此配置暂无发布版本',{exact:true}).waitFor();if(await form.getByLabel('新配置名称').inputValue()!=='')throw Error('Reconciled original draft was not cleared');return {passed:true};}");
  if(mutations.length!==2||mutations[0].body!=='{"name":"隔离检查草稿"}'||mutations[1].body!=='{"name":"原回执核对配置"}')throw Error('Identity submission duplicated or changed bytes');

  await code("async(page)=>{const row=page.locator('.code-settings-pending>li').filter({has:page.getByRole('heading',{name:'创建执行配置',exact:true})});await row.getByText('恢复选项',{exact:true}).click();await row.getByRole('button',{name:'按原请求恢复',exact:true}).click();const dialog=page.getByRole('dialog',{name:'按原请求恢复'});await dialog.waitFor();await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});if(!await row.getByRole('button',{name:'按原请求恢复',exact:true}).evaluate(node=>node===document.activeElement))throw Error('Cancel did not restore focus');return {passed:true};}");
  if(recoveryWrites.length!==0)throw Error('Cancelled original replay wrote HTTP');
  await code("async(page)=>{const row=page.locator('.code-settings-pending>li').filter({has:page.getByRole('heading',{name:'创建执行配置',exact:true})});await row.getByRole('button',{name:'按原请求恢复',exact:true}).click();await page.getByRole('dialog').getByRole('button',{name:'确认恢复',exact:true}).click();await row.waitFor({state:'hidden'});await page.getByText('已核实原请求结果',{exact:true}).waitFor();return {passed:true};}");
  if(recoveryWrites.length!==1||recoveryWrites[0].action!=='replay')throw Error('Original replay was not one explicit POST');
  await code("async(page)=>{const row=page.locator('.code-settings-pending>li').filter({has:page.getByRole('heading',{name:'登记仓库',exact:true})});await row.getByText('恢复选项',{exact:true}).click();await row.getByRole('button',{name:'按原请求恢复',exact:true}).click();await page.getByRole('dialog',{name:'按原请求恢复'}).getByRole('button',{name:'确认恢复',exact:true}).click();await page.getByText('所需执行配置尚未就绪',{exact:true}).waitFor();await row.getByText('暂未找到原回执',{exact:true}).waitFor();await row.getByRole('button',{name:'关闭原请求',exact:true}).click();const dialog=page.getByRole('dialog',{name:'关闭原请求'});await dialog.getByText('关闭只能阻止尚未接收的原请求。已接收的操作仍须核对或终止。',{exact:true}).waitFor();await dialog.getByRole('button',{name:'确认关闭',exact:true}).click();await row.getByText('原请求关闭结果待核对',{exact:true}).waitFor();return {passed:true};}");
  await code("async(page)=>{await page.getByRole('button',{name:'重新核对',exact:true}).waitFor();return {passed:true};}");
  await refresh();
  if(recoveryWrites.length!==3||recoveryWrites[1].action!=='register')throw Error('Original registration or close was automatically sent again');
  await code("async(page)=>{const row=page.locator('.code-settings-pending>li').filter({has:page.getByRole('heading',{name:'登记仓库',exact:true})});await row.getByRole('button',{name:'继续核对关闭',exact:true}).click();await page.getByRole('dialog').getByRole('button',{name:'确认关闭',exact:true}).click();await page.getByText('原请求已关闭',{exact:true}).waitFor();await page.getByText('当前没有待核对操作',{exact:true}).waitFor();return {passed:true};}");
  if(recoveryWrites.length!==4||recoveryWrites[1].key!==recoveryWrites[2].key||recoveryWrites[2].key!==recoveryWrites[3].key||recoveryWrites[2].body!==recoveryWrites[3].body)throw Error('Continued close changed its original identity');

  await code("async(page)=>{const sections=page.getByRole('combobox',{name:'设置分区'});await sections.click();await page.getByRole('option',{name:'授权',exact:true}).click();const list=page.getByRole('region',{name:'执行授权',exact:true});const unbound=list.getByRole('button',{name:'查看授权 87',exact:true});await unbound.getByText('已批准，未绑定任务',{exact:true}).waitFor();await list.getByRole('button',{name:'查看授权 85',exact:true}).getByText('已生效',{exact:true}).waitFor();await unbound.click();const detail=page.getByRole('region',{name:'授权详情',exact:true});await detail.getByText('未批准网络目标',{exact:true}).waitFor();await detail.getByText('已批准，未绑定任务',{exact:true}).waitFor();if(await detail.getByText('已生效',{exact:true}).count()||await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Narrow authorization or state isolation failed');return {passed:true};}");
  const beforeInvalidFilter=requests.filter(entry=>entry==='GET /api/v1/code-authorizations').length;
  await code("async(page)=>{const form=page.getByRole('form',{name:'筛选授权'});await form.getByLabel('任务 ID').fill('01');await form.getByRole('button',{name:'应用筛选',exact:true}).click();await form.getByRole('alert').waitFor();return {passed:true};}");
  if(requests.filter(entry=>entry==='GET /api/v1/code-authorizations').length!==beforeInvalidFilter)throw Error('Invalid task filter sent a request');
  await code("async(page)=>{const form=page.getByRole('form',{name:'筛选授权'}),list=page.getByRole('region',{name:'执行授权',exact:true});await form.getByLabel('任务 ID').fill('31');const status=form.getByRole('combobox',{name:'授权状态'});await status.click();await page.getByRole('option',{name:'已生效',exact:true}).click();await form.getByRole('button',{name:'应用筛选',exact:true}).click();await list.getByRole('button',{name:'查看授权 87',exact:true}).waitFor({state:'hidden'});await list.getByRole('button',{name:'查看授权 85',exact:true}).waitFor();await form.getByLabel('任务 ID').fill('90000');await form.getByRole('button',{name:'应用筛选',exact:true}).click();await list.getByText('没有匹配的授权',{exact:true}).waitFor();return {passed:true};}");
  await code("async(page)=>{const form=page.getByRole('form',{name:'筛选授权'}),list=page.getByRole('region',{name:'执行授权',exact:true});await page.request.get("+JSON.stringify(origin+'/__scenario?state=authorization-failed')+");await form.getByRole('button',{name:'应用筛选',exact:true}).click();await list.getByRole('alert').waitFor();if(await list.getByText('没有匹配的授权',{exact:true}).count())throw Error('Authorization error became empty');await page.request.get("+JSON.stringify(origin+'/__scenario?state=ready')+");await list.getByRole('button',{name:'重试读取',exact:true}).click();await list.getByText('没有匹配的授权',{exact:true}).waitFor();return {passed:true};}");
  await cli('resize','360','800');
  await cli('goto',origin+'/settings/code');
  await code("async(page)=>{const form=page.getByRole('form',{name:'登记仓库',exact:true});const submit=form.getByRole('button',{name:'登记仓库',exact:true});await submit.waitFor();if(!await submit.isDisabled())throw Error('Empty registration enabled');await form.getByLabel('仓库名称').fill('待修正仓库');await form.getByLabel('本机仓库目录').fill('relative');await submit.click();await form.getByText('请输入本机绝对目录路径',{exact:true}).waitFor();await form.getByLabel('本机仓库目录').fill("+JSON.stringify('C:\\test\\wrong-git')+");const section=page.getByRole('combobox',{name:'设置分区'});await section.click();await page.getByRole('option',{name:'检查配置',exact:true}).click();await section.click();await page.getByRole('option',{name:'仓库',exact:true}).click();if(await form.getByLabel('本机仓库目录').inputValue()!=="+JSON.stringify('C:\\test\\wrong-git')+")throw Error('Repository draft lost on section change');return {passed:true};}");
  if(registrationWrites.length!==0)throw Error('Invalid path or switching sections wrote registration');
  await code("async(page)=>{const form=page.getByRole('form',{name:'登记仓库',exact:true});const panel=page.getByRole('region',{name:'登记原操作',exact:true});await page.request.get("+JSON.stringify(origin+'/__scenario?state=registration-create')+");await form.getByRole('button',{name:'登记仓库',exact:true}).click();await form.getByRole('button',{name:'正在提交…',exact:true}).waitFor();await panel.getByRole('heading',{name:'登记原操作 #81',exact:true}).waitFor();await panel.getByText('正在核对仓库',{exact:true}).waitFor();if(await panel.getByRole('button',{name:'查看已保存仓库 #25',exact:true}).count()||!await form.getByLabel('本机仓库目录').isDisabled()||await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Original acceptance treated as saved or overflowed');return {passed:true};}");
  await code("async(page)=>{const form=page.getByRole('form',{name:'登记仓库',exact:true});const panel=page.getByRole('region',{name:'登记原操作',exact:true});await page.request.get("+JSON.stringify(origin+'/__scenario?state=registration-read-failed')+");await panel.getByRole('button',{name:'读取原登记操作',exact:true}).click();await panel.getByRole('alert').waitFor();await panel.getByText('正在核对仓库',{exact:true}).waitFor();await page.request.get("+JSON.stringify(origin+'/__scenario?state=registration-failed')+");await panel.getByRole('button',{name:'读取原登记操作',exact:true}).click();await panel.getByText('登记失败',{exact:true}).waitFor();await panel.getByText('不支持此来源',{exact:true}).waitFor();const submit=form.getByRole('button',{name:'登记仓库',exact:true});await submit.evaluate(button=>{if(!button.disabled)return;return new Promise(resolve=>{const observer=new MutationObserver(()=>{if(!button.disabled){observer.disconnect();resolve();}});observer.observe(button,{attributes:true,attributeFilter:['disabled']});});});if(await form.getByLabel('仓库名称').inputValue()!=='待修正仓库'||await form.getByLabel('本机仓库目录').inputValue()!=="+JSON.stringify('C:\\test\\wrong-git')+")throw Error('Terminal failure cleared repository input');return {passed:true};}");
  await code("async(page)=>{const form=page.getByRole('form',{name:'登记仓库',exact:true});await form.getByLabel('仓库名称').fill('新登记仓库');await form.getByLabel('本机仓库目录').fill("+JSON.stringify('C:\\test\\saved-git')+");await page.request.get("+JSON.stringify(origin+'/__scenario?state=registration-lost')+");await form.getByRole('button',{name:'登记仓库',exact:true}).click();await page.getByRole('heading',{name:'登记原操作 #82',exact:true}).waitFor();return {passed:true};}");
  await cli('goto',origin+'/settings/code');
  await code("async(page)=>{const form=page.getByRole('form',{name:'登记仓库',exact:true});const panel=page.getByRole('region',{name:'登记原操作',exact:true});await panel.getByRole('heading',{name:'登记原操作 #82',exact:true}).waitFor();await panel.getByText('正在核对仓库',{exact:true}).waitFor();if(await form.getByLabel('仓库名称').inputValue()!=='新登记仓库')throw Error('Restored original lost its draft');await page.request.get("+JSON.stringify(origin+'/__scenario?state=registration-saved')+");await panel.getByRole('button',{name:'读取原登记操作',exact:true}).click();await panel.getByText('仓库已保存',{exact:true}).waitFor();if(await form.getByLabel('仓库名称').inputValue()!==''||await form.getByLabel('本机仓库目录').inputValue()!=='')throw Error('Confirmed original did not clear its draft');await panel.getByRole('button',{name:'查看已保存仓库 #26',exact:true}).click();const detail=page.getByRole('region',{name:'仓库详情',exact:true});await detail.getByText("+JSON.stringify('C:\\test\\saved-git')+",{exact:true}).waitFor();return {passed:true};}");
  if(registrationWrites.length!==2||registrationWrites[0].key===registrationWrites[1].key)throw Error('Registration duplicated or reused another original key');
  if(refreshWrites.length)throw Error('Opening repository triggered a refresh');
  await code("async(page)=>{const detail=page.getByRole('region',{name:'仓库详情',exact:true});await page.request.get("+JSON.stringify(origin+'/__scenario?state=refresh-lost')+");await detail.getByRole('button',{name:'读取仓库信息',exact:true}).click();const sending=detail.getByRole('button',{name:'正在提交…',exact:true});await sending.waitFor();if(!await sending.isDisabled())throw Error('Refresh remains enabled during send');await detail.getByText('原操作 #83 · 正在读取仓库',{exact:true}).waitFor();if(!await detail.getByRole('button',{name:'读取仓库信息',exact:true}).isDisabled()||await detail.getByRole('region',{name:'已保存观察',exact:true}).count())throw Error('Receipt implied success');const layout=await detail.evaluate(node=>{const actions=node.querySelector('.code-settings-form-actions'),button=actions.querySelector('button').getBoundingClientRect(),hint=actions.querySelector('p').getBoundingClientRect();return document.documentElement.scrollWidth>innerWidth+1||button.right>innerWidth||(button.left<hint.right&&hint.left<button.right&&button.top<hint.bottom&&hint.top<button.bottom);});if(layout)throw Error('Refresh controls overflow or overlap');return {passed:true};}");
  await cli('resize','1280','800');
  await code("async(page)=>{const detail=page.getByRole('region',{name:'仓库详情',exact:true});await page.request.get("+JSON.stringify(origin+'/__scenario?state=refresh-unknown')+");await detail.getByRole('button',{name:'核对原读取请求',exact:true}).click();await detail.getByText('原操作 #83 · 仓库读取结果待核对',{exact:true}).waitFor();if(!await detail.getByRole('button',{name:'读取仓库信息',exact:true}).isDisabled())throw Error('Unknown original enabled a new mutation');await page.request.get("+JSON.stringify(origin+'/__scenario?state=refresh-saved')+");await detail.getByRole('button',{name:'核对原读取请求',exact:true}).click();await detail.getByText('原操作 #83 · 仓库观察已保存',{exact:true}).waitFor();const saved=detail.getByRole('region',{name:'已保存观察',exact:true});await saved.getByRole('heading',{name:'已保存观察 #35',exact:true}).waitFor();await saved.getByText('refs/heads/main',{exact:false}).waitFor();await saved.getByText('此次观察未记录工作树',{exact:true}).waitFor();if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Refresh detail overflows wide viewport');return {passed:true};}");
  if(refreshWrites.length!==1||requests.filter(request=>request==='GET '+observationPath).length!==1)throw Error('Refresh repeated or used another observation');
  await code("async(page)=>{await page.addInitScript(()=>Object.defineProperty(window,'indexedDB',{configurable:true,get(){throw new DOMException('Test storage blocked','SecurityError');}}));return {passed:true};}");
  await cli('goto',origin+'/settings/code');
  await code("async(page)=>{await page.getByText('待核对操作暂存不可用，请保留原输入并核对原结果',{exact:true}).waitFor();if(await page.getByText('当前没有待核对操作',{exact:true}).count())throw Error('Storage failure became empty');return {passed:true};}");
  if(requests.filter(request=>request.startsWith('POST ')).length!==9)throw Error('Unexpected POSTs: '+requests.filter(request=>request.startsWith('POST ')).join(', '));
  console.log('V20_SETTINGS_PAGE_PASSED '+JSON.stringify({recoveryReads,productReads:requests.filter(request=>request.startsWith('GET ')).length,mutations:9,states:['empty','two originals','busy','multiline error','retry','invalid section','blocked storage','identity drafts','immutable version details and empty content','version read failure with retained content','catalogue empty, pending, error and retry','managed scope references, loading empty failure retry and closed admission','creation','original 201 after lost response','explicit replay','cancelled confirmation','registration readiness with same key','continued original close','registration form and original operation','saved repository detail and original observation','explicit refresh, lost receipt, unknown and exact observation','authorization filters and real binding states'],widths:[1280,360]}));
 }finally{
  try{await cli('close');console.log('OWNED_BROWSER_CLOSED');}
  finally{await new Promise(done=>server.close(done));}
 }
}
