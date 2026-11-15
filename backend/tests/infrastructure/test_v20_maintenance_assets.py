"""Registered count-audit bytes/empty states and real quota checks on private test copies."""

import hashlib
import sqlite3
from contextlib import closing
from unittest.mock import patch

import pytest

from backend.app.infrastructure import schema_v20_assets as assets
from backend.tests.infrastructure.test_v20_upgrade_engine import offline, release
from backend.tests.requirements.test_v15_foundation import tmp_path, setup
from backend.tests.documents.test_v15_documents import workspace
from backend.app.infrastructure.windows_local_paths import PathBoundaryError
from backend.app.infrastructure.data_retention import capture_retained_data


def root_for(session):
    return session.database.path.with_name(session.database.path.name + '.count-audit')


def test_absent_audit_root_is_recorded_without_creating_fake_evidence(offline):
    session, intent, source, original = offline
    snapshot = assets.capture_audit(session)
    assert snapshot.state == 'ABSENT' and snapshot.root_identity is None and snapshot.files == ()
    assets.copy_audit(session, snapshot)
    assets.verify_audit_backup(session, snapshot)
    assert not root_for(session).exists()
    assert not (session.package_path / 'count-audit-copy').exists()


def test_existing_empty_root_is_distinct_and_preserves_an_empty_copy(offline):
    session, intent, source, original = offline
    root = root_for(session)
    root.mkdir()
    snapshot = assets.capture_audit(session)
    assert snapshot.state == 'EMPTY' and snapshot.root_identity is not None and snapshot.files == ()
    assets.copy_audit(session, snapshot)
    assets.verify_audit_backup(session, snapshot)
    assert root.is_dir()
    assert list((session.package_path / 'count-audit-copy').iterdir()) == []


def test_all_original_audit_and_admission_bytes_are_preserved_without_json_normalization(offline):
    session, intent, source, original = offline
    root = root_for(session)
    root.mkdir()
    samples = {
        'a' * 32 + '.prepared.json': b'{ "zero": 0, "null": null }\r\n',
        'a' * 32 + '.finished.json': '{"正文":"原始空白  "}\n'.encode(),
        'collaboration-' + 'b' * 64 + '.admission.json': b'{ "state": "fixture-original" }\n',
        'empty-evidence.dat': b'',
    }
    for name, data in samples.items():
        with (root / name).open('xb') as stream:
            stream.write(data)
    snapshot = assets.capture_audit(session)
    assert snapshot.state == 'FILES'
    assert snapshot.byte_count == sum(len(value) for value in samples.values())
    assets.copy_audit(session, snapshot)
    for file in snapshot.files:
        assert file.sha256 == hashlib.sha256(samples[file.name]).hexdigest()
        assert (root / file.name).read_bytes() == samples[file.name]
        assert (session.package_path / 'count-audit-copy' / file.name).read_bytes() == samples[
            file.name
        ]
    with pytest.raises(FileExistsError):
        assets.copy_audit(session, snapshot)


def test_changed_source_or_nested_tree_never_becomes_a_valid_backup(offline):
    session, intent, source, original = offline
    root = root_for(session)
    root.mkdir()
    file = root / 'source.json'
    with file.open('xb') as stream:
        stream.write(b'original')
    snapshot = assets.capture_audit(session)
    with file.open('ab') as stream:
        stream.write(b'-changed')
    with pytest.raises(assets.MaintenancePreparationError, match='AUDIT_SOURCE_CHANGED'):
        assets.copy_audit(session, snapshot)
    assert not (session.package_path / 'count-audit-copy').exists()
    (root / 'unexpected-tree').mkdir()
    with pytest.raises(PathBoundaryError, match='PATH_TYPE_DIFFERS'):
        assets.capture_audit(session)
    assert file.read_bytes() == b'original-changed'


def test_copy_failure_retains_original_and_partial_recovery_asset_without_false_verification(
    offline,
):
    session, intent, source, original = offline
    root = root_for(session)
    root.mkdir()
    file = root / 'source.json'
    with file.open('xb') as stream:
        stream.write(b'retained source')
    snapshot = assets.capture_audit(session)
    original_hash = assets._hash_file

    def failed(path, guard, output=None):
        if output is not None:
            output.write(b'partial')
            raise OSError('Injected copy write failure')
        return original_hash(path, guard)

    with patch.object(assets, '_hash_file', failed):
        with pytest.raises(OSError, match='Injected'):
            assets.copy_audit(session, snapshot)
    assert file.read_bytes() == b'retained source'
    assert (session.package_path / 'count-audit-copy' / 'source.json').read_bytes() == b'partial'
    with pytest.raises(assets.MaintenancePreparationError, match='AUDIT_BACKUP_BYTES_DIFFER'):
        assets.verify_audit_backup(session, snapshot)


def test_caller_available_disk_space_is_checked_before_any_database_change(offline):
    session, intent, source, original = offline
    snapshot = assets.capture_audit(session)
    with session.database.transaction() as connection:
        before = capture_retained_data(connection)
        observed = assets.require_disk_space(session, connection, snapshot)
        assert observed.database_bytes > 0 and observed.audit_bytes == 0
        assert observed.source_required_bytes > observed.database_bytes
        assert observed.package_required_bytes > observed.database_bytes * 2
        assert observed.shared_volume is True
        with patch.object(assets, '_available_bytes', return_value=1):
            with pytest.raises(assets.MaintenancePreparationError, match='DISK_SPACE_INSUFFICIENT'):
                assets.require_disk_space(session, connection, snapshot)
        assert capture_retained_data(connection) == before
    assert not (session.package_path / 'count-audit-copy').exists()


def test_space_snapshot_cannot_be_borrowed_from_another_connection(offline):
    session, intent, source, original = offline
    snapshot = assets.capture_audit(session)
    with closing(sqlite3.connect(':memory:', isolation_level=None)) as connection:
        connection.execute('BEGIN')
        with pytest.raises(assets.MaintenancePreparationError, match='DATABASE_CONNECTION_DIFFERS'):
            assets.require_disk_space(session, connection, snapshot)
