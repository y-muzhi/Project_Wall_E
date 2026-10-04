"""I16 canonical status input and the complete public status model."""
from dataclasses import dataclass
from backend.app.shared.http_boundary import request_query
from backend.app.shared.validation import decimal_integer
from .contracts import guide_run_read_model


@dataclass(frozen=True)
class GetGuideRunRequest:
    guide_run_id: int

    @classmethod
    def parse(cls, request):
        request_query(request)
        return cls(decimal_integer(request.path_params['guide_run_id'], 'guide_run_id'))


class GetGuideRunResponse:
    errors = frozenset({'INVALID_INPUT', 'NOT_FOUND', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR'})

    @staticmethod
    def project(data, request):
        value = guide_run_read_model(data)
        if value['id'] != request.guide_run_id:
            raise ValueError('Run status response belongs to another request')
        return value, None
