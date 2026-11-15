"""Decode and hold original data-only CHECK20 CasePack bytes."""

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from os import scandir
from time import monotonic

from backend.app.shared.json_canonical import canonical_input
from backend.app.shared.validation import strict_enum, strict_integer, strict_json_object

from .check_case_values import (
    bounded_count,
    browser_key,
    browser_locator,
    byte_literal,
    endpoint_target,
    header_value,
    json_literal,
    json_pointer,
    request_headers,
    request_method,
    response_header,
    text_literal,
)
from .check_runner_bundle import (
    CHECK_PROTOCOL,
    CheckResourceError,
    exact_record,
    reference,
    references,
    valid_sha256,
)
from .windows_config_source import LockedFileSource
from .windows_local_paths import FileIdentity
from .windows_private_package import PrivatePackageGuard

_MANIFEST = 'manifest.json'
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_DRIVERS = ('CLI', 'HTTP', 'BROWSER')


@dataclass(frozen=True)
class CasePackLimits:
    max_check_cases: int
    max_case_steps: int
    max_case_payload_bytes: int
    max_timeout_seconds: int

    def __post_init__(self):
        bounds = (
            ('max_check_cases', 4096),
            ('max_case_steps', 256),
            ('max_case_payload_bytes', 1024 * 1024),
            ('max_timeout_seconds', 3600),
        )
        for name, limit in bounds:
            strict_integer(getattr(self, name), name, minimum=1, maximum=limit)


@dataclass(frozen=True)
class CaseBasis:
    document_id: int
    revision_id: int
    quote: str

    def __post_init__(self):
        strict_integer(self.document_id, 'document_id')
        strict_integer(self.revision_id, 'revision_id')
        text_literal(self.quote)


@dataclass(frozen=True)
class CaseStep:
    step_id: str
    op: str
    operands: tuple = field(repr=False)


@dataclass(frozen=True)
class CaseAssertion:
    assertion_id: str
    op: str
    operands: tuple = field(repr=False)


@dataclass(frozen=True)
class CheckCase:
    case_id: str
    name: str
    basis_refs: tuple[CaseBasis, ...]
    steps: tuple[CaseStep, ...]
    assertions: tuple[CaseAssertion, ...]
    timeout_seconds: int


@dataclass(frozen=True)
class CasePack:
    bundle_id: str
    version: str
    driver_kind: str
    basis_refs: tuple[CaseBasis, ...]
    cases: tuple[CheckCase, ...]


@dataclass(frozen=True)
class RegisteredCasePack:
    case_pack_ref: str
    directory: FileIdentity = field(repr=False)
    manifest_sha256: str
    bundle_id: str
    version: str
    limits: CasePackLimits
    basis_refs: tuple[CaseBasis, ...]
    command_ids: tuple[str, ...] = ()
    endpoint_refs: tuple[str, ...] = ()

    def __post_init__(self):
        if (
            type(self.directory) is not FileIdentity
            or not self.directory.is_directory
            or self.directory.filesystem != 'NTFS'
            or not valid_sha256(self.manifest_sha256)
            or type(self.limits) is not CasePackLimits
        ):
            raise CheckResourceError('ORIGINAL_CASE_PACK_SOURCE_REQUIRED')
        for value in (self.case_pack_ref, self.bundle_id, self.version):
            reference(value)
        if (
            type(self.basis_refs) is not tuple
            or not 1 <= len(self.basis_refs) <= 256
            or any(type(value) is not CaseBasis for value in self.basis_refs)
        ):
            raise CheckResourceError('ORIGINAL_CASE_PACK_SCOPE_INVALID')
        _unique(self.basis_refs)
        for values in (self.command_ids, self.endpoint_refs):
            if type(values) is not tuple:
                raise CheckResourceError('ORIGINAL_CASE_PACK_SCOPE_INVALID')
            references(list(values))

    @property
    def environment_ref(self):
        return 'casepack:sha256:' + self.manifest_sha256


