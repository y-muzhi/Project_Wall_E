/** Owned temporary build/server/browser. The Python owner supplies a kill-on-close Job. */
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createServer } from 'node:http';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { randomUUID } from 'node:crypto';
const exec=promisify(execFile);
const root=resolve(import.meta.dirname,'..');
const args=process.argv.slice(2);
if(![4,6].includes(args.length) || args[0] !== '--work' || args[2] !== '--cli-entry' || (args.length === 6 && (args[4] !== '--probe' || !['all','configuration','settings','testing-settings','testing-plan-editor','testing-task-workspace','tasks','role-reconciliation','role-creation-reconciliation','repair-reconciliation','repair-creation-reconciliation','repair-settled-reconciliation','coding-report-link','coding-delivery','coding-records','coding-live-configuration'].includes(args[5]))))
 throw Error('Explicit owned work and installed CLI entry required');
const work=resolve(args[1]),entry=resolve(args[3]);
const mode=args.length === 6 ? args[5] : 'all';
if(!work.startsWith(resolve(root,'output/playwright')+'\\') ||
 !/^v20-idb-[a-z0-9_-]+$/.test(work.split(/[\\/]/).at(-1))) throw Error('Owned test directory required');
if(mode === 'settings' || mode === 'testing-settings' || mode === 'testing-plan-editor' || mode === 'testing-task-workspace' || mode === 'tasks' || mode === 'role-reconciliation' || mode === 'role-creation-reconciliation' || mode === 'repair-reconciliation' || mode === 'repair-creation-reconciliation' || mode === 'repair-settled-reconciliation' || mode === 'coding-report-link' || mode === 'coding-delivery' || mode === 'coding-records' || mode === 'coding-live-configuration'){
 const {verifySettingsPage}=await import('./verify-v20-settings-browser.mjs');
 await verifySettingsPage(root,work,entry,mode);
}else{
const {build}=await import(pathToFileURL(resolve(root,'frontend/node_modules/vite/dist/node/index.js')));
const dist=join(work,'compiled');await mkdir(dist);
await build({root:resolve(root,'frontend'),configFile:false,logLevel:'error',
 build:{outDir:dist,emptyOutDir:false,minify:false,
 lib:{entry:resolve(root,'frontend/tests/browser/v20-command-recovery-probe.ts'),
 formats:['es'],fileName:()=> 'probe.js'}}});
const script=await readFile(join(dist,'probe.js'));
const html=Buffer.from('<!doctype html><meta charset="utf-8"><title>V2命令存储专项</title><p>隔离存储专项</p><script type="module">import * as probe from "/probe.js"; window.w2Probe=probe;</script>');
const server=createServer((request,response)=>{
 response.setHeader('Cache-Control','no-store');
 if(request.url === '/'){response.setHeader('Content-Type','text/html; charset=utf-8');response.end(html);}
 else if(request.url === '/probe.js'){response.setHeader('Content-Type','text/javascript; charset=utf-8');response.end(script);}
 else{response.statusCode=404;response.end();}
});
await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
const origin='http://127.0.0.1:'+server.address().port;
const session='w20-idb-'+randomUUID().slice(0,8);
const config=join(work,'cli.config.json');
await mkdir(join(work,'temp'),{recursive:true});
await writeFile(config,JSON.stringify({browser:{browserName:'chromium',isolated:true,
 launchOptions:{executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,
 args:['--disable-background-networking','--disable-component-update','--disable-sync']},
 contextOptions:{serviceWorkers:'block',viewport:{width:1000,height:700}}},
 outputDir:join(work,'artifacts'),outputMode:'stdout'}),{flag:'wx'});
const env={...process.env,PWTEST_DAEMON_SESSION_DIR:join(work,'daemon'),TEMP:join(work,'temp'),TMP:join(work,'temp')};
async function cli(...commands){
 const result=await exec(process.execPath,[entry,'-s='+session,...commands],
  {cwd:work,env,windowsHide:true,timeout:60000,maxBuffer:4*1024*1024,encoding:'utf8'});
 if(result.stdout.includes('### Error')) throw Error(result.stdout);
 return result.stdout;
}
let opened=false;
try{
 console.log('OWNED_BROWSER_ORIGIN '+origin);
 const startup=await cli('open',origin,'--config',config,'--idle-timeout=30000');
 opened=true;
 if(!startup.includes('opened'))throw Error(startup);
 if(mode === 'configuration'){
  const configuration=await cli('run-code',`async(page)=>{await page.waitForFunction(()=>Boolean(window.w2Probe));const configuration=await page.evaluate(async()=>window.w2Probe.configurationProbe());return {passed:true,configuration};}`);
  if(! /"passed"\s*:\s*true/.test(configuration))throw Error(configuration);
  console.log(configuration.slice(0,10000));
 }else{
 const storage=await cli('run-code',`async(page)=>{
  await page.waitForFunction(()=>Boolean(window.w2Probe));
  const storage=await page.evaluate(async()=>window.w2Probe.storageProbe());
  const owner=await page.evaluate(async()=>window.w2Probe.ownerProbe());
  const bounds=await page.evaluate(async()=>window.w2Probe.boundsProbe());
  return {passed:true,storage,owner,bounds};
 }`);
 if(! /"passed"\s*:\s*true/.test(storage))throw Error(storage);
 console.log(storage.slice(0,10000));
 const tabs=await cli('run-code',`async(page)=>{
  const second=await page.context().newPage();const name='walle-v20-idb-probe-'+crypto.randomUUID();
  try{
   await second.goto(${JSON.stringify(origin)});
   await second.waitForFunction(()=>Boolean(window.w2Probe));
   const stages=await Promise.all([
     page.evaluate(name=>window.w2Probe.stageInTab(name),name),
     second.evaluate(name=>window.w2Probe.stageInTab(name),name)]);
   if(stages.filter(row=>row.kind==='PREPARED').length!==1 ||
      stages.filter(row=>row.kind==='EXISTING').length!==1 ||
      stages[0].key!==stages[1].key)throw Error('Real tab unique intent failed');
   const gates=await Promise.all([
     page.evaluate(name=>window.w2Probe.dispatchInTab(name),name),
     second.evaluate(name=>window.w2Probe.dispatchInTab(name),name)]);
   if(gates.filter(row=>row.passed).length!==1 ||
      gates.filter(row=>row.count===1).length!==1)throw Error('Real tab dispatch CAS failed');
   return {passed:true,scope:'two actual tabs, one durable original intent and one dispatch gate'};
  }finally{
   await page.evaluate(name=>window.w2Probe.closeTabOwner(name),name);
   await second.evaluate(name=>window.w2Probe.closeTabOwner(name,true),name);
   await second.close();
  }
 }`);
 if(! /"passed"\s*:\s*true/.test(tabs))throw Error(tabs);
 console.log(tabs.slice(0,5000));
 }
 console.log('V20_IDB_BROWSER_PASSED');
}finally{
 try{await cli('close');console.log('OWNED_BROWSER_CLOSED');}
 catch(error){console.error('OWNED_BROWSER_CLOSE_UNVERIFIED '+String(error));process.exitCode=1;}
 await new Promise(resolve=>server.close(resolve));
}

}
