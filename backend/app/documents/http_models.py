"""I08/I10 document transport schema; sources are verified by actual queries."""

from backend.app.requirements.http_models import GetRequirementRequest
from backend.app.shared.http_projection import document
from backend.app.shared.http_projection import exact, requirement
from backend.app.shared.http_commands import CommandRequest
from backend.app.shared.validation import strict_integer
from .contracts import (
    start_manual_draft_input,
    save_manual_draft_input,
    cancel_manual_draft_input,
    complete_manual_draft_input,
)
from .http_validation import snapshot_input


from dataclasses import dataclass


@dataclass(frozen=True)
class GetCurrentDocumentRequest:
    requirement_id: int
    document_id: int

    @classmethod
    def parse(cls, request):
        from backend.app.shared.http_boundary import request_query
        from backend.app.shared.validation import decimal_integer, MISSING

        query = request_query(request, singles=('document_id',))
        return cls(
            decimal_integer(request.path_params['requirement_id'], 'requirement_id'),
            decimal_integer(query.get('document_id', MISSING), 'document_id'),
        )


class GetManualDraftRequest(GetCurrentDocumentRequest):
    pass


def draft_projection(value):
    from .contracts import DRAFT_FIELDS
    from backend.app.shared.http_projection import snapshot_pair
    from backend.app.documents.snapshot import _time

    data = exact(value, DRAFT_FIELDS)
    for field in (
        'id',
        'requirement_id',
        'content_version',
        'target_document_id',
        'base_content_version',
    ):
        strict_integer(data[field], field)
    if data['document_type'] != 'MANUAL_DRAFT' or data['id'] == data['target_document_id']:
        raise ValueError('Invalid independent draft identity')
    if _time(data['created_at']) > _time(data['updated_at']):
        raise ValueError('Invalid draft chronology')
    if data['template_ref'] is not None:
        from backend.app.requirements.discussion import discussion_resources

        discussion_resources().validate('ResourceRef', data['template_ref'])
    data['block_state_json'] = snapshot_pair(data['markdown_content'], data['block_state_json'])
    return data


class GetCurrentDocumentResponse:
    errors = frozenset(
        {
            'INVALID_INPUT',
            'NOT_FOUND',
            'WORK_STATE_INCONSISTENT',
            'STORAGE_UNAVAILABLE',
            'INTERNAL_ERROR',
        }
    )

    @staticmethod
    def project(data, request):
        from .contracts import document_view

        value = document_view(data)
        if value['requirement_id'] != request.requirement_id or value['id'] != request.document_id:
            raise ValueError('Read returned a document owned by another requirement')
        return value, None


class GetManualDraftResponse:
    errors = GetCurrentDocumentResponse.errors | {'MANUAL_DRAFT_NOT_FOUND'}

    @staticmethod
    def project(data, request):
        value = draft_projection(data)
        if (
            value['requirement_id'] != request.requirement_id
            or value['target_document_id'] != request.document_id
        ):
            raise ValueError('Draft belongs to another target')
        return value, None


class StartManualDraftRequest(CommandRequest):
    body_fields = ('document_id', 'expected_version', 'restore_revision_id')
    mandatory = ('document_id', 'expected_version')
    validate = staticmethod(start_manual_draft_input)


class StartManualDraftResponse:
    success_code = 'DRAFT_STARTED'
    status = 201
    errors = GetManualDraftResponse.errors | {
        'STATE_CONFLICT',
        'WORK_STATE_CONFLICT',
        'CONTENT_VERSION_CONFLICT',
        'IDEMPOTENCY_CONFLICT',
        'REQUEST_IN_PROGRESS',
        'CAPACITY_EXHAUSTED',
        'DOCUMENT_INVALID',
        'SOURCE_INVALID',
        'TEMPLATE_INVALID',
        'CONFIG_INVALID',
    }

    @staticmethod
    def project(data, request):
        value = exact(data, ('manual_draft', 'requirement'))
        draft, root = draft_projection(value['manual_draft']), requirement(value['requirement'])
        if (
            root['id'] != request.payload['requirement_id']
            or draft['requirement_id'] != root['id']
            or draft['target_document_id'] != request.payload['document_id']
            or draft['base_content_version'] != request.payload['expected_version']
            or draft['content_version'] != 1
            or root['document_work_state'] != 'MANUAL_EDITING'
            or root['active_operation_type'] != 'MANUAL_DRAFT'
            or root['active_operation_id'] != draft['id']
        ):
            raise ValueError('Draft start projection contradicts target/session')
        return {'manual_draft': draft, 'requirement': root}, None


class SaveManualDraftRequest(CommandRequest):
    body_fields = (
        'document_id',
        'draft_id',
        'expected_version',
        'markdown_content',
        'block_state_json',
    )
    mandatory = body_fields

    @staticmethod
    def validate(payload):
        value = save_manual_draft_input(payload)
        snapshot_input(payload['markdown_content'], payload['block_state_json'])
        return value


