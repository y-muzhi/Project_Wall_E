"""Original Testing CLI transaction coverage, separate from the Windows Guard fixture."""

from dataclasses import asdict, replace
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.infrastructure.check_runner_bundle import RegisteredCheckRunner
from backend.app.infrastructure.content_manifest import CONTENT_POLICY
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.guard_controller_binding import bind_backend_controller
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.infrastructure.windows_project_check_command import ProjectCheckCommand
from backend.app.service import create_app
from backend.app.shared.command_execution import operation_time
from backend.app.testing import task_run, tasks
from backend.app.testing.asset_installation import (
    InstalledTarget,
    TestingAssetInstallation as AssetInstallation,
)
from backend.app.testing.cli_plan import (
    BrowserServiceAdmission,
    TestingBrowserAdmission as BrowserAdmission,
)
from backend.app.testing.cli_plan import TestingCliAdmission as CliAdmission
from backend.app.testing.cli_plan import TestingCliRuntime as CliRuntime
from backend.app.testing.pack_compile import basis_fingerprint, digest, encoded
from backend.app.testing.plans import _version
from backend.app.testing.run_ownership import read_original_run
from backend.app.testing.run_worker import TestingCliWorker as CliWorker
from backend.tests.code_tasks.test_execution_profile_versions import resources
from backend.tests.code_tasks.test_task_stop import seed_task
from backend.tests.infrastructure.test_v20_check_runner_bundle import bundle, document, member  # noqa: F401
from backend.tests.infrastructure.test_v20_command_http import package  # noqa: F401
from backend.tests.test_testing_pack_seal import automated, observe, target
from backend.tests.test_testing_policy_api import OPTIONS, content, create, post, receipt
from backend.tests.test_testing_reference_sets import (
    baseline_fixture,
    reference,
    register_reference,
)
from backend.tests.test_testing_task_api import approve, wait_task


def _assets(root, runner, *, browser_target=None):
    sources = create_private_package(root / ('test-target-' + uuid4().hex))
    packs = create_private_package(root / ('test-pack-' + uuid4().hex))
    entry = browser_target or replace(target(runner.manifest_sha256), protected_input_refs=())
    manifest = encoded(
        {
            'schema_version': 1,
            'target': {
                key: value for key, value in entry.wire().items() if key != 'fixture_sha256'
            },
            'file_entries': [],
        }
    )
    (sources / 'manifest.json').write_bytes(manifest)
    with PrivatePackageGuard(sources) as source, PrivatePackageGuard(packs) as pack:
        installed = InstalledTarget(
            replace(entry, fixture_sha256=digest(manifest)), runner, source.verify()
        )
        return AssetInstallation(pack.verify(), (installed,))


def _candidate_fixture(database, owner):
    with database.transaction(write=True) as connection:
        coding = connection.execute('SELECT * FROM code_tasks WHERE id=?', (owner,)).fetchone()
        at = operation_time(None)
        operation = entity_id(connection, EntityKind.OPERATION_RECORD)
        candidate = entity_id(connection, EntityKind.CODE_CANDIDATE)
        connection.execute(
            """INSERT INTO code_operations(id,task_id,resource_kind,resource_id,operation_type,
               idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at)
               VALUES(?,?,'TASK',?,'CAPTURE_AND_CHECK',?,1,'{}',1,'SUCCEEDED',?)""",
            (operation, owner, owner, str(uuid4()), at),
        )
        connection.execute(
            """INSERT INTO code_candidates(id,task_id,base_snapshot_id,capture_operation_id,
               content_store_key,content_tree_oid,role,control_generation,content_policy_version,
               manifest_sha256,captured_at,file_count,byte_count,created_at)
               VALUES(?,?,?,?,?,?,'BACKEND',1,?,?,?,1,1,?)""",
            (
                candidate,
                owner,
                coding['base_snapshot_id'],
                operation,
                'fixture:candidate',
                'b' * 40,
                CONTENT_POLICY,
                'd' * 64,
                at,
                at,
            ),
        )
        basis = {
            key: coding[key] for key in ('requirement_id', 'document_id', 'design_revision_id')
        }
        return candidate, {**basis, 'material_refs': []}


