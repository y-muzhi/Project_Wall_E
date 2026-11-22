"""V2.2 additions to the frozen Schema200 structure for fresh environments."""

from .database import SchemaMismatch, _statements
from .schema_v20_assembly import fresh_sql as base_fresh_sql

ENVIRONMENT_BINDING = """CREATE TABLE environment_binding (
    singleton_id INTEGER NOT NULL PRIMARY KEY CHECK (singleton_id = 1),
    environment_id TEXT NOT NULL CHECK (
        length(environment_id) = 36
        AND length(CAST(environment_id AS BLOB)) = 36
        AND substr(environment_id, 9, 1) = '-'
        AND substr(environment_id, 14, 1) = '-'
        AND substr(environment_id, 19, 1) = '-'
        AND substr(environment_id, 24, 1) = '-'
        AND length(replace(environment_id, '-', '')) = 32
        AND replace(environment_id, '-', '') NOT GLOB '*[^0-9a-f]*'
        AND substr(environment_id, 15, 1) = '4'
        AND substr(environment_id, 20, 1) IN ('8', '9', 'a', 'b')
    ),
    data_generation TEXT NOT NULL CHECK (
        length(data_generation) = 36
        AND length(CAST(data_generation AS BLOB)) = 36
        AND substr(data_generation, 9, 1) = '-'
        AND substr(data_generation, 14, 1) = '-'
        AND substr(data_generation, 19, 1) = '-'
        AND substr(data_generation, 24, 1) = '-'
        AND length(replace(data_generation, '-', '')) = 32
        AND replace(data_generation, '-', '') NOT GLOB '*[^0-9a-f]*'
        AND substr(data_generation, 15, 1) = '4'
        AND substr(data_generation, 20, 1) IN ('8', '9', 'a', 'b')
    ),
    initialized_at TEXT NOT NULL CHECK (
        length(initialized_at) = 24
        AND initialized_at GLOB
            '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z'
    )
) STRICT, WITHOUT ROWID;
"""

CODE_SNAPSHOTS = """CREATE TABLE "code_snapshots" (
  "id" INTEGER NOT NULL CHECK("id" BETWEEN 1 AND 9007199254740991),
  "repository_id" INTEGER NOT NULL CHECK("repository_id" BETWEEN 1 AND 9007199254740991),
  "registration_operation_id" INTEGER NOT NULL CHECK("registration_operation_id" BETWEEN 1 AND 9007199254740991),
  "content_profile_version_id" INTEGER NOT NULL CHECK("content_profile_version_id" BETWEEN 1 AND 9007199254740991),
  "commit_oid" TEXT NOT NULL CHECK(length("commit_oid") IN (40,64) AND "commit_oid" NOT GLOB '*[^0-9a-f]*'),
  "content_tree_oid" TEXT NOT NULL CHECK(length("content_tree_oid") IN (40,64) AND "content_tree_oid" NOT GLOB '*[^0-9a-f]*'),
  "origin_environment_id" TEXT NOT NULL CHECK (
    length("origin_environment_id")=36 AND length(CAST("origin_environment_id" AS BLOB))=36
    AND substr("origin_environment_id",9,1)='-' AND substr("origin_environment_id",14,1)='-'
    AND substr("origin_environment_id",19,1)='-' AND substr("origin_environment_id",24,1)='-'
    AND length(replace("origin_environment_id",'-',''))=32
    AND replace("origin_environment_id",'-','') NOT GLOB '*[^0-9a-f]*'
    AND substr("origin_environment_id",15,1)='4'
    AND substr("origin_environment_id",20,1) IN ('8','9','a','b')
  ),
  "origin_data_generation" TEXT NOT NULL CHECK (
    length("origin_data_generation")=36 AND length(CAST("origin_data_generation" AS BLOB))=36
    AND substr("origin_data_generation",9,1)='-' AND substr("origin_data_generation",14,1)='-'
    AND substr("origin_data_generation",19,1)='-' AND substr("origin_data_generation",24,1)='-'
    AND length(replace("origin_data_generation",'-',''))=32
    AND replace("origin_data_generation",'-','') NOT GLOB '*[^0-9a-f]*'
    AND substr("origin_data_generation",15,1)='4'
    AND substr("origin_data_generation",20,1) IN ('8','9','a','b')
  ),
  "retention_ref" TEXT NOT NULL CHECK(length("retention_ref")>0),
  "content_policy_version" TEXT NOT NULL CHECK("content_policy_version"='GIT201-BASELINE-1'),
  "registered_at" TEXT NOT NULL CHECK(length("registered_at")=24 AND "registered_at" GLOB '????-??-??T??:??:??.???Z'),
  "created_at" TEXT NOT NULL CHECK(length("created_at")=24 AND "created_at" GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY("id"),
  UNIQUE(registration_operation_id),
  UNIQUE(repository_id,retention_ref),
  UNIQUE(id,repository_id),
  FOREIGN KEY("registration_operation_id") REFERENCES "code_operations"("id") DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY("repository_id") REFERENCES "code_repositories"("id") DEFERRABLE INITIALLY DEFERRED,
  CHECK((retention_ref='refs/walle/baselines/'||origin_environment_id||'/'||origin_data_generation||'/'||id) IS TRUE),
  CHECK((created_at>=registered_at) IS TRUE)
) STRICT;
"""

