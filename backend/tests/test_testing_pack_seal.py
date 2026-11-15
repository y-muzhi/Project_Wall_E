"""Compile a reviewed plan and seal its actual operator-private NTFS files."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.code_tasks.operation_protocol import operation_steps
from backend.app.infrastructure.database import Database, StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.service import create_app
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_json_object
from backend.app.testing import pack_seal
from backend.app.testing.asset_installation import InstalledTarget
from backend.app.testing.asset_installation import TestingAssetInstallation as AssetInstallation
from backend.app.testing.assets import sealed_pack_facts
from backend.app.testing.pack_compile import (
    CompileError,
    CompilerTarget,
    compile_pack,
    digest,
    encoded,
)
from backend.app.testing.pack_validation import validation_schedule
from backend.app.testing.plans import _version
from backend.app.testing.tasks import insert_task
from backend.tests.code_tasks.test_execution_profile_versions import (
    parents,
    publish,
    resources,
    seed_price,
)
from backend.tests.infrastructure.test_v20_check_runner_bundle import bundle, member  # noqa: F401
from backend.tests.infrastructure.test_v20_command_http import package, service  # noqa: F401
from backend.tests.test_testing_pack_api import PACK, PACKS
from backend.tests.test_testing_plan_api import PLANS, VERSIONS, setup
from backend.tests.test_testing_policy_api import AUTH, OPTIONS, create, post, receipt
from backend.tests.test_testing_reference_sets import (
    baseline_fixture,
    reference,
    register_reference,
)

SEAL = PACK + '/seal'


def target(runner='a' * 64):
    return CompilerTarget(
        'test-offline',
        'CLI',
        'runner:cli',
        runner,
        'fixture:test',
        '0' * 64,
        ('print-result',),
        (),
        ('environment:test',),
        ('input:test',),
        'NONE',
    )


def automated(content):
    content = deepcopy(content)
    for row in content['behaviors']:
        row.update(mode='AUTO', case_ids=['public', 'private'], explanation='')
    content['cases'] = [
        {
            'case_id': case,
            'name': case,
            'visibility': visibility,
            'behavior_ids': [row['behavior_id'] for row in content['behaviors']],
            'driver_kind': 'CLI',
            'timeout_seconds': 3,
            'steps': [{'step_id': 'run', 'op': 'RUN', 'command_id': 'print-result', 'stdin': ''}],
            'assertions': [{'assertion_id': 'exit', 'op': 'EXIT_CODE', 'expected': 0}],
        }
        for case, visibility in (('public', 'PUBLIC'), ('private', 'HELD_OUT'))
    ]
    return content


def test_compile_freezes_visibility_stages_basis_and_content_without_execution():
    content = automated(
        {
            'id': 9,
            'requirement_id': 1,
            'document_id': 2,
            'design_revision_id': 3,
            'material_refs': [],
            'unresolved_questions': [],
            'behaviors': [
                {
                    'behavior_id': 'b',
                    'name': '行为',
                    'mode': 'MANUAL',
                    'case_ids': [],
                    'explanation': '固定原文',
                    'importance': 'CRITICAL',
                    'stages': ['BACKEND', 'ACCEPTANCE'],
                    'basis_refs': [{'document_id': 2, 'revision_id': 3, 'quote': '原文'}],
                }
            ],
        }
    )
    supplied = (target(),)
    options = {'pack_id': 7, 'version': 1, 'basis_sha256': 'b' * 64}
    compiled = compile_pack(content, supplied, **options)
    assert compiled == compile_pack(deepcopy(content), supplied, **options)
    assert compiled.case_ids == ('private', 'public')
    members = dict(compiled.files)
    manifest = strict_json_object(members['manifest.json'])
    assert compiled.sha256 == digest(members['manifest.json'])
    assert manifest['basis_fingerprint'] == 'b' * 64
    assert manifest['plan_version_id'] == 9
    for row, expected in zip(manifest['case_packs'], ('private', 'public'), strict=True):
        source = members[row['path']]
        assert digest(source) == row['sha256'] and len(source) == row['byte_count']
        assert row['stages'] == ['BACKEND', 'ACCEPTANCE']
        assert [row['case_id'] for row in strict_json_object(source)['cases']] == [expected]
    checks = compiled.check_set.value()
    assert checks['items'][0]['evidence_rule']['kind'] == 'CONTENT_INTEGRITY'
    assert checks['coverage_plan'][0]['check_ids'] == ['controlled-1', 'controlled-2']
    with pytest.raises(CompileError, match='exact registered'):
        compile_pack(content, (), **options)
    with pytest.raises(CompileError, match='exact registered'):
        compile_pack(content, (*supplied, replace(target(), target_ref='duplicate')), **options)
    content['cases'][0]['steps'][0]['command_id'] = 'unregistered'
    with pytest.raises(CompileError, match='exact registered'):
        compile_pack(content, supplied, **options)


@pytest.fixture
def installed(package, bundle):  # noqa: F811
    root, release = package
    private_root = create_private_package(root / uuid4().hex[:7])
    fixture = create_private_package(private_root / 'fixture')
    generated = create_private_package(private_root / 'packs')
    _, runner = bundle
    entry = target(runner.manifest_sha256)
    raw_member = b'fixed-test-input'
    (fixture / 'input').write_bytes(raw_member)
    manifest = encoded(
        {
            'schema_version': 1,
            'target': {
                key: value for key, value in entry.wire().items() if key != 'fixture_sha256'
            },
            'file_entries': [member('input', raw_member)],
        }
    )
    (fixture / 'manifest.json').write_bytes(manifest)
    with PrivatePackageGuard(fixture) as source, PrivatePackageGuard(generated) as output:
        registered = InstalledTarget(
            replace(entry, fixture_sha256=digest(manifest)),
            runner,
            source.verify(),
        )
        catalog = ResourceCatalog(testing_assets=AssetInstallation(output.verify(), (registered,)))
    database = Database(root / (str(uuid4()) + '.sqlite'), schema_release=release)
    database.initialize()
    return database, catalog, fixture, generated


def opened_pack(database, app, client):
    content = automated(setup((database, app, client)))
    made = post(client, PLANS + '/1/versions', {'plan_content': content})
    assert made.status_code == 201, made.text
    published = post(client, VERSIONS + '/1/publish', {'expected_state_version': 1})
    assert published.status_code == 200, published.text
    assert post(client, PACKS, {}).status_code == 201


def observe(client, identity, terminal=('SUCCEEDED', 'FAILED')):
    deadline = monotonic() + 16
    while monotonic() < deadline:
        result = client.get(f'/api/v1/testing-operations/{identity}')
        assert result.status_code == 200, result.text
        row = result.json()['data']
        if row['status'] in terminal:
            return row
        sleep(0.06)
    raise AssertionError(row)


def test_seal_resume_exact_original_after_own_process_lifespan_interrupt(installed, monkeypatch):
    database, catalog, _, output = installed
    key = str(uuid4())
    before_commit = Event()
    original_save = pack_seal._save_seal

    def database_interrupted(*args):
        before_commit.set()
        raise StorageUnavailable('isolated failure before the SQL publication')

    with monkeypatch.context() as patch:
        patch.setattr(pack_seal, '_save_seal', database_interrupted)
        app = create_app(database=database, catalog=catalog)
        with TestClient(app) as client:
            opened_pack(database, app, client)
            accepted = post(client, SEAL, {'expected_state_version': 1}, key)
            assert accepted.status_code == 202, accepted.text
            saved = accepted.json()['data']
            assert saved['test_pack_version_id'] == 1 and saved['validation_id'] is None
            assert receipt(client, SEAL, key)['original_outcome']['data'] == saved
            assert before_commit.wait(12)
            status = observe(client, saved['operation_id'], ('RUNNING',))
            assert [step['status'] for step in status['steps']] == [
                'SUCCEEDED',
                'SUCCEEDED',
                'RUNNING',
                'PENDING',
            ]
            assert post(client, SEAL, {'expected_state_version': 1}).json()['error']['code'] == (
                'OPERATION_IN_PROGRESS'
            )
            assert client.get(PACK).json()['data']['status'] == 'DRAFT'
    assert pack_seal._save_seal is original_save
    (original_package,) = output.iterdir()
    members = {
        item.name: (item.stat().st_mtime_ns, item.read_bytes())
        for item in original_package.iterdir()
    }
    assert len(members) == 4
    # A pre-rename stage left by the original writer is not authoritative.
    (original_package / '.pending-manifest.json').write_bytes(b'partial')
    restarted = create_app(database=database, catalog=catalog)
    with TestClient(restarted) as client:
        status = observe(client, saved['operation_id'])
        assert status['status'] == 'SUCCEEDED', status
        assert status['fixed_input'] == {'expected_state_version': 1}
        assert [step['status'] for step in status['steps']] == ['SUCCEEDED'] * 4
        public_pack = client.get(PACK).json()['data']
        assert public_pack['status'] == 'SEALED' and public_pack['state_version'] == 2
        assert public_pack['ready'] is False and public_pack['validation_id'] is None
        assert public_pack['sha256'] == digest(members['manifest.json'][1])
        assert 'content_ref' not in public_pack
        assert post(client, SEAL, {'expected_state_version': 1}, key).json()['data'] == saved
        assert (
            client.get('/api/v1/testing-operations/1').json()['data']['resource_kind']
            == 'TEST_PLAN_VERSION'
        )
    assert list(output.iterdir()) == [original_package]
    assert {
        item.name: (item.stat().st_mtime_ns, item.read_bytes())
        for item in original_package.iterdir()
    } == members
    with database.transaction() as connection:
        assert [
            row['owner_module']
            for row in connection.execute('SELECT * FROM code_check_set_versions')
        ] == ['TESTING']
        assert connection.execute('SELECT count(*) FROM testing_tasks').fetchone()[0] == 0


def test_changed_fixture_fails_without_writing_original_or_marking_ready(installed):
    database, catalog, fixture, output = installed
    (fixture / 'input').write_bytes(b'different')
    app = create_app(database=database, catalog=catalog)
    with TestClient(app) as client:
        opened_pack(database, app, client)
        response = post(client, SEAL, {'expected_state_version': 1})
        assert response.status_code == 202, response.text
        status = observe(client, response.json()['data']['operation_id'])
        assert status['status'] == 'FAILED' and status['failure_code'] == 'CONTENT_NOT_READY'
        assert client.get(PACK).json()['data']['status'] == 'DRAFT'
        assert not list(output.iterdir())


def test_uninstalled_manual_plan_does_not_accept_seal(service):  # noqa: F811
    database, app, client = service
    body = setup((database, app, client))
    assert post(client, PLANS + '/1/versions', {'plan_content': body}).status_code == 201
    assert post(client, VERSIONS + '/1/publish', {'expected_state_version': 1}).status_code == 200
    assert post(client, PACKS, {}).status_code == 201
    key = str(uuid4())
    result = post(client, SEAL, {'expected_state_version': 1}, key)
    assert result.status_code == 503, result.text
    assert result.json()['error']['details'] == {'capability_codes': ['Q20-CHECKS']}
    assert receipt(client, SEAL, key)['lookup_status'] == 'NOT_FOUND'
    with database.transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM code_operations WHERE operation_type='SEAL_PACK'"
            ).fetchone()[0]
            == 0
        )


def _persist_validation_fixture(connection, registration, grant, pack):
    # Persist an observed group shape to exercise read and cold dispatch boundaries.
    # The fixture has no verification, command, report, or passing result.
    validation = entity_id(connection, EntityKind.TEST_PACK_VALIDATION)
    operation = entity_id(connection, EntityKind.OPERATION_RECORD)
    samples = validation_schedule(registration.reference)
    children = [entity_id(connection, EntityKind.TESTING_TASK) for _ in samples]
    plan = _version(connection, pack['plan_version_id'])
    at = operation_time(None)
    fixed = canonical_input(
        {
            'expected_state_version': pack['state_version'],
            'profile_version_id': 1,
            'authorization_id': grant,
            'reference_set_ref': registration.reference.reference_set_ref,
            'validation_id': validation,
            'pack_sha256': pack['sha256'],
            'reference_sha256': registration.sha256,
            'samples': samples,
        }
    )
    connection.execute(
        """INSERT INTO code_operations(id,resource_kind,resource_id,operation_type,idempotency_key,
           expected_state_version,fixed_input,status,created_at,started_at)
           VALUES(?,'TEST_PACK_VERSION',?,'VALIDATE_PACK',?,?,?,'RUNNING',?,?)""",
        (operation, pack['id'], str(uuid4()), pack['state_version'], fixed, at, at),
    )
    connection.execute(
        """INSERT INTO testing_pack_validations(id,test_pack_version_id,profile_version_id,
           reference_set_ref,operation_id,result,created_at)
           VALUES(?,?,1,?,?,'RUNNING',?)""",
        (
            validation,
            pack['id'],
            registration.reference.reference_set_ref,
            operation,
            at,
        ),
    )
    connection.execute(
        "UPDATE testing_authorizations SET status='EFFECTIVE',validation_id=? WHERE id=?",
        (validation, grant),
    )
    for identity, sample in zip(children, samples, strict=True):
        insert_task(
            connection,
            identity,
            {
                **{
                    key: plan[key]
                    for key in (
                        'requirement_id',
                        'document_id',
                        'design_revision_id',
                        'material_refs',
                    )
                },
                'target_kind': 'SNAPSHOT',
                'candidate_id': None,
                'snapshot_id': sample['snapshot_id'],
                'purpose': 'PACK_VALIDATION',
                'profile_version_id': 1,
                'authorization_id': grant,
                'budget_limit_cny': '0.000000',
                'plan_version_id': plan['id'],
                'test_pack_version_id': pack['id'],
                'previous_testing_task_id': None,
            },
            at=at,
            validation_id=validation,
            ready=True,
        )
        connection.execute(
            'INSERT INTO testing_validation_tasks(validation_id,testing_task_id) VALUES(?,?)',
            (validation, identity),
        )
    for number, name in enumerate(operation_steps('RESOURCE', 'VALIDATE_PACK'), 1):
        done = number <= 2
        connection.execute(
            """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input,
               result_ref,started_at,ended_at,last_observed_at) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                operation,
                number,
                name,
                'SUCCEEDED' if done else 'PENDING',
                fixed,
                '{}' if done else None,
                at if done else None,
                at if done else None,
                at if done else None,
            ),
        )
    return validation, operation, children