def _sealed_pack(
    database,
    client,
    basis,
    *,
    publish=True,
    create_plan=True,
    quote='原固定设计',
    timeout=3,
    make_plan=automated,
):
    plan = '/api/v1/test-plans'
    version = '/api/v1/test-plan-versions/1'
    pack = '/api/v1/test-pack-versions/1'
    if create_plan:
        assert post(client, plan, {'name': '原独立测试'}).status_code == 201
    plan_content = make_plan(
        {
            **basis,
            'behaviors': [
                {
                    'behavior_id': 'result',
                    'name': '保留结果',
                    'basis_refs': [
                        {
                            'document_id': basis['document_id'],
                            'revision_id': basis['design_revision_id'],
                            'quote': quote,
                        }
                    ],
                    'stages': ['BACKEND'],
                    'importance': 'CRITICAL',
                    'mode': 'MANUAL',
                    'case_ids': [],
                    'explanation': '固定原文',
                }
            ],
            'cases': [],
            'unresolved_questions': [],
        }
    )
    for case in plan_content['cases']:
        case['timeout_seconds'] = timeout
    made = post(client, plan + '/1/versions', {'plan_content': plan_content})
    assert made.status_code == 201, made.text
    assert post(client, version + '/publish', {'expected_state_version': 1}).status_code == 200
    assert post(client, version + '/packs', {}).status_code == 201
    sealed = post(client, pack + '/seal', {'expected_state_version': 1})
    assert sealed.status_code == 202, sealed.text
    assert observe(client, sealed.json()['data']['operation_id'])['status'] == 'SUCCEEDED'
    if not publish:
        return
    with database.transaction(write=True) as connection:
        # Historical validation is a fixture here. This test uses the actual seal
        # but does not claim native reference-validation or candidate custody.
        at = operation_time(None)
        operation = entity_id(connection, EntityKind.OPERATION_RECORD)
        validation = entity_id(connection, EntityKind.TEST_PACK_VALIDATION)
        connection.execute(
            """INSERT INTO code_operations(id,resource_kind,resource_id,operation_type,
               idempotency_key,expected_state_version,fixed_input,status,created_at,started_at,ended_at)
               VALUES(?,'TEST_PACK_VERSION',1,'VALIDATE_PACK',?,2,'{}','SUCCEEDED',?,?,?)""",
            (operation, str(uuid4()), at, at, at),
        )
        connection.execute(
            """INSERT INTO testing_pack_validations(id,test_pack_version_id,profile_version_id,
               reference_set_ref,operation_id,result,created_at,ended_at)
               VALUES(?,1,1,'fixture:reference',?,'PASSED',?,?)""",
            (validation, operation, at, at),
        )
        connection.execute(
            """UPDATE testing_pack_versions SET status='PUBLISHED',validation_id=?,
               state_version=state_version+1,published_at=? WHERE id=1""",
            (validation, at),
        )


def _registered_cli(runner, *, definition=None):
    definition = definition or ProjectCheckCommand.decode(
        {
            'command_id': 'print-result',
            'executable_ref': 'fixture:exe',
            'argument_template': [],
            'working_directory': '.',
            'purpose': 'CHECK',
            'timeout_seconds': 5,
            'network_scope_ref': None,
        }
    )
    command = {**asdict(definition), 'argument_template': list(definition.argument_template)}
    admission = CliAdmission(
        'fixture:testing-admission',
        'runner:cli',
        runner.manifest_sha256,
        ('environment:test',),
        definition,
        1,
        64 * 1024 * 1024,
    )
    profile = content()
    profile.update(
        runner_refs=['runner:cli'],
        environment_refs=['environment:test'],
        commands=[command],
        admission_refs=[admission.evidence_ref],
    )
    profile['limits'].update(
        max_check_cases=2,
        max_active_seconds=max(30, definition.timeout_seconds * 2),
        max_check_output_bytes=1024,
    )
    options = {
        **OPTIONS,
        'COMMAND': [{'value': command, 'ready': True}],
        'RUNNER': [{'value': {'runner_ref': 'runner:cli'}, 'ready': True}],
        'RUNTIME': [{'value': {'runtime_ref': 'environment:test'}, 'ready': True}],
        'CAPABILITY': [{'value': {'evidence_ref': admission.evidence_ref}, 'ready': True}],
    }
    return admission, profile, options


