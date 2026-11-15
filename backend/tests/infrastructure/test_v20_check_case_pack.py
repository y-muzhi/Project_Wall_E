"""Protected CasePack contracts and Windows byte identity."""

import json
import sqlite3
from contextlib import closing, nullcontext
from dataclasses import asdict, replace
from hashlib import sha256
from time import monotonic
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.code_tasks.verification_case_reads import _case_view, verification_case_router
from backend.app.infrastructure.check_case_pack import (
    CaseBasis,
    CasePackLimits,
    RegisteredCasePack,
    decode_case_pack,
    hold_case_pack,
)
from backend.app.infrastructure.check_runner_bundle import CHECK_PROTOCOL, CheckResourceError
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)

from backend.app.shared.http_boundary import HttpRuntime

BASIS = CaseBasis(1, 2, '候选程序应输出原输入。')
LIMITS = CasePackLimits(2, 4, 4096, 30)
COMMAND = 'fixed:echo'
ENDPOINT = 'app'
LOCATOR = {'kind': 'ROLE', 'value': 'button', 'name': '发送'}


def pack(driver='CLI', **case_changes):
    if driver == 'CLI':
        steps = [{'step_id': 'run', 'op': 'RUN', 'command_id': COMMAND, 'stdin': 'AP8='}]
        assertions = [
            {'assertion_id': 'exit', 'op': 'EXIT_CODE', 'expected': 0},
            {'assertion_id': 'output', 'op': 'STDOUT_BYTES', 'expected': 'AP8='},
        ]
    elif driver == 'HTTP':
        steps = [
            {
                'step_id': 'request',
                'op': 'REQUEST',
                'endpoint_ref': ENDPOINT,
                'path': '/v1/check?probe=1',
                'method': 'POST',
                'headers': {'content-type': 'application/json'},
                'body': 'e30=',
            }
        ]
        assertions = [
            {
                'assertion_id': 'json',
                'op': 'JSON_POINTER',
                'step_id': 'request',
                'pointer': '/nested/~0~1',
                'expected': {'value': [True, 1, '1']},
            }
        ]
    else:
        steps = [
            {'step_id': 'navigate', 'op': 'NAVIGATE', 'endpoint_ref': ENDPOINT, 'path': '/app'},
            {'step_id': 'click', 'op': 'CLICK', 'locator': LOCATOR},
        ]
        assertions = [
            {'assertion_id': 'visible', 'op': 'VISIBLE', 'locator': LOCATOR, 'expected': True}
        ]
    return {
        'schema_version': 1,
        'protocol_version': CHECK_PROTOCOL,
        'bundle_id': 'fixture-pack',
        'version': '1.0.0',
        'driver_kind': driver,
        'basis_refs': [asdict(BASIS)],
        'cases': [
            {
                'case_id': 'check',
                'name': '原始行为用例',
                'basis_refs': [asdict(BASIS)],
                'steps': steps,
                'assertions': assertions,
                'timeout_seconds': 5,
                **case_changes,
            }
        ],
    }


def raw(document):
    return canonical_input(document).encode('utf-8')


def decode(document, *, limits=LIMITS):
    return decode_case_pack(
        raw(document),
        limits=limits,
        basis_refs=(BASIS,),
        command_ids=(COMMAND,),
        endpoint_refs=(ENDPOINT,),
    )


@pytest.mark.parametrize('driver', ['CLI', 'HTTP', 'BROWSER'])
def test_original_case_pack_preserves_fixed_driver_operations_and_bounded_literals(driver):
    result = decode(pack(driver))
    case = result.cases[0]
    assert result.driver_kind == driver and case.basis_refs == (BASIS,)
    assert case.name == '原始行为用例'
    if driver == 'CLI':
        assert case.steps[0].operands == (COMMAND, b'\0\xff')
    elif driver == 'HTTP':
        assert case.assertions[0].operands == (
            'request',
            ('nested', '~/'),
            '{"value":[true,1,"1"]}',
        )
    else:
        assert case.assertions[0].operands == (('ROLE', 'button', '发送'), True)


