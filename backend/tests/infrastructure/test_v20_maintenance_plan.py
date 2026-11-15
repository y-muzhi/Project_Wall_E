"""Original-source maintenance plan using real native identities and SQLite backup."""

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
from unittest.mock import patch

import pytest

from backend.app.infrastructure import schema_v20_plan as plans
from backend.app.infrastructure.schema_v20_plan_codec import decode_plan
from backend.app.infrastructure.schema_v20_assets import capture_audit, MaintenancePreparationError
from backend.app.infrastructure.schema_v20_release import canonical_bytes
from backend.app.infrastructure.schema_v20_records import read_record
from backend.app.infrastructure.data_retention import inspect_v151_source
from backend.app.infrastructure.database import SchemaMismatch
from backend.tests.infrastructure.test_v20_upgrade_engine import offline, release
from backend.tests.requirements.test_v15_foundation import tmp_path, setup
from backend.tests.documents.test_v15_documents import workspace


def seal(session):
    return plans.prepare_plan(session, configuration_paths=())


def test_sealed_original_plan_binds_real_backup_and_roundtrips_only_with_original_ids(offline):
    session, intent, source, original = offline
    before = inspect_v151_source(session.database).data
    plan, sha = seal(session)
    assert plan.retained == before == intent.retained
    assert plan.backup.identity.file_id != plan.source_identity.file_id
    assert (
        plan.backup.sha256
        == hashlib.sha256((session.package_path / plans.BACKUP_NAME).read_bytes()).hexdigest()
    )
    assert plan.audit.state == 'ABSENT'
    assert not (session.package_path / 'count-audit-copy').exists()
    assert plans.load_plan(session, upgrade_id=plan.upgrade_id, plan_sha256=sha) == (plan, sha)
    plans.verify_preapply(session, plan)
    assert inspect_v151_source(source).data == original
    assert inspect_v151_source(session.database).data == before
    with pytest.raises(MaintenancePreparationError, match='NEW_MAINTENANCE_PACKAGE_REQUIRED'):
        seal(session)
    with pytest.raises(MaintenancePreparationError, match='MAINTENANCE_UPGRADE_ID_DIFFERS'):
        plans.load_plan(session, upgrade_id=intent.upgrade_id, plan_sha256=sha)
    with pytest.raises(MaintenancePreparationError, match='MAINTENANCE_RECORD_DIGEST_DIFFERS'):
        plans.load_plan(session, upgrade_id=plan.upgrade_id, plan_sha256='0' * 64)
    with pytest.raises(MaintenancePreparationError, match='MAINTENANCE_PLAN_BINDING_DIFFERS'):
        plans._bound(session, replace(plan, program_sha256='0' * 64))


def test_sqlite_backup_runs_on_an_independent_reader_while_original_writer_is_excluded(offline):
    session, intent, source, original = offline
    real = plans.copy_database_new
    checked = []

    def copy(owned, database, name, retained):
        connection = owned.database._connect()
        try:
            connection.execute('PRAGMA busy_timeout=0')
            with pytest.raises(__import__('sqlite3').OperationalError, match='locked'):
                connection.execute('BEGIN IMMEDIATE')
            checked.append(True)
        finally:
            connection.close()
        return real(owned, database, name, retained)

    with patch.object(plans, 'copy_database_new', copy):
        plan, sha = seal(session)
    assert checked == [True]
    plans.verify_backup(session, plan)


def test_audit_bytes_and_declared_configuration_are_sealed_without_file_bodies_in_plan(offline):
    session, intent, source, original = offline
    root = session.database.path.with_name(session.database.path.name + '.count-audit')
    root.mkdir()
    body = b'original raw evidence\r\n\x00including non-json bytes'
    with (root / 'actual-evidence.journal').open('xb') as stream:
        stream.write(body)
    config = session.package_path.parent / 'settings.ref'
    with config.open('xb') as stream:
        stream.write(b'private-config-fixture')
    plan, sha = plans.prepare_plan(session, configuration_paths=(config,))
    assert plan.audit.state == 'FILES'
    assert (
        session.package_path / 'count-audit-copy' / 'actual-evidence.journal'
    ).read_bytes() == body
    assert len(plan.references) == 1
    raw = canonical_bytes(asdict(plan))
    assert body not in raw and b'private-config-fixture' not in raw
    plans.verify_preapply(session, plan)
    with config.open('ab') as stream:
        stream.write(b'changed')
    with pytest.raises(MaintenancePreparationError, match='REGISTERED_REFERENCE_CHANGED'):
        plans.verify_preapply(session, plan)
    assert read_record(session, plans.PLAN_NAME, expected_sha256=sha)[1] == sha


