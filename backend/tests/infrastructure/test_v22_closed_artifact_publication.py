"""A host freeze cannot interrupt publication of a closed release or recovery artifact."""

import json
import os
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.infrastructure.environment_files import EnvironmentFailure
from backend.app.infrastructure.environment_host_hold import BUSY, HOLD


class PublicationHost:
    def __init__(self):
        self.frozen = False
        self.admitted = False

    def check_hold(self):
        if self.frozen:
            raise EnvironmentFailure(HOLD)

    @contextmanager
    def host_admission(self):
        self.check_hold()
        assert not self.admitted
        self.admitted = True
        try:
            yield
        finally:
            self.admitted = False

    def freeze(self):
        if self.admitted:
            raise EnvironmentFailure(BUSY)
        self.frozen = True


@pytest.fixture(params=('deployment', 'generation', 'replica'))
def publication(request, tmp_path, monkeypatch):
    pytest.importorskip('fcntl')
    from backend.app.infrastructure import environment_recovery_installation as replica
    from backend.app.infrastructure import environment_recovery_restore as restore
    from backend.app.infrastructure import environment_release_deployment as deployment
    from backend.app.infrastructure import environment_restore_generation as generation

    root = tmp_path / 'environment'
    root.mkdir()
    host = PublicationHost()
    source = SimpleNamespace(
        environment_root=root,
        check_hold=host.check_hold,
        host_admission=host.host_admission,
        maintenance_uid=11205,
        group=11200,
    )
    target_id = str(uuid4())
    modules = {'deployment': deployment, 'generation': generation, 'replica': replica}
    module = modules[request.param]
    containers = {
        'deployment': deployment.DEPLOYMENTS,
        'generation': generation.GENERATIONS,
        'replica': 'replica-host',
    }
    parent = root / containers[request.param]
    parent.mkdir()
    final = parent / target_id
    source.environment_id = target_id
    observations = SimpleNamespace(
        host=host,
        parent=parent,
        final=final,
        freeze_after_preflight=False,
        freeze_after_staging=False,
        freeze_during_publish=False,
        fail_sync=False,
        renames=[],
        syncs=[],
        host_initializations=[],
    )
    args = SimpleNamespace(root=tmp_path, sha256='a' * 64, anchor_sha256='b' * 64)

    def sync(directory):
        if not final.exists():
            return
        observations.syncs.append(host.admitted)
        if observations.fail_sync:
            observations.fail_sync = False
            raise OSError('directory sync interrupted after rename')

    def publish(staging, target):
        assert target == final
        observations.renames.append(host.admitted)
        if observations.freeze_during_publish:
            try:
                host.freeze()
            except EnvironmentFailure as error:
                assert error.code == BUSY
        staging.rename(target)

    def stage(staging):
        staging.mkdir()
        if observations.freeze_after_staging:
            host.freeze()

    def finish_preflight():
        host.check_hold()
        if observations.freeze_after_preflight:
            host.freeze()

    monkeypatch.setattr(module, 'protected_directory', nullcontext)
    monkeypatch.setattr(module, 'check_ext4', lambda _: None)
    monkeypatch.setattr(
        module,
        'os',
        SimpleNamespace(
            geteuid=lambda: 0,
            path=os.path,
            fsync=sync,
            fstat=lambda _: SimpleNamespace(st_uid=0, st_gid=0, st_dev=3, st_ino=6, st_mode=0o755),
            listdir=os.listdir,
        ),
    )
    monkeypatch.setattr(
        module, 'fcntl', SimpleNamespace(flock=lambda *_: None, LOCK_SH=1, LOCK_EX=2, LOCK_NB=4)
    )
    monkeypatch.setattr(module, 'publish_directory', publish)

    if module is deployment:
        target = SimpleNamespace(source=source, deployment_id=target_id)

        def prepare_target(*_):
            finish_preflight()
            return target

        def read_prepared(path, *_):
            assert path == final
            return {'target': path, 'inode': path.stat().st_ino}

        monkeypatch.setattr(module, 'prepare_target', prepare_target)
        monkeypatch.setattr(module, 'NativeEnvironmentFiles', lambda _: object())
        monkeypatch.setattr(module, 'check_stable_resources', lambda *_: None)
        monkeypatch.setattr(module, 'stage_deployment', lambda path, _: stage(path))
        monkeypatch.setattr(module, 'read_prepared', read_prepared)
        observations.prepare = lambda: module.prepare_deployment(args, {})
    elif module is generation:
        prepared = dict.fromkeys(
            (
                'target_data_identity',
                'target_restore_receipt_sha256',
                'operation_id',
                'environment_id',
                'source_control_sha256',
                'source_database_identity',
                'target_deployment_id',
                'target_configuration_sha256',
                'target_database_sha256',
                'target_asset_index_sha256',
                'restore_target_data_sha256',
            ),
            'original',
        )
        prepared['target_data_generation'] = target_id
        ready = {'restore_readiness_sha256': 'a' * 64}
        artifact = {'bytes': 50, 'identity': 'original'}
        restored = {'database_artifact': artifact}

        def lock_source(*_, **kwargs):
            finish_preflight()
            return SimpleNamespace(assert_owned=lambda: None)

        def populate(path, *_):
            stage(path)
            (path / 'data').mkdir()

        monkeypatch.setattr(
            module, 'generation_plan', lambda _: (source, prepared, ready, root, None)
        )
        monkeypatch.setattr(module, 'lock_frozen_source', lock_source)
        monkeypatch.setattr(module, 'private_root', lambda *_: nullcontext(root))
        monkeypatch.setattr(module, 'rehearsal_receipt', lambda *_, **kwargs: (restored, b''))
        monkeypatch.setattr(module, 'match_prepared_archive', lambda *_, **kwargs: None)
        monkeypatch.setattr(module, 'sealed_audit', lambda *_: ())
        monkeypatch.setattr(module, 'populate_generation', populate)
        monkeypatch.setattr(
            module, 'read_generation', lambda path, *_: {'inode': path.stat().st_ino}
        )
        monkeypatch.setattr(module, 'snapshot_artifact', lambda *_, **kwargs: artifact)
        monkeypatch.setattr(module, 'audit_matches', lambda *_, **kwargs: None)
        monkeypatch.setattr(module, 'read_protected', Path.read_bytes)
        monkeypatch.setattr(
            module,
            'persisted_write',
            lambda directory, name, raw, **kwargs: (directory / name).write_bytes(raw),
        )
        observations.prepare = lambda: module.prepare_restore_generation(args, {}, ())
    else:
        staging = root / 'staging'
        staging.mkdir()
        target = SimpleNamespace(host_root=parent, frontend_input=root, restore_preparation={})
        plan = {
            'host_identity': {'device': '3', 'inode': '6'},
            'staging_identity': {'device': '3', 'inode': '6'},
            'deployment_id': str(uuid4()),
            'rehearsal': {'identity': {}, 'receipt_sha256': 'c' * 64},
        }

        def source_lock(*_):
            finish_preflight()
            return SimpleNamespace(assert_owned=lambda: None)

        def initialize_host(*_):
            observations.host_initializations.append(host.admitted)

        def read_replica(path, *_):
            assert path == final
            return {'inode': path.stat().st_ino}

        def fstat(path):
            mode = 0o700 if path == staging else 0o755
            return SimpleNamespace(st_uid=0, st_gid=0, st_dev=3, st_ino=6, st_mode=mode)

        monkeypatch.setattr(module.os, 'fstat', fstat)
        monkeypatch.setattr(
            module, 'load_plan', lambda _: (plan, source, root, target, staging, b'{}\n')
        )
        monkeypatch.setattr(module, 'indexed_files', lambda *_: None)
        monkeypatch.setattr(module, 'installer_lock', lambda path, **_: nullcontext(path))
        monkeypatch.setattr(module, 'no_acl', lambda _: None)
        monkeypatch.setattr(module, 'private_root', lambda *_: nullcontext(root))
        monkeypatch.setattr(
            module,
            'rehearsal_receipt',
            lambda *_, **__: ({'target_data_generation': target_id}, b''),
        )
        monkeypatch.setattr(module, 'replica_binding', lambda *_: {})
        monkeypatch.setattr(module, '_initialize_host', initialize_host)
        monkeypatch.setattr(module, '_reserve_identities', lambda _: None)
        monkeypatch.setattr(
            module, 'create_installation_files', lambda *_, staging, **__: stage(staging)
        )
        monkeypatch.setattr(
            module, 'prepare_contents', lambda work, *_: {'inode': work.stat().st_ino}
        )
        monkeypatch.setattr(module, 'read_prepared', read_replica)
        monkeypatch.setattr(restore, 'lock_frozen_source', source_lock)
        monkeypatch.setattr(restore, 'match_prepared_archive', lambda *_: None)
        observations.prepare = lambda: module.prepare_recovery_replica(args, {}, ())
        observations.target = target
    return observations


