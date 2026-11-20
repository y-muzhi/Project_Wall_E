"""Immutable history routes; production registration belongs to the verified Schema210 startup."""

from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.shared.http_boundary import read_http, request_query
from backend.app.shared.strict_objects import exact
from backend.app.shared.validation import decimal_integer

from .history_queries import read_history

formation_router = APIRouter(prefix='/api/v1', redirect_slashes=False)
BASE = '/requirements/{requirement_id}/documents/{document_id}/formation'


@dataclass(frozen=True)
class HistoryRequest:
    requirement_id: int
    document_id: int
    payload: dict
    view = 'events'
    query_fields = ('limit', 'cursor', 'step_ref', 'branch_ref')
    path_fields = ()

    @classmethod
    def parse(cls, request):
        payload = request_query(request, singles=cls.query_fields)
        if 'limit' in payload:
            payload['limit'] = decimal_integer(payload['limit'], 'limit', maximum=100)
        for name in cls.path_fields:
            value = request.path_params[name]
            payload[name] = (
                decimal_integer(value, name) if name in ('event_id', 'change_ordinal') else value
            )
        return cls(
            decimal_integer(request.path_params['requirement_id'], 'requirement_id'),
            decimal_integer(request.path_params['document_id'], 'document_id'),
            payload,
        )


class ChangesRequest(HistoryRequest):
    view = 'changes'
    query_fields = ('limit', 'cursor')
    path_fields = ('event_id',)


class MembersRequest(ChangesRequest):
    view = 'members'
    path_fields = ('event_id', 'change_ordinal')


class ClosureRequest(ChangesRequest):
    view = 'closure'
    query_fields = ('kind', 'limit', 'cursor')


class EvidenceRequest(ChangesRequest):
    view = 'evidence'
    path_fields = ('event_id', 'owner_kind', 'item_ref')


