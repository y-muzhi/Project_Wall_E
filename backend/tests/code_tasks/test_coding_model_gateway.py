"""Actual Coding ledger and fixed supplier I/O through a mock transport."""

import hashlib
import json

import httpx
import pytest

from backend.app.code_tasks import task_start_session
from backend.app.code_tasks.coding_model_admission import (
    CodingModelAdmission,
    effective_coding_binding,
)
from backend.app.code_tasks.coding_model_gateway import CodingModelDeployment, CodingModelGateway
from backend.app.code_tasks.coding_model_ledger import (
    mark_sending,
    prepare_audit_request,
    recover_interrupted_calls,
    reserve_call,
)
from backend.app.code_tasks.coding_model_listener import CodingGatewayError
from backend.app.code_tasks.coding_model_request import (
    CodingModelProtocolError,
    parse_request,
    prepare_request,
)
from backend.app.code_tasks.task_model_ingress import (
    ModelIngressProof,
    ModelWindow,
    read_original_open_window,
)
from backend.app.code_tasks.usage import UsageContract
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.model_profile import DEFAULT_PROFILE, ENDPOINT, ModelProfile
from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_json_object
from backend.tests.code_tasks import test_task_stop
from backend.tests.code_tasks.test_execution_profile_versions import fixture_snapshot, resources
from backend.tests.code_tasks.test_task_start import isolated_readiness, stop
from backend.tests.code_tasks.test_task_start_instance import original_instance
from backend.tests.code_tasks.test_task_start_session import NativeDriver, ready
from backend.tests.infrastructure.test_v20_command_http import package, service

_ACCOUNT = 'test-only-account'
_PRICE_TIME = '2026-11-01T00:00:00.000Z'
_PROVIDER = 'test-only-provider-credential'
_INSTANCE = 'e' * 64
_NATIVE = b'{"model":"walle-code","messages":[{"role":"user","content":"fixture prompt"}]}'


@pytest.fixture(autouse=True)
def fixed_price(monkeypatch):
    def seed(database):
        with database.transaction(write=True) as connection:
            connection.execute(
                """INSERT INTO model_price_versions VALUES(1,'deepseek-v2','test-only-snapshot',
                'ARK_CN_BEIJING',?,'default',?,NULL,'CNY','1.000000','2.000000',?,?,
                'TOTAL_HALF_UP_6DP','test-only-source',?)""",
                (
                    _ACCOUNT,
                    _PRICE_TIME,
                    '[{"dimension":"cached_tokens","price_per_million":"0.200000"}]',
                    canonical_input(
                        {
                            'kind': 'FLAT',
                            'pricing_clock': 'COMPLETED_AT',
                            'timezone': 'Asia/Shanghai',
                        }
                    ),
                    _PRICE_TIME,
                ),
            )

    monkeypatch.setattr(test_task_stop, 'seed_price', seed)


@pytest.fixture
def opened(ready):
    db, runtime, client, parent, task_id, _, receipt = ready
    driver = NativeDriver()
    options = {'cancelled': lambda: False, 'driver': driver}
    assert task_start_session.advance_start_session(runtime, parent, **options)
    assert task_start_session.advance_start_session(runtime, parent, **options)
    scope = driver.calls[-1][1]
    window = ModelWindow(
        task_id,
        scope.instance_id,
        scope.control_generation,
        scope.session_id,
        'ses_original',
        receipt['operation_id'],
        'msg_original',
    )
    proof = ModelIngressProof(window, 'a' * 64, 'b' * 64)
    with db.transaction() as connection:
        price = connection.execute('SELECT * FROM model_price_versions WHERE id=1').fetchone()
        digest = hashlib.sha256(_bytes(dict(price))).hexdigest()
    admission = CodingModelAdmission(
        'test-only-admission',
        'test-only-snapshot',
        _ACCOUNT,
        digest,
        ModelProfile(_PROVIDER, DEFAULT_PROFILE),
        UsageContract(
            'fixture-sse',
            'USAGE_TRAILER',
            ('input_tokens', 'output_tokens', 'cached_tokens'),
            ('cached_tokens',),
        ),
        30,
        1000,
        2000,
        100,
    )
    snapshot = fixture_snapshot()
    for kind in ('MODEL', 'CAPABILITY', 'PRICE'):
        snapshot[kind][0]['ready'] = True
    with resources(snapshot):
        yield db, runtime, client, proof, driver.credential, admission