def _op(value, id_key):
    if type(value) is not dict:
        raise CheckResourceError('CASE_PACK_OPERATION_INVALID')
    return reference(value.get(id_key)), reference(value.get('op'))


def _step(value, driver, limit, commands, endpoints):
    id_key = 'step_id'
    identity, op = _op(value, id_key)
    common = (id_key, 'op')
    if driver == 'CLI' and op == 'RUN':
        exact_record(value, (*common, 'command_id', 'stdin'))
        command = reference(value['command_id'])
        if command not in commands:
            raise CheckResourceError('CASE_PACK_COMMAND_NOT_DECLARED')
        operands = (command, byte_literal(value['stdin'], limit))
    elif driver == 'HTTP' and op == 'REQUEST':
        exact_record(value, (*common, 'endpoint_ref', 'path', 'method', 'headers', 'body'))
        operands = (
            *endpoint_target(value, endpoints),
            request_method(value['method']),
            request_headers(value['headers']),
            byte_literal(value['body'], limit),
        )
    elif driver == 'BROWSER':
        operands = _browser_step(value, op, common, endpoints)
    else:
        raise CheckResourceError('CASE_PACK_STEP_UNSUPPORTED')
    return CaseStep(identity, op, operands)


def _browser_step(value, op, common, endpoints):
    if op == 'NAVIGATE':
        exact_record(value, (*common, 'endpoint_ref', 'path'))
        return endpoint_target(value, endpoints)
    if op == 'CLICK':
        exact_record(value, (*common, 'locator'))
        return (browser_locator(value['locator']),)
    if op in ('FILL', 'SELECT', 'PRESS'):
        exact_record(value, (*common, 'locator', 'value'))
        operand = (
            browser_key(value['value'])
            if op == 'PRESS'
            else text_literal(value['value'], empty=op == 'FILL')
        )
        return browser_locator(value['locator']), operand
    raise CheckResourceError('CASE_PACK_STEP_UNSUPPORTED')


def _assertion(value, driver, limit, step_ids):
    id_key = 'assertion_id'
    identity, op = _op(value, id_key)
    common = (id_key, 'op', 'expected')
    if driver == 'CLI':
        exact_record(value, common)
        expected = value['expected']
        if op == 'EXIT_CODE':
            operands = (strict_integer(expected, 'expected', minimum=0, maximum=(1 << 32) - 1),)
        elif op == 'STDOUT_BYTES':
            operands = (byte_literal(expected, limit),)
        else:
            raise CheckResourceError('CASE_PACK_ASSERTION_UNSUPPORTED')
    elif driver == 'HTTP':
        operands = _http_assertion(value, op, common, limit, step_ids)
    else:
        exact_record(value, (*common, 'locator'))
        expected = value['expected']
        if op == 'VISIBLE' and type(expected) is bool:
            normalized = expected
        elif op == 'TEXT':
            normalized = text_literal(expected, empty=True)
        elif op == 'COUNT':
            normalized = bounded_count(expected)
        else:
            raise CheckResourceError('CASE_PACK_ASSERTION_UNSUPPORTED')
        operands = browser_locator(value['locator']), normalized
    return CaseAssertion(identity, op, operands)


def _http_assertion(value, op, common, limit, step_ids):
    common = (*common, 'step_id')
    if op == 'HEADER':
        exact_record(value, (*common, 'header'))
        tail = response_header(value['header']), header_value(value['expected'])
    elif op == 'JSON_POINTER':
        exact_record(value, (*common, 'pointer'))
        expected = json.dumps(
            json_literal(value['expected']),
            sort_keys=True,
            separators=(',', ':'),
            ensure_ascii=False,
            allow_nan=False,
        )
        tail = json_pointer(value['pointer']), expected
    elif op == 'STATUS':
        exact_record(value, common)
        tail = (strict_integer(value['expected'], 'expected', minimum=100, maximum=599),)
    elif op == 'BODY_BYTES':
        exact_record(value, common)
        tail = (byte_literal(value['expected'], limit),)
    else:
        raise CheckResourceError('CASE_PACK_ASSERTION_UNSUPPORTED')
    step_id = reference(value['step_id'])
    if step_id not in step_ids:
        raise CheckResourceError('CASE_PACK_ASSERTION_STEP_UNKNOWN')
    return step_id, *tail


