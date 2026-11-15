"""Build complete SQL candidates; never execute or publish an upgrade implicitly."""

import re

from backend.app.code_tasks.command_registry import COMMAND_ROUTES

from .schema_v20 import create_table_sql
from .schema_v20_columns import COLUMNS
from .schema_v20_legacy import (
    copy_original_sql,
    frozen_statements,
    idempotency_table_sql,
    llm_table_sql,
)
from .schema_v20_relations import table_constraints
from .schema_v20_triggers import (
    defect_reference_triggers,
    immutable_triggers,
    legacy_guard_triggers,
    ownership_triggers,
    resource_operation_triggers,
    source_reference_triggers,
    step_registration_trigger,
    verification_handoff_triggers,
    waiting_source_triggers,
)

REBUILT = ('llm_uses', 'idempotency_records')


def command_capabilities() -> tuple[str, ...]:
    return tuple(route.capability_id for route in COMMAND_ROUTES)


def new_tables() -> tuple[str, ...]:
    return tuple(
        create_table_sql(table, table_constraints(table))
        for table in COLUMNS
        if table != 'llm_uses'
    )


def _indexes() -> tuple[str, ...]:
    return (
        "CREATE UNIQUE INDEX code_repository_registration_one_reserved_id ON code_operations(resource_id) WHERE resource_kind='REPOSITORY' AND operation_type='REGISTER_REPOSITORY';",
        'CREATE UNIQUE INDEX code_repository_observation_one_operation ON code_repository_observations(operation_id);',
        "CREATE UNIQUE INDEX code_tasks_one_active_document ON code_tasks(document_id) WHERE status NOT IN ('COMPLETED','TERMINATED');",
        "CREATE UNIQUE INDEX code_operations_one_code_stop ON code_operations(task_id) WHERE operation_type='TERMINATE' AND task_id IS NOT NULL;",
        "CREATE UNIQUE INDEX code_operations_one_test_stop ON code_operations(testing_task_id) WHERE operation_type='TERMINATE' AND testing_task_id IS NOT NULL;",
        "CREATE UNIQUE INDEX code_waiting_one_code_source ON code_waiting_items(task_id,kind,source_kind,source_id) WHERE status='OPEN' AND task_id IS NOT NULL;",
        "CREATE UNIQUE INDEX code_waiting_one_test_source ON code_waiting_items(testing_task_id,kind,source_kind,source_id) WHERE status='OPEN' AND testing_task_id IS NOT NULL;",
        "CREATE UNIQUE INDEX code_sessions_one_writer ON code_sessions(task_id,control_generation) WHERE status IN ('PREPARING','ACTIVE','QUIESCING','UNKNOWN');",
        'CREATE UNIQUE INDEX code_defects_one_testing_source ON code_defects(task_id,testing_finding_id) WHERE testing_finding_id IS NOT NULL;',
        'CREATE UNIQUE INDEX llm_one_gateway_request ON llm_uses(gateway_request_id) WHERE gateway_request_id IS NOT NULL;',
        'CREATE UNIQUE INDEX llm_one_code_call ON llm_uses(execution_session_id,call_no) WHERE execution_session_id IS NOT NULL;',
        'CREATE UNIQUE INDEX llm_one_testing_call ON llm_uses(testing_task_id,call_no) WHERE testing_task_id IS NOT NULL;',
    )


def _triggers() -> tuple[str, ...]:
    return (
        *immutable_triggers(),
        *legacy_guard_triggers(),
        *ownership_triggers(),
        *defect_reference_triggers(),
        *resource_operation_triggers(),
        *waiting_source_triggers(),
        *source_reference_triggers(),
        *verification_handoff_triggers(),
        step_registration_trigger(),
    )


def _table_name(statement: str) -> str | None:
    match = re.search(r'CREATE TABLE ([a-z_]+)\s*\(', statement)
    return match[1] if match else None


def _old_rebuilt_triggers() -> tuple[tuple[str, str], ...]:
    result = []
    for statement in frozen_statements():
        match = re.search(
            r'CREATE TRIGGER ([a-z_]+) BEFORE (?:INSERT|UPDATE|DELETE) ON ([a-z_]+)', statement
        )
        if match is not None and match[2] in REBUILT:
            result.append((match[1], statement))
    return tuple(result)


def fresh_sql() -> str:
    statements = []
    for statement in frozen_statements():
        table = _table_name(statement)
        if table == 'llm_uses':
            statements.append(llm_table_sql())
        elif table == 'idempotency_records':
            statements.append(idempotency_table_sql(command_capabilities()))
        else:
            statements.append(statement)
    return '\n'.join((*statements, *new_tables(), *_indexes(), *_triggers()))


def upgrade_sql() -> str:
    statements = list(new_tables())
    old_triggers = _old_rebuilt_triggers()
    statements.extend(f'DROP TRIGGER "{name}";' for name, _ in old_triggers)
    for table in REBUILT:
        destination = table + '_v200'
        definition = (
            llm_table_sql(destination)
            if table == 'llm_uses'
            else idempotency_table_sql(command_capabilities(), destination)
        )
        statements.extend(
            (
                definition,
                copy_original_sql(table, destination),
                f'DROP TABLE "{table}";',
                f'ALTER TABLE "{destination}" RENAME TO "{table}";',
            )
        )
    statements.extend(statement for _, statement in old_triggers)
    statements.extend((*_indexes(), *_triggers()))
    return '\n'.join(statements)
