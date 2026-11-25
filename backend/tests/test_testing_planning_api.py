"""Original AI draft, usage, and closure through isolated HTTP and SQLite."""

import asyncio
from hashlib import sha256
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import httpx
import pytest

from backend.app.code_tasks.usage import UsageContract
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.model_gateway import ModelGateway
from backend.app.infrastructure.model_profile import DEFAULT_PROFILE, ModelProfile
from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.app.shared.validation import strict_json_object
from backend.app.testing.planning_context import (
    PROMPT,
    PROMPT_SHA256,
)
from backend.app.testing.planning_context import (
    TestingModelAdmission as PlanAdmission,
)
from backend.app.testing.planning_context import (
    TestingPlanningInstallation as PlanInstallation,
)
from backend.tests.code_tasks.test_execution_profile_versions import resources
from backend.tests.code_tasks.test_repository_baseline_acceptance import repository_service  # noqa: F401
from backend.tests.infrastructure.test_v20_command_http import package, service  # noqa: F401
from backend.tests.test_testing_plan_api import MAIN, MATERIAL, setup
from backend.tests.test_testing_policy_api import OPTIONS, content, create, post, receipt
from backend.tests.test_testing_reference_sets import baseline_fixture
from backend.tests.test_testing_task_api import TASKS, approve

_DRAFT = TASKS + '/1/draft-plan'
_BASIS = ('requirement_id', 'document_id', 'design_revision_id', 'material_refs')
_FIELDS = ('behaviors', 'cases', 'unresolved_questions')
_AT = '2026-01-01T00:00:00.000Z'


def _price(database):
    with database.transaction(write=True) as connection:
        connection.execute(
            """INSERT INTO model_price_versions VALUES(2,'deepseek-v2','fixture-snapshot',
              'ARK_CN_BEIJING','fixture-account','default',?,NULL,'CNY','1.000000','2.000000','[]',?,
              'TOTAL_HALF_UP_6DP','fixture-price',?)""",
            (
                _AT,
                canonical_input(
                    {
                        'kind': 'FLAT',
                        'pricing_clock': 'COMPLETED_AT',
                        'timezone': 'Asia/Shanghai',
                    }
                ),
                _AT,
            ),
        )
        return sha256(
            _bytes(
                dict(connection.execute('SELECT * FROM model_price_versions WHERE id=2').fetchone())
            )
        ).hexdigest()


def _configure(repository_service, handler, *, budget='0.500000', installed=True):  # noqa: F811
    database, runtime, client = repository_service
    basis = setup((database, client.app, client))
    snapshot = baseline_fixture(runtime, 'a' * 40)
    price = _price(database)
    model = ModelProfile('fixture-only-model-key', DEFAULT_PROFILE)
    admission = PlanAdmission(
        'fixture-model',
        'fixture-snapshot',
        'fixture-account',
        price,
        PROMPT_SHA256,
        model,
        UsageContract('test-plan-fixture', 'COMPLETE_BODY', ('input_tokens', 'output_tokens')),
        30,
        32768,
        16000,
    )
    if installed:
        runtime.catalog.testing_planning = PlanInstallation(
            (admission,), ModelGateway(transport_factory=lambda: httpx.MockTransport(handler))
        )
    profile = content()
    profile['admission_refs'].append('fixture-model')
    profile['model_binding'] = {
        'model_profile_ref': model.profile_id,
        'model_snapshot_ref': 'fixture-snapshot',
        'price_version_id': 2,
        'input_cap_tokens': 16000,
        'output_cap_tokens': 1000,
        'admission_ref': 'fixture-model',
    }
    profile['limits'].update(
        max_model_requests=2,
        max_active_seconds=30,
        max_input_bytes=32768,
        query_timeout_seconds=10,
        send_timeout_seconds=25,
    )
    options = {
        **OPTIONS,
        'MODEL': [{'value': {'model_profile_ref': model.profile_id}, 'ready': True}],
        'PRICE': [
            {'value': {'price_version_id': 2, 'model_profile_ref': model.profile_id}, 'ready': True}
        ],
        'CAPABILITY': [
            *OPTIONS['CAPABILITY'],
            {
                'value': {'capability_code': 'Q20-MODEL', 'evidence_ref': 'fixture-model'},
                'ready': True,
            },
        ],
    }
    with resources(options):
        response = create(client, profile)
    assert response.status_code == 201, response.text
    result = post(
        client,
        TASKS,
        {
            **{key: basis[key] for key in _BASIS},
            'target_kind': 'SNAPSHOT',
            'candidate_id': None,
            'snapshot_id': snapshot,
            'purpose': 'DIAGNOSTIC',
            'profile_version_id': 1,
            'authorization_id': approve(client),
            'budget_limit_cny': budget,
            'plan_version_id': None,
            'test_pack_version_id': None,
            'previous_testing_task_id': None,
        },
    )
    assert result.status_code == 201, result.text
    return basis, model


