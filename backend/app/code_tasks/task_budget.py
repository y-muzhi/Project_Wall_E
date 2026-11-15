"""C40 raises the Coding task's total without changing execution authority."""

from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success
from backend.app.shared.code_errors import empty_conflict
from backend.app.shared.command_execution import (
    ConfigurationNotReady,
    execute_idempotent,
    operation_time,
)
from backend.app.shared.http_boundary import handle_http, idempotency_header, request_query
from backend.app.shared.validation import (
    MAX_SAFE_INTEGER,
    InvalidInput,
    decimal_integer,
    object_fields,
    reject,
    strict_integer,
    strict_json_object,
    text_value,
)

from .command_registry import RegisteredCommand, registered_command
from .configuration_identities import require_schema
from .costs import format_balance, format_money, parse_money
from .task_basis import TaskBasisUnavailable

BUDGET_PATH = '/api/v1/code-tasks/{task_id}/budget'
BUDGET_CAPABILITY = 'APP-CODE-CMD-C40'
budget_write_router = APIRouter(redirect_slashes=False)


@dataclass(frozen=True)
class IncreaseBudgetRequest:
    task_id: int
    expected_state_version: int
    new_budget_limit_cny: str
    reason: str
    command: RegisteredCommand
    amount_micro: int

    body_fields = ('expected_state_version', 'new_budget_limit_cny', 'reason')

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {
            'task_id': self.task_id,
            **{field: getattr(self, field) for field in self.body_fields},
        }

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        task_id = decimal_integer(request.path_params['task_id'], 'task_id')
        fields = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        reason = text_value(fields['reason'], 'reason')
        if not reason.strip():
            reject('reason', 'TOO_SHORT', '预算调整说明必须为非空文本')
        amount = fields['new_budget_limit_cny']
        try:
            micro = parse_money(amount, 'new_budget_limit_cny')
        except InvalidInput:
            raise
        except ValueError:
            reject('new_budget_limit_cny', 'OUT_OF_RANGE', '预算金额超出可处理范围')
        return cls(
            task_id,
            strict_integer(fields['expected_state_version'], 'expected_state_version'),
            amount,
            reason,
            registered_command(
                'POST',
                BUDGET_PATH.format(task_id=task_id),
                idempotency_header(request, lowercase=True),
            ),
            micro,
        )


def _task_conflict(task, *, operation_id=None):
    return {
        **empty_conflict(),
        'task_id': task['id'],
        'current_state_version': task['state_version'],
        'related_operation_id': operation_id,
    }


def increase_task_budget(runtime, request):
    from .task_initial_configuration import initial_configuration_view
    from .task_live_configuration import project_live_configuration_activity
    from .task_read_api import project_saved_task, validate_saved_task_view

    require_schema(runtime)

    def change_budget(connection):
        task = connection.execute(
            'SELECT * FROM code_tasks WHERE id=?', (request.task_id,)
        ).fetchone()
        if task is None:
            return Rejection('NOT_FOUND', None)
        if task['status'] in ('COMPLETED', 'TERMINATED'):
            return Rejection('TASK_ENDED', _task_conflict(task))
        if task['status'] == 'STOPPING' or task['stop_requested_at'] is not None:
            return Rejection('INVALID_STATE', _task_conflict(task))
        if task['state_version'] != request.expected_state_version:
            return Rejection('VERSION_CONFLICT', _task_conflict(task))
        current = parse_money(task['budget_limit_cny'])
        if request.amount_micro <= current:
            return Rejection(
                'BUDGET_NOT_INCREASED',
                {
                    'field_errors': [{'field': 'new_budget_limit_cny', 'reason': 'RANGE'}],
                },
            )
        if task['state_version'] >= MAX_SAFE_INTEGER - 2:
            return Rejection('PRECONDITION_FAILED', _task_conflict(task))
        try:
            prior = project_saved_task(connection, runtime.catalog, task)
            prior['configuration_application'] = initial_configuration_view(connection, task['id'])
            project_live_configuration_activity(connection, task, prior, False)
        except TaskBasisUnavailable as error:
            raise ConfigurationNotReady('Q20-CONTENT') from error
        observed_at = max(operation_time(None), task['updated_at'])
        next_version = task['state_version'] + 1
        amount = format_money(request.amount_micro)
        if (
            connection.execute(
                """UPDATE code_tasks SET budget_limit_cny=?,state_version=?,updated_at=?
               WHERE id=? AND state_version=? AND control_generation=?
               AND status=? AND stop_requested_at IS NULL""",
                (
                    amount,
                    next_version,
                    observed_at,
                    task['id'],
                    task['state_version'],
                    task['control_generation'],
                    task['status'],
                ),
            ).rowcount
            != 1
        ):
            raise StorageUnavailable('Original Coding budget fence differs')
        old_budget = prior['budget']
        data = {
            **prior,
            'state_version': next_version,
            'updated_at': observed_at,
            'budget': {
                **old_budget,
                'limit_cny': amount,
                'available_cny': format_balance(
                    request.amount_micro
                    - parse_money(old_budget['settled_cny'])
                    - parse_money(old_budget['reserved_cny'])
                ),
            },
        }
        validate_saved_task_view(data, task['id'])
        return Success({'code': 'UPDATED', 'data': data, 'details': None}, 200)

    return execute_idempotent(
        runtime.commands(),
        BUDGET_CAPABILITY,
        request,
        change_budget,
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset({'CONFIG_NOT_READY'}),
    )


