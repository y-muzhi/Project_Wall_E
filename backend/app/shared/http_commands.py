"""Transport-only command construction; never queries state or writes idempotency."""
from dataclasses import dataclass
from fastapi import Request

from .http_boundary import idempotency_header, request_query
from .validation import decimal_integer, object_fields


@dataclass(frozen=True)
class CommandRequest:
    payload: dict
    body_fields = None
    mandatory = ()
    uses_key = True
    uses_requirement_path = True
    rename = {}
    normalize = staticmethod(lambda payload, validated: payload)

    @classmethod
    def parse(cls, request: Request, body=None):
        request_query(request)
        body = {} if cls.body_fields is None else object_fields(body, 'body', cls.body_fields, cls.mandatory)
        payload = {cls.rename.get(key, key): value for key, value in body.items()}
        if cls.uses_requirement_path:
            payload['requirement_id'] = decimal_integer(request.path_params['requirement_id'], 'requirement_id')
        if cls.uses_key:
            payload['idempotency_key'] = idempotency_header(request)
        return cls(cls.normalize(payload, cls.validate(payload)))
