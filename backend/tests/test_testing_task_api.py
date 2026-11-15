"""Independent TestingTask HTTP creation, owner-scoped approvals and reads."""

from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep
from uuid import uuid4

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.shared.command_execution import operation_time
from backend.app.testing import task_stop
from backend.tests.code_tasks.test_execution_profile_versions import resources
from backend.tests.code_tasks.test_repository_baseline_acceptance import repository_service  # noqa: F401
from backend.tests.infrastructure.test_v20_command_http import package, service  # noqa: F401
from backend.tests.test_testing_plan_api import setup
from backend.tests.test_testing_policy_api import AUTH, OPTIONS, create, post, receipt
from backend.tests.test_testing_reference_sets import baseline_fixture

TASKS = '/api/v1/testing-tasks'


def approve(client, *, budget='1.5', scope='TASK'):
    with resources(OPTIONS):
        result = post(
            client,
            AUTH,
            {'profile_version_id': 1, 'scope_kind': scope, 'budget_limit_cny': budget},
        )
    assert result.status_code == 201, result.text
    return result.json()['data']['id']


def draft_fixture(repo):
    database, runtime, client = repo
    basis = setup((database, client.app, client))
    snapshot = baseline_fixture(runtime, 'a' * 40)
    with resources(OPTIONS):
        assert create(client).status_code == 201
    return {
        **{
            key: basis[key]
            for key in ('requirement_id', 'document_id', 'design_revision_id', 'material_refs')
        },
        'target_kind': 'SNAPSHOT',
        'candidate_id': None,
        'snapshot_id': snapshot,
        'purpose': 'DIAGNOSTIC',
        'profile_version_id': 1,
        'authorization_id': approve(client),
        'budget_limit_cny': '1.25',
        'plan_version_id': None,
        'test_pack_version_id': None,
        'previous_testing_task_id': None,
    }


def test_fixed_task_binds_only_its_own_approval_and_replays_original(repository_service):  # noqa: F811
    database, _, client = repository_service
    draft = draft_fixture(repository_service)
    key = str(uuid4())
    created = post(client, TASKS, draft, key)
    assert created.status_code == 201, created.text
    assert created.json()['data'] == {'testing_task_id': 1, 'state_version': 1}
    original = receipt(client, TASKS, key)
    assert original['original_outcome']['data'] == created.json()['data']
    assert (original['task_id'], original['testing_task_id'], original['operation_id']) == (
        None,
        1,
        None,
    )
    assert (
        post(client, TASKS, {**draft, 'budget_limit_cny': '1.250000'}, key).json()['data']
        == created.json()['data']
    )
    repeated = post(client, TASKS, draft)
    assert (
        repeated.status_code == 403
        and repeated.json()['error']['code'] == 'AUTHORIZATION_NOT_APPLICABLE'
    )

    read = client.get(TASKS + '/1')
    assert read.status_code == 200, read.text
    task = read.json()['data']
    assert task['kind'] == 'PRODUCT' and task['status'] == 'DRAFT' and task['phase'] == 'PLAN'
    assert task['material_refs'] == draft['material_refs'] and task['snapshot_id'] == 1
    assert (
        task['runtime']['observed_at'] is None
        and task['runtime']['activity_status'] == 'NOT_STARTED'
    )
    assert task['draft_plan_result'] is None and task['termination_operation_id'] is None
    assert task['budget'] == {
        'budget_limit_cny': '1.250000',
        'settled_cny': '0.000000',
        'reserved_cny': '0.000000',
        'available_cny': '1.250000',
        'model_request_count': 0,
        'request_limit': 1,
    }
    assert {'action': 'RUN_TEST', 'enabled': False, 'reason_code': 'ASSET_NOT_READY'} in task[
        'available_actions'
    ]
    with resources(OPTIONS):
        auth = client.get(AUTH + '/1').json()['data']
    assert auth['testing_task_id'] == 1 and auth['status'] == 'EFFECTIVE'
    listed = client.get(
        TASKS, params={'snapshot_id': 1, 'purpose': 'DIAGNOSTIC', 'status': 'DRAFT'}
    ).json()
    assert [row['id'] for row in listed['data']['items']] == [1]
    assert client.get(TASKS, params={'candidate_id': 1}).json()['data']['items'] == []
    assert client.get(TASKS, params={'page': 2}).json()['data']['items'] == []
    assert client.get(TASKS, params={'task_id': 1}).status_code == 422
    assert client.get('/api/v1/code-tasks/1').status_code == 404
    assert client.get(TASKS + '/999').status_code == 404
    with database.transaction() as connection:
        for table in ('code_tasks', 'code_verifications', 'llm_uses', 'testing_reports'):
            assert connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0


