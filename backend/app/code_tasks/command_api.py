"""Original-key control endpoints on the shared HTTP boundary; no external dispatch."""

from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.infrastructure.command_receipts import lookup_receipt
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input, request_key
from backend.app.shared.code_errors import error_fact
from backend.app.shared.http_boundary import handle_http, idempotency_header, request_query
from backend.app.shared.validation import MAX_SAFE_INTEGER, object_fields, reject, strict_enum

from .command_registry import RegisteredCommand, registered_command

_TEST_PLAN_COMMANDS = frozenset(
    (
        'APP-TEST-CMD-C06',
        'APP-TEST-CMD-C09',
        'APP-TEST-CMD-C12',
        'APP-TEST-CMD-C13',
        'APP-TEST-CMD-C14',
    )
)

COMMAND_CONTROL_PATHS = frozenset(
    {
        '/api/v1/command-intents/close',
        '/api/v1/code-command-receipts',
        '/api/v1/testing-command-receipts',
    }
)
command_router = APIRouter(prefix='/api/v1', redirect_slashes=False)


def parse_identity(method, path, key):
    strict_enum(method, 'method', ('POST',))
    normalized = request_key(key, 'request_key')
    if normalized != key:
        reject('request_key', 'INVALID_FORMAT', '必须为小写UUID v4')
    try:
        return registered_command(method, path, key)
    except ValueError:
        reject('path', 'INVALID_FORMAT', '必须为已登记的规范业务路径')


@dataclass(frozen=True)
class CloseCommandRequest:
    command: RegisteredCommand
    body_fields = ('method', 'path')

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        fields = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        key = idempotency_header(request, lowercase=True)
        return cls(parse_identity(fields['method'], fields['path'], key))


@dataclass(frozen=True)
class ReceiptRequest:
    command: RegisteredCommand
    module = 'CODE'

    @classmethod
    def parse(cls, request):
        if any(name.lower() == b'idempotency-key' for name, _ in request.scope.get('headers', [])):
            reject('Idempotency-Key', 'UNKNOWN_FIELD', '读取回执使用原request_key查询参数')
        names = ('method', 'path', 'request_key')
        query = object_fields(request_query(request, singles=names), 'query', names, names)
        command = parse_identity(query['method'], query['path'], query['request_key'])
        if command.route.module != cls.module:
            reject('path', 'INVALID_FORMAT', '原请求路径不属于此回执入口')
        return cls(command)


class TestingReceiptRequest(ReceiptRequest):
    module = 'TEST'


