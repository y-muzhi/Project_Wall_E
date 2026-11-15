"""Bounded C39 local-delivery grants through real isolated HTTP and C64 checks."""

import pytest

from backend.app.code_tasks.task_delivery import _deliver_authorization
from backend.app.shared.validation import strict_json_object
from backend.tests.code_tasks import test_execution_profile_versions as versions
from backend.tests.code_tasks import test_task_model_authorization as models
from backend.tests.code_tasks import test_task_stop as stops
from backend.tests.code_tasks.test_execution_profile_content import delivery

fixed_price = models.fixed_price
isolated_readiness = models.isolated_readiness
opened = models.opened
original_instance = models.original_instance
ready = models.ready
package = models.package
service = models.service
idle_task = models.idle_task
versioned_runtime_fixture = models.versioned_runtime_fixture


def configure_original_delivery(monkeypatch, allowed):
    original_body = versions.body
    original_scope = stops.scope

    def prepared():
        value = original_body()
        value['delivery'] = delivery()
        return value

    def scope():
        value = original_scope()
        value['allow_local_delivery'] = allowed
        return value

    monkeypatch.setattr(versions, 'body', prepared)
    monkeypatch.setattr(stops, 'scope', scope)


@pytest.fixture(autouse=True)
def original_delivery(versioned_runtime_fixture, monkeypatch, request):
    configure_original_delivery(monkeypatch, getattr(request, 'param', True))


def delivery_gate(fixture):
    database, _, _, _, _, task_id, _, _, _ = fixture
    with database.transaction() as connection:
        task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        return _deliver_authorization(connection, task)


@pytest.mark.parametrize('mode', ['success', 'unknown', 'stop'])
def test_original_delivery_permission_revoke_restore_preserves_explicit_control(idle_task, mode):
    database, _, client, _, _, task_id, _, _, _ = idle_task
    assert delivery_gate(idle_task) is not None
    old, grant, content, accepted = models.propose(
        idle_task, ['deepseek-v2'], allow_local_delivery=False
    )
    assert accepted.status_code == 202, accepted.text
    identity = accepted.json()['data']['operation_id']
    with database.transaction() as connection:
        source = strict_json_object(
            connection.execute(
                'SELECT external_identity FROM code_operation_steps WHERE operation_id=? AND step_no=1',
                (identity,),
            ).fetchone()[0]
        )['source']
        proof = source['delivery_authorization']
        assert proof['launch_authorization_id'] == old['authorization_id']
        assert proof['allow_local_delivery'] is False
        assert len(proof['delivery_sha256']) == 64
        assert 'model_authorization' not in source
    driver = models.live.ReadOnlyDriver(idle_task, unknown=mode == 'unknown')
    if mode == 'stop':
        stopped = models.live.stop(client, task_id, accepted.json()['data']['state_version'])
        assert stopped.status_code == 202, stopped.text
        assert not models.advance(idle_task, driver, content)
        assert driver.calls == []
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
                == 'BOUND_PENDING_APPLY'
            )
        return
    assert models.advance(idle_task, driver, content)
    if mode == 'unknown':
        assert delivery_gate(idle_task) is not None
        with database.transaction() as connection:
            assert (
                connection.execute(
                    'SELECT status FROM code_authorizations WHERE id=?', (grant,)
                ).fetchone()[0]
                == 'APPLY_UNKNOWN'
            )
        driver.unknown = False
        assert models.advance(idle_task, driver, content)
    assert delivery_gate(idle_task) is None
    _, restored, content, accepted = models.propose(
        idle_task, ['deepseek-v2'], allow_local_delivery=True
    )
    assert accepted.status_code == 202, accepted.text
    assert models.advance(idle_task, driver, content)
    assert delivery_gate(idle_task) is not None
    with database.transaction() as connection:
        task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        assert task['authorization_id'] == restored and task['status'] == 'VERIFYING'
        assert task['current_delivery_id'] is None and task['current_delivery_plan_id'] is None
        assert connection.execute('SELECT count(*) FROM code_acceptances').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM code_deliveries').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0
    history = client.get(f'/api/v1/code-tasks/{task_id}/operations/{identity}')
    assert history.status_code == 200, history.text
    assert history.json()['data']['status'] == 'SUCCEEDED'


