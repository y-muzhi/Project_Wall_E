-- D-003 invariant correction: SQLite CHECK allows UNKNOWN for NULL.
-- Preserve immutable migration 001; refuse corrupt legacy facts, never repair them.
CREATE TEMP TABLE idempotency_migration_check (valid INTEGER NOT NULL CHECK(valid=1));
INSERT INTO idempotency_migration_check
SELECT CASE WHEN EXISTS (
  SELECT 1 FROM idempotency_records WHERE status='SUCCEEDED' AND http_status IS NULL
) THEN 0 ELSE 1 END;
DROP TABLE idempotency_migration_check;

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
