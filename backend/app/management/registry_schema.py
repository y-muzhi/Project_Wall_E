"""Independent SQLite structure for the host management registry."""

SCHEMA_VERSION = 1

STATEMENTS = (
    """CREATE TABLE manager_state(
        singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
        schema_version INTEGER NOT NULL CHECK(schema_version = 1),
        manager_id TEXT NOT NULL,
        host_id TEXT NOT NULL,
        registry_generation TEXT NOT NULL,
        initialized_at TEXT NOT NULL,
        UNIQUE(registry_generation)
    ) STRICT""",
    """CREATE TABLE managed_environments(
        environment_id TEXT PRIMARY KEY,
        purpose TEXT NOT NULL CHECK(purpose IN ('DEVELOPMENT', 'INTEGRATION', 'CANDIDATE', 'PRODUCTION')),
        display_name TEXT NOT NULL,
        host_id TEXT NOT NULL,
        record_version INTEGER NOT NULL CHECK(record_version BETWEEN 1 AND 9007199254740991),
        assignment_generation INTEGER NOT NULL CHECK(assignment_generation BETWEEN 1 AND 9007199254740991),
        registration_state TEXT NOT NULL CHECK(registration_state IN ('ACTIVE', 'ARCHIVED')),
        preparation_state TEXT NOT NULL CHECK(preparation_state IN ('PREPARING', 'PREPARED', 'INCOMPLETE')),
        configuration_sha256 TEXT,
        configuration_ref TEXT,
        program_source TEXT,
        profile_ref TEXT NOT NULL,
        task_id TEXT NOT NULL UNIQUE,
        work_package_json TEXT NOT NULL CHECK(json_valid(work_package_json)),
        writer_principal TEXT NOT NULL,
        assignment_control_state TEXT NOT NULL CHECK(assignment_control_state IN ('OPEN', 'FENCED')),
        fence_operation_id TEXT,
        CHECK((assignment_control_state = 'FENCED') = (fence_operation_id IS NOT NULL)),
        FOREIGN KEY(fence_operation_id) REFERENCES management_operations(operation_id) DEFERRABLE INITIALLY DEFERRED
    ) STRICT, WITHOUT ROWID""",
    """CREATE TABLE management_operations(
        operation_id TEXT PRIMARY KEY,
        registry_generation TEXT NOT NULL REFERENCES manager_state(registry_generation),
        request_key TEXT NOT NULL,
        principal TEXT NOT NULL,
        original_read_allowed INTEGER NOT NULL CHECK(original_read_allowed IN (0, 1)),
        action TEXT NOT NULL CHECK(action IN ('CREATE', 'ATTACH', 'START', 'STOP', 'HANDOFF',
            'REGISTER_DELIVERY', 'ARCHIVE', 'CLEANUP', 'RELEASE', 'RECONFIGURE', 'BACKUP', 'RESTORE', 'ROLLBACK_CODE')),
        environment_id TEXT NOT NULL REFERENCES managed_environments(environment_id) \
DEFERRABLE INITIALLY DEFERRED,
        expected_record_version INTEGER CHECK(expected_record_version BETWEEN 1 AND 9007199254740991),
        expected_assignment_generation INTEGER CHECK(expected_assignment_generation BETWEEN 1 AND 9007199254740991),
        intent_version INTEGER NOT NULL CHECK(intent_version = 1),
        intent_sha256 TEXT NOT NULL,
        intent_json TEXT NOT NULL CHECK(json_valid(intent_json)),
        status TEXT NOT NULL CHECK(status IN ('WAITING_CAPACITY', 'ACCEPTED', 'RUNNING',
            'SUCCEEDED', 'FAILED', 'CANCELLED', 'UNKNOWN')),
        revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 9007199254740991),
        cancel_requested INTEGER NOT NULL CHECK(cancel_requested IN (0, 1)),
        created_at TEXT NOT NULL,
        UNIQUE(registry_generation, request_key),
        UNIQUE(operation_id, registry_generation)
    ) STRICT, WITHOUT ROWID""",
    """CREATE TABLE management_controls(
        registry_generation TEXT NOT NULL,
        control_key TEXT NOT NULL,
        operation_id TEXT NOT NULL,
        principal TEXT NOT NULL,
        command TEXT NOT NULL CHECK(command IN ('CONTINUE', 'CANCEL', 'RECONCILE')),
        intent_sha256 TEXT NOT NULL,
        receipt_json TEXT NOT NULL CHECK(json_valid(receipt_json)),
        PRIMARY KEY(registry_generation, control_key),
        FOREIGN KEY(operation_id, registry_generation) REFERENCES management_operations(operation_id, registry_generation)
    ) STRICT, WITHOUT ROWID""",
    """CREATE TABLE management_steps(
        operation_id TEXT NOT NULL REFERENCES management_operations(operation_id),
        ordinal INTEGER NOT NULL CHECK(ordinal >= 1),
        step_kind TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('PLANNED', 'DISPATCHING', \
'SUCCEEDED', 'FAILED', 'UNKNOWN', 'SKIPPED')),
        executor_ref TEXT,
        external_identity_json TEXT CHECK(json_valid(external_identity_json)),
        result_json TEXT CHECK(json_valid(result_json)),
        CHECK(status NOT IN ('DISPATCHING','UNKNOWN') OR (executor_ref IS NOT NULL AND \
external_identity_json IS NOT NULL)),
        PRIMARY KEY(operation_id, ordinal)
    ) STRICT, WITHOUT ROWID""",
    """CREATE TABLE resource_claims(
        resource_id TEXT PRIMARY KEY,
        environment_id TEXT NOT NULL REFERENCES managed_environments(environment_id),
        operation_id TEXT NOT NULL REFERENCES management_operations(operation_id),
        kind TEXT NOT NULL,
        scope_ref TEXT NOT NULL,
        locator TEXT NOT NULL,
        identity_json TEXT CHECK(json_valid(identity_json)),
        quota INTEGER CHECK(quota > 0),
        released_at TEXT,
        release_json TEXT CHECK(json_valid(release_json)),
        CHECK((released_at IS NULL) = (release_json IS NULL))
    ) STRICT, WITHOUT ROWID""",
    """CREATE UNIQUE INDEX exclusive_resource_claim
        ON resource_claims(kind, scope_ref, locator) WHERE released_at IS NULL AND quota IS NULL""",
    """CREATE TABLE management_plans(
        plan_id TEXT PRIMARY KEY,
        environment_id TEXT NOT NULL REFERENCES managed_environments(environment_id),
        principal TEXT NOT NULL,
        kind TEXT NOT NULL,
        record_version INTEGER NOT NULL CHECK(record_version BETWEEN 1 AND 9007199254740991),
        assignment_generation INTEGER NOT NULL CHECK(assignment_generation BETWEEN 1 AND 9007199254740991),
        plan_sha256 TEXT NOT NULL,
        preview_json TEXT NOT NULL CHECK(json_valid(preview_json)),
        expires_at TEXT NOT NULL,
        execution_operation_id TEXT UNIQUE REFERENCES management_operations(operation_id)
    ) STRICT, WITHOUT ROWID""",
    """CREATE TABLE environment_observations(
        environment_id TEXT NOT NULL REFERENCES managed_environments(environment_id),
        source TEXT NOT NULL CHECK(source IN ('HOST', 'APPLICATION')),
        manager_run_id TEXT NOT NULL,
        observation_seq INTEGER NOT NULL CHECK(observation_seq BETWEEN 1 AND 9007199254740991),
        run_id TEXT,
        observed_at TEXT NOT NULL,
        last_success_at TEXT,
        freshness TEXT NOT NULL CHECK(freshness IN ('FRESH', 'STALE', 'UNAVAILABLE')),
        runtime_state TEXT NOT NULL CHECK(runtime_state IN ('RUNNING', 'STOPPED', 'UNKNOWN')),
        facts_json TEXT NOT NULL CHECK(json_valid(facts_json)),
        PRIMARY KEY(environment_id, source)
    ) STRICT, WITHOUT ROWID""",
    """CREATE TABLE delivery_snapshots(
        operation_id TEXT PRIMARY KEY REFERENCES management_operations(operation_id),
        environment_id TEXT NOT NULL REFERENCES managed_environments(environment_id),
        assignment_generation INTEGER NOT NULL CHECK(assignment_generation BETWEEN 1 AND 9007199254740991),
        commit_oid TEXT NOT NULL,
        evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
        submitted_by TEXT NOT NULL,
        verified_at TEXT NOT NULL
    ) STRICT, WITHOUT ROWID""",
)

