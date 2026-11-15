"""Verify the original OpenCode SDK protocol document independently of runtime."""

import hashlib
import json
from dataclasses import dataclass
from time import monotonic

from .windows_config_source import LockedFileSource

SOURCE_COMMIT = '810c0eba1a7348036f8bdf61e6632d0c36c6876c'
OPENAPI_BLOB = 'e064da66bda63c78272f398c940755ecf68b0a3f'
OPENAPI_BYTES = 1063359

# BE 7.4.2 uses these endpoints on the native instance, not the WALL-E API.
REQUIRED_OPERATIONS = (
    ('/global/health', 'get', '200'),
    ('/session', 'get', '200'),
    ('/session', 'post', '200'),
    ('/session/{sessionID}', 'get', '200'),
    ('/session/{sessionID}', 'patch', '200'),
    ('/session/{sessionID}/prompt_async', 'post', '204'),
    ('/session/status', 'get', '200'),
    ('/session/{sessionID}/message', 'get', '200'),
    ('/session/{sessionID}/message/{messageID}', 'get', '200'),
    ('/config', 'get', '200'),
    ('/config/providers', 'get', '200'),
    ('/question', 'get', '200'),
    ('/question/{requestID}/reply', 'post', '200'),
    ('/permission', 'get', '200'),
    ('/permission/{requestID}/reply', 'post', '200'),
    ('/session/{sessionID}/abort', 'post', '200'),
    ('/event', 'get', '200'),
)


class OpenCodeProtocolSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenCodeProtocolSource:
    commit: str
    blob: str
    byte_count: int


def verify_opencode_protocol_source(path, *, deadline, cancelled):
    if cancelled() or monotonic() >= deadline:
        raise OpenCodeProtocolSourceError('OPENCODE_PROTOCOL_SOURCE_CHECK_INTERRUPTED')
    with LockedFileSource(path, max_file_bytes=OPENAPI_BYTES) as lease:
        original = lease.snapshot
        digest = hashlib.sha1()
        digest.update(f'blob {original.byte_count}\0'.encode('ascii'))
        digest.update(original.raw)
        if original.byte_count != OPENAPI_BYTES or digest.hexdigest() != OPENAPI_BLOB:
            raise OpenCodeProtocolSourceError('OPENCODE_PROTOCOL_SOURCE_BLOB_DIFFERS')
        try:
            source = json.loads(original.raw)
            if source['info']['version'] != '1.0.0':
                raise OpenCodeProtocolSourceError('OPENCODE_PROTOCOL_DOCUMENT_VERSION_DIFFERS')
            for route, method, status in REQUIRED_OPERATIONS:
                response = source['paths'][route][method]['responses'][status]
                if type(response) is not dict:
                    raise OpenCodeProtocolSourceError('OPENCODE_PROTOCOL_OPERATION_DIFFERS')
        except (ValueError, KeyError, TypeError) as error:
            raise OpenCodeProtocolSourceError('OPENCODE_PROTOCOL_OPERATION_DIFFERS') from error
        if cancelled() or monotonic() >= deadline:
            raise OpenCodeProtocolSourceError('OPENCODE_PROTOCOL_SOURCE_CHECK_INTERRUPTED')
        return OpenCodeProtocolSource(SOURCE_COMMIT, OPENAPI_BLOB, OPENAPI_BYTES)
