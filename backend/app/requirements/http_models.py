"""I01/I03 strict transport inputs and successful read projections."""
from dataclasses import dataclass
from fastapi import Request

from backend.app.shared.http_boundary import request_query
from backend.app.shared.http_projection import page, requirement, requirement_summary
from backend.app.shared.validation import decimal_integer
from .contracts import list_requirements_input, STATUSES, REQUIREMENT_TYPES
from .contracts import update_requirement_input, complete_initialization_input, complete_requirement_input, reactivate_requirement_input
from .contracts import create_requirement_input
from backend.app.shared.http_commands import CommandRequest
from backend.app.shared.http_projection import exact, revision
from backend.app.shared.validation import strict_integer


@dataclass(frozen=True)
class ListRequirementsRequest:
    payload: dict

    @classmethod
    def parse(cls, request: Request):
        payload = request_query(request, singles=('keyword', 'page'), arrays={'status': STATUSES, 'requirement_type': REQUIREMENT_TYPES})
        if 'page' in payload:
            payload['page'] = decimal_integer(payload['page'], 'page', maximum=100000)
        validated = list_requirements_input(payload)
        return cls({'keyword': validated.keyword, 'status': list(validated.status), 'requirement_type': list(validated.requirement_type), 'page': validated.page})


class ListRequirementsResponse:
    errors = frozenset({'INVALID_INPUT', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR'})

    @staticmethod
    def project(data, request):
        return page(data, requirement_summary, request.payload['page'])


@dataclass(frozen=True)
class GetRequirementRequest:
    requirement_id: int

    @classmethod
    def parse(cls, request: Request):
        request_query(request)
        return cls(decimal_integer(request.path_params['requirement_id'], 'requirement_id'))


class GetRequirementResponse:
    errors = ListRequirementsResponse.errors | {'NOT_FOUND'}

    @staticmethod
    def project(data, request):
        value = requirement(data)
        if value['id'] != request.requirement_id:
            raise ValueError('Read returned a different requirement')
        return value, None


class UpdateRequirementRequest(CommandRequest):
    body_fields = ('title',)
    uses_key = False
    validate = staticmethod(update_requirement_input)
    normalize = staticmethod(lambda payload, validated: {'requirement_id': validated.requirement_id, **validated.changes})


class UpdateRequirementResponse(GetRequirementResponse):
    success_code = 'UPDATED'
    errors = GetRequirementResponse.errors | {'STATE_CONFLICT', 'WORK_STATE_CONFLICT'}

    @staticmethod
    def project(data, request):
        value = requirement(data)
        if value['id'] != request.payload['requirement_id']:
            raise ValueError('Write returned another requirement')
        return value, None


class CompleteInitializationRequest(CommandRequest):
    body_fields = ('expected_content_version',)
    mandatory = body_fields
    validate = staticmethod(complete_initialization_input)


class CompleteInitializationResponse:
    success_code = 'INITIALIZATION_COMPLETED'
    errors = UpdateRequirementResponse.errors | {'WORK_STATE_INCONSISTENT', 'CONTENT_VERSION_CONFLICT', 'DOCUMENT_INVALID', 'TEMPLATE_INVALID', 'IDEMPOTENCY_CONFLICT', 'REQUEST_IN_PROGRESS', 'CAPACITY_EXHAUSTED'}

    @staticmethod
    def project(data, request):
        value = exact(data, ('requirement', 'baseline_revision', 'current_document'))
        root = requirement(value['requirement'])
        baseline = revision(value['baseline_revision'])
        current = exact(value['current_document'], ('id', 'content_version'))
        for field in current:
            strict_integer(current[field], field)
        if root['id'] != request.payload['requirement_id'] or root['status'] != 'ACTIVE' or root['document_work_state'] != 'IDLE' or baseline['requirement_id'] != root['id'] or baseline['revision_type'] != 'BASELINE' or baseline['source_content_version'] != request.payload['expected_content_version'] or current['content_version'] != request.payload['expected_content_version']:
            raise ValueError('Initialization response contradicts the submitted target')
        return {'requirement': root, 'baseline_revision': baseline, 'current_document': current}, None


class CompleteRequirementRequest(CommandRequest):
    body_fields = ('expected_version',)
    mandatory = body_fields
    rename = {'expected_version': 'expected_content_version'}
    validate = staticmethod(complete_requirement_input)


class CompleteRequirementResponse(UpdateRequirementResponse):
    success_code = 'REQUIREMENT_COMPLETED'
    errors = UpdateRequirementResponse.errors | {'WORK_STATE_INCONSISTENT', 'CONTENT_VERSION_CONFLICT', 'IDEMPOTENCY_CONFLICT', 'REQUEST_IN_PROGRESS'}

    @staticmethod
    def project(data, request):
        value, pagination = UpdateRequirementResponse.project(data, request)
        if value['status'] != 'COMPLETED' or value['document_work_state'] != 'IDLE':
            raise ValueError('Requirement completion response has wrong lifecycle')
        return value, pagination


class ReactivateRequirementRequest(CommandRequest):
    validate = staticmethod(reactivate_requirement_input)


class ReactivateRequirementResponse(UpdateRequirementResponse):
    success_code = 'REACTIVATED'
    errors = UpdateRequirementResponse.errors | {'WORK_STATE_INCONSISTENT', 'IDEMPOTENCY_CONFLICT', 'REQUEST_IN_PROGRESS'}

    @staticmethod
    def project(data, request):
        value, pagination = UpdateRequirementResponse.project(data, request)
        if value['status'] != 'ACTIVE' or value['document_work_state'] != 'IDLE':
            raise ValueError('Reactivation response has wrong lifecycle')
        return value, pagination
class CreateRequirementRequest(CommandRequest):
    body_fields = ('title', 'requirement_type', 'template_key', 'template_version', 'initial_idea', 'initialization_mode')
    mandatory = body_fields
    uses_requirement_path = False
    validate = staticmethod(create_requirement_input)

    @staticmethod
    def normalize(payload, validated):
        return {**validated.business_input(), 'idempotency_key': validated.idempotency_key}


class CreateRequirementResponse:
    success_code = 'CREATED'
    status = 201
    errors = frozenset({'INVALID_INPUT', 'TEMPLATE_INVALID', 'CONFIG_INVALID', 'IDEMPOTENCY_CONFLICT', 'REQUEST_IN_PROGRESS', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR', 'CAPACITY_EXHAUSTED'})

    @staticmethod
    def project(data, request):
        value = exact(data, ('requirement', 'current_document_id', 'guide_run_id'))
        root = requirement(value['requirement'])
        for field in ('current_document_id', 'guide_run_id'):
            strict_integer(value[field], field)
        if root['status'] != 'INITIALIZING' or root['document_work_state'] != 'GUIDE_ACTIVE' or root['active_operation_type'] != 'GUIDE_RUN' or root['active_operation_id'] != value['guide_run_id'] or any(root[field] != request.payload[field] for field in ('title', 'requirement_type', 'initialization_mode', 'template_key', 'template_version')):
            raise ValueError('Created resource contradicts accepted creation input')
        return {'requirement': root, 'current_document_id': value['current_document_id'], 'guide_run_id': value['guide_run_id']}, None