RESTORED_SCHEMA_VERSION = 2

GENERATION_TABLE = """CREATE TABLE registry_generations(
    registry_generation TEXT PRIMARY KEY
) STRICT, WITHOUT ROWID"""

RESTORED_TABLES = (
    GENERATION_TABLE,
    *(
        statement.replace('CHECK(schema_version = 1)', 'CHECK(schema_version = 2)')
        .replace(
            'REFERENCES manager_state(registry_generation)',
            'REFERENCES registry_generations(registry_generation)',
        )
        .replace(
            'registry_generation TEXT NOT NULL,\n        initialized_at TEXT NOT NULL,',
            'registry_generation TEXT NOT NULL REFERENCES registry_generations(registry_generation),\n        initialized_at TEXT NOT NULL,',
        )
        for statement in STATEMENTS
    ),
)


def protect_history(table, scope):
    current = '(SELECT registry_generation FROM manager_state WHERE singleton = 1)'
    for event, rows in (('INSERT', ('NEW',)), ('UPDATE', ('OLD', 'NEW')), ('DELETE', ('OLD',))):
        checks = ' OR '.join(f'{scope.format(row=row)} IS NOT {current}' for row in rows)
        yield (
            f'CREATE TRIGGER immutable_{table}_{event.lower()} BEFORE {event} ON {table} '
            f"WHEN {checks} BEGIN SELECT RAISE(ABORT, 'MANAGEMENT_HISTORY_READ_ONLY'); END"
        )


