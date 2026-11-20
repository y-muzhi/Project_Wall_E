-- V2.1 document formation extension; Schema200 is preserved.

CREATE TABLE formation_schema_state (
  singleton_id INTEGER PRIMARY KEY NOT NULL CHECK(singleton_id=1),
  schema_version INTEGER NOT NULL CHECK(schema_version=210),
  schema_contract_sha256 TEXT NOT NULL CHECK(length(schema_contract_sha256)=64 AND schema_contract_sha256 NOT GLOB '*[^0-9a-f]*'),
  core_contract_sha256 TEXT NOT NULL CHECK(length(core_contract_sha256)=64 AND core_contract_sha256 NOT GLOB '*[^0-9a-f]*'),
  origin TEXT NOT NULL CHECK(origin IN ('FRESH_V21','UPGRADED_V200')),
  upgrade_id TEXT,
  source_data_sha256 TEXT CHECK(length(source_data_sha256)=64 AND source_data_sha256 NOT GLOB '*[^0-9a-f]*'),
  committed_at TEXT NOT NULL CHECK(length(committed_at)=24 AND committed_at GLOB '????-??-??T??:??:??.???Z'),
  CHECK((origin='FRESH_V21' AND upgrade_id IS NULL AND source_data_sha256 IS NULL) OR (origin='UPGRADED_V200' AND upgrade_id IS NOT NULL AND source_data_sha256 IS NOT NULL))
) STRICT;

CREATE UNIQUE INDEX formation_audit_doc_identity ON document_change_audits(id,document_id);

CREATE UNIQUE INDEX formation_message_doc_identity ON conversation_messages(id,document_id);

