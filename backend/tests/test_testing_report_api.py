"""Read and review fixed offline report fixtures through the Testing HTTP boundary."""

from json import dumps
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.code_tasks.operation_protocol import operation_steps
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.service import create_app
from backend.app.shared.command_execution import operation_time
from backend.app.testing.pack_definitions import compiled_definition
from backend.app.testing.plans import _version
from backend.app.testing.validation_evidence import expected_checks
from backend.tests.code_tasks.test_execution_profile_versions import (
    parents,
    publish,
    resources,
    seed_price,
)
from backend.tests.infrastructure.test_v20_check_runner_bundle import bundle  # noqa: F401
from backend.tests.infrastructure.test_v20_command_http import package  # noqa: F401
from backend.tests.test_testing_pack_seal import (
    PACK,
    SEAL,
    installed,  # noqa: F401
    observe,
    opened_pack,
)
from backend.tests.test_testing_policy_api import OPTIONS, create, post, receipt
from backend.tests.test_testing_reference_sets import baseline_fixture
from backend.tests.test_testing_task_api import TASKS, approve

REPORT = '/api/v1/test-reports/1'
FINDINGS = REPORT + '/findings'
REVIEW = '/api/v1/testing-findings/1/review'
VERIFICATION = TASKS + '/1/verifications/1'
FINGERPRINT = '5' * 64


