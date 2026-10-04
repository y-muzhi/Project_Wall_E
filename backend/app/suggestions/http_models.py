"""I20 exact input and full same-snapshot batch projection."""
from dataclasses import dataclass
from backend.app.shared.http_boundary import request_query
from backend.app.shared.validation import decimal_integer
from .contracts import batch_read_model
from .contracts import discard_batch_input, batch_metadata, counts_model
from backend.app.shared.http_boundary import idempotency_header
from backend.app.shared.validation import object_fields


@dataclass(frozen=True)
class GetBatchRequest:
    batch_id: int

    @classmethod
    def parse(cls, request):
        request_query(request)
        return cls(decimal_integer(request.path_params['batch_id'], 'batch_id'))


class GetBatchResponse:
    errors = frozenset({'INVALID_INPUT', 'NOT_FOUND', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR'})

    @staticmethod
    def project(data, request):
        value = batch_read_model(data)
        if value['id'] != request.batch_id:
            raise ValueError('Batch response belongs to another request')
        return value, None


@dataclass(frozen=True)
class DiscardBatchRequest:
    payload: dict

    @classmethod
    def parse(cls, request):
        request_query(request)
        payload = {'batch_id': decimal_integer(request.path_params['batch_id'], 'batch_id'), 'idempotency_key': idempotency_header(request)}
        validated = discard_batch_input(payload)
        return cls({**validated.business_input(), 'idempotency_key': validated.idempotency_key})


class DiscardBatchResponse:
    success_code = 'BATCH_DISCARDED'
    errors = GetBatchResponse.errors | {'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'IDEMPOTENCY_CONFLICT', 'REQUEST_IN_PROGRESS'}

    @staticmethod
    def project(data, request):
        value = object_fields(data, 'data', ('batch', 'counts'), ('batch', 'counts'))
        batch = batch_metadata(value['batch']); counts = counts_model(value['counts'])
        if batch['id'] != request.payload['batch_id'] or batch['status'] != 'DISCARDED':
            raise ValueError('Discard response must reference the actual discarded batch')
        return {'batch': batch, 'counts': counts}, None
