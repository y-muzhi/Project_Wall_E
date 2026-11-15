"""Exercise C39 on an original sealed candidate without native write replay."""

import json
from unittest.mock import patch
from uuid import uuid4

from backend.app.code_tasks.authorizations import project_grant
from backend.app.code_tasks.execution_profile_content import FIELDS
from backend.app.code_tasks.execution_profile_resources import RESOURCE_KINDS
from backend.app.code_tasks.task_initial_configuration import InitialConfigurationObservation
from backend.app.code_tasks.task_instance_driver import ControlConfigurationObservation
from backend.app.code_tasks.task_live_configuration import advance_live_configuration
from backend.app.code_tasks.task_start_session import original_active_session_scope
from backend.app.shared.validation import strict_json_object
from backend.tests.code_tasks.test_authorizations import approve
from backend.tests.code_tasks.test_execution_profile_versions import (
    fixture_snapshot,
    publish,
    resources,
)


def exercise_live_control_configuration(
    runtime,
    client,
    path,
    capture_driver,
    *,
    check_worker=None,
    check_set=False,
    output_limit=None,
    expect_output_limit=False,
    model_refs=None,
):
    database = runtime.database
    with database.transaction() as connection:
        original = connection.execute(
            'SELECT * FROM code_tasks WHERE id=?', (int(path.rsplit('/', 1)[-1]),)
        ).fetchone()
        row = connection.execute(
            'SELECT * FROM code_execution_profile_versions WHERE id=?',
            (original['execution_profile_version_id'],),
        ).fetchone()
        profile = {
            key: row[key]
            if key == 'check_set_version_id' or row[key] is None
            else json.loads(row[key])
            for key in FIELDS
        }
        grant = project_grant(
            connection.execute(
                'SELECT * FROM code_authorizations WHERE id=?', (original['authorization_id'],)
            ).fetchone()
        )
        source = connection.execute(
            'SELECT * FROM code_sessions WHERE id=?', (original['active_session_id'],)
        ).fetchone()
        instance = connection.execute(
            'SELECT * FROM code_instances WHERE id=?', (source['instance_id'],)
        ).fetchone()
        binding = strict_json_object(instance['runtime_binding'])
    configuration_resources = (
        {
            kind: runtime.catalog.code_configuration_options(kind)
            for kind in (*RESOURCE_KINDS, 'RUNNER', 'CASE_PACK')
        }
        if check_set or output_limit is not None
        else fixture_snapshot(profile)
    )
    if check_set:
        with database.transaction() as connection:
            previous_checks = connection.execute(
                'SELECT * FROM code_check_set_versions WHERE id=?',
                (profile['check_set_version_id'],),
            ).fetchone()
        check_input = {
            'protocol_version': previous_checks['protocol_version'],
            'items': json.loads(previous_checks['items']),
            'coverage_plan': json.loads(previous_checks['coverage_plan']),
        }
        for item in check_input['items']:
            item['timeout_seconds'] = max(1, item['timeout_seconds'] - 1)
        with resources(configuration_resources):
            changed_checks = client.post(
                f'/api/v1/code-check-sets/{previous_checks["check_set_id"]}/versions',
                json=check_input,
                headers={'Idempotency-Key': str(uuid4())},
            )
        assert changed_checks.status_code == 201, changed_checks.text
        profile['check_set_version_id'] = changed_checks.json()['data']['resource_id']
    profile['limits']['query_timeout_seconds'] += 1
    scope = grant['scope']
    if model_refs is not None:
        scope['model_profile_refs'] = list(model_refs)
    if output_limit is not None:
        profile['limits']['max_check_output_bytes'] = 128
        scope['limits']['max_check_output_bytes'] = output_limit
    scope['limits']['query_timeout_seconds'] = profile['limits']['query_timeout_seconds']
    with resources(configuration_resources):
        response = publish(client, profile)
        assert response.status_code == 201, response.text
        profile_id = response.json()['data']['resource_id']
        response = approve(client, {'profile_version_id': profile_id, 'scope': scope})
        assert response.status_code == 201, response.text
        grant_id = response.json()['data']['resource_id']
    fixed = {
        'expected_state_version': original['state_version'],
        'execution_profile_version_id': profile_id,
        'authorization_id': grant_id,
        'reason': '原候选形成后明确更新查询控制限制',
    }
    key = str(uuid4())
    registration = getattr(client.app.state, 'walle_repository_registration', None)
    assert registration is not None

    class OriginalControlReads:
        reads = 0

        def observe_control_configuration(self, native_scope, window, credential_ref, checkpoint):
            self.reads += 1
            if self.reads == 2:
                with database.transaction() as connection:
                    retained_steps = connection.execute(
                        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
                        (receipt['operation_id'],),
                    ).fetchall()
                assert [step['status'] for step in retained_steps] == [
                    'SUCCEEDED',
                    'SUCCEEDED',
                    'RUNNING',
                    'PENDING',
                ]
                application_scope = strict_json_object(retained_steps[2]['external_identity'])
                assert application_scope['mode'] == 'CONTROL_ONLY'
                assert len(application_scope['nonce']) == 32
            if self.reads == 3:
                with database.transaction() as connection:
                    retained_states = [
                        row['status']
                        for row in connection.execute(
                            'SELECT status FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
                            (receipt['operation_id'],),
                        )
                    ]
                assert retained_states == ['SUCCEEDED', 'SUCCEEDED', 'SUCCEEDED', 'RUNNING']
            assert native_scope.profile_id == instance['effective_profile_version_id']
            assert window.execution_session_id == source['id']
            assert credential_ref == source['gateway_credential_ref']
            checkpoint()
            quiet = capture_driver.observe_capture_turn(
                native_scope, window, credential_ref, checkpoint
            )
            return ControlConfigurationObservation(
                quiet,
                InitialConfigurationObservation(
                    profile['executor']['runtime_bundle_ref'],
                    binding['manifest_ref'],
                    'f' * 64,
                    'test-agent',
                ),
                'e' * 64,
            )

    driver = OriginalControlReads()
    with patch.object(registration, 'accepts_live_configuration', True, create=True):
        with resources(configuration_resources):
            accepted = client.post(
                path + '/configuration', json=fixed, headers={'Idempotency-Key': key}
            )
        assert accepted.status_code == 202, accepted.text
        receipt = accepted.json()['data']
        assert receipt['task_status'] == 'WAITING'
        before = client.get(path)
        assert before.status_code == 200, before.text
        assert (
            before.json()['data']['execution_profile_version_id']
            == original['execution_profile_version_id']
        )
        assert advance_live_configuration(
            runtime,
            driver,
            cancelled=lambda: False,
            check_admissions=getattr(registration, 'project_check_admissions', ()),
        )
        current = client.get(path)
        assert current.status_code == 200, current.text
        view = current.json()['data']
        assert (
            view['execution_profile_version_id'] == profile_id
            and view['authorization_id'] == grant_id
        )
        assert view['configuration_application']['status'] == 'APPLIED'
        assert view['current_candidate_id'] == original['current_candidate_id']
        assert (
            view['active_session_id'] == source['id']
            and view['control_generation'] == original['control_generation']
        )
        assert driver.reads == 3
        assert (
            client.post(
                path + '/configuration', json=fixed, headers={'Idempotency-Key': key}
            ).json()['data']
            == receipt
        )
    with database.transaction() as connection:
        task = connection.execute(
            'SELECT * FROM code_tasks WHERE id=?', (original['id'],)
        ).fetchone()
        active = connection.execute(
            'SELECT * FROM code_sessions WHERE id=?', (source['id'],)
        ).fetchone()
        owner = original_active_session_scope(connection, task, active)
        assert (
            owner.profile_id == instance['effective_profile_version_id']
            and owner.authorization_id == grant_id
        )
        assert (
            connection.execute(
                'SELECT effective_profile_version_id FROM code_instances WHERE id=?',
                (instance['id'],),
            ).fetchone()[0]
            == instance['effective_profile_version_id']
        )
        assert strict_json_object(active['model_window'])['state'] == 'CLOSED'
    if check_set and original['current_verification_id'] is not None:
        previous = client.get(path + f'/verifications/{original["current_verification_id"]}')
        assert previous.status_code == 200, previous.text
        assert previous.json()['data']['eligible'] is False
        assert 'CONFIGURATION_MISMATCH' in previous.json()['data']['ineligibility_reason_codes']
    if check_worker is not None:
        response = client.post(
            path + f'/candidates/{original["current_candidate_id"]}/verifications',
            json={'expected_state_version': view['state_version'], 'purpose': 'HANDOFF'},
            headers={'Idempotency-Key': str(uuid4())},
        )
        assert response.status_code == 202, response.text
        operation = response.json()['data']['operation_id']
        for _ in range(12):
            check_worker.advance()
            observed = client.get(path + f'/operations/{operation}')
            assert observed.status_code == 200, observed.text
            if observed.json()['data']['status'] not in ('PENDING', 'RUNNING'):
                break
        assert observed.json()['data']['status'] == 'SUCCEEDED', observed.text
        with database.transaction() as connection:
            check = connection.execute(
                'SELECT * FROM code_verifications WHERE operation_id=?', (operation,)
            ).fetchone()
            assert check['profile_version_id'] == profile_id
            assert check['check_set_version_id'] == profile['check_set_version_id']
            if output_limit is not None:
                from backend.app.code_tasks.coding_project_check_scope import check_claims

                frozen = connection.execute(
                    "SELECT external_identity FROM code_operation_steps WHERE operation_id=? AND step_type='CHECK'",
                    (operation,),
                ).fetchone()[0]
                assert {claim.max_output_bytes for claim in check_claims(frozen)} == {output_limit}
            environment = connection.execute(
                'SELECT effective_config_application_id FROM code_environment_records WHERE id=?',
                (check['environment_record_id'],),
            ).fetchone()
            assert (
                environment['effective_config_application_id']
                == view['configuration_application']['id']
            )
        if expect_output_limit:
            result = client.get(path + f'/verifications/{check["id"]}')
            assert result.status_code == 200, result.text
            verification = result.json()['data']
            assert verification['eligible'] is False
            assert 'REQUIRED_NOT_PASSED' in verification['ineligibility_reason_codes']
            failed = [
                item for item in verification['items'] if item['evidence_kind'] == 'PROCESS_EXIT'
            ]
            assert failed and all(
                item['result'] == 'FAILED' and item['reason_code'] == 'OUTPUT_LIMIT'
                for item in failed
            )
            assert (
                client.get(path).json()['data']['current_candidate_id']
                == original['current_candidate_id']
            )
    return profile_id, grant_id
