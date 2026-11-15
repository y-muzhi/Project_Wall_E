"""GIT20-BASELINE-1 / GIT20-LOCAL-1 ref input and original ACK decoding.

No Git, refs, processes or business dispatch change here. PREPARE bytes NEVER
contain COMMIT; the original operation must durably fence a later single send.
A valid ref syntax or ACK stream alone is not source/process/lock evidence.
"""

import hashlib
from dataclasses import asdict, dataclass

from backend.app.shared.validation import MAX_SAFE_INTEGER

from .content_manifest import git_oid, object_format
from backend.app.shared.json_canonical import canonical_input


class RefProtocolError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _positive(value):
    if type(value) is not int or not 1 <= value <= MAX_SAFE_INTEGER:
        raise RefProtocolError('GIT_REF_INTEGER_INVALID')
    return value


def branch_ref(value):
    """Full refs/heads name only; no shorthand/normalization or rev expansion."""
    if type(value) is not str:
        raise RefProtocolError('GIT_BRANCH_REF_INVALID')
    try:
        value.encode('utf-8', errors='strict')
    except UnicodeError:
        raise RefProtocolError('GIT_BRANCH_REF_INVALID') from None
    if (
        not value.startswith('refs/heads/')
        or value.endswith(('/', '.'))
        or '//' in value
        or '..' in value
        or '@{' in value
        or any(ord(char) <= 32 or ord(char) == 127 or char in '~^:?*[\\' for char in value)
        or any(part.startswith('.') or part.endswith('.lock') for part in value.split('/'))
    ):
        raise RefProtocolError('GIT_BRANCH_REF_INVALID')
    return value


def _nonzero_oid(value, format):
    try:
        git_oid(value, format)
    except ValueError:
        raise RefProtocolError('GIT_REF_OID_INVALID') from None
    if set(value) == {'0'}:
        raise RefProtocolError('GIT_REF_ZERO_OID_FORBIDDEN')
    return value


@dataclass(frozen=True)
class RefPrepareInput:
    kind: str
    resource_id: int
    object_format: str
    full_ref: str
    new_oid: str
    expected_oid: str | None

    def __post_init__(self):
        _positive(self.resource_id)
        try:
            object_format(self.object_format)
        except ValueError:
            raise RefProtocolError('GIT_REF_OBJECT_FORMAT_INVALID') from None
        _nonzero_oid(self.new_oid, self.object_format)
        if self.kind == 'BASELINE_CREATE':
            if (
                type(self.full_ref) is not str
                or self.full_ref != 'refs/walle/baselines/' + str(self.resource_id)
                or self.expected_oid is not None
            ):
                raise RefProtocolError('GIT_BASELINE_CREATE_INPUT_INVALID')
        elif self.kind == 'DELIVERY_UPDATE':
            branch_ref(self.full_ref)
            _nonzero_oid(self.expected_oid, self.object_format)
        else:
            raise RefProtocolError('GIT_REF_COMMAND_KIND_INVALID')

    def arguments(self):
        if self.kind == 'BASELINE_CREATE':
            return ('update-ref', '--no-deref', '--stdin', '-z')
        return (
            'update-ref',
            '--no-deref',
            '--create-reflog',
            '-m',
            'WALLE:' + str(self.resource_id),
            '--stdin',
            '-z',
        )

    def prepare_bytes(self):
        if self.kind == 'BASELINE_CREATE':
            command = (
                b'create '
                + self.full_ref.encode('utf-8')
                + b'\0'
                + self.new_oid.encode('ascii')
                + b'\0'
            )
        else:
            command = (
                b'update '
                + self.full_ref.encode('utf-8')
                + b'\0'
                + self.new_oid.encode('ascii')
                + b'\0'
                + self.expected_oid.encode('ascii')
                + b'\0'
            )
        return b'start\0' + command + b'prepare\0'

    @property
    def input_sha256(self):
        return hashlib.sha256(canonical_input(asdict(self)).encode('utf-8')).hexdigest()


def baseline_create(snapshot_id, commit_oid, *, format):
    return RefPrepareInput(
        'BASELINE_CREATE',
        snapshot_id,
        format,
        'refs/walle/baselines/' + str(_positive(snapshot_id)),
        commit_oid,
        None,
    )


def delivery_update(delivery_id, full_ref, planned_oid, expected_oid, *, format):
    return RefPrepareInput(
        'DELIVERY_UPDATE', delivery_id, format, full_ref, planned_oid, expected_oid
    )


@dataclass(frozen=True)
class DeliveryAncestorQuery:
    object_format: str
    ancestor_oid: str
    descendant_oid: str

    def __post_init__(self):
        object_format(self.object_format)
        _nonzero_oid(self.ancestor_oid, self.object_format)
        _nonzero_oid(self.descendant_oid, self.object_format)
        if self.ancestor_oid == self.descendant_oid:
            raise RefProtocolError('GIT_DELIVERY_ANCESTRY_REQUIRES_DIFFERENT_OBJECTS')

    @property
    def digest(self):
        return hashlib.sha256(canonical_input(asdict(self)).encode('utf-8')).hexdigest()

    def arguments(self):
        return ('merge-base', '--is-ancestor', self.ancestor_oid, self.descendant_oid)


def commit_bytes():
    """Caller must persist MAY_HAVE_BEEN_SENT under its original write fence first."""
    return b'commit\0'


def abort_bytes():
    return b'abort\0'


_ACK_LINES = {
    b'start: ok\n': 'START',
    b'prepare: ok\n': 'PREPARE',
    b'commit: ok\n': 'COMMIT',
    b'abort: ok\n': 'ABORT',
}