class Frames(httpx.SyncByteStream):
    def __init__(self, frames):
        self.frames = frames

    def __iter__(self):
        for raw in self.frames:
            yield raw[:3]
            yield raw[3:]


def _chunk(model, choices, usage=None):
    value = {
        'id': 'fixture-completion',
        'model': model,
        'object': 'chat.completion.chunk',
        'choices': choices,
    }
    if usage is not None:
        value['usage'] = usage
    return b'data: ' + _bytes(value) + b'\n'


def _reply(model, scenario):
    parts = [
        _chunk(
            model,
            [
                {
                    'index': 0,
                    'delta': {
                        'role': 'assistant',
                        'reasoning_content': 'private reasoning',
                        'tool_calls': [
                            {
                                'index': 0,
                                'id': 'fixture-tool',
                                'type': 'function',
                                'function': {'name': 'lookup', 'arguments': '{"value":'},
                            }
                        ],
                    },
                    'finish_reason': None,
                }
            ],
            {'prompt_tokens': 100, 'completion_tokens': 3},
        ),
        _chunk(
            model,
            [
                {
                    'index': 0,
                    'delta': {'tool_calls': [{'index': 0, 'function': {'arguments': ' 1}'}}]},
                    'finish_reason': 'tool_calls',
                }
            ],
        ),
    ]
    if scenario != 'missing':
        parts.append(
            _chunk(
                model,
                [],
                {
                    'prompt_tokens': 90 if scenario == 'regressed' else 110,
                    'completion_tokens': 12,
                    'prompt_tokens_details': {'cached_tokens': 20},
                },
            )
        )
    if scenario != 'truncated':
        parts.append(b'data: [DONE]\n\n')
    return httpx.Response(
        200,
        headers={'Content-Type': 'text/event-stream', 'X-Request-Id': 'opaque: 0012'},
        stream=Frames(parts),
    )


def _build(runtime, admission, handler):
    return CodingModelGateway(
        runtime,
        CodingModelDeployment((admission,)),
        transport_factory=lambda: httpx.MockTransport(handler),
    )


def _invoke(gateway, reference, proof, stream, verify=None, *, raw=_NATIVE):
    gateway(
        reference,
        proof,
        raw,
        (lambda: proof) if verify is None else verify,
        stream,
        lambda: False,
        instance_secret=_INSTANCE,
    )


