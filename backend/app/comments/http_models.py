"""I27/I28/I37 exact read transport and safe public projections."""
from dataclasses import dataclass
from backend.app.shared.http_boundary import request_query
from backend.app.shared.http_projection import page
from backend.app.shared.validation import decimal_integer
from .contracts import list_comments_input, comment_list_item, comment_read_model, comment_index_model
from .contracts import create_comment_input, edit_comment_input, resolve_comment_input, reopen_comment_input, delete_comment_input
from backend.app.shared.http_commands import CommandRequest
from backend.app.shared.http_boundary import idempotency_header
from backend.app.shared.validation import object_fields


@dataclass(frozen=True)
class ListCommentsRequest:
    payload: dict

    @classmethod
    def parse(cls, request):
        payload = request_query(request, singles=('page',))
        payload['requirement_id'] = decimal_integer(request.path_params['requirement_id'], 'requirement_id')
        if 'page' in payload:
            payload['page'] = decimal_integer(payload['page'], 'page', maximum=100000)
        validated = list_comments_input(payload)
        return cls({'requirement_id': validated.requirement_id, 'page': validated.page})


class ListCommentsResponse:
    errors = frozenset({'INVALID_INPUT', 'NOT_FOUND', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR'})

    @staticmethod
    def project(data, request):
        def item(value):
            projected = comment_list_item(value)
            if projected['requirement_id'] != request.payload['requirement_id']:
                raise ValueError('Comments must belong to the requested requirement')
            return projected
        return page(data, item, request.payload['page'])


@dataclass(frozen=True)
class GetCommentRequest:
    comment_id: int

    @classmethod
    def parse(cls, request):
        request_query(request)
        return cls(decimal_integer(request.path_params['comment_id'], 'comment_id'))


class GetCommentResponse:
    errors = ListCommentsResponse.errors

    @staticmethod
    def project(data, request):
        value = comment_read_model(data)
        if value['id'] != request.comment_id:
            raise ValueError('Comment response belongs to another identity')
        return value, None


@dataclass(frozen=True)
class GetCommentIndexRequest:
    requirement_id: int

    @classmethod
    def parse(cls, request):
        request_query(request)
        return cls(decimal_integer(request.path_params['requirement_id'], 'requirement_id'))


class GetCommentIndexResponse:
    errors = ListCommentsResponse.errors | {'WORK_STATE_INCONSISTENT'}

    @staticmethod
    def project(data, request):
        value = comment_index_model(data)
        if value['requirement_id'] != request.requirement_id:
            raise ValueError('Index response belongs to another requirement')
        return value, None


class CreateCommentRequest(CommandRequest):
    body_fields = ('expected_content_version', 'content', 'anchor_type', 'block_id', 'selection')
    mandatory = ('expected_content_version', 'content', 'anchor_type', 'block_id')
    validate = staticmethod(create_comment_input)
    normalize = staticmethod(lambda payload, validated: {**validated.business_input(), 'idempotency_key': validated.idempotency_key})


class CreateCommentResponse:
    status = 201
    success_code = 'COMMENT_CREATED'
    errors = ListCommentsResponse.errors | {'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'CONTENT_VERSION_CONFLICT', 'ANCHOR_INVALID', 'IDEMPOTENCY_CONFLICT', 'REQUEST_IN_PROGRESS', 'CAPACITY_EXHAUSTED'}

    @staticmethod
    def project(data, request):
        value = comment_read_model(data)
        if value['requirement_id'] != request.payload['requirement_id'] or value['status'] != 'OPEN' or value['anchor_status'] != 'ATTACHED' or value['deleted_at'] is not None:
            raise ValueError('Creation response must reflect the accepted new comment')
        return value, None


@dataclass(frozen=True)
class CommentActionRequest:
    payload: dict
    body_fields = None
    validate = staticmethod(resolve_comment_input)

    @classmethod
    def parse(cls, request, body=None):
        request_query(request)
        payload = {} if cls.body_fields is None else dict(object_fields(body, 'body', cls.body_fields, cls.body_fields))
        payload.update(comment_id=decimal_integer(request.path_params['comment_id'], 'comment_id'), idempotency_key=idempotency_header(request))
        validated = cls.validate(payload)
        return cls({**validated.business_input(), 'idempotency_key': validated.idempotency_key})


class EditCommentRequest(CommentActionRequest):
    body_fields = ('content',)
    validate = staticmethod(edit_comment_input)


class ResolveCommentRequest(CommentActionRequest):
    validate = staticmethod(resolve_comment_input)


class ReopenCommentRequest(CommentActionRequest):
    validate = staticmethod(reopen_comment_input)


class DeleteCommentRequest(CommentActionRequest):
    validate = staticmethod(delete_comment_input)


class EditCommentResponse:
    success_code = 'COMMENT_UPDATED'
    errors = ListCommentsResponse.errors | {'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'IDEMPOTENCY_CONFLICT', 'REQUEST_IN_PROGRESS'}

    @staticmethod
    def project(data, request):
        value = comment_read_model(data)
        if value['id'] != request.payload['comment_id']:
            raise ValueError('Comment command response belongs to another identity')
        return value, None


ResolveCommentResponse = EditCommentResponse
ReopenCommentResponse = EditCommentResponse
DeleteCommentResponse = EditCommentResponse