def test_host_freeze_is_excluded_from_rename_and_directory_sync(publication):
    publication.freeze_during_publish = True
    result = publication.prepare()
    assert publication.final.exists()
    assert result['inode'] == publication.final.stat().st_ino
    assert publication.renames == [True]
    if hasattr(publication, 'target'):
        assert publication.host_initializations == [True]
    assert publication.syncs == [True, True]
    publication.host.freeze()
    assert publication.host.frozen


def test_frozen_host_cannot_leave_a_fixed_target_after_private_staging(publication):
    publication.freeze_after_staging = True
    with pytest.raises(EnvironmentFailure, match=HOLD):
        publication.prepare()
    assert not publication.final.exists()
    assert not list(publication.parent.iterdir())
    assert not publication.renames
    assert not publication.host_initializations


def test_detached_rehearsal_does_not_need_original_host_admission(publication):
    if not hasattr(publication, 'target'):
        pytest.skip('independent rehearsal applies to recovery replicas')
    publication.target.restore_preparation = None
    publication.host.freeze()
    assert publication.prepare()['inode'] == publication.final.stat().st_ino
    assert publication.renames == [False]
    assert publication.host_initializations == [False]


def test_freeze_before_first_parent_publication_leaves_no_directory(publication):
    if hasattr(publication, 'target'):
        publication.freeze_after_preflight = True
        with pytest.raises(EnvironmentFailure, match=HOLD):
            publication.prepare()
        assert not publication.final.exists()
        assert not publication.host_initializations
        return
    publication.parent.rmdir()
    publication.freeze_after_preflight = True
    with pytest.raises(EnvironmentFailure, match=HOLD):
        publication.prepare()
    assert not publication.parent.exists()


