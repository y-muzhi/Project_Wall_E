"""Store a recovery disposition separately from its immutable original operation."""

from backend.app.infrastructure.environment_files import require

from .operation_contract import RECONFIGURE, RELEASE_ACTIONS, ROLLBACK_CODE
from .registry import registry_version
from .registry_schema import (
    DEPLOYMENT_ADOPTION_SCHEMA_VERSION,
    OUTCOME_TABLE,
    PRE_DISPATCH_SCHEMA_VERSION,
    RECONFIGURATION_RECOVERY_SCHEMA_VERSION,
    RECOVERY_RESOLUTION_SCHEMA_VERSION,
    RELEASE_RETIREMENT_SCHEMA_VERSION,
    ROLLBACK_RECOVERY_SCHEMA_VERSION,
)

UNVERIFIED = 'MANAGEMENT_REGISTRY_RECOVERY_DISPOSITION_UNVERIFIED'
UNDISPATCHED = 'UNDISPATCHED_CANCELLED'
RESERVED_START = 'UNDISPATCHED_RESERVED_CANCELLED'
BACKUP_COMPLETED = 'BACKUP_COMPLETED'
STOP_COMPLETED = 'STOP_COMPLETED'
RESTORE_RETIRED = 'RESTORE_RETIRED'
RELEASE_RETIRED = 'RELEASE_RETIRED'
OPENED_DEPLOYMENT = 'OPENED_DEPLOYMENT_ADOPTED'
UNSTARTED_OPERATION = 'UNSTARTED_OPERATION_CANCELLED'
UNSTARTED_STEPS = {
    'ARCHIVE': 'ENVIRONMENT_ARCHIVED',
    **dict.fromkeys(RELEASE_ACTIONS, 'RELEASE_DEPLOYMENT'),
    'BACKUP': 'BACKUP_RECOVERY_POINT',
    'RESTORE': 'RESTORE_ENVIRONMENT',
}
EFFECT_DISPOSITIONS = (BACKUP_COMPLETED, STOP_COMPLETED, RESTORE_RETIRED, RELEASE_RETIRED)
ORIGINAL_STATES = {
    UNSTARTED_OPERATION: (tuple(UNSTARTED_STEPS), ('ACCEPTED',)),
    UNDISPATCHED: (('START',), ('WAITING_CAPACITY',)),
    RESERVED_START: (('START',), ('ACCEPTED',)),
    BACKUP_COMPLETED: (('BACKUP',), ('RUNNING', 'UNKNOWN', 'SUCCEEDED')),
    STOP_COMPLETED: (('STOP',), ('ACCEPTED', 'UNKNOWN', 'SUCCEEDED')),
    RESTORE_RETIRED: (('RESTORE',), ('RUNNING', 'CANCELLED')),
    RELEASE_RETIRED: (RELEASE_ACTIONS, ('RUNNING', 'CANCELLED')),
    OPENED_DEPLOYMENT: ((*RELEASE_ACTIONS, 'RESTORE'), ('RUNNING',)),
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
    return expected is not None and action in expected[0] and status in expected[1]


def pending_step_clause(connection):
    observed = (
        "(step.external_identity_json IS NOT NULL OR step.status IN ('DISPATCHING','UNKNOWN') "
        "OR (op.action='STOP' AND op.status='ACCEPTED' AND step.ordinal=1 "
        "AND step.step_kind='RUNTIME_STOPPED'))"
    )
    if registry_version(connection) >= RECOVERY_RESOLUTION_SCHEMA_VERSION:
        observed += (
            f' AND NOT EXISTS (SELECT 1 FROM {OUTCOME_TABLE} AS outcome '
            'WHERE outcome.operation_id = step.operation_id '
            "AND step.ordinal = 1 AND ((outcome.disposition = 'BACKUP_COMPLETED' "
            "AND step.step_kind = 'BACKUP_RECOVERY_POINT') "
            "OR (outcome.disposition = 'STOP_COMPLETED' AND step.step_kind = 'RUNTIME_STOPPED') "
            "OR (outcome.disposition = 'RESTORE_RETIRED' "
            "AND step.step_kind = 'RESTORE_ENVIRONMENT') "
            "OR (outcome.disposition = 'RELEASE_RETIRED' "
            "AND step.step_kind = 'RELEASE_DEPLOYMENT') "
            "OR (outcome.disposition = 'OPENED_DEPLOYMENT_ADOPTED' "
            "AND step.step_kind IN ('RELEASE_DEPLOYMENT', 'RESTORE_ENVIRONMENT'))))"
        )
    return observed


def pending_operation_clause(connection, *, include_completed_effects=False):
    pending = "op.status IN ('WAITING_CAPACITY','ACCEPTED','RUNNING','UNKNOWN')"
    if include_completed_effects:
        pending = (
            f"({pending} OR (op.action IN ('BACKUP','STOP') AND op.status='SUCCEEDED') "
            "OR (op.action IN ('RESTORE','RELEASE','ROLLBACK_CODE','RECONFIGURE') "
            "AND op.status='CANCELLED' AND EXISTS ("
            'SELECT 1 FROM management_steps AS original_step '
            'WHERE original_step.operation_id = op.operation_id '
            "AND original_step.ordinal = 1 AND original_step.step_kind IN ('RESTORE_ENVIRONMENT','RELEASE_DEPLOYMENT') "
            'AND original_step.external_identity_json IS NOT NULL)))'
        )
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


def disposition_schema(disposition, *, action=None):
    if disposition == RELEASE_RETIRED:
        return RELEASE_RETIREMENT_SCHEMA_VERSION
    if disposition in (OPENED_DEPLOYMENT, UNSTARTED_OPERATION):
        if action == RECONFIGURE:
            return RECONFIGURATION_RECOVERY_SCHEMA_VERSION
        if action == ROLLBACK_CODE:
            return ROLLBACK_RECOVERY_SCHEMA_VERSION
    if disposition == OPENED_DEPLOYMENT:
        return DEPLOYMENT_ADOPTION_SCHEMA_VERSION
    return (
        PRE_DISPATCH_SCHEMA_VERSION
        if disposition == UNSTARTED_OPERATION
        else RECOVERY_RESOLUTION_SCHEMA_VERSION
    )


def add_outcome(connection, outcome):
    require(registry_version(connection) >= disposition_schema(outcome['disposition']), UNVERIFIED)
    placeholders = ','.join('?' for _ in COLUMNS)
    inserted = connection.execute(
        f'INSERT INTO {OUTCOME_TABLE} ({",".join(COLUMNS)}) VALUES ({placeholders})',
        tuple(outcome[column] for column in COLUMNS),
    )
    require(inserted.rowcount == 1, UNVERIFIED)