@pytest.mark.parametrize('terminate', [False, True])
def test_original_cli_receipt_and_closure_before_dispatch(package, bundle, monkeypatch, terminate):  # noqa: F811
    root, release = package
    _, runner = bundle
    catalog = ResourceCatalog(testing_assets=_assets(root, runner))
    database = Database(root / (str(uuid4()) + '.sqlite'), schema_release=release)
    database.initialize()
    app = create_app(database=database, catalog=catalog)
    admission, profile, options = _registered_cli(runner)
    monkeypatch.setattr(tasks, 'saved_candidate', lambda connection, candidate: (None, candidate))
    monkeypatch.setattr(tasks, 'candidate_available', lambda candidate: True)
    monkeypatch.setattr(task_run, '_held_pack', lambda *args, **kwargs: True)
    with TestClient(app) as client:
        runtime = app.state.walle_runtime
        coding = seed_task(database, runtime, client)
        candidate, basis = _candidate_fixture(database, coding)
        with resources(options):
            created_profile = create(client, profile)
        assert created_profile.status_code == 201, created_profile.text
        _sealed_pack(database, client, basis)
        path = '/api/v1/testing-tasks'
        body = {
            **basis,
            'target_kind': 'CANDIDATE',
            'candidate_id': candidate,
            'snapshot_id': None,
            'purpose': 'DIAGNOSTIC',
            'profile_version_id': 1,
            'authorization_id': approve(client, budget='0'),
            'budget_limit_cny': '0',
            'plan_version_id': 1,
            'test_pack_version_id': 1,
            'previous_testing_task_id': None,
        }
        made = post(client, path, body)
        assert made.status_code == 201, made.text
        path += '/1'
        owner = bind_backend_controller(runtime.commands().process_lock, 'a' * 64)
        worker_gate = SimpleNamespace(
            testing_cli_resources=CliRuntime(owner, (admission,)), wake=lambda: None
        )
        app.state.walle_repository_registration = worker_gate
        attached = post(
            client,
            path + '/assets',
            {'expected_state_version': 1, 'plan_version_id': 1, 'test_pack_version_id': 1},
        )
        assert attached.status_code == 200, attached.text
        assert attached.json()['data']['status'] == 'READY'
        state = attached.json()['data']['state_version']
        original_key = str(uuid4())
        run_path = path + '/run'
        expected = {'expected_state_version': state}
        worker_gate.testing_cli_resources = None
        assert post(client, run_path, expected, original_key).status_code == 503
        assert receipt(client, run_path, original_key)['lookup_status'] == 'NOT_FOUND'
        worker_gate.testing_cli_resources = CliRuntime(owner, (admission,))
        assert next(
            action
            for action in client.get(path).json()['data']['available_actions']
            if action['action'] == 'RUN_TEST'
        )['enabled']
        response = post(client, run_path, expected, original_key)
        assert response.status_code == 202, response.text
        accepted = response.json()['data']
        assert post(client, run_path, expected, original_key).json()['data'] == accepted
        assert receipt(client, run_path, original_key)['original_outcome']['data'] == accepted
        operation_path = path + f'/operations/{accepted["operation_id"]}'
        operation = client.get(operation_path)
        assert operation.status_code == 200, operation.text
        assert operation.json()['data']['status'] == 'RUNNING'
        if terminate:
            stopped = post(
                client,
                path + '/terminate',
                {'expected_state_version': accepted['state_version']},
            )
            assert stopped.status_code == 202, stopped.text
            termination = stopped.json()['data']['operation_id']
            wait_task(client, 'STOPPING', stop_status='UNKNOWN')

        def unavailable_guard():
            raise AssertionError('Undispatched original must not connect to a Guard')

        with (
            PrivatePackageGuard(
                create_private_package(root / ('cli-source-' + uuid4().hex))
            ) as parent,
            LaunchJournal(create_private_package(root / ('cli-journal-' + uuid4().hex))) as journal,
        ):
            worker = CliWorker(
                runtime,
                parent,
                owner,
                journal,
                unavailable_guard,
                (),
                cancelled=lambda: False,
            )
            assert worker.advance()
            assert worker.advance()
            assert worker.advance()
            assert not worker.advance()
        if terminate:
            wait_task(client, 'TERMINATED')
        task = client.get(path).json()['data']
        assert task['status'] == ('TERMINATED' if terminate else 'COMPLETED')
        operation = client.get(operation_path)
        assert operation.status_code == 200, operation.text
        if terminate:
            assert operation.json()['data']['status'] == 'CANCELLED'
            assert operation.json()['data']['steps'][-1]['result_ref'] is None
            closed = client.get(path + f'/operations/{termination}')
            assert closed.status_code == 200, closed.text
            assert closed.json()['data']['status'] == 'SUCCEEDED'
        else:
            assert operation.json()['data']['steps'][-1]['result_ref'] == {
                'report_id': task['report_id']
            }
        assert 'private_case_claims' not in operation.text
        with database.transaction() as connection:
            assert connection.execute('SELECT count(*) FROM testing_reports').fetchone()[0] == int(
                not terminate
            )
            if not terminate:
                assert (
                    connection.execute('SELECT result FROM testing_reports').fetchone()[0]
                    == 'UNAVAILABLE'
                )
            assert (
                connection.execute(
                    'SELECT count(*) FROM code_verification_case_results'
                ).fetchone()[0]
                == 0
            )
            commands = connection.execute(
                'SELECT task_id,testing_task_id,status,process_identity FROM code_commands ORDER BY id'
            ).fetchall()
            status = 'CANCELLED' if terminate else 'FAILED'
            assert [tuple(row) for row in commands] == [(None, 1, status, None)] * 2
        compare = {
            'expected_state_version': task['state_version'],
            'operation_id': accepted['operation_id'],
        }
        assert post(client, path + '/resume', compare).json()['error']['code'] == 'TASK_ENDED'
        missing = post(client, path + '/reconcile', {**compare, 'operation_id': 9999})
        assert missing.status_code == 404
        key = str(uuid4())
        response = post(client, path + '/reconcile', compare, key)
        assert response.status_code == 202, response.text
        recovered = response.json()['data']
        assert recovered['state_version'] == task['state_version']
        assert post(client, path + '/reconcile', compare, key).json()['data'] == recovered
        recovery_path = path + f'/operations/{recovered["operation_id"]}'
        deadline = monotonic() + 8
        while True:
            fetched = client.get(recovery_path)
            assert fetched.status_code == 200, fetched.text
            observed = fetched.json()['data']
            if observed['status'] == 'SUCCEEDED' or monotonic() >= deadline:
                break
            sleep(0.05)
        assert observed['status'] == 'SUCCEEDED'
        assert observed['steps'][-1]['result_ref'] == {
            'operation_id': accepted['operation_id'],
            'observed_status': 'CANCELLED' if terminate else 'SUCCEEDED',
        }
        assert client.get(path).json()['data']['state_version'] == task['state_version']
        assert post(client, run_path, expected, original_key).json()['data'] == accepted


