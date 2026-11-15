"""Original C39 gateway permission revoke/restore, with real Schema200 and HTTP."""

from copy import deepcopy
from uuid import uuid4

import pytest

from backend.app.code_tasks import task_live_configuration as flow
from backend.app.code_tasks.authorizations import project_grant
from backend.app.code_tasks.coding_model_admission import effective_coding_binding
from backend.app.code_tasks.coding_model_gateway import CodingModelDeployment, CodingModelGateway
from backend.app.code_tasks.coding_model_ledger import budget_facts
from backend.app.code_tasks.coding_model_listener import CodingGatewayError
from backend.app.code_tasks.costs import parse_money
from backend.app.code_tasks.task_configuration_models import (
    ModelAuthorizationError,
    compile_model_authorization,
)
from backend.app.code_tasks.task_model_ingress import ModelIngressProof
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_json_object
from backend.tests.code_tasks import test_coding_model_gateway as gateway_tests
from backend.tests.code_tasks import test_execution_profile_versions as versions
from backend.tests.code_tasks import test_task_live_configuration as live

fixed_price = live.fixed_price
isolated_readiness = live.isolated_readiness
opened = live.opened
original_instance = live.original_instance
ready = live.ready
package = live.package
service = live.service
idle_task = live.idle_task
versioned_runtime_fixture = live.versioned_runtime_fixture


def propose(fixture, refs, *, allow_local_delivery=None):
    database, _, client, _, _, task_id, _, _, _ = fixture
    old, profile, _, content = live.target_pair(fixture, 'authorization-only')
    with database.transaction() as connection:
        scope = deepcopy(
            project_grant(
                connection.execute(
                    'SELECT * FROM code_authorizations WHERE id=?', (old['authorization_id'],)
                ).fetchone()
            )['scope']
        )
    scope['model_profile_refs'] = refs
    if allow_local_delivery is not None:
        scope['allow_local_delivery'] = allow_local_delivery
    with live.resources(live.fixture_snapshot(content)):
        granted = live.approve(client, {'profile_version_id': profile, 'scope': scope})
        assert granted.status_code == 201, granted.text
        grant = granted.json()['data']['resource_id']
        response = client.post(
            f'/api/v1/code-tasks/{task_id}/configuration',
            json={
                'expected_state_version': old['state_version'],
                'execution_profile_version_id': profile,
                'authorization_id': grant,
                'reason': '明确调整原模型调用授权',
            },
            headers={'Idempotency-Key': str(uuid4())},
        )
    return old, grant, content, response


def model_resources(content):
    snapshot = live.fixture_snapshot(content)
    for kind in ('MODEL', 'CAPABILITY', 'PRICE'):
        snapshot[kind][0]['ready'] = True
    return live.resources(snapshot)


def binding(fixture, alias='walle-code'):
    database, runtime, _, ingress, _, _, _, _, admission = fixture
    with database.transaction() as connection:
        return effective_coding_binding(
            connection,
            runtime.catalog,
            {admission.evidence_ref: admission},
            ingress.window,
            alias,
            operation_time(None),
        )


def advance(fixture, driver, content):
    with live.resources(live.fixture_snapshot(content)):
        return flow.advance_live_configuration(fixture[1], driver, cancelled=lambda: False)


