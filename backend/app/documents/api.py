"""Real I08/I10 adapters with fixed CURRENT/draft application bindings."""
from fastapi import APIRouter, Request
from backend.app.shared.http_boundary import read_http
from . import queries
from .http_models import GetCurrentDocumentRequest, GetCurrentDocumentResponse, GetManualDraftRequest, GetManualDraftResponse

doc_router = APIRouter(prefix='/api/v1', redirect_slashes=False)


@doc_router.get('/requirements/{requirement_id}/current-document')
async def get_current_document_http(request: Request):
    return await read_http(request, GetCurrentDocumentRequest, GetCurrentDocumentResponse,
        lambda runtime, parsed: queries.get_current_document(runtime.database, parsed.requirement_id, catalog=runtime.catalog))


@doc_router.get('/requirements/{requirement_id}/manual-draft')
async def get_manual_draft_http(request: Request):
    return await read_http(request, GetManualDraftRequest, GetManualDraftResponse,
        lambda runtime, parsed: queries.get_manual_draft(runtime.database, parsed.requirement_id, catalog=runtime.catalog))