def test_original_target_replays_after_directory_sync_interruption(publication):
    publication.fail_sync = True
    with pytest.raises(EnvironmentFailure) as raised:
        publication.prepare()
    assert raised.value.uncertain
    assert publication.final.exists()
    before = publication.final.stat().st_ino
    assert publication.prepare()['inode'] == before
    assert len(publication.renames) == 1


@pytest.fixture(params=('prepared', 'local'))
def restore_receipt(request, tmp_path, monkeypatch):
    pytest.importorskip('fcntl')
    from backend.app.infrastructure import environment_backup_rehearsal as rehearsal
    from backend.app.infrastructure import environment_restore as restore
    from backend.app.infrastructure import environment_restore_preparation as preparation

    host = PublicationHost()
    source_root = tmp_path / 'source'
    source_root.mkdir()
    target_root = tmp_path / 'target'
    target_root.mkdir()
    observations = SimpleNamespace(
        host=host,
        receipt=target_root / restore.RECEIPT,
        private_copy=target_root / 'private-copy.sqlite',
        freezes_during_receipt=False,
        freezes_after_private_copy=False,
        receipt_admission=[],
    )
    identities = {
        key: str(uuid4()) for key in ('environment_id', 'data_generation', 'deployment_id')
    }
    common = {
        'operation_id': str(uuid4()),
        'source_environment_id': identities['environment_id'],
        'target_data_generation': str(uuid4()),
    }
    control = {'control_revision': 4, 'admission': 'CLOSED', 'outbound_hold': True}
    lock = SimpleNamespace(assert_owned=lambda: None)
    installation = SimpleNamespace(
        **identities,
        maintenance_uid=11205,
        group=11200,
        lock=lambda _: nullcontext(lock),
        directory=lambda *_: nullcontext(source_root),
        check_hold=host.check_hold,
        check_identity=lambda **_: None,
        host_admission=host.host_admission,
    )
    capture = {
        'installation_sha256': 'a' * 64,
        'source_program': str(source_root / 'app'),
        'source_program_sha256': 'b' * 64,
        'control_revision': 4,
    }
    plan = {
        **{f'source_{key}': value for key, value in identities.items()},
        'format_version': 2,
        'capture_policy': {'sha256': 'c' * 64},
        'expected_database_sha256': 'd' * 64,
        'expected_asset_index_sha256': 'e' * 64,
    }
    proof = {
        'database_artifact': {'sha256': plan['expected_database_sha256']},
        'asset_index': {'sha256': plan['expected_asset_index_sha256']},
    }
    facts = '2026-11-24T15:11:00.000Z', SimpleNamespace(sha256='f' * 64)

    def convert(*_, **_options):
        observations.private_copy.write_bytes(b'private target')
        if observations.freezes_after_private_copy:
            host.freeze()
        return facts, proof['database_artifact']

    def read_receipt(*_):
        if not observations.receipt.exists():
            return None
        return json.loads(observations.receipt.read_bytes())

    def persist(directory, name, raw, *, mode):
        assert directory == target_root and name == restore.RECEIPT and mode == 0o400
        observations.receipt_admission.append(host.admitted)
        if observations.freezes_during_receipt:
            try:
                host.freeze()
            except EnvironmentFailure as error:
                assert error.code == BUSY
        observations.receipt.write_bytes(raw)

    def read_control(*_):
        return control

    monkeypatch.setattr(restore, 'read_control', read_control)
    monkeypatch.setattr(preparation, 'read_control', read_control)
    module = rehearsal if request.param == 'prepared' else restore
    monkeypatch.setattr(module, 'completed', read_receipt)
    monkeypatch.setattr(module, 'convert', convert)
    monkeypatch.setattr(module, 'persisted_write', persist)
    monkeypatch.setattr(module, 'restore_count_audit', lambda *_: proof['asset_index'])

    if request.param == 'prepared':
        manifest = {
            'logical_content_sha256': facts[1].sha256,
            'original_result_index_ref': {'sha256': 'a' * 64},
        }
        backup = {'backup_id': str(uuid4()), 'backup_manifest_sha256': 'a' * 64}
        source = SimpleNamespace(
            installation=installation, lock=lock, control_fd=source_root, control=control
        )
        target = SimpleNamespace(
            verified=SimpleNamespace(
                receipt={'selected_result_index_sha256': 'a' * 64},
                source=source,
                document_ai_schema=None,
            ),
            principal=installation,
            schema=object(),
            selected_fd=source_root,
            target_fd=target_root,
            plan=plan,
            backup=backup,
            policy_sha256='a' * 64,
            conversion=lambda: None,
        )

        def restore_result(_, receipt):
            host.check_hold()
            return receipt

        monkeypatch.setattr(module, 'verify_contents', lambda *_, **kwargs: (manifest,))
        monkeypatch.setattr(module, 'read_evidence', lambda *_: {'capture_receipt_ref': 'archived'})
        monkeypatch.setattr(
            module, 'recovery_contract', lambda *_, **options: (plan, capture, dict(common))
        )
        monkeypatch.setattr(module, 'pinned_schema', lambda *_: object())
        monkeypatch.setattr(module, 'anchored_path', lambda path: path)
        monkeypatch.setattr(module, 'reopen_archive', lambda *_: facts)
        monkeypatch.setattr(module, 'os', SimpleNamespace(listdir=os.listdir, fsync=lambda _: None))
        monkeypatch.setattr(preparation, 'restore_data_result', restore_result)
        monkeypatch.setattr(preparation, 'locked_restore_target', lambda *_: nullcontext(target))
        observations.prepare = lambda: preparation.prepare_restore_data(None, None, None, None)
        observations.rehearse = lambda: module.data_rehearsal(
            installation, None, source_root, target_root, plan, backup, None, 'a' * 64
        )
    else:
        args = SimpleNamespace(
            anchor=source_root,
            anchor_sha256=capture['installation_sha256'],
            restore_policy=source_root / 'restore-policy.v1.json',
            restore_sha256='c' * 64,
        )
        entry = {'verify_program': lambda _: capture['source_program_sha256']}

        def recovery_directory(destination, _):
            path = target_root if destination is target_root else source_root
            return nullcontext((path, path))

        monkeypatch.setattr(module, 'load_restore', lambda *_: (plan, capture))

        def admission_inputs(*_, offline=False):
            if not offline:
                host.check_hold()
            return installation, object()

        monkeypatch.setattr(module, 'admission_inputs', admission_inputs)
        monkeypatch.setattr(module, 'planned_restore', lambda *_: (target_root, common))
        monkeypatch.setattr(module, 'recovery_directory', recovery_directory)
        monkeypatch.setattr(module, 'stopped_for_policy', lambda *_: True)
        monkeypatch.setattr(module, 'original_receipt', lambda *_: proof)
        observations.prepare = lambda: module.restore_database(None, None, args, entry)
    return observations