@pytest.mark.parametrize('mode', ['success', 'unknown', 'stop'])
def test_gateway_permission_revoke_restores_only_original_refs(idle_task, mode):
    database, _, client, ingress, _, task_id, _, _, _ = idle_task
    old, grant, content, accepted = propose(idle_task, [])
    assert accepted.status_code == 202, accepted.text
    identity = accepted.json()['data']['operation_id']
    with database.transaction() as connection:
        stored = strict_json_object(
            connection.execute(
                'SELECT external_identity FROM code_operation_steps WHERE operation_id=? AND step_no=1',
                (identity,),
            ).fetchone()[0]
        )['source']['model_authorization']
        assert stored['launch_authorization_id'] == old['authorization_id']
        assert stored['model_profile_refs'] == []
        assert not any(alias['allowed'] for alias in stored['aliases'])
    driver = live.ReadOnlyDriver(idle_task, unknown=mode == 'unknown')
    if mode == 'stop':
        stopped = live.stop(client, task_id, accepted.json()['data']['state_version'])
        assert stopped.status_code == 202, stopped.text
        assert not advance(idle_task, driver, content)
        assert driver.calls == []
        with database.transaction() as connection:
            assert (
                connection.execute(
                    'SELECT authorization_id FROM code_tasks WHERE id=?', (task_id,)
                ).fetchone()[0]
                == old['authorization_id']
            )
        return
    assert advance(idle_task, driver, content)
    if mode == 'unknown':
        with database.transaction() as connection:
            assert (
                connection.execute(
                    'SELECT authorization_id FROM code_tasks WHERE id=?', (task_id,)
                ).fetchone()[0]
                == old['authorization_id']
            )
            assert (
                connection.execute(
                    'SELECT status FROM code_authorizations WHERE id=?', (grant,)
                ).fetchone()[0]
                == 'APPLY_UNKNOWN'
            )
        driver.unknown = False
        assert advance(idle_task, driver, content)
    outcome = client.get(f'/api/v1/code-tasks/{task_id}/operations/{identity}')
    assert outcome.status_code == 200, outcome.text
    assert outcome.json()['data']['status'] == 'SUCCEEDED'
    with model_resources(content), pytest.raises(CodingGatewayError, match='hold'):
        binding(idle_task)
    # Restoring the original permission does not restore a retired grant identity.
    _, restored, restored_content, response = propose(idle_task, ['deepseek-v2'])
    assert response.status_code == 202, response.text
    assert advance(idle_task, driver, restored_content)
    with model_resources(restored_content):
        assert binding(idle_task).profile_version_id == old['execution_profile_version_id']
    with database.transaction() as connection:
        task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        assert task['authorization_id'] == restored
        assert task['active_session_id'] == ingress.window.execution_session_id
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0
    assert client.get(f'/api/v1/code-tasks/{task_id}/operations/{identity}').status_code == 200


def test_model_compilation_cannot_expand_past_original_launch(idle_task):
    database, _, _, _, _, task_id, _, _, _ = idle_task
    _, _, _, content = live.target_pair(idle_task)
    with database.transaction() as connection:
        with pytest.raises(ModelAuthorizationError):
            compile_model_authorization(
                connection, task_id, content['models'], {'model_profile_refs': ['doubao-v1']}
            )
        changed = deepcopy(content['models'])
        changed['bindings'][0]['model_profile_ref'] = 'doubao-v1'
        with pytest.raises(ModelAuthorizationError):
            compile_model_authorization(connection, task_id, changed, {'model_profile_refs': []})


@pytest.mark.parametrize('alias', ['walle-code', 'walle-compaction'])
def test_revoked_model_is_blocked_before_ledger_or_supplier_and_restore_does_not_resume(
    idle_task, alias
):
    database, runtime, _, ingress, _, _, _, _, admission = idle_task
    _, _, content, accepted = propose(idle_task, [])
    assert accepted.status_code == 202, accepted.text
    driver = live.ReadOnlyDriver(idle_task)
    assert advance(idle_task, driver, content)
    supplier_calls = []

    def forbidden_transport(_):
        supplier_calls.append(True)
        raise AssertionError('A closed or unauthorized window must not contact a supplier')

    gateway = CodingModelGateway(
        runtime, CodingModelDeployment((admission,)), transport_factory=forbidden_transport
    )
    proof = ModelIngressProof(ingress.window, 'a' * 64, 'b' * 64)
    raw = canonical_input(
        {'model': alias, 'messages': [{'role': 'user', 'content': 'offline fixture'}]}
    ).encode()
    with model_resources(content), pytest.raises(CodingGatewayError, match='hold'):
        gateway(
            'a' * 32,
            proof,
            raw,
            lambda: proof,
            lambda _: None,
            lambda: False,
            instance_secret='e' * 64,
        )
    _, _, restored_content, response = propose(idle_task, ['deepseek-v2'])
    assert response.status_code == 202, response.text
    assert advance(idle_task, driver, restored_content)
    with model_resources(restored_content):
        assert binding(idle_task, alias).admission is admission
        with pytest.raises(CodingGatewayError, match='hold'):
            gateway(
                'a' * 32,
                proof,
                raw,
                lambda: proof,
                lambda _: None,
                lambda: False,
                instance_secret='e' * 64,
            )
    assert supplier_calls == []
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0


