"""Deterministic CHECK20 observations, bounded results, and driver frame integrity."""

from dataclasses import replace

import pytest

from backend.app.infrastructure.check_case_evidence import (
    BrowserCaseFrames,
    CheckEvidenceUnknown,
    DriverFrameIdentity,
    HttpStepObservation,
    evaluate_cli_case,
    evaluate_http_case,
    validated_assertions,
)
from backend.app.infrastructure.check_runner_bundle import CheckResourceError
from backend.tests.infrastructure.test_v20_check_case_pack import LOCATOR, decode, pack, raw

AT = '2026-11-10T04:00:00.000Z'


def test_original_cli_bytes_and_exit_are_independent_and_redacted():
    case = decode(pack()).cases[0]
    original = evaluate_cli_case(
        case, exit_code=0, stdout=b'\0\xff', output_limit=32, complete=True
    )
    assert original['result'] == 'PASSED' and original['capture_status'] == 'REDACTED'
    assert original['assertion_results'][0] == {
        'assertion_id': 'exit',
        'result': 'PASSED',
        'actual_value': 0,
    }
    assert original['assertion_results'][1]['actual_value'].startswith('sha256:')
    changed = evaluate_cli_case(case, exit_code=0, stdout=b'\0', output_limit=32, complete=True)
    assert [row['result'] for row in changed['assertion_results']] == ['PASSED', 'FAILED']
    for evidence in (
        {'complete': False, 'output_limit': 32},
        {'complete': True, 'output_limit': 1},
    ):
        with pytest.raises(CheckEvidenceUnknown):
            evaluate_cli_case(case, exit_code=0, stdout=b'\0\xff', **evidence)


def test_http_observations_are_original_complete_and_data_only():
    source = pack('HTTP')
    source['cases'][0]['assertions'] += [
        {'assertion_id': 'status', 'op': 'STATUS', 'step_id': 'request', 'expected': 201},
        {
            'assertion_id': 'header',
            'op': 'HEADER',
            'step_id': 'request',
            'header': 'content-type',
            'expected': 'application/json',
        },
        {
            'assertion_id': 'null',
            'op': 'JSON_POINTER',
            'step_id': 'request',
            'pointer': '/present',
            'expected': None,
        },
    ]
    case = decode(source).cases[0]
    body = b'{"nested":{"~/":{"value":[true,1,"1"]}},"present":null}'
    observation = HttpStepObservation('request', 201, (('content-type', 'application/json'),), body)
    success = evaluate_http_case(case, (observation,), output_limit=512)
    assert success['result'] == 'PASSED' and success['capture_status'] == 'REDACTED'
    assert 'application/json' not in str(success)
    wrong = evaluate_http_case(
        case,
        (replace(observation, body=b'{"nested":{"~/":{"value":[1,1,"1"]}}}'),),
        output_limit=512,
    )
    assert [item['result'] for item in wrong['assertion_results']] == [
        'FAILED',
        'PASSED',
        'PASSED',
        'FAILED',
    ]
    invalid = [
        replace(observation, complete=False),
        replace(observation, step_id='different'),
        replace(observation, headers=observation.headers + observation.headers),
    ]
    for result in invalid:
        with pytest.raises(CheckEvidenceUnknown):
            evaluate_http_case(case, (result,), output_limit=512)
    with pytest.raises(CheckEvidenceUnknown):
        evaluate_http_case(case, (observation,), output_limit=len(body))


def frame(identity, seq, kind, case=None, assertions=(), **changes):
    return raw(
        {
            'schema_version': 1,
            'verification_id': identity.verification_id,
            'item_id': identity.item_id,
            'nonce': identity.nonce,
            'seq': seq,
            'type': kind,
            'case_id': case,
            'assertion_results': list(assertions),
            'observed_at': AT,
            **changes,
        }
    )