def test_restore_receipt_excludes_freeze_during_publication(restore_receipt):
    restore_receipt.freezes_during_receipt = True
    first = restore_receipt.prepare()
    assert restore_receipt.receipt.exists()
    assert first == restore_receipt.prepare()
    assert restore_receipt.receipt_admission == [True]
    restore_receipt.host.freeze()


def test_freeze_after_private_restore_copy_blocks_completion_receipt(restore_receipt):
    restore_receipt.freezes_after_private_copy = True
    with pytest.raises(EnvironmentFailure):
        restore_receipt.prepare()
    assert restore_receipt.private_copy.exists()
    assert not restore_receipt.receipt.exists()
    assert restore_receipt.receipt_admission == []


@pytest.mark.parametrize('restore_receipt', ['prepared'], indirect=True)
def test_independent_backup_rehearsal_does_not_require_source_host_admission(restore_receipt):
    restore_receipt.host.freeze()
    result = restore_receipt.rehearse()
    assert result['status'] == 'BACKUP_PACKAGE_DATA_REHEARSED'
    assert restore_receipt.receipt_admission == [False]


@pytest.fixture
def capture_receipt(tmp_path, monkeypatch):
    pytest.importorskip('fcntl')
    from backend.app.infrastructure import environment_backup as backup

    host = PublicationHost()
    target = tmp_path / 'archive'
    target.mkdir()
    state = SimpleNamespace(
        host=host,
        receipt=target / backup.RECEIPT,
        snapshot=target / backup.SNAPSHOT,
        before_receipt=False,
        during_receipt=False,
        writes=[],
    )
    plan = {
        'format_version': 2,
        'control_revision': 8,
        **{key: str(uuid4()) for key in ('environment_id', 'data_generation', 'deployment_id')},
        'operation_id': str(uuid4()),
    }
    stopped = {'admission': 'CLOSED', 'control_revision': plan['control_revision']}
    lock = SimpleNamespace(assert_owned=lambda: None)
    installation = SimpleNamespace(
        lock=lambda _: nullcontext(lock),
        directory=lambda *_: nullcontext(tmp_path),
        check_hold=host.check_hold,
        host_admission=host.host_admission,
    )

    def read_receipt(*_):
        if state.receipt.exists():
            return json.loads(state.receipt.read_bytes())
        return None

    def copy_database(*_):
        state.snapshot.write_bytes(b'private consistent backup')
        return '2026-11-24T15:35:00.000Z', {'sha256': 'b' * 64}

    def verify_audit(*_):
        if state.before_receipt:
            host.freeze()
        return ()

    def write_capture(directory, name, raw, *, mode):
        assert directory == target and name == backup.RECEIPT and mode == 0o400
        state.writes.append(host.admitted)
        if state.during_receipt:
            try:
                host.freeze()
            except EnvironmentFailure as error:
                assert error.code == BUSY
        state.receipt.write_bytes(raw)

    def capture_inputs(*_, offline=False):
        if not offline:
            host.check_hold()
        return plan, installation, object()

    monkeypatch.setattr(backup, 'capture_inputs', capture_inputs)
    monkeypatch.setattr(backup, 'recovery_directory', lambda *_: nullcontext((target, target)))
    monkeypatch.setattr(backup, 'original_receipt', read_receipt)
    monkeypatch.setattr(backup, 'read_control', lambda *_: stopped)
    monkeypatch.setattr(backup, 'stopped_for_policy', lambda *_: True)
    monkeypatch.setattr(backup, 'copy_database', copy_database)
    monkeypatch.setattr(backup, 'capture_count_audit', lambda *_: {'audit': 'captured'})
    monkeypatch.setattr(backup, 'verify_count_audit', verify_audit)
    monkeypatch.setattr(backup, 'persisted_write', write_capture)
    args = SimpleNamespace(capture_sha256='a' * 64)
    state.capture = lambda: backup.capture_database(None, None, args, None)
    return state


