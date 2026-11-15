"""CHECK20 assertion facts from bounded original observations or a bound driver stream."""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from math import isfinite

from backend.app.shared.validation import (
    MAX_SAFE_INTEGER,
    strict_integer,
    strict_json_loads,
    strict_json_object,
)

from .check_case_pack import CasePack, CheckCase
from .check_case_values import header_value, json_literal, response_header
from .check_runner_bundle import CheckResourceError, exact_record, reference, valid_sha256
from backend.app.shared.json_canonical import canonical_input

_SCALAR_TEXT_BYTES = 4096
_MAX_FRAME_BYTES = 128 * 1024
_RESULT_KEYS = ('assertion_id', 'result', 'actual_value')
_FRAME_KEYS = (
    'schema_version',
    'verification_id',
    'item_id',
    'nonce',
    'seq',
    'type',
    'case_id',
    'assertion_results',
    'observed_at',
)


class CheckEvidenceUnknown(CheckResourceError):
    pass


def _scalar(value):
    if value is None or type(value) is bool:
        return value
    if type(value) is int and abs(value) <= MAX_SAFE_INTEGER:
        return value
    if type(value) is float and isfinite(value):
        return value
    if (
        type(value) is str
        and len(value.encode('utf-8', errors='strict')) <= _SCALAR_TEXT_BYTES
        and all(ord(char) >= 32 or char in '\r\n\t' for char in value)
        and '\x7f' not in value
    ):
        return value
    raise CheckEvidenceUnknown('CHECK20_ACTUAL_SCALAR_INVALID')


def validated_assertions(values, expected):
    if type(values) is not list or len(values) != len(expected) or not expected:
        raise CheckEvidenceUnknown('CHECK20_ASSERTION_COUNT_DIFFERS')
    output = []
    identities = set()
    for raw in values:
        row = exact_record(raw, _RESULT_KEYS)
        identity = reference(row['assertion_id'])
        if (
            identity in identities
            or identity not in expected
            or row['result'] not in ('PASSED', 'FAILED')
        ):
            raise CheckEvidenceUnknown('CHECK20_ASSERTION_IDENTITY_OR_RESULT_DIFFERS')
        identities.add(identity)
        output.append(
            {
                'assertion_id': identity,
                'result': row['result'],
                'actual_value': _scalar(row['actual_value']),
            }
        )
    return tuple(output)


def _hash_summary(raw):
    return 'sha256:' + sha256(raw).hexdigest()


def _outcome(case, rows, *, redacted):
    assertions = validated_assertions(rows, {item.assertion_id for item in case.assertions})
    return {
        'case_id': case.case_id,
        'result': 'FAILED' if any(row['result'] == 'FAILED' for row in assertions) else 'PASSED',
        'assertion_results': list(assertions),
        'capture_status': 'REDACTED' if redacted else 'FULL',
    }


def _result(assertion, matched, actual):
    return {
        'assertion_id': assertion.assertion_id,
        'result': 'PASSED' if matched else 'FAILED',
        'actual_value': actual,
    }


def _complete_bytes(raw, maximum):
    if type(raw) is not bytes or len(raw) > maximum:
        raise CheckEvidenceUnknown('CHECK20_ORIGINAL_OUTPUT_LIMIT')
    return raw


def _cli_facts(case, exit_code, *, stdout_matches, stdout_summary):
    if type(case) is not CheckCase or len(case.steps) != 1 or case.steps[0].op != 'RUN':
        raise CheckEvidenceUnknown('CHECK20_CLI_ORIGINAL_OBSERVATION_REQUIRED')
    actual_exit = strict_integer(exit_code, 'exit_code', minimum=0, maximum=(1 << 32) - 1)
    facts = []
    redacted = False
    for item in case.assertions:
        (expected,) = item.operands
        if item.op == 'EXIT_CODE':
            facts.append(_result(item, actual_exit == expected, actual_exit))
        elif item.op == 'STDOUT_BYTES':
            facts.append(_result(item, stdout_matches(expected), stdout_summary))
            redacted = True
        else:
            raise CheckEvidenceUnknown('CHECK20_CLI_ASSERTION_KIND_DIFFERS')
    return _outcome(case, facts, redacted=redacted)


def evaluate_cli_case(case, *, exit_code, stdout, output_limit, complete):
    """Compare bounded original bytes while the owned command output is held."""
    if complete is not True:
        raise CheckEvidenceUnknown('CHECK20_CLI_ORIGINAL_OBSERVATION_REQUIRED')
    limit = strict_integer(output_limit, 'output_limit', maximum=16 * 1024 * 1024)
    original_stdout = _complete_bytes(stdout, limit)
    return _cli_facts(
        case,
        exit_code,
        stdout_matches=lambda expected: original_stdout == expected,
        stdout_summary=_hash_summary(original_stdout),
    )


