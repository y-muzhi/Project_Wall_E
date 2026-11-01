-- V1.5 fresh database schema, design 1.0 / EFFECTIVE. No legacy migration.
-- Reuses the seven aggregates and existing transaction/idempotency/manual-proof tables.

CREATE TABLE requirements (
  id INTEGER PRIMARY KEY NOT NULL CHECK (id BETWEEN 1 AND 9007199254740991),
  requirement_no TEXT NOT NULL,
  requirement_type TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL,
  document_work_state TEXT NOT NULL,
  active_operation_type TEXT,
  active_operation_id INTEGER CHECK (active_operation_id BETWEEN 1 AND 9007199254740991),
  created_at TEXT NOT NULL CHECK (length(created_at)=24 AND created_at GLOB '????-??-??T??:??:??.???Z'),
  updated_at TEXT NOT NULL CHECK (length(updated_at)=24 AND updated_at GLOB '????-??-??T??:??:??.???Z'),
  completed_at TEXT CHECK (length(completed_at)=24 AND completed_at GLOB '????-??-??T??:??:??.???Z'),
  state_started_at TEXT CHECK (length(state_started_at)=24 AND state_started_at GLOB '????-??-??T??:??:??.???Z'),
  metadata_version INTEGER NOT NULL CHECK(metadata_version BETWEEN 1 AND 9007199254740991),
  initial_message_id INTEGER NOT NULL CHECK(initial_message_id BETWEEN 1 AND 9007199254740991),
  discussion_version INTEGER NOT NULL CHECK(discussion_version BETWEEN 1 AND 9007199254740991),
  discussion_state_json TEXT NOT NULL CHECK(json_valid(discussion_state_json) AND json_type(discussion_state_json)='object'),
  closed_at TEXT CHECK(length(closed_at)=24 AND closed_at GLOB '????-??-??T??:??:??.???Z'),
  CHECK (requirement_type IN ('NEW', 'CHANGE')),
  CHECK (status IN ('PLANNING', 'READY', 'IMPLEMENTING', 'COMPLETED', 'CLOSED')),
  CHECK (document_work_state IN ('IDLE', 'MANUAL_EDITING', 'GUIDE_ACTIVE', 'SUGGESTION_REVIEWING')),
  CHECK (length(requirement_no)=9 AND requirement_no GLOB 'REQ[0-9][0-9][0-9][0-9][0-9][0-9]'),
  CHECK (length(title) BETWEEN 1 AND 20 AND instr(title, char(10))=0),
  CHECK ((status='COMPLETED' AND completed_at IS NOT NULL) OR (status<>'COMPLETED' AND completed_at IS NULL)),
  CHECK ((document_work_state='IDLE' AND active_operation_type IS NULL AND active_operation_id IS NULL AND state_started_at IS NULL) OR (document_work_state<>'IDLE' AND active_operation_type IS NOT NULL AND active_operation_id IS NOT NULL AND state_started_at IS NOT NULL AND ((document_work_state='MANUAL_EDITING' AND active_operation_type='MANUAL_DRAFT') OR (document_work_state='GUIDE_ACTIVE' AND active_operation_type='GUIDE_RUN') OR (document_work_state='SUGGESTION_REVIEWING' AND active_operation_type='SUGGESTION_BATCH')))),
  CHECK ((status='CLOSED' AND closed_at IS NOT NULL) OR (status<>'CLOSED' AND closed_at IS NULL)),
  FOREIGN KEY(initial_message_id,id) REFERENCES conversation_messages(id,requirement_id) DEFERRABLE INITIALLY DEFERRED,
  UNIQUE (requirement_no)
) STRICT;

CREATE TRIGGER requirements_immutable_fields BEFORE UPDATE ON requirements
WHEN NEW.id IS NOT OLD.id OR NEW.requirement_no IS NOT OLD.requirement_no OR NEW.requirement_type IS NOT OLD.requirement_type OR NEW.initial_message_id IS NOT OLD.initial_message_id OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_FIELD'); END;

