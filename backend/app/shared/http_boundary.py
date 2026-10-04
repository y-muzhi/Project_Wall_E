"""Real ASGI transport gates; application functions are invoked exactly once.

Routers require an explicit initialized runtime. Production startup/recovery is
a separate capability; these adapters do not create a database or skip recovery.
"""
from dataclasses import dataclass
from typing import Callable
from urllib.parse import parse_qsl

from fastapi import Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from backend.app.infrastructure.database import Database
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.resources import ResourceCatalog
from .http_errors import error_response, new_request_id
from .validation import InvalidInput, query_fields, reject

HTTP_REQUEST_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class HttpRuntime:
    database: Database
    catalog: ResourceCatalog


def request_query(request: Request, *, singles=(), arrays=None) -> dict:
    try:
        text = request.scope.get('query_string', b'').decode('utf-8', errors='strict')
        pairs = parse_qsl(text, keep_blank_values=True, encoding='utf-8', errors='strict')
    except UnicodeError:
        reject('query', 'INVALID_FORMAT', '查询参数必须使用有效UTF-8编码')
    return query_fields(pairs, singles, arrays or {})


async def empty_body(request: Request) -> None:
    # Count application-visible request bytes, including URI and header fields,
    # before consuming the body. Never trust Content-Length to enforce the cap.
    used = len(request.scope.get('raw_path', b'')) + len(request.scope.get('query_string', b''))
    used += sum(len(key)+len(value) for key, value in request.scope.get('headers', []))
    if used > HTTP_REQUEST_BYTES:
        reject('request', 'TOO_LONG', '完整请求超过8MiB容量')
    async for chunk in request.stream():
        used += len(chunk)
        if used > HTTP_REQUEST_BYTES:
            reject('request', 'TOO_LONG', '完整请求超过8MiB容量')
        if chunk:
            reject('body', 'INVALID_TYPE', '此接口使用空请求体')


async def read_http(request: Request, request_model: type, response_model: type, invoke: Callable) -> JSONResponse:
    request_id = new_request_id()
    request.state.request_id = request_id
    def failure(code, details=None):
        projected = error_response(code, details, allowed_errors=response_model.errors, request_id=request_id)
        return JSONResponse(projected.body, status_code=projected.status)
    try:
        await empty_body(request)
        parsed = request_model.parse(request)
    except InvalidInput as error:
        return failure('INVALID_INPUT', error.details)
    except Exception:
        return failure('INTERNAL_ERROR')
    try:
        runtime = getattr(request.app.state, 'walle_runtime', None)
        if not isinstance(runtime, HttpRuntime):
            raise ValueError('An initialized runtime must be attached by the startup owner')
        result = await run_in_threadpool(invoke, runtime, parsed)
        if type(result) is not dict or set(result) != {'code', 'data', 'details'}:
            raise ValueError('Invalid application result contract')
        if result['code'] != 'READ_OK':
            if result['data'] is not None:
                raise ValueError('Failure results cannot carry success data')
            return failure(result['code'], result['details'])
        if result['details'] is not None:
            raise ValueError('Success results cannot carry error details')
        data, pagination = response_model.project(result['data'], parsed)
        canonical_input(data)  # No nonfinite numbers, unsafe integers, bad Unicode or ORM objects.
        meta = {'request_id': request_id}
        if pagination is not None:
            meta['pagination'] = pagination
        return JSONResponse({'success': True, 'data': data, 'error': None, 'meta': meta}, status_code=200)
    except Exception:
        return failure('INTERNAL_ERROR')
