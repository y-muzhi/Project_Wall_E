"""Original C39 check-set proposals use actual Schema200/ASGI with offline native reads."""

import json
from dataclasses import asdict, replace
from uuid import uuid4

import pytest

from backend.app.code_tasks.authorizations import project_grant
from backend.app.code_tasks.coding_check_plan import read_coding_check_selection
from backend.app.code_tasks.coding_project_check_scope import require_project_check_admissions
from backend.app.code_tasks.execution_profile_content import FIELDS
from backend.app.code_tasks.task_live_configuration import advance_live_configuration
from backend.tests.code_tasks import test_execution_profile_versions as versions
from backend.tests.code_tasks import test_task_stop as stops
from backend.tests.code_tasks.test_authorizations import approve
from backend.tests.code_tasks.test_check_set_content import body as check_body
from backend.tests.code_tasks.test_check_set_content import command, integrity
from backend.tests.code_tasks.test_check_set_versions import publish as publish_checks
from backend.tests.code_tasks.test_execution_profile_versions import (
    fixture_snapshot,
    publish,
    resources,
)
from backend.tests.code_tasks.test_task_live_configuration import (
    ReadOnlyDriver,
    fixed_price,  # noqa: F401
    idle_task,  # noqa: F401
    isolated_readiness,  # noqa: F401
    opened,  # noqa: F401
    original_instance,  # noqa: F401
    ready,  # noqa: F401
    versioned_runtime_fixture,  # noqa: F401
)
from backend.tests.infrastructure.test_v20_command_http import package, service  # noqa: F401
from backend.tests.infrastructure.v20_guard_control_git_pipe_worker import fixture_project_admission


@pytest.fixture(autouse=True)
def check_profile(versioned_runtime_fixture, monkeypatch):  # noqa: F811
    previous = versions.body
    definition = json.loads(json.dumps(asdict(fixture_project_admission().command)))
    previous_scope = stops.scope

    def body():
        result = previous()
        result['commands'] = [definition]
        return result

    def scope():
        result = previous_scope()
        result['allowed_command_ids'] = [definition['command_id']]
        return result

    monkeypatch.setattr(versions, 'body', body)
    monkeypatch.setattr(stops, 'scope', scope)


def check_resources(content, *, available=True):
    snapshot = fixture_snapshot(content)
    for row in snapshot['COMMAND']:
        row['ready'] = available
        row['unresolved_capability_codes'] = [] if available else ['Q20-CHECKS']
    snapshot['RUNNER'] = [
        {
            'ready': available,
            'unresolved_capability_codes': [] if available else ['Q20-CHECKS'],
            'value': {
                'runner_ref': 'fixture:project-runner',
                'protocol_version': 'CHECK20-CONTROL-1',
                'capabilities': ['CLI', 'CONTENT_INTEGRITY'],
                'protected_input_refs': [],
            },
        }
    ]
    return snapshot


def prepare_check_pair(
    fixture,
    *,
    timeout=17,
    empty=False,
    stages=None,
    preserve_checks=False,
    output_profile=None,
    output_grant=None,
    same_profile=False,
):
    database, _, client, _, _, task_id, _, _, _ = fixture
    with database.transaction() as connection:
        original = dict(
            connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        )
        row = connection.execute(
            'SELECT * FROM code_execution_profile_versions WHERE id=?',
            (original['execution_profile_version_id'],),
        ).fetchone()
        content = {
            key: row[key]
            if key == 'check_set_version_id' or row[key] is None
            else json.loads(row[key])
            for key in FIELDS
        }
        scope = project_grant(
            connection.execute(
                'SELECT * FROM code_authorizations WHERE id=?', (original['authorization_id'],)
            ).fetchone()
        )['scope']
    selected_stages = ['BACKEND'] if stages is None else stages
    checks = (
        []
        if empty
        else [
            integrity(runner_ref='fixture:project-runner', stages=selected_stages),
            {
                **command(
                    runner_ref='fixture:project-runner',
                    stages=selected_stages,
                    timeout_seconds=timeout,
                ),
                'command_id': content['commands'][0]['command_id'],
            },
        ]
    )
    if output_profile is not None:
        content['limits']['max_check_output_bytes'] = output_profile
    if output_grant is not None:
        scope['limits']['max_check_output_bytes'] = output_grant
    with resources(check_resources(content)):
        if not preserve_checks:
            result = publish_checks(client, check_body(checks, []))
            assert result.status_code == 201, result.text
            content['check_set_version_id'] = result.json()['data']['resource_id']
        if same_profile:
            profile = original['execution_profile_version_id']
        else:
            result = publish(client, content)
            assert result.status_code == 201, result.text
            profile = result.json()['data']['resource_id']
        result = approve(client, {'profile_version_id': profile, 'scope': scope})
        assert result.status_code == 201, result.text
        grant = result.json()['data']['resource_id']
    return original, profile, grant, content


