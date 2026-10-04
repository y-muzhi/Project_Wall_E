"""I24/I25 strict historical reads, with pagination confined to meta."""
from dataclasses import dataclass
from fastapi import Request
from backend.app.shared.http_boundary import request_query
from backend.app.shared.http_projection import page, revision
from backend.app.shared.validation import decimal_integer


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