HISTORY_PROTECTION = (
    *protect_history('management_operations', '{row}.registry_generation'),
    *protect_history('management_controls', '{row}.registry_generation'),
    *protect_history(
        'management_steps',
        '(SELECT registry_generation FROM management_operations WHERE operation_id = {row}.operation_id)',
    ),
    *protect_history(
        'delivery_snapshots',
        '(SELECT registry_generation FROM management_operations WHERE operation_id = {row}.operation_id)',
    ),
)

RECOVERY_RESOLUTION_SCHEMA_VERSION = 3
PRE_DISPATCH_SCHEMA_VERSION = 4
DEPLOYMENT_ADOPTION_SCHEMA_VERSION = 5
ROLLBACK_RECOVERY_SCHEMA_VERSION = 6
RECONFIGURATION_RECOVERY_SCHEMA_VERSION = 7
RELEASE_RETIREMENT_SCHEMA_VERSION = 8
OUTCOME_TABLE = 'registry_recovery_outcomes'
OUTCOME_STATEMENT = f"""CREATE TABLE {OUTCOME_TABLE}(
    operation_id TEXT PRIMARY KEY,
    source_registry_generation TEXT NOT NULL,
    recorded_registry_generation TEXT NOT NULL REFERENCES registry_generations(registry_generation),
    source_revision INTEGER NOT NULL CHECK(source_revision BETWEEN 1 AND 9007199254740991),
    source_intent_sha256 TEXT NOT NULL CHECK(length(source_intent_sha256) = 64),
    source_snapshot_sha256 TEXT NOT NULL CHECK(length(source_snapshot_sha256) = 64),
    policy_sha256 TEXT NOT NULL CHECK(length(policy_sha256) = 64),
    evidence_sha256 TEXT NOT NULL CHECK(length(evidence_sha256) = 64),
    disposition TEXT NOT NULL CHECK(disposition IN ('UNDISPATCHED_CANCELLED', \
'UNDISPATCHED_RESERVED_CANCELLED', 'BACKUP_COMPLETED', \
'STOP_COMPLETED', 'RESTORE_RETIRED')),
    recorded_at TEXT NOT NULL,
    FOREIGN KEY(operation_id, source_registry_generation)
        REFERENCES management_operations(operation_id, registry_generation),
    CHECK(source_registry_generation != recorded_registry_generation)
) STRICT, WITHOUT ROWID"""

RESOLUTION_TABLES = (
    *(
        statement.replace('CHECK(schema_version = 2)', 'CHECK(schema_version = 3)')
        for statement in RESTORED_TABLES
    ),
    OUTCOME_STATEMENT,
)

