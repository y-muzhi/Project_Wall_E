"""V2 rebuilds for the two existing tables whose definitions change.

The frozen 151 SQL stays byte-for-byte intact. Copies name every original column;
no legacy value is normalized and no code/testing owner is fabricated.
"""

import re

from .database import Migration, _statements
from .schema_v20 import column_sql, literals
from .schema_v20_columns import COLUMNS
from backend.app.code_tasks.error_codes import ERROR_HTTP


def frozen_statements() -> tuple[str, ...]:
    return tuple(_statements(Migration().sql))


def _frozen_table(name: str) -> str:
    prefix = f'CREATE TABLE {name} ('
    for statement in frozen_statements():
        start = statement.find(prefix)
        if start >= 0:
            return statement[start:].strip()
    raise ValueError('Frozen source table not found')


def llm_table_sql(name: str = 'llm_uses') -> str:
    sql = _frozen_table('llm_uses')
    sql = sql.replace('CREATE TABLE llm_uses (', f'CREATE TABLE "{name}" (', 1)
    sql = sql.replace('guide_run_id INTEGER NOT NULL', 'guide_run_id INTEGER', 1)
    sql = sql.replace(
        'CHECK(call_no=1 AND attempt_no=1)',
        'CHECK(attempt_no=1 AND (guide_run_id IS NULL OR call_no=1))',
        1,
    )
    added_names = (
        'execution_session_id',
        'testing_task_id',
        'operation_id',
        'gateway_request_id',
        'retry_of_llm_use_id',
        'protocol_version',
        'call_purpose',
        'transport_status',
        'usage_status',
        'capture_status',
        'source_evidence_ref',
    )
    fields = {field[0]: field for field in COLUMNS['llm_uses'][1]}
    columns = [column_sql('LLMUse', *fields[field]) for field in added_names]
    constraints = [
        'UNIQUE(id,testing_task_id)',
        'UNIQUE(id,execution_session_id)',
        'CHECK(((guide_run_id IS NOT NULL)+(execution_session_id IS NOT NULL)+(testing_task_id IS NOT NULL))=1)',
        'FOREIGN KEY(execution_session_id) REFERENCES code_sessions(id) DEFERRABLE INITIALLY DEFERRED',
        'FOREIGN KEY(testing_task_id) REFERENCES testing_tasks(id) DEFERRABLE INITIALLY DEFERRED',
        'FOREIGN KEY(operation_id) REFERENCES code_operations(id) DEFERRABLE INITIALLY DEFERRED',
        'FOREIGN KEY(retry_of_llm_use_id) REFERENCES llm_uses(id) DEFERRABLE INITIALLY DEFERRED',
        """CHECK(((guide_run_id IS NOT NULL AND execution_session_id IS NULL AND testing_task_id IS NULL
          AND operation_id IS NULL AND gateway_request_id IS NULL AND protocol_version IS NULL
          AND call_purpose IS NULL AND transport_status IS NULL AND usage_status IS NULL
          AND capture_status IS NULL AND source_evidence_ref IS NULL AND retry_of_llm_use_id IS NULL)
        OR (guide_run_id IS NULL AND operation_id IS NOT NULL AND source_evidence_ref IS NOT NULL
          AND transport_status IS NOT NULL AND usage_status IS NOT NULL AND capture_status IS NOT NULL
          AND (provider_request_id IS NULL OR length(provider_request_id) BETWEEN 1 AND 1024)
          AND ((execution_session_id IS NOT NULL AND testing_task_id IS NULL
            AND function_type='CODE_EXECUTION' AND protocol_version='OC20-MODEL-1'
            AND gateway_request_id IS NOT NULL AND call_purpose IN ('CODE','COMPACTION')
            AND parse_status='NOT_APPLICABLE' AND validation_status='NOT_APPLICABLE'
            AND parsed_output_json IS NULL AND trusted_output_json IS NULL)
          OR (testing_task_id IS NOT NULL AND execution_session_id IS NULL
            AND function_type='TEST_PLAN_DRAFT' AND protocol_version='TEST20-PLAN-1'
            AND gateway_request_id IS NULL AND call_purpose='TEST_DESIGN'
            AND parse_status IN ('PENDING','SUCCEEDED','FAILED')
            AND validation_status IN ('PENDING','SUCCEEDED','FAILED')
            AND retry_of_llm_use_id IS NULL)))) IS TRUE)""",
    ]
    sql = sql.replace(
        '  CHECK(attempt_no=', '  ' + ',\n  '.join(columns) + ',\n  CHECK(attempt_no=', 1
    )
    return sql.replace('\n) STRICT;', ',\n  ' + ',\n  '.join(constraints) + '\n) STRICT;')


