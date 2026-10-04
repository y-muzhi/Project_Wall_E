"""Real I27/I28/I37 adapters; explicitly owned runtime, no startup bypass."""
from fastapi import APIRouter, Request
from backend.app.shared.http_boundary import read_http
from . import queries
from .http_models import ListCommentsRequest, ListCommentsResponse, GetCommentRequest, GetCommentResponse, GetCommentIndexRequest, GetCommentIndexResponse
from .http_models import CreateCommentRequest, CreateCommentResponse, EditCommentRequest, EditCommentResponse, ResolveCommentRequest, ResolveCommentResponse, ReopenCommentRequest, ReopenCommentResponse, DeleteCommentRequest, DeleteCommentResponse
from backend.app.shared.http_boundary import handle_http
from . import commands

comment_router = APIRouter(prefix='/api/v1', redirect_slashes=False)


@comment_router.get('/requirements/{requirement_id}/comments')
async def list_comments_http(request: Request):
    return await read_http(request, ListCommentsRequest, ListCommentsResponse,
        lambda runtime, parsed: queries.list_comments(runtime.database, parsed.payload, catalog=runtime.catalog))


@comment_router.get('/comments/{comment_id}')
async def get_comment_http(request: Request):
    return await read_http(request, GetCommentRequest, GetCommentResponse,
        lambda runtime, parsed: queries.get_comment(runtime.database, parsed.comment_id))


@comment_router.get('/requirements/{requirement_id}/comment-index')
async def get_comment_index_http(request: Request):
    return await read_http(request, GetCommentIndexRequest, GetCommentIndexResponse,
        lambda runtime, parsed: queries.get_comment_index(runtime.database, parsed.requirement_id, catalog=runtime.catalog))


@comment_router.post('/requirements/{requirement_id}/comments')
async def create_comment_http(request: Request):
    return await handle_http(request, CreateCommentRequest, CreateCommentResponse,
        lambda runtime, parsed: commands.create_comment(runtime.commands(), parsed.payload, catalog=runtime.catalog))


@comment_router.patch('/comments/{comment_id}')
async def edit_comment_http(request: Request):
    return await handle_http(request, EditCommentRequest, EditCommentResponse,
        lambda runtime, parsed: commands.edit_comment(runtime.commands(), parsed.payload))


@comment_router.post('/comments/{comment_id}/resolve')
async def resolve_comment_http(request: Request):
    return await handle_http(request, ResolveCommentRequest, ResolveCommentResponse,
        lambda runtime, parsed: commands.resolve_comment(runtime.commands(), parsed.payload))


@comment_router.post('/comments/{comment_id}/reopen')
async def reopen_comment_http(request: Request):
    return await handle_http(request, ReopenCommentRequest, ReopenCommentResponse,
        lambda runtime, parsed: commands.reopen_comment(runtime.commands(), parsed.payload))


@comment_router.delete('/comments/{comment_id}')
async def delete_comment_http(request: Request):
    return await handle_http(request, DeleteCommentRequest, DeleteCommentResponse,
        lambda runtime, parsed: commands.delete_comment(runtime.commands(), parsed.payload))
