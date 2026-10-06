import {spawnSync} from 'node:child_process';
import {readdirSync,readFileSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {createHash} from 'node:crypto';
const root=resolve(import.meta.dirname,'..');
function hashes(){
 const files=readdirSync(resolve(root,'backend'),{recursive:true,withFileTypes:true})
  .filter(entry=>entry.isFile()&&/\.(py|sql|json|md|lock)$/.test(entry.name)).map(entry=>resolve(entry.parentPath,entry.name));
 files.push(resolve(root,'tools/verify-counted-runtime.mjs'));
 return Object.fromEntries(files.sort().map(path=>[path.slice(root.length+1).replaceAll('\\','/'),createHash('sha256').update(readFileSync(path)).digest('hex')]));
}
const regression=process.argv.includes('--regression');
if(process.argv.slice(2).some(arg=>arg!=='--regression'))throw Error('Unknown option');
const modules=['backend.tests.guide.test_counted_orchestrator','backend.tests.infrastructure.test_counting_journal','backend.tests.guide.test_counted_worker'];
if(regression)modules.push('backend.tests.guide.test_counted_context','backend.tests.infrastructure.test_tokenization','backend.tests.infrastructure.test_audit_repository','backend.tests.guide.test_trusted_output','backend.tests.guide.test_orchestrator','backend.tests.guide.test_worker');
const record={scope:'D-011 native counted ORCH and independent filesystem audit; actual local count/Chat TCP, SQLite and C07 under explicit offline compatibility injections. Candidate remains pending real framing proof; no real Ark/paid/effect/complete acceptance claim. Scope is the named tests.',recorded_at:new Date().toISOString(),inputs_before:hashes(),commands:[]};
for(const [command,args] of [[process.execPath,['tools/spec-audit.mjs','check']],[resolve(root,'.venv/Scripts/python.exe'),['-X','utf8','-m','unittest',...modules,'-v']]]){const result=spawnSync(command,args,{cwd:root,encoding:'utf8',windowsHide:true,maxBuffer:4*1024*1024});record.commands.push({command,args,code:result.status,error:result.error?.message??null,stdout:result.stdout,stderr:result.stderr});}
record.inputs_after=hashes();record.changed_inputs=[...new Set([...Object.keys(record.inputs_before),...Object.keys(record.inputs_after)])].filter(path=>record.inputs_before[path]!==record.inputs_after[path]);record.diagnostic_errors=record.commands.filter(result=>result.stderr.includes('Traceback (most recent call last):')).map(result=>result.command);record.passed=record.changed_inputs.length===0&&record.diagnostic_errors.length===0&&record.commands.every(result=>result.code===0&&result.error===null);
const path=resolve(root,'docs/verification',`counted-runtime-${record.recorded_at.replace(/[:.]/g,'-')}.json`);writeFileSync(path,JSON.stringify(record,null,2)+'\n');console.log(JSON.stringify({passed:record.passed,evidence:path}));if(!record.passed)process.exitCode=1;