def test_creation_checks_fixed_revision_scope_and_budget_before_consuming_approval(
    repository_service,  # noqa: F811
):
    _, _, client = repository_service
    draft = draft_fixture(repository_service)
    assert post(client, TASKS, {**draft, 'kind': 'PACK_VALIDATION'}).status_code == 422
    assert post(client, TASKS, {**draft, 'snapshot_id': None}).status_code == 422
    assert post(client, TASKS, {**draft, 'plan_version_id': 1}).status_code == 422
    assert post(client, TASKS, {**draft, 'snapshot_id': 999}).status_code == 404
    assert post(client, TASKS, {**draft, 'budget_limit_cny': '1.500001'}).status_code == 403
    assert (
        post(client, TASKS, {**draft, 'requirement_id': 999}).json()['error']['code']
        == 'BASIS_REF_INVALID'
    )
    group = approve(client, budget='0', scope='PACK_VALIDATION')
    assert (
        post(
            client, TASKS, {**draft, 'authorization_id': group, 'budget_limit_cny': '0'}
        ).status_code
        == 403
    )
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: post(client, TASKS, draft), range(3)))
    assert sorted(result.status_code for result in results) == [201, 403, 403]
    repeated = post(
        client,
        TASKS,
        {
            **draft,
            'authorization_id': approve(client, budget='0'),
            'budget_limit_cny': '0',
            'previous_testing_task_id': 1,
        },
    )
    assert repeated.status_code == 201, repeated.text
    assert client.get(TASKS + '/2').json()['data']['previous_testing_task_id'] == 1


def test_budget_changes_only_original_testing_grant_and_replays_after_stop(repository_service):  # noqa: F811
    _, _, client = repository_service
    draft = draft_fixture(repository_service)
    assert post(client, TASKS, draft).status_code == 201
    path = TASKS + '/1/budget'
    grant = approve(client, budget='2')
    body = {'expected_state_version': 1, 'new_budget_limit_cny': '2', 'authorization_id': grant}
    assert (
        post(client, path, {**body, 'expected_state_version': 2}).json()['error']['code']
        == 'VERSION_CONFLICT'
    )
    assert (
        post(client, path, {**body, 'new_budget_limit_cny': '1.25'}).json()['error']['code']
        == 'BUDGET_NOT_INCREASED'
    )
    assert post(client, path, {**body, 'new_budget_limit_cny': '2.1'}).status_code == 403
    key = str(uuid4())
    saved = post(client, path, body, key)
    assert saved.status_code == 200, saved.text
    task = saved.json()['data']
    assert (task['state_version'], task['status'], task['authorization_id']) == (2, 'DRAFT', grant)
    assert task['budget']['available_cny'] == '2.000000'
    assert receipt(client, path, key)['testing_task_id'] == 1
    with resources(OPTIONS):
        assert client.get(AUTH + '/1').json()['data']['status'] == 'RETIRED'
        assert client.get(AUTH + '/' + str(grant)).json()['data']['status'] == 'EFFECTIVE'
    attached = post(
        client,
        TASKS + '/1/assets',
        {'expected_state_version': 2, 'plan_version_id': 1, 'test_pack_version_id': 2},
    )
    assert attached.status_code == 404
    stopped = post(client, TASKS + '/1/terminate', {'expected_state_version': 2})
    assert stopped.status_code == 202, stopped.text
    assert wait_task(client, 'TERMINATED')['state_version'] == 4
    assert post(client, path, body, key).json()['data'] == task
    assert receipt(client, path, key)['original_outcome']['data'] == task
    assert (
        post(client, path, {**body, 'expected_state_version': 4}).json()['error']['code']
        == 'TASK_ENDED'
    )


