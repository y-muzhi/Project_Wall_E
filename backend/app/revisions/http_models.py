"""I24/I25 strict historical reads, with pagination confined to meta."""

from dataclasses import dataclass
from fastapi import Request
from backend.app.shared.http_boundary import request_query
from backend.app.shared.http_projection import page, revision
from backend.app.shared.validation import decimal_integer
from backend.app.shared.http_commands import CommandRequest
from .contracts import create_manual_revision_input, create_manual_revision_result


@dataclass(frozen=True)
class ListRevisionsRequest:
    requirement_id: int
    document_id: int
    page: int

    @classmethod
    def parse(cls, request: Request):
        query = request_query(request, singles=('document_id', 'page'))
        return cls(
            decimal_integer(request.path_params['requirement_id'], 'requirement_id'),
            decimal_integer(query.get('document_id'), 'document_id'),
            decimal_integer(query.get('page', '1'), 'page', maximum=100000),
        )


class ListRevisionsResponse:
    errors = frozenset({'INVALID_INPUT', 'NOT_FOUND', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR'})

    @staticmethod
    def project(data, request):
        def item(value):
            projected = revision(value)
            if (
                projected['requirement_id'] != request.requirement_id
                or projected['document_id'] != request.document_id
            ):
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
    body_fields = ('document_id', 'expected_version', 'description')
    mandatory = ('document_id', 'expected_version')
    validate = staticmethod(create_manual_revision_input)
    normalize = staticmethod(
        lambda payload, validated: {
            **validated.business_input(),
            'idempotency_key': validated.idempotency_key,
        }
    )


class CreateManualRevisionResponse:
    success_code = 'VERSION_MARKED'
    status = 200
    errors = ListRevisionsResponse.errors | {
        'STATE_CONFLICT',
        'WORK_STATE_CONFLICT',
        'WORK_STATE_INCONSISTENT',
        'CONTENT_VERSION_CONFLICT',
        'DOCUMENT_INVALID',
        'IDEMPOTENCY_CONFLICT',
        'REQUEST_IN_PROGRESS',
        'CAPACITY_EXHAUSTED',
    }

    @staticmethod
    def project(data, request):
        return create_manual_revision_result(data), None