@pytest.fixture
def unused_declared_model(versioned_runtime_fixture, monkeypatch):
    body = versions.body
    snapshot = versions.fixture_snapshot

    def declared_body():
        value = body()
        value['models']['auxiliary_profile_refs'] = ['doubao-v1']
        return value

    def declared_snapshot(content=None):
        value = snapshot(content)
        value['MODEL'].append(
            {
                'value': {'model_profile_ref': 'doubao-v1'},
                'ready': False,
                'unresolved_capability_codes': ['Q20-MODEL'],
            }
        )
        return value

    monkeypatch.setattr(versions, 'body', declared_body)
    monkeypatch.setattr(versions, 'fixture_snapshot', declared_snapshot)
    monkeypatch.setattr(live, 'fixture_snapshot', declared_snapshot)


@pytest.fixture
def declared_idle(unused_declared_model, request):
    return request.getfixturevalue('idle_task')


def test_declared_but_never_launched_model_is_rejected_before_binding(declared_idle):
    database, _, _, _, _, task_id, _, _, _ = declared_idle
    old, grant, content, response = propose(declared_idle, ['doubao-v1'])
    assert 'doubao-v1' in content['models']['auxiliary_profile_refs']
    assert response.status_code in (403, 409), response.text
    assert response.json()['error']['code'] == 'AUTHORIZATION_NOT_APPLICABLE'
    with database.transaction() as connection:
        current = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        assert current['state_version'] == old['state_version']
        assert current['authorization_id'] == old['authorization_id']
        assert connection.execute(
            'SELECT task_id,status FROM code_authorizations WHERE id=?', (grant,)
        ).fetchone()[:] == (None, 'APPROVED_UNBOUND')
        assert (
            connection.execute(
                "SELECT count(*) FROM code_operations WHERE task_id=? AND operation_type='APPLY_CONFIGURATION'",
                (task_id,),
            ).fetchone()[0]
            == 0
        )


def test_original_model_grant_requires_exact_json_owner_ids(idle_task, monkeypatch):
    from backend.app.code_tasks import task_start
    from backend.app.code_tasks.task_start_authorization import original_start_authorization

    database, _, _, _, _, task_id, _, _, _ = idle_task
    read_steps = task_start.original_start_steps
    with database.transaction() as connection:
        original = original_start_authorization(connection, task_id)
        for field in ('task_id', 'operation_id', 'profile_id'):
            for kind in ('float', 'boolean'):

                def malformed_owner(connection, operation, field=field, kind=kind):
                    fixed, rows = read_steps(connection, operation)
                    rows = [dict(row) for row in rows]
                    source = strict_json_object(rows[4]['external_identity'])
                    source[field] = float(source[field]) if kind == 'float' else True
                    rows[4]['external_identity'] = canonical_input(source)
                    return fixed, rows

                with monkeypatch.context() as patch:
                    patch.setattr(task_start, 'original_start_steps', malformed_owner)
                    with pytest.raises(StorageUnavailable, match='owner differs'):
                        original_start_authorization(connection, task_id)
        assert original_start_authorization(connection, task_id) == original


