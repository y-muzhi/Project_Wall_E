"""Immutable bounded metadata on an actual private NTFS maintenance package."""

from unittest.mock import patch

import pytest

from backend.app.infrastructure import schema_v20_records as records
from backend.app.infrastructure.schema_v20_assets import MaintenancePreparationError
from backend.tests.infrastructure.test_v20_upgrade_engine import offline, release
from backend.tests.requirements.test_v15_foundation import tmp_path, setup
from backend.tests.documents.test_v15_documents import workspace


def test_metadata_is_not_visible_until_atomic_publication_and_reopens_with_exact_digest(offline):
    session, intent, source, original = offline
    original_publish = records._publish_new
    observed = []

    def publish(temporary, target):
        assert not target.exists()
        assert temporary.read_bytes() == b'{"schema_version":1,"value":"original"}\n'
        observed.append(True)
        original_publish(temporary, target)

    with patch.object(records, '_publish_new', publish):
        sha = records.write_record(
            session, 'plan.v1.json', {'schema_version': 1, 'value': 'original'}
        )
    data, digest = records.read_record(session, 'plan.v1.json', expected_sha256=sha)
    assert (
        data == {'schema_version': 1, 'value': 'original'} and digest == sha and observed == [True]
    )
    assert list(session.package_path.glob('.maintenance-*.tmp')) == []


def test_existing_record_is_not_replaced_and_tampering_cannot_be_read_as_original(offline):
    session, intent, source, original = offline
    sha = records.write_record(session, 'plan.v1.json', {'schema_version': 1})
    with pytest.raises(MaintenancePreparationError, match='NEW_MAINTENANCE_RECORD_REQUIRED'):
        records.write_record(session, 'plan.v1.json', {'schema_version': 999})
    assert records.read_record(session, 'plan.v1.json', expected_sha256=sha)[0] == {
        'schema_version': 1
    }
    with (session.package_path / 'plan.v1.json').open('ab') as stream:
        stream.write(b' ')
    with pytest.raises(MaintenancePreparationError, match='MAINTENANCE_RECORD_DIGEST_DIFFERS'):
        records.read_record(session, 'plan.v1.json', expected_sha256=sha)


def test_failed_publication_cleans_only_its_private_temporary_file(offline):
    session, intent, source, original = offline
    with patch.object(records, '_publish_new', side_effect=OSError('Injected publish failure')):
        with pytest.raises(OSError, match='Injected'):
            records.write_record(session, 'plan.v1.json', {'schema_version': 1})
    assert not (session.package_path / 'plan.v1.json').exists()
    assert list(session.package_path.glob('.maintenance-*.tmp')) == []
    assert session.database.path.is_file()


def test_invalid_record_paths_and_capacity_fail_before_creating_an_output(offline):
    session, intent, source, original = offline
    before = tuple(sorted(path.name for path in session.package_path.iterdir()))
    for name in (
        '../outside.json',
        '/outside.json',
        'C:/outside.json',
        r'folder\file.json',
        'a/b/c.json',
        'a//b.json',
        'CON.json',
        'bad\0.json',
    ):
        with pytest.raises(Exception):
            records.write_record(session, name, {'schema_version': 1})
    with patch.object(records, 'MAX_RECORD_BYTES', 16):
        with pytest.raises(MaintenancePreparationError, match='MAINTENANCE_RECORD_TOO_LARGE'):
            records.write_record(session, 'too-large.json', {'large': 'x' * 64})
    assert tuple(sorted(path.name for path in session.package_path.iterdir())) == before


def test_receipts_are_additional_immutable_private_records(offline):
    session, intent, source, original = offline
    (session.package_path / 'receipts').mkdir()
    sha = records.write_record(
        session, 'receipts/00000001.json', {'schema_version': 1, 'phase': 'PLAN'}
    )
    data, _ = records.read_record(session, 'receipts/00000001.json', expected_sha256=sha)
    assert data['phase'] == 'PLAN'
    with pytest.raises(MaintenancePreparationError):
        records.write_record(session, 'receipts/00000001.json', {'phase': 'changed'})