def test_validation_group_reserves_original_children_and_stays_unavailable_without_runner(
    package, bundle
):
    root, release = package
    _, runner = bundle
    installed = _assets(root, runner)
    catalog = ResourceCatalog(testing_assets=installed)
    database = Database(root / (str(uuid4()) + '.sqlite'), schema_release=release)
    database.initialize()
    app = create_app(database=database, catalog=catalog)
    admission, profile, options = _registered_cli(runner)
    with TestClient(app) as client:
        runtime = app.state.walle_runtime
        coding = seed_task(database, runtime, client)
        _, basis = _candidate_fixture(database, coding)
        with resources(options):
            assert create(client, profile).status_code == 201
        _sealed_pack(database, client, basis, publish=False)
        positive = baseline_fixture(runtime, '2' * 40)
        negative = baseline_fixture(runtime, '3' * 40)
        with database.transaction() as connection:
            fingerprint = basis_fingerprint(connection, _version(connection, 1))
        registered = register_reference(
            root,
            'cli-reference-' + uuid4().hex,
            reference(
                basis_fingerprint=fingerprint,
                positive_snapshot_ids=[positive],
                negative_controls=[
                    {'snapshot_id': negative, 'expected_failed_case_ids': ['private']}
                ],
                repeat_count=2,
            ),
        )
        catalog.testing_assets = AssetInstallation(
            installed.pack_directory, installed.registered_targets, (registered,)
        )
        grant = approve(client, scope='PACK_VALIDATION', budget='0')
        owner = bind_backend_controller(runtime.commands().process_lock, 'b' * 64)
        app.state.walle_repository_registration = SimpleNamespace(
            testing_cli_resources=CliRuntime(owner, (admission,), snapshots=True),
            wake=lambda: None,
        )
        path = '/api/v1/test-pack-versions/1/validations'
        body = {
            'expected_state_version': 2,
            'profile_version_id': 1,
            'reference_set_ref': registered.reference.reference_set_ref,
            'authorization_id': grant,
        }
        key = str(uuid4())
        response = post(client, path, body, key)
        assert response.status_code == 202, response.text
        accepted = response.json()['data']
        assert post(client, path, body, key).json()['data'] == accepted
        assert receipt(client, path, key)['original_outcome']['data'] == accepted
        read = '/api/v1/test-pack-validations/' + str(accepted['validation_id'])
        original = client.get(read)
        assert original.status_code == 200, original.text
        assert original.json()['data']['result'] == 'RUNNING'
        children = original.json()['data']['testing_tasks']
        assert [row['snapshot_id'] for row in children] == [positive, positive, negative, negative]
        with database.transaction() as connection:
            first = connection.execute(
                "SELECT id,testing_task_id FROM code_operations WHERE operation_type='RUN_TEST' ORDER BY id LIMIT 1"
            ).fetchone()
        internal = client.get(
            f'/api/v1/testing-tasks/{first["testing_task_id"]}/operations/{first["id"]}'
        )
        assert internal.status_code == 200, internal.text
        assert post(client, path, body).status_code == 403

        def unavailable_guard():
            raise AssertionError('No original validation child may launch without the resource')

        with (
            PrivatePackageGuard(
                create_private_package(root / ('group-source-' + uuid4().hex))
            ) as parent,
            LaunchJournal(
                create_private_package(root / ('group-journal-' + uuid4().hex))
            ) as journal,
        ):
            worker = CliWorker(
                runtime, parent, owner, journal, unavailable_guard, (), cancelled=lambda: False
            )
            for index in range(12):
                assert worker.advance(), index
            assert not worker.advance()
        assert observe(client, accepted['operation_id'])['status'] == 'SUCCEEDED'
        final = client.get(read)
        assert final.status_code == 200, final.text
        assert final.json()['data']['result'] == 'UNAVAILABLE'
        assert all(row['status'] == 'COMPLETED' for row in final.json()['data']['testing_tasks'])
        assert (
            post(
                client, '/api/v1/test-pack-versions/1/publish', {'expected_state_version': 2}
            ).status_code
            == 409
        )
        with database.transaction() as connection:
            assert connection.execute('SELECT count(*) FROM testing_reports').fetchone()[0] == 4
            assert (
                connection.execute(
                    'SELECT count(*) FROM code_verification_case_results'
                ).fetchone()[0]
                == 0
            )


