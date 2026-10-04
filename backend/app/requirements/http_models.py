"""I01/I03 strict transport inputs and successful read projections."""
from dataclasses import dataclass
from fastapi import Request

from backend.app.shared.http_boundary import request_query
from backend.app.shared.http_projection import page, requirement, requirement_summary
from backend.app.shared.validation import decimal_integer
from .contracts import list_requirements_input, STATUSES, REQUIREMENT_TYPES


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
