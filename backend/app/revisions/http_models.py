"""I24/I25 strict historical reads, with pagination confined to meta."""
from dataclasses import dataclass
from fastapi import Request
from backend.app.shared.http_boundary import request_query
from backend.app.shared.http_projection import page, revision
from backend.app.shared.validation import decimal_integer
from backend.app.shared.http_commands import CommandRequest
from .contracts import create_manual_revision_input


@dataclass(frozen=True)
class ListRevisionsRequest:
    requirement_id: int
    page: int

    @classmethod
    def parse(cls, request: Request):
        query = request_query(request, singles=('page',))
        return cls(decimal_integer(request.path_params['requirement_id'], 'requirement_id'), decimal_integer(query.get('page', '1'), 'page', maximum=100000))


class ListRevisionsResponse:
    errors = frozenset({'INVALID_INPUT', 'NOT_FOUND', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR'})

    @staticmethod
    def project(data, request):
        def item(value):
            projected = revision(value)
            if projected['requirement_id'] != request.requirement_id:
                raise ValueError('Revision list crossed requirement ownership')
            return projected
        return page(data, item, request.page)


@dataclass(frozen=True)
class GetRevisionRequest:
    revision_id: int

    @classmethod
    def parse(cls, request: Request):
        request_query(request)
        return cls(decimal_integer(request.path_params['revision_id'], 'revision_id'))


class GetRevisionResponse:
    errors = ListRevisionsResponse.errors

    @staticmethod
    def project(data, request):
        value = revision(data, full=True)
        if value['id'] != request.revision_id:
            raise ValueError('Read returned another revision')
        return value, None


class CreateManualRevisionRequest(CommandRequest):
    body_fields = ('expected_version', 'description')
    mandatory = ('expected_version',)
    rename = {'expected_version': 'expected_content_version'}
    validate = staticmethod(create_manual_revision_input)
    normalize = staticmethod(lambda payload, validated: {**validated.current.business_input(), 'idempotency_key': validated.current.idempotency_key, 'description': validated.description})


class CreateManualRevisionResponse:
    success_code = 'REVISION_CREATED'
    status = 201
    errors = ListRevisionsResponse.errors | {'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'CONTENT_VERSION_CONFLICT', 'DOCUMENT_INVALID', 'IDEMPOTENCY_CONFLICT', 'REQUEST_IN_PROGRESS', 'CAPACITY_EXHAUSTED'}

    @staticmethod
    def project(data, request):
        value = revision(data)
        if value['requirement_id'] != request.payload['requirement_id'] or value['revision_type'] != 'MANUAL' or value['source_content_version'] != request.payload['expected_content_version']:
            raise ValueError('Manual revision response contradicts the actual submitted source')
        return value, None