def _save_fixture(connection, snapshot, *, candidate=None):
    # Only persisted inputs to the read APIs are arranged here. No native run is asserted.
    task = connection.execute('SELECT * FROM testing_tasks WHERE id=1').fetchone()
    pack = connection.execute('SELECT * FROM testing_pack_versions WHERE id=1').fetchone()
    _, compiled = compiled_definition(connection, pack)
    scope, checks = expected_checks(compiled)
    at = max(task['created_at'], operation_time(None))
    operation = entity_id(connection, EntityKind.OPERATION_RECORD)
    fixed = canonical_input({'input_fingerprint': FINGERPRINT})
    connection.execute(
        """INSERT INTO code_operations(id,testing_task_id,resource_kind,resource_id,operation_type,
           idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at,started_at,ended_at)
           VALUES(?,1,'TESTING_TASK',1,'RUN_TEST',?,1,?,1,'SUCCEEDED',?,?,?)""",
        (operation, str(uuid4()), fixed, at, at, at),
    )
    connection.executemany(
        """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input,
           result_ref,started_at,ended_at,last_observed_at) VALUES(?,?,?,'SUCCEEDED',?,'{}',?,?,?)""",
        [
            (operation, number, step, fixed, at, at, at)
            for number, step in enumerate(operation_steps('TESTING', 'RUN_TEST'), 1)
        ],
    )
    environment = entity_id(connection, EntityKind.ENVIRONMENT_RECORD)
    connection.execute(
        """INSERT INTO code_environment_records(id,testing_task_id,runtime_refs,dependency_refs,
           runner_refs,testing_profile_version_id,check_resource_refs,scope_key,observed_at)
           VALUES(?,1,'[]','[]','["runner:cli"]',1,'[]',?,?)""",
        (environment, FINGERPRINT, at),
    )
    verification = entity_id(connection, EntityKind.VERIFICATION)
    connection.execute(
        """INSERT INTO code_verifications(id,owner_kind,testing_task_id,snapshot_id,candidate_id,purpose,
           check_set_version_id,testing_profile_version_id,environment_record_id,operation_id,
           scope_stages,selected_check_ids,status,stop_status,cleanup_status,source_integrity_status,
           created_at,ended_at)
           VALUES(?,'TESTING',1,?,?,'DIAGNOSTIC',?,1,?,?,?,?,'FINISHED','VERIFIED','VERIFIED','VERIFIED',?,?)""",
        (
            verification,
            snapshot,
            candidate,
            pack['check_set_version_id'],
            environment,
            operation,
            dumps(scope),
            dumps(list(checks)),
            at,
            at,
        ),
    )
    failed_item = None
    for check, assertions in checks.items():
        item = entity_id(connection, EntityKind.VERIFICATION_ITEM)
        controlled = bool(assertions)
        failure = 'public' in assertions
        counts = (1, 1, int(not failure), int(failure)) if controlled else (None,) * 4
        connection.execute(
            """INSERT INTO code_verification_items(id,verification_id,check_id,required,check_kind,
               evidence_kind,result,expected_case_count,executed_case_count,passed_case_count,
               failed_case_count,started_at,ended_at)
               VALUES(?,?,?,1,'CONTROLLED_ASSERTION',?,?,?,?,?,?,?,?)""",
            (
                item,
                verification,
                check,
                'CONTROLLED_CASES' if controlled else 'CONTENT_INTEGRITY',
                'FAILED' if failure else 'PASSED',
                *counts,
                at,
                at,
            ),
        )
        if controlled:
            command = entity_id(connection, EntityKind.COMMAND_EXECUTION)
            owner = 'fixture:guard-run:' + str(item)
            connection.execute(
                """INSERT INTO code_commands(id,testing_task_id,operation_id,purpose,command_ref,
                   testing_profile_version_id,status,created_at,verification_item_id,process_identity,
                   runtime_binding,exit_code,started_at,ended_at)
                   VALUES(?,1,?,'CHECK','print-result',1,?,?,?,?,?,?,?,?)""",
                (
                    command,
                    operation,
                    'FAILED' if failure else 'SUCCEEDED',
                    at,
                    item,
                    canonical_input({'pid': 4210, 'created_at': at, 'ownership_ref': owner}),
                    canonical_input(
                        {
                            'runtime_policy_version': 'WIN20-TESTING-CHECK-1',
                            'run_kind': 'TASK',
                            'guard_run_ref': owner,
                            'appcontainer_profile_ref': 'fixture:container',
                            'job_refs': ['fixture:job:' + str(item)],
                            'manifest_ref': 'a' * 64,
                        }
                    ),
                    int(failure),
                    at,
                    at,
                ),
            )
            connection.executemany(
                """INSERT INTO code_runtime_observations(id,testing_task_id,command_id,
                   operation_id,control_generation,runtime_binding_ref,kind,result,reason_codes,
                   active_process_count,observed_at,evidence_ref)
                   VALUES(?,1,?,?,1,?,?,'VERIFIED','[]',?,?,?)""",
                [
                    (
                        entity_id(connection, EntityKind.RUNTIME_OBSERVATION),
                        command,
                        operation,
                        owner,
                        kind,
                        active,
                        at,
                        'testing-check:sha256:' + 'f' * 64,
                    )
                    for kind, active in (('PREPARE', None), ('STOP', 0), ('CLEANUP', 0))
                ],
            )
            connection.execute(
                'UPDATE code_verification_items SET command_execution_id=? WHERE id=?',
                (command, item),
            )
        for case, expected in assertions.items():
            outcomes = [
                {
                    'assertion_id': identity,
                    'result': 'FAILED' if failure else 'PASSED',
                    'actual_value': int(failure),
                }
                for identity in sorted(expected)
            ]
            connection.execute(
                """INSERT INTO code_verification_case_results VALUES(?,?,?,?,'REDACTED',?)""",
                (item, case, 'FAILED' if failure else 'PASSED', dumps(outcomes), at),
            )
        if failure:
            failed_item = item
    assert failed_item is not None
    for kind in ('STOP', 'CLEANUP'):
        connection.execute(
            """INSERT INTO code_runtime_observations(id,testing_task_id,operation_id,
               control_generation,kind,result,reason_codes,active_process_count,observed_at,evidence_ref)
               VALUES(?,1,?,1,?,'VERIFIED','[]',0,?,'isolated-proof-fixture')""",
            (entity_id(connection, EntityKind.RUNTIME_OBSERVATION), operation, kind, at),
        )
    connection.execute(
        """INSERT INTO testing_reports(id,testing_task_id,verification_id,plan_version_id,
           test_pack_version_id,input_fingerprint,result,scope_stages,manual_coverage_ids,
           uncovered_behavior_ids,created_at) VALUES(1,1,?,1,1,?,'FAILED',?,'[]','[]',?)""",
        (verification, FINGERPRINT, dumps(scope), at),
    )
    case = next(
        case for pack in compiled.case_packs for case in pack.cases if case.case_id == 'public'
    )
    basis = next(ref for ref in case.basis_refs if ref.document_id == task['document_id'])
    connection.execute(
        """INSERT INTO testing_findings(id,test_report_id,item_id,case_id,actual_behavior,
           expected_behavior,basis_ref,classification,state_version,created_at)
           VALUES(1,1,?,'public','返回非零退出码','按设计退出成功',?,'UNCLASSIFIED',1,?)""",
        (
            failed_item,
            canonical_input(
                {
                    'document_id': basis.document_id,
                    'revision_id': basis.revision_id,
                    'quote': basis.quote,
                }
            ),
            at,
        ),
    )
    connection.execute(
        """INSERT INTO testing_findings(id,test_report_id,actual_behavior,classification,state_version,created_at)
           VALUES(2,1,'环境信息缺失','UNCLASSIFIED',1,?)""",
        (at,),
    )
    connection.execute(
        """UPDATE testing_tasks SET plan_version_id=1,test_pack_version_id=1,current_verification_id=?,
           state_version=2,status='COMPLETED',phase='FINISHED',report_id=1,ended_at=? WHERE id=1""",
        (verification, at),
    )
    return failed_item