def project_receipt(value, command):
    fields = {
        'lookup_status',
        'record_status',
        'original_http_status',
        'original_outcome',
        'task_id',
        'testing_task_id',
        'operation_id',
    }
    if type(value) is not dict or set(value) != fields:
        raise ValueError('Incomplete command receipt')
    for field in ('task_id', 'testing_task_id', 'operation_id'):
        identity = value[field]
        if identity is not None and (
            type(identity) is not int or not 1 <= identity <= MAX_SAFE_INTEGER
        ):
            raise ValueError('Invalid command receipt identity')
    if (command.route.module == 'CODE' and value['testing_task_id'] is not None) or (
        command.route.module == 'TEST' and value['task_id'] is not None
    ):
        raise ValueError('Command receipt crosses modules')
    lookup = value['lookup_status']
    record = value['record_status']
    if lookup == 'FOUND':
        if record not in ('SUCCEEDED', 'REJECTED', 'CLOSED'):
            raise ValueError('FOUND requires an actual terminal record')
        outcome = value['original_outcome']
        if type(outcome) is not dict or set(outcome) != {'success', 'data', 'error'}:
            raise ValueError('Original outcome must be complete')
        status = value['original_http_status']
        if type(status) is not int:
            raise ValueError('Original outcome requires an HTTP status')
        if record == 'SUCCEEDED':
            if (
                outcome['success'] is not True
                or type(outcome['data']) is not dict
                or outcome['error'] is not None
                or not 200 <= status < 300
            ):
                raise ValueError('Original success shape differs')
            if command.route.capability_id in ('APP-TEST-CMD-C01', 'APP-TEST-CMD-C04'):
                from backend.app.testing.policies import (
                    project_authorization_view,
                    project_profile_view,
                )

                if status != 201 or any(
                    value[field] is not None
                    for field in ('task_id', 'testing_task_id', 'operation_id')
                ):
                    raise ValueError('Original Testing policy receipt crosses scope')
                if command.route.capability_id == 'APP-TEST-CMD-C01':
                    project_profile_view(outcome['data'])
                elif project_authorization_view(outcome['data'])['status'] != 'APPROVED_UNBOUND':
                    raise ValueError('Original Testing approval is not unbound')
            elif command.route.capability_id == 'APP-TEST-CMD-C15':
                from backend.app.testing.asset_api import project_created_pack

                if status != 201 or any(
                    value[field] is not None
                    for field in ('task_id', 'testing_task_id', 'operation_id')
                ):
                    raise ValueError('Original Testing pack creation crosses scope')
                project_created_pack(outcome['data'])
            elif command.route.capability_id == 'APP-TEST-CMD-C18':
                from backend.app.testing.asset_api import project_seal_receipt

                pack = command.route.match(command.path)['id']
                data = project_seal_receipt(outcome['data'], pack)
                if (
                    status != 202
                    or value['task_id'] is not None
                    or value['testing_task_id'] is not None
                    or value['operation_id'] != data['operation_id']
                ):
                    raise ValueError('Original Testing seal receipt crosses scope')
            elif command.route.capability_id in ('APP-TEST-CMD-C21', 'APP-TEST-CMD-C22'):
                from backend.app.testing.assets import project_pack

                pack = project_pack(outcome['data'])
                if (
                    status != 200
                    or pack['status']
                    != (
                        'PUBLISHED'
                        if command.route.capability_id == 'APP-TEST-CMD-C21'
                        else 'REVOKED'
                    )
                    or pack['id'] != command.route.match(command.path)['id']
                    or any(
                        value[field] is not None
                        for field in ('task_id', 'testing_task_id', 'operation_id')
                    )
                ):
                    raise ValueError('Original Testing pack control crosses scope')
            elif command.route.capability_id == 'APP-TEST-CMD-C23':
                from backend.app.testing.task_api import project_task_created

                data = project_task_created(outcome['data'])
                if (
                    status != 201
                    or value['task_id'] is not None
                    or value['testing_task_id'] != data['testing_task_id']
                    or value['operation_id'] is not None
                ):
                    raise ValueError('Original independent Testing task receipt crosses scope')
            elif command.route.capability_id in (
                'APP-TEST-CMD-C27',
                'APP-TEST-CMD-C29',
                'APP-TEST-CMD-C31',
            ):
                from backend.app.testing.task_stop import project_accepted
                from backend.app.testing.task_views import project_task_view

                task = command.route.match(command.path)['testing_task_id']
                if value['task_id'] is not None or value['testing_task_id'] != task:
                    raise ValueError('Original Testing control crosses owner scope')
                if status == 202 and command.route.capability_id == 'APP-TEST-CMD-C31':
                    data = project_accepted(outcome['data'], task)
                    if value['operation_id'] != data['operation_id']:
                        raise ValueError('Original Testing termination operation differs')
                elif status == 200 and value['operation_id'] is None:
                    row = project_task_view(outcome['data'], task)
                    if command.route.capability_id == 'APP-TEST-CMD-C31' and row['status'] not in (
                        'COMPLETED',
                        'TERMINATED',
                    ):
                        raise ValueError('Original terminal Testing receipt differs')
                else:
                    raise ValueError('Original Testing control status differs')
            elif command.route.capability_id == 'APP-TEST-CMD-C40':
                from backend.app.testing.report_api import project_review_receipt

                if any(
                    value[field] is not None
                    for field in ('task_id', 'testing_task_id', 'operation_id')
                ):
                    raise ValueError('Original Testing finding review crosses scope')
                project_review_receipt(command, outcome['data'], status)
            elif command.route.capability_id in _TEST_PLAN_COMMANDS:
                from backend.app.testing.plan_api import project_plan_receipt

                if any(
                    value[field] is not None
                    for field in ('task_id', 'testing_task_id', 'operation_id')
                ):
                    raise ValueError('Original Testing plan receipt crosses scope')
                project_plan_receipt(command, outcome['data'], status)
            elif command.route.capability_id == 'APP-CODE-CMD-C40':
                from .task_budget import validate_budget_result

                task_id = validate_budget_result(command, outcome['data'], status)
                if value['task_id'] not in (None, task_id) or value['operation_id'] is not None:
                    raise ValueError('Original budget receipt crosses task scope')
                value = {**value, 'task_id': task_id}
            elif command.route.capability_id == 'APP-CODE-CMD-C36':
                from .task_resume import validate_resume_receipt

                task_id = validate_resume_receipt(command, outcome['data'], status)
                if (
                    value['task_id'] != task_id
                    or value['operation_id'] != outcome['data']['operation_id']
                ):
                    raise ValueError('Original continuation receipt crosses task scope')
            elif command.route.capability_id in ('APP-CODE-CMD-C50', 'APP-CODE-CMD-C51'):
                from .task_check_api import validate_candidate_check_receipt

                task_id = validate_candidate_check_receipt(command, outcome['data'], status)
                if (
                    value['task_id'] != task_id
                    or value['operation_id'] != outcome['data']['operation_id']
                ):
                    raise ValueError('Original candidate check receipt crosses task scope')
            elif command.route.capability_id == 'APP-CODE-CMD-C38':
                from .task_role_reconciliation import validate_reconciliation_receipt

                task_id = validate_reconciliation_receipt(command, outcome['data'], status)
                if (
                    value['task_id'] != task_id
                    or value['operation_id'] != outcome['data']['operation_id']
                ):
                    raise ValueError('Original reconciliation receipt crosses task scope')
            elif command.route.capability_id == 'APP-CODE-CMD-C68':
                from .task_testing_publication import validate_publication_receipt

                task_id = validate_publication_receipt(command, outcome['data'], status)
                if value['task_id'] not in (None, task_id) or value['operation_id'] is not None:
                    raise ValueError('Original Coding publication receipt crosses task scope')
                value = {**value, 'task_id': task_id}
            elif command.route.capability_id in ('APP-CODE-CMD-C62', 'APP-CODE-CMD-C64'):
                from .task_delivery_api import project_delivery_receipt

                original = project_delivery_receipt(command, outcome['data'], status)
                if (value['task_id'], value['operation_id']) != (
                    original['task_id'],
                    original['operation_id'],
                ):
                    raise ValueError('Original Coding delivery receipt crosses scope')
            elif command.route.capability_id == 'APP-CODE-CMD-C59':
                from .task_repairs import project_repair_receipt

                repair = project_repair_receipt(command, outcome['data'], status)
                if (value['task_id'], value['operation_id']) != (
                    repair['task_id'],
                    repair['operation_id'],
                ):
                    raise ValueError('Original Coding repair receipt crosses scope')
            elif command.route.capability_id == 'APP-CODE-CMD-C69':
                from .task_report_link import project_link_receipt

                linked = project_link_receipt(command, outcome['data'], status)
                if value['task_id'] != linked['task_id'] or value['operation_id'] is not None:
                    raise ValueError('Original Coding report link receipt crosses scope')
            elif command.route.capability_id in ('APP-CODE-CMD-C46', 'APP-CODE-CMD-C47'):
                from .task_question_response import validate_question_receipt

                task_id = validate_question_receipt(command, outcome['data'], status)
                if (
                    value['task_id'] != task_id
                    or value['operation_id'] != outcome['data']['operation_id']
                ):
                    raise ValueError('Original question receipt crosses task scope')
            elif command.route.capability_id in ('APP-CODE-CMD-C48', 'APP-CODE-CMD-C49'):
                from .task_question_handoff import validate_handoff_receipt

                task_id = validate_handoff_receipt(command, outcome['data'], status)
                if value['task_id'] not in (None, task_id) or value['operation_id'] is not None:
                    raise ValueError('Original document handoff receipt crosses task scope')
                value = {**value, 'task_id': task_id}
        else:
            error = outcome['error']
            if (
                outcome['success'] is not False
                or outcome['data'] is not None
                or type(error) is not dict
                or set(error) != {'code', 'message', 'details'}
            ):
                raise ValueError('Original rejection shape differs')
            if command.route.capability_id == 'APP-TEST-CMD-C15':
                from backend.app.testing.asset_api import CreatedPack

                if error['code'] not in CreatedPack.errors:
                    raise ValueError('Original Testing pack rejection differs')
            elif command.route.capability_id == 'APP-TEST-CMD-C18':
                from backend.app.testing.asset_api import PackSealAccepted

                if error['code'] not in PackSealAccepted.errors:
                    raise ValueError('Original Testing seal rejection differs')
            elif command.route.capability_id == 'APP-TEST-CMD-C19':
                from backend.app.testing.asset_api import PackValidationAccepted

                if error['code'] not in PackValidationAccepted.errors:
                    raise ValueError('Original Testing pack validation rejection differs')
            elif command.route.capability_id in ('APP-TEST-CMD-C21', 'APP-TEST-CMD-C22'):
                from backend.app.testing.asset_api import PackPublished, PackRevoked

                policy = (
                    PackPublished
                    if command.route.capability_id == 'APP-TEST-CMD-C21'
                    else PackRevoked
                )
                if error['code'] not in policy.errors:
                    raise ValueError('Original Testing pack control rejection differs')
            elif command.route.capability_id == 'APP-TEST-CMD-C23':
                from backend.app.testing.task_api import TaskCreated

                if error['code'] not in TaskCreated.errors:
                    raise ValueError('Original Testing task creation rejection differs')
            elif command.route.capability_id in (
                'APP-TEST-CMD-C27',
                'APP-TEST-CMD-C29',
                'APP-TEST-CMD-C31',
            ):
                from backend.app.testing.task_api import TaskTerminated, TaskUpdated

                policy = (
                    TaskTerminated
                    if command.route.capability_id == 'APP-TEST-CMD-C31'
                    else TaskUpdated
                )
                if error['code'] not in policy.errors:
                    raise ValueError('Original Testing control rejection differs')
            elif command.route.capability_id == 'APP-TEST-CMD-C28':
                from backend.app.testing.task_api import RunAccepted

                if error['code'] not in RunAccepted.errors:
                    raise ValueError('Original Testing run rejection differs')
            elif command.route.capability_id == 'APP-TEST-CMD-C40':
                from backend.app.testing.report_api import FindingReviewed

                if error['code'] not in FindingReviewed.errors:
                    raise ValueError('Original Testing finding rejection differs')
            elif command.route.capability_id in _TEST_PLAN_COMMANDS:
                from backend.app.testing.plan_api import plan_command_errors

                if error['code'] not in plan_command_errors(command):
                    raise ValueError('Original Testing plan rejection differs')
            elif command.route.capability_id in ('APP-TEST-CMD-C01', 'APP-TEST-CMD-C04'):
                from backend.app.testing.policy_api import AuthorizationCreated, ProfileCreated

                policy = (
                    ProfileCreated
                    if command.route.capability_id == 'APP-TEST-CMD-C01'
                    else AuthorizationCreated
                )
                if error['code'] not in policy.errors:
                    raise ValueError('Original Testing policy rejection differs')
            elif command.route.capability_id in ('APP-CODE-CMD-C62', 'APP-CODE-CMD-C64'):
                from .task_delivery_api import DeliveryAccepted

                if error['code'] not in DeliveryAccepted.errors:
                    raise ValueError('Original Coding delivery rejection differs')
            elif command.route.capability_id == 'APP-CODE-CMD-C59':
                from .task_repairs import RepairAccepted

                if error['code'] not in RepairAccepted.errors:
                    raise ValueError('Original Coding repair rejection differs')
            elif command.route.capability_id == 'APP-CODE-CMD-C69':
                from .task_report_link import LinkReportResponse

                if error['code'] not in LinkReportResponse.errors:
                    raise ValueError('Original Coding report link rejection differs')
            fact = error_fact(error['code'], error['details'])
            if (
                fact[0] != status
                or fact[2] != error['message']
                or (record == 'CLOSED') != (error['code'] == 'COMMAND_CLOSED')
            ):
                raise ValueError('Original rejection facts differ')
            if record == 'CLOSED' and error['details']['path'] != command.path:
                raise ValueError('Close receipt differs from the original path')
    else:
        if (
            lookup not in ('IN_PROGRESS', 'NOT_FOUND', 'UNKNOWN')
            or value['original_http_status'] is not None
            or value['original_outcome'] is not None
        ):
            raise ValueError('Nonterminal lookup cannot invent an outcome')
        if (
            (lookup == 'IN_PROGRESS' and record != 'PROCESSING')
            or (lookup == 'NOT_FOUND' and record is not None)
            or (lookup == 'UNKNOWN' and record not in (None, 'PROCESSING'))
        ):
            raise ValueError('Lookup status and record differ')
        if lookup == 'NOT_FOUND' and any(
            value[field] is not None for field in ('task_id', 'testing_task_id', 'operation_id')
        ):
            raise ValueError('Missing record cannot invent associations')
    canonical_input(value)
    return value


