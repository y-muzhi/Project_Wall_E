-- UNAPPROVED PROPOSAL. Never apply this file to a production database before confirmation.
-- SQLite 3.45.3; transaction/PRAGMA/ownership policy is in 公共决策稿-v1.md.
-- Schema version and hash are written by the approved initializer, not hidden defaults.

CREATE TABLE requirements (
  -- BE L205: ID; required
  id INTEGER PRIMARY KEY NOT NULL CHECK (id BETWEEN 1 AND 9007199254740991),
  -- BE L206: Text; required
  requirement_no TEXT NOT NULL,
  -- BE L207: NEW / CHANGE; required
  requirement_type TEXT NOT NULL,
  -- BE L208: IDEATION / DESIGN; required
  initialization_mode TEXT NOT NULL,
  -- BE L209: Text; required
  title TEXT NOT NULL,
  -- BE L210: Text; required
  template_key TEXT NOT NULL,
  -- BE L211: Text; required
  template_version TEXT NOT NULL,
  -- BE L212: Text; required
  status TEXT NOT NULL,
  -- BE L213: Text; required
  document_work_state TEXT NOT NULL,
  -- BE L214: Text; nullable
  active_operation_type TEXT,
  -- BE L215: ID; nullable
  active_operation_id INTEGER CHECK (active_operation_id BETWEEN 1 AND 9007199254740991),
  -- BE L216: UtcTime; required
  created_at TEXT NOT NULL CHECK (length(created_at)=24 AND created_at GLOB '????-??-??T??:??:??.???Z'),
  -- BE L217: UtcTime; required
  updated_at TEXT NOT NULL CHECK (length(updated_at)=24 AND updated_at GLOB '????-??-??T??:??:??.???Z'),
  -- BE L218: UtcTime; nullable
  completed_at TEXT CHECK (length(completed_at)=24 AND completed_at GLOB '????-??-??T??:??:??.???Z'),
  -- BE L219: UtcTime; nullable
  state_started_at TEXT CHECK (length(state_started_at)=24 AND state_started_at GLOB '????-??-??T??:??:??.???Z'),
  CHECK (requirement_type IN ('NEW', 'CHANGE')),
  CHECK (initialization_mode IN ('IDEATION', 'DESIGN')),
  CHECK (status IN ('INITIALIZING', 'ACTIVE', 'COMPLETED')),
  CHECK (document_work_state IN ('IDLE', 'MANUAL_EDITING', 'GUIDE_ACTIVE', 'SUGGESTION_REVIEWING')),
  CHECK (length(requirement_no)=9 AND requirement_no GLOB 'REQ[0-9][0-9][0-9][0-9][0-9][0-9]'),
  CHECK (length(title) BETWEEN 1 AND 20 AND instr(title, char(10))=0),
  CHECK ((status='COMPLETED' AND completed_at IS NOT NULL) OR (status<>'COMPLETED' AND completed_at IS NULL)),
  CHECK ((document_work_state='IDLE' AND active_operation_type IS NULL AND active_operation_id IS NULL AND state_started_at IS NULL) OR (document_work_state<>'IDLE' AND active_operation_type IS NOT NULL AND active_operation_id IS NOT NULL AND state_started_at IS NOT NULL AND ((document_work_state='MANUAL_EDITING' AND active_operation_type='MANUAL_DRAFT') OR (document_work_state='GUIDE_ACTIVE' AND active_operation_type='GUIDE_RUN') OR (document_work_state='SUGGESTION_REVIEWING' AND active_operation_type='SUGGESTION_BATCH')))),
  UNIQUE (requirement_no)
) STRICT;

CREATE TRIGGER requirements_immutable_fields BEFORE UPDATE ON requirements
WHEN NEW.id IS NOT OLD.id OR NEW.requirement_no IS NOT OLD.requirement_no OR NEW.requirement_type IS NOT OLD.requirement_type OR NEW.template_key IS NOT OLD.template_key OR NEW.template_version IS NOT OLD.template_version OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_FIELD'); END;

