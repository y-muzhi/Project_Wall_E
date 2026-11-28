"""I20 exact input and full same-snapshot batch projection."""

from dataclasses import dataclass
from backend.app.shared.http_boundary import request_query
from backend.app.shared.validation import decimal_integer, reject, strict_integer
from .contracts import batch_read_model
from .contracts import discard_batch_input, batch_metadata, counts_model
from backend.app.shared.http_boundary import idempotency_header
from backend.app.shared.validation import object_fields
from .contracts import decide_suggestion_input, suggestion_read_model
from .contracts import complete_batch_input, decide_group_input
from .contracts import accept_pending_input
from backend.app.shared.http_projection import document


@dataclass(frozen=True)
class GetPendingDocumentBatchRequest:
    requirement_id: int
    document_id: int

    @classmethod
    def parse(cls, request):
        request_query(request)
        return cls(
            decimal_integer(request.path_params['requirement_id'], 'requirement_id'),
            decimal_integer(request.path_params['document_id'], 'document_id'),
        )


class GetPendingDocumentBatchResponse:
    errors = frozenset({'INVALID_INPUT', 'NOT_FOUND', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR'})

    @staticmethod
    def project(data, request):
        fields = ('requirement_id', 'document_id', 'batch_id')
        value = object_fields(data, 'data', fields, fields)
        if (
            strict_integer(value['requirement_id'], 'requirement_id') != request.requirement_id
            or strict_integer(value['document_id'], 'document_id') != request.document_id
        ):
            raise ValueError('Pending suggestion belongs to another document')
        if value['batch_id'] is not None:
            strict_integer(value['batch_id'], 'batch_id')
        return value, None


@dataclass(frozen=True)
class GetBatchRequest:
    batch_id: int
    include_review: bool

    @classmethod
    def parse(cls, request):
        fields = request_query(request, singles=('include_review',))
        include = fields.get('include_review')
        if include not in (None, '1'):
            reject('include_review', 'INVALID_FORMAT', '如需读取审阅结果，请使用 1')
        return cls(decimal_integer(request.path_params['batch_id'], 'batch_id'), include == '1')


class GetBatchResponse:
    errors = frozenset({'INVALID_INPUT', 'NOT_FOUND', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR'})

    @staticmethod
    def project(data, request):
        if request.include_review:
            value = object_fields(data, 'data', ('batch', 'review'), ('batch', 'review'))
            batch = batch_read_model(value['batch'])
            if batch['id'] != request.batch_id:
                raise ValueError('Review belongs to another batch')
            return {'batch': batch, 'review': value['review']}, None
        value = batch_read_model(data)
        if value['id'] != request.batch_id:
            raise ValueError('Batch response belongs to another request')
        return value, None


@dataclass(frozen=True)
class AcceptPendingRequest:
    payload: dict
    body_fields = ('expected_content_version', 'expected_pending_ids')

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        fields = cls.body_fields
        value = object_fields(body, 'body', fields, fields)
        parsed = accept_pending_input(
            {
                **value,
                'batch_id': decimal_integer(request.path_params['batch_id'], 'batch_id'),
                'idempotency_key': idempotency_header(request),
            }
        )
        return cls({**parsed.business_input(), 'idempotency_key': parsed.idempotency_key})


class AcceptPendingResponse:
    success_code = 'SUGGESTIONS_ACCEPTED'
    errors = frozenset(
        {
            'INVALID_INPUT',
            'NOT_FOUND',
            'STATE_CONFLICT',
            'WORK_STATE_CONFLICT',
            'WORK_STATE_INCONSISTENT',
            'CONTENT_VERSION_CONFLICT',
            'TARGET_STALE',
            'PATCH_INVALID',
            'IDEMPOTENCY_CONFLICT',
            'REQUEST_IN_PROGRESS',
            'STORAGE_UNAVAILABLE',
            'INTERNAL_ERROR',
        }
    )

    @staticmethod
    def project(data, request):
        value = object_fields(
            data, 'data', ('batch', 'accepted_suggestion_ids'), ('batch', 'accepted_suggestion_ids')
        )
        batch = batch_read_model(value['batch'])
        ids = value['accepted_suggestion_ids']
        if (
            batch['id'] != request.payload['batch_id']
            or batch['status'] != 'PENDING'
            or batch['counts']['pending'] != 0
            or batch['base_content_version'] != request.payload['expected_content_version']
            or ids != request.payload['expected_pending_ids']
            or any(
                next(
                    (item['status'] for item in batch['suggestions'] if item['id'] == identity),
                    None,
                )
                != 'ACCEPTED'
                for identity in ids
            )
        ):
            raise ValueError('Bulk acceptance must preserve actual same-batch decisions')
        return {'batch': batch, 'accepted_suggestion_ids': ids}, None


@dataclass(frozen=True)
class DiscardBatchRequest:
    payload: dict

    @classmethod
    def parse(cls, request):
        request_query(request)
        payload = {
            'batch_id': decimal_integer(request.path_params['batch_id'], 'batch_id'),
            'idempotency_key': idempotency_header(request),
        }
        validated = discard_batch_input(payload)
        return cls({**validated.business_input(), 'idempotency_key': validated.idempotency_key})


class DiscardBatchResponse:
    success_code = 'BATCH_DISCARDED'
    errors = GetBatchResponse.errors | {
        'STATE_CONFLICT',
        'CONTENT_VERSION_CONFLICT',
        'WORK_STATE_CONFLICT',
        'WORK_STATE_INCONSISTENT',
        'IDEMPOTENCY_CONFLICT',
        'REQUEST_IN_PROGRESS',
    }

    @staticmethod
    def project(data, request):
        value = object_fields(data, 'data', ('batch', 'counts'), ('batch', 'counts'))
        batch = batch_metadata(value['batch'])
        counts = counts_model(value['counts'])
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
        payload.update(
            suggestion_id=decimal_integer(request.path_params['suggestion_id'], 'suggestion_id'),
            idempotency_key=idempotency_header(request),
        )
        validated = decide_suggestion_input(payload)
        return cls({**validated.business_input(), 'idempotency_key': validated.idempotency_key})


class DecideSuggestionResponse:
    success_code = 'SUGGESTION_DECIDED'
    errors = DiscardBatchResponse.errors | {
        'PATCH_INVALID',
        'TARGET_STALE',
        'CONTENT_VERSION_CONFLICT',
    }

    @staticmethod
    def project(data, request):
        value = object_fields(data, 'data', ('suggestion', 'counts'), ('suggestion', 'counts'))
        suggestion = suggestion_read_model(value['suggestion'])
        counts = counts_model(value['counts'])
        if (
            suggestion['id'] != request.payload['suggestion_id']
            or suggestion['status'] != request.payload['decision']
            or suggestion['user_edited_content'] != request.payload.get('edited_content')
            or counts[suggestion['status'].lower()] < 1
        ):
            raise ValueError('Decision response must reflect the actual accepted action')
        return {'suggestion': suggestion, 'counts': counts}, None


@dataclass(frozen=True)
class DecideGroupRequest:
    payload: dict
    body_fields = ('decision', 'expected_decision_version')

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        payload = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        parsed = decide_group_input(
            {
                **payload,
                'batch_id': decimal_integer(request.path_params['batch_id'], 'batch_id'),
                'group_id': decimal_integer(request.path_params['group_id'], 'group_id'),
                'idempotency_key': idempotency_header(request),
            }
        )
        return cls({**parsed.business_input(), 'idempotency_key': parsed.idempotency_key})


class DecideGroupResponse:
    success_code = 'GROUP_DECIDED'
    errors = DecideSuggestionResponse.errors | {'DECISION_VERSION_CONFLICT'}

    @staticmethod
    def project(data, request):
        fields = ('batch_id', 'group', 'decision_version')
        value = object_fields(data, 'data', fields, fields)
        group = value['group']
        if (
            strict_integer(value['batch_id'], 'batch_id') != request.payload['batch_id']
            or group['group_id'] != request.payload['group_id']
            or group['status'] != request.payload['decision']
            or strict_integer(value['decision_version'], 'decision_version')
            != request.payload['expected_decision_version'] + 1
        ):
            raise ValueError('Group response must reflect the actual accepted decision')
        return value, None


@dataclass(frozen=True)
class CompleteBatchRequest:
    payload: dict
    body_fields = ('expected_content_version', 'expected_decision_version')

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        payload = dict(object_fields(body, 'body', cls.body_fields, ('expected_content_version',)))
        payload.update(
            batch_id=decimal_integer(request.path_params['batch_id'], 'batch_id'),
            idempotency_key=idempotency_header(request),
        )
        validated = complete_batch_input(payload)
        return cls({**validated.business_input(), 'idempotency_key': validated.idempotency_key})


class CompleteBatchResponse:
    success_codes = ('BATCH_APPLIED', 'BATCH_NO_CHANGE')
    errors = DiscardBatchResponse.errors | {
        'CONTENT_VERSION_CONFLICT',
        'BATCH_PENDING',
        'DECISION_VERSION_CONFLICT',
        'TARGET_STALE',
        'PATCH_INVALID',
        'DOCUMENT_INVALID',
        'CAPACITY_EXHAUSTED',
    }

    @staticmethod
    def project(data, request):
        fields = (
            'batch',
            'counts',
            'current_document',
            'document_effect',
            'applied_suggestion_ids',
        )
        value = object_fields(data, 'data', fields, fields)
        batch = batch_metadata(value['batch'])
        counts = counts_model(value['counts'])
        current = document(value['current_document'], 'CURRENT')
        if (
            batch['id'] != request.payload['batch_id']
            or batch['status'] != 'COMPLETED'
            or counts['pending']
            or batch['base_content_version'] != request.payload['expected_content_version']
            or current['requirement_id'] != batch['requirement_id']
            or current['content_version']
            != (batch['applied_content_version'] or batch['base_content_version'])
        ):
            raise ValueError(
                'Completion projection must preserve actual committed batch/document effects'
            )
        from backend.app.documents.contracts import document_effect
        from backend.app.shared.validation import strict_integer

        effect = document_effect(value['document_effect'])
        ids = value['applied_suggestion_ids']
        if (
            type(ids) is not list
            or len(set(ids)) != len(ids)
            or len(ids) != counts['accepted'] + counts['edited']
        ):
            raise ValueError('Actual adopted suggestion identities required')
        for identity in ids:
            strict_integer(identity, 'applied_suggestion_ids')
        if (
            current['id'] != batch['target_document_id']
            or effect['document_id'] != current['id']
            or effect['before_content_version'] != batch['base_content_version']
            or effect['after_content_version'] != current['content_version']
            or effect['result']
            != ('NO_CHANGE' if batch['completion_result'] == 'NO_CHANGE' else 'UPDATED')
        ):
            raise ValueError('Completion effect differs from the committed target')
        return {
            **value,
            'batch': batch,
            'counts': counts,
            'current_document': current,
            'document_effect': effect,
        }, None
