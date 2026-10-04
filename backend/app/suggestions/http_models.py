"""I20 exact input and full same-snapshot batch projection."""
from dataclasses import dataclass
from backend.app.shared.http_boundary import request_query
from backend.app.shared.validation import decimal_integer
from .contracts import batch_read_model
from .contracts import discard_batch_input, batch_metadata, counts_model
from backend.app.shared.http_boundary import idempotency_header
from backend.app.shared.validation import object_fields
from .contracts import decide_suggestion_input, suggestion_read_model
from .contracts import complete_batch_input
from backend.app.shared.http_projection import document


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


@dataclass(frozen=True)
class DecideSuggestionRequest:
    payload: dict
    body_fields = ('decision', 'edited_content')

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        payload = dict(object_fields(body, 'body', cls.body_fields, ('decision',)))
        payload.update(suggestion_id=decimal_integer(request.path_params['suggestion_id'], 'suggestion_id'), idempotency_key=idempotency_header(request))
        validated = decide_suggestion_input(payload)
        return cls({**validated.business_input(), 'idempotency_key': validated.idempotency_key})


class DecideSuggestionResponse:
    success_code = 'SUGGESTION_DECIDED'
    errors = DiscardBatchResponse.errors | {'PATCH_INVALID'}

    @staticmethod
    def project(data, request):
        value = object_fields(data, 'data', ('suggestion', 'counts'), ('suggestion', 'counts'))
        suggestion = suggestion_read_model(value['suggestion']); counts = counts_model(value['counts'])
        if suggestion['id'] != request.payload['suggestion_id'] or suggestion['status'] != request.payload['decision'] or suggestion['user_edited_content'] != request.payload['edited_content'] or counts[suggestion['status'].lower()] < 1:
            raise ValueError('Decision response must reflect the actual accepted action')
        return {'suggestion': suggestion, 'counts': counts}, None


@dataclass(frozen=True)
class CompleteBatchRequest:
    payload: dict
    body_fields = ('expected_content_version',)

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        payload = dict(object_fields(body, 'body', cls.body_fields, cls.body_fields))
        payload.update(batch_id=decimal_integer(request.path_params['batch_id'], 'batch_id'), idempotency_key=idempotency_header(request))
        validated = complete_batch_input(payload)
        return cls({**validated.business_input(), 'idempotency_key': validated.idempotency_key})


class CompleteBatchResponse:
    success_codes = ('BATCH_APPLIED', 'BATCH_NO_CHANGE')
    errors = DiscardBatchResponse.errors | {'CONTENT_VERSION_CONFLICT', 'BATCH_PENDING', 'TARGET_STALE', 'PATCH_INVALID', 'DOCUMENT_INVALID', 'CAPACITY_EXHAUSTED'}

    @staticmethod
    def project(data, request):
        value = object_fields(data, 'data', ('batch', 'counts', 'current_document'), ('batch', 'counts', 'current_document'))
        batch = batch_metadata(value['batch']); counts = counts_model(value['counts']); current = document(value['current_document'], 'CURRENT')
        if batch['id'] != request.payload['batch_id'] or batch['status'] != 'COMPLETED' or counts['pending'] or batch['base_content_version'] != request.payload['expected_content_version'] or current['requirement_id'] != batch['requirement_id'] or current['content_version'] != (batch['applied_content_version'] or batch['base_content_version']):
            raise ValueError('Completion projection must preserve actual committed batch/document effects')
        return {'batch': batch, 'counts': counts, 'current_document': current}, None
