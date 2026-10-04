"""I20 actual APP adapter with explicit runtime ownership."""
from fastapi import APIRouter, Request
from backend.app.shared.http_boundary import read_http
from . import queries
from .http_models import GetBatchRequest, GetBatchResponse
from .http_models import DiscardBatchRequest, DiscardBatchResponse
from backend.app.shared.http_boundary import handle_http
from . import commands

batch_router = APIRouter(prefix='/api/v1', redirect_slashes=False)


@batch_router.get('/suggestion-batches/{batch_id}')
async def get_batch_http(request: Request):
    return await read_http(request, GetBatchRequest, GetBatchResponse,
        lambda runtime, parsed: queries.get_batch(runtime.database, parsed.batch_id, catalog=runtime.catalog))


@batch_router.post('/suggestion-batches/{batch_id}/discard')
async def discard_batch_http(request: Request):
    return await handle_http(request, DiscardBatchRequest, DiscardBatchResponse,
        lambda runtime, parsed: commands.discard_batch(runtime.commands(), parsed.payload))
