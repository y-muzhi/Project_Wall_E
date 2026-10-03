-- D-008 approved 2026-10-03. Preserve legacy facts; never infer sessions.
CREATE TEMP TABLE manual_source_migration_check (valid INTEGER NOT NULL CHECK(valid=1));
INSERT INTO manual_source_migration_check SELECT CASE WHEN
  EXISTS (SELECT 1 FROM requirement_documents d, json_tree(d.block_state_json) j WHERE j.key IN ('created_source_type','last_modified_source_type') AND j.value='MANUAL_EDIT') OR
  EXISTS (SELECT 1 FROM revisions r, json_tree(r.block_state_snapshot_json) j WHERE j.key IN ('created_source_type','last_modified_source_type') AND j.value='MANUAL_EDIT') OR
  EXISTS (SELECT 1 FROM document_change_audits WHERE source_type='MANUAL_EDIT')
THEN 0 ELSE 1 END;
DROP TABLE manual_source_migration_check;

-- Approved D-008 migration 003; immutable after adoption.
-- Before adoption: refuse legacy MANUAL_EDIT references without proven sessions.
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
