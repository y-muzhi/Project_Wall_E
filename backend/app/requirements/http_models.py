"""V1.5 requirement HTTP contracts on the existing /api/v1 routes."""

from dataclasses import dataclass
from fastapi import Request

from backend.app.shared.http_boundary import request_query
from backend.app.shared.http_commands import CommandRequest
from backend.app.shared.http_projection import page, requirement, requirement_summary, exact
from backend.app.shared.validation import decimal_integer, strict_enum, strict_integer
from .contracts import (
    list_requirements_input,
    STATUSES,
    REQUIREMENT_TYPES,
    create_requirement_input,
    update_requirement_input,
)


@dataclass(frozen=True)
class ListRequirementsRequest:
    payload: dict

    @classmethod
    def parse(cls, request: Request):
        payload = request_query(
            request,
            singles=('keyword', 'page'),
            arrays={'status': STATUSES, 'requirement_type': REQUIREMENT_TYPES},
        )
        if 'page' in payload:
            payload['page'] = decimal_integer(payload['page'], 'page', maximum=100000)
        validated = list_requirements_input(payload)
        return cls(
            {
                'keyword': validated.keyword,
                'status': list(validated.status),
                'requirement_type': list(validated.requirement_type),
                'page': validated.page,
            }
        )


class ListRequirementsResponse:
    errors = frozenset({'INVALID_INPUT', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR'})

    @staticmethod
    def project(data, request):
        return page(data, requirement_summary, request.payload['page'])


@dataclass(frozen=True)
class GetRequirementRequest:
    requirement_id: int
    expand: str | None = None

    @classmethod
    def parse(cls, request: Request):
        query = request_query(request, singles=('expand',))
        expand = (
            strict_enum(query['expand'], 'expand', ('discussion',)) if 'expand' in query else None
        )
        return cls(decimal_integer(request.path_params['requirement_id'], 'requirement_id'), expand)


class GetRequirementResponse:
    errors = ListRequirementsResponse.errors | {'NOT_FOUND'}

    @staticmethod
    def project(data, request):
        from .queries import project_detail

        value = project_detail(data, request.expand)
        if value['requirement']['id'] != request.requirement_id:
            raise ValueError('Read returned a different requirement')
        return value, None


class UpdateRequirementRequest(CommandRequest):
    body_fields = (
        'expected_metadata_version',
        'changes',
        'expected_discussion_version',
        'discussion_command',
    )
    mandatory = ()

    @staticmethod
    def validate(payload):
        from .contracts import discussion_command_input

        return (
            discussion_command_input(payload)
            if {'expected_discussion_version', 'discussion_command'} & payload.keys()
            else update_requirement_input(payload)
        )

    normalize = staticmethod(
        lambda payload, validated: {
            **validated.business_input(),
            'idempotency_key': validated.idempotency_key,
        }
    )


class UpdateRequirementResponse:
    success_codes = ('UPDATED', 'NO_CHANGE')
    errors = GetRequirementResponse.errors | {
        'METADATA_VERSION_CONFLICT',
        'DISCUSSION_VERSION_CONFLICT',
        'STATE_CONFLICT',
        'WORK_STATE_CONFLICT',
        'WORK_STATE_INCONSISTENT',
        'SOURCE_INVALID',
        'SCOPE_INVALID',
        'IDEMPOTENCY_CONFLICT',
        'REQUEST_IN_PROGRESS',
        'CAPACITY_EXHAUSTED',
    }

    @staticmethod
    def project(data, request):
        if 'discussion_command' in request.payload:
            from .discussion import validate_discussion

            value = exact(data, ('requirement_id', 'discussion_version', 'discussion'))
            if value['requirement_id'] != request.payload['requirement_id']:
                raise ValueError('Discussion result belongs to another requirement')
            strict_integer(value['discussion_version'], 'discussion_version')
            value['discussion'] = validate_discussion(value['discussion'])
            return value, None
        value = requirement(data)
        if value['id'] != request.payload['requirement_id']:
            raise ValueError('Write returned another requirement')
        return value, None


class CompleteInitializationRequest(CommandRequest):
    validate = staticmethod(lambda payload: payload)


class CompleteInitializationResponse:
    errors = frozenset({'INVALID_INPUT', 'STATE_CONFLICT', 'INTERNAL_ERROR'})


class CompleteRequirementRequest(CommandRequest):
    body_fields = ('expected_metadata_version',)
    mandatory = body_fields
    status_value = 'COMPLETED'

    @classmethod
    def validate(cls, payload):
        return update_requirement_input({**payload, 'changes': {'status': cls.status_value}})


class CompleteRequirementResponse(UpdateRequirementResponse):
    pass


class ReactivateRequirementRequest(CompleteRequirementRequest):
    status_value = 'PLANNING'


class ReactivateRequirementResponse(UpdateRequirementResponse):
    pass


class CreateRequirementRequest(CommandRequest):
    body_fields = ('title', 'requirement_type', 'initial_idea')
    mandatory = body_fields
    uses_requirement_path = False
    validate = staticmethod(create_requirement_input)
    normalize = staticmethod(
        lambda payload, validated: {
            **validated.business_input(),
            'idempotency_key': validated.idempotency_key,
        }
    )


class CreateRequirementResponse:
    success_code = 'CREATED'
    status = 201
    errors = frozenset(
        {
            'INVALID_INPUT',
            'CONFIG_INVALID',
            'IDEMPOTENCY_CONFLICT',
            'REQUEST_IN_PROGRESS',
            'STORAGE_UNAVAILABLE',
            'INTERNAL_ERROR',
            'CAPACITY_EXHAUSTED',
        }
    )

    @staticmethod
    def project(data, request):
        value = exact(data, ('requirement', 'initial_message_id', 'documents'))
        root = requirement(value['requirement'])
        strict_integer(value['initial_message_id'], 'initial_message_id')
        if (
            root['status'] != 'PLANNING'
            or root['document_work_state'] != 'IDLE'
            or value['documents'] != []
            or root['initial_message_id'] != value['initial_message_id']
            or any(root[field] != request.payload[field] for field in ('title', 'requirement_type'))
        ):
            raise ValueError('Created resource contradicts creation input')
        return {
            'requirement': root,
            'initial_message_id': value['initial_message_id'],
            'documents': [],
        }, None