def test_database_capture_preserves_original_receipt_and_blocks_freeze_at_commit(capture_receipt):
    capture_receipt.during_receipt = True
    receipt = capture_receipt.capture()
    assert capture_receipt.capture() == receipt
    assert capture_receipt.writes == [True]
    assert capture_receipt.receipt.exists()
    capture_receipt.host.freeze()


def test_freeze_after_copy_and_audit_prevents_capture_success(capture_receipt):
    capture_receipt.before_receipt = True
    with pytest.raises(EnvironmentFailure) as failure:
        capture_receipt.capture()
    assert failure.value.uncertain
    assert capture_receipt.snapshot.read_bytes() == b'private consistent backup'
    assert not capture_receipt.receipt.exists()
    assert capture_receipt.writes == []


def test_frozen_host_reads_only_the_original_completed_capture(capture_receipt):
    original = capture_receipt.capture()
    receipt = capture_receipt.receipt.read_bytes()
    capture_receipt.host.freeze()
    assert capture_receipt.capture() == original
    assert capture_receipt.receipt.read_bytes() == receipt
    assert capture_receipt.writes == [True]


@pytest.mark.parametrize('restore_receipt', ['local'], indirect=True)
def test_frozen_host_reads_only_the_original_completed_restore(restore_receipt):
    original = restore_receipt.prepare()
    receipt = restore_receipt.receipt.read_bytes()
    restore_receipt.host.freeze()
    assert restore_receipt.prepare() == original
    assert restore_receipt.receipt.read_bytes() == receipt
    assert restore_receipt.receipt_admission == [True]