def wait_task(client, status, *, stop_status=None):
    deadline = monotonic() + 9
    while monotonic() < deadline:
        result = client.get(TASKS + '/1')
        assert result.status_code == 200, result.text
        row = result.json()['data']
        if row['status'] == status and (
            stop_status is None or row['runtime']['stop_status'] == stop_status
        ):
            return row
        sleep(0.05)
    raise AssertionError(row)


def test_testing_stop_has_one_fence_across_keys_and_proves_empty_only_for_owner(
    repository_service,  # noqa: F811
    monkeypatch,
):
    database, _, client = repository_service
    assert post(client, TASKS, draft_fixture(repository_service)).status_code == 201
    path = TASKS + '/1/terminate'
    key, alias = (str(uuid4()) for _ in range(2))

    def deferred(*args):
        raise StorageUnavailable('isolated test pauses original verification')

    with monkeypatch.context() as patch:
        patch.setattr(task_stop, '_empty_scope', deferred)
        first = post(client, path, {'expected_state_version': 1}, key)
        assert first.status_code == 202, first.text
        before = wait_task(client, 'STOPPING')
        assert (
            before['control_generation'] == 2 and before['runtime']['active_process_count'] is None
        )
        again = post(client, path, {'expected_state_version': 2}, alias)
        assert again.status_code == 202, again.text
        assert again.json()['data'] == first.json()['data']
    finished = wait_task(client, 'TERMINATED')
    assert finished['phase'] == 'FINISHED'
    assert finished['runtime']['stop_status'] == finished['runtime']['cleanup_status'] == 'VERIFIED'
    assert finished['runtime']['activity_status'] == 'NOT_STARTED'
    assert finished['runtime']['active_process_count'] == 0
    operation_id = first.json()['data']['operation_id']
    owned = client.get(TASKS + f'/1/operations/{operation_id}')
    assert owned.status_code == 200, owned.text
    fact = owned.json()['data']
    assert fact['id'] == operation_id and fact['testing_task_id'] == 1
    assert fact['fixed_input'] == {'expected_state_version': 1}
    assert fact['steps'][1]['result_ref'] == {'stop_observation_id': 1, 'cleanup_observation_id': 2}
    assert 'owned_records' not in owned.text and 'evidence_ref' not in owned.text
    assert client.get(f'/api/v1/testing-operations/{operation_id}').json()['data'] == fact
    assert client.get(TASKS + f'/2/operations/{operation_id}').status_code == 404
    assert client.get(TASKS + '/1/operations').json()['data']['items'] == [fact]
    terminal_key = str(uuid4())
    terminal = post(client, path, {'expected_state_version': 1}, terminal_key)
    assert terminal.status_code == 200, terminal.text
    assert terminal.json()['data'] == finished
    assert receipt(client, path, terminal_key)['testing_task_id'] == 1
    for original in (key, alias):
        read = receipt(client, path, original)
        assert read['operation_id'] == first.json()['data']['operation_id']
        assert read['original_http_status'] == 202
    with database.transaction() as connection:
        scope = connection.execute(
            'SELECT testing_task_id,task_id,kind,result,active_process_count FROM code_runtime_observations ORDER BY id'
        ).fetchall()
        assert [tuple(row) for row in scope] == [
            (1, None, 'STOP', 'VERIFIED', 0),
            (1, None, 'CLEANUP', 'VERIFIED', 0),
        ]
        assert connection.execute('SELECT count(*) FROM code_commands').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM testing_reports').fetchone()[0] == 0


