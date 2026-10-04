import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const migration = 'backend/app/infrastructure/migrations/004_manual_identity_proofs.sql';
const record = 'docs/manual-identity-adoption-v1.json';
if ([migration, record].some(path => existsSync(resolve(root, path)))) throw new Error('Adoption already exists; preserve frozen bytes');
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const approved = ['docs/proposals/manual-identity-receipts-v1.md', 'docs/proposals/manual-identity-receipts-v1.sql'].map(path => ({ path, sha256: digest(readFileSync(resolve(root, path))) }));
const guard = `-- D-009 approved 2026-10-04. Reject unknowable legacy allocation facts.
CREATE TEMP TABLE manual_identity_migration_check (valid INTEGER NOT NULL CHECK(valid=1));
INSERT INTO manual_identity_migration_check SELECT CASE WHEN EXISTS (
  SELECT 1 FROM requirement_documents d LEFT JOIN manual_draft_context c ON c.draft_id=d.id
  WHERE d.document_type='MANUAL_DRAFT' AND (
    c.draft_id IS NULL OR
    json_extract(d.block_state_json,'$.schema_version') IS NOT 1 OR
    json_extract(c.baseline_block_state_json,'$.schema_version') IS NOT 1 OR
    json_type(d.block_state_json,'$.next_block_id') IS NOT 'integer' OR
    json_type(c.baseline_block_state_json,'$.next_block_id') IS NOT 'integer' OR
    json_extract(d.block_state_json,'$.next_block_id') IS NOT json_extract(c.baseline_block_state_json,'$.next_block_id') OR
    json_type(d.block_state_json,'$.blocks') IS NOT 'array' OR
    json_type(c.baseline_block_state_json,'$.blocks') IS NOT 'array' OR
    EXISTS (SELECT 1 FROM json_each(d.block_state_json,'$.blocks') b WHERE NOT EXISTS (
      SELECT 1 FROM json_each(c.baseline_block_state_json,'$.blocks') original WHERE
      json_extract(b.value,'$.block_id') IS json_extract(original.value,'$.block_id') AND
      json_type(b.value,'$.block_id')='integer' AND
      json_extract(b.value,'$.created_by_type') IS json_extract(original.value,'$.created_by_type') AND
      json_extract(b.value,'$.created_source_type') IS json_extract(original.value,'$.created_source_type') AND
      json_extract(b.value,'$.created_source_id') IS json_extract(original.value,'$.created_source_id') AND
      json_extract(b.value,'$.created_at') IS json_extract(original.value,'$.created_at')
    ))
  )
) THEN 0 ELSE 1 END;
DROP TABLE manual_identity_migration_check;

`;
const adopted = guard + readFileSync(resolve(root, approved[1].path), 'utf8').replace('-- Proposed internal proof tables only. Not an adopted migration; awaiting confirmation.', '-- Approved D-009 migration 004; preserve adopted bytes.');
writeFileSync(resolve(root, migration), adopted);
writeFileSync(resolve(root, record), JSON.stringify({ decision: 'D-009', user_confirmation: '确认补充稿，按方案接入（推荐）', recorded_at: new Date().toISOString(), approved, migration: { path: migration, sha256: digest(Buffer.from(adopted)), changes: 'Approval annotation and reviewed conservative legacy-draft preflight.' } }, null, 2) + '\n');
console.log(JSON.stringify({ migration, record }));