CREATE TABLE requirement_documents (
  -- BE L282: ID; required
  id INTEGER PRIMARY KEY NOT NULL CHECK (id BETWEEN 1 AND 9007199254740991),
  -- BE L283: ID; required
  requirement_id INTEGER NOT NULL CHECK (requirement_id BETWEEN 1 AND 9007199254740991),
  -- BE L284: Text; required
  document_type TEXT NOT NULL,
  -- BE L285: Text; required
  markdown_content TEXT NOT NULL,
  -- BE L286: BlockState（OBJ-DOC／SHR-BLOCK）; required
  block_state_json TEXT NOT NULL CHECK (json_valid(block_state_json) AND json_type(block_state_json)='object'),
  -- BE L287: PositiveInt; required
  content_version INTEGER NOT NULL CHECK (content_version BETWEEN 1 AND 9007199254740991),
  -- BE L288: UtcTime; required
  created_at TEXT NOT NULL CHECK (length(created_at)=24 AND created_at GLOB '????-??-??T??:??:??.???Z'),
  -- BE L289: UtcTime; required
  updated_at TEXT NOT NULL CHECK (length(updated_at)=24 AND updated_at GLOB '????-??-??T??:??:??.???Z'),
  FOREIGN KEY (requirement_id) REFERENCES requirements(id),
  CHECK (document_type IN ('CURRENT', 'MANUAL_DRAFT')),
  UNIQUE (requirement_id, document_type)
) STRICT;

CREATE TRIGGER requirement_documents_immutable_fields BEFORE UPDATE ON requirement_documents
WHEN NEW.id IS NOT OLD.id OR NEW.requirement_id IS NOT OLD.requirement_id OR NEW.document_type IS NOT OLD.document_type OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_FIELD'); END;

CREATE TABLE revisions (
  -- BE L365: ID; required
  id INTEGER PRIMARY KEY NOT NULL CHECK (id BETWEEN 1 AND 9007199254740991),
  -- BE L366: ID; required
  requirement_id INTEGER NOT NULL CHECK (requirement_id BETWEEN 1 AND 9007199254740991),
  -- BE L367: PositiveInt; required
  version_no INTEGER NOT NULL CHECK (version_no BETWEEN 1 AND 9007199254740991),
  -- BE L368: Text; required
  revision_type TEXT NOT NULL,
  -- BE L369: Text; required
  markdown_snapshot TEXT NOT NULL,
  -- BE L370: BlockState（OBJ-DOC／SHR-BLOCK）; required
  block_state_snapshot_json TEXT NOT NULL CHECK (json_valid(block_state_snapshot_json) AND json_type(block_state_snapshot_json)='object'),
  -- BE L371: Text; nullable
  description TEXT,
  -- BE L372: PositiveInt; required
  source_content_version INTEGER NOT NULL CHECK (source_content_version BETWEEN 1 AND 9007199254740991),
  -- BE L373: UtcTime; required
  created_at TEXT NOT NULL CHECK (length(created_at)=24 AND created_at GLOB '????-??-??T??:??:??.???Z'),
  FOREIGN KEY (requirement_id) REFERENCES requirements(id),
  CHECK (revision_type IN ('BASELINE', 'MANUAL')),
  CHECK ((revision_type='BASELINE' AND version_no=1) OR (revision_type='MANUAL' AND version_no>1)),
  UNIQUE (requirement_id, version_no)
) STRICT;

CREATE TRIGGER revisions_immutable BEFORE UPDATE ON revisions
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;

