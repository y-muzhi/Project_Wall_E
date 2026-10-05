"""I35 one actual application query after transport validation."""
from fastapi import APIRouter, Request
from backend.app.shared.http_boundary import read_http
from . import queries
from .http_models import ListMessagesRequest, ListMessagesResponse
from .http_models import SubmitCardResponsesRequest, SubmitCardResponsesResponse
from backend.app.shared.http_boundary import handle_http
from backend.app.guide import commands

message_router = APIRouter(prefix='/api/v1', redirect_slashes=False)


@message_router.get('/requirements/{requirement_id}/messages')
async def list_messages_http(request: Request):
    return await read_http(request, ListMessagesRequest, ListMessagesResponse,
        lambda runtime, parsed: queries.list_messages(runtime.database, parsed.payload, catalog=runtime.catalog))


@message_router.post('/conversation-messages/{message_id}/responses')
async def submit_card_responses_http(request: Request):
    return await handle_http(request, SubmitCardResponsesRequest, SubmitCardResponsesResponse,
        lambda runtime, parsed: commands.submit_card_responses(runtime.commands(), parsed.payload, catalog=runtime.catalog))