@pytest.mark.parametrize('scenario', ['complete', 'missing', 'regressed', 'truncated'])
def test_gateway_persists_frames_before_forward_and_settles_only_final_usage(opened, scenario):
    db, runtime, client, proof, reference, admission = opened
    sent, relayed = [], []

    def handler(request):
        assert str(request.url) == ENDPOINT and request.method == 'POST'
        assert request.headers['Authorization'] == 'Bearer ' + _PROVIDER
        assert 'x-opencode-session-id' not in request.headers
        body = json.loads(request.content)
        assert body['messages'] == json.loads(_NATIVE)['messages'] and body['stream'] is True
        assert body['model'] == admission.model.model_name and body['max_tokens'] == 100
        sent.append(body)
        with db.transaction() as connection:
            state = connection.execute('SELECT transport_status FROM llm_uses').fetchone()[0]
            reserve = connection.execute(
                'SELECT status,reserved_cny FROM code_task_reservations'
            ).fetchone()
            assert state == 'SENDING' and tuple(reserve) == ('RESERVED', '0.001200')
        with pytest.raises(CodingGatewayError, match='hold'):
            _invoke(gateway, reference, proof, relayed.append)
        return _reply(admission.model.model_name, scenario)

    def stream(raw):
        relayed.append(raw)
        with db.transaction() as connection:
            frames = connection.execute(
                'SELECT count(*) FROM code_model_response_frames'
            ).fetchone()[0]
            assert frames == len(relayed)

    gateway = _build(runtime, admission, handler)
    if scenario in ('complete', 'missing'):
        _invoke(gateway, reference, proof, stream)
        assert relayed[-1] == b'data: [DONE]\n\n'
    else:
        with pytest.raises(CodingGatewayError, match='hold'):
            _invoke(gateway, reference, proof, stream)
        assert b'[DONE]' not in b''.join(relayed)
    assert len(sent) == 1
    with db.transaction() as connection:
        call = connection.execute('SELECT * FROM llm_uses').fetchone()
        reserve = connection.execute('SELECT * FROM code_task_reservations').fetchone()
        window = strict_json_object(
            connection.execute('SELECT model_window FROM code_sessions').fetchone()[0]
        )
        frames = connection.execute(
            'SELECT frame_json FROM code_model_response_frames ORDER BY seq'
        ).fetchall()
        assert 'private reasoning' not in str([row[0] for row in frames])
        assert call['provider_request_id'] == 'opaque: 0012'
        assert call['source_evidence_ref'] == proof.source_evidence_ref
        assert _PROVIDER not in call['request_snapshot_json']
        summary = strict_json_object(call['raw_response_json'])
        assert summary['frame_count'] == len(frames)
        if scenario == 'complete':
            assert call['usage_status'] == 'FINAL' and reserve['status'] == 'SETTLED'
            assert call['cost'] == reserve['settled_cny'] == '0.000118'
            assert summary['complete'] is True and window['state'] == 'OPEN'
        else:
            assert reserve['status'] == ('DISPUTED' if scenario == 'regressed' else 'UNKNOWN')
            assert reserve['settled_cny'] is None and window['state'] == 'HELD'
            assert summary['complete'] is (scenario == 'missing')
    response = client.get(f'/api/v1/code-tasks/{proof.window.task_id}')
    assert response.status_code == 200, response.text
    task = response.json()['data']
    assert task['budget']['unresolved_call_count'] == int(scenario != 'complete')
    if scenario == 'complete':
        assert task['status'] == 'RUNNING' and task['waiting_items'] == []
    else:
        assert task['status'] == 'WAITING' and task['resume_phase'] == 'BACKEND'
        (waiting,) = task['waiting_items']
        assert (waiting['kind'], waiting['source_kind'], waiting['source_id']) == (
            'MODEL_RESULT',
            'LLM_USE',
            call['id'],
        )
    base = f'/api/v1/code-tasks/{proof.window.task_id}/model-calls'
    listed = client.get(base)
    assert listed.status_code == 200, listed.text
    data = listed.json()
    assert data['meta']['pagination']['total'] == 1
    (public,) = data['data']['items']
    assert public['id'] == call['id'] and public['call_status'] == call['call_status']
    assert 'request_snapshot' not in public and 'provider_request_id' not in public
    detail = client.get(f'{base}/{call["id"]}')
    assert detail.status_code == 200, detail.text
    assert _PROVIDER not in detail.text and 'private reasoning' not in detail.text
    assert 'source_evidence_ref' not in detail.text and 'admission_ref' not in detail.text
    payload = detail.json()['data']
    assert payload['provider_request_id'] == 'opaque: 0012'
    assert payload['request_snapshot']['native_request'] == json.loads(_NATIVE)
    assert payload['request_snapshot']['supplier_request'] == sent[0]
    assert payload['response_snapshot']['complete'] is summary['complete']
    assert payload['response_snapshot']['frame_count'] == len(frames)
    assert payload['reservation_status'] == reserve['status']
    assert payload['settled_cny'] == reserve['settled_cny']
    assert len(sent) == 1
    if scenario == 'complete':
        assert client.get(base + '?page=2').json()['data'] == {'items': []}
        assert client.get(base + '?page=1&page=2').status_code == 422
        assert client.get(base, headers={'Idempotency-Key': 'unaccepted'}).status_code == 422
        assert (
            client.get(
                f'/api/v1/code-tasks/{proof.window.task_id + 1}/model-calls/{call["id"]}'
            ).status_code
            == 404
        )
        # Model an incomplete index while keeping the retained frames immutable.
        with db.transaction(write=True) as connection:
            connection.execute(
                'UPDATE llm_uses SET raw_response_json=? WHERE id=?',
                (
                    canonical_input({**summary, 'frame_count': summary['frame_count'] + 1}),
                    call['id'],
                ),
            )
        incomplete = client.get(f'{base}/{call["id"]}').json()['data']
        assert incomplete['capture_status'] == 'INCOMPLETE'
        assert incomplete['response_snapshot']['complete'] is False
        assert incomplete['response_snapshot']['frame_count'] == len(frames)

    if scenario != 'complete':
        with pytest.raises(CodingGatewayError, match='hold'):
            _invoke(gateway, reference, proof, stream)
        assert len(sent) == 1