def test_browser_original_intake_reserves_three_distinct_commands_without_fixture_pass(
    package, monkeypatch
):  # noqa: F811
    root, release = package
    runner_path = create_private_package(root / 'browser-planning-runner')
    (runner_path / 'bin').mkdir()
    (runner_path / 'bin' / 'entry').write_bytes(b'runner')
    (runner_path / 'zero').write_bytes(b'')
    raw = encoded(document(capabilities=['BROWSER', 'CONTENT_INTEGRITY']))
    (runner_path / 'manifest.json').write_bytes(raw)
    with PrivatePackageGuard(runner_path) as held:
        runner = RegisteredCheckRunner(
            held.verify(),
            digest(raw),
            'native-check-runner',
            '1.0.0',
        )
    target_spec = replace(
        target(runner.manifest_sha256),
        target_ref='browser-candidate',
        driver_kind='BROWSER',
        runner_ref='runner:browser',
        command_ids=('frontend', 'backend'),
        endpoint_refs=('application', 'front-port', 'back-port'),
        protected_input_refs=(),
    )
    admission, profile, options = _registered_cli(runner)
    frontend = replace(
        admission,
        runner_ref='runner:browser',
        evidence_ref='fixture:front-service',
        command=ProjectCheckCommand.decode(
            {
                'command_id': 'frontend',
                'executable_ref': 'fixture:front',
                'argument_template': ['{CHECK_HOST}', '{CHECK_PORT}'],
                'working_directory': '.',
                'purpose': 'SERVICE',
                'timeout_seconds': 10,
                'network_scope_ref': 'front-port',
            }
        ),
    )
    backend = replace(
        admission,
        runner_ref='runner:browser',
        evidence_ref='fixture:back-service',
        command=ProjectCheckCommand.decode(
            {
                'command_id': 'backend',
                'executable_ref': 'fixture:back',
                'argument_template': ['{CHECK_HOST}', '{CHECK_PORT}'],
                'working_directory': '.',
                'purpose': 'SERVICE',
                'timeout_seconds': 10,
                'network_scope_ref': 'back-port',
            }
        ),
    )
    browser = BrowserAdmission(
        'browser-candidate',
        'fixture:driver',
        'runner:browser',
        runner.manifest_sha256,
        ('environment:test',),
        'browser-driver',
        8,
        512 * 1024 * 1024,
        (
            BrowserServiceAdmission('FRONTEND', 'application', '/', frontend),
            BrowserServiceAdmission('BACKEND', 'application', '/api/', backend),
        ),
    )
    profile['limits'].update(max_case_steps=8, max_case_payload_bytes=4096)
    profile.update(
        runner_refs=['runner:browser'],
        admission_refs=[frontend.evidence_ref, backend.evidence_ref, browser.evidence_ref],
        commands=[
            {**asdict(row.command), 'argument_template': list(row.command.argument_template)}
            for row in (frontend, backend)
        ],
    )
    options.update(
        COMMAND=[{'value': row, 'ready': True} for row in profile['commands']],
        RUNNER=[{'value': {'runner_ref': 'runner:browser'}, 'ready': True}],
        SCOPE=[
            {'value': {'scope_ref': ref, 'scope_kind': 'NETWORK_TARGET'}, 'ready': True}
            for ref in ('front-port', 'back-port')
        ],
        CAPABILITY=[
            {'value': {'evidence_ref': ref}, 'ready': True} for ref in profile['admission_refs']
        ],
    )

    def browser_plan(content):
        plan = automated(content)
        for case in plan['cases']:
            case['driver_kind'] = 'BROWSER'
            case['steps'] = [
                {
                    'step_id': 'nav',
                    'op': 'NAVIGATE',
                    'endpoint_ref': 'application',
                    'path': '/index.html',
                },
            ]
            case['assertions'] = [
                {
                    'assertion_id': 'visible',
                    'op': 'VISIBLE',
                    'locator': {'kind': 'TEST_ID', 'value': 'result'},
                    'expected': True,
                }
            ]
        return plan

    catalog = ResourceCatalog(testing_assets=_assets(root, runner, browser_target=target_spec))
    database = Database(root / (str(uuid4()) + '.sqlite'), schema_release=release)
    database.initialize()
    app = create_app(database=database, catalog=catalog)
    monkeypatch.setattr(tasks, 'saved_candidate', lambda connection, candidate: (None, candidate))
    monkeypatch.setattr(tasks, 'candidate_available', lambda candidate: True)
    monkeypatch.setattr(task_run, '_held_pack', lambda *args, **kwargs: True)
    with TestClient(app) as client:
        runtime = app.state.walle_runtime
        coding = seed_task(database, runtime, client)
        candidate, basis = _candidate_fixture(database, coding)
        with resources(options):
            created = create(client, profile)
        assert created.status_code == 201, created.text
        _sealed_pack(database, client, basis, make_plan=browser_plan)
        worker_gate = SimpleNamespace(testing_cli_resources=None, wake=lambda: None)
        app.state.walle_repository_registration = worker_gate
        made = post(
            client,
            '/api/v1/testing-tasks',
            {
                **basis,
                'target_kind': 'CANDIDATE',
                'candidate_id': candidate,
                'snapshot_id': None,
                'purpose': 'DIAGNOSTIC',
                'profile_version_id': 1,
                'authorization_id': approve(client, budget='0'),
                'budget_limit_cny': '0',
                'plan_version_id': 1,
                'test_pack_version_id': 1,
                'previous_testing_task_id': None,
            },
        )
        assert made.status_code == 201, made.text
        path = '/api/v1/testing-tasks/1'
        owner = bind_backend_controller(runtime.commands().process_lock, 'a' * 64)
        worker_gate.testing_cli_resources = CliRuntime(owner, (), browser_admissions=(browser,))
        attached = post(
            client,
            path + '/assets',
            {'expected_state_version': 1, 'plan_version_id': 1, 'test_pack_version_id': 1},
        )
        assert attached.status_code == 200, attached.text
        assert attached.json()['data']['status'] == 'READY', attached.text
        accepted = post(
            client,
            path + '/run',
            {'expected_state_version': attached.json()['data']['state_version']},
        )
        assert accepted.status_code == 202, accepted.text
        operation = accepted.json()['data']['operation_id']
        with database.transaction() as connection:
            original = read_original_run(connection, operation)
            assert len(original.cases) == 2
            for case in original.cases:
                assert case.command['purpose'] == 'CHECK' and case.fixed['kind'] == 'BROWSER'
                assert [
                    (app.command['purpose'], app.fixed['role']) for app in case.applications
                ] == [
                    ('SERVICE', 'FRONTEND'),
                    ('SERVICE', 'BACKEND'),
                ]
                assert len({case.scope, *(part.scope for part in case.applications)}) == 3

        def unavailable_guard():
            raise AssertionError('Original undispatched browser must not open a Guard')

        with (
            PrivatePackageGuard(create_private_package(root / 'browser-intake-source')) as parent,
            LaunchJournal(create_private_package(root / 'browser-intake-journal')) as journal,
        ):
            worker = CliWorker(
                runtime, parent, owner, journal, unavailable_guard, (), cancelled=lambda: False
            )
            assert all(worker.advance() for _ in range(3))
        with database.transaction() as connection:
            assert (
                connection.execute('SELECT result FROM testing_reports').fetchone()[0]
                == 'UNAVAILABLE'
            )
            commands = connection.execute(
                'SELECT status,process_identity FROM code_commands WHERE operation_id=?',
                (operation,),
            ).fetchall()
            assert [tuple(row) for row in commands] == [('FAILED', None)] * 6
            assert not connection.execute('SELECT 1 FROM code_verification_case_results').fetchone()