@pytest.mark.parametrize(
    'fault',
    [
        'extra',
        'duplicate-case',
        'duplicate-step',
        'duplicate-assertion',
        'no-assertions',
        'basis',
        'long-timeout',
        'payload',
        'too-many-steps',
        'noncanonical-bytes',
        'shell',
        'external-url',
        'encoded-slash',
        'parent',
        'auth-header',
        'bad-pointer',
        'unknown-step',
        'browser-eval',
        'selector',
        'skip',
    ],
)
def test_case_pack_fails_closed_on_scope_ambiguity_or_arbitrary_program(fault):
    driver = (
        'HTTP'
        if fault
        in ('external-url', 'encoded-slash', 'parent', 'auth-header', 'bad-pointer', 'unknown-step')
        else 'BROWSER'
        if fault in ('browser-eval', 'selector')
        else 'CLI'
    )
    document = pack(driver)
    case = document['cases'][0]
    step = case['steps'][0]
    assertion = case['assertions'][0]
    limits = LIMITS
    match fault:
        case 'extra':
            document['ready'] = True
        case 'duplicate-case':
            document['cases'].append(case)
        case 'duplicate-step':
            case['steps'].append(step)
        case 'duplicate-assertion':
            case['assertions'].append(assertion)
        case 'no-assertions':
            case['assertions'] = []
        case 'basis':
            case['basis_refs'] = [{**asdict(BASIS), 'quote': '不同的原文。'}]
        case 'long-timeout':
            case['timeout_seconds'] = 31
        case 'payload':
            limits = replace(limits, max_case_payload_bytes=128)
        case 'too-many-steps':
            limits = replace(limits, max_case_steps=1)
        case 'noncanonical-bytes':
            step['stdin'] = 'AP9='
        case 'shell':
            step['command_id'] = 'powershell'
        case 'external-url':
            step['path'] = 'https://other.invalid/'
        case 'encoded-slash':
            step['path'] = '/%2fother.invalid'
        case 'parent':
            step['path'] = '/a/%2E%2e/b'
        case 'auth-header':
            step['headers']['authorization'] = 'private'
        case 'bad-pointer':
            assertion['pointer'] = '/bad~2'
        case 'unknown-step':
            assertion['step_id'] = 'other-request'
        case 'browser-eval':
            case['steps'][1]['op'] = 'EVALUATE'
        case 'selector':
            case['steps'][1]['locator'] = {'kind': 'CSS', 'value': 'body'}
        case 'skip':
            case['skip'] = True
    with pytest.raises(CheckResourceError):
        decode(document, limits=limits)


def test_case_pack_is_read_locked_and_bound_to_its_registered_bytes(tmp_path):
    directory = create_private_package(tmp_path / 'cases')
    path = directory / 'manifest.json'
    content = raw(pack())
    path.write_bytes(content)
    with PrivatePackageGuard(directory) as package:
        registered = RegisteredCasePack(
            'fixture:cases',
            package.verify(),
            sha256(content).hexdigest(),
            'fixture-pack',
            '1.0.0',
            LIMITS,
            (BASIS,),
            command_ids=(COMMAND,),
        )
    with hold_case_pack(registered, deadline=monotonic() + 10, cancelled=lambda: False) as held:
        assert held == decode(pack())
        with pytest.raises(OSError), path.open('ab'):
            raise AssertionError('The original manifest must remain write locked')
    path.write_bytes(raw(pack(name='同版本的新名称')))
    with (
        pytest.raises(CheckResourceError, match='MANIFEST_DIFFERS'),
        hold_case_pack(registered, deadline=monotonic() + 10, cancelled=lambda: False),
    ):
        raise AssertionError('Changed bytes matched the original case pack')


def test_case_view_requires_original_assertions_and_never_projects_actual_values():
    case = decode(pack()).cases[0]
    outcomes = [
        {'assertion_id': 'exit', 'result': 'PASSED', 'actual_value': 0},
        {'assertion_id': 'output', 'result': 'FAILED', 'actual_value': 'private-value'},
    ]
    row = {
        'case_id': case.case_id,
        'result': 'FAILED',
        'assertion_results': json.dumps(outcomes),
        'capture_status': 'REDACTED',
        'observed_at': '2026-11-10T03:00:00.000Z',
    }
    data = _case_view(row, case)
    assert data['expected_assertion_count'] == 2
    assert data['passed_assertion_count'] == data['failed_assertion_count'] == 1
    assert 'private-value' not in canonical_input(data)
    incomplete = {
        **row,
        'assertion_results': json.dumps(outcomes[1:]),
        'capture_status': 'INCOMPLETE',
    }
    assert _case_view(incomplete, case)['passed_assertion_count'] == 0
    for changed in (
        {'result': 'PASSED'},
        {'assertion_results': json.dumps([outcomes[1], outcomes[1]])},
        {'assertion_results': json.dumps([{**outcomes[0], 'assertion_id': 'foreign'}])},
    ):
        with pytest.raises(StorageUnavailable):
            _case_view({**row, **changed}, case)


