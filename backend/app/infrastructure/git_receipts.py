"""Strict private GIT20-LOCAL-1 evidence codec; never execution authority.

Only the original operation binds decoded facts to its actual native sources.
A valid receipt does not prove an ACK, a stopped process or delivery success.
No source configuration, stderr, arbitrary result or public projection is stored.
"""

import re
from dataclasses import asdict, dataclass
from datetime import datetime

from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_json_object

from .content_manifest import git_oid, object_format
from .git_ref_protocol import RefProtocolError, branch_ref
from backend.app.shared.json_canonical import canonical_input
from .runtime_launch_journal import LaunchScope

PHASES = ('PREPARED', 'COMMIT_MAY_BE_SENT', 'COMMIT_ACK', 'OBSERVED', 'ABORTED', 'EXITED')
POSTCHECKS = ('NOT_RUN', 'VERIFIED', 'CONFLICT', 'UNKNOWN')
PROTOCOL = 'GIT20-LOCAL-1'


class GitReceiptError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _positive(value):
    if type(value) is not int or not 1 <= value <= MAX_SAFE_INTEGER:
        raise GitReceiptError('GIT_RECEIPT_ID_INVALID')
    return value


def _digest(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise GitReceiptError('GIT_RECEIPT_DIGEST_INVALID')
    return value


def _opaque(value):
    if type(value) is not str or re.fullmatch('[a-zA-Z0-9_-]{16,128}', value) is None:
        raise GitReceiptError('GIT_RECEIPT_OPAQUE_REFERENCE_INVALID')
    return value


def _oid(value, format):
    try:
        git_oid(value, format)
    except ValueError:
        raise GitReceiptError('GIT_RECEIPT_OID_INVALID') from None
    if set(value) == {'0'}:
        raise GitReceiptError('GIT_RECEIPT_ZERO_OID_FORBIDDEN')
    return value


def _ref(value):
    if type(value) is not str:
        raise GitReceiptError('GIT_RECEIPT_REF_INVALID')
    if value.startswith('refs/walle/baselines/'):
        resource = value.removeprefix('refs/walle/baselines/')
        if re.fullmatch('[1-9][0-9]{0,15}', resource) is None:
            raise GitReceiptError('GIT_RECEIPT_REF_INVALID')
        _positive(int(resource))
        return value
    try:
        return branch_ref(value)
    except RefProtocolError:
        raise GitReceiptError('GIT_RECEIPT_REF_INVALID') from None


def _symref(value):
    if value == 'HEAD':
        return value
    if type(value) is not str or not value.startswith('refs/'):
        raise GitReceiptError('GIT_RECEIPT_SYMREF_INVALID')
    try:
        # Reuse Git's full-name character/component rules, without incorrectly
        # claiming an observed unsupported symref must itself be a local branch.
        branch_ref('refs/heads/' + value[5:])
    except RefProtocolError:
        raise GitReceiptError('GIT_RECEIPT_SYMREF_INVALID') from None
    return value


def _timestamp(value):
    if (
        type(value) is not str
        or re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z', value)
        is None
    ):
        raise GitReceiptError('GIT_RECEIPT_TIMESTAMP_INVALID')
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise GitReceiptError('GIT_RECEIPT_TIMESTAMP_INVALID') from None
    return value


def _fields(value, names):
    if type(value) is not dict or set(value) != set(names):
        raise GitReceiptError('GIT_RECEIPT_FIELDS_INVALID')
    return value


@dataclass(frozen=True)
class GitReceiptBinding:
    scope: LaunchScope
    guard_run_ref: str
    repository_id: int
    repository_fingerprint_sha256: str
    planned_commit_oid: str | None
    object_format: str

    def __post_init__(self):
        if type(self.scope) is not LaunchScope:
            raise GitReceiptError('GIT_RECEIPT_ORIGINAL_SCOPE_REQUIRED')
        _opaque(self.guard_run_ref)
        _positive(self.repository_id)
        _digest(self.repository_fingerprint_sha256)
        try:
            object_format(self.object_format)
        except ValueError:
            raise GitReceiptError('GIT_RECEIPT_OBJECT_FORMAT_INVALID') from None
        if self.planned_commit_oid is not None:
            _oid(self.planned_commit_oid, self.object_format)

    def fields(self):
        return {
            'operation_id': self.scope.operation_id,
            'step_no': self.scope.step_no,
            'guard_run_ref': self.guard_run_ref,
            'nonce': self.scope.nonce,
            'protocol_version': PROTOCOL,
            'repository_id': self.repository_id,
            'repository_fingerprint_sha256': self.repository_fingerprint_sha256,
            'planned_commit_oid': self.planned_commit_oid,
        }


@dataclass(frozen=True)
class GitRefObservation:
    full_ref: str
    oid: str | None
    symref: str | None

    def validate(self, format):
        _ref(self.full_ref)
        if self.oid is not None:
            _oid(self.oid, format)
        if self.symref is not None:
            _symref(self.symref)


@dataclass(frozen=True)
class GitReceiptFacts:
    prepared_ack: bool | None
    commit_ack: bool | None
    exit_code: int | None
    ref_observation: GitRefObservation | None
    worktree_fingerprint_sha256: str | None
    postcheck_status: str | None

    def validate(self, format):
        for value in (self.prepared_ack, self.commit_ack):
            if value is not None and type(value) is not bool:
                raise GitReceiptError('GIT_RECEIPT_ACK_INVALID')
        if self.exit_code is not None and (
            type(self.exit_code) is not int
            or not -MAX_SAFE_INTEGER <= self.exit_code <= MAX_SAFE_INTEGER
        ):
            raise GitReceiptError('GIT_RECEIPT_EXIT_CODE_INVALID')
        if self.ref_observation is not None:
            if type(self.ref_observation) is not GitRefObservation:
                raise GitReceiptError('GIT_RECEIPT_REF_OBSERVATION_INVALID')
            self.ref_observation.validate(format)
        if self.worktree_fingerprint_sha256 is not None:
            _digest(self.worktree_fingerprint_sha256)
        if self.postcheck_status is not None and (
            type(self.postcheck_status) is not str or self.postcheck_status not in POSTCHECKS
        ):
            raise GitReceiptError('GIT_RECEIPT_POSTCHECK_INVALID')


@dataclass(frozen=True)
class GitReceipt:
    binding: GitReceiptBinding
    phase: str
    observed_at: str
    facts: GitReceiptFacts

    def fields(self):
        if type(self.binding) is not GitReceiptBinding or type(self.facts) is not GitReceiptFacts:
            raise GitReceiptError('GIT_RECEIPT_ORIGINAL_TYPES_REQUIRED')
        if type(self.phase) is not str or self.phase not in PHASES:
            raise GitReceiptError('GIT_RECEIPT_PHASE_INVALID')
        _timestamp(self.observed_at)
        self.facts.validate(self.binding.object_format)
        return {
            'schema_version': 1,
            **self.binding.fields(),
            'phase': self.phase,
            'observed_at': self.observed_at,
            'facts': asdict(self.facts),
        }


def _limit(maximum):
    if type(maximum) is not int or not 1 <= maximum <= MAX_SAFE_INTEGER:
        raise GitReceiptError('GIT_RECEIPT_LIMIT_INVALID')


def encode_receipt(receipt, *, max_receipt_bytes):
    _limit(max_receipt_bytes)
    if type(receipt) is not GitReceipt:
        raise GitReceiptError('GIT_RECEIPT_ORIGINAL_TYPES_REQUIRED')
    try:
        raw = (canonical_input(receipt.fields()) + '\n').encode('utf-8', errors='strict')
    except UnicodeError:
        raise GitReceiptError('GIT_RECEIPT_UTF8_INVALID') from None
    if len(raw) > max_receipt_bytes:
        raise GitReceiptError('GIT_RECEIPT_BYTES_EXCEEDED')
    return raw


def decode_receipt(raw, binding, *, max_receipt_bytes):
    _limit(max_receipt_bytes)
    if type(binding) is not GitReceiptBinding:
        raise GitReceiptError('GIT_RECEIPT_ORIGINAL_BINDING_REQUIRED')
    if type(raw) is not bytes or not raw or len(raw) > max_receipt_bytes:
        raise GitReceiptError('GIT_RECEIPT_BYTES_INVALID')
    try:
        value = strict_json_object(raw)
    except ValueError:
        raise GitReceiptError('GIT_RECEIPT_JSON_INVALID') from None
    names = set(binding.fields()) | {'schema_version', 'phase', 'observed_at', 'facts'}
    _fields(value, names)
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise GitReceiptError('GIT_RECEIPT_SCHEMA_INVALID')
    for name, expected in binding.fields().items():
        if type(value[name]) is not type(expected) or value[name] != expected:
            raise GitReceiptError('GIT_RECEIPT_ORIGINAL_BINDING_DIFFERS')
    facts = dict(_fields(value['facts'], GitReceiptFacts.__dataclass_fields__))
    if facts['ref_observation'] is not None:
        ref = _fields(facts['ref_observation'], GitRefObservation.__dataclass_fields__)
        facts['ref_observation'] = GitRefObservation(**ref)
    receipt = GitReceipt(binding, value['phase'], value['observed_at'], GitReceiptFacts(**facts))
    if encode_receipt(receipt, max_receipt_bytes=max_receipt_bytes) != raw:
        raise GitReceiptError('GIT_RECEIPT_CANONICAL_BYTES_DIFFER')
    return receipt