@pytest.fixture
def settled_idle(opened, request):
    _, runtime, _, proof, credential, admission = opened

    def settled_response(_):
        return gateway_tests._reply(admission.model.model_name, 'complete')

    gateway = gateway_tests._build(runtime, admission, settled_response)
    gateway_tests._invoke(gateway, credential, proof, lambda _: None)
    return request.getfixturevalue('idle_task')


def test_reauthorization_preserves_settled_task_cost_and_request_count(settled_idle):
    database, _, client, _, _, task_id, _, _, _ = settled_idle

    def ledger():
        with database.transaction() as connection:
            limit = parse_money(
                connection.execute(
                    'SELECT budget_limit_cny FROM code_tasks WHERE id=?', (task_id,)
                ).fetchone()[0]
            )
            facts = budget_facts(connection, task_id, limit)
            calls = [tuple(row) for row in connection.execute('SELECT * FROM llm_uses ORDER BY id')]
            reservations = [
                tuple(row)
                for row in connection.execute('SELECT * FROM code_task_reservations ORDER BY id')
            ]
            return facts, calls, reservations

    original = ledger()
    assert original[0].requests == 1 and original[0].settled == 118
    assert original[0].reserved == original[0].unresolved == 0
    public = client.get(f'/api/v1/code-tasks/{task_id}').json()['data']['budget']
    driver = live.ReadOnlyDriver(settled_idle)
    for refs in ([], ['deepseek-v2']):
        _, _, content, accepted = propose(settled_idle, refs)
        assert accepted.status_code == 202, accepted.text
        assert advance(settled_idle, driver, content)
        assert ledger() == original
        response = client.get(f'/api/v1/code-tasks/{task_id}')
        assert response.status_code == 200, response.text
        assert response.json()['data']['budget'] == public


def test_model_revoke_cannot_bind_while_original_call_is_sending(opened, monkeypatch):
    from types import SimpleNamespace

    database, runtime, client, proof, credential, admission = opened
    task_id = proof.window.task_id
    fixture = (database, runtime, client, proof, None, task_id, None, None, admission)
    monkeypatch.setattr(
        client.app.state,
        'walle_repository_registration',
        SimpleNamespace(accepts_live_configuration=True, wake=lambda: None),
        raising=False,
    )
    observed = []

    def sending_response(_):
        with database.transaction() as connection:
            assert (
                connection.execute('SELECT transport_status FROM llm_uses').fetchone()[0]
                == 'SENDING'
            )
            assert (
                connection.execute('SELECT status FROM code_task_reservations').fetchone()[0]
                == 'RESERVED'
            )
        old, grant, _, response = propose(fixture, [])
        assert response.status_code == 503, response.text
        assert response.json()['error']['code'] == 'CONFIG_NOT_READY'
        with database.transaction() as connection:
            task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
            assert task['authorization_id'] == old['authorization_id']
            assert task['state_version'] == old['state_version']
            assert connection.execute(
                'SELECT task_id,status FROM code_authorizations WHERE id=?', (grant,)
            ).fetchone()[:] == (None, 'APPROVED_UNBOUND')
            assert (
                connection.execute(
                    "SELECT count(*) FROM code_operations WHERE task_id=? AND operation_type='APPLY_CONFIGURATION'",
                    (task_id,),
                ).fetchone()[0]
                == 0
            )
        observed.append(grant)
        return gateway_tests._reply(admission.model.model_name, 'complete')

    failures = []

    def checked_response(request):
        # The production gateway hides supplier exceptions. Keep test assertions
        # outside that privacy boundary without changing the real gateway.
        try:
            return sending_response(request)
        except AssertionError as error:
            failures.append(error)
            return gateway_tests._reply(admission.model.model_name, 'complete')

    gateway = gateway_tests._build(runtime, admission, checked_response)
    gateway_tests._invoke(gateway, credential, proof, lambda _: None)
    if failures:
        raise failures[0]
    assert len(observed) == 1
    with database.transaction() as connection:
        assert (
            connection.execute('SELECT status FROM code_task_reservations').fetchone()[0]
            == 'SETTLED'
        )