def _coding_candidate(database, snapshot, basis):
    from backend.tests.code_tasks.test_authorizations import scope
    from backend.tests.test_testing_cli_run import _candidate_fixture

    at = operation_time(None)
    with database.transaction(write=True) as connection:
        task = entity_id(connection, EntityKind.CODE_TASK)
        grant = entity_id(connection, EntityKind.AUTHORIZATION_GRANT)
        connection.execute(
            """INSERT INTO code_tasks(id,requirement_id,document_id,design_revision_id,
               repository_id,base_snapshot_id,target_branch,execution_profile_version_id,authorization_id,
               budget_limit_cny,status,phase,state_version,control_generation,created_at,updated_at)
               VALUES(?,?,?,?,1,?,'refs/heads/main',1,?,'10.000000','PENDING','PREPARING',1,1,?,?)""",
            (
                task,
                basis['requirement_id'],
                basis['document_id'],
                basis['design_revision_id'],
                snapshot,
                grant,
                at,
                at,
            ),
        )
        connection.execute(
            """INSERT INTO code_authorizations(id,task_id,profile_version_id,scope,status,approved_at,actor_ref)
               VALUES(?,?,1,?,'BOUND_PENDING_APPLY',?,'isolated-owner')""",
            (grant, task, canonical_input(scope()), at),
        )
        connection.executemany(
            'INSERT INTO code_task_materials(task_id,document_id,revision_id) VALUES(?,?,?)',
            [(task, row['document_id'], row['revision_id']) for row in basis['material_refs']],
        )
    candidate, _ = _candidate_fixture(database, task)
    with database.transaction(write=True) as connection:
        connection.execute(
            "UPDATE code_tasks SET status='VERIFYING',phase='BACKEND',current_candidate_id=? WHERE id=?",
            (candidate, task),
        )
    return candidate