def _bounded_array(value, limit):
    if type(value) is not list or not 1 <= len(value) <= limit:
        raise CheckResourceError('CASE_PACK_ARRAY_SIZE_INVALID')
    return value


def _unique(values):
    values = tuple(values)
    if len(set(values)) != len(values):
        raise CheckResourceError('CASE_PACK_DUPLICATE_ID')
    return frozenset(values)


def _basis(values):
    rows = _bounded_array(values, 256)
    result = tuple(CaseBasis(**exact_record(row, CaseBasis.__dataclass_fields__)) for row in rows)
    _unique(result)
    return result


def _case(value, driver, basis, limits, commands, endpoints):
    exact_record(value, CheckCase.__dataclass_fields__)
    case_basis = _basis(value['basis_refs'])
    if not set(case_basis).issubset(basis):
        raise CheckResourceError('CASE_PACK_CASE_BASIS_DIFFERS')
    payload = limits.max_case_payload_bytes
    if len(canonical_input(value).encode('utf-8')) > payload:
        raise CheckResourceError('CASE_PACK_CASE_PAYLOAD_LIMIT')
    steps = tuple(
        _step(step, driver, payload, commands, endpoints)
        for step in _bounded_array(value['steps'], limits.max_case_steps)
    )
    step_ids = _unique(step.step_id for step in steps)
    assertions = tuple(
        _assertion(assertion, driver, payload, step_ids)
        for assertion in _bounded_array(value['assertions'], limits.max_case_steps)
    )
    _unique(assertion.assertion_id for assertion in assertions)
    _complete_operations(driver, steps, step_ids, assertions)
    return CheckCase(
        reference(value['case_id']),
        text_literal(value['name'], limit=256),
        case_basis,
        steps,
        assertions,
        strict_integer(
            value['timeout_seconds'],
            'timeout_seconds',
            minimum=1,
            maximum=limits.max_timeout_seconds,
        ),
    )


def _complete_operations(driver, steps, step_ids, assertions):
    if not steps or not assertions:
        raise CheckResourceError('CASE_PACK_ARRAY_SIZE_INVALID')
    if driver == 'CLI' and len(steps) != 1:
        raise CheckResourceError('CASE_PACK_CLI_RUN_COUNT_INVALID')
    if driver == 'BROWSER' and steps[0].op != 'NAVIGATE':
        raise CheckResourceError('CASE_PACK_BROWSER_TARGET_REQUIRED')
    if driver == 'HTTP' and {assertion.operands[0] for assertion in assertions} != step_ids:
        raise CheckResourceError('CASE_PACK_UNCHECKED_HTTP_STEP')


def validate_draft_operations(value, driver, limits, *, complete=False):
    """Use the CHECK20 data grammar without claiming draft resources are admitted."""
    steps = value['steps']
    assertions = value['assertions']
    if any(
        type(rows) is not list or len(rows) > limits.max_case_steps for rows in (steps, assertions)
    ):
        raise CheckResourceError('CASE_PACK_ARRAY_SIZE_INVALID')
    if len(canonical_input(value).encode('utf-8')) > limits.max_case_payload_bytes:
        raise CheckResourceError('CASE_PACK_CASE_PAYLOAD_LIMIT')
    commands = tuple(step.get('command_id') for step in steps if type(step) is dict)
    endpoints = tuple(step.get('endpoint_ref') for step in steps if type(step) is dict)
    decoded = [
        _step(step, driver, limits.max_case_payload_bytes, commands, endpoints) for step in steps
    ]
    step_ids = _unique(step.step_id for step in decoded)
    checks = [
        _assertion(assertion, driver, limits.max_case_payload_bytes, step_ids)
        for assertion in assertions
    ]
    _unique(assertion.assertion_id for assertion in checks)
    if complete:
        _complete_operations(driver, decoded, step_ids, checks)