class SaveManualDraftResponse:
    success_code = 'DRAFT_SAVED'
    errors = StartManualDraftResponse.errors

    @staticmethod
    def project(data, request):
        value = draft_projection(data)
        if (
            value['id'] != request.payload['draft_id']
            or value['target_document_id'] != request.payload['document_id']
            or value['requirement_id'] != request.payload['requirement_id']
            or value['content_version'] != request.payload['expected_version'] + 1
            or value['markdown_content'] != request.payload['markdown_content']
            or value['block_state_json']['next_block_id']
            != request.payload['block_state_json']['next_block_id']
            or [block['block_id'] for block in value['block_state_json']['blocks']]
            != [block['block_id'] for block in request.payload['block_state_json']['blocks']]
        ):
            raise ValueError('Saved snapshot differs from the submitted draft')
        return value, None


class CancelManualDraftRequest(CommandRequest):
    body_fields = ('document_id', 'draft_id', 'expected_version')
    mandatory = body_fields
    validate = staticmethod(cancel_manual_draft_input)


class CancelManualDraftResponse:
    success_code = 'DRAFT_CANCELLED'
    errors = StartManualDraftResponse.errors

    @staticmethod
    def project(data, request):
        value = exact(data, ('requirement_id', 'document_id', 'manual_draft_id', 'cancelled'))
        if (
            value['requirement_id'] != request.payload['requirement_id']
            or value['document_id'] != request.payload['document_id']
            or value['manual_draft_id'] != request.payload['draft_id']
            or value['cancelled'] is not True
        ):
            raise ValueError('Cancellation response differs from target/session')
        return value, None


class CompleteManualDraftRequest(CancelManualDraftRequest):
    validate = staticmethod(complete_manual_draft_input)


class CompleteManualDraftResponse:
    success_code = 'DRAFT_COMPLETED'
    errors = StartManualDraftResponse.errors

    @staticmethod
    def project(data, request):
        from .contracts import document_effect

        value = document_effect(data)
        if value['document_id'] != request.payload['document_id']:
            raise ValueError('Completion returned another document')
        return value, None


class CreateDocumentRequest(CommandRequest):
    from .contracts import create_document_input

    body_fields = ('name', 'document_kind', 'template_ref')
    mandatory = body_fields
    validate = staticmethod(create_document_input)
    normalize = staticmethod(
        lambda payload, validated: {
            **validated.business_input(),
            'idempotency_key': validated.idempotency_key,
        }
    )


class CreateDocumentResponse:
    success_code = 'CREATED'
    status = 201
    errors = frozenset(
        {
            'INVALID_INPUT',
            'NOT_FOUND',
            'STATE_CONFLICT',
            'WORK_STATE_CONFLICT',
            'WORK_STATE_INCONSISTENT',
            'TEMPLATE_INVALID',
            'CONFIG_INVALID',
            'CAPACITY_EXHAUSTED',
            'IDEMPOTENCY_CONFLICT',
            'REQUEST_IN_PROGRESS',
            'STORAGE_UNAVAILABLE',
            'INTERNAL_ERROR',
        }
    )

    @staticmethod
    def project(data, request):
        from .contracts import document_view

        value = exact(data, ('document', 'revision_id'))
        current = document_view(value['document'])
        strict_integer(value['revision_id'], 'revision_id')
        if (
            current['requirement_id'] != request.payload['requirement_id']
            or current['name'] != request.payload['name']
            or current['document_kind'] != request.payload['document_kind']
            or current['content_version'] != 1
            or current['current_revision_id'] != value['revision_id']
            or current['template_ref'] != request.payload['template_ref']
        ):
            raise ValueError('Created document contradicts the submitted target')
        return {'document': current, 'revision_id': value['revision_id']}, None


class DocumentMetadataRequest(CommandRequest):
    body_fields = ('expected_metadata_version', 'change')
    mandatory = body_fields

    @classmethod
    def parse(cls, request, body):
        from backend.app.shared.http_boundary import request_query, idempotency_header
        from backend.app.shared.validation import object_fields, decimal_integer
        from .contracts import document_metadata_input

        request_query(request)
        body = object_fields(body, 'body', cls.body_fields, cls.mandatory)
        parsed = document_metadata_input(
            {
                **body,
                'document_id': decimal_integer(request.path_params['document_id'], 'document_id'),
                'idempotency_key': idempotency_header(request),
            }
        )
        return cls({**parsed.business_input(), 'idempotency_key': parsed.idempotency_key})


class DocumentMetadataResponse:
    success_codes = ('UPDATED', 'NO_CHANGE')
    errors = CreateDocumentResponse.errors | {
        'METADATA_VERSION_CONFLICT',
        'CONTENT_VERSION_CONFLICT',
        'SOURCE_INVALID',
    }

    @staticmethod
    def project(data, request):
        from .contracts import document_summary

        value = exact(data, ('document', 'event_id'))
        summary = document_summary(value['document'])
        if summary['id'] != request.payload['document_id']:
            raise ValueError('Updated document identity differs')
        if value['event_id'] is not None:
            strict_integer(value['event_id'], 'event_id')
        return {'document': summary, 'event_id': value['event_id']}, None