CREATE TABLE conversation_messages (
  -- BE L422: ID; required
  id INTEGER PRIMARY KEY NOT NULL CHECK (id BETWEEN 1 AND 9007199254740991),
  -- BE L423: ID; required
  requirement_id INTEGER NOT NULL CHECK (requirement_id BETWEEN 1 AND 9007199254740991),
  -- BE L424: ID; nullable
  guide_run_id INTEGER CHECK (guide_run_id BETWEEN 1 AND 9007199254740991),
  -- BE L425: PositiveInt; required
  sequence_no INTEGER NOT NULL CHECK (sequence_no BETWEEN 1 AND 9007199254740991),
  -- BE L426: Text; required
  role TEXT NOT NULL,
  -- BE L427: Text; required
  content TEXT NOT NULL,
  -- BE L428: Text; required
  message_type TEXT NOT NULL,
  -- BE L429: 卡片组或整组回答（本节 SHR-CARDS）; nullable
  structured_content_json TEXT CHECK (json_valid(structured_content_json) AND json_type(structured_content_json)='object' OR structured_content_json IS NULL),
  -- BE L430: ID; nullable
  reply_to_message_id INTEGER CHECK (reply_to_message_id BETWEEN 1 AND 9007199254740991),
  -- BE L431: Text; nullable
  idempotency_key TEXT,
  -- BE L432: UtcTime; required
  created_at TEXT NOT NULL CHECK (length(created_at)=24 AND created_at GLOB '????-??-??T??:??:??.???Z'),
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
  -- BE L528: ID; required
  id INTEGER PRIMARY KEY NOT NULL CHECK (id BETWEEN 1 AND 9007199254740991),
  -- BE L529: ID; required
  requirement_id INTEGER NOT NULL CHECK (requirement_id BETWEEN 1 AND 9007199254740991),
  -- BE L530: Text; required
  idempotency_key TEXT NOT NULL,
  -- BE L531: ID; nullable
  trigger_message_id INTEGER CHECK (trigger_message_id BETWEEN 1 AND 9007199254740991),
  -- BE L532: Text; required
  trigger_type TEXT NOT NULL,
  -- BE L533: Text; required
  source_type TEXT NOT NULL,
  -- BE L534: ID; nullable
  source_id INTEGER CHECK (source_id BETWEEN 1 AND 9007199254740991),
  -- BE L535: Text; required
  function_type TEXT NOT NULL,
  -- BE L536: Text; required
  context_template_key TEXT NOT NULL,
  -- BE L537: Text; required
  context_template_version TEXT NOT NULL,
  -- BE L538: Text; required
  prompt_version TEXT NOT NULL,
  -- BE L539: Text; required
  action_type TEXT NOT NULL,
  -- BE L540: Text; nullable
  mode_snapshot TEXT,
  -- BE L541: Text; required
  instruction_summary TEXT NOT NULL,
  -- BE L542: Text; required
  scope_type TEXT NOT NULL,
  -- BE L543: ScopeRef（APP-GUIDE-CMD-C01 输入）; nullable
  scope_ref_json TEXT CHECK (json_valid(scope_ref_json) AND json_type(scope_ref_json)='object' OR scope_ref_json IS NULL),
  -- BE L544: JSON对象; required
  read_scope_manifest_json TEXT NOT NULL CHECK (json_valid(read_scope_manifest_json) AND json_type(read_scope_manifest_json)='object'),
  -- BE L545: JSON对象; required
  allowed_targets_json TEXT NOT NULL CHECK (json_valid(allowed_targets_json) AND json_type(allowed_targets_json)='object'),
  -- BE L546: Text; required
  status TEXT NOT NULL,
  -- BE L547: Text; required
  current_step TEXT NOT NULL,
  -- BE L548: JSON对象; nullable
  final_result_json TEXT CHECK (json_valid(final_result_json) AND json_type(final_result_json)='object' OR final_result_json IS NULL),
  -- BE L549: UtcTime; required
  created_at TEXT NOT NULL CHECK (length(created_at)=24 AND created_at GLOB '????-??-??T??:??:??.???Z'),
  -- BE L550: UtcTime; nullable
  started_at TEXT CHECK (length(started_at)=24 AND started_at GLOB '????-??-??T??:??:??.???Z'),
  -- BE L551: UtcTime; nullable
  waiting_user_at TEXT CHECK (length(waiting_user_at)=24 AND waiting_user_at GLOB '????-??-??T??:??:??.???Z'),
  -- BE L552: UtcTime; nullable
  ended_at TEXT CHECK (length(ended_at)=24 AND ended_at GLOB '????-??-??T??:??:??.???Z'),
  -- BE L553: UtcTime; required
  updated_at TEXT NOT NULL CHECK (length(updated_at)=24 AND updated_at GLOB '????-??-??T??:??:??.???Z'),
  -- BE L554: Text; nullable
  error_code TEXT,
  -- BE L555: Text; nullable
  error_message TEXT,
  -- BE L556: Text; nullable
  cancel_reason TEXT,
  -- BE L557: ID; nullable
  retry_of_guide_run_id INTEGER CHECK (retry_of_guide_run_id BETWEEN 1 AND 9007199254740991),
  FOREIGN KEY (requirement_id) REFERENCES requirements(id),
  CHECK (action_type IN ('INITIALIZE', 'ASK', 'REVIEW', 'MODIFY')),
  CHECK (source_type IN ('USER_INSTRUCTION', 'REVIEW_RESULT', 'COMMENT')),
  CHECK (scope_type IN ('DOCUMENT', 'SECTION', 'BLOCK', 'SELECTION')),
  CHECK (status IN ('RUNNING', 'WAITING_USER', 'COMPLETED', 'FAILED', 'CANCELLED')),
  CHECK (current_step IN ('PREPARING', 'CALLING_MODEL', 'VALIDATING', 'PERSISTING', 'WAITING_USER', 'FINISHED')),
  CHECK ((action_type='INITIALIZE' AND mode_snapshot IS NOT NULL AND mode_snapshot IN ('IDEATION','DESIGN')) OR (action_type<>'INITIALIZE' AND mode_snapshot IS NULL)),
  CHECK ((status IN ('COMPLETED','FAILED','CANCELLED') AND ended_at IS NOT NULL) OR (status IN ('RUNNING','WAITING_USER') AND ended_at IS NULL)),
  CHECK (status<>'FAILED' OR (error_code IS NOT NULL AND error_message IS NOT NULL)),
  CHECK (status<>'CANCELLED' OR (cancel_reason IS NOT NULL AND final_result_json IS NULL)),
  CHECK (retry_of_guide_run_id IS NULL OR retry_of_guide_run_id<>id),
  FOREIGN KEY (retry_of_guide_run_id) REFERENCES guide_runs(id)
) STRICT;

