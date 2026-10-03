import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { inspectSource } from './spec-audit.mjs';

const root = resolve(import.meta.dirname, '..');
const metadata = JSON.parse(readFileSync(resolve(root, 'docs/sources/manifest.json'), 'utf8')).find(source => source.key === 'backend');
const source = inspectSource(metadata);
const names = { Requirement: 'requirements', RequirementDocument: 'requirement_documents', Revision: 'revisions', ConversationMessage: 'conversation_messages', GuideRun: 'guide_runs', LLMUse: 'llm_uses', SuggestionBatch: 'suggestion_batches', Suggestion: 'suggestions', Comment: 'comments' };
const entities = {};
let current, inFields = false;
for (let index = 0; index < 834; index++) {
  const line = source.lines[index];
  const name = line.match(/^\*\*([A-Za-z]+)\*\*$/)?.[1];
  if (names[name]) { current = name; inFields = false; entities[name] = []; }
  if (current && line.startsWith('|字段路径|逻辑类型或定义引用|')) { inFields = true; continue; }
  if (!inFields) continue;
  if (line.startsWith('|---')) continue;
  if (!line.startsWith('|')) { inFields = false; continue; }
  const cells = line.split('|').slice(1, -1);
  if (cells.length !== 6 || !/^[a-z_]+$/.test(cells[0])) throw new Error(`Unexpected persistent field row at ${index + 1}`);
  entities[current].push({ name: cells[0], logical_type: cells[1], nullable: cells[3] === '是', source_line: index + 1, immutable: cells[5].startsWith('不可修改') });
}
if (Object.keys(entities).length !== 9 || Object.values(entities).some(fields => !fields.length || fields[0].name !== 'id')) throw new Error('All nine complete entity field tables are required');
const path = resolve(root, 'docs/proposals/storage-v1.sql');
if (existsSync(path)) throw new Error('Storage draft already exists; edit explicitly instead of overwriting review');
const sql = ['-- UNAPPROVED PROPOSAL. Never apply this file to a production database before confirmation.', '-- SQLite 3.45.3; transaction/PRAGMA/ownership policy is in 公共决策稿-v1.md.', '-- Schema version and hash are written by the approved initializer, not hidden defaults.', ''];
const max = '9007199254740991';
const enumCheck = (column, values) => `CHECK (${column} IN (${values.map(value => `'${value}'`).join(', ')}))`;
const extra = {
  requirements: [enumCheck('requirement_type', ['NEW','CHANGE']), enumCheck('initialization_mode', ['IDEATION','DESIGN']), enumCheck('status', ['INITIALIZING','ACTIVE','COMPLETED']), enumCheck('document_work_state', ['IDLE','MANUAL_EDITING','GUIDE_ACTIVE','SUGGESTION_REVIEWING']), "CHECK (length(requirement_no)=9 AND requirement_no GLOB 'REQ[0-9][0-9][0-9][0-9][0-9][0-9]')", "CHECK (length(title) BETWEEN 1 AND 20 AND instr(title, char(10))=0)", "CHECK ((status='COMPLETED' AND completed_at IS NOT NULL) OR (status<>'COMPLETED' AND completed_at IS NULL))", "CHECK ((document_work_state='IDLE' AND active_operation_type IS NULL AND active_operation_id IS NULL AND state_started_at IS NULL) OR (document_work_state<>'IDLE' AND active_operation_type IS NOT NULL AND active_operation_id IS NOT NULL AND state_started_at IS NOT NULL AND ((document_work_state='MANUAL_EDITING' AND active_operation_type='MANUAL_DRAFT') OR (document_work_state='GUIDE_ACTIVE' AND active_operation_type='GUIDE_RUN') OR (document_work_state='SUGGESTION_REVIEWING' AND active_operation_type='SUGGESTION_BATCH'))))", 'UNIQUE (requirement_no)'],
  requirement_documents: [enumCheck('document_type', ['CURRENT','MANUAL_DRAFT']), 'UNIQUE (requirement_id, document_type)'],
  revisions: [enumCheck('revision_type', ['BASELINE','MANUAL']), "CHECK ((revision_type='BASELINE' AND version_no=1) OR (revision_type='MANUAL' AND version_no>1))", 'UNIQUE (requirement_id, version_no)'],
  conversation_messages: [enumCheck('role', ['USER','ASSISTANT']), enumCheck('message_type', ['TEXT','INTERACTION_CARDS','CARD_RESPONSE']), "CHECK ((role='USER' AND idempotency_key IS NOT NULL) OR (role='ASSISTANT' AND idempotency_key IS NULL))", "CHECK ((message_type='TEXT' AND structured_content_json IS NULL AND reply_to_message_id IS NULL) OR (message_type='INTERACTION_CARDS' AND role='ASSISTANT' AND structured_content_json IS NOT NULL AND reply_to_message_id IS NULL) OR (message_type='CARD_RESPONSE' AND role='USER' AND structured_content_json IS NOT NULL AND reply_to_message_id IS NOT NULL))", 'UNIQUE (requirement_id, sequence_no)', 'FOREIGN KEY (guide_run_id) REFERENCES guide_runs(id) DEFERRABLE INITIALLY DEFERRED', 'FOREIGN KEY (reply_to_message_id) REFERENCES conversation_messages(id)'],
  guide_runs: [enumCheck('action_type', ['INITIALIZE','ASK','REVIEW','MODIFY']), enumCheck('source_type', ['USER_INSTRUCTION','REVIEW_RESULT','COMMENT']), enumCheck('scope_type', ['DOCUMENT','SECTION','BLOCK','SELECTION']), enumCheck('status', ['RUNNING','WAITING_USER','COMPLETED','FAILED','CANCELLED']), enumCheck('current_step', ['PREPARING','CALLING_MODEL','VALIDATING','PERSISTING','WAITING_USER','FINISHED']), "CHECK ((action_type='INITIALIZE' AND mode_snapshot IS NOT NULL AND mode_snapshot IN ('IDEATION','DESIGN')) OR (action_type<>'INITIALIZE' AND mode_snapshot IS NULL))", "CHECK ((status IN ('COMPLETED','FAILED','CANCELLED') AND ended_at IS NOT NULL) OR (status IN ('RUNNING','WAITING_USER') AND ended_at IS NULL))", "CHECK (status<>'FAILED' OR (error_code IS NOT NULL AND error_message IS NOT NULL))", "CHECK (status<>'CANCELLED' OR (cancel_reason IS NOT NULL AND final_result_json IS NULL))", 'CHECK (retry_of_guide_run_id IS NULL OR retry_of_guide_run_id<>id)', 'FOREIGN KEY (retry_of_guide_run_id) REFERENCES guide_runs(id)'],
  llm_uses: ['CHECK (attempt_no BETWEEN 1 AND 3)', "CHECK ((validation_status='SUCCEEDED' AND trusted_output_json IS NOT NULL) OR (validation_status<>'SUCCEEDED' AND trusted_output_json IS NULL))", 'UNIQUE (guide_run_id, call_no, attempt_no)', 'FOREIGN KEY (guide_run_id) REFERENCES guide_runs(id)', "CHECK (provider_request_id IS NULL OR length(provider_request_id)<=1024)", 'CHECK ((cost IS NULL AND cost_currency IS NULL) OR (cost IS NOT NULL AND cost_currency IS NOT NULL))'],
  suggestion_batches: [enumCheck('status', ['PENDING','COMPLETED','DISCARDED']), "CHECK ((status='PENDING' AND completion_result IS NULL AND completed_at IS NULL AND applied_content_version IS NULL) OR (status='DISCARDED' AND completion_result IS NULL AND completed_at IS NOT NULL AND applied_content_version IS NULL) OR (status='COMPLETED' AND completion_result IS NOT NULL AND completed_at IS NOT NULL AND ((completion_result='CHANGES_APPLIED' AND applied_content_version IS NOT NULL) OR (completion_result='NO_CHANGE' AND applied_content_version IS NULL))))", 'UNIQUE (guide_run_id)', 'FOREIGN KEY (guide_run_id) REFERENCES guide_runs(id)'],
  suggestions: [enumCheck('status', ['PENDING','ACCEPTED','REJECTED','EDITED']), enumCheck('validation_status', ['VALID','INVALID']), enumCheck('patch_operation', ['REPLACE_BLOCK','INSERT_BEFORE','INSERT_AFTER','DELETE_BLOCK','REPLACE_TABLE_ROW']), "CHECK ((status='EDITED' AND user_edited_content IS NOT NULL AND patch_operation<>'DELETE_BLOCK') OR (status<>'EDITED' AND user_edited_content IS NULL))", "CHECK ((status='PENDING' AND decided_at IS NULL) OR (status<>'PENDING' AND decided_at IS NOT NULL))", "CHECK ((patch_operation IN ('REPLACE_BLOCK','INSERT_BEFORE','INSERT_AFTER') AND proposed_markdown IS NOT NULL AND length(proposed_markdown)>0 AND selector_json IS NULL AND proposed_data_json IS NULL) OR (patch_operation='DELETE_BLOCK' AND proposed_markdown IS NULL AND selector_json IS NULL AND proposed_data_json IS NULL) OR (patch_operation='REPLACE_TABLE_ROW' AND proposed_markdown IS NULL AND selector_json IS NOT NULL AND proposed_data_json IS NOT NULL))", 'UNIQUE (batch_id, order_no)', 'FOREIGN KEY (batch_id) REFERENCES suggestion_batches(id)'],
  comments: [enumCheck('status', ['OPEN','RESOLVED']), enumCheck('anchor_status', ['ATTACHED','ORPHANED']), enumCheck('anchor_type', ['BLOCK','SELECTION']), "CHECK ((status='OPEN' AND resolved_at IS NULL) OR (status='RESOLVED' AND resolved_at IS NOT NULL))", 'CHECK (length(content) BETWEEN 1 AND 2000)'],
};
for (const [name, fields] of Object.entries(entities)) {
  const table = names[name];
  const columns = fields.map(field => {
    const type = field.name === 'provider_request_id' ? 'TEXT' : /^(?:ID|BlockId|PositiveInt|Int)$/.test(field.logical_type) ? 'INTEGER' : 'TEXT';
    const constraints = [];
    if (field.name === 'id') constraints.push('PRIMARY KEY');
    if (!field.nullable) constraints.push('NOT NULL');
    if (type === 'INTEGER') constraints.push(`CHECK (${field.name} BETWEEN ${['input_tokens','output_tokens','duration_ms'].includes(field.name) ? '0' : '1'} AND ${max})`);
    if (field.logical_type === 'UtcTime') constraints.push(`CHECK (length(${field.name})=24 AND ${field.name} GLOB '????-??-??T??:??:??.???Z')`);
    if (field.name.endsWith('_json')) constraints.push(`CHECK (json_valid(${field.name}) AND json_type(${field.name})='object'${field.nullable ? ` OR ${field.name} IS NULL` : ''})`);
    return `  -- BE L${field.source_line}: ${field.logical_type}; ${field.nullable ? 'nullable' : 'required'}\n  ${field.name} ${type} ${constraints.join(' ')}`.trimEnd();
  });
  if (table === 'llm_uses') columns.push('  -- Q-13 proposal: provider-reported decimal string and currency only; unknown stays NULL.\n  cost TEXT,\n  cost_currency TEXT');
  if (fields.some(field => field.name === 'requirement_id')) columns.push('  FOREIGN KEY (requirement_id) REFERENCES requirements(id)');
  columns.push(...extra[table].map(constraint => `  ${constraint}`));
  sql.push(`CREATE TABLE ${table} (\n${columns.join(',\n')}\n) STRICT;`, '');
  const immutable = fields.filter(field => field.immutable).map(field => field.name);
  if (table === 'conversation_messages' || table === 'revisions') {
    sql.push(`CREATE TRIGGER ${table}_immutable BEFORE UPDATE ON ${table}\nBEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;`, '');
  } else if (immutable.length) {
    sql.push(`CREATE TRIGGER ${table}_immutable_fields BEFORE UPDATE ON ${table}\nWHEN ${immutable.map(column => `NEW.${column} IS NOT OLD.${column}`).join(' OR ')}\nBEGIN SELECT RAISE(ABORT, 'IMMUTABLE_FIELD'); END;`, '');
  }
}
sql.push(`CREATE UNIQUE INDEX revisions_one_baseline ON revisions(requirement_id) WHERE revision_type='BASELINE';`, `CREATE UNIQUE INDEX messages_one_card_response ON conversation_messages(reply_to_message_id) WHERE message_type='CARD_RESPONSE';`, `CREATE INDEX requirements_recent ON requirements(updated_at DESC, id DESC);`, `CREATE INDEX comments_order ON comments(requirement_id, created_at, id) WHERE deleted_at IS NULL;`, `CREATE INDEX runs_order ON guide_runs(requirement_id, created_at DESC, id DESC);`, `CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL) STRICT;`, `CREATE TABLE sequences (entity_kind TEXT PRIMARY KEY NOT NULL, last_value INTEGER NOT NULL CHECK(last_value BETWEEN 0 AND ${max})) STRICT;`, `CREATE TABLE manual_draft_context (draft_id INTEGER PRIMARY KEY NOT NULL REFERENCES requirement_documents(id), current_document_id INTEGER NOT NULL REFERENCES requirement_documents(id), base_content_version INTEGER NOT NULL CHECK(base_content_version BETWEEN 1 AND ${max}), baseline_block_state_json TEXT NOT NULL CHECK(json_valid(baseline_block_state_json) AND json_type(baseline_block_state_json)='object'), operation_time TEXT NOT NULL) STRICT;`, `CREATE TABLE document_change_audits (id INTEGER PRIMARY KEY NOT NULL CHECK(id BETWEEN 1 AND ${max}), requirement_id INTEGER NOT NULL REFERENCES requirements(id), document_id INTEGER NOT NULL REFERENCES requirement_documents(id), source_type TEXT NOT NULL, source_id INTEGER NOT NULL, reason_code TEXT NOT NULL, before_content_version INTEGER NOT NULL, after_content_version INTEGER NOT NULL, created_at TEXT NOT NULL) STRICT;`, `CREATE TABLE idempotency_records (capability_id TEXT NOT NULL, target_identity TEXT NOT NULL, idempotency_key TEXT NOT NULL, business_input_json TEXT NOT NULL CHECK(json_valid(business_input_json) AND json_type(business_input_json)='object'), status TEXT NOT NULL CHECK(status IN ('PROCESSING','SUCCEEDED')), owner_epoch TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, success_result_json TEXT CHECK(success_result_json IS NULL OR (json_valid(success_result_json) AND json_type(success_result_json)='object')), http_status INTEGER, PRIMARY KEY(capability_id,target_identity,idempotency_key), CHECK((status='PROCESSING' AND success_result_json IS NULL AND http_status IS NULL) OR (status='SUCCEEDED' AND success_result_json IS NOT NULL AND http_status BETWEEN 200 AND 299))) STRICT;`, '');
mkdirSync(resolve(path, '..'), { recursive: true });
writeFileSync(path, sql.join('\n') + '\n');
writeFileSync(resolve(root, 'docs/proposals/storage-field-map.json'), JSON.stringify({ status: 'UNAPPROVED_PROPOSAL', source_sha256: source.hash, entities }, null, 2) + '\n');
console.log(JSON.stringify({ path, entities: Object.keys(entities).length, persistentFields: Object.values(entities).reduce((sum, fields) => sum + fields.length, 0), adopted: false }));