def test_pack_lifecycle_requires_real_reference_and_validation_then_revokes_original(installed):
    database, catalog, _, output = installed
    app = create_app(database=database, catalog=catalog)
    with TestClient(app) as client:
        parents(client)
        seed_price(database)
        with resources():
            assert publish(client).status_code == 201
        opened_pack(database, app, client)
        response = post(client, SEAL, {'expected_state_version': 1})
        assert response.status_code == 202, response.text
        assert observe(client, response.json()['data']['operation_id'])['status'] == 'SUCCEEDED'
        original = client.get(PACK).json()['data']
        assert original['reason_codes'] == ['PACK_NOT_PUBLISHED', 'REFERENCE_SET_NOT_REGISTERED']
        key = str(uuid4())
        publication = PACK + '/publish'
        try_publish = post(client, publication, {'expected_state_version': 2}, key)
        assert try_publish.status_code == 503, try_publish.text
        assert receipt(client, publication, key)['lookup_status'] == 'NOT_FOUND'
        assert client.get('/api/v1/test-pack-validations/1').status_code == 404

        # The fixtures provide committed Git registration facts without executing
        # the sealed test pack or supplying a passing result.
        at = operation_time(None)
        with database.transaction(write=True) as connection:
            connection.execute(
                'INSERT INTO code_repositories VALUES(?,?,?,?,?,?)',
                (1, 'isolated', 'C:/testing-reference', 'C:/testing-reference/.git', 'sha1', at),
            )
            pack = connection.execute('SELECT * FROM testing_pack_versions WHERE id=1').fetchone()
            _, facts = sealed_pack_facts(connection, pack)
        runtime = app.state.walle_runtime
        first = baseline_fixture(runtime, '1' * 40)
        second = baseline_fixture(runtime, '2' * 40)
        root = create_private_package(Path(database.path).parent / uuid4().hex[:6])
        selected = register_reference(
            root,
            'fixed',
            reference(
                'reference:test',
                basis_fingerprint=facts['basis_fingerprint'],
                positive_snapshot_ids=[first],
                negative_controls=[
                    {'snapshot_id': second, 'expected_failed_case_ids': ['private']}
                ],
            ),
        )
        catalog.testing_assets = replace(catalog.testing_assets, reference_sets=(selected,))
        no_pass = post(client, publication, {'expected_state_version': 2}, key)
        assert no_pass.status_code == 409 and no_pass.json()['error']['code'] == 'INVALID_STATE'
        assert receipt(client, publication, key)['record_status'] == 'REJECTED'
        with resources(OPTIONS):
            assert create(client).status_code == 201
            approval = post(
                client,
                AUTH,
                {'profile_version_id': 1, 'scope_kind': 'PACK_VALIDATION', 'budget_limit_cny': '0'},
            )
            assert approval.status_code == 201, approval.text
            validation = PACK + '/validations'
            request = {
                'expected_state_version': 2,
                'profile_version_id': 1,
                'reference_set_ref': 'reference:test',
                'authorization_id': 1,
            }
            assert post(client, validation, {**request, 'authorization_id': 99}).status_code == 403
            validation_key = str(uuid4())
            accepted = post(client, validation, request, validation_key)
            assert accepted.status_code == 503, accepted.text
            assert 'Q20-CHECKS' in accepted.json()['error']['details']['capability_codes']
            assert receipt(client, validation, validation_key)['lookup_status'] == 'NOT_FOUND'
            assert client.get(AUTH + '/1').json()['data']['status'] == 'APPROVED_UNBOUND'
            original_installation = catalog.testing_assets
            try:
                catalog.testing_assets = replace(original_installation, registered_targets=())
                missing_runner = post(client, validation, request)
                assert missing_runner.status_code == 409, missing_runner.text
                assert missing_runner.json()['error']['code'] == 'CONTENT_NOT_READY'
            finally:
                catalog.testing_assets = original_installation
            (stored_pack,) = output.iterdir()
            manifest = stored_pack / 'manifest.json'
            exact_bytes = manifest.read_bytes()
            try:
                manifest.write_bytes(exact_bytes + b' ')
                tampered = post(client, validation, request)
                assert tampered.status_code == 409, tampered.text
                assert tampered.json()['error']['code'] == 'CONTENT_NOT_READY'
                assert client.get(AUTH + '/1').json()['data']['status'] == 'APPROVED_UNBOUND'
            finally:
                manifest.write_bytes(exact_bytes)

        with database.transaction(write=True) as connection:
            assert (
                connection.execute('SELECT count(*) FROM testing_pack_validations').fetchone()[0]
                == 0
            )
            assert connection.execute('SELECT count(*) FROM testing_tasks').fetchone()[0] == 0
            group, original_operation, children = _persist_validation_fixture(
                connection, selected, 1, pack
            )
        validation_read = client.get(f'/api/v1/test-pack-validations/{group}')
        assert validation_read.status_code == 200, validation_read.text
        saved_group = validation_read.json()['data']
        assert saved_group['result'] == 'RUNNING' and saved_group['testing_task_ids'] == children
        assert all(child['status'] == 'READY' for child in saved_group['testing_tasks'])
        original_operation_read = client.get(f'/api/v1/testing-operations/{original_operation}')
        assert original_operation_read.status_code == 200, original_operation_read.text
        assert 'expected_failed_case_ids' not in original_operation_read.text
        assert original_operation_read.json()['data']['steps'][-1]['result_ref'] is None
        run_path = f'/api/v1/testing-tasks/{children[0]}/run'
        run_key = str(uuid4())
        cold_run = post(client, run_path, {'expected_state_version': 1}, run_key)
        assert cold_run.status_code == 503, cold_run.text
        assert cold_run.json()['error']['details']['capability_codes'] == ['Q20-CHECKS']
        assert receipt(client, run_path, run_key)['lookup_status'] == 'NOT_FOUND'
        assert client.get(run_path.removesuffix('/run')).json()['data']['state_version'] == 1
        try:
            manifest.write_bytes(exact_bytes + b' ')
            rejected = post(client, run_path, {'expected_state_version': 1})
            assert rejected.status_code == 409, rejected.text
            assert rejected.json()['error']['code'] == 'CONTENT_NOT_READY'
            assert client.get(run_path.removesuffix('/run')).json()['data']['state_version'] == 1
        finally:
            manifest.write_bytes(exact_bytes)

        revoked_key = str(uuid4())
        revoked_path = PACK + '/revoke'
        body = {'expected_state_version': 2, 'reason': '替换固定材料'}
        revoked = post(client, revoked_path, body, revoked_key)
        assert revoked.status_code == 200, revoked.text
        row = revoked.json()['data']
        assert row['status'] == 'REVOKED' and row['sha256'] == original['sha256']
        assert row['check_set_version_id'] == original['check_set_version_id']
        assert row['reason_codes'] == ['TEST_ASSET_REVOKED']
        assert receipt(client, revoked_path, revoked_key)['original_outcome']['data'] == row
        assert post(client, revoked_path, body, revoked_key).json()['data'] == row
        with database.transaction() as connection:
            identity = connection.execute(
                "SELECT id FROM code_operations WHERE operation_type='REVOKE_PACK'"
            ).fetchone()[0]
            assert (
                connection.execute(
                    "SELECT count(*) FROM code_operations WHERE operation_type='RUN_TEST'"
                ).fetchone()[0]
                == 0
            )
            assert connection.execute('SELECT count(*) FROM code_verifications').fetchone()[0] == 0
        assert all(
            child['status'] == 'DRAFT'
            for child in client.get(f'/api/v1/test-pack-validations/{group}').json()['data'][
                'testing_tasks'
            ]
        )
        after_revoke = post(client, run_path, {'expected_state_version': 2})
        assert (
            after_revoke.status_code == 409
            and after_revoke.json()['error']['code'] == 'TEST_ASSET_REVOKED'
        )
        action = client.get(f'/api/v1/testing-operations/{identity}').json()['data']
        assert action['resource_kind'] == 'TEST_PACK_VERSION' and action['fixed_input'] == body
        assert action['steps'][-1]['result_ref']['status'] == 'REVOKED'
    (original_pack,) = output.iterdir()
    assert digest((original_pack / 'manifest.json').read_bytes()) == original['sha256']
