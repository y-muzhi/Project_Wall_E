"""I16 actual read capability; startup remains the service owner's responsibility."""
from fastapi import APIRouter, Request
from backend.app.shared.http_boundary import read_http
from . import queries
from .http_models import GetGuideRunRequest, GetGuideRunResponse

guide_router = APIRouter(prefix='/api/v1', redirect_slashes=False)


@guide_router.get('/guide-runs/{guide_run_id}')
async def get_guide_run_http(request: Request):
    return await read_http(request, GetGuideRunRequest, GetGuideRunResponse,
        lambda runtime, parsed: queries.get_guide_run(runtime.database, parsed.guide_run_id, catalog=runtime.catalog))