def test_browser_requires_original_root_complete_end_and_derives_predicate():
    source = pack('BROWSER')
    source['cases'][0]['assertions'].append(
        {'assertion_id': 'text', 'op': 'TEXT', 'locator': LOCATOR, 'expected': '计划文案'}
    )
    browser = decode(source)
    identity = DriverFrameIdentity(1, 2, 'a' * 32)
    reader = BrowserCaseFrames(identity, browser, max_bytes=32768)
    reader.receive(frame(identity, 1, 'BEGIN'))
    reader.receive(
        frame(
            identity,
            2,
            'CASE_RESULT',
            'check',
            (
                {'assertion_id': 'visible', 'result': 'PASSED', 'actual_value': True},
                {'assertion_id': 'text', 'result': 'FAILED', 'actual_value': '隔离保留数据'},
            ),
        )
    )
    with pytest.raises(CheckEvidenceUnknown):
        reader.finish(authenticated_root=True, original_exit_code=0)
    reader.receive(frame(identity, 3, 'END'))
    with pytest.raises(CheckEvidenceUnknown):
        reader.finish(authenticated_root=False, original_exit_code=0)
    with pytest.raises(CheckEvidenceUnknown):
        reader.finish(authenticated_root=True, original_exit_code=1)
    (result,) = reader.finish(authenticated_root=True, original_exit_code=0)
    assert result['result'] == 'FAILED' and result['capture_status'] == 'REDACTED'
    assert '隔离保留数据' not in str(result)
    with pytest.raises(CheckEvidenceUnknown):
        reader.receive(frame(identity, 4, 'END'))
    with pytest.raises(CheckEvidenceUnknown):
        reader.finish(authenticated_root=True, original_exit_code=0)


@pytest.mark.parametrize(
    'fault',
    [
        'scope',
        'nonce',
        'duplicate',
        'missing',
        'wrong-status',
        'wrong-type',
        'wrong-order',
        'old-time',
        'early-end',
    ],
)
def test_browser_latches_unknown_on_first_conflicting_frame(fault):
    browser = decode(pack('BROWSER'))
    identity = DriverFrameIdentity(1, 2, 'a' * 32)
    reader = BrowserCaseFrames(identity, browser, max_bytes=32768)
    reader.receive(frame(identity, 1, 'BEGIN'))
    asserted = {'assertion_id': 'visible', 'result': 'PASSED', 'actual_value': True}
    changes = {}
    assertions = (asserted,)
    sequence, kind, case = 2, 'CASE_RESULT', 'check'
    if fault == 'scope':
        changes['verification_id'] = 2
    if fault == 'nonce':
        changes['nonce'] = 'b' * 32
    if fault == 'duplicate':
        assertions = (asserted, asserted)
    if fault == 'missing':
        assertions = ()
    if fault == 'wrong-status':
        assertions = ({**asserted, 'result': 'FAILED'},)
    if fault == 'wrong-type':
        assertions = ({**asserted, 'actual_value': 1},)
    if fault == 'wrong-order':
        sequence = 3
    if fault == 'old-time':
        changes['observed_at'] = '2026-11-09T04:00:00.000Z'
    if fault == 'early-end':
        kind, case, assertions = 'END', None, ()
    with pytest.raises(CheckEvidenceUnknown):
        reader.receive(frame(identity, sequence, kind, case, assertions, **changes))
    with pytest.raises(CheckEvidenceUnknown):
        reader.receive(frame(identity, 2, 'CASE_RESULT', 'check', (asserted,)))
    with pytest.raises(CheckEvidenceUnknown):
        reader.finish(authenticated_root=True, original_exit_code=0)


def test_assertion_facts_require_exact_bounded_public_scalars():
    good = {'assertion_id': 'known', 'result': 'FAILED', 'actual_value': None}
    assert validated_assertions([good], {'known'}) == (good,)
    for change in (
        {'actual_value': {}},
        {'actual_value': 'a' * 4097},
        {'actual_value': float('nan')},
        {'actual_value': 2**53},
        {'actual_value': '\0'},
        {'raw_stdout': 'secret'},
        {'assertion_id': 'wrong'},
    ):
        with pytest.raises(CheckResourceError):
            validated_assertions([{**good, **change}], {'known'})
