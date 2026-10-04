"""I20 actual APP adapter with explicit runtime ownership."""
from fastapi import APIRouter, Request
from backend.app.shared.http_boundary import read_http
from . import queries
from .http_models import GetBatchRequest, GetBatchResponse
from .http_models import DiscardBatchRequest, DiscardBatchResponse
from backend.app.shared.http_boundary import handle_http
from . import commands
from .http_models import DecideSuggestionRequest, DecideSuggestionResponse
from .http_models import CompleteBatchRequest, CompleteBatchResponse

batch_router = APIRouter(prefix='/api/v1', redirect_slashes=False)


@batch_router.get('/suggestion-batches/{batch_id}')
async def get_batch_http(request: Request):
    return await read_http(request, GetBatchRequest, GetBatchResponse,
        lambda runtime, parsed: queries.get_batch(runtime.database, parsed.batch_id, catalog=runtime.catalog))


@batch_router.post('/suggestion-batches/{batch_id}/discard')
async def discard_batch_http(request: Request):
    return await handle_http(request, DiscardBatchRequest, DiscardBatchResponse,
        lambda runtime, parsed: commands.discard_batch(runtime.commands(), parsed.payload))


@batch_router.put('/suggestions/{suggestion_id}/decision')
async def decide_suggestion_http(request: Request):
    return await handle_http(request, DecideSuggestionRequest, DecideSuggestionResponse,
        lambda runtime, parsed: commands.decide_suggestion(runtime.commands(), parsed.payload, catalog=runtime.catalog))


@batch_router.post('/suggestion-batches/{batch_id}/complete')
async def complete_batch_http(request: Request):
    return await handle_http(request, CompleteBatchRequest, CompleteBatchResponse,
        lambda runtime, parsed: commands.complete_batch(runtime.commands(), parsed.payload, catalog=runtime.catalog))
