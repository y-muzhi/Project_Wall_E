import {spawnSync} from 'node:child_process';
import {readdirSync,readFileSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {createHash} from 'node:crypto';
const root=resolve(import.meta.dirname,'..');
const python=resolve(root,'.venv/Scripts/python.exe');
function hashes(){
 const files=readdirSync(resolve(root,'backend'),{recursive:true,withFileTypes:true}).filter(entry=>entry.isFile()&&/\.(py|sql|json|md|lock)$/.test(entry.name)).map(entry=>resolve(entry.parentPath,entry.name));
 files.push(resolve(root,'tools/framing-probe.py'),resolve(root,'tools/verify-framing-probe.mjs'));
 return Object.fromEntries(files.sort().map(path=>[path.slice(root.length+1).replaceAll('\\','/'),createHash('sha256').update(readFileSync(path)).digest('hex')]));
}
const record={scope:'Private six-function framing observation plan/collector: actual local TCP count/Chat, fixed signed resources and parameters, explicit exact-plan authorization, fsync/unknown/no replay/30-day local maintenance. Default CLI prepare and inspect are offline. No real Ark/paid execution, universal framing proof, production enablement, effects or whole acceptance claim.',recorded_at:new Date().toISOString(),before:hashes(),commands:[]};
function run(command,args){const result=spawnSync(command,args,{cwd:root,encoding:'utf8',windowsHide:true,maxBuffer:4*1024*1024,env:{...process.env,PYTHONIOENCODING:'utf-8'}});const value={command,args,code:result.status,error:result.error?.message??null,stdout:result.stdout,stderr:result.stderr};record.commands.push(value);return value;}
run(process.execPath,['tools/spec-audit.mjs','check']);
run(python,['-m','unittest','backend.tests.infrastructure.test_framing_probe','backend.tests.infrastructure.test_tokenization','backend.tests.infrastructure.test_model_gateway','-v']);
const prepared=run(python,['tools/framing-probe.py','--prepare']);
if(prepared.code===0){try{const value=JSON.parse(prepared.stdout);record.prepared=value;run(python,['tools/framing-probe.py','--plan',value.plan]);}catch(error){record.prepare_error=String(error);}}
record.after=hashes();record.changed_inputs=[...new Set([...Object.keys(record.before),...Object.keys(record.after)])].filter(path=>record.before[path]!==record.after[path]);record.diagnostic_errors=record.commands.filter(value=>value.stderr.includes('Traceback (most recent call last):')).map(value=>value.command);
record.passed=record.changed_inputs.length===0&&record.diagnostic_errors.length===0&&!record.prepare_error&&record.commands.every(value=>value.code===0&&value.error===null)&&record.prepared?.paid_requests===0;
const path=resolve(root,'docs/verification',`framing-probe-${record.recorded_at.replace(/[:.]/g,'-')}.json`);writeFileSync(path,JSON.stringify(record,null,2)+'\n');console.log(JSON.stringify({passed:record.passed,evidence:path}));if(!record.passed)process.exitCode=1;