CREATE TRIGGER guide_runs_immutable_fields BEFORE UPDATE ON guide_runs
WHEN NEW.id IS NOT OLD.id OR NEW.requirement_id IS NOT OLD.requirement_id OR NEW.idempotency_key IS NOT OLD.idempotency_key OR NEW.function_type IS NOT OLD.function_type OR NEW.context_template_key IS NOT OLD.context_template_key OR NEW.context_template_version IS NOT OLD.context_template_version OR NEW.prompt_version IS NOT OLD.prompt_version OR NEW.action_type IS NOT OLD.action_type OR NEW.mode_snapshot IS NOT OLD.mode_snapshot OR NEW.created_at IS NOT OLD.created_at OR NEW.retry_of_guide_run_id IS NOT OLD.retry_of_guide_run_id
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_FIELD'); END;

CREATE TABLE llm_uses (
  -- BE L564: ID; required
  id INTEGER PRIMARY KEY NOT NULL CHECK (id BETWEEN 1 AND 9007199254740991),
  -- BE L565: ID; required
  guide_run_id INTEGER NOT NULL CHECK (guide_run_id BETWEEN 1 AND 9007199254740991),
  -- BE L566: PositiveInt; required
  call_no INTEGER NOT NULL CHECK (call_no BETWEEN 1 AND 9007199254740991),
  -- BE L567: PositiveInt; required
  attempt_no INTEGER NOT NULL CHECK (attempt_no BETWEEN 1 AND 9007199254740991),
  -- BE L568: Text; required
  provider TEXT NOT NULL,
  -- BE L569: Text; required
  model_name TEXT NOT NULL,
  -- BE L570: Text; nullable
  model_version TEXT,
  -- BE L571: Text; required
  function_type TEXT NOT NULL,
  -- BE L572: Text; required
  prompt_config TEXT NOT NULL,
  -- BE L573: JSON对象; required
  request_snapshot_json TEXT NOT NULL CHECK (json_valid(request_snapshot_json) AND json_type(request_snapshot_json)='object'),
  -- BE L574: JSON对象; nullable
  parsed_output_json TEXT CHECK (json_valid(parsed_output_json) AND json_type(parsed_output_json)='object' OR parsed_output_json IS NULL),
  -- BE L575: JSON对象; nullable
  trusted_output_json TEXT CHECK (json_valid(trusted_output_json) AND json_type(trusted_output_json)='object' OR trusted_output_json IS NULL),
  -- BE L576: Text; required
  input_summary TEXT NOT NULL,
  -- BE L577: JSON对象; required
  context_manifest_json TEXT NOT NULL CHECK (json_valid(context_manifest_json) AND json_type(context_manifest_json)='object'),
  -- BE L578: JSON对象; nullable
  raw_response_json TEXT CHECK (json_valid(raw_response_json) AND json_type(raw_response_json)='object' OR raw_response_json IS NULL),
  -- BE L579: Text; nullable
  finish_reason TEXT,
  -- BE L580: Text; required
  parse_status TEXT NOT NULL,
  -- BE L581: Text; nullable
  parse_error TEXT,
  -- BE L582: Text; required
  validation_status TEXT NOT NULL,
  -- BE L583: Text; nullable
  validation_error TEXT,
  -- BE L584: Text; required
  call_status TEXT NOT NULL,
  -- BE L585: Int; nullable
  input_tokens INTEGER CHECK (input_tokens BETWEEN 0 AND 9007199254740991),
  -- BE L586: Int; nullable
  output_tokens INTEGER CHECK (output_tokens BETWEEN 0 AND 9007199254740991),
  -- BE L587: JSON对象; nullable
  cache_info_json TEXT CHECK (json_valid(cache_info_json) AND json_type(cache_info_json)='object' OR cache_info_json IS NULL),
  -- BE L588: ID; nullable
  provider_request_id TEXT,
  -- BE L589: UtcTime; required
  started_at TEXT NOT NULL CHECK (length(started_at)=24 AND started_at GLOB '????-??-??T??:??:??.???Z'),
  -- BE L590: UtcTime; nullable
  ended_at TEXT CHECK (length(ended_at)=24 AND ended_at GLOB '????-??-??T??:??:??.???Z'),
  -- BE L591: Int; nullable
  duration_ms INTEGER CHECK (duration_ms BETWEEN 0 AND 9007199254740991),
  -- BE L592: Text; nullable
  error_code TEXT,
  -- BE L593: Text; nullable
  error_message TEXT,
  -- Q-13 proposal: provider-reported decimal string and currency only; unknown stays NULL.
  cost TEXT,
  cost_currency TEXT,
  CHECK (attempt_no BETWEEN 1 AND 3),
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
  -- BE L665: ID; required
  id INTEGER PRIMARY KEY NOT NULL CHECK (id BETWEEN 1 AND 9007199254740991),
  -- BE L666: ID; required
  requirement_id INTEGER NOT NULL CHECK (requirement_id BETWEEN 1 AND 9007199254740991),
  -- BE L667: ID; required
  guide_run_id INTEGER NOT NULL CHECK (guide_run_id BETWEEN 1 AND 9007199254740991),
  -- BE L668: Text; required
  source_type TEXT NOT NULL,
  -- BE L669: ID; nullable
  source_id INTEGER CHECK (source_id BETWEEN 1 AND 9007199254740991),
  -- BE L670: Text; required
  title TEXT NOT NULL,
  -- BE L671: Text; required
  summary TEXT NOT NULL,
  -- BE L672: Text; required
  status TEXT NOT NULL,
  -- BE L673: Text; nullable
  completion_result TEXT,
  -- BE L674: Text; nullable
  error_message TEXT,
  -- BE L675: Int; required
  base_content_version INTEGER NOT NULL CHECK (base_content_version BETWEEN 1 AND 9007199254740991),
  -- BE L676: Int; nullable
  applied_content_version INTEGER CHECK (applied_content_version BETWEEN 1 AND 9007199254740991),
  -- BE L677: UtcTime; required
  created_at TEXT NOT NULL CHECK (length(created_at)=24 AND created_at GLOB '????-??-??T??:??:??.???Z'),
  -- BE L678: UtcTime; nullable
  completed_at TEXT CHECK (length(completed_at)=24 AND completed_at GLOB '????-??-??T??:??:??.???Z'),
  -- BE L679: UtcTime; required
  updated_at TEXT NOT NULL CHECK (length(updated_at)=24 AND updated_at GLOB '????-??-??T??:??:??.???Z'),
  FOREIGN KEY (requirement_id) REFERENCES requirements(id),
  CHECK (status IN ('PENDING', 'COMPLETED', 'DISCARDED')),
  CHECK ((status='PENDING' AND completion_result IS NULL AND completed_at IS NULL AND applied_content_version IS NULL) OR (status='DISCARDED' AND completion_result IS NULL AND completed_at IS NOT NULL AND applied_content_version IS NULL) OR (status='COMPLETED' AND completion_result IS NOT NULL AND completed_at IS NOT NULL AND ((completion_result='CHANGES_APPLIED' AND applied_content_version IS NOT NULL) OR (completion_result='NO_CHANGE' AND applied_content_version IS NULL)))),
  UNIQUE (guide_run_id),
  FOREIGN KEY (guide_run_id) REFERENCES guide_runs(id)
) STRICT;