def budget_only_versions(connection, task, version, *, through, match_current=True):
    """Prove pre-start control versions from their original committed receipts."""
    from .task_configuration_progress import public_configuration_operation, staged_configuration

    if version == 1:
        return True
    target = 'POST ' + BUDGET_PATH.format(task_id=task['id'])
    rows = connection.execute(
        """SELECT business_input_json,success_result_json,http_status FROM idempotency_records
           WHERE capability_id=? AND target_identity=? AND status='SUCCEEDED'
           AND json_extract(business_input_json,'$.expected_state_version')<?
           ORDER BY json_extract(business_input_json,'$.expected_state_version')""",
        (BUDGET_CAPABILITY, target, version),
    ).fetchall()
    configuration = staged_configuration(connection, task['id'])
    configuration_version = None
    if configuration is not None and configuration['expected_state_version'] < version:
        original = public_configuration_operation(connection, configuration)
        if not task['created_at'] <= original['created_at'] <= through:
            return False
        configuration_version = original['expected_state_version']
        if (
            original['fixed_input']['authorization_id'] != task['authorization_id']
            or original['fixed_input']['execution_profile_version_id']
            != task['execution_profile_version_id']
        ):
            return False
    if len(rows) != version - 1 - int(configuration_version is not None):
        return False
    expected_versions = (
        expected for expected in range(1, version) if expected != configuration_version
    )
    prior_amount, prior_at = 0, task['created_at']
    for expected, row in zip(expected_versions, rows, strict=True):
        try:
            fixed = strict_json_object(row['business_input_json'])
            result = strict_json_object(row['success_result_json'])
            data = result['data']
            amount = parse_money(fixed['new_budget_limit_cny'])
            updated_at = data['updated_at']
            if (
                row['http_status'] != 200
                or result['code'] != 'UPDATED'
                or fixed['task_id'] != task['id']
                or fixed['expected_state_version'] != expected
                or data['id'] != task['id']
                or data['state_version'] != expected + 1
                or data['control_generation'] != 1
                or data['status'] != 'PENDING'
                or data['phase'] != 'PREPARING'
                or data['active_operations'] != []
                or data['workspace_id'] is not None
                or data['active_session_id'] is not None
                or not prior_at <= updated_at <= through
                or amount <= prior_amount
                or data['budget']['limit_cny'] != format_money(amount)
            ):
                return False
        except (InvalidInput, ValueError, TypeError, KeyError):
            return False
        prior_amount, prior_at = amount, updated_at
    return not rows or not match_current or format_money(prior_amount) == task['budget_limit_cny']