@pytest.mark.parametrize('original_delivery', [False], indirect=True)
def test_explicit_new_approval_can_enable_fixed_original_delivery(idle_task):
    database, _, _, _, _, task_id, _, _, _ = idle_task
    assert delivery_gate(idle_task) is None
    old, grant, content, response = models.propose(
        idle_task, ['deepseek-v2'], allow_local_delivery=True
    )
    assert response.status_code == 202, response.text
    driver = models.live.ReadOnlyDriver(idle_task)
    assert models.advance(idle_task, driver, content)
    assert delivery_gate(idle_task) is not None
    with database.transaction() as connection:
        task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        assert task['authorization_id'] == grant
        assert task['execution_profile_version_id'] == old['execution_profile_version_id']
        assert task['current_delivery_id'] is None and task['current_delivery_plan_id'] is None
        assert connection.execute('SELECT count(*) FROM code_deliveries').fetchone()[0] == 0


def test_compiler_rejects_delivery_identity_drift(idle_task):
    from copy import deepcopy

    from backend.app.code_tasks.task_configuration_delivery import (
        DeliveryAuthorizationError,
        compile_delivery_authorization,
    )

    database, _, _, _, _, task_id, _, _, _ = idle_task
    original = delivery()
    with database.transaction() as connection:
        changed = deepcopy(original)
        changed['author_email'] = 'different@example.test'
        for target in (None, changed):
            with pytest.raises(DeliveryAuthorizationError):
                compile_delivery_authorization(
                    connection, task_id, target, {'allow_local_delivery': True}
                )


def test_model_and_delivery_permissions_adopt_as_one_original_pair(idle_task):
    from backend.app.code_tasks.coding_model_listener import CodingGatewayError

    database, _, _, _, _, task_id, _, _, _ = idle_task
    old, grant, content, accepted = models.propose(idle_task, [], allow_local_delivery=False)
    assert accepted.status_code == 202, accepted.text
    driver = models.live.ReadOnlyDriver(idle_task)
    assert models.advance(idle_task, driver, content)
    assert delivery_gate(idle_task) is None
    with models.model_resources(content), pytest.raises(CodingGatewayError, match='hold'):
        models.binding(idle_task)
    with database.transaction() as connection:
        current = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        assert current['authorization_id'] == grant
        assert (
            connection.execute(
                'SELECT status FROM code_authorizations WHERE id=?', (old['authorization_id'],)
            ).fetchone()[0]
            == 'RETIRED'
        )
        source = strict_json_object(
            connection.execute(
                'SELECT external_identity FROM code_operation_steps WHERE operation_id=? AND step_no=1',
                (accepted.json()['data']['operation_id'],),
            ).fetchone()[0]
        )['source']
        assert source['model_authorization']['launch_authorization_id'] == old['authorization_id']
        assert (
            source['delivery_authorization']['launch_authorization_id'] == old['authorization_id']
        )
    _, restored, content, accepted = models.propose(
        idle_task, ['deepseek-v2'], allow_local_delivery=True
    )
    assert accepted.status_code == 202, accepted.text
    assert models.advance(idle_task, driver, content)
    assert delivery_gate(idle_task) is not None
    with models.model_resources(content):
        assert models.binding(idle_task).profile_version_id == old['execution_profile_version_id']
    with database.transaction() as connection:
        assert (
            connection.execute(
                'SELECT authorization_id FROM code_tasks WHERE id=?', (task_id,)
            ).fetchone()[0]
            == restored
        )
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM code_deliveries').fetchone()[0] == 0
