"""Real I01/I03 adapters; no production startup or placeholder capabilities."""
from fastapi import APIRouter, Request
from backend.app.shared.http_boundary import read_http
from . import queries
from .http_models import ListRequirementsRequest, ListRequirementsResponse, GetRequirementRequest, GetRequirementResponse
from backend.app.shared.http_boundary import handle_http
from . import commands
from .http_models import UpdateRequirementRequest, UpdateRequirementResponse, CompleteInitializationRequest, CompleteInitializationResponse, CompleteRequirementRequest, CompleteRequirementResponse, ReactivateRequirementRequest, ReactivateRequirementResponse
from .http_models import CreateRequirementRequest, CreateRequirementResponse

req_router = APIRouter(prefix='/api/v1', redirect_slashes=False)


@req_router.get('/requirements')
async def list_requirements_http(request: Request):
    return await read_http(request, ListRequirementsRequest, ListRequirementsResponse,
        lambda runtime, parsed: queries.list_requirements(runtime.database, parsed.payload))


@req_router.get('/requirements/{requirement_id}')
async def get_requirement_http(request: Request):
    return await read_http(request, GetRequirementRequest, GetRequirementResponse,
        lambda runtime, parsed: queries.get_requirement(runtime.database, parsed.requirement_id))


@req_router.patch('/requirements/{requirement_id}')
async def update_requirement_http(request: Request):
    return await handle_http(request, UpdateRequirementRequest, UpdateRequirementResponse,
        lambda runtime, parsed: commands.update_requirement(runtime.database, parsed.payload))


@req_router.post('/requirements/{requirement_id}/complete-initialization')
async def complete_initialization_http(request: Request):
    return await handle_http(request, CompleteInitializationRequest, CompleteInitializationResponse,
        lambda runtime, parsed: commands.complete_initialization(runtime.commands(), parsed.payload, catalog=runtime.catalog))


@req_router.post('/requirements/{requirement_id}/complete')
async def complete_requirement_http(request: Request):
    return await handle_http(request, CompleteRequirementRequest, CompleteRequirementResponse,
        lambda runtime, parsed: commands.complete_requirement(runtime.commands(), parsed.payload))


@req_router.post('/requirements/{requirement_id}/reactivate')
async def reactivate_requirement_http(request: Request):
    return await handle_http(request, ReactivateRequirementRequest, ReactivateRequirementResponse,
        lambda runtime, parsed: commands.reactivate_requirement(runtime.commands(), parsed.payload))
@req_router.post('/requirements')
async def create_requirement_http(request: Request):
    return await handle_http(request, CreateRequirementRequest, CreateRequirementResponse,
        lambda runtime, parsed: commands.create_requirement(runtime.commands(), parsed.payload, catalog=runtime.catalog))