CREATE TABLE formation_heads (
  document_id INTEGER NOT NULL CHECK(document_id BETWEEN 1 AND 9007199254740991),
  version INTEGER NOT NULL CHECK(version BETWEEN 1 AND 9007199254740991),
  goal_version INTEGER NOT NULL CHECK(goal_version BETWEEN 1 AND 9007199254740991),
  goal_text TEXT NOT NULL CHECK(length(goal_text) BETWEEN 1 AND 1000),
  goal_sources_json TEXT NOT NULL CHECK(json_valid(goal_sources_json) AND json_type(goal_sources_json)='array'),
  current_step_ref TEXT CHECK(substr(current_step_ref,1,1)='s' AND substr(current_step_ref,2)<>'' AND substr(current_step_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(current_step_ref,2),1,1)<>'0' AND (length(substr(current_step_ref,2))<16 OR length(substr(current_step_ref,2))=16 AND substr(current_step_ref,2)<='9007199254740991')),
  active_branch_ref TEXT CHECK(substr(active_branch_ref,1,1)='b' AND substr(active_branch_ref,2)<>'' AND substr(active_branch_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(active_branch_ref,2),1,1)<>'0' AND (length(substr(active_branch_ref,2))<16 OR length(substr(active_branch_ref,2))=16 AND substr(active_branch_ref,2)<='9007199254740991')),
  next_step_no INTEGER NOT NULL CHECK(next_step_no BETWEEN 1 AND 9007199254740991),
  next_branch_no INTEGER NOT NULL CHECK(next_branch_no BETWEEN 1 AND 9007199254740991),
  next_issue_no INTEGER NOT NULL CHECK(next_issue_no BETWEEN 1 AND 9007199254740991),
  next_artifact_no INTEGER NOT NULL CHECK(next_artifact_no BETWEEN 1 AND 9007199254740991),
  PRIMARY KEY(document_id),
  FOREIGN KEY(document_id) REFERENCES requirement_documents(id) ON DELETE RESTRICT,
  FOREIGN KEY(document_id,current_step_ref) REFERENCES formation_steps(document_id,step_ref) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(document_id,active_branch_ref) REFERENCES formation_branches(document_id,branch_ref) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE formation_steps (
  document_id INTEGER NOT NULL CHECK(document_id BETWEEN 1 AND 9007199254740991),
  step_ref TEXT NOT NULL CHECK(substr(step_ref,1,1)='s' AND substr(step_ref,2)<>'' AND substr(step_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(step_ref,2),1,1)<>'0' AND (length(substr(step_ref,2))<16 OR length(substr(step_ref,2))=16 AND substr(step_ref,2)<='9007199254740991')),
  definition_version INTEGER NOT NULL CHECK(definition_version BETWEEN 1 AND 9007199254740991),
  next_result_no INTEGER NOT NULL CHECK(next_result_no BETWEEN 1 AND 9007199254740991),
  position INTEGER NOT NULL CHECK(position<>0 AND position BETWEEN -9007199254740991 AND 9007199254740991),
  title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
  status TEXT NOT NULL CHECK(status IN ('PLANNED','IN_PROGRESS','PAUSED','COMPLETED','CANCELLED')),
  closure_event_id INTEGER CHECK(closure_event_id BETWEEN 1 AND 9007199254740991),
  PRIMARY KEY(document_id,step_ref),
  FOREIGN KEY(document_id) REFERENCES formation_heads(document_id) ON DELETE RESTRICT,
  FOREIGN KEY(closure_event_id,document_id) REFERENCES document_change_audits(id,document_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE UNIQUE INDEX formation_steps_active_position ON formation_steps(document_id,position) WHERE status<>'CANCELLED';

CREATE INDEX formation_steps_order ON formation_steps(document_id,position,step_ref);

CREATE TABLE formation_results (
  document_id INTEGER NOT NULL CHECK(document_id BETWEEN 1 AND 9007199254740991),
  step_ref TEXT NOT NULL CHECK(substr(step_ref,1,1)='s' AND substr(step_ref,2)<>'' AND substr(step_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(step_ref,2),1,1)<>'0' AND (length(substr(step_ref,2))<16 OR length(substr(step_ref,2))=16 AND substr(step_ref,2)<='9007199254740991')),
  result_ref TEXT NOT NULL CHECK(substr(result_ref,1,1)='s' AND instr(result_ref,'.o')>2) CHECK(substr(result_ref,2,instr(result_ref,'.o')-2)<>'' AND substr(result_ref,2,instr(result_ref,'.o')-2) NOT GLOB '*[^0-9]*' AND substr(substr(result_ref,2,instr(result_ref,'.o')-2),1,1)<>'0' AND (length(substr(result_ref,2,instr(result_ref,'.o')-2))<16 OR length(substr(result_ref,2,instr(result_ref,'.o')-2))=16 AND substr(result_ref,2,instr(result_ref,'.o')-2)<='9007199254740991')) CHECK(substr(result_ref,instr(result_ref,'.o')+2)<>'' AND substr(result_ref,instr(result_ref,'.o')+2) NOT GLOB '*[^0-9]*' AND substr(substr(result_ref,instr(result_ref,'.o')+2),1,1)<>'0' AND (length(substr(result_ref,instr(result_ref,'.o')+2))<16 OR length(substr(result_ref,instr(result_ref,'.o')+2))=16 AND substr(result_ref,instr(result_ref,'.o')+2)<='9007199254740991')),
  description TEXT NOT NULL CHECK(length(description) BETWEEN 1 AND 1000),
  kind TEXT NOT NULL CHECK(kind IN ('CONTENT','ANALYSIS')),
  PRIMARY KEY(document_id,step_ref,result_ref),
  UNIQUE(document_id,result_ref),
  CHECK(substr(result_ref,1,instr(result_ref,'.o')-1)=step_ref),
  FOREIGN KEY(document_id,step_ref) REFERENCES formation_steps(document_id,step_ref) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE formation_step_edges (
  document_id INTEGER NOT NULL CHECK(document_id BETWEEN 1 AND 9007199254740991),
  from_step_ref TEXT NOT NULL CHECK(substr(from_step_ref,1,1)='s' AND substr(from_step_ref,2)<>'' AND substr(from_step_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(from_step_ref,2),1,1)<>'0' AND (length(substr(from_step_ref,2))<16 OR length(substr(from_step_ref,2))=16 AND substr(from_step_ref,2)<='9007199254740991')),
  to_step_ref TEXT NOT NULL CHECK(substr(to_step_ref,1,1)='s' AND substr(to_step_ref,2)<>'' AND substr(to_step_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(to_step_ref,2),1,1)<>'0' AND (length(substr(to_step_ref,2))<16 OR length(substr(to_step_ref,2))=16 AND substr(to_step_ref,2)<='9007199254740991')),
  kind TEXT NOT NULL CHECK(kind IN ('DEPENDENCY','REPLACES')),
  PRIMARY KEY(document_id,from_step_ref,to_step_ref,kind),
  CHECK(from_step_ref<>to_step_ref),
  FOREIGN KEY(document_id,from_step_ref) REFERENCES formation_steps(document_id,step_ref) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(document_id,to_step_ref) REFERENCES formation_steps(document_id,step_ref) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE INDEX formation_edges_incoming ON formation_step_edges(document_id,to_step_ref,kind,from_step_ref);

CREATE TABLE formation_step_topics (
  document_id INTEGER NOT NULL CHECK(document_id BETWEEN 1 AND 9007199254740991),
  step_ref TEXT NOT NULL CHECK(substr(step_ref,1,1)='s' AND substr(step_ref,2)<>'' AND substr(step_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(step_ref,2),1,1)<>'0' AND (length(substr(step_ref,2))<16 OR length(substr(step_ref,2))=16 AND substr(step_ref,2)<='9007199254740991')),
  topic_ref TEXT NOT NULL,
  PRIMARY KEY(document_id,step_ref,topic_ref),
  FOREIGN KEY(document_id,step_ref) REFERENCES formation_steps(document_id,step_ref) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE formation_branches (
  document_id INTEGER NOT NULL CHECK(document_id BETWEEN 1 AND 9007199254740991),
  branch_ref TEXT NOT NULL CHECK(substr(branch_ref,1,1)='b' AND substr(branch_ref,2)<>'' AND substr(branch_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(branch_ref,2),1,1)<>'0' AND (length(substr(branch_ref,2))<16 OR length(substr(branch_ref,2))=16 AND substr(branch_ref,2)<='9007199254740991')),
  origin_step_ref TEXT NOT NULL CHECK(substr(origin_step_ref,1,1)='s' AND substr(origin_step_ref,2)<>'' AND substr(origin_step_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(origin_step_ref,2),1,1)<>'0' AND (length(substr(origin_step_ref,2))<16 OR length(substr(origin_step_ref,2))=16 AND substr(origin_step_ref,2)<='9007199254740991')),
  return_step_ref TEXT NOT NULL CHECK(substr(return_step_ref,1,1)='s' AND substr(return_step_ref,2)<>'' AND substr(return_step_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(return_step_ref,2),1,1)<>'0' AND (length(substr(return_step_ref,2))<16 OR length(substr(return_step_ref,2))=16 AND substr(return_step_ref,2)<='9007199254740991')),
  question TEXT NOT NULL CHECK(length(question) BETWEEN 1 AND 1000),
  relevance TEXT NOT NULL CHECK(length(relevance) BETWEEN 1 AND 1000),
  status TEXT NOT NULL CHECK(status IN ('OPEN','RESOLVED','DEFERRED','DROPPED')),
  origin_event_id INTEGER NOT NULL CHECK(origin_event_id BETWEEN 1 AND 9007199254740991),
  state_event_id INTEGER NOT NULL CHECK(state_event_id BETWEEN 1 AND 9007199254740991),
  result_summary TEXT CHECK(length(result_summary) BETWEEN 1 AND 1000),
  result_sources_json TEXT NOT NULL CHECK(json_valid(result_sources_json) AND json_type(result_sources_json)='array'),
  disposition_event_id INTEGER CHECK(disposition_event_id BETWEEN 1 AND 9007199254740991),
  PRIMARY KEY(document_id,branch_ref),
  FOREIGN KEY(document_id,origin_step_ref) REFERENCES formation_steps(document_id,step_ref) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(document_id,return_step_ref) REFERENCES formation_steps(document_id,step_ref) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(origin_event_id,document_id) REFERENCES document_change_audits(id,document_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(state_event_id,document_id) REFERENCES document_change_audits(id,document_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(disposition_event_id,document_id) REFERENCES document_change_audits(id,document_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  CHECK(status<>'RESOLVED' OR (result_summary IS NOT NULL AND json_array_length(result_sources_json)>0))
) STRICT;

CREATE INDEX formation_branches_return ON formation_branches(document_id,return_step_ref,status,branch_ref);

CREATE INDEX formation_branches_status ON formation_branches(document_id,status,branch_ref);

CREATE TABLE formation_branch_topics (
  document_id INTEGER NOT NULL CHECK(document_id BETWEEN 1 AND 9007199254740991),
  branch_ref TEXT NOT NULL CHECK(substr(branch_ref,1,1)='b' AND substr(branch_ref,2)<>'' AND substr(branch_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(branch_ref,2),1,1)<>'0' AND (length(substr(branch_ref,2))<16 OR length(substr(branch_ref,2))=16 AND substr(branch_ref,2)<='9007199254740991')),
  topic_ref TEXT NOT NULL,
  PRIMARY KEY(document_id,branch_ref,topic_ref),
  FOREIGN KEY(document_id,branch_ref) REFERENCES formation_branches(document_id,branch_ref) ON DELETE RESTRICT
) STRICT;

CREATE TABLE formation_issues (
  document_id INTEGER NOT NULL CHECK(document_id BETWEEN 1 AND 9007199254740991),
  issue_ref TEXT NOT NULL CHECK(substr(issue_ref,1,1)='i' AND substr(issue_ref,2)<>'' AND substr(issue_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(issue_ref,2),1,1)<>'0' AND (length(substr(issue_ref,2))<16 OR length(substr(issue_ref,2))=16 AND substr(issue_ref,2)<='9007199254740991')),
  step_ref TEXT NOT NULL CHECK(substr(step_ref,1,1)='s' AND substr(step_ref,2)<>'' AND substr(step_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(step_ref,2),1,1)<>'0' AND (length(substr(step_ref,2))<16 OR length(substr(step_ref,2))=16 AND substr(step_ref,2)<='9007199254740991')),
  branch_ref TEXT CHECK(substr(branch_ref,1,1)='b' AND substr(branch_ref,2)<>'' AND substr(branch_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(branch_ref,2),1,1)<>'0' AND (length(substr(branch_ref,2))<16 OR length(substr(branch_ref,2))=16 AND substr(branch_ref,2)<='9007199254740991')),
  description TEXT NOT NULL CHECK(length(description) BETWEEN 1 AND 1000),
  source_refs_json TEXT NOT NULL CHECK(json_valid(source_refs_json) AND json_type(source_refs_json)='array'),
  blocking INTEGER NOT NULL CHECK(blocking IN (0,1)),
  disposition TEXT NOT NULL CHECK(disposition IN ('OPEN','RESOLVED','DEFERRED','DROPPED')),
  disposition_reason TEXT CHECK(length(disposition_reason) BETWEEN 1 AND 1000),
  resolution_sources_json TEXT NOT NULL CHECK(json_valid(resolution_sources_json) AND json_type(resolution_sources_json)='array'),
  disposition_event_id INTEGER CHECK(disposition_event_id BETWEEN 1 AND 9007199254740991),
  PRIMARY KEY(document_id,issue_ref),
  FOREIGN KEY(document_id,step_ref) REFERENCES formation_steps(document_id,step_ref) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(document_id,branch_ref) REFERENCES formation_branches(document_id,branch_ref) ON DELETE RESTRICT,
  FOREIGN KEY(disposition_event_id,document_id) REFERENCES document_change_audits(id,document_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  CHECK(disposition NOT IN ('DEFERRED','DROPPED') OR disposition_reason IS NOT NULL),
  CHECK(disposition<>'RESOLVED' OR json_array_length(resolution_sources_json)>0)
) STRICT;

CREATE INDEX formation_issues_step ON formation_issues(document_id,step_ref,disposition,issue_ref);

CREATE INDEX formation_issues_branch ON formation_issues(document_id,branch_ref,disposition,issue_ref);

CREATE TABLE formation_artifacts (
  document_id INTEGER NOT NULL CHECK(document_id BETWEEN 1 AND 9007199254740991),
  artifact_ref TEXT NOT NULL CHECK(substr(artifact_ref,1,1)='a' AND substr(artifact_ref,2)<>'' AND substr(artifact_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(artifact_ref,2),1,1)<>'0' AND (length(substr(artifact_ref,2))<16 OR length(substr(artifact_ref,2))=16 AND substr(artifact_ref,2)<='9007199254740991')),
  step_ref TEXT NOT NULL CHECK(substr(step_ref,1,1)='s' AND substr(step_ref,2)<>'' AND substr(step_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(step_ref,2),1,1)<>'0' AND (length(substr(step_ref,2))<16 OR length(substr(step_ref,2))=16 AND substr(step_ref,2)<='9007199254740991')),
  source_event_id INTEGER NOT NULL CHECK(source_event_id BETWEEN 1 AND 9007199254740991),
  origin_revision_id INTEGER NOT NULL CHECK(origin_revision_id BETWEEN 1 AND 9007199254740991),
  origin_digest TEXT NOT NULL CHECK(length(origin_digest)=64 AND origin_digest NOT GLOB '*[^0-9a-f]*'),
  summary TEXT NOT NULL CHECK(length(summary) BETWEEN 1 AND 240),
  checked_against_revision_id INTEGER NOT NULL CHECK(checked_against_revision_id BETWEEN 1 AND 9007199254740991),
  freshness TEXT NOT NULL CHECK(freshness IN ('CURRENT','NEEDS_REVIEW','REMOVED')),
  review_reason TEXT CHECK(review_reason IN ('CHANGED','UNVERIFIABLE')),
  PRIMARY KEY(document_id,artifact_ref),
  FOREIGN KEY(document_id,step_ref) REFERENCES formation_steps(document_id,step_ref) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(source_event_id,document_id) REFERENCES document_change_audits(id,document_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(origin_revision_id,document_id) REFERENCES revisions(id,document_id) ON DELETE RESTRICT,
  FOREIGN KEY(checked_against_revision_id,document_id) REFERENCES revisions(id,document_id) ON DELETE RESTRICT,
  CHECK((freshness='NEEDS_REVIEW' AND review_reason IS NOT NULL) OR (freshness<>'NEEDS_REVIEW' AND review_reason IS NULL))
) STRICT;

CREATE INDEX formation_artifacts_step ON formation_artifacts(document_id,step_ref,freshness,artifact_ref);

CREATE TABLE formation_artifact_results (
  document_id INTEGER NOT NULL CHECK(document_id BETWEEN 1 AND 9007199254740991),
  artifact_ref TEXT NOT NULL CHECK(substr(artifact_ref,1,1)='a' AND substr(artifact_ref,2)<>'' AND substr(artifact_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(artifact_ref,2),1,1)<>'0' AND (length(substr(artifact_ref,2))<16 OR length(substr(artifact_ref,2))=16 AND substr(artifact_ref,2)<='9007199254740991')),
  result_ref TEXT NOT NULL CHECK(substr(result_ref,1,1)='s' AND instr(result_ref,'.o')>2) CHECK(substr(result_ref,2,instr(result_ref,'.o')-2)<>'' AND substr(result_ref,2,instr(result_ref,'.o')-2) NOT GLOB '*[^0-9]*' AND substr(substr(result_ref,2,instr(result_ref,'.o')-2),1,1)<>'0' AND (length(substr(result_ref,2,instr(result_ref,'.o')-2))<16 OR length(substr(result_ref,2,instr(result_ref,'.o')-2))=16 AND substr(result_ref,2,instr(result_ref,'.o')-2)<='9007199254740991')) CHECK(substr(result_ref,instr(result_ref,'.o')+2)<>'' AND substr(result_ref,instr(result_ref,'.o')+2) NOT GLOB '*[^0-9]*' AND substr(substr(result_ref,instr(result_ref,'.o')+2),1,1)<>'0' AND (length(substr(result_ref,instr(result_ref,'.o')+2))<16 OR length(substr(result_ref,instr(result_ref,'.o')+2))=16 AND substr(result_ref,instr(result_ref,'.o')+2)<='9007199254740991')),
  PRIMARY KEY(document_id,artifact_ref,result_ref),
  FOREIGN KEY(document_id,artifact_ref) REFERENCES formation_artifacts(document_id,artifact_ref) ON DELETE RESTRICT,
  FOREIGN KEY(document_id,result_ref) REFERENCES formation_results(document_id,result_ref) ON DELETE RESTRICT
) STRICT;

CREATE TABLE formation_artifact_ranges (
  document_id INTEGER NOT NULL CHECK(document_id BETWEEN 1 AND 9007199254740991),
  artifact_ref TEXT NOT NULL CHECK(substr(artifact_ref,1,1)='a' AND substr(artifact_ref,2)<>'' AND substr(artifact_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(artifact_ref,2),1,1)<>'0' AND (length(substr(artifact_ref,2))<16 OR length(substr(artifact_ref,2))=16 AND substr(artifact_ref,2)<='9007199254740991')),
  role TEXT NOT NULL CHECK(role IN ('ORIGIN','CURRENT')),
  ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 9007199254740991),
  revision_id INTEGER NOT NULL CHECK(revision_id BETWEEN 1 AND 9007199254740991),
  block_id INTEGER NOT NULL CHECK(block_id BETWEEN 1 AND 9007199254740991),
  block_digest TEXT NOT NULL CHECK(length(block_digest)=64 AND block_digest NOT GLOB '*[^0-9a-f]*'),
  PRIMARY KEY(document_id,artifact_ref,role,ordinal),
  FOREIGN KEY(document_id,artifact_ref) REFERENCES formation_artifacts(document_id,artifact_ref) ON DELETE RESTRICT,
  FOREIGN KEY(revision_id,document_id) REFERENCES revisions(id,document_id) ON DELETE RESTRICT
) STRICT;

CREATE INDEX formation_ranges_block ON formation_artifact_ranges(document_id,revision_id,block_id,role);

CREATE TABLE formation_assessments (
  id INTEGER NOT NULL CHECK(id BETWEEN 1 AND 9007199254740991),
  document_id INTEGER NOT NULL CHECK(document_id BETWEEN 1 AND 9007199254740991),
  step_ref TEXT NOT NULL CHECK(substr(step_ref,1,1)='s' AND substr(step_ref,2)<>'' AND substr(step_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(step_ref,2),1,1)<>'0' AND (length(substr(step_ref,2))<16 OR length(substr(step_ref,2))=16 AND substr(step_ref,2)<='9007199254740991')),
  event_id INTEGER NOT NULL CHECK(event_id BETWEEN 1 AND 9007199254740991),
  assistant_message_id INTEGER NOT NULL CHECK(assistant_message_id BETWEEN 1 AND 9007199254740991),
  goal_version INTEGER NOT NULL CHECK(goal_version BETWEEN 1 AND 9007199254740991),
  definition_version INTEGER NOT NULL CHECK(definition_version BETWEEN 1 AND 9007199254740991),
  evaluated_revision_id INTEGER NOT NULL CHECK(evaluated_revision_id BETWEEN 1 AND 9007199254740991),
  verdict TEXT NOT NULL CHECK(verdict IN ('SUFFICIENT','GAPS_REMAIN','UNCERTAIN')),
  reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 1000),
  coverage_json TEXT NOT NULL CHECK(json_valid(coverage_json) AND json_type(coverage_json)='array'),
  source_refs_json TEXT NOT NULL CHECK(json_valid(source_refs_json) AND json_type(source_refs_json)='array'),
  PRIMARY KEY(id),
  FOREIGN KEY(evaluated_revision_id,document_id) REFERENCES revisions(id,document_id) ON DELETE RESTRICT,
  FOREIGN KEY(document_id,step_ref) REFERENCES formation_steps(document_id,step_ref) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(event_id,document_id) REFERENCES document_change_audits(id,document_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(assistant_message_id,document_id) REFERENCES conversation_messages(id,document_id) ON DELETE RESTRICT
) STRICT;

CREATE INDEX formation_assessments_latest ON formation_assessments(document_id,step_ref,event_id DESC,id DESC);

CREATE TABLE formation_recommendations (
  id INTEGER NOT NULL CHECK(id BETWEEN 1 AND 9007199254740991),
  document_id INTEGER NOT NULL CHECK(document_id BETWEEN 1 AND 9007199254740991),
  step_ref TEXT NOT NULL CHECK(substr(step_ref,1,1)='s' AND substr(step_ref,2)<>'' AND substr(step_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(step_ref,2),1,1)<>'0' AND (length(substr(step_ref,2))<16 OR length(substr(step_ref,2))=16 AND substr(step_ref,2)<='9007199254740991')),
  event_id INTEGER NOT NULL CHECK(event_id BETWEEN 1 AND 9007199254740991),
  assistant_message_id INTEGER NOT NULL CHECK(assistant_message_id BETWEEN 1 AND 9007199254740991),
  action TEXT NOT NULL,
  reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 1000),
  target_step_ref TEXT CHECK(substr(target_step_ref,1,1)='s' AND substr(target_step_ref,2)<>'' AND substr(target_step_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(target_step_ref,2),1,1)<>'0' AND (length(substr(target_step_ref,2))<16 OR length(substr(target_step_ref,2))=16 AND substr(target_step_ref,2)<='9007199254740991')),
  source_refs_json TEXT NOT NULL CHECK(json_valid(source_refs_json) AND json_type(source_refs_json)='array'),
  basis_json TEXT NOT NULL CHECK(json_valid(basis_json) AND json_type(basis_json)='object'),
  PRIMARY KEY(id),
  FOREIGN KEY(document_id,target_step_ref) REFERENCES formation_steps(document_id,step_ref) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(document_id,step_ref) REFERENCES formation_steps(document_id,step_ref) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(event_id,document_id) REFERENCES document_change_audits(id,document_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(assistant_message_id,document_id) REFERENCES conversation_messages(id,document_id) ON DELETE RESTRICT
) STRICT;

CREATE INDEX formation_recommendations_latest ON formation_recommendations(document_id,step_ref,event_id DESC,id DESC);

CREATE TABLE formation_proposal_index (
  document_id INTEGER NOT NULL CHECK(document_id BETWEEN 1 AND 9007199254740991),
  message_id INTEGER NOT NULL CHECK(message_id BETWEEN 1 AND 9007199254740991),
  card_key TEXT NOT NULL CHECK(length(card_key) BETWEEN 1 AND 100),
  purpose TEXT NOT NULL CHECK(purpose IN ('STAGED_WRITE','FORMATION_PATH_CHANGE')),
  disposition TEXT NOT NULL CHECK(disposition IN ('PENDING','DEFERRED','APPLIED','SUPERSEDED')),
  disposition_event_id INTEGER CHECK(disposition_event_id BETWEEN 1 AND 9007199254740991),
  binding_json TEXT NOT NULL CHECK(json_valid(binding_json) AND json_type(binding_json)='object'),
  payload_digest TEXT NOT NULL CHECK(length(payload_digest)=64 AND payload_digest NOT GLOB '*[^0-9a-f]*'),
  PRIMARY KEY(document_id,message_id,card_key),
  FOREIGN KEY(document_id) REFERENCES formation_heads(document_id) ON DELETE RESTRICT,
  FOREIGN KEY(message_id,document_id) REFERENCES conversation_messages(id,document_id) ON DELETE RESTRICT,
  FOREIGN KEY(disposition_event_id,document_id) REFERENCES document_change_audits(id,document_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE INDEX formation_proposals_page ON formation_proposal_index(document_id,purpose,disposition,message_id,card_key);

CREATE TABLE formation_event_refs (
  document_id INTEGER NOT NULL CHECK(document_id BETWEEN 1 AND 9007199254740991),
  event_id INTEGER NOT NULL CHECK(event_id BETWEEN 1 AND 9007199254740991),
  kind TEXT NOT NULL CHECK(kind IN ('STEP','BRANCH','ISSUE','ARTIFACT','RESULT')),
  ref TEXT NOT NULL,
  PRIMARY KEY(document_id,event_id,kind,ref),
  FOREIGN KEY(document_id) REFERENCES formation_heads(document_id) ON DELETE RESTRICT,
  FOREIGN KEY(event_id,document_id) REFERENCES document_change_audits(id,document_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE INDEX formation_events_entity ON formation_event_refs(document_id,kind,ref,event_id DESC);

CREATE TABLE formation_event_changes (
  event_id INTEGER NOT NULL CHECK(event_id BETWEEN 1 AND 9007199254740991),
  ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 9007199254740991),
  document_id INTEGER NOT NULL CHECK(document_id BETWEEN 1 AND 9007199254740991),
  entity_kind TEXT NOT NULL CHECK(entity_kind IN ('GOAL','STEP','RESULT','BRANCH','ISSUE','ARTIFACT','ASSESSMENT','RECOMMENDATION','PROPOSAL','PROPOSAL_CHECK','ARTIFACT_REVIEW','RESULT_ROUTE','ORDER')),
  entity_ref TEXT NOT NULL,
  before_json TEXT CHECK(before_json IS NULL OR json_valid(before_json)),
  after_json TEXT CHECK(after_json IS NULL OR json_valid(after_json)),
  member_count INTEGER NOT NULL CHECK(member_count BETWEEN 0 AND 9007199254740991),
  member_digest TEXT NOT NULL CHECK(length(member_digest)=64 AND member_digest NOT GLOB '*[^0-9a-f]*'),
  PRIMARY KEY(event_id,ordinal),
  UNIQUE(event_id,ordinal,document_id),
  CHECK(before_json IS NOT NULL OR after_json IS NOT NULL),
  FOREIGN KEY(document_id) REFERENCES formation_heads(document_id) ON DELETE RESTRICT,
  FOREIGN KEY(event_id,document_id) REFERENCES document_change_audits(id,document_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE UNIQUE INDEX formation_review_fact_unique ON formation_event_changes(event_id,entity_kind,entity_ref) WHERE entity_kind IN ('PROPOSAL_CHECK','ARTIFACT_REVIEW');

CREATE TABLE formation_closures (
  event_id INTEGER NOT NULL CHECK(event_id BETWEEN 1 AND 9007199254740991),
  document_id INTEGER NOT NULL CHECK(document_id BETWEEN 1 AND 9007199254740991),
  step_ref TEXT NOT NULL CHECK(substr(step_ref,1,1)='s' AND substr(step_ref,2)<>'' AND substr(step_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(step_ref,2),1,1)<>'0' AND (length(substr(step_ref,2))<16 OR length(substr(step_ref,2))=16 AND substr(step_ref,2)<='9007199254740991')),
  definition_version INTEGER NOT NULL CHECK(definition_version BETWEEN 1 AND 9007199254740991),
  goal_version INTEGER NOT NULL CHECK(goal_version BETWEEN 1 AND 9007199254740991),
  revision_id INTEGER NOT NULL CHECK(revision_id BETWEEN 1 AND 9007199254740991),
  command_message_id INTEGER NOT NULL CHECK(command_message_id BETWEEN 1 AND 9007199254740991),
  next_step_ref TEXT CHECK(substr(next_step_ref,1,1)='s' AND substr(next_step_ref,2)<>'' AND substr(next_step_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(next_step_ref,2),1,1)<>'0' AND (length(substr(next_step_ref,2))<16 OR length(substr(next_step_ref,2))=16 AND substr(next_step_ref,2)<='9007199254740991')),
  result_count INTEGER NOT NULL CHECK(result_count BETWEEN 0 AND 9007199254740991),
  issue_count INTEGER NOT NULL CHECK(issue_count BETWEEN 0 AND 9007199254740991),
  branch_count INTEGER NOT NULL CHECK(branch_count BETWEEN 0 AND 9007199254740991),
  items_digest TEXT NOT NULL CHECK(length(items_digest)=64 AND items_digest NOT GLOB '*[^0-9a-f]*'),
  PRIMARY KEY(event_id),
  FOREIGN KEY(document_id) REFERENCES formation_heads(document_id) ON DELETE RESTRICT,
  FOREIGN KEY(document_id,step_ref) REFERENCES formation_steps(document_id,step_ref) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(document_id,next_step_ref) REFERENCES formation_steps(document_id,step_ref) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(event_id,document_id) REFERENCES document_change_audits(id,document_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(revision_id,document_id) REFERENCES revisions(id,document_id) ON DELETE RESTRICT,
  FOREIGN KEY(command_message_id,document_id) REFERENCES conversation_messages(id,document_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE formation_closure_items (
  event_id INTEGER NOT NULL CHECK(event_id BETWEEN 1 AND 9007199254740991),
  kind TEXT NOT NULL CHECK(kind IN ('RESULT','ISSUE','BRANCH')),
  item_ref TEXT NOT NULL,
  ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 9007199254740991),
  status TEXT NOT NULL,
  payload_json TEXT NOT NULL CHECK(json_valid(payload_json) AND json_type(payload_json)='object'),
  PRIMARY KEY(event_id,kind,item_ref),
  UNIQUE(event_id,kind,ordinal),
  FOREIGN KEY(event_id) REFERENCES formation_closures(event_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE formation_closure_evidence (
  event_id INTEGER NOT NULL CHECK(event_id BETWEEN 1 AND 9007199254740991),
  owner_kind TEXT NOT NULL CHECK(owner_kind IN ('RESULT','ISSUE','BRANCH')),
  item_ref TEXT NOT NULL,
  ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 9007199254740991),
  evidence_kind TEXT NOT NULL,
  artifact_ref TEXT CHECK(substr(artifact_ref,1,1)='a' AND substr(artifact_ref,2)<>'' AND substr(artifact_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(artifact_ref,2),1,1)<>'0' AND (length(substr(artifact_ref,2))<16 OR length(substr(artifact_ref,2))=16 AND substr(artifact_ref,2)<='9007199254740991')),
  payload_json TEXT NOT NULL CHECK(json_valid(payload_json) AND json_type(payload_json)='object'),
  PRIMARY KEY(event_id,owner_kind,item_ref,ordinal),
  FOREIGN KEY(event_id,owner_kind,item_ref) REFERENCES formation_closure_items(event_id,kind,item_ref) ON DELETE RESTRICT
) STRICT;

CREATE INDEX formation_closure_evidence_page ON formation_closure_evidence(event_id,owner_kind,item_ref,evidence_kind,ordinal);

CREATE TABLE formation_event_members (
  event_id INTEGER NOT NULL CHECK(event_id BETWEEN 1 AND 9007199254740991),
  change_ordinal INTEGER NOT NULL CHECK(change_ordinal BETWEEN 1 AND 9007199254740991),
  ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 9007199254740991),
  document_id INTEGER NOT NULL CHECK(document_id BETWEEN 1 AND 9007199254740991),
  collection TEXT NOT NULL CHECK(collection IN ('DEPENDENCY','REPLACES','TOPIC','GOAL_SOURCE','ISSUE_SOURCE','ISSUE_RESOLUTION_SOURCE','BRANCH_TOPIC','BRANCH_RESULT_SOURCE','ARTIFACT_RESULT','ORIGIN_RANGE','CURRENT_RANGE')),
  member_key TEXT NOT NULL,
  before_json TEXT CHECK(before_json IS NULL OR json_valid(before_json)),
  after_json TEXT CHECK(after_json IS NULL OR json_valid(after_json)),
  PRIMARY KEY(event_id,change_ordinal,ordinal),
  UNIQUE(event_id,change_ordinal,collection,member_key),
  CHECK(before_json IS NOT NULL OR after_json IS NOT NULL),
  FOREIGN KEY(event_id,change_ordinal,document_id) REFERENCES formation_event_changes(event_id,ordinal,document_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE formation_artifact_reviews (
  document_id INTEGER NOT NULL CHECK(document_id BETWEEN 1 AND 9007199254740991),
  event_id INTEGER NOT NULL CHECK(event_id BETWEEN 1 AND 9007199254740991),
  reviewed_artifact_ref TEXT NOT NULL CHECK(substr(reviewed_artifact_ref,1,1)='a' AND substr(reviewed_artifact_ref,2)<>'' AND substr(reviewed_artifact_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(reviewed_artifact_ref,2),1,1)<>'0' AND (length(substr(reviewed_artifact_ref,2))<16 OR length(substr(reviewed_artifact_ref,2))=16 AND substr(reviewed_artifact_ref,2)<='9007199254740991')),
  replacement_artifact_ref TEXT CHECK(substr(replacement_artifact_ref,1,1)='a' AND substr(replacement_artifact_ref,2)<>'' AND substr(replacement_artifact_ref,2) NOT GLOB '*[^0-9]*' AND substr(substr(replacement_artifact_ref,2),1,1)<>'0' AND (length(substr(replacement_artifact_ref,2))<16 OR length(substr(replacement_artifact_ref,2))=16 AND substr(replacement_artifact_ref,2)<='9007199254740991')),
  result TEXT NOT NULL CHECK(result IN ('MATCHED','REASSOCIATED','UNVERIFIED','REMOVED')),
  checked_against_revision_id INTEGER NOT NULL CHECK(checked_against_revision_id BETWEEN 1 AND 9007199254740991),
  assistant_message_id INTEGER NOT NULL CHECK(assistant_message_id BETWEEN 1 AND 9007199254740991),
  source_refs_json TEXT NOT NULL CHECK(json_valid(source_refs_json) AND json_type(source_refs_json)='array'),
  PRIMARY KEY(document_id,event_id,reviewed_artifact_ref),
  FOREIGN KEY(event_id,document_id) REFERENCES document_change_audits(id,document_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(document_id,reviewed_artifact_ref) REFERENCES formation_artifacts(document_id,artifact_ref) ON DELETE RESTRICT,
  FOREIGN KEY(document_id,replacement_artifact_ref) REFERENCES formation_artifacts(document_id,artifact_ref) ON DELETE RESTRICT,
  FOREIGN KEY(checked_against_revision_id,document_id) REFERENCES revisions(id,document_id) ON DELETE RESTRICT,
  FOREIGN KEY(assistant_message_id,document_id) REFERENCES conversation_messages(id,document_id) ON DELETE RESTRICT,
  CHECK((result='REASSOCIATED' AND replacement_artifact_ref IS NOT NULL AND replacement_artifact_ref<>reviewed_artifact_ref) OR (result<>'REASSOCIATED' AND replacement_artifact_ref IS NULL))
) STRICT;

CREATE UNIQUE INDEX formation_artifact_reviewed_unique ON formation_artifact_reviews(document_id,reviewed_artifact_ref) WHERE result='REASSOCIATED';

CREATE UNIQUE INDEX formation_artifact_replacement_unique ON formation_artifact_reviews(document_id,replacement_artifact_ref) WHERE result='REASSOCIATED';

CREATE INDEX formation_reviews_history ON formation_artifact_reviews(document_id,reviewed_artifact_ref,event_id DESC);

CREATE TRIGGER formation_schema_state_update_guard BEFORE UPDATE ON formation_schema_state BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;

CREATE TRIGGER formation_schema_state_delete_guard BEFORE DELETE ON formation_schema_state BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;

CREATE TRIGGER formation_assessments_update_guard BEFORE UPDATE ON formation_assessments BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;

CREATE TRIGGER formation_assessments_delete_guard BEFORE DELETE ON formation_assessments BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;

CREATE TRIGGER formation_recommendations_update_guard BEFORE UPDATE ON formation_recommendations BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;

CREATE TRIGGER formation_recommendations_delete_guard BEFORE DELETE ON formation_recommendations BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;

CREATE TRIGGER formation_event_refs_update_guard BEFORE UPDATE ON formation_event_refs BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;

CREATE TRIGGER formation_event_refs_delete_guard BEFORE DELETE ON formation_event_refs BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;

CREATE TRIGGER formation_event_changes_update_guard BEFORE UPDATE ON formation_event_changes BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;

CREATE TRIGGER formation_event_changes_delete_guard BEFORE DELETE ON formation_event_changes BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;

CREATE TRIGGER formation_event_members_update_guard BEFORE UPDATE ON formation_event_members BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;

CREATE TRIGGER formation_event_members_delete_guard BEFORE DELETE ON formation_event_members BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;

CREATE TRIGGER formation_closures_update_guard BEFORE UPDATE ON formation_closures BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;

CREATE TRIGGER formation_closures_delete_guard BEFORE DELETE ON formation_closures BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;

CREATE TRIGGER formation_closure_items_update_guard BEFORE UPDATE ON formation_closure_items BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;

CREATE TRIGGER formation_closure_items_delete_guard BEFORE DELETE ON formation_closure_items BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;

CREATE TRIGGER formation_closure_evidence_update_guard BEFORE UPDATE ON formation_closure_evidence BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;

CREATE TRIGGER formation_closure_evidence_delete_guard BEFORE DELETE ON formation_closure_evidence BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;

CREATE TRIGGER formation_artifact_reviews_update_guard BEFORE UPDATE ON formation_artifact_reviews BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;

CREATE TRIGGER formation_artifact_reviews_delete_guard BEFORE DELETE ON formation_artifact_reviews BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;

CREATE TRIGGER formation_artifact_results_update_guard BEFORE UPDATE ON formation_artifact_results BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;

CREATE TRIGGER formation_artifact_results_delete_guard BEFORE DELETE ON formation_artifact_results BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;

CREATE TRIGGER formation_artifacts_identity_guard BEFORE UPDATE ON formation_artifacts WHEN NEW.document_id IS NOT OLD.document_id OR NEW.artifact_ref IS NOT OLD.artifact_ref OR NEW.step_ref IS NOT OLD.step_ref OR NEW.source_event_id IS NOT OLD.source_event_id OR NEW.origin_revision_id IS NOT OLD.origin_revision_id OR NEW.origin_digest IS NOT OLD.origin_digest BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_IDENTITY'); END;

CREATE TRIGGER formation_proposal_index_identity_guard BEFORE UPDATE ON formation_proposal_index WHEN NEW.document_id IS NOT OLD.document_id OR NEW.message_id IS NOT OLD.message_id OR NEW.card_key IS NOT OLD.card_key OR NEW.purpose IS NOT OLD.purpose OR NEW.binding_json IS NOT OLD.binding_json OR NEW.payload_digest IS NOT OLD.payload_digest BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_IDENTITY'); END;

CREATE TRIGGER formation_branches_identity_guard BEFORE UPDATE ON formation_branches WHEN NEW.document_id IS NOT OLD.document_id OR NEW.branch_ref IS NOT OLD.branch_ref OR NEW.origin_step_ref IS NOT OLD.origin_step_ref OR NEW.origin_event_id IS NOT OLD.origin_event_id BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_IDENTITY'); END;

CREATE TRIGGER formation_steps_identity_guard BEFORE UPDATE ON formation_steps WHEN NEW.document_id IS NOT OLD.document_id OR NEW.step_ref IS NOT OLD.step_ref BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_IDENTITY'); END;

CREATE TRIGGER formation_artifact_ranges_identity_guard BEFORE UPDATE ON formation_artifact_ranges WHEN NEW.document_id IS NOT OLD.document_id OR NEW.artifact_ref IS NOT OLD.artifact_ref OR NEW.role IS NOT OLD.role OR NEW.ordinal IS NOT OLD.ordinal BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_IDENTITY'); END;

CREATE TRIGGER formation_results_identity_guard BEFORE UPDATE ON formation_results WHEN NEW.document_id IS NOT OLD.document_id OR NEW.step_ref IS NOT OLD.step_ref OR NEW.result_ref IS NOT OLD.result_ref OR NEW.kind IS NOT OLD.kind BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_IDENTITY'); END;

CREATE TRIGGER formation_artifact_result_owner BEFORE INSERT ON formation_artifact_results WHEN NOT EXISTS(SELECT 1 FROM formation_artifacts a JOIN formation_results r ON r.document_id=a.document_id AND r.step_ref=a.step_ref WHERE a.document_id=NEW.document_id AND a.artifact_ref=NEW.artifact_ref AND r.result_ref=NEW.result_ref) BEGIN SELECT RAISE(ABORT,'FORMATION_RESULT_OWNER_MISMATCH'); END;

CREATE TRIGGER formation_head_current_guard BEFORE INSERT ON formation_heads WHEN NOT EXISTS(SELECT 1 FROM requirement_documents WHERE id=NEW.document_id AND document_type='CURRENT') BEGIN SELECT RAISE(ABORT,'FORMATION_REQUIRES_CURRENT_DOCUMENT'); END;

CREATE TRIGGER formation_origin_range_update_guard BEFORE UPDATE ON formation_artifact_ranges WHEN OLD.role='ORIGIN' BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_ORIGIN'); END;

CREATE TRIGGER formation_origin_range_delete_guard BEFORE DELETE ON formation_artifact_ranges WHEN OLD.role='ORIGIN' BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_ORIGIN'); END;
