"""I16 canonical status input and the complete public status model."""
from dataclasses import dataclass
from backend.app.shared.http_boundary import request_query
from backend.app.shared.validation import decimal_integer
from .contracts import guide_run_read_model
from backend.app.shared.http_boundary import idempotency_header
from .contracts import cancel_guide_run_input, guide_run_accepted
from .contracts import list_guide_runs_input, guide_run_summary, GUIDE_STATUSES
from backend.app.shared.http_projection import page


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


@dataclass(frozen=True)
class CancelGuideRunRequest:
    payload: dict

    @classmethod
    def parse(cls, request):
        request_query(request)
        payload = {'guide_run_id': decimal_integer(request.path_params['guide_run_id'], 'guide_run_id'), 'idempotency_key': idempotency_header(request)}
        cancel_guide_run_input(payload)
        return cls(payload)


class CancelGuideRunResponse:
    success_code = 'GUIDE_CANCELLED'
    errors = frozenset({'INVALID_INPUT', 'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'IDEMPOTENCY_CONFLICT', 'REQUEST_IN_PROGRESS', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR'})

    @staticmethod
    def project(data, request):
        value = guide_run_accepted(data)
        if value['id'] != request.payload['guide_run_id'] or value['status'] != 'CANCELLED' or value['current_step'] != 'FINISHED':
            raise ValueError('Cancellation response must reference the actual cancelled run')
        return value, None


@dataclass(frozen=True)
class ListGuideRunsRequest:
    payload: dict

    @classmethod
    def parse(cls, request):
        payload = request_query(request, singles=('page',), arrays={'status': GUIDE_STATUSES, 'action_type': ('INITIALIZE', 'ASK', 'REVIEW', 'MODIFY')})
        payload['requirement_id'] = decimal_integer(request.path_params['requirement_id'], 'requirement_id')
        if 'page' in payload:
            payload['page'] = decimal_integer(payload['page'], 'page', maximum=100000)
        validated = list_guide_runs_input(payload)
        return cls({'requirement_id': validated.requirement_id, 'page': validated.page, 'status': list(validated.status), 'action_type': list(validated.action_type)})


class ListGuideRunsResponse:
    errors = GetGuideRunResponse.errors

    @staticmethod
    def project(data, request):
        def project_item(item):
            value = guide_run_summary(item)
            if value['requirement_id'] != request.payload['requirement_id']:
                raise ValueError('History response contains another requirement')
            return value
        return page(data, project_item, request.payload['page'])