CREATE TABLE requirement_documents (
  id INTEGER PRIMARY KEY NOT NULL CHECK (id BETWEEN 1 AND 9007199254740991),
  requirement_id INTEGER NOT NULL CHECK (requirement_id BETWEEN 1 AND 9007199254740991),
  document_type TEXT NOT NULL,
  markdown_content TEXT NOT NULL,
  block_state_json TEXT NOT NULL CHECK (json_valid(block_state_json) AND json_type(block_state_json)='object'),
  content_version INTEGER NOT NULL CHECK (content_version BETWEEN 1 AND 9007199254740991),
  created_at TEXT NOT NULL CHECK (length(created_at)=24 AND created_at GLOB '????-??-??T??:??:??.???Z'),
  updated_at TEXT NOT NULL CHECK (length(updated_at)=24 AND updated_at GLOB '????-??-??T??:??:??.???Z'),
  name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 80),
  document_kind TEXT NOT NULL CHECK(document_kind IN ('REQUIREMENT_BRIEF','DESIGN','SPECIFICATION')),
  metadata_version INTEGER NOT NULL CHECK(metadata_version BETWEEN 1 AND 9007199254740991),
  archived_at TEXT CHECK(length(archived_at)=24 AND archived_at GLOB '????-??-??T??:??:??.???Z'),
  confirmed_revision_id INTEGER,
  target_document_id INTEGER,
  template_ref TEXT CHECK(template_ref IS NULL OR (json_valid(template_ref) AND json_type(template_ref)='object')),
  origin TEXT NOT NULL CHECK(json_valid(origin) AND json_type(origin)='object'),
  FOREIGN KEY (requirement_id) REFERENCES requirements(id),
  CHECK (document_type IN ('CURRENT', 'MANUAL_DRAFT')),
  CHECK((document_type='CURRENT' AND target_document_id IS NULL) OR (document_type='MANUAL_DRAFT' AND target_document_id IS NOT NULL AND archived_at IS NULL AND confirmed_revision_id IS NULL)),
  UNIQUE(id,requirement_id),
  FOREIGN KEY(target_document_id,requirement_id) REFERENCES requirement_documents(id,requirement_id),
  FOREIGN KEY(confirmed_revision_id,id) REFERENCES revisions(id,document_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TRIGGER requirement_documents_immutable_fields BEFORE UPDATE ON requirement_documents
WHEN NEW.id IS NOT OLD.id OR NEW.requirement_id IS NOT OLD.requirement_id OR NEW.document_type IS NOT OLD.document_type OR NEW.document_kind IS NOT OLD.document_kind OR NEW.target_document_id IS NOT OLD.target_document_id OR NEW.template_ref IS NOT OLD.template_ref OR NEW.origin IS NOT OLD.origin OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_FIELD'); END;

CREATE TABLE revisions (
  id INTEGER PRIMARY KEY NOT NULL CHECK (id BETWEEN 1 AND 9007199254740991),
  requirement_id INTEGER NOT NULL CHECK (requirement_id BETWEEN 1 AND 9007199254740991),
  version_no INTEGER NOT NULL CHECK (version_no BETWEEN 1 AND 9007199254740991),
  revision_type TEXT NOT NULL,
  markdown_snapshot TEXT NOT NULL,
  block_state_snapshot_json TEXT NOT NULL CHECK (json_valid(block_state_snapshot_json) AND json_type(block_state_snapshot_json)='object'),
  description TEXT,
  source_content_version INTEGER NOT NULL CHECK (source_content_version BETWEEN 1 AND 9007199254740991),
  created_at TEXT NOT NULL CHECK (length(created_at)=24 AND created_at GLOB '????-??-??T??:??:??.???Z'),
  document_id INTEGER NOT NULL,
  source_refs_json TEXT NOT NULL CHECK(json_valid(source_refs_json) AND json_type(source_refs_json)='array'),
  change_summary TEXT,
  FOREIGN KEY (requirement_id) REFERENCES requirements(id),
  CHECK (revision_type='CONTENT'),
  CHECK(version_no=source_content_version),
  FOREIGN KEY(document_id,requirement_id) REFERENCES requirement_documents(id,requirement_id),
  UNIQUE(id,document_id),
  UNIQUE(document_id,source_content_version)
) STRICT;

CREATE TRIGGER revisions_immutable BEFORE UPDATE ON revisions
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;

CREATE TABLE conversation_messages (
  id INTEGER PRIMARY KEY NOT NULL CHECK (id BETWEEN 1 AND 9007199254740991),
  requirement_id INTEGER NOT NULL CHECK (requirement_id BETWEEN 1 AND 9007199254740991),
  guide_run_id INTEGER CHECK (guide_run_id BETWEEN 1 AND 9007199254740991),
  sequence_no INTEGER NOT NULL CHECK (sequence_no BETWEEN 1 AND 9007199254740991),
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  message_type TEXT NOT NULL,
  structured_content_json TEXT CHECK (json_valid(structured_content_json) AND json_type(structured_content_json)='object' OR structured_content_json IS NULL),
  reply_to_message_id INTEGER CHECK (reply_to_message_id BETWEEN 1 AND 9007199254740991),
  idempotency_key TEXT,
  created_at TEXT NOT NULL CHECK (length(created_at)=24 AND created_at GLOB '????-??-??T??:??:??.???Z'),
  phase_ref TEXT,
  topic_refs TEXT NOT NULL CHECK(json_valid(topic_refs) AND json_type(topic_refs)='array'),
  document_ids TEXT NOT NULL CHECK(json_valid(document_ids) AND json_type(document_ids)='array'),
  UNIQUE(id,requirement_id),
  FOREIGN KEY (requirement_id) REFERENCES requirements(id),
  CHECK (role IN ('USER', 'ASSISTANT')),
  CHECK (message_type IN ('TEXT', 'INTERACTION_CARDS', 'CARD_RESPONSE')),
  CHECK ((role='USER' AND idempotency_key IS NOT NULL) OR (role='ASSISTANT' AND idempotency_key IS NULL)),
  CHECK ((message_type='TEXT' AND structured_content_json IS NULL AND reply_to_message_id IS NULL) OR (message_type='INTERACTION_CARDS' AND role='ASSISTANT' AND structured_content_json IS NOT NULL AND reply_to_message_id IS NULL) OR (message_type='CARD_RESPONSE' AND role='USER' AND structured_content_json IS NOT NULL AND reply_to_message_id IS NOT NULL)),
  UNIQUE (requirement_id, sequence_no),
  FOREIGN KEY (guide_run_id) REFERENCES guide_runs(id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (reply_to_message_id) REFERENCES conversation_messages(id)
) STRICT;

CREATE TRIGGER conversation_messages_immutable BEFORE UPDATE ON conversation_messages
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;

CREATE TABLE guide_runs (
  id INTEGER PRIMARY KEY NOT NULL CHECK (id BETWEEN 1 AND 9007199254740991),
  requirement_id INTEGER NOT NULL CHECK (requirement_id BETWEEN 1 AND 9007199254740991),
  idempotency_key TEXT NOT NULL,
  trigger_message_id INTEGER CHECK (trigger_message_id BETWEEN 1 AND 9007199254740991),
  trigger_type TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_id INTEGER CHECK (source_id BETWEEN 1 AND 9007199254740991),
  function_type TEXT NOT NULL,
  context_template_key TEXT NOT NULL,
  context_template_version TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  action_type TEXT NOT NULL,
  mode_snapshot TEXT,
  instruction_summary TEXT NOT NULL,
  scope_type TEXT,
  scope_ref_json TEXT CHECK (json_valid(scope_ref_json) AND json_type(scope_ref_json)='object' OR scope_ref_json IS NULL),
  read_scope_manifest_json TEXT NOT NULL CHECK (json_valid(read_scope_manifest_json) AND json_type(read_scope_manifest_json)='object'),
  allowed_targets_json TEXT NOT NULL CHECK (json_valid(allowed_targets_json) AND json_type(allowed_targets_json)='object'),
  status TEXT NOT NULL,
  current_step TEXT NOT NULL,
  final_result_json TEXT CHECK (json_valid(final_result_json) AND json_type(final_result_json)='object' OR final_result_json IS NULL),
  created_at TEXT NOT NULL CHECK (length(created_at)=24 AND created_at GLOB '????-??-??T??:??:??.???Z'),
  started_at TEXT CHECK (length(started_at)=24 AND started_at GLOB '????-??-??T??:??:??.???Z'),
  waiting_user_at TEXT CHECK (length(waiting_user_at)=24 AND waiting_user_at GLOB '????-??-??T??:??:??.???Z'),
  ended_at TEXT CHECK (length(ended_at)=24 AND ended_at GLOB '????-??-??T??:??:??.???Z'),
  updated_at TEXT NOT NULL CHECK (length(updated_at)=24 AND updated_at GLOB '????-??-??T??:??:??.???Z'),
  error_code TEXT,
  error_message TEXT,
  cancel_reason TEXT,
  retry_of_guide_run_id INTEGER CHECK (retry_of_guide_run_id BETWEEN 1 AND 9007199254740991),
  operation TEXT NOT NULL CHECK(operation IN ('DISCUSS','GENERATE','REVISE','PROPOSE_CHANGES','COMPARE','REVIEW')),
  target_document_id INTEGER,
  parent_guide_run_id INTEGER,
  discussion_version_snapshot INTEGER NOT NULL CHECK(discussion_version_snapshot BETWEEN 1 AND 9007199254740991),
  execution_basis_json TEXT NOT NULL CHECK(json_valid(execution_basis_json) AND json_type(execution_basis_json)='object'),
  FOREIGN KEY (requirement_id) REFERENCES requirements(id),
  CHECK (action_type IN ('ASK', 'GENERATE', 'REVIEW', 'MODIFY')),
  CHECK (source_type IN ('USER_INSTRUCTION', 'REVIEW_RESULT', 'COMMENT')),
  CHECK (scope_type IN ('DOCUMENT', 'SECTION', 'BLOCK', 'SELECTION')),
  CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')),
  CHECK (current_step IN ('PREPARING', 'CALLING_MODEL', 'VALIDATING', 'PERSISTING', 'FINISHED')),
  CHECK(mode_snapshot IS NULL AND waiting_user_at IS NULL),
  CHECK ((status IN ('COMPLETED','FAILED','CANCELLED') AND ended_at IS NOT NULL) OR (status='RUNNING' AND ended_at IS NULL)),
  CHECK (status<>'FAILED' OR (error_code IS NOT NULL AND error_message IS NOT NULL)),
  CHECK (status<>'CANCELLED' OR (cancel_reason IS NOT NULL AND final_result_json IS NULL)),
  CHECK (retry_of_guide_run_id IS NULL OR retry_of_guide_run_id<>id),
  CHECK(parent_guide_run_id IS NULL OR parent_guide_run_id<>id),
  UNIQUE(id,requirement_id),
  FOREIGN KEY(target_document_id,requirement_id) REFERENCES requirement_documents(id,requirement_id),
  FOREIGN KEY(parent_guide_run_id,requirement_id) REFERENCES guide_runs(id,requirement_id),
  FOREIGN KEY(retry_of_guide_run_id,requirement_id) REFERENCES guide_runs(id,requirement_id)
) STRICT;

CREATE TRIGGER guide_runs_immutable_fields BEFORE UPDATE ON guide_runs
WHEN NEW.id IS NOT OLD.id OR NEW.requirement_id IS NOT OLD.requirement_id OR NEW.idempotency_key IS NOT OLD.idempotency_key OR NEW.function_type IS NOT OLD.function_type OR NEW.context_template_key IS NOT OLD.context_template_key OR NEW.context_template_version IS NOT OLD.context_template_version OR NEW.prompt_version IS NOT OLD.prompt_version OR NEW.action_type IS NOT OLD.action_type OR NEW.trigger_message_id IS NOT OLD.trigger_message_id OR NEW.trigger_type IS NOT OLD.trigger_type OR NEW.source_type IS NOT OLD.source_type OR NEW.source_id IS NOT OLD.source_id OR NEW.instruction_summary IS NOT OLD.instruction_summary OR NEW.scope_type IS NOT OLD.scope_type OR NEW.scope_ref_json IS NOT OLD.scope_ref_json OR NEW.read_scope_manifest_json IS NOT OLD.read_scope_manifest_json OR NEW.allowed_targets_json IS NOT OLD.allowed_targets_json OR NEW.mode_snapshot IS NOT OLD.mode_snapshot OR NEW.operation IS NOT OLD.operation OR NEW.target_document_id IS NOT OLD.target_document_id OR NEW.parent_guide_run_id IS NOT OLD.parent_guide_run_id OR NEW.discussion_version_snapshot IS NOT OLD.discussion_version_snapshot OR NEW.execution_basis_json IS NOT OLD.execution_basis_json OR NEW.created_at IS NOT OLD.created_at OR NEW.retry_of_guide_run_id IS NOT OLD.retry_of_guide_run_id
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_FIELD'); END;

CREATE TABLE llm_uses (
  id INTEGER PRIMARY KEY NOT NULL CHECK (id BETWEEN 1 AND 9007199254740991),
  guide_run_id INTEGER NOT NULL CHECK (guide_run_id BETWEEN 1 AND 9007199254740991),
  call_no INTEGER NOT NULL CHECK (call_no BETWEEN 1 AND 9007199254740991),
  attempt_no INTEGER NOT NULL CHECK (attempt_no BETWEEN 1 AND 9007199254740991),
  provider TEXT NOT NULL,
  model_name TEXT NOT NULL,
  model_version TEXT,
  function_type TEXT NOT NULL,
  prompt_config TEXT NOT NULL,
  request_snapshot_json TEXT NOT NULL CHECK (json_valid(request_snapshot_json) AND json_type(request_snapshot_json)='object'),
  parsed_output_json TEXT CHECK (json_valid(parsed_output_json) AND json_type(parsed_output_json)='object' OR parsed_output_json IS NULL),
  trusted_output_json TEXT CHECK (json_valid(trusted_output_json) AND json_type(trusted_output_json)='object' OR trusted_output_json IS NULL),
  input_summary TEXT NOT NULL,
  context_manifest_json TEXT NOT NULL CHECK (json_valid(context_manifest_json) AND json_type(context_manifest_json)='object'),
  raw_response_json TEXT CHECK (json_valid(raw_response_json) AND json_type(raw_response_json)='object' OR raw_response_json IS NULL),
  finish_reason TEXT,
  parse_status TEXT NOT NULL,
  parse_error TEXT,
  validation_status TEXT NOT NULL,
  validation_error TEXT,
  call_status TEXT NOT NULL,
  input_tokens INTEGER CHECK (input_tokens BETWEEN 0 AND 9007199254740991),
  output_tokens INTEGER CHECK (output_tokens BETWEEN 0 AND 9007199254740991),
  cache_info_json TEXT CHECK (json_valid(cache_info_json) AND json_type(cache_info_json)='object' OR cache_info_json IS NULL),
  provider_request_id TEXT,
  started_at TEXT NOT NULL CHECK (length(started_at)=24 AND started_at GLOB '????-??-??T??:??:??.???Z'),
  ended_at TEXT CHECK (length(ended_at)=24 AND ended_at GLOB '????-??-??T??:??:??.???Z'),
  duration_ms INTEGER CHECK (duration_ms BETWEEN 0 AND 9007199254740991),
  error_code TEXT,
  error_message TEXT,
  cost TEXT,
  cost_currency TEXT,
  CHECK(call_no=1 AND attempt_no=1),
  CHECK ((validation_status='SUCCEEDED' AND trusted_output_json IS NOT NULL) OR (validation_status<>'SUCCEEDED' AND trusted_output_json IS NULL)),
  UNIQUE (guide_run_id, call_no, attempt_no),
  FOREIGN KEY (guide_run_id) REFERENCES guide_runs(id),
  CHECK (provider_request_id IS NULL OR length(provider_request_id)<=1024),
  CHECK ((cost IS NULL AND cost_currency IS NULL) OR (cost IS NOT NULL AND cost_currency IS NOT NULL))
) STRICT;

CREATE TRIGGER llm_uses_immutable_fields BEFORE UPDATE ON llm_uses
WHEN NEW.id IS NOT OLD.id OR NEW.guide_run_id IS NOT OLD.guide_run_id OR NEW.function_type IS NOT OLD.function_type
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_FIELD'); END;

CREATE TABLE suggestion_batches (
  id INTEGER PRIMARY KEY NOT NULL CHECK (id BETWEEN 1 AND 9007199254740991),
  requirement_id INTEGER NOT NULL CHECK (requirement_id BETWEEN 1 AND 9007199254740991),
  guide_run_id INTEGER NOT NULL CHECK (guide_run_id BETWEEN 1 AND 9007199254740991),
  source_type TEXT NOT NULL,
  source_id INTEGER CHECK (source_id BETWEEN 1 AND 9007199254740991),
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  status TEXT NOT NULL,
  completion_result TEXT,
  error_message TEXT,
  base_content_version INTEGER NOT NULL CHECK (base_content_version BETWEEN 1 AND 9007199254740991),
  applied_content_version INTEGER CHECK (applied_content_version BETWEEN 1 AND 9007199254740991),
  created_at TEXT NOT NULL CHECK (length(created_at)=24 AND created_at GLOB '????-??-??T??:??:??.???Z'),
  completed_at TEXT CHECK (length(completed_at)=24 AND completed_at GLOB '????-??-??T??:??:??.???Z'),
  updated_at TEXT NOT NULL CHECK (length(updated_at)=24 AND updated_at GLOB '????-??-??T??:??:??.???Z'),
  target_document_id INTEGER NOT NULL,
  source_refs_json TEXT NOT NULL CHECK(json_valid(source_refs_json) AND json_type(source_refs_json)='array'),
  source_heads_json TEXT NOT NULL CHECK(json_valid(source_heads_json) AND json_type(source_heads_json)='array'),
  FOREIGN KEY (requirement_id) REFERENCES requirements(id),
  CHECK (status IN ('PENDING', 'COMPLETED', 'DISCARDED')),
  CHECK ((status='PENDING' AND completion_result IS NULL AND completed_at IS NULL AND applied_content_version IS NULL) OR (status='DISCARDED' AND completion_result IS NULL AND completed_at IS NOT NULL AND applied_content_version IS NULL) OR (status='COMPLETED' AND completion_result IS NOT NULL AND completed_at IS NOT NULL AND ((completion_result='CHANGES_APPLIED' AND applied_content_version IS NOT NULL) OR (completion_result='NO_CHANGE' AND applied_content_version IS NULL)))),
  UNIQUE (guide_run_id),
  FOREIGN KEY(target_document_id,requirement_id) REFERENCES requirement_documents(id,requirement_id),
  FOREIGN KEY (guide_run_id,requirement_id) REFERENCES guide_runs(id,requirement_id)
) STRICT;

CREATE TRIGGER suggestion_batches_immutable_fields BEFORE UPDATE ON suggestion_batches
WHEN NEW.id IS NOT OLD.id OR NEW.requirement_id IS NOT OLD.requirement_id OR NEW.guide_run_id IS NOT OLD.guide_run_id OR NEW.target_document_id IS NOT OLD.target_document_id OR NEW.source_refs_json IS NOT OLD.source_refs_json OR NEW.source_heads_json IS NOT OLD.source_heads_json OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_FIELD'); END;

CREATE TABLE suggestions (
  id INTEGER PRIMARY KEY NOT NULL CHECK (id BETWEEN 1 AND 9007199254740991),
  batch_id INTEGER NOT NULL CHECK (batch_id BETWEEN 1 AND 9007199254740991),
  order_no INTEGER NOT NULL CHECK (order_no BETWEEN 1 AND 9007199254740991),
  title TEXT NOT NULL,
  explanation TEXT NOT NULL,
  impact TEXT,
  patch_operation TEXT NOT NULL,
  target_ref_json TEXT NOT NULL CHECK (json_valid(target_ref_json) AND json_type(target_ref_json)='object'),
  selector_json TEXT CHECK (json_valid(selector_json) AND json_type(selector_json)='object' OR selector_json IS NULL),
  original_content TEXT NOT NULL,
  proposed_markdown TEXT,
  proposed_data_json TEXT CHECK (json_valid(proposed_data_json) AND json_type(proposed_data_json)='object' OR proposed_data_json IS NULL),
  user_edited_content TEXT,
  status TEXT NOT NULL,
  validation_status TEXT NOT NULL,
  validation_error TEXT,
  created_at TEXT NOT NULL CHECK (length(created_at)=24 AND created_at GLOB '????-??-??T??:??:??.???Z'),
  decided_at TEXT CHECK (length(decided_at)=24 AND decided_at GLOB '????-??-??T??:??:??.???Z'),
  updated_at TEXT NOT NULL CHECK (length(updated_at)=24 AND updated_at GLOB '????-??-??T??:??:??.???Z'),
  CHECK (status IN ('PENDING', 'ACCEPTED', 'REJECTED', 'EDITED')),
  CHECK (validation_status IN ('VALID', 'INVALID')),
  CHECK (patch_operation IN ('REPLACE_BLOCK', 'INSERT_BEFORE', 'INSERT_AFTER', 'DELETE_BLOCK', 'REPLACE_TABLE_ROW')),
  CHECK ((status='EDITED' AND user_edited_content IS NOT NULL AND patch_operation<>'DELETE_BLOCK') OR (status<>'EDITED' AND user_edited_content IS NULL)),
  CHECK ((status='PENDING' AND decided_at IS NULL) OR (status<>'PENDING' AND decided_at IS NOT NULL)),
  CHECK ((patch_operation IN ('REPLACE_BLOCK','INSERT_BEFORE','INSERT_AFTER') AND proposed_markdown IS NOT NULL AND length(proposed_markdown)>0 AND selector_json IS NULL AND proposed_data_json IS NULL) OR (patch_operation='DELETE_BLOCK' AND proposed_markdown IS NULL AND selector_json IS NULL AND proposed_data_json IS NULL) OR (patch_operation='REPLACE_TABLE_ROW' AND proposed_markdown IS NULL AND selector_json IS NOT NULL AND proposed_data_json IS NOT NULL)),
  UNIQUE (batch_id, order_no),
  FOREIGN KEY (batch_id) REFERENCES suggestion_batches(id)
) STRICT;

CREATE TRIGGER suggestions_immutable_fields BEFORE UPDATE ON suggestions
WHEN NEW.id IS NOT OLD.id OR NEW.batch_id IS NOT OLD.batch_id OR NEW.order_no IS NOT OLD.order_no OR NEW.patch_operation IS NOT OLD.patch_operation OR NEW.target_ref_json IS NOT OLD.target_ref_json OR NEW.selector_json IS NOT OLD.selector_json OR NEW.original_content IS NOT OLD.original_content OR NEW.proposed_markdown IS NOT OLD.proposed_markdown OR NEW.proposed_data_json IS NOT OLD.proposed_data_json OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_FIELD'); END;

CREATE TABLE comments (
  id INTEGER PRIMARY KEY NOT NULL CHECK (id BETWEEN 1 AND 9007199254740991),
  requirement_id INTEGER NOT NULL CHECK (requirement_id BETWEEN 1 AND 9007199254740991),
  content TEXT NOT NULL,
  anchor_type TEXT NOT NULL,
  block_id INTEGER NOT NULL CHECK (block_id BETWEEN 1 AND 9007199254740991),
  anchor_ref_json TEXT NOT NULL CHECK (json_valid(anchor_ref_json) AND json_type(anchor_ref_json)='object'),
  anchor_status TEXT NOT NULL,
  status TEXT NOT NULL,
  resolved_at TEXT CHECK (length(resolved_at)=24 AND resolved_at GLOB '????-??-??T??:??:??.???Z'),
  deleted_at TEXT CHECK (length(deleted_at)=24 AND deleted_at GLOB '????-??-??T??:??:??.???Z'),
  created_at TEXT NOT NULL CHECK (length(created_at)=24 AND created_at GLOB '????-??-??T??:??:??.???Z'),
  updated_at TEXT NOT NULL CHECK (length(updated_at)=24 AND updated_at GLOB '????-??-??T??:??:??.???Z'),
  document_id INTEGER NOT NULL,
  FOREIGN KEY(document_id,requirement_id) REFERENCES requirement_documents(id,requirement_id),
  FOREIGN KEY (requirement_id) REFERENCES requirements(id),
  CHECK (status IN ('OPEN', 'RESOLVED')),
  CHECK (anchor_status IN ('ATTACHED', 'ORPHANED')),
  CHECK (anchor_type IN ('BLOCK', 'SELECTION')),
  CHECK ((status='OPEN' AND resolved_at IS NULL) OR (status='RESOLVED' AND resolved_at IS NOT NULL)),
  CHECK (length(content) BETWEEN 1 AND 2000)
) STRICT;

CREATE TRIGGER comments_immutable_fields BEFORE UPDATE ON comments
WHEN NEW.id IS NOT OLD.id OR NEW.requirement_id IS NOT OLD.requirement_id OR NEW.anchor_type IS NOT OLD.anchor_type OR NEW.block_id IS NOT OLD.block_id OR NEW.anchor_ref_json IS NOT OLD.anchor_ref_json OR NEW.document_id IS NOT OLD.document_id OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_FIELD'); END;

CREATE UNIQUE INDEX messages_one_card_response ON conversation_messages(reply_to_message_id) WHERE message_type='CARD_RESPONSE';

CREATE INDEX requirements_recent ON requirements(updated_at DESC, id DESC);

CREATE INDEX comments_order ON comments(requirement_id,document_id, created_at, id) WHERE deleted_at IS NULL;

CREATE INDEX runs_order ON guide_runs(requirement_id, created_at DESC, id DESC);

CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY NOT NULL,
  checksum TEXT NOT NULL,
  applied_at TEXT NOT NULL
) STRICT;

CREATE TABLE sequences (
  entity_kind TEXT PRIMARY KEY NOT NULL,
  last_value INTEGER NOT NULL CHECK(last_value BETWEEN 0 AND 9007199254740991)
) STRICT;

CREATE TABLE manual_draft_context (
  draft_id INTEGER PRIMARY KEY NOT NULL REFERENCES requirement_documents(id),
  current_document_id INTEGER NOT NULL REFERENCES requirement_documents(id),
  base_content_version INTEGER NOT NULL CHECK(base_content_version BETWEEN 1 AND 9007199254740991),
  baseline_block_state_json TEXT NOT NULL CHECK(json_valid(baseline_block_state_json) AND json_type(baseline_block_state_json)='object'),
  operation_time TEXT NOT NULL,
  source_refs_json TEXT NOT NULL CHECK(json_valid(source_refs_json) AND json_type(source_refs_json)='array')
) STRICT;

CREATE TABLE document_change_audits (
  id INTEGER PRIMARY KEY NOT NULL CHECK(id BETWEEN 1 AND 9007199254740991),
  requirement_id INTEGER NOT NULL REFERENCES requirements(id),
  document_id INTEGER,
  source_type TEXT NOT NULL,
  source_id INTEGER NOT NULL CHECK(source_id BETWEEN 1 AND 9007199254740991),
  reason_code TEXT NOT NULL,
  before_content_version INTEGER CHECK(before_content_version BETWEEN 1 AND 9007199254740991),
  after_content_version INTEGER CHECK(after_content_version BETWEEN 1 AND 9007199254740991),
  created_at TEXT NOT NULL CHECK(length(created_at)=24 AND created_at GLOB '????-??-??T??:??:??.???Z'),
  event_type TEXT NOT NULL CHECK(event_type IN ('CONTENT_COMMITTED','DOCUMENT_CONFIRMED','DOCUMENT_RENAMED','DOCUMENT_ARCHIVED','DOCUMENT_RESTORED','REQUIREMENT_UPDATED','PHASE_CHANGED','DISCUSSION_UPDATED','VERSION_MARKED')),
  revision_id INTEGER,
  guide_run_id INTEGER,
  payload_json TEXT NOT NULL CHECK(json_valid(payload_json) AND json_type(payload_json)='object'),
  CHECK(event_type<>'CONTENT_COMMITTED' OR (document_id IS NOT NULL AND revision_id IS NOT NULL AND after_content_version IS NOT NULL AND (before_content_version IS NULL OR after_content_version=before_content_version+1))),
  CHECK(document_id IS NOT NULL OR (revision_id IS NULL AND before_content_version IS NULL AND after_content_version IS NULL)),
  FOREIGN KEY(document_id,requirement_id) REFERENCES requirement_documents(id,requirement_id),
  FOREIGN KEY(revision_id,document_id) REFERENCES revisions(id,document_id),
  FOREIGN KEY(guide_run_id,requirement_id) REFERENCES guide_runs(id,requirement_id)
) STRICT;

CREATE TABLE idempotency_records (
  capability_id TEXT NOT NULL,
  target_identity TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  business_input_json TEXT NOT NULL CHECK(json_valid(business_input_json) AND json_type(business_input_json)='object'),
  status TEXT NOT NULL CHECK(status IN ('PROCESSING','SUCCEEDED')),
  owner_epoch TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  success_result_json TEXT CHECK(success_result_json IS NULL OR (json_valid(success_result_json) AND json_type(success_result_json)='object')),
  http_status INTEGER,
  PRIMARY KEY(capability_id,target_identity,idempotency_key),
  CHECK((status='PROCESSING' AND success_result_json IS NULL AND http_status IS NULL) OR (status='SUCCEEDED' AND success_result_json IS NOT NULL AND http_status BETWEEN 200 AND 299))
) STRICT;

CREATE TRIGGER idempotency_success_status_insert BEFORE INSERT ON idempotency_records
WHEN NEW.status='SUCCEEDED' AND NEW.http_status IS NULL
BEGIN SELECT RAISE(ABORT, 'SUCCESS_HTTP_STATUS_REQUIRED'); END;

CREATE TRIGGER idempotency_success_status_update BEFORE UPDATE ON idempotency_records
WHEN NEW.status='SUCCEEDED' AND NEW.http_status IS NULL
BEGIN SELECT RAISE(ABORT, 'SUCCESS_HTTP_STATUS_REQUIRED'); END;

CREATE TRIGGER idempotency_success_immutable BEFORE UPDATE ON idempotency_records
WHEN OLD.status='SUCCEEDED'
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_SUCCESS'); END;

CREATE TRIGGER idempotency_success_retained BEFORE DELETE ON idempotency_records
WHEN OLD.status='SUCCEEDED'
BEGIN SELECT RAISE(ABORT, 'SUCCESS_MUST_BE_RETAINED'); END;

CREATE TRIGGER idempotency_identity_immutable BEFORE UPDATE ON idempotency_records
WHEN NEW.capability_id IS NOT OLD.capability_id OR NEW.target_identity IS NOT OLD.target_identity OR NEW.idempotency_key IS NOT OLD.idempotency_key OR NEW.business_input_json IS NOT OLD.business_input_json OR NEW.owner_epoch IS NOT OLD.owner_epoch OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_CLAIM_IDENTITY'); END;

CREATE TABLE manual_edit_sessions (
  draft_id INTEGER PRIMARY KEY NOT NULL CHECK(draft_id BETWEEN 1 AND 9007199254740991),
  requirement_id INTEGER NOT NULL REFERENCES requirements(id),
  current_document_id INTEGER NOT NULL REFERENCES requirement_documents(id),
  status TEXT NOT NULL CHECK(status IN ('EDITING', 'COMPLETED', 'CANCELLED')),
  started_at TEXT NOT NULL CHECK(length(started_at)=24 AND started_at GLOB '????-??-??T??:??:??.???Z'),
  closed_at TEXT CHECK(length(closed_at)=24 AND closed_at GLOB '????-??-??T??:??:??.???Z'),
  CHECK((status='EDITING' AND closed_at IS NULL) OR (status IN ('COMPLETED', 'CANCELLED') AND closed_at IS NOT NULL AND closed_at >= started_at))
) STRICT;

CREATE TRIGGER manual_edit_sessions_immutable_identity BEFORE UPDATE ON manual_edit_sessions
WHEN NEW.draft_id IS NOT OLD.draft_id OR NEW.requirement_id IS NOT OLD.requirement_id OR NEW.current_document_id IS NOT OLD.current_document_id OR NEW.started_at IS NOT OLD.started_at
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_FIELD'); END;

CREATE TRIGGER manual_edit_sessions_closed BEFORE UPDATE ON manual_edit_sessions
WHEN OLD.status <> 'EDITING'
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;

CREATE TRIGGER manual_edit_sessions_retained BEFORE DELETE ON manual_edit_sessions
BEGIN SELECT RAISE(ABORT, 'PERMANENT_SOURCE'); END;

CREATE TABLE manual_block_allocation_ranges (
  draft_id INTEGER NOT NULL REFERENCES manual_draft_context(draft_id),
  start_block_id INTEGER NOT NULL CHECK(start_block_id BETWEEN 1 AND 9007199254740990),
  end_block_id INTEGER NOT NULL CHECK(end_block_id BETWEEN 2 AND 9007199254740991 AND end_block_id > start_block_id),
  observed_at TEXT NOT NULL CHECK(length(observed_at)=24 AND observed_at GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY(draft_id,start_block_id)
) STRICT;

CREATE TRIGGER manual_block_ranges_nonoverlap BEFORE INSERT ON manual_block_allocation_ranges
WHEN EXISTS(SELECT 1 FROM manual_block_allocation_ranges r WHERE r.draft_id=NEW.draft_id AND r.start_block_id < NEW.end_block_id AND NEW.start_block_id < r.end_block_id)
BEGIN SELECT RAISE(ABORT,'OVERLAPPING_ALLOCATION'); END;

CREATE TRIGGER manual_block_ranges_immutable BEFORE UPDATE ON manual_block_allocation_ranges
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_ALLOCATION'); END;

CREATE TABLE manual_block_origins (
  draft_id INTEGER NOT NULL REFERENCES manual_draft_context(draft_id),
  block_id INTEGER NOT NULL CHECK(block_id BETWEEN 1 AND 9007199254740990),
  created_by_type TEXT NOT NULL CHECK(created_by_type='USER'),
  created_source_type TEXT NOT NULL CHECK(created_source_type='MANUAL_EDIT'),
  created_source_id INTEGER NOT NULL CHECK(created_source_id=draft_id),
  created_at TEXT NOT NULL CHECK(length(created_at)=24 AND created_at GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY(draft_id,block_id)
) STRICT;

CREATE TRIGGER manual_block_origins_allocation BEFORE INSERT ON manual_block_origins
WHEN NOT EXISTS(SELECT 1 FROM manual_block_allocation_ranges r WHERE r.draft_id=NEW.draft_id AND r.start_block_id <= NEW.block_id AND NEW.block_id < r.end_block_id AND r.observed_at=NEW.created_at)
BEGIN SELECT RAISE(ABORT,'UNPROVEN_BLOCK_ORIGIN'); END;

CREATE TRIGGER manual_block_origins_immutable BEFORE UPDATE ON manual_block_origins
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_BLOCK_ORIGIN'); END;

CREATE UNIQUE INDEX manual_draft_target ON requirement_documents(target_document_id) WHERE document_type='MANUAL_DRAFT';

CREATE UNIQUE INDEX manual_draft_requirement ON requirement_documents(requirement_id) WHERE document_type='MANUAL_DRAFT';

CREATE UNIQUE INDEX content_run_commit ON document_change_audits(guide_run_id,document_id,event_type) WHERE event_type='CONTENT_COMMITTED' AND guide_run_id IS NOT NULL;

CREATE INDEX documents_order ON requirement_documents(requirement_id,created_at,id) WHERE document_type='CURRENT';

CREATE INDEX revisions_order ON revisions(document_id,source_content_version DESC);

CREATE TRIGGER initial_message_is_user_text BEFORE INSERT ON conversation_messages
WHEN EXISTS(SELECT 1 FROM requirements WHERE initial_message_id=NEW.id AND (id<>NEW.requirement_id OR NEW.role<>'USER' OR NEW.message_type<>'TEXT' OR NEW.guide_run_id IS NOT NULL))
BEGIN SELECT RAISE(ABORT,'INVALID_INITIAL_MESSAGE'); END;

CREATE TRIGGER draft_target_is_current BEFORE INSERT ON requirement_documents
WHEN NEW.document_type='MANUAL_DRAFT' AND NOT EXISTS(SELECT 1 FROM requirement_documents WHERE id=NEW.target_document_id AND requirement_id=NEW.requirement_id AND document_type='CURRENT')
BEGIN SELECT RAISE(ABORT,'INVALID_DRAFT_TARGET'); END;

CREATE TRIGGER revisions_retained BEFORE DELETE ON revisions
BEGIN SELECT RAISE(ABORT,'PERMANENT_REVISION'); END;

CREATE TRIGGER messages_retained BEFORE DELETE ON conversation_messages
BEGIN SELECT RAISE(ABORT,'PERMANENT_MESSAGE'); END;

CREATE TRIGGER current_documents_retained BEFORE DELETE ON requirement_documents
WHEN OLD.document_type='CURRENT'
BEGIN SELECT RAISE(ABORT,'PERMANENT_DOCUMENT'); END;

CREATE TRIGGER document_events_immutable BEFORE UPDATE ON document_change_audits
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVENT'); END;

CREATE TRIGGER document_events_retained BEFORE DELETE ON document_change_audits
BEGIN SELECT RAISE(ABORT,'PERMANENT_EVENT'); END;