def _wait(client, identity, status):
    deadline = monotonic() + 15
    path = TASKS + f'/1/operations/{identity}'
    while monotonic() < deadline:
        response = client.get(path)
        assert response.status_code == 200, response.text
        result = response.json()['data']
        if result['status'] == status:
            return result
        sleep(0.04)
    pytest.fail(f'Original draft {identity} did not reach {status}: {result}')


@pytest.mark.parametrize('mode', ['valid', 'bad_quote', 'unknown'])
def test_explicit_draft_at_most_once_with_original_usage(repository_service, mode):  # noqa: F811
    database, _, client = repository_service
    calls = []

    def handler(request):
        calls.append(strict_json_object(request.content))
        draft = {key: basis[key] for key in _FIELDS}
        if mode == 'bad_quote':
            draft['behaviors'][0]['basis_refs'][0]['quote'] = '凭空编造的依据'
        body = {
            'id': 'test-provider-response',
            'model': model.model_name,
            'choices': [
                {
                    'finish_reason': 'stop',
                    'message': {
                        'role': 'assistant',
                        'content': canonical_input(draft),
                    },
                }
            ],
        }
        if mode != 'unknown':
            body['usage'] = {'prompt_tokens': 99, 'completion_tokens': 30}
        return httpx.Response(200, json=body)

    budget = '0.000000' if mode == 'valid' else '0.500000'
    basis, model = _configure(repository_service, handler, budget=budget)
    initial = client.get(TASKS + '/1')
    assert initial.status_code == 200, initial.text
    assert {'action': 'DRAFT_PLAN', 'enabled': True, 'reason_code': None} in initial.json()['data'][
        'available_actions'
    ]
    key = str(uuid4())
    accepted = post(client, _DRAFT, {'expected_state_version': 1}, key)
    assert accepted.status_code == 202, accepted.text
    operation = accepted.json()['data']['operation_id']
    assert (
        post(client, _DRAFT, {'expected_state_version': 1}, key).json()['data']
        == accepted.json()['data']
    )
    assert receipt(client, _DRAFT, key)['operation_id'] == operation
    completed = _wait(
        client, operation, {'valid': 'SUCCEEDED', 'bad_quote': 'FAILED', 'unknown': 'UNKNOWN'}[mode]
    )
    assert len(calls) == 1
    original = calls[0]
    assert original['response_format'] == {'type': 'json_object'} and original['stream'] is False
    assert original['max_tokens'] == 1000 and 'tools' not in original
    assert original['messages'][0]['content'] == PROMPT
    fixed = strict_json_object(original['messages'][1]['content'])
    assert [row['markdown'] for row in fixed['fixed_design_and_materials']] == [
        MAIN + '\n',
        MATERIAL + '\n',
    ]
    assert set(fixed) == {
        'fixed_design_and_materials',
        'registered_capabilities',
        'output_schema',
        'budget_limit_cny',
        'output_cap_tokens',
    }
    assert fixed['budget_limit_cny'] == budget
    task = client.get(TASKS + '/1').json()['data']
    assert task['plan_version_id'] is None and task['test_pack_version_id'] is None
    assert task['status'] == ('WAITING' if mode == 'unknown' else 'DRAFT')
    assert (task['draft_plan_result'] is not None) == (mode == 'valid')
    if mode == 'valid':
        assert completed['steps'][-1]['result_ref'] == {
            field: task['draft_plan_result'][field] for field in ('plan_id', 'plan_version_id')
        }
    with database.transaction() as connection:
        use = connection.execute('SELECT * FROM llm_uses WHERE testing_task_id=1').fetchone()
        reserve = connection.execute(
            'SELECT * FROM code_task_reservations WHERE testing_task_id=1'
        ).fetchone()
        assert use['gateway_request_id'] is None and use['execution_session_id'] is None
        assert use['call_no'] == use['attempt_no'] == 1
        assert reserve['status'] == ('UNKNOWN' if mode == 'unknown' else 'SETTLED')
        assert reserve['settled_cny'] == (None if mode == 'unknown' else '0.000159')
        assert connection.execute('SELECT count(*) FROM testing_plan_versions').fetchone()[
            0
        ] == int(mode == 'valid')
        assert connection.execute('SELECT count(*) FROM model_usage_evidence').fetchone()[0] == int(
            mode != 'unknown'
        )
    if mode == 'unknown':
        stopped = post(
            client, TASKS + '/1/terminate', {'expected_state_version': task['state_version']}
        )
        assert stopped.status_code == 202, stopped.text
        _wait(client, stopped.json()['data']['operation_id'], 'SUCCEEDED')
        _wait(client, operation, 'CANCELLED')
        assert len(calls) == 1
        with database.transaction() as connection:
            assert (
                connection.execute(
                    'SELECT status FROM code_task_reservations WHERE testing_task_id=1'
                ).fetchone()[0]
                == 'UNKNOWN'
            )


