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
from backend.app.infrastructure.idempotency import Idempotency, canonical_input, request_key
from backend.app.infrastructure.resources import ResourceCatalog
from .http_errors import error_response, new_request_id
from .validation import InvalidInput, query_fields, reject, strict_json_object

HTTP_REQUEST_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class HttpRuntime:
    database: Database
    catalog: ResourceCatalog
    executor: Idempotency | None = None
    worker: object | None = None

    def commands(self) -> Idempotency:
        if not isinstance(self.executor, Idempotency) or self.executor.database is not self.database:
            raise ValueError('Command runtime must share the actual database and held process lock')
        return self.executor


def idempotency_header(request: Request) -> str:
    values = [value for name, value in request.scope.get('headers', []) if name.lower() == b'idempotency-key']
    if not values:
        reject('Idempotency-Key', 'REQUIRED', '必须提供此请求头')
    if len(values) != 1:
        reject('Idempotency-Key', 'DUPLICATE_PARAMETER', '幂等请求头不能重复提供')
    return request_key(values[0].decode('latin-1'))


def request_query(request: Request, *, singles=(), arrays=None) -> dict:
    try:
        text = request.scope.get('query_string', b'').decode('utf-8', errors='strict')
        pairs = parse_qsl(text, keep_blank_values=True, encoding='utf-8', errors='strict')
    except UnicodeError:
        reject('query', 'INVALID_FORMAT', '查询参数必须使用有效UTF-8编码')
    return query_fields(pairs, singles, arrays or {})


async def request_body(request: Request, *, json_required: bool = False) -> dict | None:
    # Count application-visible request bytes, including URI and header fields,
    # before consuming the body. Never trust Content-Length to enforce the cap.
    used = len(request.scope.get('raw_path', b'')) + len(request.scope.get('query_string', b''))
    used += sum(len(key)+len(value) for key, value in request.scope.get('headers', []))
    if used > HTTP_REQUEST_BYTES:
        reject('request', 'TOO_LONG', '完整请求超过8MiB容量')
    body = bytearray()
    async for chunk in request.stream():
        used += len(chunk)
        if used > HTTP_REQUEST_BYTES:
            reject('request', 'TOO_LONG', '完整请求超过8MiB容量')
        if chunk and not json_required:
            reject('body', 'INVALID_TYPE', '此接口使用空请求体')
        body.extend(chunk)
    if not json_required:
        return None
    media = [value.decode('latin-1') for name, value in request.scope.get('headers', []) if name.lower() == b'content-type']
    if len(media) != 1 or media[0].split(';', 1)[0].strip().lower() != 'application/json':
        reject('Content-Type', 'INVALID_FORMAT', 'JSON请求体必须使用application/json')
    if not body:
        reject('body', 'REQUIRED', '必须提供JSON对象请求体')
    return strict_json_object(bytes(body))


async def handle_http(request: Request, request_model: type, response_model: type, invoke: Callable) -> JSONResponse:
    request_id = new_request_id()
    request.state.request_id = request_id
    def failure(code, details=None):
        projected = error_response(code, details, allowed_errors=response_model.errors, request_id=request_id)
        return JSONResponse(projected.body, status_code=projected.status)
    try:
        has_body = getattr(request_model, 'body_fields', None) is not None
        body = await request_body(request, json_required=has_body)
        parsed = request_model.parse(request, body) if has_body else request_model.parse(request)
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
        success_codes = getattr(response_model, 'success_codes', (getattr(response_model, 'success_code', 'READ_OK'),))
        if result['code'] not in success_codes:
            if result['data'] is not None:
                raise ValueError('Failure results cannot carry success data')
            return failure(result['code'], result['details'])
        if result['details'] is not None:
            raise ValueError('Success results cannot carry error details')
        if runtime.worker is not None:
            from backend.app.guide.worker import GuideWorker
            if not isinstance(runtime.worker, GuideWorker) or runtime.worker.database is not runtime.database:
                raise ValueError('Post-commit dispatcher must own this actual runtime database')
            await runtime.worker.after_commit(result)
        data, pagination = response_model.project(result['data'], parsed)
        canonical_input(data)  # No nonfinite numbers, unsafe integers, bad Unicode or ORM objects.
        meta = {'request_id': request_id}
        if pagination is not None:
            meta['pagination'] = pagination
        return JSONResponse({'success': True, 'data': data, 'error': None, 'meta': meta}, status_code=getattr(response_model, 'status', 200))
    except Exception:
        return failure('INTERNAL_ERROR')


# Read adapters keep the same entry point and policy; command models declare
# their body requirements and exact success code/status through the same gate.
read_http = handle_http
