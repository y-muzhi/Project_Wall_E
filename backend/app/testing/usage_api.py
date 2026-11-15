"""Read Testing model audit and its original settlement without provider I/O."""

from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.code_tasks.authorization_api import authorization_query
from backend.app.code_tasks.configuration_identities import require_schema
from backend.app.code_tasks.costs import format_money, parse_money
from backend.app.code_tasks.repository_operations import _time
from backend.app.infrastructure.audit_data import MAX_AUDIT_BYTES, sanitize_audit
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.shared.http_boundary import handle_http
from backend.app.shared.http_projection import exact, page
from backend.app.shared.pagination import MAX_PAGE, PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import (
    decimal_integer,
    raw_text,
    strict_enum,
    strict_integer,
    strict_json_object,
)

from .assets import NOT_FOUND, _read
from .plan_content import BASIS_FIELDS, parse_plan_content
from .policy_api import PolicyRead
from .tasks import materials_for, read_task_row

CALLS = '/testing-tasks/{testing_task_id}/model-calls'
CALL = CALLS + '/{llm_use_id}'
TEST_USAGE_ROUTER = APIRouter(redirect_slashes=False)
SUMMARY = (
    'id',
    'testing_task_id',
    'operation_id',
    'call_no',
    'attempt_no',
    'function_type',
    'model_name',
    'call_status',
    'parse_status',
    'validation_status',
    'started_at',
    'ended_at',
    'input_tokens',
    'output_tokens',
    'usage_status',
    'provider_request_id',
)
DETAIL = (
    'request_snapshot',
    'response_snapshot',
    'parsed_output',
    'trusted_output',
    'reservation_id',
    'reserved_cny',
    'settled_cny',
    'settlement_basis',
)
PLAN_DRAFT = ('behaviors', 'cases', 'unresolved_questions')
OWNER = """ FROM llm_uses u
    LEFT JOIN code_operations o ON o.id=u.operation_id AND o.testing_task_id=u.testing_task_id
      AND o.task_id IS NULL AND o.resource_kind='TESTING_TASK' AND o.resource_id=u.testing_task_id
      AND o.operation_type='DRAFT_PLAN'
    LEFT JOIN code_task_reservations r ON r.llm_use_id=u.id AND r.testing_task_id=u.testing_task_id
      AND r.task_id IS NULL
    WHERE u.testing_task_id=? AND u.guide_run_id IS NULL AND u.execution_session_id IS NULL"""
SUMMARY_SQL = ','.join('u.' + key for key in SUMMARY)
SCOPE_SQL = ',o.id AS owned_operation_id,r.id AS reservation_id,u.transport_status'
DETAIL_SQL = """,u.request_snapshot_json,u.raw_response_json,u.parsed_output_json,
    u.trusted_output_json,u.cost,u.cost_currency,r.reserved_cny,r.settled_cny,
    r.settlement_basis,r.status AS reservation_status"""


@dataclass(frozen=True)
class CallsRequest:
    task: int
    page: int

    @classmethod
    def parse(cls, request):
        query = authorization_query(request, singles=('page',))
        return cls(
            decimal_integer(request.path_params['testing_task_id'], 'testing_task_id'),
            decimal_integer(query.get('page', '1'), 'page', MAX_PAGE),
        )


@dataclass(frozen=True)
class CallRequest:
    task: int
    identity: int

    @classmethod
    def parse(cls, request):
        authorization_query(request)
        return cls(
            decimal_integer(request.path_params['testing_task_id'], 'testing_task_id'),
            decimal_integer(request.path_params['llm_use_id'], 'llm_use_id'),
        )


def project_summary(value, owner):
    row = exact(value, SUMMARY)
    for key in ('id', 'testing_task_id', 'operation_id', 'call_no', 'attempt_no'):
        strict_integer(row[key], key)
    if (
        row['testing_task_id'] != owner
        or row['attempt_no'] != 1
        or row['function_type'] != 'TEST_PLAN_DRAFT'
    ):
        raise ValueError('Original Testing call owner or purpose differs')
    raw_text(row['model_name'], 'model_name', 1, 1024)
    if row['provider_request_id'] is not None:
        raw_text(row['provider_request_id'], 'provider_request_id', 1, 1024)
    strict_enum(row['call_status'], 'call_status', ('RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED'))
    for key in ('parse_status', 'validation_status'):
        strict_enum(row[key], key, ('PENDING', 'SUCCEEDED', 'FAILED'))
    usage = strict_enum(
        row['usage_status'], 'usage_status', ('NOT_REPORTED', 'PARTIAL', 'FINAL', 'DISPUTED')
    )
    counts = (row['input_tokens'], row['output_tokens'])
    for amount in counts:
        if amount is not None:
            strict_integer(amount, 'tokens', minimum=0)
    if usage == 'NOT_REPORTED' and counts != (None, None) or usage == 'FINAL' and None in counts:
        raise ValueError('Original Testing usage stage differs')
    _time(row['started_at'], nullable=False)
    _time(row['ended_at'])
    if row['ended_at'] is not None and row['ended_at'] < row['started_at']:
        raise ValueError('Original Testing call time differs')
    return row


