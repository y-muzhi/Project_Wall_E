"""Fixed raw cat-file reads with exact type/OID integrity, never rev expressions.

A verified object is bounded original bytes, not a parsed tree, complete history,
content-policy approval, object closure or a registered baseline.
"""

import hashlib
from dataclasses import dataclass, field

from backend.app.shared.validation import MAX_SAFE_INTEGER

from .content_manifest import git_oid, object_format
from .git_repository_read import RepositoryReadCommand
from .windows_pipe_capture import require_complete_output

OBJECT_TYPES = ('commit', 'tree', 'blob')


class GitObjectReadError(ValueError):
    code = 'CONTENT_NOT_READY'


@dataclass(frozen=True)
class ReadGitObject:
    format: str
    object_type: str
    object_oid: str
    byte_count: int
    sha256: str
    raw: bytes = field(repr=False)


def _binding(format, object_type, oid):
    object_format(format)
    if type(object_type) is not str or object_type not in OBJECT_TYPES:
        raise GitObjectReadError('RAW_GIT_OBJECT_TYPE_UNSUPPORTED')
    git_oid(oid, format)
    if set(oid) == {'0'}:
        raise GitObjectReadError('RAW_GIT_OBJECT_OID_INVALID')


def git_object_id(raw, *, format, object_type):
    object_format(format)
    if type(raw) is not bytes or object_type not in OBJECT_TYPES:
        raise GitObjectReadError('RAW_GIT_OBJECT_TYPE_OR_BYTES_INVALID')
    digest = hashlib.new(format)
    digest.update(object_type.encode('ascii') + b' ' + str(len(raw)).encode('ascii') + b'\0')
    digest.update(raw)
    return digest.hexdigest()


def verify_git_object(raw, *, format, object_type, oid, max_output_bytes):
    _binding(format, object_type, oid)
    if (
        type(raw) is not bytes
        or type(max_output_bytes) is not int
        or not 1 <= max_output_bytes <= MAX_SAFE_INTEGER
        or len(raw) > max_output_bytes
    ):
        raise GitObjectReadError('RAW_GIT_OBJECT_BYTES_INVALID')
    if git_object_id(raw, format=format, object_type=object_type) != oid:
        # cat-file <type> can dereference a tag or extract a commit's tree.
        # Recomputing with the requested type rejects every such conversion.
        raise GitObjectReadError('RAW_GIT_OBJECT_TYPE_OR_OID_DIFFERS')
    return ReadGitObject(format, object_type, oid, len(raw), hashlib.sha256(raw).hexdigest(), raw)


class RepositoryObjectCommand(RepositoryReadCommand):
    def __init__(self, metadata, parsed_config, hooks, *, object_type, oid):
        # Resource validation is owned by the same base as metadata commands.
        self._object_type, self._oid = object_type, oid
        super().__init__(metadata, parsed_config, hooks)
        _binding(self._original['metadata']['object_format'], object_type, oid)

    def command_facts(self):
        return {
            'command': 'RAW_GIT_OBJECT_1',
            'object_type': self._object_type,
            'object_oid': self._oid,
        }

    def arguments(self):
        self.facts()
        _binding(self._original['metadata']['object_format'], self._object_type, self._oid)
        return super().arguments() + ('cat-file', self._object_type, self._oid)

    def decode_output(self, output, *, scope, io_nonce, exit_code, max_output_bytes):
        self.facts()
        output = require_complete_output(
            output,
            scope=scope,
            io_nonce=io_nonce,
            exit_code=exit_code,
            max_output_bytes=max_output_bytes,
        )
        result = verify_git_object(
            output.stdout,
            format=self._original['metadata']['object_format'],
            object_type=self._object_type,
            oid=self._oid,
            max_output_bytes=max_output_bytes,
        )
        self.facts()
        return result
