"""GIT20-LOCAL-1 immutable delivery commit bytes, no Git/database/filesystem IO.

BUILD renders the adopted template once. Recovery validates and reads the exact
stored bytes; it never substitutes a new time, identity, template or parent.
"""

import hashlib
import re
from dataclasses import asdict, dataclass, field
from string import Formatter

from backend.app.shared.validation import MAX_SAFE_INTEGER

from .content_manifest import ContentManifestError, git_oid, object_format
from backend.app.shared.json_canonical import canonical_input


class DeliveryCommitError(ValueError):
    pass


@dataclass(frozen=True)
class CommitIdentity:
    name: str
    email: str


@dataclass(frozen=True)
class DeliveryReflogIdentity:
    name: str
    email: str
    unix_seconds: int

    def __post_init__(self):
        _identity(CommitIdentity(self.name, self.email))
        _integer(self.unix_seconds, minimum=0)

    @property
    def digest(self):
        return hashlib.sha256(canonical_input(asdict(self)).encode('utf-8')).hexdigest()

    def environment(self):
        return {
            'GIT_COMMITTER_NAME': self.name,
            'GIT_COMMITTER_EMAIL': self.email,
            'GIT_COMMITTER_DATE': f'{self.unix_seconds} +0000',
        }


@dataclass(frozen=True)
class DeliveryCommitInput:
    format: str
    tree_oid: str
    parent_oid: str
    delivery_id: int
    fixed_unix_seconds: int
    author: CommitIdentity
    committer: CommitIdentity
    payload: bytes = field(repr=False)
    payload_sha256: str
    commit_oid: str


def _integer(value, *, minimum=1):
    if type(value) is not int or not minimum <= value <= MAX_SAFE_INTEGER:
        raise DeliveryCommitError('DELIVERY_COMMIT_INTEGER_INVALID')
    return value


def _text(value):
    if type(value) is not str or '\0' in value:
        raise DeliveryCommitError('DELIVERY_COMMIT_TEXT_INVALID')
    try:
        value.encode('utf-8', errors='strict')
    except UnicodeError:
        raise DeliveryCommitError('DELIVERY_COMMIT_TEXT_INVALID') from None
    return value


def _identity(value):
    if type(value) is not CommitIdentity:
        raise DeliveryCommitError('DELIVERY_COMMIT_IDENTITY_INVALID')
    for part in (value.name, value.email):
        _text(part)
        if (
            not part.strip()
            or '<' in part
            or '>' in part
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in part)
        ):
            raise DeliveryCommitError('DELIVERY_COMMIT_IDENTITY_INVALID')
    return value


def _objects(format, tree, parent):
    try:
        format = object_format(format)
        git_oid(tree, format)
        git_oid(parent, format)
    except ContentManifestError:
        raise DeliveryCommitError('DELIVERY_COMMIT_OBJECT_BINDING_INVALID') from None
    if set(tree) == {'0'} or set(parent) == {'0'}:
        raise DeliveryCommitError('DELIVERY_COMMIT_OBJECT_BINDING_INVALID')
    return format


def _trailer(line):
    return re.match(r'^[ \t]*WALL-E-Delivery[ \t]*:', line, re.IGNORECASE) is not None


def render_delivery_message(template, *, task_id, candidate_id):
    """Only the two documented literal ID substitutions, no format expressions."""
    _text(template)
    values = {
        'task_id': str(_integer(task_id)),
        'candidate_id': str(_integer(candidate_id)),
    }
    parts = []
    try:
        for literal, name, spec, conversion in Formatter().parse(template):
            parts.append(literal)
            if name is not None:
                if name not in values or spec or conversion is not None:
                    raise DeliveryCommitError('DELIVERY_COMMIT_TEMPLATE_INVALID')
                parts.append(values[name])
    except ValueError:
        raise DeliveryCommitError('DELIVERY_COMMIT_TEMPLATE_INVALID') from None
    result = ''.join(parts).replace('\r\n', '\n').replace('\r', '\n')
    if any(_trailer(line) for line in result.split('\n')):
        raise DeliveryCommitError('DELIVERY_COMMIT_TRAILER_ALREADY_PRESENT')
    return result


def _hash(raw, format):
    header = b'commit ' + str(len(raw)).encode('ascii') + b'\0'
    return hashlib.new(format, header + raw).hexdigest()