def recover_cli_case(case, *, exit_code, stdout_byte_count, stdout_sha256):
    """Reproduce the comparison from the protected complete stdout summary."""
    strict_integer(stdout_byte_count, 'stdout_byte_count', minimum=0)
    if not valid_sha256(stdout_sha256):
        raise CheckEvidenceUnknown('CHECK20_CLI_ORIGINAL_OBSERVATION_REQUIRED')
    return _cli_facts(
        case,
        exit_code,
        stdout_matches=lambda expected: (
            (len(expected), sha256(expected).hexdigest()) == (stdout_byte_count, stdout_sha256)
        ),
        stdout_summary='sha256:' + stdout_sha256,
    )


@dataclass(frozen=True)
class HttpStepObservation:
    step_id: str
    status: int
    headers: tuple[tuple[str, str], ...] = field(repr=False)
    body: bytes = field(repr=False)
    complete: bool = True


def _http_observations(case, rows, limit):
    if type(rows) is not tuple or len(rows) != len(case.steps):
        raise CheckEvidenceUnknown('CHECK20_HTTP_STEP_COUNT_DIFFERS')
    originals = {}
    consumed = 0
    for step, row in zip(case.steps, rows, strict=True):
        if (
            step.op != 'REQUEST'
            or type(row) is not HttpStepObservation
            or row.complete is not True
            or row.step_id != step.step_id
            or type(row.headers) is not tuple
            or len(row.headers) > 64
        ):
            raise CheckEvidenceUnknown('CHECK20_HTTP_ORIGINAL_STEP_DIFFERS')
        strict_integer(row.status, 'status', 100, 599)
        consumed += len(_complete_bytes(row.body, limit))
        for header in row.headers:
            if type(header) is not tuple or len(header) != 2:
                raise CheckEvidenceUnknown('CHECK20_HTTP_HEADER_CAPTURE_DIFFERS')
            name, value = header
            consumed += len(response_header(name)) + len(header_value(value))
        if consumed > limit:
            raise CheckEvidenceUnknown('CHECK20_ORIGINAL_OUTPUT_LIMIT')
        originals[row.step_id] = row
    return originals


_MISSING = object()


def _lookup_pointer(value, tokens):
    current = value
    for token in tokens:
        if type(current) is dict and token in current:
            current = current[token]
        elif (
            type(current) is list
            and re.fullmatch(r'0|[1-9][0-9]{0,8}', token)
            and int(token) < len(current)
        ):
            current = current[int(token)]
        else:
            return _MISSING
    return current


def _json_fact(body, tokens, expected_json):
    try:
        loaded = json_literal(strict_json_loads(body, 'response_body'))
    except (CheckResourceError, TypeError, ValueError):
        return False, None, False
    found = _lookup_pointer(loaded, tokens)
    if found is _MISSING:
        return False, None, False
    expected = json.loads(expected_json)
    observed = canonical_input({'value': found}).encode('utf-8')
    matched = observed == canonical_input({'value': expected}).encode('utf-8')
    if type(found) in (str, list, dict):
        return matched, _hash_summary(observed), True
    return matched, _scalar(found), False


def evaluate_http_case(case, rows, *, output_limit):
    """Compare complete responses in original step order, without issuing requests."""
    if type(case) is not CheckCase:
        raise CheckEvidenceUnknown('CHECK20_HTTP_ORIGINAL_OBSERVATION_REQUIRED')
    limit = strict_integer(output_limit, 'output_limit', maximum=16 * 1024 * 1024)
    observations = _http_observations(case, rows, limit)
    facts = []
    redacted = False
    for item in case.assertions:
        step_id, *operands = item.operands
        row = observations.get(step_id)
        if row is None:
            raise CheckEvidenceUnknown('CHECK20_HTTP_ASSERTION_STEP_DIFFERS')
        if item.op == 'STATUS':
            facts.append(_result(item, row.status == operands[0], row.status))
        elif item.op == 'BODY_BYTES':
            facts.append(_result(item, row.body == operands[0], _hash_summary(row.body)))
            redacted = True
        elif item.op == 'HEADER':
            name, expected = operands
            values = [value for key, value in row.headers if key == name]
            if len(values) > 1:
                raise CheckEvidenceUnknown('CHECK20_HTTP_ASSERTED_HEADER_AMBIGUOUS')
            actual = values[0] if values else None
            facts.append(
                _result(
                    item,
                    actual == expected,
                    None if actual is None else _hash_summary(actual.encode('utf-8')),
                )
            )
            redacted |= actual is not None
        elif item.op == 'JSON_POINTER':
            matched, actual, private = _json_fact(row.body, *operands)
            facts.append(_result(item, matched, actual))
            redacted |= private
        else:
            raise CheckEvidenceUnknown('CHECK20_HTTP_ASSERTION_KIND_DIFFERS')
    return _outcome(case, facts, redacted=redacted)


@dataclass(frozen=True)
class DriverFrameIdentity:
    verification_id: int
    item_id: int
    nonce: str

    def __post_init__(self):
        strict_integer(self.verification_id, 'verification_id')
        strict_integer(self.item_id, 'item_id')
        if type(self.nonce) is not str or re.fullmatch('[0-9a-f]{32}', self.nonce) is None:
            raise CheckEvidenceUnknown('CHECK20_ORIGINAL_DRIVER_NONCE_REQUIRED')


