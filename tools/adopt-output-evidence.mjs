import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { resolve, relative, isAbsolute } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const source = resolve(root, 'docs/proposals/resources-v2');
const target = resolve(root, 'backend/resources/v2');
const recordPath = 'docs/output-evidence-adoption-v2.json';
const approvedManifest = '06a2048688b5d014a69384ed39b2599993caa00cc59c2af96102039da98757dd';
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
if (existsSync(target) || existsSync(resolve(root, recordPath))) throw new Error('Refusing overwrite of immutable v2 adoption');
const decision = readFileSync(resolve(root, 'docs/决策记录.md'), 'utf8');
if (!decision.includes('## D-010') || !decision.includes(approvedManifest)) throw new Error('Record the actual D-010 approval first');
const manifestBytes = readFileSync(resolve(source, 'manifest.json'));
if (sha(manifestBytes) !== approvedManifest) throw new Error('Candidate manifest differs from human-approved identity');
const manifest = JSON.parse(manifestBytes);
if (manifest.status !== 'PROPOSED' || manifest.files.length !== 30) throw new Error('Expected complete proposed v2 release');
const approved = ['docs/proposals/output-evidence-equivalence-v1.md', 'docs/proposals/output-evidence-resources-v2-review.md', 'docs/proposals/resources-v2/manifest.json']
  .map(path => ({path, sha256: sha(readFileSync(resolve(root, path)))}));
const pending = [];
const paths = new Set();
for (const entry of manifest.files) {
  const path = resolve(source, entry.path), rel = relative(source, path);
  if (!rel || rel.startsWith('..') || isAbsolute(rel) || paths.has(entry.path)) throw new Error('Unsafe or duplicated candidate path');
  paths.add(entry.path);
  const original = readFileSync(path);
  if (original.length !== entry.bytes || sha(original) !== entry.sha256) throw new Error(`Approved candidate changed: ${entry.path}`);
  let adopted = original;
  if (entry.path === 'functions.v2.json') {
    const value = JSON.parse(original);
    if (value.proposal !== true) throw new Error('Missing expected proposal annotation');
    adopted = Buffer.from(original.toString('utf8').replace('"proposal": true', '"proposal": false'));
  }
  pending.push({entry, adopted});
  approved.push({path: 'docs/proposals/resources-v2/' + entry.path, sha256: entry.sha256});
}
// Complete verification precedes any writes. A partial failed adoption is never
// overwritten or loaded: the immutable manifest is written last.
const files = pending.map(({entry, adopted}) => ({path:entry.path, sha256:sha(adopted), bytes:adopted.length, proposal_sha256:entry.sha256}));
const adoptedManifest = Buffer.from(JSON.stringify({schema_version:1,status:'APPROVED',decision:'D-010',version:'v2',base_manifest_sha256:manifest.base_manifest_sha256,files},null,2)+'\n');
for (const {entry, adopted} of pending) {
  const path = resolve(target,entry.path);
  mkdirSync(resolve(path,'..'),{recursive:true}); writeFileSync(path,adopted,{flag:'wx'});
}
writeFileSync(resolve(root,recordPath),JSON.stringify({decision:'D-010',user_confirmation:'确认算法与完整v2候选，按稿接入（推荐）',recorded_at:new Date().toISOString(),approved_manifest_sha256:approvedManifest,approved,files,manifest_sha256:sha(adoptedManifest),annotation_changes_only:['functions.v2.json: proposal true to false'],exclusions:['tokenizer/framing compatibility proof','real model effects and evaluation samples/thresholds','paid calls and budget'],legacy_resources:'v1 bytes and restoration preserved'},null,2)+'\n',{flag:'wx'});
writeFileSync(resolve(target,'manifest.json'),adoptedManifest,{flag:'wx'});
console.log(JSON.stringify({record:recordPath,manifest_sha256:sha(adoptedManifest),files:files.length}));
