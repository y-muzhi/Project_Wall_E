import {spawn} from 'node:child_process';
import {cp,mkdir,readdir,readFile,writeFile} from 'node:fs/promises';
import {resolve,basename} from 'node:path';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';

// Fresh project-local dependencies and database, never the user's normal data.
const root=resolve(import.meta.dirname,'..'),stamp=new Date().toISOString();
const target=resolve(root,'output',`clean-install-${stamp.replace(/[:.]/g,'-')}`);
const report={timestamp:stamp,scope:'Fresh copied actual source, locked npm/pip installs, real production TS/Vite build, explicit database CLI and actual Python SPA/API lifespan over TCP. Local smoke only; no Provider, complete browser scenarios, runtime crash investigation or whole acceptance.',commands:[]};
const env=Object.fromEntries(Object.entries(process.env).filter(([key])=>!key.startsWith('WALLE_MODEL_')&&!['PYTHONPATH','WALLE_DATABASE_PATH','WALLE_FRONTEND_DIST'].includes(key)));
function child(command,args,options={}){const process=spawn(command,args,{cwd:target,env,windowsHide:true,...options}),record={command,args,stdout:'',stderr:'',code:null};process.stdout.on('data',data=>record.stdout+=data);process.stderr.on('data',data=>record.stderr+=data);const exited=new Promise((accept,reject)=>{process.once('error',reject);process.once('exit',code=>{record.code=code;accept(code);});});return {process,record,exited};}
async function command(executable,args,options={}){const task=child(executable,args,options);await task.exited;report.commands.push(task.record);assert.equal(task.record.code,0,`${basename(executable)} ${args.join(' ')} failed: ${task.record.stderr}`);return task.record;}
async function hashes(base){const files=[];async function walk(path){for(const entry of await readdir(path,{withFileTypes:true})){if(['node_modules','dist','__pycache__','.pytest_cache'].includes(entry.name))continue;const item=resolve(path,entry.name);if(entry.isDirectory())await walk(item);else if(/\.(py|sql|json|ts|tsx|html|mjs|css|lock|in)$/.test(entry.name))files.push(item);}}for(const name of ['backend','frontend','shared'])await walk(resolve(base,name));return Object.fromEntries(await Promise.all(files.sort().map(async file=>[file.slice(base.length+1).replaceAll('\\','/'),createHash('sha256').update(await readFile(file)).digest('hex')])));}
const wait=delay=>new Promise(accept=>setTimeout(accept,delay));let service;
try{
 report.source_before=await hashes(root);await mkdir(target,{recursive:true});
 for(const name of ['backend','frontend','shared'])await cp(resolve(root,name),resolve(target,name),{recursive:true,filter:source=>!['node_modules','dist','__pycache__','.pytest_cache'].includes(basename(source))});
 await mkdir(resolve(target,'tools'));await cp(resolve(root,'tools/api-browser-service.py'),resolve(target,'tools/api-browser-service.py'));
 report.copy_before=await hashes(target);assert.deepEqual(report.copy_before,report.source_before);
 const setup=await Promise.allSettled([
  command(resolve(root,'.venv/Scripts/python.exe'),['-m','venv',resolve(target,'.venv')]),
  command(process.execPath,[resolve(process.execPath,'../node_modules/npm/bin/npm-cli.js'),'ci','--no-audit','--no-fund'],{cwd:resolve(target,'frontend')})
 ]);for(const result of setup)if(result.status==='rejected')throw result.reason;
 const python=resolve(target,'.venv/Scripts/python.exe');
 await command(python,['-X','utf8','-m','pip','install','--disable-pip-version-check','-r','backend/requirements.lock']);
 await command(python,['-X','utf8','-m','pip','check']);
 await command(process.execPath,[resolve(process.execPath,'../node_modules/npm/bin/npm-cli.js'),'run','build'],{cwd:resolve(target,'frontend')});
 const output=resolve(target,'output/playwright');await mkdir(output,{recursive:true});
 const explicit=resolve(output,'clean-cli.sqlite'),configured={...env,WALLE_DATABASE_PATH:explicit};
 await command(python,['-X','utf8','-m','backend.app.infrastructure.database','init'],{env:configured});
 await command(python,['-X','utf8','-m','backend.app.infrastructure.database','check'],{env:configured});
 service=child(python,['-X','utf8','tools/api-browser-service.py','--database',resolve(output,'api-walle-clean.sqlite'),'--frontend-dist',resolve(target,'frontend/dist')]);
 let url;for(let index=0;index<150;index++){const line=service.record.stdout.split('\n').find(line=>line.startsWith('{'));if(line){const ready=JSON.parse(line);assert.equal(ready.ready,true);url=ready.url;break;}if(service.process.exitCode!==null)throw Error(service.record.stderr);await wait(100);}assert.match(url??'',/^http:\/\/127\.0\.0\.1:[0-9]+$/);
 const index=await fetch(url+'/requirements');assert.equal(index.status,200);const html=await index.text();assert(html.includes('id="root"'));assert.equal((await fetch(url+'/requirements/1')).status,200);
 const asset=html.match(/src="([^"]+\.js)"/)[1];const script=await fetch(url+asset);assert.equal(script.status,200);assert((await script.text()).length>10000);
 assert.equal((await fetch(url+'/src/main.tsx')).status,404);assert.equal((await fetch(url+'/api/not-a-binding')).status,404);
 const empty=await fetch(url+'/api/v1/requirements');assert.equal(empty.status,200);assert.equal((await empty.json()).meta.pagination.total,0);
 const body={title:'干净安装实际需求',requirement_type:'NEW',template_key:'new-requirement',template_version:'v1',initial_idea:'正式受理与持久化联调。',initialization_mode:'DESIGN'};
 const created=await fetch(url+'/api/v1/requirements',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID()},body:JSON.stringify(body)});assert.equal(created.status,201);const accepted=await created.json();assert.equal(accepted.data.requirement.id,1);
 const current=await fetch(url+'/api/v1/requirements/1/current-document');assert.equal(current.status,200);const actual=await current.json();assert.equal(actual.data.content_version,1);assert(actual.data.block_state_json.blocks.length>0);
 report.smoke={passed:true,url,asset,accepted,current:actual};report.passed=true;
}catch(error){report.passed=false;report.error=String(error);process.exitCode=1;}
finally{
 if(service){if(service.process.exitCode===null&&service.process.signalCode===null){service.process.stdin.end('shutdown\n');let timer;try{await Promise.race([service.exited,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Clean native service shutdown exceeded wait')),20000);})]);}catch(error){report.shutdown_error=String(error);report.passed=false;process.exitCode=1;if(process.platform==='win32'){const killer=child('taskkill',['/PID',String(service.process.pid),'/T','/F']);await killer.exited;}else service.process.kill();await service.exited;}finally{clearTimeout(timer);}}
  report.service=service.record;const lines=service.record.stdout.trim().split('\n').filter(line=>line.startsWith('{')),closed=lines.length>1?JSON.parse(lines.at(-1)):null;report.native_facts=closed?.facts;if(!closed?.closed||service.record.code!==0||closed.facts.requirements!==1||closed.facts.requirement_documents!==1||closed.facts.guide_runs!==1||closed.facts.llm_uses!==0){report.passed=false;report.error??='Clean native closure/facts differ';process.exitCode=1;}}
 report.source_after=await hashes(root);report.source_changes=Object.keys(report.source_before??{}).filter(key=>report.source_before[key]!==report.source_after[key]);
 if(report.copy_before){report.copy_after=await hashes(target);report.copy_changes=Object.keys(report.copy_before).filter(key=>report.copy_before[key]!==report.copy_after[key]);}
 if(report.source_changes.length||report.copy_changes?.length){report.passed=false;report.error??='Source/lock inputs changed';process.exitCode=1;}
 report.target=target;const path=resolve(root,'docs/verification',`clean-install-${stamp.replace(/[:.]/g,'-')}.json`);await writeFile(path,JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({passed:report.passed,evidence:path,error:report.error}));
}