class ReceiptResponse:
    error_contract = 'code'
    errors = frozenset(
        {
            'INVALID_INPUT',
            'NOT_FOUND',
            'PERMISSION_NOT_GRANTED',
            'CONTENT_NOT_READY',
            'CONFIG_NOT_READY',
            'STORAGE_UNAVAILABLE',
            'INTERNAL_ERROR',
        }
    )

    @staticmethod
    def project(data, request):
        return project_receipt(data, request.command), None


class TestingReceiptResponse(ReceiptResponse):
    errors = frozenset(
        {
            'INVALID_INPUT',
            'NOT_FOUND',
            'PERMISSION_NOT_GRANTED',
            'STORAGE_UNAVAILABLE',
            'INTERNAL_ERROR',
        }
    )


class CloseCommandResponse:
    error_contract = 'code'
    success_code = 'UPDATED'
    errors = frozenset(
        {
            'INVALID_INPUT',
            'NOT_FOUND',
            'AUTHORIZATION_NOT_APPLICABLE',
            'STORAGE_UNAVAILABLE',
            'INTERNAL_ERROR',
        }
    )

    @staticmethod
    def project(data, request):
        if type(data) is not dict or set(data) != {'close_status', 'original_receipt'}:
            raise ValueError('Incomplete original-key close receipt')
        receipt = project_receipt(data['original_receipt'], request.command)
        if data['close_status'] not in ('CLOSED', 'ALREADY_RECEIVED') or (
            data['close_status'] == 'CLOSED'
        ) != (receipt['record_status'] == 'CLOSED'):
            raise ValueError('Close status differs from the actual original record')
        return data, None


def read_original(runtime, parsed):
    if runtime.database.schema_release is None:
        raise StorageUnavailable('Explicit Schema200 initialization or maintenance is required')
    return {
        'code': 'READ_OK',
        'data': lookup_receipt(runtime.database, parsed.command.scope),
        'details': None,
    }


def close_original(runtime, parsed):
    if runtime.database.schema_release is None:
        raise StorageUnavailable('Explicit Schema200 initialization or maintenance is required')
    return {
        'code': 'UPDATED',
        'data': runtime.commands().close_command(parsed.command.scope),
        'details': None,
    }


@command_router.post('/command-intents/close')
async def close_http(request: Request):
    return await handle_http(request, CloseCommandRequest, CloseCommandResponse, close_original)


@command_router.get('/code-command-receipts')
async def coding_receipt_http(request: Request):
    return await handle_http(request, ReceiptRequest, ReceiptResponse, read_original)


@command_router.get('/testing-command-receipts')
async def testing_receipt_http(request: Request):
    return await handle_http(request, TestingReceiptRequest, TestingReceiptResponse, read_original)
