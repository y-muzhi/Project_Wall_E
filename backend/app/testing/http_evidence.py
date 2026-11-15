"""Validate original HTTP comparison facts after the service Job was closed."""

from hashlib import sha256

from backend.app.infrastructure.check_case_evidence import (
    CheckEvidenceUnknown,
    validated_assertions,
)
from backend.app.infrastructure.check_runner_bundle import valid_sha256
from backend.app.infrastructure.idempotency import canonical_input


def _summary(actual):
    return type(actual) is str and actual.startswith('sha256:') and valid_sha256(actual[7:])


def _match_summary(actual, expected):
    return _summary(actual) and actual[7:] == sha256(expected).hexdigest()


def check_http_assertions(case, assertions):
    checked = validated_assertions(assertions, {item.assertion_id for item in case.assertions})
    rows = {row['assertion_id']: row for row in checked}
    redacted = False
    for assertion in case.assertions:
        row = rows[assertion.assertion_id]
        actual = row['actual_value']
        _, *expected = assertion.operands
        if assertion.op == 'STATUS':
            valid = type(actual) is int and 200 <= actual <= 599
            matches = valid and actual == expected[0]
        elif assertion.op == 'BODY_BYTES':
            valid = _summary(actual)
            matches = _match_summary(actual, expected[0])
        elif assertion.op == 'HEADER':
            valid = actual is None or _summary(actual)
            matches = _match_summary(actual, expected[1].encode('utf-8'))
        elif assertion.op == 'JSON_POINTER':
            valid = actual is None or type(actual) in (bool, int, float) or _summary(actual)
            if _summary(actual):
                matches = (
                    actual[7:]
                    == sha256(('{"value":' + expected[1] + '}').encode('utf-8')).hexdigest()
                )
            elif actual is None and expected[1] == 'null':
                # A missing pointer and a present JSON null share the public scalar.
                matches = row['result'] == 'PASSED'
            else:
                matches = canonical_input({'value': actual}) == '{"value":' + expected[1] + '}'
        else:
            raise CheckEvidenceUnknown('ORIGINAL_TESTING_HTTP_ASSERTION_KIND_DIFFERS')
        if not valid or (row['result'] == 'PASSED') != matches:
            raise CheckEvidenceUnknown('ORIGINAL_TESTING_HTTP_ASSERTION_DIFFERS')
        redacted |= _summary(actual)
    return checked, redacted


def original_http_outcome(completed, original, case):
    native = completed.result
    evidence = completed.http
    if native.reason_code in ('INPUT_CHANGED', 'OUTPUT_LIMIT'):
        return None, 'FAILED', native.reason_code
    if evidence is None:
        if native.result == 'CANCELLED':
            return None, 'CANCELLED', None
        if native.result == 'UNAVAILABLE':
            return None, 'FAILED', native.reason_code
        return None, 'UNKNOWN', 'EVIDENCE_INCOMPLETE'
    if evidence['status'] != 'OBSERVED':
        if native.result == 'CANCELLED':
            return None, 'CANCELLED', None
        if evidence['status'] == 'UNAVAILABLE':
            return None, 'FAILED', 'ISOLATION_UNAVAILABLE'
        return None, 'UNKNOWN', 'EVIDENCE_INCOMPLETE'
    if (
        native.source_integrity != 'VERIFIED'
        or native.stop_receipt_sha256 is None
        or native.cleanup_ref is None
        or completed.prepared is None
        or completed.created is None
        or evidence['native_receipt'] != completed.created['native']['receipt_sha256']
        or evidence['steps'] != [step.step_id for step in case.steps]
        or any(step.operands[0] != original.fixed['endpoint_ref'] for step in case.steps)
    ):
        raise CheckEvidenceUnknown('ORIGINAL_TESTING_HTTP_OBSERVATION_UNVERIFIED')
    outcome = evidence['outcome']
    if (
        set(outcome) != {'case_id', 'result', 'assertion_results', 'capture_status'}
        or outcome['case_id'] != case.case_id
    ):
        raise CheckEvidenceUnknown('ORIGINAL_TESTING_HTTP_OUTCOME_DIFFERS')
    rows, redacted = check_http_assertions(case, outcome['assertion_results'])
    result = 'FAILED' if any(row['result'] == 'FAILED' for row in rows) else 'PASSED'
    if result != outcome['result'] or outcome['capture_status'] != (
        'REDACTED' if redacted else 'FULL'
    ):
        raise CheckEvidenceUnknown('ORIGINAL_TESTING_HTTP_OUTCOME_DIFFERS')
    return outcome, 'SUCCEEDED', None
