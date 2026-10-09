import {spawn} from 'node:child_process';
import {mkdir,readdir,readFile,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {homedir} from 'node:os';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';

const root=resolve(import.meta.dirname,'..'),session=`walle-comment-batch-${Date.now()}-${crypto.randomUUID().replaceAll('-','').slice(0,12)}`;
const directory=resolve(root,'output/playwright'),database=resolve(directory,`api-${session}.sqlite`),dist=resolve(directory,`compiled-${session}`);
await mkdir(directory,{recursive:true});
const report={timestamp:new Date().toISOString(),scope:'Actual comment I34 to SuggestionBatch root and public discard, using explicitly named validated generation fixture; no C07/model/Provider/effect proof, paid requests or normal data changes.',commands:[],cases:[],session};
const env=Object.fromEntries(Object.entries(process.env).filter(([key])=>!key.startsWith('WALLE_')));
const bash='C:/Program Files/Git/bin/bash.exe',wrapper=resolve(homedir(),'.codex/skills/playwright/scripts/playwright_cli.sh');
function processRun(command,args,options={}){
 const child=spawn(command,args,{cwd:root,windowsHide:true,env,...options}),record={command,args,stdout:'',stderr:'',code:null};
 child.stdout.on('data',data=>record.stdout+=data);child.stderr.on('data',data=>record.stderr+=data);
 const exited=new Promise((accept,reject)=>{child.once('error',reject);child.once('exit',code=>{record.code=code;accept(code);});});return {child,record,exited};
}
async function command(command,args,options={}){const job=processRun(command,args,options);await job.exited;report.commands.push(job.record);assert.equal(job.record.code,0,job.record.stdout+'\n'+job.record.stderr);return job.record.stdout;}
async function cli(...args){const output=await command(bash,[wrapper,`-s=${session}`,...args]);assert(!output.includes('### Error'),output);return output;}
async function run(code){const output=await cli('run-code',code.replace(/\r?\n/g,' '));const match=/### Result\s*\n([\s\S]*?)\n### Ran Playwright code/.exec(output);assert(match,output);return JSON.parse(match[1]);}
async function hashes(){const paths=[];async function walk(path){for(const item of await readdir(path,{withFileTypes:true})){if(['node_modules','dist','__pycache__'].includes(item.name))continue;const next=resolve(path,item.name);if(item.isDirectory())await walk(next);else if(/\.(py|json|sql|lock|ts|tsx|mjs|css|html)$/.test(next))paths.push(next);}}for(const part of ['backend','frontend','shared'])await walk(resolve(root,part));paths.push(resolve(root,'tools/verify-comment-batch-browser.mjs'),resolve(root,'tools/api-browser-service.py'));return Object.fromEntries(await Promise.all(paths.sort().map(async path=>[path.slice(root.length+1).replaceAll('\\','/'),createHash('sha256').update(await readFile(path)).digest('hex')])));}
report.inputs_before=await hashes();let native,url,opened=false;
const sleep=milliseconds=>new Promise(accept=>setTimeout(accept,milliseconds));
async function api(path,body,method=body===undefined?'GET':'POST'){const options=method==='GET'?{}:{method,headers:{'Idempotency-Key':crypto.randomUUID(),...(body!==undefined&&body!==null?{'Content-Type':'application/json'}:{})},...(body!==undefined&&body!==null?{body:JSON.stringify(body)}:{})};const response=await fetch(url+'/api/v1'+path,options);assert(response.ok,`${path} ${response.status} ${await response.clone().text()}`);return response.json();}


const editor=`page.locator('.requirement-owned-document .document-owner-host:not([hidden]) .ProseMirror')`,controls=`page.getByRole('region',{name:'人工编辑操作',exact:true})`;
const operations=[{kind:'INITIALIZATION',status:'INITIALIZING',label:'完成初始化',path:'complete-initialization',next:'ACTIVE'},{kind:'COMPLETE',status:'ACTIVE',label:'完成需求',path:'complete',next:'COMPLETED'},{kind:'REACTIVATE',status:'COMPLETED',label:'重新激活',path:'reactivate',next:'ACTIVE'}];
const knownCases=['COMMENT-BATCH-block','COMMENT-BATCH-selection','COMMENT-BATCH-unknown'];
const args=process.argv.slice(2);assert(!args.length||args[0]==='--cases'&&args.length>1);const selected=new Set(args.length?args.slice(1):knownCases);assert.equal(selected.size,args.length?args.length-1:knownCases.length);for(const name of selected)assert(knownCases.includes(name),'Unknown case '+name);report.selected_cases=[...selected];
const saved=`await page.waitForFunction(()=>document.querySelector('.manual-draft-toolbar')?.textContent.includes('已保存'));`,editable=`await page.locator('.requirement-owned-document .ProseMirror[contenteditable=true]').waitFor();`,supported=`await page.waitForFunction(()=>document.querySelector('.requirement-detail-frame')?.getAttribute('data-viewport-phase')==='SUPPORTED');`;
async function inspect(id){const revisions=(await api(`/requirements/${id}/revisions`)).data;return {requirement:(await api('/requirements/'+id)).data,current:(await api(`/requirements/${id}/current-document`)).data,revisions,revision_details:await Promise.all(revisions.items.map(async revision=>(await api('/revisions/'+revision.id)).data))};}
async function fresh(name,code,{status='ACTIVE',dangerous=false}={}){
 if(!selected.has(name))return;
 await run(`async(page)=>{await page.unrouteAll({behavior:'wait'});await page.evaluate(()=>{for(const listener of window.detailUnloads??[])window.removeEventListener('beforeunload',listener);});await page.setViewportSize({width:1440,height:1000});return true;}`);
 const created=(await api('/requirements',{title:'工具栏验收'+String(report.cases.length+1),requirement_type:'NEW',template_key:'new-requirement',template_version:'v1',initial_idea:'独立真实工具栏验收',initialization_mode:'DESIGN'})).data,id=created.requirement.id;
 for(let i=0;i<100;i++){if((await api('/requirements/'+id)).data.document_work_state==='IDLE')break;await sleep(25);}
 await run(`async(page)=>{await page.goto('${url}/requirements/${id}');await page.getByRole('button',{name:'人工编辑',exact:true}).click();await page.locator('[aria-label=\"人工编辑草稿\"][contenteditable=\"true\"]').waitFor();${editable}await ${editor}.locator('p').last().click();await page.waitForTimeout(100);await page.keyboard.press('End');await page.waitForTimeout(100);await page.keyboard.press('Enter');await page.keyboard.insertText('工具栏验收的真实人工输入😀');${saved}await ${controls}.getByRole('button',{name:'完成编辑',exact:true}).click();await page.getByRole('button',{name:'人工编辑',exact:true}).waitFor();return true;}`);
 await api(`/requirements/${id}/manual-draft`,{expected_version:2});await api(`/requirements/${id}/manual-draft/complete`,{expected_version:1});
 if(status!=='INITIALIZING')await api(`/requirements/${id}/complete-initialization`,{expected_content_version:3});if(status==='COMPLETED')await api(`/requirements/${id}/complete`,{expected_version:3});
 let comment=null;if(dangerous){const current=(await api(`/requirements/${id}/current-document`)).data,block=current.block_state_json.blocks.findLast(b=>b.block_type==='paragraph');comment=(await api(`/requirements/${id}/comments`,{expected_content_version:3,content:'评论AI建议前置夹具',anchor_type:name==='COMMENT-BATCH-selection'?'SELECTION':'BLOCK',block_id:block.block_id,...(name==='COMMENT-BATCH-selection'?{selection:{selected_text:'真实人工输入😀',prefix_text:'',suffix_text:''}}:{})})).data;}
 const before=await inspect(id);assert.equal(before.current.content_version,3);assert.equal(before.requirement.status,status);
 await run(`async(page)=>{await page.evaluate(()=>{localStorage.clear();sessionStorage.clear();});await page.goto('${url}/requirements/${id}');${supported}await page.locator('.requirement-owned-document .ProseMirror[contenteditable=false]').waitFor();return true;}`);await cli('snapshot');
 const script=code(id,{before,comment});new Function('return ('+script+')');const result=await run(script);assert.equal(result.passed,true);
 if(name==='HEADER-initialization_mode-success'){
  const accepted=(await api(`/requirements/${id}/guide-runs`,{expected_version:3,action_type:'INITIALIZE',instruction:'核对模式变更后的新运行',scope_type:'DOCUMENT',source_type:'USER_INSTRUCTION'})).data;
  let subsequent;for(let i=0;i<200;i++){subsequent=(await api('/guide-runs/'+accepted.guide_run.id)).data;if(subsequent.status==='FAILED')break;await sleep(25);}
  assert.equal(subsequent.status,'FAILED');result.subsequent_run=subsequent;
 }
 const after=await inspect(id);assert.deepEqual(after.current,before.current);assert.deepEqual(result.current_before_discard,before.current);
 if(result.completed_initialization){assert.equal(before.revisions.items.length,0);assert.equal(after.revisions.items.length,1);assert.equal(after.revision_details[0].markdown_content,before.current.markdown_content);assert.deepEqual(after.revision_details[0].block_state_json,before.current.block_state_json);}
 else {assert.deepEqual(after.revisions,before.revisions);assert.deepEqual(after.revision_details,before.revision_details);}
 report.cases.push({name,before,comment,fixture:{status,dangerous},result,after});console.log(JSON.stringify({case:name,passed:true}));
}
try{
 await command(bash,['-lc','command -v npx >/dev/null 2>&1']);await command(process.execPath,['tools/spec-audit.mjs','check']);await command(process.execPath,[resolve(process.execPath,'../node_modules/npm/bin/npm-cli.js'),'run','build','--','--outDir',dist],{cwd:resolve(root,'frontend')});
 native=processRun(resolve(root,'.venv/Scripts/python.exe'),['-X','utf8','tools/api-browser-service.py','--database',database,'--frontend-dist',dist,'--seed-comment-suggestion-fixture']);
 for(let i=0;i<150;i++){const line=native.record.stdout.split('\n').find(line=>line.startsWith('{'));if(line){const value=JSON.parse(line);assert(value.ready);url=value.url;break;}assert.equal(native.child.exitCode,null,native.record.stderr);await sleep(100);}assert(url);
 await cli('open',url+'/requirements');opened=true;await cli('snapshot');
 await run(`async(page)=>{await page.addInitScript(()=>{const add=window.addEventListener.bind(window);window.detailUnloads=[];window.addEventListener=(type,listener,options)=>{if(type==='beforeunload')window.detailUnloads.push(listener);return add(type,listener,options);};const original=window.fetch.bind(window),c=window.detailWire={requests:[],writeMode:'NORMAL'};window.fetch=async(input,options)=>{const target=new URL(typeof input==='string'?input:input.url,location.href),path=target.pathname,method=options?.method||'GET',row={path,query:target.search,method,body:options?.body,key:options?.headers?.['Idempotency-Key'],delivered:false};c.requests.push(row);const write=method!=='GET',lose=write&&c.writeMode==='LOSE_ONCE',hold=write&&c.writeMode==='HOLD_ONCE';if(lose||hold)c.writeMode='NORMAL';if(write&&path.endsWith('/guide-runs')&&path.startsWith('/api/v1/comments/')&&c.beforeI34){const plan=c.beforeI34;delete c.beforeI34;const external=await original(plan.path,{method:plan.method,headers:{'Idempotency-Key':plan.key,...(plan.body?{'Content-Type':'application/json'}:{})},...(plan.body?{body:JSON.stringify(plan.body)}:{})});c.external={status:external.status,response:await external.json()};if(external.status!==plan.expected)throw Error('Explicit before-I34 external state failed');}const response=await original(input,options);row.status=response.status;row.response=await response.clone().json();if(hold){c.writeHeld=true;await new Promise(resolve=>c.releaseWrite=resolve);}if(lose)throw Error('Explicit actual native commit with receipt delivery loss');row.delivered=true;return response;};});return true;}`);
 const openComments=`await page.getByRole('button',{name:/^辅助面板/}).click();await page.getByRole('tab',{name:'评论',exact:true}).click();await page.getByRole('region',{name:'评论列表',exact:true}).waitFor();`;
 for(const kind of ['block','selection','unknown'])await fresh('COMMENT-BATCH-'+kind,(id,{comment,before})=>`async(page)=>{
 ${openComments}const card=page.locator('[data-comment-id="${comment.id}"]');await card.getByRole('button',{name:'让 AI 修改',exact:true}).waitFor();
 if('${kind}'==='unknown')await page.evaluate(()=>window.detailWire.writeMode='LOSE_ONCE');await card.getByRole('button',{name:'让 AI 修改',exact:true}).click();
 if('${kind}'==='unknown'){await card.getByRole('button',{name:'重新确认评论操作结果',exact:true}).click();}
 await page.waitForFunction(()=>document.querySelector('#detail-tab-AI')?.getAttribute('aria-selected')==='true');
 let wire=await page.evaluate(()=>window.detailWire),requests=wire.requests.filter(r=>r.method!=='GET'),receipt=requests.at(-1).response.data;
 if(requests.length!==${kind==='unknown'?2:1}||requests.some(r=>r.status!==202||r.path!=='/api/v1/comments/${comment.id}/guide-runs'||JSON.stringify(JSON.parse(r.body))!=='{"expected_content_version":3}'))throw Error('Original I34 changed fields/source or repeated');
 if('${kind}'==='unknown'&&(requests[0].key!==requests[1].key||requests[0].body!==requests[1].body||requests[0].delivered))throw Error('I34 unknown changed original identity');
 let run;for(let i=0;i<200;i++){run=(await(await page.request.get('${url}/api/v1/guide-runs/'+receipt.id)).json()).data;if(run.status==='COMPLETED')break;await page.waitForTimeout(25);}if(run.status!=='COMPLETED'||!run.suggestion_batch_id||run.source_id!==${comment.id}||run.function_type!=='MODIFY_FROM_COMMENT')throw Error('Explicit batch fixture not completed/linked');
 await page.getByRole('button',{name:'重新读取详情',exact:true}).click();const panel=page.getByRole('region',{name:'建议处理',exact:true});await panel.waitFor();await panel.locator('.suggestion-card').waitFor();
 const beforeBatch=(await(await page.request.get('${url}/api/v1/suggestion-batches/'+run.suggestion_batch_id)).json()).data;
 if(beforeBatch.source_type!=='COMMENT'||beforeBatch.source_id!==${comment.id}||beforeBatch.guide_run_id!==run.id||beforeBatch.base_content_version!==3||beforeBatch.suggestions.length!==1||beforeBatch.status!=='PENDING')throw Error('Comment batch lost original source/one patch');
 const currentBefore=(await(await page.request.get('${url}/api/v1/requirements/${id}/current-document')).json()).data;
 await page.screenshot({path:'output/playwright/${session}-${kind}-pending.png'});await panel.getByRole('button',{name:'放弃本批建议',exact:true}).click();const dialog=page.getByRole('dialog',{name:'放弃本批建议',exact:true});await dialog.getByRole('button',{name:'确认放弃',exact:true}).click();await dialog.waitFor({state:'detached'});
 await panel.getByText('本批已放弃',{exact:true}).waitFor();const finalBatch=(await(await page.request.get('${url}/api/v1/suggestion-batches/'+run.suggestion_batch_id)).json()).data,finalComment=(await(await page.request.get('${url}/api/v1/comments/${comment.id}')).json()).data;
 if(finalBatch.status!=='DISCARDED'||finalBatch.suggestions[0].status!=='PENDING'||JSON.stringify(finalComment)!==JSON.stringify(${JSON.stringify(comment)}))throw Error('Discard changed original comment/decision');
 return {passed:true,wire:await page.evaluate(()=>window.detailWire),finalComment,accepted_run:run,original_scope:receipt.scope.scope_ref,before_batch:beforeBatch,final_batch:finalBatch,current_before_discard:currentBefore,fixture_generation:true};
 }`,{dangerous:true});
 assert.equal(report.cases.length,selected.size);report.passed=true;
}catch(error){report.passed=false;report.error=String(error);process.exitCode=1;if(opened)try{report.failure_diagnostics=await run(`async(page)=>await page.evaluate(()=>({wire:window.detailWire,frame:document.querySelector('.requirement-detail-frame')?.outerHTML.slice(0,1600),route:location.pathname,preferences:localStorage.getItem('walle:v1:preferences'),editor:document.querySelector('.requirement-owned-document .ProseMirror')?.innerHTML}))`);await cli('snapshot');await cli('screenshot',`--filename=output/playwright/${session}-failure.png`);}catch(other){report.diagnostic_error=String(other);}}
finally{
 if(opened)try{await cli('close');}catch(error){report.close_error=String(error);report.passed=false;process.exitCode=1;}
 if(native){native.child.stdin.end('shutdown\n');let timer;try{await Promise.race([native.exited,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Owned native service shutdown exceeded 20 seconds')),20000);})]);}catch(error){report.shutdown_error=String(error);report.passed=false;process.exitCode=1;const killer=processRun('taskkill',['/PID',String(native.child.pid),'/T','/F']);await killer.exited;await native.exited;}finally{clearTimeout(timer);}report.native=native.record;const closed=native.record.stdout.trim().split('\n').filter(line=>line.startsWith('{')).map(line=>JSON.parse(line)).at(-1);report.native_facts=closed?.facts;if(native.record.code!==0||!closed?.closed||closed.facts.llm_uses!==0){report.passed=false;report.error??='Native cleanup or model isolation failed';process.exitCode=1;}report.database_sha256=createHash('sha256').update(await readFile(database)).digest('hex');}
 report.inputs_after=await hashes();report.changed_inputs=Object.keys(report.inputs_before).filter(key=>report.inputs_before[key]!==report.inputs_after[key]);if(report.changed_inputs.length){report.passed=false;report.error??='Source changed during verification';process.exitCode=1;}
 const path=resolve(root,'docs/verification',`comment-batch-browser-${report.timestamp.replace(/[:.]/g,'-')}-${session.split('-').at(-1)}.json`);await writeFile(path,JSON.stringify(report,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify({passed:report.passed,evidence:path,error:report.error}));
}