def build_delivery_commit(
    *,
    format,
    tree_oid,
    parent_oid,
    delivery_id,
    fixed_unix_seconds,
    author,
    committer,
    message_template,
    task_id,
    candidate_id,
    max_payload_bytes,
):
    format = _objects(format, tree_oid, parent_oid)
    _integer(delivery_id)
    _integer(fixed_unix_seconds, minimum=0)
    _integer(max_payload_bytes)
    author, committer = _identity(author), _identity(committer)
    message = render_delivery_message(message_template, task_id=task_id, candidate_id=candidate_id)
    if message and not message.endswith('\n'):
        message += '\n'
    payload = (
        f'tree {tree_oid}\nparent {parent_oid}\n'
        f'author {author.name} <{author.email}> {fixed_unix_seconds} +0000\n'
        f'committer {committer.name} <{committer.email}> {fixed_unix_seconds} +0000\n\n'
        + message
        + f'WALL-E-Delivery: {delivery_id}\n'
    ).encode('utf-8')
    if len(payload) > max_payload_bytes:
        raise DeliveryCommitError('DELIVERY_COMMIT_PAYLOAD_TOO_LARGE')
    return DeliveryCommitInput(
        format,
        tree_oid,
        parent_oid,
        delivery_id,
        fixed_unix_seconds,
        author,
        committer,
        payload,
        hashlib.sha256(payload).hexdigest(),
        _hash(payload, format),
    )


def _stored_identity(line, kind):
    match = re.fullmatch(
        re.escape(kind) + r' (.*?) <([^<>]*)> (0|[1-9][0-9]*) \+0000',
        line,
    )
    if match is None:
        raise DeliveryCommitError('STORED_DELIVERY_COMMIT_HEADER_INVALID')
    identity = _identity(CommitIdentity(match[1], match[2]))
    if len(match[3]) > len(str(MAX_SAFE_INTEGER)):
        raise DeliveryCommitError('DELIVERY_COMMIT_INTEGER_INVALID')
    timestamp = _integer(int(match[3]), minimum=0)
    return identity, timestamp


def verify_stored_delivery_commit(
    raw,
    *,
    format,
    tree_oid,
    parent_oid,
    delivery_id,
    expected_payload_sha256,
    expected_commit_oid,
    max_payload_bytes,
):
    """Integrity/association check only; never render a template during recovery."""
    format = _objects(format, tree_oid, parent_oid)
    _integer(delivery_id)
    _integer(max_payload_bytes)
    if type(raw) is not bytes or not raw or len(raw) > max_payload_bytes:
        raise DeliveryCommitError('STORED_DELIVERY_COMMIT_PAYLOAD_INVALID')
    if (
        type(expected_payload_sha256) is not str
        or re.fullmatch('[0-9a-f]{64}', expected_payload_sha256) is None
        or hashlib.sha256(raw).hexdigest() != expected_payload_sha256
        or _hash(raw, format) != expected_commit_oid
    ):
        raise DeliveryCommitError('STORED_DELIVERY_COMMIT_BYTES_DIFFER')
    try:
        text = raw.decode('utf-8', errors='strict')
    except UnicodeError:
        raise DeliveryCommitError('STORED_DELIVERY_COMMIT_UTF8_INVALID') from None
    if '\r' in text or '\0' in text or not text.endswith('\n'):
        raise DeliveryCommitError('STORED_DELIVERY_COMMIT_WIRE_INVALID')
    headers, separator, body = text.partition('\n\n')
    lines = headers.split('\n')
    if (
        not separator
        or len(lines) != 4
        or lines[0] != 'tree ' + tree_oid
        or lines[1] != 'parent ' + parent_oid
    ):
        raise DeliveryCommitError('STORED_DELIVERY_COMMIT_HEADER_INVALID')
    author, timestamp = _stored_identity(lines[2], 'author')
    committer, committer_time = _stored_identity(lines[3], 'committer')
    if timestamp != committer_time:
        raise DeliveryCommitError('STORED_DELIVERY_COMMIT_TIME_DIFFERS')
    body_lines = body.split('\n')
    if (
        len(body_lines) < 2
        or body_lines[-2] != f'WALL-E-Delivery: {delivery_id}'
        or sum(_trailer(line) for line in body_lines) != 1
    ):
        raise DeliveryCommitError('STORED_DELIVERY_COMMIT_TRAILER_INVALID')
    return DeliveryCommitInput(
        format,
        tree_oid,
        parent_oid,
        delivery_id,
        timestamp,
        author,
        committer,
        raw,
        expected_payload_sha256,
        expected_commit_oid,
    )
