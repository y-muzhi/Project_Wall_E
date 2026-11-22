"""Store a recovery disposition separately from its immutable original operation."""

from backend.app.infrastructure.environment_files import require

from .registry import registry_version
from .registry_schema import OUTCOME_TABLE, RECOVERY_RESOLUTION_SCHEMA_VERSION

UNVERIFIED = 'MANAGEMENT_REGISTRY_RECOVERY_DISPOSITION_UNVERIFIED'
UNDISPATCHED = 'UNDISPATCHED_CANCELLED'
BACKUP_COMPLETED = 'BACKUP_COMPLETED'
ORIGINAL_STATES = {
    UNDISPATCHED: ('START', ('WAITING_CAPACITY',)),
    BACKUP_COMPLETED: ('BACKUP', ('RUNNING', 'UNKNOWN', 'SUCCEEDED')),
}
COLUMNS = (
    'operation_id',
    'source_registry_generation',
    'recorded_registry_generation',
    'source_revision',
    'source_intent_sha256',
    'source_snapshot_sha256',
    'policy_sha256',
    'evidence_sha256',
    'disposition',
    'recorded_at',
)


def matching_original(disposition, action, status):
    expected = ORIGINAL_STATES.get(disposition) if type(disposition) is str else None
    return expected is not None and expected[0] == action and status in expected[1]


def pending_step_clause(connection):
    observed = (
        "(step.external_identity_json IS NOT NULL OR step.status IN ('DISPATCHING','UNKNOWN'))"
    )
    if registry_version(connection) >= RECOVERY_RESOLUTION_SCHEMA_VERSION:
        observed += (
            f' AND NOT EXISTS (SELECT 1 FROM {OUTCOME_TABLE} AS outcome WHERE outcome.operation_id = step.operation_id '
            "AND outcome.disposition = 'BACKUP_COMPLETED' AND step.ordinal = 1 AND step.step_kind = 'BACKUP_RECOVERY_POINT')"
        )
    return observed


def pending_operation_clause(connection, *, include_completed_backups=False):
    pending = "op.status IN ('WAITING_CAPACITY','ACCEPTED','RUNNING','UNKNOWN')"
    if include_completed_backups:
        pending = f"({pending} OR (op.action='BACKUP' AND op.status='SUCCEEDED'))"
    if registry_version(connection) >= RECOVERY_RESOLUTION_SCHEMA_VERSION:
        pending += f' AND NOT EXISTS (SELECT 1 FROM {OUTCOME_TABLE} AS outcome WHERE outcome.operation_id = op.operation_id)'
    return pending


def outcome_for_operation(connection, operation_id):
    if registry_version(connection) < RECOVERY_RESOLUTION_SCHEMA_VERSION:
        return None
    row = connection.execute(
        f'SELECT * FROM {OUTCOME_TABLE} WHERE operation_id=?', (operation_id,)
    ).fetchone()
    return None if row is None else dict(zip(COLUMNS, row, strict=True))


def add_outcome(connection, outcome):
    require(registry_version(connection) == RECOVERY_RESOLUTION_SCHEMA_VERSION, UNVERIFIED)
    placeholders = ','.join('?' for _ in COLUMNS)
    inserted = connection.execute(
        f'INSERT INTO {OUTCOME_TABLE} ({",".join(COLUMNS)}) VALUES ({placeholders})',
        tuple(outcome[column] for column in COLUMNS),
    )
    require(inserted.rowcount == 1, UNVERIFIED)