def start_budget_versions(connection, task, start, *, offset, version=None, through=None):
    """Remove only proven budget increments from the original START version."""
    version = task['state_version'] if version is None else version
    through = task['updated_at'] if through is None else through
    base = start['expected_state_version'] + 1
    expected_count = version - base - (offset - 1)
    if expected_count <= 0:
        return expected_count == 0
    rows = connection.execute(
        """SELECT business_input_json,success_result_json,http_status FROM idempotency_records
           WHERE capability_id=? AND target_identity=? AND status='SUCCEEDED'
           AND json_extract(business_input_json,'$.expected_state_version')>=?
           AND json_extract(business_input_json,'$.expected_state_version')<?
           ORDER BY json_extract(business_input_json,'$.expected_state_version')""",
        (BUDGET_CAPABILITY, 'POST ' + BUDGET_PATH.format(task_id=task['id']), base, version),
    ).fetchall()
    if len(rows) != expected_count:
        return False
    prior_amount, prior_at, published = 0, start['created_at'], False
    for index, row in enumerate(rows):
        try:
            fixed = strict_json_object(row['business_input_json'])
            result = strict_json_object(row['success_result_json'])
            data = result['data']
            amount = parse_money(fixed['new_budget_limit_cny'])
            at = data['updated_at']
            has_workspace = data['workspace_id'] is not None
            action = next(item for item in data['available_actions'] if item['action'] == 'START')
            if (
                row['http_status'] != 200
                or result['code'] != 'UPDATED'
                or data['id'] != task['id']
                or fixed['task_id'] != task['id']
                or fixed['expected_state_version'] != base + index + int(has_workspace)
                or data['state_version'] != fixed['expected_state_version'] + 1
                or data['control_generation'] != start['control_generation']
                or data['status'] != 'PENDING'
                or data['phase'] != 'PREPARING'
                or action['related_id'] != start['id']
                or data['active_session_id'] is not None
                or (published and not has_workspace)
                or (has_workspace and (offset != 2 or data['workspace_id'] != task['workspace_id']))
                or not prior_at <= at <= through
                or amount <= prior_amount
                or data['budget']['limit_cny'] != format_money(amount)
            ):
                return False
        except (InvalidInput, ValueError, TypeError, KeyError, StopIteration):
            return False
        prior_amount, prior_at, published = amount, at, has_workspace
    return format_money(prior_amount) == task['budget_limit_cny']


def validate_budget_result(command, data, status):
    from .task_read_api import validate_saved_task_view

    task_id = command.route.match(command.path)['task_id']
    if status != 200 or data['status'] in ('STOPPING', 'TERMINATED', 'COMPLETED'):
        raise ValueError('Original Coding budget receipt differs')
    validate_saved_task_view(data, task_id)
    return task_id


class IncreaseBudgetResponse:
    error_contract = 'code'
    success_code = 'UPDATED'
    errors = frozenset(
        {
            'INVALID_INPUT',
            'NOT_FOUND',
            'INVALID_STATE',
            'TASK_ENDED',
            'VERSION_CONFLICT',
            'OPERATION_CONFLICT',
            'OPERATION_IN_PROGRESS',
            'BUDGET_NOT_INCREASED',
            'AUTHORIZATION_NOT_APPLICABLE',
            'CONFIG_NOT_READY',
            'PRECONDITION_FAILED',
            'STORAGE_UNAVAILABLE',
            'INTERNAL_ERROR',
            'COMMAND_CLOSED',
        }
    )

    @staticmethod
    def project(data, request):
        validate_budget_result(request.command, data, 200)
        if data['state_version'] != request.expected_state_version + 1 or data['budget'][
            'limit_cny'
        ] != format_money(request.amount_micro):
            raise ValueError('Coding budget receipt differs from the original input')
        return data, None


@budget_write_router.post(BUDGET_PATH)
async def increase_budget_http(request: Request):
    return await handle_http(
        request, IncreaseBudgetRequest, IncreaseBudgetResponse, increase_task_budget
    )
