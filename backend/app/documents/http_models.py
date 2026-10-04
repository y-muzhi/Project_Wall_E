"""I08/I10 document transport schema; sources are verified by actual queries."""
from backend.app.requirements.http_models import GetRequirementRequest
from backend.app.shared.http_projection import document
from backend.app.shared.http_projection import exact, requirement
from backend.app.shared.http_commands import CommandRequest
from backend.app.shared.validation import strict_integer
from .contracts import start_manual_draft_input, save_manual_draft_input, cancel_manual_draft_input
from .http_validation import snapshot_input


class GetCurrentDocumentRequest(GetRequirementRequest):
    @classmethod
    def parse(cls, request):
        return super().parse(request)


class GetManualDraftRequest(GetRequirementRequest):
    @classmethod
    def parse(cls, request):
        return super().parse(request)


class GetCurrentDocumentResponse:
    errors = frozenset({'INVALID_INPUT', 'NOT_FOUND', 'WORK_STATE_INCONSISTENT', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR'})

    @staticmethod
    def project(data, request):
        value = document(data, 'CURRENT')
        if value['requirement_id'] != request.requirement_id:
            raise ValueError('Read returned a document owned by another requirement')
        return value, None


class GetManualDraftResponse:
    errors = GetCurrentDocumentResponse.errors | {'MANUAL_DRAFT_NOT_FOUND'}

    @staticmethod
    def project(data, request):
        value = document(data, 'MANUAL_DRAFT')
        if value['requirement_id'] != request.requirement_id:
            raise ValueError('Read returned a document owned by another requirement')
        return value, None


class StartManualDraftRequest(CommandRequest):
    body_fields = ('expected_version',)
    mandatory = body_fields
    rename = {'expected_version': 'expected_content_version'}
    validate = staticmethod(start_manual_draft_input)


class StartManualDraftResponse:
    success_code = 'DRAFT_STARTED'
    status = 201
    errors = GetCurrentDocumentResponse.errors | {'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'CONTENT_VERSION_CONFLICT', 'IDEMPOTENCY_CONFLICT', 'REQUEST_IN_PROGRESS', 'CAPACITY_EXHAUSTED'}

    @staticmethod
    def project(data, request):
        value = exact(data, ('manual_draft', 'requirement'))
        draft = document(value['manual_draft'], 'MANUAL_DRAFT')
        root = requirement(value['requirement'])
        if root['id'] != request.payload['requirement_id'] or root['status'] not in ('INITIALIZING', 'ACTIVE') or draft['requirement_id'] != root['id'] or draft['content_version'] != 1 or root['active_operation_type'] != 'MANUAL_DRAFT' or root['active_operation_id'] != draft['id']:
            raise ValueError('Draft start projection has contradictory target/occupancy')
        return {'manual_draft': draft, 'requirement': root}, None


class SaveManualDraftRequest(CommandRequest):
    body_fields = ('expected_version', 'markdown_content', 'block_state_json')
    mandatory = body_fields
    uses_key = False

    @staticmethod
    def validate(payload):
        save_manual_draft_input(payload)
        snapshot_input(payload['markdown_content'], payload['block_state_json'])


class SaveManualDraftResponse:
    success_code = 'DRAFT_SAVED'
    errors = GetManualDraftResponse.errors - {'MANUAL_DRAFT_NOT_FOUND'} | {'WORK_STATE_CONFLICT', 'CONTENT_VERSION_CONFLICT', 'DOCUMENT_INVALID', 'CAPACITY_EXHAUSTED'}

    @staticmethod
    def project(data, request):
        value = document(data, 'MANUAL_DRAFT')
        if value['requirement_id'] != request.payload['requirement_id'] or value['content_version'] != request.payload['expected_version']+1 or value['markdown_content'] != request.payload['markdown_content'] or value['block_state_json']['next_block_id'] != request.payload['block_state_json']['next_block_id'] or [block['block_id'] for block in value['block_state_json']['blocks']] != [block['block_id'] for block in request.payload['block_state_json']['blocks']]:
            raise ValueError('Saved snapshot does not correspond to this submission')
        return value, None


class CancelManualDraftRequest(CommandRequest):
    body_fields = ('expected_version',)
    mandatory = body_fields
    validate = staticmethod(cancel_manual_draft_input)


class CancelManualDraftResponse:
    success_code = 'DRAFT_CANCELLED'
    errors = GetCurrentDocumentResponse.errors | {'WORK_STATE_CONFLICT', 'CONTENT_VERSION_CONFLICT', 'IDEMPOTENCY_CONFLICT', 'REQUEST_IN_PROGRESS'}

    @staticmethod
    def project(data, request):
        value = exact(data, ('requirement_id', 'manual_draft_id', 'cancelled'))
        strict_integer(value['requirement_id'], 'requirement_id')
        strict_integer(value['manual_draft_id'], 'manual_draft_id')
        if value['requirement_id'] != request.payload['requirement_id'] or value['cancelled'] is not True:
            raise ValueError('Cancellation response contradicts submitted target')
        return value, None