@pytest.fixture
def completed_fixture(installed, request, monkeypatch):  # noqa: F811
    database, catalog, _, _ = installed
    app = create_app(database=database, catalog=catalog)
    with TestClient(app) as client:
        parents(client)
        seed_price(database)
        mode = getattr(request, 'param', None)
        if mode == 'candidate-delivery':
            from backend.tests.code_tasks.test_execution_profile_content import body, delivery
            from backend.tests.code_tasks.test_execution_profile_versions import fixture_snapshot

            profile = {**body(), 'delivery': delivery()}
            with resources(fixture_snapshot(profile)):
                result = publish(client, profile)
            assert result.status_code == 201, result.text
        else:
            with resources():
                assert publish(client).status_code == 201
        opened_pack(database, app, client)
        response = post(client, SEAL, {'expected_state_version': 1})
        assert response.status_code == 202, response.text
        assert observe(client, response.json()['data']['operation_id'])['status'] == 'SUCCEEDED'
        with database.transaction(write=True) as connection:
            connection.execute(
                'INSERT INTO code_repositories VALUES(?,?,?,?,?,?)',
                (
                    1,
                    'isolated',
                    'C:/testing-report',
                    'C:/testing-report/.git',
                    'sha1',
                    operation_time(None),
                ),
            )
        snapshot = baseline_fixture(app.state.walle_runtime, 'b' * 40)
        with resources(OPTIONS):
            assert create(client).status_code == 201
        with database.transaction() as connection:
            plan = connection.execute('SELECT * FROM testing_plan_versions WHERE id=1').fetchone()
            basis = {
                key: plan[key] for key in ('requirement_id', 'document_id', 'design_revision_id')
            }
            basis['material_refs'] = _version(connection, 1)['material_refs']
        candidate = None
        if mode in ('candidate', 'candidate-delivery'):
            from backend.app.testing import tasks

            candidate = _coding_candidate(database, snapshot, basis)
            monkeypatch.setattr(tasks, 'saved_candidate', lambda connection, row: (None, row))
            monkeypatch.setattr(tasks, 'candidate_available', lambda row: True)
        response = post(
            client,
            TASKS,
            {
                **basis,
                'target_kind': 'SNAPSHOT' if candidate is None else 'CANDIDATE',
                'candidate_id': candidate,
                'snapshot_id': snapshot if candidate is None else None,
                'purpose': 'DIAGNOSTIC',
                'profile_version_id': 1,
                'authorization_id': approve(client, budget='0'),
                'budget_limit_cny': '0',
                'plan_version_id': None,
                'test_pack_version_id': None,
                'previous_testing_task_id': None,
            },
        )
        assert response.status_code == 201, response.text
        with database.transaction(write=True) as connection:
            item = _save_fixture(
                connection, snapshot if candidate is None else None, candidate=candidate
            )
        yield client, item


