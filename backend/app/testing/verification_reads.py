"""Testing-owned Verification and case projections for the original fixed pack."""

from backend.app.code_tasks.check_set_content import STAGES
from backend.app.code_tasks.configuration_identities import require_schema
from backend.app.code_tasks.repository_operations import _time
from backend.app.code_tasks.task_verification_reads import (
    ENVIRONMENT_FIELDS,
    ITEM_FIELDS,
    VERIFICATION_FIELDS,
)
from backend.app.code_tasks.verification_case_reads import _case_view
from backend.app.infrastructure.check_runner_bundle import reference, valid_sha256
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.shared.http_projection import exact
from backend.app.shared.pagination import PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import (
    strict_enum,
    strict_integer,
    strict_json_loads,
)

from .assets import NOT_FOUND, _read
from .pack_definitions import compiled_definition
from .tasks import PURPOSES, read_task_row
from .validation_evidence import _case_facts, _owned_close, expected_checks, owned_check_fact

FIELDS = (
    *VERIFICATION_FIELDS,
    'items',
    'environment_record',
    'eligible',
    'ineligibility_reason_codes',
)
ITEM_RESULTS = ('NOT_RUN', 'RUNNING', 'PASSED', 'FAILED', 'UNAVAILABLE', 'UNKNOWN', 'CANCELLED')
REASONS = (
    'REQUIRED_NOT_PASSED',
    'NO_CONTROLLED_CASES',
    'RESOURCE_NOT_READY',
    'COVERAGE_NOT_READY',
    'ACTIVITY_NOT_STOPPED',
    'EVIDENCE_INCOMPLETE',
    'TEST_ASSET_REVOKED',
)


def _refs(values, field, *, nonempty=False):
    if type(values) is not list or nonempty and not values or len(values) != len(set(values)):
        raise ValueError(f'Original Testing verification references differ for {field}')
    for value in values:
        reference(value)
    return values


def _project_item(value, verification):
    row = exact(value, ITEM_FIELDS)
    strict_integer(row['id'], 'item_id')
    reference(row['check_id'])
    evidence = strict_enum(
        row['evidence_kind'], 'evidence_kind', ('CONTENT_INTEGRITY', 'CONTROLLED_CASES')
    )
    result = strict_enum(row['result'], 'result', ITEM_RESULTS)
    if (
        row['verification_id'] != verification
        or row['check_kind'] != 'CONTROLLED_ASSERTION'
        or type(row['required']) is not bool
        or row['evidence_summary'] is not None
        or row['reused_from_item_id'] is not None
    ):
        raise ValueError('Original Testing verification item owner differs')
    if row['command_execution_id'] is not None:
        strict_integer(row['command_execution_id'], 'command_execution_id')
    if row['reason_code'] is not None:
        reference(row['reason_code'])
    for field in ('started_at', 'ended_at'):
        _time(row[field])
    if row['ended_at'] is not None and (
        row['started_at'] is None or row['ended_at'] < row['started_at']
    ):
        raise ValueError('Original Testing verification item chronology differs')
    names = ('expected_case_count', 'executed_case_count', 'passed_case_count', 'failed_case_count')
    if evidence == 'CONTROLLED_CASES':
        expected, executed, passed, failed = (
            strict_integer(row[key], key, minimum=0) for key in names
        )
        if (
            executed != passed + failed
            or executed > expected
            or result == 'PASSED'
            and (not expected or passed != expected or failed)
        ):
            raise ValueError('Original Testing verification case counts differ')
    elif any(row[key] is not None for key in names):
        raise ValueError('Content integrity must not invent a case count')
    return row


