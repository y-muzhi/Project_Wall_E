"""Read the original persisted cases and pinned definitions without running a check."""

from dataclasses import dataclass
from time import monotonic

from fastapi import APIRouter, Request

from backend.app.infrastructure.check_case_pack import hold_case_pack
from backend.app.infrastructure.check_case_values import json_literal, text_literal
from backend.app.infrastructure.check_runner_bundle import CheckResourceError, reference
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.windows_config_source import ConfigReadError
from backend.app.infrastructure.windows_local_paths import PathBoundaryError
from backend.app.infrastructure.windows_private_package import PackageSecurityError
from backend.app.shared.http_boundary import handle_http
from backend.app.shared.http_projection import exact, page
from backend.app.shared.pagination import MAX_PAGE, PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import (
    decimal_integer,
    strict_enum,
    strict_integer,
    strict_json_loads,
)

from .configuration_identities import require_schema
from .repository_operations import _time
from .repository_reads import ERRORS
from .task_candidate_reads import NOT_FOUND
from .task_read_query import read_task_query

PATH = '/api/v1/code-tasks/{task_id}/verifications/{verification_id}/items/{item_id}/cases'
FIELDS = (
    'case_id',
    'name',
    'result',
    'expected_assertion_count',
    'passed_assertion_count',
    'failed_assertion_count',
    'capture_status',
    'summary',
    'observed_at',
)
RESULTS = ('PASSED', 'FAILED')
CAPTURE = ('FULL', 'REDACTED', 'INCOMPLETE')
NOT_READY = {
    'code': 'CONFIG_NOT_READY',
    'data': None,
    'details': {'capability_codes': ['Q20-CHECKS']},
}
verification_case_router = APIRouter(redirect_slashes=False)


@dataclass(frozen=True)
class CodingCaseRequest:
    task_id: int
    verification_id: int
    item_id: int
    page: int
    case_packs: tuple

    @classmethod
    def parse(cls, request):
        query = read_task_query(request, singles=('page',))
        registration = getattr(request.app.state, 'walle_repository_registration', None)
        return cls(
            decimal_integer(request.path_params['task_id'], 'task_id'),
            decimal_integer(request.path_params['verification_id'], 'verification_id'),
            decimal_integer(request.path_params['item_id'], 'item_id'),
            decimal_integer(query.get('page', '1'), 'page', MAX_PAGE),
            () if registration is None else getattr(registration, 'case_pack_admissions', ()),
        )


def _project(value):
    result = exact(value, FIELDS)
    reference(result['case_id'])
    text_literal(result['name'], limit=256)
    strict_enum(result['result'], 'result', RESULTS)
    strict_enum(result['capture_status'], 'capture_status', CAPTURE)
    _time(result['observed_at'], nullable=False)
    expected = strict_integer(result['expected_assertion_count'], 'expected_assertion_count')
    passed = strict_integer(result['passed_assertion_count'], 'passed_assertion_count', minimum=0)
    failed = strict_integer(result['failed_assertion_count'], 'failed_assertion_count', minimum=0)
    if result['summary'] is not None:
        text_literal(result['summary'], limit=256)
    observed = passed + failed
    if (
        observed > expected
        or result['capture_status'] != 'INCOMPLETE'
        and observed != expected
        or result['result'] == 'PASSED'
        and (failed or observed != expected or result['capture_status'] == 'INCOMPLETE')
        or result['result'] == 'FAILED'
        and not failed
    ):
        raise ValueError('Original verification case counts differ')
    return result


def _case_view(row, definition):
    try:
        expected = {assertion.assertion_id for assertion in definition.assertions}
        outcomes = strict_json_loads(row['assertion_results'])
        if type(outcomes) is not list or not 0 < len(outcomes) <= len(expected):
            raise ValueError('Original verification assertion evidence differs')
        seen = set()
        failed = 0
        for outcome in outcomes:
            outcome = exact(outcome, ('assertion_id', 'result', 'actual_value'))
            identity = reference(outcome['assertion_id'])
            if identity in seen or identity not in expected:
                raise ValueError('Original verification assertion identity differs')
            seen.add(identity)
            failed += strict_enum(outcome['result'], 'result', RESULTS) == 'FAILED'
            actual = outcome['actual_value']
            if type(actual) in (dict, list):
                raise ValueError('Original assertion actual value must be a scalar')
            json_literal(actual)
        capture = row['capture_status']
        return _project(
            {
                'case_id': row['case_id'],
                'name': definition.name,
                'result': row['result'],
                'expected_assertion_count': len(expected),
                'passed_assertion_count': len(seen) - failed,
                'failed_assertion_count': failed,
                'capture_status': capture,
                'summary': (
                    '已记录失败断言，部分证据缺失。'
                    if capture == 'INCOMPLETE'
                    else '部分诊断信息已脱敏。'
                    if capture == 'REDACTED'
                    else None
                ),
                'observed_at': row['observed_at'],
            }
        )
    except (ValueError, CheckResourceError) as error:
        raise StorageUnavailable('Original verification case evidence differs') from error


