"""Exercise the development structure cutover without a production environment or model."""

import os
import sqlite3
import sys
from contextlib import closing, contextmanager, nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    digest,
    identity,
)

if sys.platform != 'linux':
    pytest.skip('Linux recovery tools require native filesystem controls', allow_module_level=True)

from backend.app.infrastructure import environment_backup_rehearsal as rehearsal
from backend.app.infrastructure import environment_control as control
from backend.app.infrastructure import environment_release_deployment as deployment
from backend.app.infrastructure import environment_release_switch as switch
from backend.app.infrastructure import environment_restore as restore
from backend.app.infrastructure import environment_restore_preflight as preflight
from backend.app.infrastructure import environment_restore_readiness as readiness
from backend.app.infrastructure import environment_restore_switch as restore_switch
from backend.app.infrastructure import schema_v22_release as schema
from backend.app.infrastructure.environment_backup import SNAPSHOT
from backend.app.infrastructure.environment_backup_assets import AUDIT_INDEX
from backend.app.infrastructure.environment_binding import EnvironmentBinding, write_initial_schema
from backend.app.infrastructure.environment_installation import read_document_ai_policy

PIN = '1' * 64
CUTOFF = '2026-11-27T02:00:00.000Z'
LATER_CUTOFF = '2026-11-27T02:01:00.000Z'


def uuid():
    return str(uuid4())


def write_policy(path, data, *, mode=0o440):
    raw = canonical(data)
    path.write_bytes(raw)
    path.chmod(mode)
    return digest(raw)