def test_report_and_case_reads_preserve_history_after_asset_revocation(completed_fixture):
    client, item = completed_fixture
    result = client.get(REPORT)
    assert result.status_code == 200, result.text
    report = result.json()['data']
    assert client.get(TASKS + '/1/report').json()['data'] == report
    assert report['result'] == 'FAILED' and report['eligible'] is False
    assert report['delivery_eligible'] is False
    assert report['provenance']['snapshot_id'] == 1
    assert report['provenance']['source_code_task_id'] is None
    assert 'NOT_CODING_CANDIDATE' in report['delivery_ineligibility_reason_codes']
    assert 'ACTIVITY_NOT_STOPPED' not in report['ineligibility_reason_codes']

    result = client.get(VERIFICATION)
    assert result.status_code == 200, result.text
    assert result.json()['data']['role'] is None
    assert result.json()['data']['eligible'] is False
    assert client.get(TASKS + '/2/verifications/1').status_code == 404
    assert client.get(TASKS + '/2/report').status_code == 404
    assert client.get(REPORT, params={'task_id': 1}).status_code == 422
    link = '/api/v1/code-tasks/1/test-reports'
    link_key = str(uuid4())
    request = {'expected_state_version': 1, 'candidate_id': 1, 'test_report_id': 1}
    missing = post(client, link, request, link_key)
    assert missing.status_code == 404 and missing.json()['error']['code'] == 'NOT_FOUND'
    replay = client.get(
        '/api/v1/code-command-receipts',
        params={'method': 'POST', 'path': link, 'request_key': link_key},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()['data']['original_outcome']['error'] == missing.json()['error']
    assert post(client, link, request, link_key).json()['error'] == missing.json()['error']
    cases = VERIFICATION + f'/items/{item}/cases'
    result = client.get(cases)
    assert result.status_code == 200, result.text
    assert 'isolated-private-fixture-evidence' not in result.text
    assert result.json()['data']['items'][0]['failed_assertion_count'] == 1
    assert client.get(cases, params={'page': 2}).json()['data']['items'] == []
    assert client.get(VERIFICATION + '/items/999/cases').status_code == 404
    assert client.get(VERIFICATION + '/items/1/cases').status_code == 404

    revoked = post(client, PACK + '/revoke', {'expected_state_version': 2, 'reason': '依据需复审'})
    assert revoked.status_code == 200, revoked.text
    updated = client.get(REPORT).json()['data']
    assert updated['result'] == report['result']
    assert updated['input_fingerprint'] == report['input_fingerprint']
    assert 'TEST_ASSET_REVOKED' in updated['ineligibility_reason_codes']


def test_finding_review_requires_the_real_negative_case_and_keeps_original_receipt(
    completed_fixture,
):
    client, _ = completed_fixture
    assert client.get(FINDINGS, params={'page': 2}).json()['data']['items'] == []
    rows = client.get(FINDINGS).json()['data']['items']
    assert [row['classification'] for row in rows] == ['UNCLASSIFIED', 'UNCLASSIFIED']
    fixed = {
        'expected_state_version': 1,
        'classification': 'PRODUCT',
        'reason': '复核原设计及失败断言',
    }
    no_case = post(client, '/api/v1/testing-findings/2/review', fixed)
    assert no_case.status_code == 409 and no_case.json()['error']['code'] == 'TEST_SOURCE_MISMATCH'
    assert post(client, REVIEW, {**fixed, 'classification': 'UNCLASSIFIED'}).status_code == 422
    key = str(uuid4())
    response = post(client, REVIEW, fixed, key)
    assert response.status_code == 200, response.text
    original = response.json()['data']
    assert original['classification'] == 'PRODUCT' and original['state_version'] == 2
    assert post(client, REVIEW, fixed).json()['error']['code'] == 'VERSION_CONFLICT'
    assert (
        post(
            client, REVIEW, {**fixed, 'expected_state_version': 2, 'classification': 'TEST_DESIGN'}
        ).status_code
        == 200
    )
    assert post(client, REVIEW, fixed, key).json()['data'] == original
    assert receipt(client, REVIEW, key)['original_outcome']['data'] == original
    operation = client.get(f'/api/v1/testing-operations/{original["review_operation_id"]}')
    assert operation.status_code == 200, operation.text
    assert 'actor_ref' not in operation.text
    assert operation.json()['data']['fixed_input'] == fixed
    assert operation.json()['data']['steps'][-1]['result_ref']['classification'] == 'PRODUCT'
    assert client.get(FINDINGS).json()['data']['items'][0]['classification'] == 'TEST_DESIGN'
    assert client.get(REPORT).json()['data']['result'] == 'FAILED'


@pytest.mark.parametrize('completed_fixture', ['candidate'], indirect=True)
def test_import_product_finding_keeps_original_defect_and_is_unique(completed_fixture):
    client, _ = completed_fixture
    path = '/api/v1/code-tasks/1/defects'
    body = {'expected_state_version': 1, 'candidate_id': 1, 'testing_finding_id': 1}
    assert post(client, path, body).json()['error']['code'] == 'TEST_SOURCE_MISMATCH'
    reviewed = post(
        client,
        REVIEW,
        {
            'expected_state_version': 1,
            'classification': 'PRODUCT',
            'reason': '核对原失败用例',
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    key = str(uuid4())
    imported = post(client, path, body, key)
    assert imported.status_code == 201, imported.text
    assert post(client, path, body, key).json()['data'] == imported.json()['data']
    finding = reviewed.json()['data']
    original = client.get(path + '/1')
    assert original.status_code == 200, original.text
    original = original.json()['data']
    assert original['testing_finding_id'] == 1 and original['evidence_refs'] == []
    for field in ('actual_behavior', 'expected_behavior', 'basis_ref'):
        assert original[field] == finding[field]
    assert (
        post(client, path, {**body, 'expected_state_version': 2}).json()['error']['code']
        == 'OPERATION_CONFLICT'
    )
    reclassified = post(
        client,
        REVIEW,
        {
            'expected_state_version': 2,
            'classification': 'TEST_DESIGN',
            'reason': '保留历史归因',
        },
    )
    assert reclassified.status_code == 200
    assert client.get(path + '/1').json()['data'] == original