def decode_case_pack(
    raw, *, limits, basis_refs, command_ids=(), endpoint_refs=(), checkpoint=lambda: None
):
    if (
        type(limits) is not CasePackLimits
        or type(raw) is not bytes
        or not 0 < len(raw) <= _MAX_MANIFEST_BYTES
    ):
        raise CheckResourceError('CASE_PACK_MANIFEST_SIZE_INVALID')
    try:
        value = exact_record(
            strict_json_object(raw),
            ('schema_version', 'protocol_version', *CasePack.__dataclass_fields__),
        )
        if (
            type(value['schema_version']) is not int
            or value['schema_version'] != 1
            or value['protocol_version'] != CHECK_PROTOCOL
        ):
            raise CheckResourceError('CASE_PACK_MANIFEST_PROTOCOL_INVALID')
        basis = _basis(value['basis_refs'])
        if not set(basis).issubset(basis_refs):
            raise CheckResourceError('CASE_PACK_BASIS_DIFFERS')
        driver = strict_enum(value['driver_kind'], 'driver_kind', _DRIVERS)
        cases = []
        for row in _bounded_array(value['cases'], limits.max_check_cases):
            checkpoint()
            cases.append(_case(row, driver, basis, limits, command_ids, endpoint_refs))
        _unique(case.case_id for case in cases)
        return CasePack(
            reference(value['bundle_id']), reference(value['version']), driver, basis, tuple(cases)
        )
    except (ValueError, RecursionError) as error:
        raise CheckResourceError('CASE_PACK_MANIFEST_DATA_INVALID') from error


def _manifest_member(package):
    with scandir(package.path) as entries:
        first = next(entries, None)
        if first is None or first.name != _MANIFEST or next(entries, None) is not None:
            raise CheckResourceError('ORIGINAL_CASE_PACK_INVENTORY_DIFFERS')
    return package.verify_member(_MANIFEST, directory=False)


@contextmanager
def hold_case_pack(registration, *, deadline, cancelled):
    if type(registration) is not RegisteredCasePack or not callable(cancelled):
        raise CheckResourceError('ORIGINAL_CASE_PACK_SOURCE_REQUIRED')

    def checkpoint():
        if cancelled() or monotonic() >= deadline:
            raise CheckResourceError('CASE_PACK_INSPECTION_INTERRUPTED')

    checkpoint()
    with PrivatePackageGuard(registration.directory.canonical_path) as package:
        if package.verify() != registration.directory:
            raise CheckResourceError('ORIGINAL_CASE_PACK_DIRECTORY_DIFFERS')
        identity = _manifest_member(package)
        with LockedFileSource(
            package.path / _MANIFEST,
            max_file_bytes=_MAX_MANIFEST_BYTES,
            expected_file=identity,
            checkpoint=checkpoint,
        ) as source:
            original = source.snapshot
            if original.sha256 != registration.manifest_sha256:
                raise CheckResourceError('ORIGINAL_CASE_PACK_MANIFEST_DIFFERS')
            pack = decode_case_pack(
                original.raw,
                limits=registration.limits,
                basis_refs=registration.basis_refs,
                command_ids=registration.command_ids,
                endpoint_refs=registration.endpoint_refs,
                checkpoint=checkpoint,
            )
            if (pack.bundle_id, pack.version) != (registration.bundle_id, registration.version):
                raise CheckResourceError('ORIGINAL_CASE_PACK_IDENTITY_DIFFERS')
            yield pack
            if (
                package.verify() != registration.directory
                or _manifest_member(package) != identity
                or source.verify() != original
            ):
                raise CheckResourceError('ORIGINAL_CASE_PACK_CHANGED')
