import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const migration = 'backend/app/infrastructure/migrations/003_manual_edit_sources.sql';
const record = 'docs/manual-edit-source-adoption-v1.json';
if (existsSync(resolve(root, migration)) || existsSync(resolve(root, record))) throw new Error('Frozen adoption already exists; do not overwrite');
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const approved = ['docs/proposals/manual-edit-source-v1.md', 'docs/proposals/manual-edit-source-v1.sql'].map(path => ({ path, sha256: digest(readFileSync(resolve(root, path))) }));
const ddl = readFileSync(resolve(root, approved[1].path), 'utf8');
const guard = `-- D-008 approved 2026-10-03. Preserve legacy facts; never infer sessions.
CREATE TEMP TABLE manual_source_migration_check (valid INTEGER NOT NULL CHECK(valid=1));
INSERT INTO manual_source_migration_check SELECT CASE WHEN
  EXISTS (SELECT 1 FROM requirement_documents d, json_tree(d.block_state_json) j WHERE j.key IN ('created_source_type','last_modified_source_type') AND j.value='MANUAL_EDIT') OR
  EXISTS (SELECT 1 FROM revisions r, json_tree(r.block_state_snapshot_json) j WHERE j.key IN ('created_source_type','last_modified_source_type') AND j.value='MANUAL_EDIT') OR
  EXISTS (SELECT 1 FROM document_change_audits WHERE source_type='MANUAL_EDIT')
THEN 0 ELSE 1 END;
DROP TABLE manual_source_migration_check;

`;
const adopted = guard + ddl.replace('-- Proposal only; do not install before approval. Intended migration 003.', '-- Approved D-008 migration 003; immutable after adoption.');
writeFileSync(resolve(root, migration), adopted);
writeFileSync(resolve(root, record), JSON.stringify({ decision: 'D-008', user_confirmation: '确认按补充稿接入（推荐）', recorded_at: new Date().toISOString(), approved, migration: { path: migration, sha256: digest(Buffer.from(adopted)), changes: 'Approval annotation; SQL preflight implements the reviewed legacy-source refusal.' } }, null, 2) + '\n');
console.log(JSON.stringify({ adopted: migration, record }));