@pytest.mark.parametrize(
    'case',
    [
        'success',
        'unknown',
        'withdrawn',
        'admission-changed',
        'missing-admission',
        'empty',
        'future-only',
        'stop',
        'stop-during-read',
    ],
)
def test_new_check_set_keeps_original_launch_and_revalidates_same_proposal(idle_task, case):  # noqa: F811
    database, runtime, client, ingress, _, task_id, _, _, _ = idle_task
    original, profile, grant, content = prepare_check_pair(
        idle_task, empty=case == 'empty', stages=['FRONTEND'] if case == 'future-only' else None
    )
    path = f'/api/v1/code-tasks/{task_id}'
    admissions = (fixture_project_admission(),)
    worker = client.app.state.walle_repository_registration
    worker.project_check_admissions = () if case == 'missing-admission' else admissions
    key = str(uuid4())
    fixed = {
        'expected_state_version': original['state_version'],
        'execution_profile_version_id': profile,
        'authorization_id': grant,
        'reason': '明确应用新的检查标准并保留原候选',
    }
    with resources(check_resources(content)):
        accepted = client.post(
            path + '/configuration', json=fixed, headers={'Idempotency-Key': key}
        )
    if case in ('missing-admission', 'empty', 'future-only'):
        assert accepted.status_code == 503, accepted.text
        assert 'Q20-CHECKS' in accepted.text
        with database.transaction() as connection:
            assert connection.execute(
                'SELECT task_id,status FROM code_authorizations WHERE id=?', (grant,)
            ).fetchone()[:] == (None, 'APPROVED_UNBOUND')
        return
    assert accepted.status_code == 202, accepted.text
    receipt = accepted.json()['data']
    driver = ReadOnlyDriver(idle_task, unknown=case == 'unknown')
    if case in ('stop', 'stop-during-read'):
        from datetime import UTC, datetime, timedelta

        from backend.app.code_tasks import task_runtime_stop
        from backend.tests.code_tasks.test_task_runtime_stop import StopDriver
        from backend.tests.code_tasks.test_task_start import stop

        def stop_original():
            result = stop(client, task_id, receipt['state_version'])
            assert result.status_code == 202, result.text

        if case == 'stop':
            stop_original()
        else:
            driver.interleave = stop_original
        assert not advance_live_configuration(
            runtime, driver, cancelled=lambda: False, check_admissions=admissions
        )
        assert len(driver.calls) == (1 if case == 'stop-during-read' else 0)
        clock = datetime.now(UTC) + timedelta(days=1)

        def after_grace(_):
            nonlocal clock
            clock += timedelta(minutes=2)
            return clock.isoformat(timespec='milliseconds').replace('+00:00', 'Z')

        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(task_runtime_stop, 'operation_time', after_grace)
            stop_driver = StopDriver(idle_task[4])
            for _ in range(10):
                task_runtime_stop.advance_owned_stops(runtime, stop_driver, cancelled=lambda: False)
                terminal = client.get(path)
                assert terminal.status_code == 200, terminal.text
                if terminal.json()['data']['status'] == 'TERMINATED':
                    break
        view = terminal.json()['data']
        assert view['status'] == 'TERMINATED'
        assert view['runtime']['cleanup_status'] == 'VERIFIED'
        assert view['execution_profile_version_id'] == original['execution_profile_version_id']
        assert (
            client.get(path + f'/operations/{receipt["operation_id"]}').json()['data']['status']
            == 'CANCELLED'
        )
        with database.transaction() as connection:
            assert (
                connection.execute(
                    'SELECT status FROM code_authorizations WHERE id=?', (grant,)
                ).fetchone()[0]
                == 'APPLY_FAILED'
            )
        return
    observed_admissions = (
        (replace(admissions[0], runner_manifest_sha256='b' * 64),)
        if case == 'admission-changed'
        else admissions
    )
    with resources(check_resources(content, available=case != 'withdrawn')):
        assert advance_live_configuration(
            runtime, driver, cancelled=lambda: False, check_admissions=observed_admissions
        )
    if case in ('unknown', 'withdrawn', 'admission-changed'):
        pending = client.get(path)
        assert pending.status_code == 200, pending.text
        assert pending.json()['data']['configuration_application']['status'] == 'UNKNOWN'
        assert (
            pending.json()['data']['execution_profile_version_id']
            == original['execution_profile_version_id']
        )
        driver.unknown = False
        with resources(check_resources(content)):
            assert advance_live_configuration(
                runtime, driver, cancelled=lambda: False, check_admissions=admissions
            )
    with resources(check_resources(content)):
        response = client.get(path)
        assert response.status_code == 200, response.text
        view = response.json()['data']
        assert (view['execution_profile_version_id'], view['authorization_id']) == (profile, grant)
        assert view['current_candidate_id'] == original['current_candidate_id']
        assert view['active_session_id'] == ingress.window.execution_session_id
        assert view['control_generation'] == original['control_generation']
        assert view['status'] == 'VERIFYING'
        assert view['configuration_application']['status'] == 'APPLIED'
        with database.transaction() as connection:
            task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
            version, _, selection, definitions, _ = read_coding_check_selection(
                connection, runtime.catalog, task
            )
            prepared = require_project_check_admissions(
                selection, admissions, definitions=definitions
            )
            assert version == content['check_set_version_id']
            assert prepared[0].timeout_seconds == 17
            instance = connection.execute(
                'SELECT effective_profile_version_id FROM code_instances WHERE id=?',
                (ingress.window.instance_id,),
            ).fetchone()
            assert instance[0] == original['execution_profile_version_id']
    # Retained operation facts stay readable after the live runner is withdrawn.
    with resources(check_resources(content, available=False)):
        response = client.get(path + f'/operations/{receipt["operation_id"]}')
        assert response.status_code == 200, response.text
        assert response.json()['data']['status'] == 'SUCCEEDED'
        assert 'admissions_sha256' not in response.text
        assert 'check_configuration' not in response.text
    replay = client.post(path + '/configuration', json=fixed, headers={'Idempotency-Key': key})
    assert replay.status_code == 202 and replay.json()['data'] == receipt