def idempotency_table_sql(capabilities: tuple[str, ...], name: str = 'idempotency_records') -> str:
    sql = _frozen_table('idempotency_records')
    sql = sql.replace('CREATE TABLE idempotency_records (', f'CREATE TABLE "{name}" (', 1)
    sql = sql.replace(
        "business_input_json TEXT NOT NULL CHECK(json_valid(business_input_json) AND json_type(business_input_json)='object')",
        'business_input_json TEXT CHECK(business_input_json IS NULL OR '
        "(json_valid(business_input_json) AND json_type(business_input_json)='object'))",
    )
    sql = sql.replace(
        "status IN ('PROCESSING','SUCCEEDED')",
        "status IN ('PROCESSING','SUCCEEDED','REJECTED','CLOSED')",
    )
    sql = sql.replace(
        '  PRIMARY KEY(',
        "  error_result_json TEXT CHECK(error_result_json IS NULL OR (json_valid(error_result_json) AND json_type(error_result_json)='object')),\n  PRIMARY KEY(",
        1,
    )
    start = sql.index("  CHECK((status='PROCESSING'")
    sql = (
        sql[:start]
        + f"""  CHECK((
       (status='PROCESSING' AND business_input_json IS NOT NULL AND success_result_json IS NULL
          AND error_result_json IS NULL AND http_status IS NULL)
    OR (status='SUCCEEDED' AND business_input_json IS NOT NULL AND success_result_json IS NOT NULL
          AND error_result_json IS NULL AND http_status BETWEEN 200 AND 299)
    OR (status='REJECTED' AND capability_id IN ({literals(capabilities)})
          AND business_input_json IS NOT NULL AND success_result_json IS NULL AND error_result_json IS NOT NULL
          AND json_type(error_result_json,'$.data')='null'
          AND json_type(error_result_json,'$.code')='text'
          AND json_extract(error_result_json,'$.code')<>'COMMAND_CLOSED'
          AND http_status BETWEEN 400 AND 499 AND CASE json_extract(error_result_json,'$.code')
          """
        + ' '.join(
            f"WHEN '{code}' THEN {status}"
            for code, status in ERROR_HTTP.items()
            if 400 <= status < 500
        )
        + """ END=http_status)
    OR (status='CLOSED' AND capability_id IN ("""
        + literals(capabilities)
        + """)
          AND business_input_json IS NULL AND success_result_json IS NULL AND error_result_json IS NOT NULL
          AND http_status=409 AND json_extract(error_result_json,'$.code')='COMMAND_CLOSED'
          AND json_type(error_result_json,'$.data')='null'
          AND json_extract(error_result_json,'$.details.method')='POST'
          AND target_identity='POST '||json_extract(error_result_json,'$.details.path')
          AND json_extract(error_result_json,'$.details.closed_at')=created_at AND updated_at=created_at)
    ) IS TRUE)
) STRICT;"""
    )
    return sql


def original_columns(table: str) -> tuple[str, ...]:
    return tuple(
        re.findall(r'^  ([a-z_]+) (?:INTEGER|TEXT|BLOB|REAL)\b', _frozen_table(table), re.M)
    )


def copy_original_sql(table: str, destination: str) -> str:
    columns = ','.join('"' + column + '"' for column in original_columns(table))
    return f'INSERT INTO "{destination}"({columns}) SELECT {columns} FROM "{table}";'