class BrowserCaseFrames:
    """Validate frames read from an already authenticated, root-only Guard pipe.

    An object of this type does not authenticate a pipe or infer process exit.
    A caller must supply those original native facts, never candidate stdout.
    """

    def __init__(self, identity, pack, *, max_bytes):
        if (
            type(identity) is not DriverFrameIdentity
            or type(pack) is not CasePack
            or pack.driver_kind != 'BROWSER'
        ):
            raise CheckEvidenceUnknown('CHECK20_ORIGINAL_BROWSER_DRIVER_REQUIRED')
        self._identity = identity
        self._pack = pack
        self._max_bytes = strict_integer(max_bytes, 'max_bytes', maximum=16 * 1024 * 1024)
        self._seen = 0
        self._sequence = 1
        self._results = []
        self._closed = False
        self._invalid = False
        self._observed = None

    def _validate_frame(self, raw):
        original = self._identity
        row = exact_record(strict_json_object(raw), _FRAME_KEYS)
        if (
            type(row['schema_version']) is not int
            or row['schema_version'] != 1
            or strict_integer(row['verification_id'], 'verification_id') != original.verification_id
            or strict_integer(row['item_id'], 'item_id') != original.item_id
            or row['nonce'] != original.nonce
            or strict_integer(row['seq'], 'seq') != self._sequence
        ):
            raise CheckEvidenceUnknown('CHECK20_BROWSER_FRAME_IDENTITY_DIFFERS')
        at = row['observed_at']
        if (
            type(at) is not str
            or not re.fullmatch(
                r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z', at
            )
            or self._observed is not None
            and at < self._observed
        ):
            raise CheckEvidenceUnknown('CHECK20_BROWSER_FRAME_TIME_DIFFERS')
        datetime.fromisoformat(at)
        self._observed = at
        return row

    def receive(self, raw):
        if self._invalid or self._closed:
            self._invalid = True
            raise CheckEvidenceUnknown('CHECK20_BROWSER_FRAME_AFTER_TERMINAL')
        try:
            data = _complete_bytes(raw, _MAX_FRAME_BYTES)
            self._seen += len(data)
            if self._seen > self._max_bytes:
                raise CheckEvidenceUnknown('CHECK20_ORIGINAL_OUTPUT_LIMIT')
            row = self._validate_frame(data)
            self._consume(row)
            self._sequence += 1
        except (CheckResourceError, TypeError, ValueError) as error:
            self._invalid = True
            raise CheckEvidenceUnknown('CHECK20_BROWSER_FRAME_NOT_AUTHORITATIVE') from error

    def _consume(self, row):
        if self._sequence == 1 or len(self._results) == len(self._pack.cases):
            expected = 'BEGIN' if self._sequence == 1 else 'END'
            if (
                row['type'] != expected
                or row['case_id'] is not None
                or row['assertion_results'] != []
            ):
                raise CheckEvidenceUnknown('CHECK20_BROWSER_BOUNDARY_FRAME_DIFFERS')
            self._closed = expected == 'END'
            return
        case = self._pack.cases[len(self._results)]
        if row['type'] != 'CASE_RESULT' or row['case_id'] != case.case_id:
            raise CheckEvidenceUnknown('CHECK20_BROWSER_CASE_ORDER_DIFFERS')
        rows = validated_assertions(
            row['assertion_results'], {item.assertion_id for item in case.assertions}
        )
        by_id = {item['assertion_id']: item for item in rows}
        facts = []
        redacted = False
        for assertion in case.assertions:
            result = by_id[assertion.assertion_id]
            value = result['actual_value']
            valid_type = {'VISIBLE': bool, 'TEXT': str, 'COUNT': int}.get(assertion.op)
            if (
                valid_type is None
                or type(value) is not valid_type
                or (assertion.op == 'COUNT' and value < 0)
            ):
                raise CheckEvidenceUnknown('CHECK20_BROWSER_ASSERTION_OBSERVATION_DIFFERS')
            actual_expected = assertion.operands[-1]
            matched = value == actual_expected
            if matched != (result['result'] == 'PASSED'):
                raise CheckEvidenceUnknown('CHECK20_BROWSER_ASSERTION_RESULT_DIFFERS')
            if type(value) is str:
                value = _hash_summary(value.encode('utf-8'))
                redacted = True
            facts.append(_result(assertion, matched, value))
        self._results.append(_outcome(case, facts, redacted=redacted))

    def finish(self, *, authenticated_root, original_exit_code):
        if (
            self._invalid
            or not self._closed
            or authenticated_root is not True
            or type(original_exit_code) is not int
            or original_exit_code != 0
            or len(self._results) != len(self._pack.cases)
        ):
            raise CheckEvidenceUnknown('CHECK20_BROWSER_RESULT_NOT_COMPLETE')
        return tuple(self._results)
