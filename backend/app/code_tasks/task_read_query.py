"""Common read-only query boundary for Coding task and audit reads."""

from backend.app.shared.http_boundary import request_query
from backend.app.shared.validation import reject


def read_task_query(request, **options):
    if any(name.lower() == b'idempotency-key' for name, _ in request.scope.get('headers', [])):
        reject('Idempotency-Key', 'UNKNOWN_FIELD', '读取任务不接收幂等请求头')
    return request_query(request, **options)