def test_unknown_prior_testing_dispatch_remains_fenced_and_never_proves_empty(repository_service):  # noqa: F811
    database, _, client = repository_service
    assert post(client, TASKS, draft_fixture(repository_service)).status_code == 201
    with database.transaction(write=True) as connection:
        operation = entity_id(connection, EntityKind.OPERATION_RECORD)
        at = operation_time(None)
        connection.execute(
            """INSERT INTO code_operations(id,testing_task_id,resource_kind,resource_id,operation_type,
                idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at,started_at)
                VALUES(?,1,'TESTING_TASK',1,'DRAFT_PLAN',?,1,?,1,'UNKNOWN',?,?)""",
            (operation, str(uuid4()), canonical_input({'expected_state_version': 1}), at, at),
        )
        connection.execute(
            """UPDATE testing_tasks SET status='WAITING',state_version=2,active_operation_id=?,
               draft_plan_operation_id=? WHERE id=1""",
            (operation, operation),
        )
        connection.executemany(
            """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input)
               VALUES(?,?,?,'PENDING',?)""",
            [
                (operation, i, step, canonical_input({'expected_state_version': 1}))
                for i, step in enumerate(
                    ('BUILD_CONTEXT', 'RESERVE', 'CALL_MODEL', 'SAVE_DRAFT'), 1
                )
            ],
        )
    result = post(client, TASKS + '/1/terminate', {'expected_state_version': 2})
    assert result.status_code == 202, result.text
    row = wait_task(client, 'STOPPING', stop_status='UNKNOWN')
    assert row['runtime']['active_process_count'] is None and row['stopped_at'] is None
    with database.transaction() as connection:
        assert (
            connection.execute('SELECT count(*) FROM code_runtime_observations').fetchone()[0] == 0
        )