@contextmanager
def opened(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        yield fd
    finally:
        os.close(fd)


def test_preflight_freezes_target_before_the_current_backup_exists(tmp_path, monkeypatch):
    data = {
        'format_version': 1,
        'operation_id': uuid(),
        'installation_sha256': PIN,
        'source_data_generation': uuid(),
        'source_deployment_id': uuid(),
        'source_control_revision': 5,
        'source_configuration_sha256': PIN,
        'accepted_backup_cutoff_at': CUTOFF,
        'data_handling': preflight.DOCUMENT_AI_DATA_HANDLING,
        'candidate_proof': {},
        'target_manifest': {},
        'target_schema_directory': str(tmp_path / 'schema'),
        'target_data_generation': uuid(),
        'target_deployment_id': uuid(),
        'target_configuration_sha256': PIN,
        'data_preparation': {
            'path': str(tmp_path / preflight.DATA_POLICY),
            'sha256': PIN,
        },
    }
    proof = {'path': str(tmp_path / 'package.json'), 'sha256': PIN}
    backup = uuid()
    data['preserved'] = {'backup_id': backup, 'capture_policy': {}, 'verification': proof}
    data['selected'] = {'backup_id': backup, 'verification': proof}
    data['data_target'] = {
        'path': str(tmp_path / data['operation_id']),
        'identity': identity(tmp_path.stat()),
        'max_database_bytes': 8 * 1024**2,
    }
    monkeypatch.setattr(preflight, 'read_protected', Path.read_bytes)
    path = tmp_path / preflight.DOCUMENT_AI_POLICY
    pin = write_policy(path, data)
    intent = preflight.restore_authorization(preflight.restore_plan(path, pin))
    final = deepcopy(data)
    final['accepted_backup_cutoff_at'] = LATER_CUTOFF
    final['data_preparation']['sha256'] = '2' * 64
    final['selected']['verification'] = final['preserved']['verification'] = {
        **proof,
        'sha256': '3' * 64,
    }
    pin = write_policy(path, final)
    assert preflight.restore_authorization(preflight.restore_plan(path, pin)) == intent
    final['data_target']['max_database_bytes'] += 4096
    pin = write_policy(path, final)
    assert preflight.restore_authorization(preflight.restore_plan(path, pin)) != intent
    final['selected']['backup_id'] = uuid()
    pin = write_policy(path, final)
    with pytest.raises(EnvironmentFailure, match=preflight.INVALID):
        preflight.restore_plan(path, pin)


def test_batch_review_keeps_decision_versions_across_data_generations():
    from backend.app.infrastructure.idempotency import generation_namespace
    from backend.app.suggestions.review import GROUP_DECISION, decision_version

    current = generation_namespace(uuid())
    historical = generation_namespace(uuid())
    with closing(sqlite3.connect(':memory:')) as connection:
        connection.execute(
            'CREATE TABLE idempotency_records(capability_id TEXT, target_identity TEXT, status TEXT)'
        )
        connection.execute('CREATE TABLE suggestions(id INTEGER PRIMARY KEY, batch_id INTEGER)')
        connection.execute('INSERT INTO suggestions VALUES (7,1),(8,2)')
        connection.executemany(
            'INSERT INTO idempotency_records VALUES (?, ?, ?)',
            (
                (GROUP_DECISION, 'Batch:1', 'SUCCEEDED'),
                (GROUP_DECISION, historical + 'Batch:1', 'SUCCEEDED'),
                ('APP-BATCH-CMD-C01', current + 'Suggestion:7', 'SUCCEEDED'),
                ('APP-BATCH-CMD-C01', current + 'Suggestion:8', 'SUCCEEDED'),
                (GROUP_DECISION, current + 'Batch:1', 'REJECTED'),
            ),
        )
        assert decision_version(connection, 1) == 4
        assert decision_version(connection, 2) == 2


def test_live_model_policy_is_fixed_to_one_target_tuple(tmp_path):
    policy = tmp_path / 'document-ai-policy.v1.json'
    environment, generation, deployment = uuid(), uuid(), uuid()
    model = {
        'format_version': 1,
        'environment_id': environment,
        'data_generation': generation,
        'deployment_id': deployment,
        'configuration_sha256': PIN,
        'credential': '/run/credentials/isolated-dev.service/openai',
        'local_http_proxy': 'http://127.0.0.1:17890',
        'discussion_release_sha256': '2' * 64,
        'document_release_sha256': '3' * 64,
    }
    pin = write_policy(policy, model)
    scope = {
        'environment': environment,
        'generation': generation,
        'deployment': deployment,
        'configuration': PIN,
    }
    assert read_document_ai_policy(policy, pin, **scope) == model
    for field, different in (
        ('generation', uuid()),
        ('deployment', uuid()),
        ('configuration', 'f' * 64),
    ):
        with pytest.raises(EnvironmentFailure, match='DOCUMENT_AI_POLICY_MISMATCH'):
            read_document_ai_policy(policy, pin, **{**scope, field: different})


def build_release(folder, name, *, document_ai=False):
    path = folder / name
    path.mkdir()
    files = schema.build_candidate(name, PIN, document_ai=document_ai)
    for name, raw in files.items():
        (path / name).write_bytes(raw)
    return path, schema.load_release(path, digest(files[schema.MANIFEST]), PIN)


@pytest.fixture
def databases(tmp_path):
    source_dir = tmp_path / 'backup'
    target_dir = tmp_path / 'prepared'
    source_dir.mkdir(mode=0o700)
    target_dir.mkdir(mode=0o700)
    source_schema, core = build_release(tmp_path, 'development-core')
    target_schema, document_ai = build_release(tmp_path, 'development-ai', document_ai=True)
    source = EnvironmentBinding(uuid(), uuid())
    target = EnvironmentBinding(source.environment_id, uuid())
    source_db = source_dir / SNAPSHOT
    with closing(sqlite3.connect(source_db, isolation_level=None)) as connection:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('BEGIN IMMEDIATE')
        write_initial_schema(connection, core, source)
        connection.execute(
            "INSERT INTO sequences(entity_kind,last_value) VALUES ('requirement',17)"
        )
        connection.commit()
    source_db.chmod(0o400)
    original = restore.reopen_archive(source_db, core, source)[1]
    return SimpleNamespace(
        source_dir=source_dir,
        target_dir=target_dir,
        source_db=source_db,
        core=core,
        source_schema=source_schema,
        target_schema=target_schema,
        document_ai=document_ai,
        source=source,
        target=target,
        original=original,
    )


def test_reopened_package_retains_the_original_and_binds_readiness_to_the_new_database(
    databases,
    monkeypatch,
):
    db = databases
    active = SimpleNamespace(runtime_manifest_sha256=PIN)
    capture = {
        'operation_id': uuid(),
        'environment_id': db.source.environment_id,
        'data_generation': db.source.data_generation,
        'deployment_id': uuid(),
        'control_revision': 5,
        'intent_sha256': PIN,
    }
    artifact = {
        'sha256': digest(db.source_db.read_bytes()),
        'bytes': db.source_db.stat().st_size,
    }
    audit = canonical(
        {
            'format_version': 1,
            'asset_kind': 'COUNTING_AUDIT',
            **capture,
            'database_sha256': artifact['sha256'],
            'state': 'ABSENT',
            'entries': [],
        }
    )
    (db.source_dir / AUDIT_INDEX).write_bytes(audit)
    (db.source_dir / AUDIT_INDEX).chmod(0o400)
    index = {'name': AUDIT_INDEX, 'sha256': digest(audit), 'bytes': len(audit)}
    capture.update(database_artifact=artifact, asset_index=index)
    operation = uuid()
    manifest = {
        'source_environment_id': db.source.environment_id,
        'source_data_generation': db.source.data_generation,
        'source_deployment_id': capture['deployment_id'],
        'database_artifact': artifact,
        'asset_index_ref': index,
        'original_result_index_ref': {'sha256': '8' * 64},
        'logical_content_sha256': db.original.sha256,
        'program_and_configuration_refs': {
            'runtime_manifest_sha256': PIN,
            'schema_manifest_sha256': db.core.manifest_sha256,
            'schema_contract_sha256': db.core.schema_contract_sha256,
        },
    }
    plan = {
        'source_environment_id': db.source.environment_id,
        'target_data_generation': db.target.data_generation,
        'operation_id': operation,
    }
    backup = {'backup_id': capture['operation_id'], 'backup_manifest_sha256': '7' * 64}
    evidence = {
        'capture_receipt_ref': capture,
        'restore_verification_ref': {'target_data_generation': uuid(), 'operation_id': uuid()},
    }
    monkeypatch.setattr(rehearsal, 'verify_contents', lambda *_, **_kwargs: (manifest,))
    monkeypatch.setattr(rehearsal, 'read_evidence', lambda *_: evidence)
    conversion = SimpleNamespace(
        document_ai_schema={'contract_sha256': db.document_ai.schema_contract_sha256},
        maximum_bytes=artifact['bytes'] + 8 * 1024**2,
        release=db.document_ai,
        source_program=schema.ROOT,
    )
    principal = SimpleNamespace(maintenance_uid=os.geteuid(), group=os.getegid())
    with opened(db.source_dir) as source, opened(db.target_dir) as target:
        receipt = rehearsal.data_rehearsal(
            principal,
            db.source_schema,
            source,
            target,
            plan,
            backup,
            active,
            PIN,
            conversion=conversion,
        )
        assert receipt == rehearsal.data_rehearsal(
            principal,
            db.source_schema,
            source,
            target,
            plan,
            backup,
            active,
            PIN,
            conversion=conversion,
        )
        wrong = SimpleNamespace(**vars(conversion))
        wrong.document_ai_schema = {'contract_sha256': 'f' * 64}
        with pytest.raises(EnvironmentFailure, match=rehearsal.UNVERIFIED):
            rehearsal.data_rehearsal(
                principal,
                db.source_schema,
                source,
                target,
                plan,
                backup,
                active,
                PIN,
                conversion=wrong,
            )
    assert receipt['content_sha256'] != db.original.sha256
    assert receipt['restored_asset_index'] == index
    assert receipt['database_artifact']['bytes'] >= artifact['bytes']
    assert digest(db.source_db.read_bytes()) == artifact['sha256']
    target_db = db.target_dir / SNAPSHOT
    with closing(
        sqlite3.connect(target_db.as_uri() + '?mode=ro&immutable=1', uri=True)
    ) as connection:
        assert connection.execute('SELECT last_value FROM sequences').fetchone() == (17,)

    deployment = uuid()
    actual = {
        'operation_id': operation,
        'environment_id': db.source.environment_id,
        'source_control_sha256': PIN,
        'target_data_generation': db.target.data_generation,
        'target_deployment_id': deployment,
        'selected_backup_manifest_sha256': backup['backup_manifest_sha256'],
        'target_restore_receipt_sha256': PIN,
        'target_schema_manifest_sha256': db.document_ai.manifest_sha256,
        'target_program_snapshot_sha256': PIN,
        'target_frontend_index_sha256': PIN,
        'target_database_sha256': receipt['database_artifact']['sha256'],
        'selected_logical_content_sha256': db.original.sha256,
        'target_logical_content_sha256': receipt['content_sha256'],
        'target_configuration_sha256': PIN,
        'target_restored_at': receipt['restored_at'],
        'restore_preflight_sha256': PIN,
        'restore_target_data_sha256': PIN,
    }
    read = {
        'environment_id': db.source.environment_id,
        'data_generation': db.target.data_generation,
        'deployment_id': deployment,
        'backup_id': backup['backup_id'],
        'backup_manifest_sha256': backup['backup_manifest_sha256'],
        'rehearsal_receipt_sha256': PIN,
        'schema_manifest_sha256': db.document_ai.manifest_sha256,
        'program_snapshot_sha256': PIN,
        'frontend_index_sha256': PIN,
        'database_sha256': receipt['database_artifact']['sha256'],
        'logical_content_sha256': receipt['content_sha256'],
        'runtime_manifest_sha256': PIN,
        'configuration_sha256': '9' * 64,
        'verified_at': receipt['restored_at'],
        'verified_scopes': ['DOCUMENT_CONTENT', 'DOCUMENT_HISTORY'],
    }
    proof = {
        'restore_preflight_sha256': PIN,
        'restore_target_data_sha256': PIN,
        'read_verification': {'sha256': PIN},
    }
    args = SimpleNamespace(restore_readiness_policy_sha256=PIN)
    verified = {'selected_backup_id': backup['backup_id']}
    assert (
        readiness.verify_prepared_readiness(args, active, verified, actual, proof, read)[
            'outbound_hold_required'
        ]
        is True
    )
    with pytest.raises(EnvironmentFailure, match=readiness.UNVERIFIED):
        readiness.verify_prepared_readiness(
            args,
            active,
            verified,
            actual,
            proof,
            {**read, 'logical_content_sha256': db.original.sha256},
        )


def test_deployment_configuration_is_fixed_before_and_after_data_preparation(
    databases,
    tmp_path,
    monkeypatch,
):
    from backend.app.infrastructure.environment_installation import ACCESS_NAME

    environment_root = tmp_path / 'environment'
    environment_root.mkdir()
    access_policy = b'configured-access'
    access = environment_root / ACCESS_NAME
    access.write_bytes(access_policy)
    access.chmod(0o440)
    db = databases
    key = uuid()
    operation = uuid()
    source = SimpleNamespace(
        anchor=environment_root / 'installation.v1.json',
        anchor_sha256='2' * 64,
        deployment_id=uuid(),
        configuration_sha256='3' * 64,
        environment_id=db.source.environment_id,
        data_generation=db.source.data_generation,
        environment_root=environment_root,
        project=schema.ROOT,
        schema=db.source_schema,
        roots={'data': identity(environment_root.stat())},
        ingress_group=None,
        restore_generation_sha256=None,
        check_hold=lambda: None,
        description={
            'purpose': 'DEVELOPMENT',
            'program_source': {'sha256': '4' * 64},
            'schema_manifest_sha256': db.core.manifest_sha256,
            'access_policy_ref': {'sha256': digest(access_policy)},
        },
    )
    manifest = {
        'release_id': uuid(),
        'schema_manifest_sha256': db.document_ai.manifest_sha256,
        'frontend_index_ref': {'sha256': '5' * 64},
    }
    target_program_pin = '6' * 64
    plan = {
        'format_version': 1,
        'installation_sha256': source.anchor_sha256,
        'source_deployment_id': source.deployment_id,
        'target_deployment_id': key,
        'target_manifest': {'path': str(tmp_path / 'fixed/manifest.v1.json'), 'sha256': PIN},
        'target_schema_directory': str(db.target_schema),
        'candidate_proof': {},
        'operation_id': operation,
        'target_data_generation': db.target.data_generation,
    }
    policy = tmp_path / deployment.DOCUMENT_AI_POLICY
    args = SimpleNamespace(
        root=tmp_path / 'runtime',
        anchor=source.anchor,
        anchor_sha256=source.anchor_sha256,
        sha256=PIN,
        project=source.project,
        program_sha256=source.description['program_source']['sha256'],
        restore_executor_sha256=target_program_pin,
        release_deployment_policy=policy,
        release_deployment_policy_sha256=write_policy(policy, plan),
    )
    monkeypatch.setattr(deployment, 'load_installation', lambda *_: source)
    monkeypatch.setattr(
        deployment,
        'candidate_target',
        lambda *_: ({}, manifest, db.document_ai, target_program_pin),
    )
    entry = {'verify_program': lambda _: target_program_pin}
    described = deployment.describe_restore_deployment(args, entry)
    assert described['outbound_hold_required'] is True
    receipt = {
        'operation_id': operation,
        'target_deployment_id': key,
        'target_configuration_sha256': described['target_configuration_sha256'],
        'data_identity': identity(db.target_dir.stat()),
        'document_ai_schema_contract_sha256': db.document_ai.schema_contract_sha256,
    }
    monkeypatch.setattr(deployment, 'read_restore_generation', lambda *_: (receipt, PIN))
    ready = deployment.prepare_target(args, entry)
    assert digest(canonical(ready.description)) == described['target_configuration_sha256']
    assert ready.description['data_generation'] == db.target.data_generation
    receipt['document_ai_schema_contract_sha256'] = PIN
    with pytest.raises(EnvironmentFailure, match=deployment.UNVERIFIED):
        deployment.prepare_target(args, entry)
    args.restore_executor_sha256 = PIN
    with pytest.raises(EnvironmentFailure, match=deployment.INVALID):
        deployment.describe_restore_deployment(args, entry)
    args.restore_executor_sha256 = target_program_pin
    source.description['purpose'] = 'INTEGRATION'
    with pytest.raises(EnvironmentFailure, match=deployment.INVALID):
        deployment.describe_restore_deployment(args, entry)


@pytest.mark.parametrize('selection_visible', [False, True])
def test_closed_selection_can_revert_once_without_discarding_either_database(
    databases,
    tmp_path,
    monkeypatch,
    selection_visible,
):
    from backend.app.infrastructure.environment_installation import (
        GENERATION_RECEIPT,
        RESTORE_MODE,
        restored_data_root,
    )

    db = databases
    operation = uuid()
    runtime = tmp_path / 'runtime'
    stable = tmp_path / 'environment'
    control_dir = tmp_path / 'control'
    runtime.mkdir()
    control_dir.mkdir()
    db.source_db.chmod(0o660)
    target_root = restored_data_root(stable, db.target.data_generation)
    target_root.mkdir(parents=True)
    target_db = target_root / SNAPSHOT
    target_db.touch(mode=0o600, exist_ok=False)
    restore.prepare_document_ai_target(
        db.source_db,
        target_db,
        db.core,
        db.document_ai,
        db.source,
        db.target,
        restore.archived_document_ai_source(db.source_db, db.core, db.source),
        64 * 1024**2,
        operation,
    )
    target_db.chmod(0o660)
    _, after_facts = restore.reopen_archive(target_db, db.document_ai, db.target)
    original_digest = digest(db.source_db.read_bytes())
    target_digest = digest(target_db.read_bytes())

    @contextmanager
    def locked(_native):
        import fcntl

        with (tmp_path / 'lock').open('a+b') as file:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield SimpleNamespace(assert_owned=lambda: None)

    def installation(binding, file, release, schema_dir, anchor_pin, config_pin):
        directories = {'data': file.parent, 'control': control_dir, 'runtime': runtime}
        return SimpleNamespace(
            environment_id=binding.environment_id,
            data_generation=binding.data_generation,
            deployment_id=uuid(),
            configuration_sha256=config_pin,
            anchor_sha256=anchor_pin,
            database=file,
            database_relative=Path(file.name),
            schema=schema_dir,
            project=schema.ROOT,
            environment_root=stable,
            restore_generation_sha256=None,
            document_ai_policy_sha256=None,
            description={
                'purpose': 'DEVELOPMENT',
                'program_source': {'sha256': PIN},
                'runtime_manifest_sha256': PIN,
                'schema_manifest_sha256': release.manifest_sha256,
            },
            check_hold=lambda: None,
            lock=locked,
            host_admission=nullcontext,
            directory=lambda _native, kind: opened(directories[kind]),
            path=lambda kind: directories[kind],
            group=os.getegid(),
            maintenance_uid=os.geteuid(),
            application_uid=os.geteuid(),
        )

    source = installation(db.source, db.source_db, db.core, db.source_schema, '2' * 64, '3' * 64)
    target = installation(
        db.target, target_db, db.document_ai, db.target_schema, '4' * 64, '5' * 64
    )
    target.description['deployment_slot'] = {
        'authorization_mode': RESTORE_MODE,
        'source_deployment_id': source.deployment_id,
        'source_configuration_sha256': source.configuration_sha256,
    }
    initial = {**control.initial_control(source, uuid()), 'control_revision': 6}
    frozen = control.maintained_control(initial, operation, PIN)
    control_path = control_dir / control.CONTROL_NAME
    write_policy(control_path, frozen, mode=0o640)
    write_policy(
        control_dir / control.maintenance_name(operation),
        {
            'format_version': 1,
            'operation_id': operation,
            'plan_sha256': PIN,
            'before_sha256': digest(canonical(initial)),
            'before': initial,
        },
    )
    source_identity = identity(db.source_db.stat())
    target_identity = identity(target_db.stat())
    generation = {
        'format_version': 1,
        'status': 'RESTORE_GENERATION_PREPARED_CLOSED',
        'operation_id': operation,
        'environment_id': source.environment_id,
        'source_control_sha256': digest(canonical(frozen)),
        'target_configuration_sha256': target.configuration_sha256,
        'target_database_sha256': target_digest,
        'target_asset_index_sha256': PIN,
        'restore_target_data_sha256': PIN,
        'restore_readiness_sha256': PIN,
        'generation_policy_sha256': PIN,
        'source_database_identity': source_identity,
        'target_data_generation': target.data_generation,
        'target_deployment_id': target.deployment_id,
        'data_root': str(target_root),
        'outbound_hold_required': True,
        'data_identity': identity(target_root.stat()),
        'database_identity': target_identity,
        'document_ai_schema_contract_sha256': db.document_ai.schema_contract_sha256,
        'source_logical_content_sha256': db.original.sha256,
        'target_logical_content_sha256': after_facts.sha256,
        'document_ai_policy_sha256': '8' * 64,
    }
    target.restore_generation_sha256 = write_policy(
        target_root.parent / GENERATION_RECEIPT, generation
    )
    target.document_ai_policy_sha256 = generation['document_ai_policy_sha256']
    assert not control.initial_control(target, operation)['outbound_hold']
    selection = switch.ReleaseSelection(
        PIN,
        operation,
        source,
        target,
        SimpleNamespace(release_preflight_policy_sha256=PIN),
        PIN,
    )
    with opened(control_dir) as fd, locked(None) as lock:
        selected = switch.commit_selection(
            selection,
            frozen,
            fd,
            lock,
            backup_manifest_sha256=PIN,
            preserved_result_index_sha256=PIN,
            selected_backup_manifest_sha256=PIN,
            selected_result_index_sha256=PIN,
            selected_source_data_generation=source.data_generation,
            logical_content_sha256=after_facts.sha256,
            database_identity=target_identity,
            source_database_identity=source_identity,
            source_logical_content_sha256=db.original.sha256,
            restore_generation_sha256=target.restore_generation_sha256,
        )
        assert control.read_control(fd, target)['outbound_hold'] is True
    active = SimpleNamespace(runtime_manifest_sha256=PIN)
    selected_control = control_path.read_bytes()
    write_policy(
        control_path,
        {
            **control.initial_control(target, operation),
            'control_revision': selected['control_revision'] + 1,
            'admission': 'OPEN',
            'closed_reason': 'NONE',
        },
        mode=0o640,
    )
    with pytest.raises(EnvironmentFailure, match=switch.DIFFERENT):
        restore_switch.revert_closed_document_ai(None, active, selection)
    pending_control = selected_control if selection_visible else canonical(frozen)
    control_path.write_bytes(pending_control)

    with monkeypatch.context() as failure:

        def lost_write(*_args, **_options):
            raise OSError('simulated interruption before publishing control')

        failure.setattr(restore_switch, 'persisted_write', lost_write)
        with pytest.raises(OSError, match='simulated interruption'):
            restore_switch.revert_closed_document_ai(None, active, selection)
    assert control_path.read_bytes() == pending_control
    with opened(control_dir) as fd:
        transition = switch.original_transition(fd, selection)
        with pytest.raises(EnvironmentFailure, match=switch.DIFFERENT):
            control.require_release_not_reverting(fd, transition, switch.DIFFERENT)

    result = restore_switch.revert_closed_document_ai(None, active, selection)
    assert result == restore_switch.revert_closed_document_ai(None, active, selection)
    with opened(control_dir) as fd:
        assert control.read_control(fd, source) == {
            **initial,
            'control_revision': result['control_revision'],
        }
    assert result['control_revision'] == selected['control_revision'] + 1
    assert digest(db.source_db.read_bytes()) == original_digest
    assert digest(target_db.read_bytes()) == target_digest