def project_verification(value, task_id, verification_id):
    row = exact(value, FIELDS)
    for key in (
        'id',
        'testing_task_id',
        'check_set_version_id',
        'testing_profile_version_id',
        'environment_record_id',
        'operation_id',
    ):
        strict_integer(row[key], key)
    if (
        row['id'] != verification_id
        or row['testing_task_id'] != task_id
        or row['owner_kind'] != 'TESTING'
        or any(
            row[key] is not None
            for key in (
                'task_id',
                'role',
                'profile_version_id',
                'backend_handoff_operation_id',
                'frontend_handoff_operation_id',
            )
        )
        or (row['candidate_id'] is None) == (row['snapshot_id'] is None)
    ):
        raise ValueError('Original Testing verification owner differs')
    for field in ('candidate_id', 'snapshot_id'):
        if row[field] is not None:
            strict_integer(row[field], field)
    strict_enum(row['purpose'], 'purpose', PURPOSES)
    strict_enum(row['status'], 'status', ('PENDING', 'RUNNING', 'FINISHED', 'UNKNOWN', 'CANCELLED'))
    strict_enum(row['stop_status'], 'stop_status', ('NOT_STARTED', 'ACTIVE', 'VERIFIED', 'UNKNOWN'))
    strict_enum(
        row['cleanup_status'],
        'cleanup_status',
        ('NOT_STARTED', 'CLEANING', 'VERIFIED', 'FAILED', 'UNKNOWN'),
    )
    strict_enum(
        row['source_integrity_status'],
        'source_integrity_status',
        ('NOT_CHECKED', 'VERIFIED', 'CHANGED', 'UNKNOWN'),
    )
    _time(row['created_at'], nullable=False)
    _time(row['ended_at'])
    if row['ended_at'] is not None and row['ended_at'] < row['created_at']:
        raise ValueError('Original Testing verification chronology differs')
    scope = row['scope_stages']
    if (
        type(scope) is not list
        or not scope
        or scope != [stage for stage in STAGES if stage in scope]
    ):
        raise ValueError('Original Testing verification stages differ')
    checks = _refs(row['selected_check_ids'], 'selected_check_ids', nonempty=True)
    items = row['items']
    if type(items) is not list or len(items) != len(checks):
        raise ValueError('Original Testing verification check set differs')
    if [_project_item(item, verification_id)['check_id'] for item in items] != checks:
        raise ValueError('Original Testing verification check ordering differs')
    environment = exact(row['environment_record'], ENVIRONMENT_FIELDS)
    if (
        environment['id'] != row['environment_record_id']
        or environment['testing_task_id'] != task_id
        or environment['task_id'] is not None
        or environment['effective_config_application_id'] is not None
        or environment['testing_profile_version_id'] != row['testing_profile_version_id']
        or not valid_sha256(environment['scope_key'])
    ):
        raise ValueError('Original Testing environment owner differs')
    _time(environment['observed_at'], nullable=False)
    for field in ('runtime_refs', 'dependency_refs', 'runner_refs', 'check_resource_refs'):
        _refs(environment[field], field)
    reasons = row['ineligibility_reason_codes']
    if (
        type(row['eligible']) is not bool
        or type(reasons) is not list
        or (
            reasons != [reason for reason in REASONS if reason in reasons]
            or row['eligible'] != (not reasons)
        )
    ):
        raise ValueError('Original Testing verification readiness differs')
    return row


def _owned(connection, task_id, verification_id):
    row = connection.execute(
        """SELECT * FROM code_verifications WHERE id=? AND testing_task_id=? AND task_id IS NULL
           AND owner_kind='TESTING'""",
        (verification_id, task_id),
    ).fetchone()
    task = read_task_row(connection, task_id)
    if row is None or task is None:
        return None
    if (
        task['current_verification_id'] != row['id']
        or task['purpose'] != row['purpose']
        or task['candidate_id'] != row['candidate_id']
        or task['snapshot_id'] != row['snapshot_id']
        or task['profile_version_id'] != row['testing_profile_version_id']
        or task['test_pack_version_id'] is None
    ):
        raise StorageUnavailable('Original Testing verification facts differ')
    pack = connection.execute(
        'SELECT * FROM testing_pack_versions WHERE id=? AND plan_version_id=? AND check_set_version_id=?',
        (task['test_pack_version_id'], task['plan_version_id'], row['check_set_version_id']),
    ).fetchone()
    if pack is None:
        raise StorageUnavailable('Original Testing verification pack differs')
    return task, row, pack


