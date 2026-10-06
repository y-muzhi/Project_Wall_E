import {spawnSync} from 'node:child_process';
import {readFileSync,readdirSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {createHash} from 'node:crypto';
const root=resolve(import.meta.dirname,'..');
function hashes(){
 const files=readdirSync(resolve(root,'backend'),{recursive:true,withFileTypes:true})
  .filter(e=>e.isFile()&&/\.(py|sql|json|md|lock)$/.test(e.name)).map(e=>resolve(e.parentPath,e.name));
 files.push(resolve(root,'tools/verify-product-flow.py'),resolve(root,'tools/product-suggestions-flow.py'),resolve(root,'tools/verify-product-flow.mjs'));
 return Object.fromEntries(files.sort().map(p=>[p.slice(root.length+1).replaceAll('\\','/'),createHash('sha256').update(readFileSync(p)).digest('hex')]));
}
const record={scope:'Independent actual TC-E2E-01/02/03/04 HTTP/worker/local count and Chat TCP/native C07/baseline/manual save-complete-cancel/six SQL rollback barriers and independently referenced suggestion application/no-change/table/failure/discard branches, plus both card continuation paths with native concurrency barrier/committed response loss. Fresh SQLite per case, explicit private offline compatibility fixtures. No paid Provider or full project acceptance.',recorded_at:new Date().toISOString(),before:hashes(),commands:[]};
for(const [command,args] of [
 [process.execPath,['tools/spec-audit.mjs','check']],
 [resolve(root,'.venv/Scripts/python.exe'),['-X','utf8','tools/verify-product-flow.py']]]){
 const result=spawnSync(command,args,{cwd:root,windowsHide:true,encoding:'utf8',maxBuffer:4*1024*1024,env:{...process.env,PYTHONIOENCODING:'utf-8'}});
 record.commands.push({command,args,exit_code:result.status,error:result.error?.message??null,stdout:result.stdout,stderr:result.stderr});
}
record.after=hashes();record.inputs_unchanged=JSON.stringify(record.before)===JSON.stringify(record.after);
record.passed=record.inputs_unchanged&&record.commands.every(c=>c.exit_code===0&&c.error===null&&!c.stderr.includes('Traceback (most recent call last):'));
const path=resolve(root,'docs/verification',`product-flow-command-${record.recorded_at.replace(/[:.]/g,'-')}.json`);
writeFileSync(path,JSON.stringify(record,null,2)+'\n');console.log(JSON.stringify({passed:record.passed,evidence:path}));if(!record.passed)process.exitCode=1;