def test_backup_or_audit_tamper_is_rejected_without_repairing_or_overwriting_assets(offline):
    session, intent, source, original = offline
    root = session.database.path.with_name(session.database.path.name + '.count-audit')
    root.mkdir()
    with (root / 'a.journal').open('xb') as stream:
        stream.write(b'a')
    plan, sha = seal(session)
    with (session.package_path / 'count-audit-copy' / 'a.journal').open('ab') as stream:
        stream.write(b'-tampered')
    with pytest.raises(MaintenancePreparationError, match='AUDIT_BACKUP_BYTES_DIFFER'):
        plans.verify_backup(session, plan)
    with (session.package_path / plans.BACKUP_NAME).open('ab') as stream:
        stream.write(b'-tampered')
    with pytest.raises(MaintenancePreparationError, match='SOURCE_BACKUP_CHANGED'):
        plans.verify_backup(session, plan)
    assert read_record(session, plans.PLAN_NAME, expected_sha256=sha)[1] == sha
    assert inspect_v151_source(source).data == original


def test_source_or_audit_changes_do_not_refresh_an_existing_plan(offline):
    session, intent, source, original = offline
    plan, sha = seal(session)
    with session.database.transaction(write=True) as connection:
        connection.execute("UPDATE requirements SET title='after-plan' WHERE id=1")
    with pytest.raises(SchemaMismatch, match='SOURCE_CHANGED'):
        plans.verify_preapply(session, plan)
    assert read_record(session, plans.PLAN_NAME, expected_sha256=sha)[1] == sha
    root = session.database.path.with_name(session.database.path.name + '.count-audit')
    root.mkdir()
    with pytest.raises(MaintenancePreparationError, match='AUDIT_SOURCE_CHANGED'):
        plans.verify_preapply(session, plan)


def test_failed_last_publication_retains_backups_but_never_exposes_a_usable_plan(offline):
    session, intent, source, original = offline
    with patch.object(plans, 'write_record', side_effect=OSError('Injected last publication')):
        with pytest.raises(OSError, match='Injected'):
            seal(session)
    assert (session.package_path / plans.BACKUP_NAME).is_file()
    assert not (session.package_path / plans.PLAN_NAME).exists()
    assert inspect_v151_source(session.database).data == intent.retained
    with pytest.raises(MaintenancePreparationError, match='NEW_MAINTENANCE_PACKAGE_REQUIRED'):
        seal(session)


def test_strict_plan_decoder_rejects_omitted_tables_wrong_types_duplicates_and_forged_aggregate(
    offline, subtests
):
    session, intent, source, original = offline
    plan, sha = seal(session)
    original_row = __import__('json').loads(canonical_bytes(asdict(plan)))
    mutations = (
        lambda row: row.update(schema_version=True),
        lambda row: row.update(unknown='not allowed'),
        lambda row: row['retained']['tables'].pop(),
        lambda row: row['retained']['tables'].append(row['retained']['tables'][0]),
        lambda row: row['retained']['tables'][0].update(row_count=True),
        lambda row: row['retained']['tables'][0]['projection']['columns'].pop(),
        lambda row: row['retained'].update(sha256='0' * 64),
        lambda row: row['backup'].update(byte_count=True),
        lambda row: row['space'].update(shared_volume=1),
        lambda row: row['source_identity'].update(is_directory=0),
        lambda row: row['source_identity'].update(canonical_path=r'\\server\data.sqlite'),
        lambda row: row['audit'].update(state='FILES'),
        lambda row: row['audit'].update(root_path=row['source_identity']['canonical_path']),
        lambda row: row.update(created_at='2026-02-31T00:00:00.000Z'),
    )
    for number, mutate in enumerate(mutations):
        with subtests.test(case=number):
            invalid = deepcopy(original_row)
            mutate(invalid)
            with pytest.raises(Exception):
                decode_plan(invalid)


def test_duplicate_config_declarations_and_unregistered_backup_paths_fail_before_writing(offline):
    session, intent, source, original = offline
    config = session.package_path.parent / 'settings.ref'
    with config.open('xb') as stream:
        stream.write(b'fixture')
    with pytest.raises(MaintenancePreparationError, match='DUPLICATE_CONFIGURATION_REFERENCE'):
        plans.prepare_plan(session, configuration_paths=(config, config))
    assert not (session.package_path / plans.BACKUP_NAME).exists()
    with pytest.raises(
        MaintenancePreparationError, match='REGISTERED_BACKUP_SOURCE_AND_NAME_REQUIRED'
    ):
        plans.copy_database_new(session, source, '../outside.sqlite', intent.retained)
    assert not (session.package_path.parent / 'outside.sqlite').exists()