@pytest.mark.parametrize('value,encoded', [(None, 'null'), (True, 'true'), (1, '1'), ('1', '"1"')])
def test_http_assertions_keep_json_scalar_type(value, encoded):
    document = pack('HTTP')
    document['cases'][0]['assertions'][0]['expected'] = value
    assert decode(document).cases[0].assertions[0].operands[-1] == encoded


def test_case_http_pages_only_original_saved_results_and_holds_exact_pack(tmp_path):
    document = pack()
    document['cases'].append({**document['cases'][0], 'case_id': 'pending', 'name': '尚无记录'})
    directory = create_private_package(tmp_path / 'original-cases')
    manifest = directory / 'manifest.json'
    contents = raw(document)
    manifest.write_bytes(contents)
    with PrivatePackageGuard(directory) as package:
        binding = RegisteredCasePack(
            'fixture:cases',
            package.verify(),
            sha256(contents).hexdigest(),
            'fixture-pack',
            '1.0.0',
            LIMITS,
            (BASIS,),
            command_ids=(COMMAND,),
        )
    with closing(sqlite3.connect(':memory:', check_same_thread=False)) as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            CREATE TABLE code_verification_items(id INTEGER,verification_id INTEGER,check_id TEXT,check_kind TEXT,evidence_kind TEXT,expected_case_count INTEGER,executed_case_count INTEGER);
            CREATE TABLE code_verifications(id INTEGER,task_id INTEGER,owner_kind TEXT,check_set_version_id INTEGER,environment_record_id INTEGER);
            CREATE TABLE code_check_set_versions(id INTEGER,owner_module TEXT,items TEXT);
            CREATE TABLE code_environment_records(id INTEGER,task_id INTEGER,check_resource_refs TEXT);
            CREATE TABLE code_verification_case_results(item_id INTEGER,case_id TEXT,result TEXT,assertion_results TEXT,capture_status TEXT,observed_at TEXT);
            INSERT INTO code_verifications VALUES(17,11,'CODING',20,21);
            INSERT INTO code_verification_items VALUES(18,17,'controlled','CONTROLLED_ASSERTION','CONTROLLED_CASES',2,1);
            INSERT INTO code_verification_items VALUES(19,17,'project','PROJECT_COMMAND','PROCESS_EXIT',NULL,NULL);
        """)
        checks = [
            {
                'check_id': 'controlled',
                'check_kind': 'CONTROLLED_ASSERTION',
                'case_pack_ref': 'fixture:cases',
            }
        ]
        connection.execute(
            "INSERT INTO code_check_set_versions VALUES(20,'CODING',?)", (json.dumps(checks),)
        )
        connection.execute(
            'INSERT INTO code_environment_records VALUES(21,11,?)',
            (json.dumps([binding.environment_ref]),),
        )
        evidence = [
            {'assertion_id': 'exit', 'result': 'PASSED', 'actual_value': 0},
            {'assertion_id': 'output', 'result': 'FAILED', 'actual_value': 'private-output'},
        ]
        connection.execute(
            "INSERT INTO code_verification_case_results VALUES(18,'check','FAILED',?,'REDACTED','2026-11-10T03:00:00.000Z')",
            (json.dumps(evidence),),
        )
        app = FastAPI()
        app.include_router(verification_case_router)
        app.state.walle_runtime = HttpRuntime(
            SimpleNamespace(schema_release=object(), transaction=lambda: nullcontext(connection)),
            None,
            None,
        )
        app.state.walle_repository_registration = SimpleNamespace(case_pack_admissions=(binding,))
        path = '/api/v1/code-tasks/11/verifications/17/items/18/cases'
        with TestClient(app) as client:
            reply = client.get(path)
            assert reply.status_code == 200, reply.text
            payload = reply.json()
            assert payload['meta']['pagination']['total'] == 1
            assert [item['case_id'] for item in payload['data']['items']] == ['check']
            assert 'private-output' not in reply.text and '尚无记录' not in reply.text
            reply = client.get(path, params={'page': 2})
            assert reply.status_code == 200 and reply.json()['data']['items'] == []
            assert client.get(path.replace('/11/', '/12/')).status_code == 404
            assert client.get(path.replace('/17/', '/16/')).status_code == 404
            assert client.get(path + '?page=1&page=2').status_code == 422
            assert client.get(path.replace('/18/', '/19/')).json()['data']['items'] == []
            manifest.write_bytes(raw(pack(name='同引用的新版本')))
            assert client.get(path).status_code == 503