def _original_case_pack(connection, scope, request):
    row = connection.execute(
        "SELECT items FROM code_check_set_versions WHERE id=? AND owner_module='CODING'",
        (scope['check_set_version_id'],),
    ).fetchone()
    environment = connection.execute(
        'SELECT check_resource_refs FROM code_environment_records WHERE id=? AND task_id=?',
        (scope['environment_record_id'], request.task_id),
    ).fetchone()
    if row is None or environment is None:
        raise StorageUnavailable('Original verification case dependencies are missing')
    try:
        checks = strict_json_loads(row['items'])
        refs = strict_json_loads(environment['check_resource_refs'])
        selected = [check for check in checks if check['check_id'] == scope['check_id']]
        if len(selected) != 1 or selected[0]['check_kind'] != 'CONTROLLED_ASSERTION':
            raise ValueError('Original controlled check identity differs')
        case_pack_ref = reference(selected[0]['case_pack_ref'])
        if type(refs) is not list or any(type(ref) is not str for ref in refs):
            raise ValueError('Original controlled check resource list differs')
    except (CheckResourceError, TypeError, KeyError, ValueError) as error:
        raise StorageUnavailable('Original verification case dependencies differ') from error
    matches = [
        binding
        for binding in request.case_packs
        if binding.case_pack_ref == case_pack_ref and binding.environment_ref in refs
    ]
    if len(matches) > 1:
        raise StorageUnavailable('Original verification CasePack identity is ambiguous')
    return matches[0] if matches else None


def _scope(connection, request):
    return connection.execute(
        """SELECT i.check_id,i.check_kind,i.evidence_kind,i.expected_case_count,
                  i.executed_case_count,v.check_set_version_id,v.environment_record_id
           FROM code_verification_items i
           JOIN code_verifications v ON v.id=i.verification_id
           WHERE i.id=? AND v.id=? AND v.task_id=? AND v.owner_kind='CODING'""",
        (request.item_id, request.verification_id, request.task_id),
    ).fetchone()


def read_coding_cases(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        scope = _scope(connection, request)
        if scope is None:
            return NOT_FOUND
        total = connection.execute(
            'SELECT count(*) FROM code_verification_case_results WHERE item_id=?',
            (request.item_id,),
        ).fetchone()[0]
        data = {**page_metadata(request.page, total), 'items': []}
        if scope['evidence_kind'] != 'CONTROLLED_CASES':
            if total:
                raise StorageUnavailable('Cases exist for an item without controlled evidence')
            return {'code': 'READ_OK', 'data': data, 'details': None}
        if scope['check_kind'] != 'CONTROLLED_ASSERTION':
            raise StorageUnavailable('Controlled case evidence is attached to a project command')
        if not total:
            return {'code': 'READ_OK', 'data': data, 'details': None}
        if (
            scope['expected_case_count'] is None
            or scope['executed_case_count'] is None
            or total != scope['executed_case_count']
            or total > scope['expected_case_count']
        ):
            raise StorageUnavailable('Original verification case count differs')
        rows = connection.execute(
            """SELECT * FROM code_verification_case_results
               WHERE item_id=? ORDER BY case_id COLLATE BINARY LIMIT ? OFFSET ?""",
            (request.item_id, PAGE_SIZE, page_offset(request.page)),
        ).fetchall()
        if not rows:
            return {'code': 'READ_OK', 'data': data, 'details': None}
        binding = _original_case_pack(connection, scope, request)
    if binding is None:
        return NOT_READY
    try:
        with hold_case_pack(binding, deadline=monotonic() + 2, cancelled=lambda: False) as pack:
            if len(pack.cases) != scope['expected_case_count']:
                raise StorageUnavailable('Original verification case plan differs')
            definitions = {case.case_id: case for case in pack.cases}
            for row in rows:
                definition = definitions.get(row['case_id'])
                if definition is None:
                    raise StorageUnavailable('Original verification case is outside the plan')
                data['items'].append(_case_view(row, definition))
    except (CheckResourceError, ConfigReadError, PathBoundaryError, PackageSecurityError, OSError):
        return NOT_READY
    return {'code': 'READ_OK', 'data': data, 'details': None}


class CodingCaseResponse:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(data, request):
        return page(data, _project, request.page)


@verification_case_router.get(PATH)
async def read_coding_cases_http(request: Request):
    return await handle_http(request, CodingCaseRequest, CodingCaseResponse, read_coding_cases)
