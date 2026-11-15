"""Real NTFS/private-package/SQLite offline engine on owned nonempty 151 copies."""

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import os
from uuid import uuid4

import pytest

from backend.app.infrastructure import schema_v20_upgrade as engine
from backend.app.infrastructure.database import Database, CommitOutcomeUnknown, SchemaMismatch
from backend.app.infrastructure.data_retention import capture_retained_data, inspect_v151_source
from backend.app.infrastructure.idempotency import Idempotency
from backend.app.infrastructure.process_lock import ProcessAlreadyRunning
from backend.app.infrastructure.schema_v20_release import (
    build_candidate,
    _load_verified_release,
    digest,
)
from backend.app.infrastructure.windows_private_package import create_private_package
from backend.tests.requirements.test_v15_foundation import tmp_path, setup, create
from backend.tests.documents.test_v15_documents import workspace
from backend.tests.infrastructure.test_v20_schema_migration import seeded_source


@pytest.fixture(scope='module')
def release():
    with TemporaryDirectory(
        prefix='v20-upgrade-release-', dir=os.environ['WALLE_CHECK_TEMP']
    ) as directory:
        root = Path(directory)
        files = build_candidate('upgrade-test')
        for name, content in files.items():
            with (root / name).open('xb') as stream:
                stream.write(content)
        yield _load_verified_release(root, digest(files['manifest.json']))


@pytest.fixture
def offline(workspace, tmp_path, release):
    original = seeded_source(workspace)
    package = create_private_package(tmp_path / 'private-maintenance')
    working = workspace[0].backup_to(package / 'isolated-working.sqlite')
    # It is an owned test copy; normal operators must first seal plan/backups/rehearsal.
    with engine.MaintenanceSession(
        working, package, release, maintenance_window_confirmed=True
    ) as session:
        with session.database.transaction() as connection:
            retained = capture_retained_data(connection)
        intent = engine.UpgradeIntent(
            str(uuid4()), release.manifest_sha256, session.source_guard.identity, retained
        )
        yield session, intent, workspace[0], original


def test_real_rebuild_and_same_identity_reentry_reopen_without_second_ddl(offline):
    session, intent, source, original = offline
    assert engine.recover_locked(session, intent).status == 'NOT_APPLIED'
    first = engine.rebuild_locked(session, intent)
    assert first.status == 'UPGRADED'
    assert first.retained_data_matches is True
    with patch.object(
        engine, '_commit_once', side_effect=AssertionError('No second migration commit')
    ):
        repeat = engine.rebuild_locked(session, intent)
    assert repeat.status == 'ALREADY_COMMITTED'
    assert repeat.committed_at == first.committed_at
    assert repeat.retained_data_matches is True
    with Database(
        session.database.path, schema_release=session.release
    ).transaction() as connection:
        assert [
            row[0]
            for row in connection.execute('SELECT version FROM schema_migrations ORDER BY version')
        ] == [151, 200]
        assert connection.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert connection.execute('PRAGMA synchronous').fetchone()[0] == 2
        assert connection.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
    assert inspect_v151_source(source).data == original


def test_failure_after_table_rebuild_rolls_back_every_schema_and_old_value(offline):
    session, intent, source, original = offline
    with patch.object(
        engine, '_save_marker', side_effect=RuntimeError('Injected before marker commit')
    ):
        with pytest.raises(RuntimeError, match='Injected'):
            engine.rebuild_locked(session, intent)
    with session.database.transaction() as connection:
        assert capture_retained_data(connection) == intent.retained
    assert engine.recover_locked(session, intent).status == 'NOT_APPLIED'
    assert inspect_v151_source(source).data == original


def test_lost_upgrade_commit_ack_is_resolved_from_original_marker_without_retry(offline):
    session, intent, source, original = offline
    calls = []

    def lost(connection):
        calls.append('commit')
        connection.commit()
        raise CommitOutcomeUnknown('Injected after durable original commit')

    with patch.object(engine, '_commit_once', lost):
        with pytest.raises(CommitOutcomeUnknown):
            engine.rebuild_locked(session, intent)
        recovered = engine.recover_locked(session, intent)
        assert recovered.status == 'ALREADY_COMMITTED'
        assert recovered.retained_data_matches is True
        assert engine.rebuild_locked(session, intent).status == 'ALREADY_COMMITTED'
    assert calls == ['commit']
    assert inspect_v151_source(source).data == original


def test_changed_source_is_preserved_and_old_plan_cannot_apply(offline):
    session, intent, source, original = offline
    with session.database.transaction(write=True) as connection:
        connection.execute("UPDATE requirements SET title='计划后变更' WHERE id=1")
    before = engine.recover_locked(session, intent)
    assert before.status == 'UNKNOWN' and before.reason_code == 'SOURCE_CHANGED'
    with pytest.raises(SchemaMismatch, match='SOURCE_CHANGED'):
        engine.rebuild_locked(session, intent)
    with session.database.transaction() as connection:
        assert (
            connection.execute('SELECT title FROM requirements WHERE id=1').fetchone()[0]
            == '计划后变更'
        )
        assert connection.execute('SELECT max(version) FROM schema_migrations').fetchone()[0] == 151
    assert inspect_v151_source(source).data == original


