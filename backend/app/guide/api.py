"""I16 actual read capability; startup remains the service owner's responsibility."""
from fastapi import APIRouter, Request
from backend.app.shared.http_boundary import read_http
from . import queries
from .http_models import GetGuideRunRequest, GetGuideRunResponse
from backend.app.shared.http_boundary import handle_http
from .http_models import CancelGuideRunRequest, CancelGuideRunResponse
from . import commands
from .http_models import ListGuideRunsRequest, ListGuideRunsResponse
from .http_models import CreateGuideRunRequest, CreateGuideRunResponse, ContinueGuideRunRequest, ContinueGuideRunResponse

guide_router = APIRouter(prefix='/api/v1', redirect_slashes=False)


@guide_router.get('/guide-runs/{guide_run_id}')
async def get_guide_run_http(request: Request):
    return await read_http(request, GetGuideRunRequest, GetGuideRunResponse,
        lambda runtime, parsed: queries.get_guide_run(runtime.database, parsed.guide_run_id, catalog=runtime.catalog))


@guide_router.post('/guide-runs/{guide_run_id}/cancel')
async def cancel_guide_run_http(request: Request):
    return await handle_http(request, CancelGuideRunRequest, CancelGuideRunResponse,
        lambda runtime, parsed: commands.cancel_guide_run(runtime.commands(), parsed.payload))


@guide_router.get('/requirements/{requirement_id}/guide-runs')
async def list_guide_runs_http(request: Request):
    return await read_http(request, ListGuideRunsRequest, ListGuideRunsResponse,
        lambda runtime, parsed: queries.list_guide_runs(runtime.database, parsed.payload))


@guide_router.post('/requirements/{requirement_id}/guide-runs')
async def create_guide_run_http(request: Request):
    return await handle_http(request, CreateGuideRunRequest, CreateGuideRunResponse,
        lambda runtime, parsed: commands.create_guide_run(runtime.commands(), parsed.payload, catalog=runtime.catalog))


@guide_router.post('/guide-runs/{guide_run_id}/continue')
async def continue_guide_run_http(request: Request):
    return await handle_http(request, ContinueGuideRunRequest, ContinueGuideRunResponse,
        lambda runtime, parsed: commands.continue_guide_run(runtime.commands(), parsed.payload, catalog=runtime.catalog))