def test_testing_model_audit_reads_exact_original_owner_and_usage_without_provider(
    repository_service,  # noqa: F811
):
    database, _, client = repository_service
    draft = draft_fixture(repository_service)
    assert post(client, TASKS, draft).status_code == 201
    assert post(client, TASKS, {**draft, 'authorization_id': approve(client)}).status_code == 201
    path = TASKS + '/1/model-calls'
    assert client.get(path).json()['data']['items'] == []

    with database.transaction(write=True) as connection:
        at = operation_time(None)
        for number, final in enumerate((True, False), 1):
            operation = entity_id(connection, EntityKind.OPERATION_RECORD)
            use = entity_id(connection, EntityKind.LLM_USE)
            reserve = entity_id(connection, EntityKind.CODE_TASK_RESERVATION)
            connection.execute(
                """INSERT INTO code_operations(id,testing_task_id,resource_kind,resource_id,operation_type,
                   idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at,started_at,ended_at)
                   VALUES(?,1,'TESTING_TASK',1,'DRAFT_PLAN',?,1,'{}',1,?,?,?,?)""",
                (
                    operation,
                    str(uuid4()),
                    'FAILED' if final else 'RUNNING',
                    at,
                    at,
                    at if final else None,
                ),
            )
            connection.execute(
                """INSERT INTO llm_uses(id,testing_task_id,operation_id,call_no,attempt_no,
                   provider,model_name,function_type,prompt_config,request_snapshot_json,
                   input_summary,context_manifest_json,raw_response_json,parse_status,validation_status,
                   call_status,input_tokens,output_tokens,provider_request_id,started_at,ended_at,
                   cost,cost_currency,protocol_version,call_purpose,transport_status,usage_status,
                   capture_status,source_evidence_ref)
                   VALUES(?,1,?,?,1,'fixture','fixed-model','TEST_PLAN_DRAFT','fixture',
                     '{"api_key":"isolated-secret","request":{"model":"fixed-model"}}',
                     'fixture','{}',?,?,'PENDING',?,?,?,?,?,?,?,?,'TEST20-PLAN-1','TEST_DESIGN',
                     ?,?,'REDACTED','isolated-evidence')""",
                (
                    use,
                    operation,
                    number,
                    '{"fixture":"failed parsing"}' if final else None,
                    'FAILED' if final else 'PENDING',
                    'FAILED' if final else 'RUNNING',
                    0,
                    0 if final else None,
                    ' opaque-id ' if final else None,
                    at,
                    at if final else None,
                    '0.000000' if final else None,
                    'CNY' if final else None,
                    'COMPLETE' if final else 'SENT',
                    'FINAL' if final else 'PARTIAL',
                ),
            )
            connection.execute(
                """INSERT INTO code_task_reservations(id,testing_task_id,llm_use_id,price_version_id,
                   reserved_cny,status,created_at,settled_cny,settled_at,settlement_basis)
                   VALUES(?,1,?,1,'0.125000',?,?,?,?,?)""",
                (
                    reserve,
                    use,
                    'SETTLED' if final else 'RESERVED',
                    at,
                    '0.000000' if final else None,
                    at if final else None,
                    'VERIFIED_USAGE' if final else None,
                ),
            )
    listing = client.get(path)
    assert listing.status_code == 200, listing.text
    rows = listing.json()['data']['items']
    assert [row['usage_status'] for row in rows] == ['FINAL', 'PARTIAL']
    assert rows[0]['input_tokens'] == rows[0]['output_tokens'] == 0
    assert rows[1]['output_tokens'] is None
    assert rows[0]['provider_request_id'] == ' opaque-id '
    assert 'request_snapshot' not in rows[0]
    first = client.get(path + '/1')
    assert first.status_code == 200, first.text
    settled = first.json()['data']
    assert 'isolated-secret' not in first.text
    assert settled['request_snapshot'] == {'request': {'model': 'fixed-model'}}
    assert settled['response_snapshot'] == {'fixture': 'failed parsing'}
    assert settled['reserved_cny'] == '0.125000' and settled['settled_cny'] == '0.000000'
    assert settled['parsed_output'] is None and settled['trusted_output'] is None
    second = client.get(path + '/2')
    assert second.status_code == 200, second.text
    assert second.json()['data']['settled_cny'] is None
    assert second.json()['data']['response_snapshot'] is None
    assert client.get(path, params={'page': 2}).json()['data']['items'] == []
    assert client.get(path, params={'page_size': 20}).status_code == 422
    assert client.get(TASKS + '/2/model-calls').json()['data']['items'] == []
    assert client.get(TASKS + '/2/model-calls/1').status_code == 404
    assert client.get('/api/v1/code-tasks/1/model-calls/1').status_code == 404


def test_run_intent_rejects_unprepared_or_stopped_task_without_an_execution(
    repository_service,  # noqa: F811
):
    database, _, client = repository_service
    assert post(client, TASKS, draft_fixture(repository_service)).status_code == 201
    run = TASKS + '/1/run'
    assert post(client, run, {'expected_state_version': 1, 'scope_stages': []}).status_code == 422
    assert post(client, TASKS + '/99/run', {'expected_state_version': 1}).status_code == 404
    assert (
        post(client, run, {'expected_state_version': 2}).json()['error']['code']
        == 'VERSION_CONFLICT'
    )
    key = str(uuid4())
    before = client.get(TASKS + '/1').json()['data']
    blocked = post(client, run, {'expected_state_version': 1}, key)
    assert blocked.status_code == 409 and blocked.json()['error']['code'] == 'INVALID_STATE'
    assert receipt(client, run, key)['original_outcome']['error'] == blocked.json()['error']
    assert client.get(TASKS + '/1').json()['data'] == before
    stop = post(client, TASKS + '/1/terminate', {'expected_state_version': 1})
    assert stop.status_code == 202
    current = wait_task(client, 'TERMINATED')
    assert (
        post(client, run, {'expected_state_version': current['state_version']}).json()['error'][
            'code'
        ]
        == 'TASK_ENDED'
    )
    assert (
        post(client, run, {'expected_state_version': 1}, key).json()['error']
        == blocked.json()['error']
    )
    with database.transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM code_operations WHERE operation_type='RUN_TEST'"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute('SELECT count(*) FROM code_verifications').fetchone()[0] == 0
