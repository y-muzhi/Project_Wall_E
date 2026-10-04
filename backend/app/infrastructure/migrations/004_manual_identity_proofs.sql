-- D-009 approved 2026-10-04. Reject unknowable legacy allocation facts.
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

-- Approved D-009 migration 004; preserve adopted bytes.
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
