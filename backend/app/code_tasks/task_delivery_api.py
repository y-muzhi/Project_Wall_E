"""Coding API62/64 and safe views of their original operations."""

from dataclasses import dataclass, field

from fastapi import APIRouter, Request

from backend.app.shared.http_boundary import handle_http, idempotency_header, request_query
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import decimal_integer, strict_enum, strict_integer

from .command_registry import RegisteredCommand, registered_command
from .operation_protocol import operation_steps
from .repository_operations import OPERATION_FIELDS, STATES, STEP_FIELDS, _time
from .repository_reads import ERRORS
from .task_check_api import candidate_check_admissions
from .task_delivery import (
    ACCEPT_FIELDS,
    ACCEPT_PATH,
    DELIVER,
    PREPARE,
    PREPARE_PATH,
    PREVIEW_FIELDS,
    accept_delivery_command,
    fixed_input,
    original_operation,
)

delivery_command_router = APIRouter(redirect_slashes=False)
_RECEIPT = ('task_id', 'operation_id', 'operation_status', 'task_status', 'state_version')


@dataclass(frozen=True)
class PrepareDeliveryRequest:
    task_id: int
    data: dict
    command: RegisteredCommand
    admissions: tuple = field(repr=False)

    body_fields = PREVIEW_FIELDS
    kind = PREPARE
    path = PREPARE_PATH

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        task = decimal_integer(request.path_params['task_id'], 'task_id')
        return cls(
            task,
            fixed_input(body, cls.kind),
            registered_command(
                'POST', cls.path.format(task_id=task), idempotency_header(request, lowercase=True)
            ),
            candidate_check_admissions(request),
        )

    def business_input(self):
        return self.data

    @property
    def idempotency_key(self):
        return self.command.key


class AcceptDeliveryRequest(PrepareDeliveryRequest):
    body_fields = ACCEPT_FIELDS
    kind = DELIVER
    path = ACCEPT_PATH


def project_delivery_receipt(command, value, status):
    acceptance = command.route.capability_id == 'APP-CODE-CMD-C64'
    fields = (*_RECEIPT, 'acceptance_id', 'delivery_id') if acceptance else _RECEIPT
    data = exact(value, fields)
    for key in fields:
        if key not in ('operation_status', 'task_status'):
            strict_integer(data[key], key)
    if (
        status != 202
        or data['operation_status'] != 'PENDING'
        or data['task_status'] != 'AWAITING_ACCEPTANCE'
        or data['task_id'] != command.route.match(command.path)['task_id']
    ):
        raise ValueError('Original delivery receipt crosses scope')
    return data


class DeliveryAccepted:
    error_contract = 'code'
    success_code = 'OPERATION_ACCEPTED'
    status = 202
    errors = ERRORS | {
        'TASK_ENDED',
        'INVALID_STATE',
        'VERSION_CONFLICT',
        'OPERATION_CONFLICT',
        'COMMAND_CLOSED',
        'TEST_REPORT_NOT_ELIGIBLE',
        'TEST_SOURCE_MISMATCH',
        'TEST_ASSET_REVOKED',
        'CHECKS_NOT_PASSED',
        'VERIFICATION_STAGE_NOT_READY',
        'CANDIDATE_NOT_CURRENT',
        'DELIVERY_PLAN_STALE',
        'TARGET_CHANGED',
        'TARGET_CHECKED_OUT',
        'DELIVERY_NOT_AUTHORIZED',
        'DELIVERY_WINDOW_REQUIRED',
        'REPOSITORY_UNSUPPORTED',
    }

    @staticmethod
    def project(value, request):
        data = project_delivery_receipt(request.command, value, 202)
        if data['state_version'] != request.data['expected_state_version'] + 1:
            raise ValueError('Original delivery acceptance version differs')
        return data, None


def project_delivery_operation(value, identity):
    row = exact(value, OPERATION_FIELDS)
    kind = strict_enum(row['operation_type'], 'operation_type', (PREPARE, DELIVER))
    fixed = fixed_input(row['fixed_input'], kind)
    for key in (
        'id',
        'task_id',
        'resource_id',
        'control_generation',
        'expected_state_version',
        'session_id',
    ):
        strict_integer(row[key], key)
    path = PREPARE_PATH if kind == PREPARE else ACCEPT_PATH
    registered_command('POST', path.format(task_id=row['task_id']), row['idempotency_key'])
    steps = operation_steps('CODING', kind)
    if (
        row['id'] != identity
        or row['resource_kind'] != 'TASK'
        or row['resource_id'] != row['task_id']
        or row['testing_task_id'] is not None
        or row['content_capture'] is not None
        or row['expected_state_version'] != fixed['expected_state_version']
        or type(row['steps']) is not list
        or len(row['steps']) != len(steps)
    ):
        raise ValueError('Original delivery operation differs')
    strict_enum(row['status'], 'status', STATES)
    for name in ('created_at', 'started_at', 'ended_at'):
        _time(row[name], nullable=name != 'created_at')
    for number, (step, name) in enumerate(zip(row['steps'], steps, strict=True), 1):
        exact(step, STEP_FIELDS)
        if (
            step['operation_id'] != identity
            or step['step_no'] != number
            or step['step_type'] != name
            or step['external_identity'] is not None
            or step['fixed_input'] != fixed
        ):
            raise ValueError('Original delivery step differs')
        strict_enum(step['status'], 'step.status', STATES)
        for timestamp in ('started_at', 'ended_at', 'last_observed_at'):
            _time(step[timestamp])
        if step['result_ref'] is not None:
            if kind != PREPARE or name != 'SAVE_PLAN' or step['status'] != 'SUCCEEDED':
                raise ValueError('Original delivery step disclosed private evidence')
            result = exact(step['result_ref'], ('delivery_plan_id',))
            strict_integer(result['delivery_plan_id'], 'delivery_plan_id')
    return row


def public_delivery_operation(connection, operation):
    row, fixed, steps = original_operation(connection, operation['id'], operation['operation_type'])
    plan_id = None
    if row['operation_type'] == PREPARE and steps[-1]['status'] == 'SUCCEEDED':
        plan = connection.execute(
            'SELECT id FROM code_delivery_plans WHERE operation_id=? AND task_id=?',
            (row['id'], row['task_id']),
        ).fetchone()
        if plan is None:
            raise ValueError('Published delivery plan is missing')
        plan_id = plan['id']
    return project_delivery_operation(
        {
            **dict(row),
            'fixed_input': fixed,
            'content_capture': None,
            'steps': [
                {
                    **dict(step),
                    'fixed_input': fixed,
                    'external_identity': None,
                    'result_ref': {'delivery_plan_id': plan_id}
                    if plan_id and step['step_type'] == 'SAVE_PLAN'
                    else None,
                }
                for step in steps
            ],
        },
        row['id'],
    )


async def _deliver(request, decoder):
    worker = getattr(request.app.state, 'walle_repository_registration', None)
    response = await handle_http(
        request,
        decoder,
        DeliveryAccepted,
        lambda runtime, parsed: accept_delivery_command(runtime, parsed, worker=worker),
    )
    if response.status_code == 202 and getattr(worker, 'accepts_delivery_previews', False):
        worker.wake()
    return response


@delivery_command_router.post(PREPARE_PATH)
async def prepare_delivery_http(request: Request):
    return await _deliver(request, PrepareDeliveryRequest)


@delivery_command_router.post(ACCEPT_PATH)
async def accept_delivery_http(request: Request):
    return await _deliver(request, AcceptDeliveryRequest)
