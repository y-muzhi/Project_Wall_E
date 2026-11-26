"""Public C32 fixed task creation."""

import re
from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.infrastructure.git_ref_protocol import RefProtocolError, branch_ref
from backend.app.shared.http_boundary import handle_http, idempotency_header, request_query
from backend.app.shared.validation import (
    InvalidInput,
    decimal_integer,
    object_fields,
    reject,
    strict_integer,
)

from .command_registry import RegisteredCommand, registered_command, validate_registered_success
from .costs import format_money, parse_money
from .repository_snapshot_reads import with_repository_request
from .task_creation import TASK_INPUT_FIELDS, create_fixed_task

PATH = '/api/v1/documents/{document_id}/code-tasks'
task_creation_router = APIRouter(redirect_slashes=False)


def is_document_code_tasks_path(path):
    return re.fullmatch(r'/api/v1/documents/[^/]+/code-tasks', path) is not None


def _materials(value, document_id):
    if type(value) is not list:
        reject('material_refs', 'INVALID_TYPE', '必须提供固定材料数组')
    seen = {document_id}
    materials = []
    for index, item in enumerate(value):
        field = f'material_refs[{index}]'
        keys = ('document_id', 'revision_id')
        item = object_fields(item, field, keys, keys)
        material_document = strict_integer(item['document_id'], field + '.document_id')
        revision = strict_integer(item['revision_id'], field + '.revision_id')
        if material_document in seen:
            reject(field + '.document_id', 'DUPLICATE_PARAMETER', '每份非主文档只可选择一个版本')
        seen.add(material_document)
        materials.append({'document_id': material_document, 'revision_id': revision})
    return tuple(materials)


@dataclass(frozen=True)
class CreateTaskRequest:
    document_id: int
    design_revision_id: int
    material_refs: tuple[dict, ...]
    repository_id: int
    base_snapshot_id: int
    target_branch: str
    execution_profile_version_id: int
    authorization_id: int
    budget_limit_cny: str
    normalized_budget: str
    command: RegisteredCommand
    body_fields = TASK_INPUT_FIELDS

    def business_input(self):
        return {
            **{field: getattr(self, field) for field in TASK_INPUT_FIELDS},
            'material_refs': list(self.material_refs),
        }

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        document_id = decimal_integer(request.path_params['document_id'], 'document_id')
        fields = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        key = idempotency_header(request, lowercase=True)
        command = registered_command('POST', PATH.format(document_id=document_id), key)
        try:
            branch = branch_ref(fields['target_branch'])
        except RefProtocolError:
            reject('target_branch', 'INVALID_FORMAT', '必须提供完整的本地分支引用')
        budget = fields['budget_limit_cny']
        try:
            amount = parse_money(budget, 'budget_limit_cny')
        except InvalidInput:
            raise
        except ValueError:
            reject('budget_limit_cny', 'OUT_OF_RANGE', '预算金额超出可处理范围')
        return cls(
            document_id,
            strict_integer(fields['design_revision_id'], 'design_revision_id'),
            _materials(fields['material_refs'], document_id),
            strict_integer(fields['repository_id'], 'repository_id'),
            strict_integer(fields['base_snapshot_id'], 'base_snapshot_id'),
            branch,
            strict_integer(fields['execution_profile_version_id'], 'execution_profile_version_id'),
            strict_integer(fields['authorization_id'], 'authorization_id'),
            budget,
            format_money(amount),
            command,
        )


class CreatedTaskResponse:
    error_contract = 'code'
    success_code = 'CREATED'
    status = 201
    errors = frozenset(
        {
            'INVALID_INPUT',
            'NOT_FOUND',
            'ACTIVE_TASK_EXISTS',
            'BASIS_NOT_CONFIRMED',
            'CONFIG_NOT_READY',
            'AUTHORIZATION_NOT_APPLICABLE',
            'CONTENT_NOT_READY',
            'STORAGE_UNAVAILABLE',
            'INTERNAL_ERROR',
            'OPERATION_CONFLICT',
            'OPERATION_IN_PROGRESS',
            'COMMAND_CLOSED',
            'PRECONDITION_FAILED',
        }
    )

    @staticmethod
    def project(data, request):
        validate_registered_success(request.command, data, 'CREATED', 201)
        for field in ('document_id', *TASK_INPUT_FIELDS[:-1]):
            expected = getattr(request, field)
            if field == 'material_refs':
                expected = list(expected)
            if data[field] != expected:
                raise ValueError('Created task differs from fixed request')
        if data['budget']['limit_cny'] != request.normalized_budget:
            raise ValueError('Created task budget differs from fixed request')
        return data, None


@task_creation_router.post(PATH)
async def create_task_http(request: Request):
    async def invoke(started, cancelled, worker):
        def create(runtime, parsed):
            started.set()
            return create_fixed_task(runtime, parsed, worker, cancelled)

        return await handle_http(request, CreateTaskRequest, CreatedTaskResponse, create)

    return await with_repository_request(request, invoke)