SNAPSHOT_TRIGGERS = """CREATE TRIGGER "code_snapshots_identity_fixed" BEFORE UPDATE ON "code_snapshots"
WHEN NEW."origin_environment_id" IS NOT OLD."origin_environment_id"
  OR NEW."origin_data_generation" IS NOT OLD."origin_data_generation"
  OR NEW."commit_oid" IS NOT OLD."commit_oid" OR NEW."content_policy_version" IS NOT OLD."content_policy_version" OR NEW."content_profile_version_id" IS NOT OLD."content_profile_version_id" OR NEW."content_tree_oid" IS NOT OLD."content_tree_oid" OR NEW."created_at" IS NOT OLD."created_at" OR NEW."id" IS NOT OLD."id" OR NEW."registered_at" IS NOT OLD."registered_at" OR NEW."registration_operation_id" IS NOT OLD."registration_operation_id" OR NEW."repository_id" IS NOT OLD."repository_id" OR NEW."retention_ref" IS NOT OLD."retention_ref"
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD_INPUT'); END;

CREATE TRIGGER code_snapshots_origin_guard_insert
BEFORE INSERT ON code_snapshots
WHEN NOT EXISTS (
    SELECT 1 FROM code_operations o
    WHERE o.id=NEW.registration_operation_id
      AND o.resource_kind='REPOSITORY' AND o.resource_id=NEW.repository_id
      AND o.operation_type='REGISTER_BASE'
      AND json_extract(o.fixed_input,'$.snapshot_id')=NEW.id
      AND json_extract(o.fixed_input,'$.origin_environment_id')=NEW.origin_environment_id
      AND json_extract(o.fixed_input,'$.origin_data_generation')=NEW.origin_data_generation
      AND json_extract(o.fixed_input,'$.retention_ref')=NEW.retention_ref
      AND json_extract(o.fixed_input,'$.commit_oid')=NEW.commit_oid
      AND json_extract(o.fixed_input,'$.execution_profile_version_id')=NEW.content_profile_version_id
)
BEGIN
    SELECT RAISE(ABORT,'SNAPSHOT_ORIGIN_MISMATCH');
END;
"""


def fresh_sql() -> str:
    """Retain every original statement except the two explicitly updated objects."""
    replacements = {
        'CREATE TABLE "code_snapshots" (': CODE_SNAPSHOTS,
        'CREATE TRIGGER "code_snapshots_identity_fixed" BEFORE': SNAPSHOT_TRIGGERS,
    }
    found = set()
    statements = []
    for original in _statements(base_fresh_sql()):
        statement = original.lstrip()
        for prefix, replacement in replacements.items():
            if statement.startswith(prefix):
                if prefix in found:
                    raise SchemaMismatch('Duplicate V2.2 Schema construction target')
                found.add(prefix)
                statements.append(replacement)
                break
        else:
            statements.append(original)
    if found != replacements.keys():
        raise SchemaMismatch('Missing V2.2 Schema construction target')
    return '\n'.join((*statements, ENVIRONMENT_BINDING))