def test_different_upgrade_or_file_or_release_cannot_borrow_an_existing_commit(offline):
    session, intent, source, original = offline
    for invalid in (
        replace(intent, release_manifest_sha256='0' * 64),
        replace(intent, source_identity=replace(intent.source_identity, file_id='0' * 32)),
    ):
        with pytest.raises(SchemaMismatch):
            engine.rebuild_locked(session, invalid)
    engine.rebuild_locked(session, intent)
    other = replace(intent, upgrade_id=str(uuid4()))
    assert engine.recover_locked(session, other).status == 'UNKNOWN'
    with pytest.raises(SchemaMismatch):
        engine.rebuild_locked(session, other)


def test_later_real_document_writes_do_not_erase_the_historical_upgrade_fact(offline):
    session, intent, source, original = offline
    first = engine.rebuild_locked(session, intent)
    current = Database(session.database.path, schema_release=session.release)
    assert (
        create(Idempotency(current, session.process_lock), title='升级后的正常写入')['code']
        == 'CREATED'
    )
    recovered = engine.recover_locked(session, intent)
    assert recovered.status == 'ALREADY_COMMITTED'
    assert recovered.committed_at == first.committed_at
    assert recovered.retained_data_matches is False
    assert recovered.reason_code == 'CURRENT_DATA_CHANGED'
    with patch.object(engine, '_commit_once', side_effect=AssertionError('No second DDL')):
        assert engine.rebuild_locked(session, intent).retained_data_matches is False
    with current.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM requirements').fetchone()[0] == 2
    assert inspect_v151_source(source).data == original


def test_unverified_objects_are_unknown_and_never_repaired_or_removed(offline):
    session, intent, source, original = offline
    engine.rebuild_locked(session, intent)
    current = Database(session.database.path, schema_release=session.release)
    with current.transaction(write=True) as connection:
        connection.execute('CREATE TABLE unexpected_retained(value TEXT)')
    observed = engine.recover_locked(session, intent)
    assert observed.status == 'UNKNOWN' and observed.reason_code == 'DATABASE_UNVERIFIED'
    with pytest.raises(SchemaMismatch):
        engine.rebuild_locked(session, intent)
    connection = current._connect()
    try:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_schema WHERE name='unexpected_retained'"
            ).fetchone()
            is not None
        )
    finally:
        connection.close()
    assert inspect_v151_source(source).data == original


def test_second_session_needs_real_process_lock_not_a_file_or_pid(offline):
    session, intent, source, original = offline
    with pytest.raises(ProcessAlreadyRunning):
        with engine.MaintenanceSession(
            session.database.path,
            session.package_path,
            session.release,
            maintenance_window_confirmed=True,
        ):
            pytest.fail('Existing lock file is not ownership')
    session.verify()
    assert engine.recover_locked(session, intent).status == 'NOT_APPLIED'


def test_raw_junction_source_is_rejected_before_resolution_or_locking(offline):
    import base64
    import subprocess
    from backend.app.infrastructure.windows_local_paths import PathBoundaryError

    session, intent, source, original = offline
    alias = session.package_path.parent / 'source-junction'
    quoted = lambda path: "'" + str(path).replace("'", "''") + "'"
    script = (
        'New-Item -ItemType Junction -Path '
        + quoted(alias)
        + ' -Target '
        + quoted(session.package_path)
        + ' -ErrorAction Stop | Out-Null'
    )
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    result = subprocess.run(
        ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
        capture_output=True,
        timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0, result.stderr
    try:
        with pytest.raises(PathBoundaryError, match='REPARSE_POINT_REJECTED'):
            with engine.MaintenanceSession(
                alias / session.database.path.name,
                session.package_path,
                session.release,
                maintenance_window_confirmed=True,
            ):
                pytest.fail('The raw original path must be checked before resolve()')
    finally:
        assert alias.parent == session.package_path.parent
        alias.rmdir()
    session.verify()


def test_missing_maintenance_confirmation_has_no_path_or_lock_side_effect(offline):
    session, intent, source, original = offline
    before = tuple(sorted(path.name for path in session.package_path.iterdir()))
    with patch.object(engine, 'LocalPathGuard', side_effect=AssertionError('No path opening')):
        for value in (False, None, 1, 'true'):
            with pytest.raises(ValueError):
                engine.MaintenanceSession(
                    session.database.path,
                    session.package_path,
                    session.release,
                    maintenance_window_confirmed=value,
                )
    assert tuple(sorted(path.name for path in session.package_path.iterdir())) == before
    session.verify()