class RefAckDecoder:
    """Bounded exact STDOUT bytes from ONE original Git process, never stderr."""

    def __init__(self, *, max_output_bytes):
        self._limit = _positive(max_output_bytes)
        self._received = 0
        self._pending = bytearray()
        self._phases = []
        self._broken = False
        self._finished = False

    def _fail(self, reason):
        self._broken = True
        raise RefProtocolError(reason)

    def _allowed(self):
        if not self._phases:
            return ('START',)
        if self._phases == ['START']:
            return ('PREPARE', 'ABORT')
        if self._phases == ['START', 'PREPARE']:
            return ('COMMIT', 'ABORT')
        return ()

    @property
    def phases(self):
        if self._broken:
            raise RefProtocolError('GIT_ACK_STREAM_INVALID')
        return tuple(self._phases)

    def feed(self, raw):
        if self._broken or self._finished:
            self._fail('GIT_ACK_STREAM_CLOSED')
        if type(raw) is not bytes:
            self._fail('GIT_ACK_BYTES_REQUIRED')
        if self._received + len(raw) > self._limit:
            self._fail('GIT_ACK_OUTPUT_LIMIT_EXCEEDED')
        self._received += len(raw)
        self._pending.extend(raw)
        while b'\n' in self._pending:
            end = self._pending.index(10) + 1
            line = bytes(self._pending[:end])
            phase = _ACK_LINES.get(line)
            if phase is None or phase not in self._allowed():
                self._fail('GIT_ACK_FRAME_OR_ORDER_INVALID')
            self._phases.append(phase)
            del self._pending[:end]
        if self._pending and not any(
            line.startswith(self._pending)
            for line, phase in _ACK_LINES.items()
            if phase in self._allowed()
        ):
            self._fail('GIT_ACK_FRAME_OR_ORDER_INVALID')

    def finish(self, *, expected_terminal):
        if self._broken or self._finished:
            self._fail('GIT_ACK_STREAM_CLOSED')
        if (
            expected_terminal not in ('COMMIT', 'ABORT')
            or self._pending
            or not self._phases
            or self._phases[-1] != expected_terminal
        ):
            self._fail('GIT_ACK_TERMINAL_UNVERIFIED')
        self._finished = True
        return self.phases


def prepared_ref_observation(raw, intent, *, query_exit_code, max_output_bytes):
    """Successful original for-each-ref: %(refname)%00%(objectname)%00%(symref)%00.

    Caller must bind the query and prepare ACK to the original held process/
    repository. Empty stdout is absence only after an explicit exit-code zero.
    """
    limit = _positive(max_output_bytes)
    if type(intent) is not RefPrepareInput:
        raise RefProtocolError('GIT_REF_ORIGINAL_INPUT_REQUIRED')
    if type(query_exit_code) is not int or query_exit_code != 0:
        raise RefProtocolError('GIT_REF_QUERY_RESULT_UNVERIFIED')
    if type(raw) is not bytes or len(raw) > limit:
        raise RefProtocolError('GIT_REF_QUERY_OUTPUT_INVALID')
    if intent.kind == 'BASELINE_CREATE':
        if raw:
            raise RefProtocolError('GIT_BASELINE_REF_NOT_ABSENT')
        return {'full_ref': intent.full_ref, 'oid': None, 'symref': None}
    observed = exact_direct_ref_observation(
        raw,
        intent.full_ref,
        intent.object_format,
        query_exit_code=query_exit_code,
        max_output_bytes=limit,
    )
    if observed['oid'] != intent.expected_oid:
        raise RefProtocolError('GIT_REF_QUERY_EXPECTED_VALUE_DIFFERS')
    return observed


def exact_direct_ref_observation(raw, full_ref, format, *, query_exit_code, max_output_bytes):
    """Decode the fixed local branch observation without following a symbolic ref."""
    branch_ref(full_ref)
    limit = _positive(max_output_bytes)
    if type(query_exit_code) is not int or query_exit_code != 0:
        raise RefProtocolError('GIT_REF_QUERY_RESULT_UNVERIFIED')
    if type(raw) is not bytes or len(raw) > limit:
        raise RefProtocolError('GIT_REF_QUERY_OUTPUT_INVALID')
    if not raw:
        return {'full_ref': full_ref, 'oid': None, 'symref': None}
    fields = raw.split(b'\0')
    if len(fields) != 4 or fields[-1] != b'\n' or fields[0] != full_ref.encode('utf-8'):
        raise RefProtocolError('GIT_REF_QUERY_NOT_UNIQUE_OR_EXACT')
    if fields[2]:
        raise RefProtocolError('GIT_REF_SYMBOLIC_TARGET_FORBIDDEN')
    try:
        oid = _nonzero_oid(fields[1].decode('ascii', errors='strict'), format)
    except (UnicodeError, RefProtocolError):
        raise RefProtocolError('GIT_REF_QUERY_OID_INVALID') from None
    return {'full_ref': full_ref, 'oid': oid, 'symref': None}


def branch_namespace(values):
    """Full branch grammar plus conservative aliases, preserving exact duplicates.

    Ref grammar differs from product-file paths; in particular this never applies
    content-path normalization, modes, or NFC changes to existing Git names.
    """
    names = {}
    result = []
    for value in values:
        value = branch_ref(value)
        parts = value.split('/')
        proposed = []
        for length in range(1, len(parts) + 1):
            spelling = '/'.join(parts[:length])
            kind = 'REF' if length == len(parts) else 'DIRECTORY'
            key = spelling.casefold()
            previous = names.get(key)
            if previous is not None and previous != (spelling, kind):
                raise RefProtocolError('GIT_BRANCH_NAMESPACE_ALIAS_OR_CONFLICT')
            proposed.append((key, (spelling, kind)))
        names.update(proposed)
        result.append(value)
    return tuple(result)
