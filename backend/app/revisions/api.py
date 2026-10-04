"""Real I24/I25 adapters; immutable snapshots come from revision queries."""
from fastapi import APIRouter, Request
from backend.app.shared.http_boundary import read_http
from . import queries
from .http_models import ListRevisionsRequest, ListRevisionsResponse, GetRevisionRequest, GetRevisionResponse

rev_router = APIRouter(prefix='/api/v1', redirect_slashes=False)


@rev_router.get('/requirements/{requirement_id}/revisions')
async def list_revisions_http(request: Request):
    return await read_http(request, ListRevisionsRequest, ListRevisionsResponse,
        lambda runtime, parsed: queries.list_revisions(runtime.database, {'requirement_id': parsed.requirement_id, 'page': parsed.page}))


@rev_router.get('/revisions/{revision_id}')
async def get_revision_http(request: Request):
    return await read_http(request, GetRevisionRequest, GetRevisionResponse,
        lambda runtime, parsed: queries.get_revision(runtime.database, parsed.revision_id, catalog=runtime.catalog))