def test_missing_draft_admission_rejects_before_model_use(repository_service):  # noqa: F811
    database, _, client = repository_service
    _configure(
        repository_service,
        lambda _: pytest.fail('No provider call authorized'),
        installed=False,
    )
    failed = post(client, _DRAFT, {'expected_state_version': 1})
    assert (failed.status_code, failed.json()['error']['code']) == (503, 'CONFIG_NOT_READY')
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0


def test_late_model_completion_keeps_usage_and_cannot_save_a_draft(repository_service):  # noqa: F811
    database, _, client = repository_service
    sent, release = Event(), Event()

    async def handler(request):
        sent.set()
        assert await asyncio.to_thread(release.wait, 12)
        return httpx.Response(
            200,
            json={
                'id': 'late-model-fixture',
                'model': model.model_name,
                'choices': [
                    {
                        'finish_reason': 'stop',
                        'message': {
                            'role': 'assistant',
                            'content': canonical_input({key: basis[key] for key in _FIELDS}),
                        },
                    }
                ],
                'usage': {'prompt_tokens': 99, 'completion_tokens': 30},
            },
        )

    basis, model = _configure(repository_service, handler)
    response = post(client, _DRAFT, {'expected_state_version': 1})
    assert response.status_code == 202, response.text
    try:
        assert sent.wait(timeout=10)
        stopped = post(client, TASKS + '/1/terminate', {'expected_state_version': 2})
        assert stopped.status_code == 202, stopped.text
    finally:
        release.set()
    _wait(client, stopped.json()['data']['operation_id'], 'SUCCEEDED')
    _wait(client, response.json()['data']['operation_id'], 'CANCELLED')
    task = client.get(TASKS + '/1').json()['data']
    assert task['status'] == 'TERMINATED' and task['draft_plan_result'] is None
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM testing_plan_versions').fetchone()[0] == 0
        assert (
            connection.execute(
                'SELECT status FROM code_task_reservations WHERE testing_task_id=1'
            ).fetchone()[0]
            == 'SETTLED'
        )
