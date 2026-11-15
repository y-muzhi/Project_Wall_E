"""A published native Coding candidate must reject an existing failed Testing report.

The report execution facts are an explicit negative fixture, never native PASS
evidence. Candidate custody and Coding publication come from the original Guard.
"""

from hashlib import sha256
from uuid import uuid4

from backend.app.infrastructure.check_runner_bundle import RegisteredCheckRunner
from backend.app.infrastructure.windows_private_package import PrivatePackageGuard
from backend.app.testing.pack_seal import advance_pending_pack_seals
from backend.app.testing.plan_api import TEST_PLAN_ROUTER
from backend.app.testing.policy_api import testing_policy_router
from backend.tests.code_tasks.test_execution_profile_versions import resources
from backend.tests.test_testing_cli_run import _assets, _registered_cli, _sealed_pack
from backend.tests.test_testing_pack_seal import observe
from backend.tests.test_testing_policy_api import create, post
from backend.tests.test_testing_report_api import _save_fixture
from backend.tests.test_testing_task_api import approve


def exercise_failed_report_link(runtime, client, path, root):
    before = client.get(path).json()['data']
    assert (before['status'], before['phase']) == ('AWAITING_TESTING', 'TESTING')
    with runtime.database.transaction() as connection:
        task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (before['id'],)).fetchone()
        assert connection.execute('SELECT count(*) FROM testing_tasks').fetchone()[0] == 0
        basis = {key: task[key] for key in ('requirement_id', 'document_id', 'design_revision_id')}
        basis['material_refs'] = [
            dict(row)
            for row in connection.execute(
                'SELECT document_id,revision_id FROM code_task_materials WHERE task_id=? ORDER BY document_id',
                (task['id'],),
            )
        ]
    client.app.include_router(testing_policy_router)
    client.app.include_router(TEST_PLAN_ROUTER)
    with PrivatePackageGuard(root / 'registered-runner') as directory:
        runner = RegisteredCheckRunner(
            directory.verify(),
            sha256((directory.path / 'manifest.json').read_bytes()).hexdigest(),
            'native-check-runner',
            '1.0.0',
        )
    runtime.catalog.testing_assets = _assets(root, runner)
    _, profile, options = _registered_cli(runner)
    with resources(options):
        made = create(client, profile)
    assert made.status_code == 201, made.text

    # Seal is actual product compilation. Validation/execution are deliberately
    # absent for this failed report fixture; they must never grant acceptance.
    from unittest.mock import patch
    from backend.tests import test_testing_cli_run

    def observe_after_compile(client, identity):
        assert advance_pending_pack_seals(runtime, lambda: False)
        return observe(client, identity)

    with patch.object(test_testing_cli_run, 'observe', observe_after_compile):
        _sealed_pack(runtime.database, client, basis, publish=False)

    created = post(
        client,
        '/api/v1/testing-tasks',
        {
            **basis,
            'target_kind': 'CANDIDATE',
            'candidate_id': before['current_candidate_id'],
            'snapshot_id': None,
            'purpose': 'DIAGNOSTIC',
            'profile_version_id': 1,
            'authorization_id': approve(client, budget='0'),
            'budget_limit_cny': '0',
            'plan_version_id': None,
            'test_pack_version_id': None,
            'previous_testing_task_id': None,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()['data']['testing_task_id'] == 1
    with runtime.database.transaction(write=True) as connection:
        _save_fixture(connection, None, candidate=before['current_candidate_id'])
    report = client.get('/api/v1/test-reports/1')
    assert report.status_code == 200, report.text
    row = report.json()['data']
    assert row['result'] == 'FAILED' and not row['delivery_eligible']
    assert row['provenance']['candidate_id'] == before['current_candidate_id']
    request = {
        'expected_state_version': before['state_version'],
        'candidate_id': before['current_candidate_id'],
        'test_report_id': row['id'],
    }
    key = str(uuid4())
    result = post(client, path + '/test-reports', request, key)
    assert result.status_code == 409, result.text
    assert result.json()['error']['code'] == 'TEST_REPORT_NOT_ELIGIBLE'
    replay = post(client, path + '/test-reports', request, key)
    assert replay.status_code == 409 and replay.json()['error'] == result.json()['error']
    after = client.get(path).json()['data']
    assert after['state_version'] == before['state_version']
    assert (after['status'], after['phase']) == ('AWAITING_TESTING', 'TESTING')
    assert after['current_refs']['test_report_id'] is None
    assert after['current_refs']['delivery_plan_id'] is None
    with runtime.database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_acceptances').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM code_deliveries').fetchone()[0] == 0
    print('NATIVE_CODING_EXISTING_FAILED_REPORT_REJECTED_WITHOUT_STATE_CHANGE', flush=True)