CREATE TRIGGER suggestion_batches_immutable_fields BEFORE UPDATE ON suggestion_batches
WHEN NEW.id IS NOT OLD.id OR NEW.requirement_id IS NOT OLD.requirement_id OR NEW.guide_run_id IS NOT OLD.guide_run_id OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_FIELD'); END;

CREATE TABLE suggestions (
  -- BE L686: ID; required
  id INTEGER PRIMARY KEY NOT NULL CHECK (id BETWEEN 1 AND 9007199254740991),
  -- BE L687: ID; required
  batch_id INTEGER NOT NULL CHECK (batch_id BETWEEN 1 AND 9007199254740991),
  -- BE L688: PositiveInt; required
  order_no INTEGER NOT NULL CHECK (order_no BETWEEN 1 AND 9007199254740991),
  -- BE L689: Text; required
  title TEXT NOT NULL,
  -- BE L690: Text; required
  explanation TEXT NOT NULL,
  -- BE L691: Text; nullable
  impact TEXT,
  -- BE L692: Text; required
  patch_operation TEXT NOT NULL,
  -- BE L693: TargetRef（本节 SHR-PATCH）; required
  target_ref_json TEXT NOT NULL CHECK (json_valid(target_ref_json) AND json_type(target_ref_json)='object'),
  -- BE L694: TableRowSelector（本节 SHR-PATCH）; nullable
  selector_json TEXT CHECK (json_valid(selector_json) AND json_type(selector_json)='object' OR selector_json IS NULL),
  -- BE L695: Text; required
  original_content TEXT NOT NULL,
  -- BE L696: Text; nullable
  proposed_markdown TEXT,
  -- BE L697: TableRowData（本节 SHR-PATCH）; nullable
  proposed_data_json TEXT CHECK (json_valid(proposed_data_json) AND json_type(proposed_data_json)='object' OR proposed_data_json IS NULL),
  -- BE L698: Text; nullable
  user_edited_content TEXT,
  -- BE L699: Text; required
  status TEXT NOT NULL,
  -- BE L700: Text; required
  validation_status TEXT NOT NULL,
  -- BE L701: Text; nullable
  validation_error TEXT,
  -- BE L702: UtcTime; required
  created_at TEXT NOT NULL CHECK (length(created_at)=24 AND created_at GLOB '????-??-??T??:??:??.???Z'),
  -- BE L703: UtcTime; nullable
  decided_at TEXT CHECK (length(decided_at)=24 AND decided_at GLOB '????-??-??T??:??:??.???Z'),
  -- BE L704: UtcTime; required
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
  -- BE L788: ID; required
  id INTEGER PRIMARY KEY NOT NULL CHECK (id BETWEEN 1 AND 9007199254740991),
  -- BE L789: ID; required
  requirement_id INTEGER NOT NULL CHECK (requirement_id BETWEEN 1 AND 9007199254740991),
  -- BE L790: Text; required
  content TEXT NOT NULL,
  -- BE L791: Text; required
  anchor_type TEXT NOT NULL,
  -- BE L792: BlockId; required
  block_id INTEGER NOT NULL CHECK (block_id BETWEEN 1 AND 9007199254740991),
  -- BE L793: AnchorRef（本节 SHR-ANCHOR）; required
  anchor_ref_json TEXT NOT NULL CHECK (json_valid(anchor_ref_json) AND json_type(anchor_ref_json)='object'),
  -- BE L794: Text; required
  anchor_status TEXT NOT NULL,
  -- BE L795: Text; required
  status TEXT NOT NULL,
  -- BE L796: UtcTime; nullable
  resolved_at TEXT CHECK (length(resolved_at)=24 AND resolved_at GLOB '????-??-??T??:??:??.???Z'),
  -- BE L797: UtcTime; nullable
  deleted_at TEXT CHECK (length(deleted_at)=24 AND deleted_at GLOB '????-??-??T??:??:??.???Z'),
  -- BE L798: UtcTime; required
  created_at TEXT NOT NULL CHECK (length(created_at)=24 AND created_at GLOB '????-??-??T??:??:??.???Z'),
  -- BE L799: UtcTime; required
  updated_at TEXT NOT NULL CHECK (length(updated_at)=24 AND updated_at GLOB '????-??-??T??:??:??.???Z'),
  FOREIGN KEY (requirement_id) REFERENCES requirements(id),
  CHECK (status IN ('OPEN', 'RESOLVED')),
  CHECK (anchor_status IN ('ATTACHED', 'ORPHANED')),
  CHECK (anchor_type IN ('BLOCK', 'SELECTION')),
  CHECK ((status='OPEN' AND resolved_at IS NULL) OR (status='RESOLVED' AND resolved_at IS NOT NULL)),
  CHECK (length(content) BETWEEN 1 AND 2000)
) STRICT;