class HistoryResponse:
    errors = frozenset(
        {'INVALID_INPUT', 'NOT_FOUND', 'STATE_CONFLICT', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR'}
    )

    @staticmethod
    def project(data, request):
        value = exact(data, ('value', 'pagination'))
        pagination = exact(value['pagination'], ('page_size', 'has_more', 'next_cursor'))
        if type(pagination['has_more']) is not bool or (
            pagination['has_more'] != (pagination['next_cursor'] is not None)
        ):
            raise ValueError('History pagination is inconsistent')
        return value['value'], pagination


async def _read(request, model):
    return await read_http(
        request,
        model,
        HistoryResponse,
        lambda runtime, parsed: read_history(
            runtime.database, parsed.requirement_id, parsed.document_id, parsed.view, parsed.payload
        ),
    )


@formation_router.get(BASE + '/events')
async def events_http(request: Request):
    return await _read(request, HistoryRequest)


@formation_router.get(BASE + '/events/{event_id}/changes')
async def changes_http(request: Request):
    return await _read(request, ChangesRequest)


@formation_router.get(BASE + '/events/{event_id}/changes/{change_ordinal}/members')
async def members_http(request: Request):
    return await _read(request, MembersRequest)


@formation_router.get(BASE + '/events/{event_id}/closure-items')
async def closure_http(request: Request):
    return await _read(request, ClosureRequest)


@formation_router.get(BASE + '/events/{event_id}/closure-items/{owner_kind}/{item_ref}/evidence')
async def evidence_http(request: Request):
    return await _read(request, EvidenceRequest)


@dataclass(frozen=True)
class EntityRequest:
    requirement_id: int
    document_id: int
    kind: str
    payload: dict
    detail = False

    @classmethod
    def parse(cls, request):
        fields = (
            ('known_f',)
            if cls.detail
            else (
                'limit',
                'cursor',
                'known_f',
                'state',
                'step_ref',
                'branch_ref',
                'include_cancelled',
                'include_superseded',
            )
        )
        payload = request_query(request, singles=fields)
        for name in ('limit', 'known_f'):
            if name in payload:
                payload[name] = decimal_integer(
                    payload[name], name, maximum=100 if name == 'limit' else 9007199254740991
                )
        for name in ('include_cancelled', 'include_superseded'):
            if name in payload:
                from backend.app.shared.validation import strict_enum

                payload[name] = strict_enum(payload[name], name, ('true', 'false')) == 'true'
        return cls(
            decimal_integer(request.path_params['requirement_id'], 'requirement_id'),
            decimal_integer(request.path_params['document_id'], 'document_id'),
            request.path_params['kind'],
            payload,
        )


class DetailRequest(EntityRequest):
    detail = True


class EntityResponse(HistoryResponse):
    @staticmethod
    def project(data, request):
        value = exact(data, ('value', 'pagination'))
        if value['pagination'] is None:
            return value['value'], None
        return HistoryResponse.project(data, request)


@formation_router.get(BASE + '/{kind}')
async def entities_http(request: Request):
    from .read_queries import read_entities

    return await read_http(
        request,
        EntityRequest,
        EntityResponse,
        lambda runtime, parsed: read_entities(
            runtime.database,
            parsed.requirement_id,
            parsed.document_id,
            parsed.kind,
            parsed.payload,
            catalog=runtime.catalog,
        ),
    )


@formation_router.get(BASE + '/{kind}/{entity_ref}')
async def entity_detail_http(request: Request):
    from .read_queries import read_detail

    return await read_http(
        request,
        DetailRequest,
        EntityResponse,
        lambda runtime, parsed: read_detail(
            runtime.database,
            parsed.requirement_id,
            parsed.document_id,
            parsed.kind,
            request.path_params['entity_ref'],
            parsed.payload,
            catalog=runtime.catalog,
        ),
    )


class RelatedRequest(HistoryRequest):
    query_fields = (
        'relation_kind',
        'limit',
        'cursor',
        'known_f',
        'state',
        'branch_ref',
        'include_superseded',
    )
    path_fields = ('step_ref',)

    @classmethod
    def parse(cls, request):
        parsed = super().parse(request)
        if 'known_f' in parsed.payload:
            parsed.payload['known_f'] = decimal_integer(parsed.payload['known_f'], 'known_f')
        if 'include_superseded' in parsed.payload:
            from backend.app.shared.validation import strict_enum

            parsed.payload['include_superseded'] = (
                strict_enum(
                    parsed.payload['include_superseded'], 'include_superseded', ('true', 'false')
                )
                == 'true'
            )
        return parsed


class RangesRequest(RelatedRequest):
    query_fields = ('role', 'limit', 'cursor', 'known_f')
    path_fields = ('artifact_ref',)


class LineageRequest(RangesRequest):
    query_fields = ('limit', 'cursor', 'known_f')


@formation_router.get(BASE + '/steps/{step_ref}/relations')
async def relations_http(request: Request):
    from .relation_queries import read_relations

    return await read_http(
        request,
        RelatedRequest,
        EntityResponse,
        lambda runtime, parsed: read_relations(
            runtime.database,
            parsed.requirement_id,
            parsed.document_id,
            parsed.payload['step_ref'],
            {key: value for key, value in parsed.payload.items() if key != 'step_ref'},
            catalog=runtime.catalog,
        ),
    )


@formation_router.get(BASE + '/artifacts/{artifact_ref}/ranges')
async def ranges_http(request: Request):
    from .relation_queries import read_ranges

    return await read_http(
        request,
        RangesRequest,
        EntityResponse,
        lambda runtime, parsed: read_ranges(
            runtime.database,
            parsed.requirement_id,
            parsed.document_id,
            parsed.payload['artifact_ref'],
            {key: value for key, value in parsed.payload.items() if key != 'artifact_ref'},
            catalog=runtime.catalog,
        ),
    )


@formation_router.get(BASE + '/artifacts/{artifact_ref}/lineage')
async def lineage_http(request: Request):
    from .relation_queries import read_lineage

    return await read_http(
        request,
        LineageRequest,
        EntityResponse,
        lambda runtime, parsed: read_lineage(
            runtime.database,
            parsed.requirement_id,
            parsed.document_id,
            parsed.payload['artifact_ref'],
            {key: value for key, value in parsed.payload.items() if key != 'artifact_ref'},
            catalog=runtime.catalog,
        ),
    )


@dataclass(frozen=True)
class PreviewRequest:
    requirement_id: int
    document_id: int
    payload: dict
    body_fields = (
        'expected_discussion_version',
        'discussion_command',
        'section',
        'limit',
        'cursor',
    )

    @classmethod
    def parse(cls, request, body):
        from .preview_queries import preview_input

        request_query(request)
        preview_input(body)
        return cls(
            decimal_integer(request.path_params['requirement_id'], 'requirement_id'),
            decimal_integer(request.path_params['document_id'], 'document_id'),
            body,
        )


class PreviewResponse:
    errors = HistoryResponse.errors | {
        'FORMATION_INVALID',
        'FORMATION_LIMIT_EXCEEDED',
        'DISCUSSION_VERSION_CONFLICT',
        'CONTENT_VERSION_CONFLICT',
    }

    @staticmethod
    def project(data, request):
        from .preview_contracts import validate

        value = validate(data)
        if value['document_id'] != request.document_id:
            raise ValueError('Preview belongs to another document')
        return value, None


@formation_router.post(BASE + '/path-preview')
async def path_preview_http(request: Request):
    from .preview_queries import preview_path

    return await read_http(
        request,
        PreviewRequest,
        PreviewResponse,
        lambda runtime, parsed: preview_path(
            runtime.database,
            parsed.requirement_id,
            parsed.document_id,
            parsed.payload,
            catalog=runtime.catalog,
        ),
    )
