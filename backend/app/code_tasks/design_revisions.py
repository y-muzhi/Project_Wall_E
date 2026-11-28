"""Read original design revisions and their durable confirmation facts."""

import re
from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.documents.drawing import is_drawing
from backend.app.shared.http_boundary import handle_http, request_query
from backend.app.shared.http_projection import exact, page
from backend.app.shared.pagination import MAX_PAGE, PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import decimal_integer, reject, strict_enum, strict_integer

from .configuration_identities import require_schema
from .repository_operations import _time
from .repository_reads import ERRORS

PATH = '/documents/{document_id}/code-design-revisions'
USAGES = ('MAIN', 'MATERIAL')
FIELDS = (
    'revision_id',
    'requirement_id',
    'document_id',
    'version_no',
    'is_current',
    'confirmation_event_id',
    'confirmed_at',
    'eligible',
    'reason_code',
)

# The event must reference this exact immutable revision and the same content
# version in both the audit columns and the originally recorded event payload.
_CHOICES = """
SELECT r.id AS revision_id,r.requirement_id,r.document_id,r.version_no,
       r.markdown_snapshot,d.content_version AS current_version,d.document_kind,d.template_ref,
       a.id AS confirmation_event_id,a.created_at AS confirmed_at
FROM revisions r
JOIN requirement_documents d ON d.id=r.document_id AND d.requirement_id=r.requirement_id
LEFT JOIN document_change_audits a ON a.id=(
    SELECT e.id FROM document_change_audits e
    WHERE e.revision_id=r.id AND e.document_id=r.document_id AND e.requirement_id=r.requirement_id
      AND e.event_type='DOCUMENT_CONFIRMED' AND e.reason_code='DOCUMENT_CONFIRMED'
      AND e.source_type='USER_ACTION' AND e.source_id=r.document_id AND e.guide_run_id IS NULL
      AND e.before_content_version=r.version_no AND e.after_content_version=r.version_no
      AND json_type(e.payload_json,'$.revision_id')='integer'
      AND json_extract(e.payload_json,'$.revision_id')=r.id
      AND json_type(e.payload_json,'$.content_version')='integer'
      AND json_extract(e.payload_json,'$.content_version')=r.version_no
      AND json_type(e.payload_json,'$.idempotency_key')='text'
    ORDER BY e.created_at DESC,e.id DESC LIMIT 1
)
WHERE d.document_type='CURRENT' AND r.revision_type='CONTENT' AND r.document_id=?
"""

design_revision_router = APIRouter(prefix='/api/v1', redirect_slashes=False)


def is_design_revision_path(path):
    return re.fullmatch(r'/api/v1/documents/[^/]+/code-design-revisions', path) is not None


def _choice(row, usage):
    reason = None
    if row['confirmation_event_id'] is None:
        reason = 'UNCONFIRMED'
    elif is_drawing(row):
        reason = 'UNAVAILABLE'
    elif usage == 'MAIN' and not row['markdown_snapshot'].strip():
        reason = 'EMPTY_MAIN'
    return {
        **{field: row[field] for field in (*FIELDS[:4], 'confirmation_event_id', 'confirmed_at')},
        'is_current': row['version_no'] == row['current_version'],
        'eligible': reason is None,
        'reason_code': reason,
    }


def design_revision_choice(connection, document_id, revision_id, *, usage, include_markdown=False):
    strict_enum(usage, 'usage', USAGES)
    row = connection.execute(_CHOICES + ' AND r.id=?', (document_id, revision_id)).fetchone()
    if row is None:
        return None
    result = _choice(row, usage)
    if include_markdown:
        result['markdown_snapshot'] = '' if is_drawing(row) else row['markdown_snapshot']
    return result


def list_design_revisions(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        document = connection.execute(
            "SELECT id FROM requirement_documents WHERE id=? AND document_type='CURRENT'",
            (request.document_id,),
        ).fetchone()
        if document is None:
            return {'code': 'NOT_FOUND', 'data': None, 'details': None}
        total = connection.execute(
            "SELECT count(*) FROM revisions WHERE document_id=? AND revision_type='CONTENT'",
            (request.document_id,),
        ).fetchone()[0]
        rows = connection.execute(
            _CHOICES + ' ORDER BY r.version_no DESC,r.id DESC LIMIT ? OFFSET ?',
            (request.document_id, PAGE_SIZE, page_offset(request.page)),
        ).fetchall()
        items = [_choice(row, request.usage) for row in rows]
    return {
        'code': 'READ_OK',
        'data': {'items': items, **page_metadata(request.page, total)},
        'details': None,
    }


@dataclass(frozen=True)
class DesignRevisionRequest:
    document_id: int
    usage: str
    page: int

    @classmethod
    def parse(cls, request):
        if any(key.lower() == b'idempotency-key' for key, _ in request.scope.get('headers', [])):
            reject('Idempotency-Key', 'UNKNOWN_FIELD', '读取设计版本不接收幂等请求头')
        query = request_query(request, singles=('usage', 'page'))
        return cls(
            decimal_integer(request.path_params['document_id'], 'document_id'),
            strict_enum(query.get('usage', 'MAIN'), 'usage', USAGES),
            decimal_integer(query.get('page', '1'), 'page', MAX_PAGE),
        )


def _project(value, request):
    row = exact(value, FIELDS)
    for field in FIELDS[:4]:
        strict_integer(row[field], field)
    if row['document_id'] != request.document_id or type(row['is_current']) is not bool:
        raise ValueError('Original design revision belongs to a different document')
    event = row['confirmation_event_id']
    if event is not None:
        strict_integer(event, 'confirmation_event_id')
    _time(row['confirmed_at'])
    if (event is None) != (row['confirmed_at'] is None):
        raise ValueError('Original confirmation event and timestamp differ')
    reason = row['reason_code']
    if reason is not None:
        strict_enum(reason, 'reason_code', ('UNCONFIRMED', 'EMPTY_MAIN', 'UNAVAILABLE'))
    if (
        type(row['eligible']) is not bool
        or row['eligible'] != (reason is None)
        or event is None
        and reason != 'UNCONFIRMED'
        or reason == 'UNCONFIRMED'
        and event is not None
        or reason == 'EMPTY_MAIN'
        and request.usage != 'MAIN'
    ):
        raise ValueError('Original design revision eligibility differs')
    return row


class DesignRevisionResponse:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(data, request):
        result, pagination = page(data, lambda value: _project(value, request), request.page)
        versions = [item['version_no'] for item in result['items']]
        if versions != sorted(set(versions), reverse=True):
            raise ValueError('Original design revision order differs')
        return result, pagination


@design_revision_router.get(PATH)
async def design_revisions_http(request: Request):
    return await handle_http(
        request, DesignRevisionRequest, DesignRevisionResponse, list_design_revisions
    )
