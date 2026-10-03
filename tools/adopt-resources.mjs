import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const proposals = resolve(root, 'docs/proposals');
const source = resolve(proposals, 'resources-v1');
const target = resolve(root, 'backend/resources/v1');
const adoptionPath = resolve(root, 'docs/resource-adoption-v1.json');
if (existsSync(adoptionPath)) throw new Error('Already adopted: do not overwrite frozen resources');
const decision = readFileSync(resolve(root, 'docs/决策记录.md'), 'utf8');
if (!decision.includes('## D-004') || !decision.includes('## D-005')) throw new Error('Actual user decisions must be recorded before adoption');
const evidence = JSON.parse(readFileSync(resolve(root, 'docs/verification/proposals-v1.json'), 'utf8'));
const resourceManifest = JSON.parse(readFileSync(resolve(source, 'manifest.json'), 'utf8'));
const sha = content => createHash('sha256').update(content).digest('hex');
const entries = [];
for (const file of resourceManifest.files) {
  const original = readFileSync(resolve(source, file.path), 'utf8');
  if (sha(original) !== file.sha256) throw new Error(`Proposal has changed since approval: ${file.path}`);
  // Remove review annotations only, with no field/behavior change.
  let adopted = original;
  if (file.path.startsWith('schemas/')) adopted = adopted.replace('urn:walle:proposal:', 'urn:walle:').replace(' (unapproved proposal)', '');
  if (file.path.startsWith('prompts/')) adopted = adopted.replace('（待确认）', '');
  if (file.path.endsWith('.json')) adopted = adopted.replaceAll('"proposal": true', '"proposal": false');
  const path = resolve(target, file.path);
  if (existsSync(path)) throw new Error(`Refusing overwrite of frozen ${file.path}`);
  mkdirSync(resolve(path, '..'), { recursive: true });
  writeFileSync(path, adopted);
  entries.push({ path: file.path, sha256: sha(adopted), proposal_sha256: sha(original), bytes: Buffer.byteLength(adopted) });
}
const sqlOriginal = readFileSync(resolve(proposals, 'storage-v1.sql'), 'utf8');
if (sha(sqlOriginal) !== evidence.content_hashes['storage-v1.sql']) throw new Error('DDL changed since approval');
const sql = sqlOriginal.replace('-- UNAPPROVED PROPOSAL. Never apply this file to a production database before confirmation.', '-- Approved implementation supplement D-003/D-005, 2026-10-03. Version 1; do not modify after migration use.');
const ddlPath = resolve(root, 'backend/app/infrastructure/migrations/001_initial.sql');
if (existsSync(ddlPath)) throw new Error('Do not overwrite a registered migration');
mkdirSync(resolve(ddlPath, '..'), { recursive: true });
writeFileSync(ddlPath, sql);
mkdirSync(target, { recursive: true });
const record = { schema_version: 1, status: 'APPROVED', user_decisions: ['D-003', 'D-004', 'D-005'], adopted_at: new Date().toISOString(), annotation_changes_only: true, files: entries, migration: { path: 'backend/app/infrastructure/migrations/001_initial.sql', sha256: sha(sql), proposal_sha256: sha(sqlOriginal) }, still_unconfirmed: ['Provider/model/version', 'tokenizer compatibility proof', 'real effect evaluation samples/thresholds and paid-call budget'] };
writeFileSync(resolve(target, 'manifest.json'), JSON.stringify({ schema_version: 1, status: 'APPROVED', files: entries }, null, 2) + '\n');
writeFileSync(adoptionPath, JSON.stringify(record, null, 2) + '\n');
console.log(JSON.stringify({ adopted: true, resources: entries.length, ddl: ddlPath, evidence: adoptionPath }));
