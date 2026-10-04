"""Real I01/I03 adapters; no production startup or placeholder capabilities."""
from fastapi import APIRouter, Request
from backend.app.shared.http_boundary import read_http
from . import queries
from .http_models import ListRequirementsRequest, ListRequirementsResponse, GetRequirementRequest, GetRequirementResponse

req_router = APIRouter(prefix='/api/v1', redirect_slashes=False)


@req_router.get('/requirements')
async def list_requirements_http(request: Request):
    return await read_http(request, ListRequirementsRequest, ListRequirementsResponse,
        lambda runtime, parsed: queries.list_requirements(runtime.database, parsed.payload))


@req_router.get('/requirements/{requirement_id}')
async def get_requirement_http(request: Request):
    return await read_http(request, GetRequirementRequest, GetRequirementResponse,
        lambda runtime, parsed: queries.get_requirement(runtime.database, parsed.requirement_id))
