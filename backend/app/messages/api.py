"""I35 one actual application query after transport validation."""
from fastapi import APIRouter, Request
from backend.app.shared.http_boundary import read_http
from . import queries
from .http_models import ListMessagesRequest, ListMessagesResponse

message_router = APIRouter(prefix='/api/v1', redirect_slashes=False)


@message_router.get('/requirements/{requirement_id}/messages')
async def list_messages_http(request: Request):
    return await read_http(request, ListMessagesRequest, ListMessagesResponse,
        lambda runtime, parsed: queries.list_messages(runtime.database, parsed.payload, catalog=runtime.catalog))