def project_detail(value, owner, identity):
    row = exact(value, SUMMARY + DETAIL)
    project_summary({key: row[key] for key in SUMMARY}, owner)
    if row['id'] != identity:
        raise ValueError('Original Testing call identity differs')
    strict_integer(row['reservation_id'], 'reservation_id')
    for key in ('reserved_cny', 'settled_cny'):
        if (row[key] is not None or key == 'reserved_cny') and format_money(
            parse_money(row[key], key)
        ) != row[key]:
            raise ValueError('Original Testing call amount differs')
    if (row['settled_cny'] is None) != (row['settlement_basis'] is None):
        raise ValueError('Original Testing settlement basis differs')
    if row['settlement_basis'] is not None:
        strict_enum(
            row['settlement_basis'], 'settlement_basis', ('VERIFIED_USAGE', 'PROVIDER_BILL')
        )
    for key in ('request_snapshot', 'response_snapshot', 'parsed_output', 'trusted_output'):
        if row[key] is not None and type(row[key]) is not dict:
            raise ValueError('Original Testing audit is not an object')
    if (
        (row['parsed_output'] is not None) != (row['parse_status'] == 'SUCCEEDED')
        or (row['trusted_output'] is not None) != (row['validation_status'] == 'SUCCEEDED')
        or row['trusted_output'] is not None
        and row['parsed_output'] is None
    ):
        raise ValueError('Original Testing parse or validation audit differs')
    if row['trusted_output'] is not None:
        exact(row['trusted_output'], PLAN_DRAFT)
    return row


def _summary(row):
    if row['owned_operation_id'] != row['operation_id'] or row['reservation_id'] is None:
        raise StorageUnavailable('Original Testing model call ownership differs')
    if row['usage_status'] == 'FINAL' and row['transport_status'] != 'COMPLETE':
        raise StorageUnavailable('Final Testing usage lacks a complete original response')
    return {key: row[key] for key in SUMMARY}


def _snapshot(raw):
    if raw is None:
        return None
    if len(raw.encode('utf-8')) > MAX_AUDIT_BYTES:
        raise StorageUnavailable('Original Testing audit exceeds its capacity')
    return sanitize_audit(strict_json_object(raw))


def _detail(connection, task, row):
    data = _summary(row)
    if (
        row['cost'] != row['settled_cny']
        or row['cost_currency'] != (None if row['settled_cny'] is None else 'CNY')
        or (row['reservation_status'] == 'SETTLED') != (row['settled_cny'] is not None)
    ):
        raise StorageUnavailable('Original Testing ledger differs')
    data.update(
        request_snapshot=_snapshot(row['request_snapshot_json']),
        response_snapshot=_snapshot(row['raw_response_json']),
        parsed_output=_snapshot(row['parsed_output_json']),
        trusted_output=_snapshot(row['trusted_output_json']),
        **{key: row[key] for key in DETAIL[4:]},
    )
    trusted = data['trusted_output']
    if trusted is not None:
        basis = {key: task[key] for key in BASIS_FIELDS if key != 'material_refs'}
        basis['material_refs'] = materials_for(connection, task['id'])
        checked = parse_plan_content({**basis, **exact(trusted, PLAN_DRAFT)})
        if any(checked[key] != trusted[key] for key in PLAN_DRAFT):
            raise StorageUnavailable('Original trusted Testing draft differs')
    return project_detail(data, task['id'], row['id'])


def list_calls(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        if read_task_row(connection, request.task) is None:
            return NOT_FOUND.result
        total = connection.execute('SELECT count(*) ' + OWNER, (request.task,)).fetchone()[0]
        rows = connection.execute(
            'SELECT ' + SUMMARY_SQL + SCOPE_SQL + OWNER + ' ORDER BY u.id LIMIT ? OFFSET ?',
            (request.task, PAGE_SIZE, page_offset(request.page)),
        ).fetchall()
        try:
            items = [project_summary(_summary(row), request.task) for row in rows]
        except (KeyError, TypeError, ValueError) as error:
            raise StorageUnavailable('Original Testing call list is unreadable') from error
        return _read({**page_metadata(request.page, total), 'items': items})


def read_call(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        task = read_task_row(connection, request.task)
        if task is None:
            return NOT_FOUND.result
        row = connection.execute(
            'SELECT ' + SUMMARY_SQL + SCOPE_SQL + DETAIL_SQL + OWNER + ' AND u.id=?',
            (request.task, request.identity),
        ).fetchone()
        if row is None:
            return NOT_FOUND.result
        try:
            return _read(_detail(connection, task, row))
        except (KeyError, TypeError, ValueError) as error:
            raise StorageUnavailable('Original Testing model audit is unreadable') from error


class CallsRead(PolicyRead):
    @staticmethod
    def project(value, request):
        data, metadata = page(value, lambda row: project_summary(row, request.task), request.page)
        ids = [row['id'] for row in data['items']]
        if ids != sorted(set(ids)):
            raise ValueError('Original Testing call order differs')
        return data, metadata


class CallRead(PolicyRead):
    @staticmethod
    def project(value, request):
        return project_detail(value, request.task, request.identity), None


@TEST_USAGE_ROUTER.get(CALLS)
async def calls_http(request: Request):
    return await handle_http(request, CallsRequest, CallsRead, list_calls)


@TEST_USAGE_ROUTER.get(CALL)
async def call_http(request: Request):
    return await handle_http(request, CallRequest, CallRead, read_call)