CREATE TRIGGER comments_immutable_fields BEFORE UPDATE ON comments
WHEN NEW.id IS NOT OLD.id OR NEW.requirement_id IS NOT OLD.requirement_id OR NEW.anchor_type IS NOT OLD.anchor_type OR NEW.block_id IS NOT OLD.block_id OR NEW.anchor_ref_json IS NOT OLD.anchor_ref_json OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_FIELD'); END;

CREATE UNIQUE INDEX revisions_one_baseline ON revisions(requirement_id) WHERE revision_type='BASELINE';
CREATE UNIQUE INDEX messages_one_card_response ON conversation_messages(reply_to_message_id) WHERE message_type='CARD_RESPONSE';
CREATE INDEX requirements_recent ON requirements(updated_at DESC, id DESC);
CREATE INDEX comments_order ON comments(requirement_id, created_at, id) WHERE deleted_at IS NULL;
CREATE INDEX runs_order ON guide_runs(requirement_id, created_at DESC, id DESC);
CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL) STRICT;
CREATE TABLE sequences (entity_kind TEXT PRIMARY KEY NOT NULL, last_value INTEGER NOT NULL CHECK(last_value BETWEEN 0 AND 9007199254740991)) STRICT;
CREATE TABLE manual_draft_context (draft_id INTEGER PRIMARY KEY NOT NULL REFERENCES requirement_documents(id), current_document_id INTEGER NOT NULL REFERENCES requirement_documents(id), base_content_version INTEGER NOT NULL CHECK(base_content_version BETWEEN 1 AND 9007199254740991), baseline_block_state_json TEXT NOT NULL CHECK(json_valid(baseline_block_state_json) AND json_type(baseline_block_state_json)='object'), operation_time TEXT NOT NULL) STRICT;
CREATE TABLE document_change_audits (id INTEGER PRIMARY KEY NOT NULL CHECK(id BETWEEN 1 AND 9007199254740991), requirement_id INTEGER NOT NULL REFERENCES requirements(id), document_id INTEGER NOT NULL REFERENCES requirement_documents(id), source_type TEXT NOT NULL, source_id INTEGER NOT NULL, reason_code TEXT NOT NULL, before_content_version INTEGER NOT NULL, after_content_version INTEGER NOT NULL, created_at TEXT NOT NULL) STRICT;
CREATE TABLE idempotency_records (capability_id TEXT NOT NULL, target_identity TEXT NOT NULL, idempotency_key TEXT NOT NULL, business_input_json TEXT NOT NULL CHECK(json_valid(business_input_json) AND json_type(business_input_json)='object'), status TEXT NOT NULL CHECK(status IN ('PROCESSING','SUCCEEDED')), owner_epoch TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, success_result_json TEXT CHECK(success_result_json IS NULL OR (json_valid(success_result_json) AND json_type(success_result_json)='object')), http_status INTEGER, PRIMARY KEY(capability_id,target_identity,idempotency_key), CHECK((status='PROCESSING' AND success_result_json IS NULL AND http_status IS NULL) OR (status='SUCCEEDED' AND success_result_json IS NOT NULL AND http_status BETWEEN 200 AND 299))) STRICT;