def _saved(connection, task, row, pack):
    result = {key: row[key] for key in VERIFICATION_FIELDS}
    for key in ('scope_stages', 'selected_check_ids'):
        result[key] = strict_json_loads(row[key], key)
    environment = connection.execute(
        'SELECT * FROM code_environment_records WHERE id=? AND testing_task_id=? AND task_id IS NULL',
        (row['environment_record_id'], task['id']),
    ).fetchone()
    if environment is None:
        raise StorageUnavailable('Original Testing verification environment is missing')
    result['environment_record'] = {key: environment[key] for key in ENVIRONMENT_FIELDS}
    for key in ('runtime_refs', 'dependency_refs', 'runner_refs', 'check_resource_refs'):
        result['environment_record'][key] = strict_json_loads(environment[key], key)
    items = connection.execute(
        'SELECT * FROM code_verification_items WHERE verification_id=? ORDER BY id',
        (row['id'],),
    ).fetchall()
    for item in items:
        if item['required'] not in (0, 1):
            raise StorageUnavailable('Original Testing required flag is unreadable')
        command = item['command_execution_id']
        if (
            command is not None
            and connection.execute(
                'SELECT 1 FROM code_commands WHERE id=? AND testing_task_id=? AND task_id IS NULL AND operation_id=?',
                (command, task['id'], row['operation_id']),
            ).fetchone()
            is None
        ):
            raise StorageUnavailable('Original Testing verification command crosses scope')
    result['items'] = [
        {
            **{key: item[key] for key in ITEM_FIELDS},
            'required': bool(item['required']),
            'evidence_summary': None,
        }
        for item in items
    ]
    _, compiled = compiled_definition(connection, pack)
    scope, checks = expected_checks(compiled)
    groups = {f'controlled-{index}': group for index, group in enumerate(compiled.case_packs, 1)}
    reasons = set()
    if (
        result['scope_stages'] != scope
        or result['selected_check_ids'] != list(checks)
        or any(
            not item['required']
            or item['evidence_kind']
            != (
                'CONTENT_INTEGRITY'
                if item['check_id'] == 'content-integrity'
                else 'CONTROLLED_CASES'
            )
            for item in items
        )
    ):
        reasons.add('COVERAGE_NOT_READY')
    if any(item['required'] and item['result'] != 'PASSED' for item in items):
        reasons.add('REQUIRED_NOT_PASSED')
    if not any(item['required'] and item['evidence_kind'] == 'CONTROLLED_CASES' for item in items):
        reasons.add('NO_CONTROLLED_CASES')
    if (
        row['stop_status'] != 'VERIFIED'
        or row['cleanup_status'] != 'VERIFIED'
        or not _owned_close(connection, task, row)
    ):
        reasons.add('ACTIVITY_NOT_STOPPED')
    operation = connection.execute(
        """SELECT status,ended_at FROM code_operations WHERE id=? AND task_id IS NULL
           AND testing_task_id=? AND resource_kind='TESTING_TASK' AND resource_id=?
           AND operation_type='RUN_TEST' AND control_generation=?""",
        (row['operation_id'], task['id'], task['id'], task['control_generation']),
    ).fetchone()
    if (
        row['status'] != 'FINISHED'
        or row['source_integrity_status'] != 'VERIFIED'
        or operation is None
        or operation['status'] != 'SUCCEEDED'
        or operation['ended_at'] is None
        or row['ended_at'] is None
        or operation['ended_at'] < row['ended_at']
        or any(
            item['evidence_kind'] == 'CONTROLLED_CASES'
            and (
                item['check_id'] not in checks
                or _case_facts(connection, item, checks[item['check_id']]) is None
                or item['result'] == 'PASSED'
                and owned_check_fact(connection, task, row, item, groups.get(item['check_id']))
                is None
            )
            for item in items
        )
    ):
        reasons.add('EVIDENCE_INCOMPLETE')
    plan = connection.execute(
        'SELECT status FROM testing_plan_versions WHERE id=?', (pack['plan_version_id'],)
    ).fetchone()
    if plan is None:
        raise StorageUnavailable('Original Testing verification plan is missing')
    if pack['status'] == 'REVOKED' or plan['status'] == 'REVOKED':
        reasons.add('TEST_ASSET_REVOKED')
    elif plan['status'] != 'PUBLISHED' or pack['status'] not in (
        ('SEALED', 'PUBLISHED') if task['kind'] == 'PACK_VALIDATION' else ('PUBLISHED',)
    ):
        reasons.add('RESOURCE_NOT_READY')
    result.update(
        eligible=not reasons,
        ineligibility_reason_codes=[code for code in REASONS if code in reasons],
    )
    return project_verification(result, task['id'], row['id'])


def read_verification(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        original = _owned(connection, request.task, request.verification)
        if original is None:
            return NOT_FOUND.result
        try:
            return _read(_saved(connection, *original))
        except (TypeError, ValueError, KeyError) as error:
            raise StorageUnavailable('Original Testing verification is unreadable') from error


def read_cases(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        original = _owned(connection, request.task, request.verification)
        if original is None:
            return NOT_FOUND.result
        _, verification, pack = original
        item = connection.execute(
            'SELECT * FROM code_verification_items WHERE id=? AND verification_id=?',
            (request.item, verification['id']),
        ).fetchone()
        if item is None or item['evidence_kind'] != 'CONTROLLED_CASES':
            return NOT_FOUND.result
        _, compiled = compiled_definition(connection, pack)
        members = {
            f'controlled-{number}': group for number, group in enumerate(compiled.case_packs, 1)
        }
        member = members.get(item['check_id'])
        if member is None:
            raise StorageUnavailable('Original Testing item is missing its CasePack')
        definitions = {case.case_id: case for case in member.cases}
        total = connection.execute(
            'SELECT count(*) FROM code_verification_case_results WHERE item_id=?',
            (item['id'],),
        ).fetchone()[0]
        if total > len(definitions) or total != item['executed_case_count']:
            raise StorageUnavailable('Original Testing case count differs from its item')
        rows = connection.execute(
            """SELECT * FROM code_verification_case_results WHERE item_id=?
               ORDER BY case_id LIMIT ? OFFSET ?""",
            (item['id'], PAGE_SIZE, page_offset(request.page)),
        ).fetchall()
        if any(row['case_id'] not in definitions for row in rows):
            raise StorageUnavailable('Original Testing case is outside its fixed pack')
        return _read(
            {
                **page_metadata(request.page, total),
                'items': [_case_view(row, definitions[row['case_id']]) for row in rows],
            }
        )
