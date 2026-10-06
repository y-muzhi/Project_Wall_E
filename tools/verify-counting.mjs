import {spawnSync} from 'node:child_process';
import {readdirSync,readFileSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {createHash} from 'node:crypto';
const root=resolve(import.meta.dirname,'..');
function hashes(){
 const files=readdirSync(resolve(root,'backend'),{recursive:true,withFileTypes:true})
  .filter(entry=>entry.isFile()&&/\.(py|sql|json|md|lock)$/.test(entry.name)).map(entry=>resolve(entry.parentPath,entry.name));
 files.push(resolve(root,'tools/verify-counting.mjs'),resolve(root,'docs/proposals/context-budget-compatibility-v1.md'),resolve(root,'docs/proposals/context-budget-approval-v1.json'));
 return Object.fromEntries(files.sort().map(path=>[path.slice(root.length+1).replaceAll('\\','/'),createHash('sha256').update(readFileSync(path)).digest('hex')]));
}
const record={scope:'D-011 standalone reachable-schema derivation, exact Ark text-count adapter and frozen compiler candidate: actual local TCP/C03 SQLite, exact field serialization and ownership, unchanged budgets, whole-history then optional-block recount, immutable v1/v2 resources. No real Ark calls, Chat framing proof, production Builder/Audit/ORCH enablement, paid/effect or complete acceptance claim.',timestamp:new Date().toISOString(),inputs_before:hashes(),commands:[]};
for(const [command,args] of [[process.execPath,['tools/spec-audit.mjs','check']],[resolve(root,'.venv/Scripts/python.exe'),['-X','utf8','-m','unittest','backend.tests.infrastructure.test_schema_transport','backend.tests.infrastructure.test_tokenization','backend.tests.infrastructure.test_model_profile_audit_data','backend.tests.guide.test_model_context','backend.tests.guide.test_counted_context','-v']]]){const result=spawnSync(command,args,{cwd:root,encoding:'utf8',windowsHide:true});record.commands.push({command,args,code:result.status,error:result.error?.message??null,stdout:result.stdout,stderr:result.stderr});}
record.inputs_after=hashes();record.changed_inputs=[...new Set([...Object.keys(record.inputs_before),...Object.keys(record.inputs_after)])].filter(path=>record.inputs_before[path]!==record.inputs_after[path]);record.passed=record.changed_inputs.length===0&&record.commands.every(result=>result.code===0&&result.error===null);
const path=resolve(root,'docs/verification',`counting-adapters-${record.timestamp.replace(/[:.]/g,'-')}.json`);writeFileSync(path,JSON.stringify(record,null,2)+'\n');console.log(JSON.stringify({passed:record.passed,evidence:path}));if(!record.passed)process.exitCode=1;
