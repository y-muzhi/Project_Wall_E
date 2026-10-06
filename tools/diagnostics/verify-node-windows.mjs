import {spawn} from 'node:child_process';
import {createServer,request} from 'node:http';
import {once} from 'node:events';
import {resolve} from 'node:path';
import {mkdir,readFile,writeFile,readdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
const root=resolve(import.meta.dirname,'../..');
const [runtime,mode='fetch-exit',count='100']=process.argv.slice(2);
assert(runtime);assert(['fetch-exit','http','dev','preview'].includes(mode));assert(/^[1-9][0-9]*$/.test(count));
const rounds=Number(count),stamp=new Date().toISOString().replaceAll(':','-').replaceAll('.','-');
const dir=resolve(root,'output/runtime-diagnostics',stamp);await mkdir(dir,{recursive:true});
const env=Object.fromEntries(Object.entries(process.env).filter(([key])=>['SYSTEMROOT','WINDIR','PATH','PATHEXT','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA','COMSPEC'].includes(key.toUpperCase())));
const report={timestamp:stamp,scope:'Isolated runtime/HTTP cancellation/actual Vite config dev or preview; no DB/business/Provider. Fetch-exit deliberately reproduces upstream teardown and is separate from live Vite evidence.',runtime:resolve(runtime),mode,rounds,exe_sha256:createHash('sha256').update(await readFile(runtime)).digest('hex'),records:[],passed:false};
const fixture=resolve(dir,'static');await mkdir(resolve(fixture,'tests/browser'),{recursive:true});await writeFile(resolve(fixture,'tests/browser/api.html'),'<!doctype html><title>runtime isolation</title>');
let upstream;
try {
  upstream=createServer((req,res)=>{
    if(req.url.includes('reset')){req.socket.destroy();return;}
    if(req.url.includes('slow')){const timer=setTimeout(()=>res.end('isolated-delay'),25);res.on('close',()=>clearTimeout(timer));return;}
    res.setHeader('Content-Type','application/json');res.end('{"isolated":true}');
  });upstream.listen(0,'127.0.0.1');await once(upstream,'listening');env.WALLE_DIAGNOSTIC_URL=`http://127.0.0.1:${upstream.address().port}`;
  for(let i=0;i<rounds;i++){
    const args=['--report-on-fatalerror','--report-exclude-env',`--report-directory=${dir}`,resolve(root,'tools/diagnostics/node-windows-child.mjs'),mode,root,fixture];
    const child=spawn(runtime,args,{env,windowsHide:true,stdio:['pipe','pipe','pipe']});
    const record={i,pid:child.pid,args,stdout:'',stderr:'',code:null,signal:null,timeout:false,requests:0};report.records.push(record);
    child.stdout.on('data',data=>record.stdout+=data);child.stderr.on('data',data=>record.stderr+=data);
    const done=new Promise((accept,reject)=>{child.once('error',reject);child.once('close',(code,signal)=>{record.code=code;record.signal=signal;accept();});});
    let monitor,monitored;
    if(process.env.WALLE_DIAGNOSTIC_PROCDUMP){
      monitor=spawn(process.env.WALLE_DIAGNOSTIC_PROCDUMP,['-accepteula','-e','-ma',String(child.pid),dir],{env,windowsHide:true});
      record.monitor={stdout:'',stderr:'',code:null};monitor.stdout.on('data',data=>record.monitor.stdout+=data);monitor.stderr.on('data',data=>record.monitor.stderr+=data);
      monitored=new Promise((accept,reject)=>{monitor.once('error',reject);monitor.once('close',code=>{record.monitor.code=code;accept();});});
      await new Promise(accept=>setTimeout(accept,700));
    }
    const timer=setTimeout(()=>{record.timeout=true;child.kill();},30000);
    try{
      if(mode!=='fetch-exit'){
        let ready;
        for(let poll=0;poll<300;poll++){
          ready=record.stdout.split('\n').filter(line=>line.startsWith('{')).map(line=>JSON.parse(line)).find(line=>line.ready);
          if(ready||record.code!==null)break;await new Promise(accept=>setTimeout(accept,20));
        }
        assert(ready,'Ready child required');
        for(let wave=0;wave<10;wave++)await Promise.all(Array.from({length:30},(_,n)=>new Promise(accept=>{
          const type=n%3,url=ready.url+'/api/'+(type===0?'ok':type===1?'slow':'reset');
          const req=request(url,{agent:false},res=>{res.resume();res.once('end',accept);res.once('error',accept);});
          req.on('error',accept);req.on('close',accept);req.end();if(type===1)setTimeout(()=>req.destroy(),2);record.requests++;
        })));
        // A fresh socket avoids the driver reusing an idle fetch pool for a recycled ephemeral port.
        record.health=await new Promise((accept,reject)=>{const req=request(ready.url+'/api/ok',{agent:false},res=>{let body='';res.on('data',data=>body+=data);res.on('end',()=>accept({status:res.statusCode,body}));res.on('error',reject);});req.setTimeout(3000,()=>req.destroy(new Error('Health timeout')));req.on('error',reject);req.end();});
        assert.equal(record.health.status,200);assert.equal(JSON.parse(record.health.body).isolated,true);
        // Stay alive after the socket churn; faults during service cannot be masked by shutdown.
        await new Promise(accept=>setTimeout(accept,100));assert.equal(child.exitCode,null,'Live child died');
        child.stdin.end('close\n');
      }
      await done;
    }finally{clearTimeout(timer);if(child.exitCode===null&&child.signalCode===null){child.kill();await done;}if(monitored)await monitored;}
    if(record.code!==0||record.timeout)break;
    // Bound port churn below Windows' ephemeral pool; execute matrices sequentially.
    await new Promise(accept=>setTimeout(accept,3000));
    if((i+1)%10===0)console.log(JSON.stringify({progress:i+1,mode}));
  }
  report.passed=report.records.length===rounds&&report.records.every(r=>r.code===0&&!r.timeout);
}catch(error){report.error={name:error.name,message:error.message,stack:error.stack,cause:error.cause?.message,code:error.code};}
finally{if(upstream){upstream.closeAllConnections();await new Promise(accept=>upstream.close(accept));}}
report.native_reports=await readdir(dir);const evidence=resolve(root,'docs/verification',`node-windows-${mode}-${stamp}.json`);await writeFile(evidence,JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({passed:report.passed,completed:report.records.length,evidence,last:report.records.at(-1)&&{pid:report.records.at(-1).pid,code:report.records.at(-1).code,requests:report.records.at(-1).requests,stderr_tail:report.records.at(-1).stderr.slice(-700),monitor:report.records.at(-1).monitor}}));if(!report.passed)process.exitCode=1;