OUTCOME_PROTECTION = (
    f"""CREATE TRIGGER recovery_outcome_bound BEFORE INSERT ON {OUTCOME_TABLE}
    WHEN NEW.recorded_registry_generation IS NOT
            (SELECT registry_generation FROM manager_state WHERE singleton = 1)
        OR NOT EXISTS (
            SELECT 1 FROM management_operations WHERE operation_id = NEW.operation_id
            AND registry_generation = NEW.source_registry_generation
            AND revision = NEW.source_revision AND intent_sha256 = NEW.source_intent_sha256
            AND ((NEW.disposition = 'UNDISPATCHED_CANCELLED' AND action = 'START' AND status = 'WAITING_CAPACITY')
                OR (NEW.disposition = 'UNDISPATCHED_RESERVED_CANCELLED' AND action = 'START' \
AND status = 'ACCEPTED')
                OR (NEW.disposition = 'BACKUP_COMPLETED' AND action = 'BACKUP' \
AND status IN ('RUNNING','UNKNOWN','SUCCEEDED'))
                OR (NEW.disposition = 'STOP_COMPLETED' AND action = 'STOP' AND status IN ('ACCEPTED','UNKNOWN','SUCCEEDED'))
                OR (NEW.disposition = 'RESTORE_RETIRED' AND action = 'RESTORE' AND status IN ('RUNNING','CANCELLED')))
        )
    BEGIN SELECT RAISE(ABORT, 'MANAGEMENT_RECOVERY_OUTCOME_UNBOUND'); END""",
    *(
        f'CREATE TRIGGER immutable_recovery_outcome_{event.lower()} BEFORE {event} ON {OUTCOME_TABLE} '
        "BEGIN SELECT RAISE(ABORT, 'MANAGEMENT_RECOVERY_OUTCOME_READ_ONLY'); END"
        for event in ('UPDATE', 'DELETE')
    ),
)

PRE_DISPATCH_TABLES = (
    *(
        statement.replace('CHECK(schema_version = 3)', 'CHECK(schema_version = 4)')
        for statement in RESOLUTION_TABLES[:-1]
    ),
    OUTCOME_STATEMENT.replace(
        "'STOP_COMPLETED', 'RESTORE_RETIRED'))",
        "'STOP_COMPLETED', 'RESTORE_RETIRED', 'UNSTARTED_OPERATION_CANCELLED'))",
    ),
)

PRE_DISPATCH_PROTECTION = (
    OUTCOME_PROTECTION[0].replace(
        "OR (NEW.disposition = 'RESTORE_RETIRED'",
        "OR (NEW.disposition = 'UNSTARTED_OPERATION_CANCELLED' "
        "AND action IN ('ARCHIVE','RELEASE','BACKUP','RESTORE') AND status = 'ACCEPTED')\n"
        "                OR (NEW.disposition = 'RESTORE_RETIRED'",
    ),
    *OUTCOME_PROTECTION[1:],
)

DEPLOYMENT_ADOPTION_TABLES = (
    *(
        statement.replace('CHECK(schema_version = 4)', 'CHECK(schema_version = 5)')
        for statement in PRE_DISPATCH_TABLES[:-1]
    ),
    PRE_DISPATCH_TABLES[-1].replace(
        "'UNSTARTED_OPERATION_CANCELLED'))",
        "'UNSTARTED_OPERATION_CANCELLED', 'OPENED_DEPLOYMENT_ADOPTED'))",
    ),
)

DEPLOYMENT_ADOPTION_PROTECTION = (
    PRE_DISPATCH_PROTECTION[0].replace(
        "OR (NEW.disposition = 'RESTORE_RETIRED'",
        "OR (NEW.disposition = 'OPENED_DEPLOYMENT_ADOPTED' "
        "AND action IN ('RELEASE','RESTORE') AND status = 'RUNNING' AND cancel_requested = 0)\n"
        "                OR (NEW.disposition = 'RESTORE_RETIRED'",
    ),
    *PRE_DISPATCH_PROTECTION[1:],
)

ROLLBACK_RECOVERY_TABLES = (
    *(
        statement.replace('CHECK(schema_version = 5)', 'CHECK(schema_version = 6)')
        for statement in DEPLOYMENT_ADOPTION_TABLES[:-1]
    ),
    DEPLOYMENT_ADOPTION_TABLES[-1],
)

ROLLBACK_RECOVERY_PROTECTION = (
    DEPLOYMENT_ADOPTION_PROTECTION[0]
    .replace(
        "action IN ('ARCHIVE','RELEASE','BACKUP','RESTORE')",
        "action IN ('ARCHIVE','RELEASE','ROLLBACK_CODE','BACKUP','RESTORE')",
    )
    .replace(
        "action IN ('RELEASE','RESTORE') AND status = 'RUNNING'",
        "action IN ('RELEASE','ROLLBACK_CODE','RESTORE') AND status = 'RUNNING'",
    ),
    *DEPLOYMENT_ADOPTION_PROTECTION[1:],
)

