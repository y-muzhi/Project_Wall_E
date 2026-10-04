"""I08/I10 document transport schema; sources are verified by actual queries."""
from backend.app.requirements.http_models import GetRequirementRequest
from backend.app.shared.http_projection import document


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