def test_fenced_unsent_preserves_call_number_and_releases_only_its_reserve(opened):
    db, runtime, _, proof, reference, admission = opened
    requests = []
    gateway = _build(
        runtime,
        admission,
        lambda request: requests.append(request) or _reply(admission.model.model_name, 'complete'),
    )
    wrong = ModelIngressProof(proof.window, proof.source_evidence_ref, 'c' * 64)
    with pytest.raises(CodingGatewayError, match='source'):
        _invoke(gateway, reference, proof, lambda _: None, lambda: wrong)
    assert not requests
    _invoke(gateway, reference, proof, lambda _: None)
    with db.transaction() as connection:
        rows = connection.execute(
            'SELECT u.call_no,u.retry_of_llm_use_id,r.status FROM llm_uses u JOIN code_task_reservations r ON r.llm_use_id=u.id ORDER BY u.id'
        ).fetchall()
        assert [tuple(row) for row in rows] == [(1, None, 'RELEASED_UNSENT'), (2, None, 'SETTLED')]


def test_budget_and_credential_reject_before_supplier_or_llm_use(opened):
    db, runtime, client, proof, reference, admission = opened

    def never(_):
        pytest.fail('Supplier transport should not have been invoked')

    gateway = _build(runtime, admission, never)
    with pytest.raises(CodingModelProtocolError):
        _invoke(
            gateway,
            reference,
            proof,
            lambda _: None,
            raw=_NATIVE.replace(b'fixture prompt', _PROVIDER.encode()),
        )
    with db.transaction(write=True) as connection:
        connection.execute(
            "UPDATE code_tasks SET budget_limit_cny='0.000001' WHERE id=?", (proof.window.task_id,)
        )
    with pytest.raises(CodingGatewayError, match='budget'):
        _invoke(gateway, reference, proof, lambda _: None)
    with db.transaction() as connection:
        assert connection.execute('SELECT COUNT(*) FROM llm_uses').fetchone()[0] == 0

    with pytest.raises(CodingGatewayError, match='hold'):
        _invoke(gateway, reference, proof, lambda _: None)
    response = client.get(f'/api/v1/code-tasks/{proof.window.task_id}')
    assert response.status_code == 200, response.text
    detail = response.json()['data']
    assert detail['status'] == 'WAITING' and detail['state_version'] == 5
    assert detail['budget']['reserved_cny'] == '0.000000'
    (waiting,) = detail['waiting_items']
    assert (waiting['kind'], waiting['source_kind'], waiting['source_id']) == (
        'BUDGET',
        'OPERATION',
        proof.window.operation_id,
    )
    assert client.get(f'/api/v1/code-tasks/{proof.window.task_id}/model-calls').json()['data'] == {
        'items': []
    }