RECONFIGURATION_RECOVERY_TABLES = (
    *(
        statement.replace('CHECK(schema_version = 6)', 'CHECK(schema_version = 7)')
        for statement in ROLLBACK_RECOVERY_TABLES[:-1]
    ),
    ROLLBACK_RECOVERY_TABLES[-1],
)

RECONFIGURATION_RECOVERY_PROTECTION = (
    ROLLBACK_RECOVERY_PROTECTION[0]
    .replace(
        "action IN ('ARCHIVE','RELEASE','ROLLBACK_CODE','BACKUP','RESTORE')",
        "action IN ('ARCHIVE','RELEASE','ROLLBACK_CODE','RECONFIGURE','BACKUP','RESTORE')",
    )
    .replace(
        "action IN ('RELEASE','ROLLBACK_CODE','RESTORE') AND status = 'RUNNING'",
        "action IN ('RELEASE','ROLLBACK_CODE','RECONFIGURE','RESTORE') AND status = 'RUNNING'",
    ),
    *ROLLBACK_RECOVERY_PROTECTION[1:],
)

RELEASE_RETIREMENT_TABLES = (
    *(
        statement.replace('CHECK(schema_version = 7)', 'CHECK(schema_version = 8)')
        for statement in RECONFIGURATION_RECOVERY_TABLES[:-1]
    ),
    RECONFIGURATION_RECOVERY_TABLES[-1].replace(
        "'OPENED_DEPLOYMENT_ADOPTED'))",
        "'OPENED_DEPLOYMENT_ADOPTED', 'RELEASE_RETIRED'))",
    ),
)

RELEASE_RETIREMENT_PROTECTION = (
    RECONFIGURATION_RECOVERY_PROTECTION[0].replace(
        "OR (NEW.disposition = 'RESTORE_RETIRED'",
        "OR (NEW.disposition = 'RELEASE_RETIRED' "
        "AND action IN ('RELEASE','ROLLBACK_CODE','RECONFIGURE') "
        "AND ((status = 'RUNNING' AND cancel_requested = 0) OR (status = 'CANCELLED' AND cancel_requested = 1)))\n"
        "                OR (NEW.disposition = 'RESTORE_RETIRED'",
    ),
    *RECONFIGURATION_RECOVERY_PROTECTION[1:],
)

RECOVERY_TABLES = {
    RESTORED_SCHEMA_VERSION: RESTORED_TABLES,
    RECOVERY_RESOLUTION_SCHEMA_VERSION: RESOLUTION_TABLES,
    PRE_DISPATCH_SCHEMA_VERSION: PRE_DISPATCH_TABLES,
    DEPLOYMENT_ADOPTION_SCHEMA_VERSION: DEPLOYMENT_ADOPTION_TABLES,
    ROLLBACK_RECOVERY_SCHEMA_VERSION: ROLLBACK_RECOVERY_TABLES,
    RECONFIGURATION_RECOVERY_SCHEMA_VERSION: RECONFIGURATION_RECOVERY_TABLES,
    RELEASE_RETIREMENT_SCHEMA_VERSION: RELEASE_RETIREMENT_TABLES,
}

RECOVERY_TRIGGERS = {
    RESTORED_SCHEMA_VERSION: HISTORY_PROTECTION,
    RECOVERY_RESOLUTION_SCHEMA_VERSION: (*HISTORY_PROTECTION, *OUTCOME_PROTECTION),
    PRE_DISPATCH_SCHEMA_VERSION: (*HISTORY_PROTECTION, *PRE_DISPATCH_PROTECTION),
    DEPLOYMENT_ADOPTION_SCHEMA_VERSION: (*HISTORY_PROTECTION, *DEPLOYMENT_ADOPTION_PROTECTION),
    ROLLBACK_RECOVERY_SCHEMA_VERSION: (*HISTORY_PROTECTION, *ROLLBACK_RECOVERY_PROTECTION),
    RECONFIGURATION_RECOVERY_SCHEMA_VERSION: (
        *HISTORY_PROTECTION,
        *RECONFIGURATION_RECOVERY_PROTECTION,
    ),
    RELEASE_RETIREMENT_SCHEMA_VERSION: (*HISTORY_PROTECTION, *RELEASE_RETIREMENT_PROTECTION),
}

SCHEMAS = {
    SCHEMA_VERSION: STATEMENTS,
    **{
        version: (*tables, *RECOVERY_TRIGGERS[version])
        for version, tables in RECOVERY_TABLES.items()
    },
}