def test_frozen_host_blocks_new_capture_before_copy(capture_receipt):
    capture_receipt.host.freeze()
    with pytest.raises(EnvironmentFailure, match=HOLD):
        capture_receipt.capture()
    assert not capture_receipt.snapshot.exists()
    assert not capture_receipt.receipt.exists()


@pytest.mark.parametrize('restore_receipt', ['local'], indirect=True)
def test_frozen_host_blocks_new_restore_before_copy(restore_receipt):
    restore_receipt.host.freeze()
    with pytest.raises(EnvironmentFailure, match=HOLD):
        restore_receipt.prepare()
    assert not restore_receipt.private_copy.exists()
    assert not restore_receipt.receipt.exists()


def test_restore_marker_read_never_creates_a_missing_target(monkeypatch):
    pytest.importorskip('fcntl')
    from backend.app.infrastructure import environment_restore as restore

    def unexpected(*_):
        pytest.fail('A completed archive read attempted to prepare a target.')

    monkeypatch.setattr(restore, 'read_local', lambda *_: None)
    monkeypatch.setattr(restore, 'os', SimpleNamespace(listdir=unexpected, open=unexpected))
    with pytest.raises(EnvironmentFailure, match=restore.UNVERIFIED):
        restore.target_marker(None, None, {})