@pytest.mark.parametrize('state', ['unsent', 'sending'])
def test_restart_reconciles_only_the_original_reservation(opened, state):
    db, runtime, _, proof, reference, admission = opened
    admissions = {admission.evidence_ref: admission}
    with db.transaction(write=True) as connection:
        binding = effective_coding_binding(
            connection,
            runtime.catalog,
            admissions,
            proof.window,
            'walle-code',
            operation_time(None),
        )
        request = prepare_request(parse_request(_NATIVE), binding.contract)
        audit = prepare_audit_request(proof, request, binding, (_PROVIDER, _INSTANCE))
        call = reserve_call(
            connection, runtime.catalog, admissions, reference, proof, request, binding, audit
        )
        if state == 'sending':
            mark_sending(connection, call, proof)
    with db.transaction(write=True) as connection:
        assert recover_interrupted_calls(connection) == 1
        assert recover_interrupted_calls(connection) == 0
    with db.transaction() as connection:
        assert connection.execute('SELECT status FROM code_task_reservations').fetchone()[0] == (
            'UNKNOWN' if state == 'sending' else 'RELEASED_UNSENT'
        )
        saved = strict_json_object(
            connection.execute('SELECT model_window FROM code_sessions').fetchone()[0]
        )
        assert saved['state'] == ('HELD' if state == 'sending' else 'OPEN')


def test_original_stop_during_supplier_stream_preserves_charge_without_waiting(opened):
    db, runtime, client, proof, reference, admission = opened
    task_id = proof.window.task_id

    def handler(_):
        response = stop(client, task_id, 4)
        assert response.status_code == 202, response.text
        return _reply(admission.model.model_name, 'complete')

    gateway = _build(runtime, admission, handler)
    relayed = []
    with pytest.raises(CodingGatewayError, match='hold'):
        _invoke(gateway, reference, proof, relayed.append)
    assert not relayed
    with db.transaction() as connection:
        call = connection.execute('SELECT id,call_status FROM llm_uses').fetchone()
        assert call['call_status'] == 'CANCELLED'
        assert (
            connection.execute('SELECT status FROM code_task_reservations').fetchone()[0]
            == 'UNKNOWN'
        )
        assert connection.execute('SELECT COUNT(*) FROM code_waiting_items').fetchone()[0] == 0
    task = client.get(f'/api/v1/code-tasks/{task_id}')
    assert task.status_code == 200, task.text
    assert task.json()['data']['status'] == 'STOPPING'
    assert task.json()['data']['budget']['unresolved_call_count'] == 1


@pytest.mark.parametrize(
    'operation_type', ['CAPTURE_AND_CHECK', 'VERIFY_CANDIDATE', 'HANDOFF_ROLE']
)
def test_stage_fence_rejects_original_model_proof_before_new_call(opened, operation_type):
    db, runtime, _, proof, credential, admission = opened
    window = proof.window
    at = operation_time(None)
    with db.transaction(write=True) as connection:
        assert read_original_open_window(connection, window, credential) == window
        stage = entity_id(connection, EntityKind.OPERATION_RECORD)
        connection.execute(
            """INSERT INTO code_operations(id,task_id,resource_kind,resource_id,session_id,operation_type,
               idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at)
               VALUES(?,?,'TASK',?,?,?,?,4,'{}',?,'PENDING',?)""",
            (
                stage,
                window.task_id,
                window.task_id,
                window.execution_session_id,
                operation_type,
                'stage-fence-fixture',
                window.generation,
                at,
            ),
        )
        assert read_original_open_window(connection, window, credential) is None
    gateway = _build(runtime, admission, lambda _: pytest.fail('Fenced model used supplier'))
    with pytest.raises(CodingGatewayError, match='hold'):
        _invoke(gateway, credential, proof, lambda _: None)
    with db.transaction(write=True) as connection:
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0
        connection.execute(
            "UPDATE code_operations SET status='UNKNOWN',started_at=? WHERE id=?", (at, stage)
        )
        assert read_original_open_window(connection, window, credential) is None