@pytest.mark.parametrize('mode', ['profile', 'grant-only', 'empty-checks'])
def test_future_output_limit_is_frozen_with_actual_grant_before_adoption(idle_task, mode):  # noqa: F811
    from backend.app.code_tasks.task_configuration_checks import effective_check_output_limit
    from backend.app.shared.validation import strict_json_object

    database, runtime, client, _, _, task_id, _, _, _ = idle_task
    worker = client.app.state.walle_repository_registration
    admissions = (fixture_project_admission(),)
    worker.project_check_admissions = admissions
    path = f'/api/v1/code-tasks/{task_id}'

    def accept(original, profile, grant, content):
        fixed = {
            'expected_state_version': original['state_version'],
            'execution_profile_version_id': profile,
            'authorization_id': grant,
            'reason': '明确调整未来检查输出上限',
        }
        key = str(uuid4())
        with resources(check_resources(content)):
            result = client.post(
                path + '/configuration', json=fixed, headers={'Idempotency-Key': key}
            )
        return result, key, fixed

    if mode != 'empty-checks':
        original, profile, grant, content = prepare_check_pair(idle_task)
        accepted, _, _ = accept(original, profile, grant, content)
        assert accepted.status_code == 202, accepted.text
        with resources(check_resources(content)):
            assert advance_live_configuration(
                runtime,
                ReadOnlyDriver(idle_task),
                cancelled=lambda: False,
                check_admissions=admissions,
            )
    with database.transaction() as connection:
        task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        old_scope = project_grant(
            connection.execute(
                'SELECT * FROM code_authorizations WHERE id=?',
                (task['authorization_id'],),
            ).fetchone()
        )['scope']
    only_grant = mode == 'grant-only'
    selected_limit = (
        max(1, old_scope['limits']['max_check_output_bytes'] // 2) if only_grant else 64
    )
    original, profile, grant, content = prepare_check_pair(
        idle_task,
        preserve_checks=True,
        output_profile=None if only_grant else 128,
        output_grant=selected_limit,
        same_profile=only_grant,
    )
    accepted, key, fixed = accept(original, profile, grant, content)
    if mode == 'empty-checks':
        assert accepted.status_code == 503, accepted.text
        with database.transaction() as connection:
            assert connection.execute(
                'SELECT task_id,status FROM code_authorizations WHERE id=?',
                (grant,),
            ).fetchone()[:] == (None, 'APPROVED_UNBOUND')
        return
    assert accepted.status_code == 202, accepted.text
    receipt = accepted.json()['data']
    with database.transaction() as connection:
        source = strict_json_object(
            connection.execute(
                'SELECT external_identity FROM code_operation_steps WHERE operation_id=? AND step_no=1',
                (receipt['operation_id'],),
            ).fetchone()[0]
        )['source']
        assert source['check_configuration']['max_output_bytes'] == selected_limit
    with resources(check_resources(content)):
        assert advance_live_configuration(
            runtime,
            ReadOnlyDriver(idle_task),
            cancelled=lambda: False,
            check_admissions=(),
        )
        pending = client.get(path)
        assert pending.status_code == 200, pending.text
        assert pending.json()['data']['configuration_application']['status'] == 'UNKNOWN'
        assert pending.json()['data']['authorization_id'] == original['authorization_id']
        assert advance_live_configuration(
            runtime,
            ReadOnlyDriver(idle_task),
            cancelled=lambda: False,
            check_admissions=admissions,
        )
    with resources(check_resources(content, available=False)):
        response = client.get(path + f'/operations/{receipt["operation_id"]}')
        assert response.status_code == 200, response.text
        assert response.json()['data']['status'] == 'SUCCEEDED'
    with database.transaction() as connection:
        task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        chosen = connection.execute(
            'SELECT * FROM code_execution_profile_versions WHERE id=?', (profile,)
        ).fetchone()
        scope = project_grant(
            connection.execute('SELECT * FROM code_authorizations WHERE id=?', (grant,)).fetchone()
        )['scope']
        assert task['execution_profile_version_id'] == profile
        assert task['authorization_id'] == grant
        assert chosen['check_set_version_id'] == content['check_set_version_id']
        assert effective_check_output_limit(chosen, scope) == selected_limit
    replay = client.post(path + '/configuration', json=fixed, headers={'Idempotency-Key': key})
    assert replay.status_code == 202 and replay.json()['data'] == receipt
