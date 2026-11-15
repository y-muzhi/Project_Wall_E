"""Sealed rehearsal and original-path commit/recovery, only owned 151 copies."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from backend.app.infrastructure import schema_v20_maintenance as maintenance
from backend.app.infrastructure import schema_v20_plan as plans
from backend.app.infrastructure import schema_v20_upgrade as engine
from backend.app.infrastructure.data_retention import inspect_v151_source
from backend.app.infrastructure.database import CommitOutcomeUnknown, Database
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.schema_v20_assets import MaintenancePreparationError
from backend.tests.documents.test_v15_documents import workspace
from backend.tests.infrastructure.test_v20_upgrade_engine import offline, release
from backend.tests.requirements.test_v15_foundation import setup, tmp_path


def prepared(session):
    plan, sha = plans.prepare_plan(session, configuration_paths=())
    keys = {'upgrade_id': plan.upgrade_id, 'plan_sha256': sha}
    return plan, keys


def test_real_rehearsal_does_not_touch_original_then_same_original_apply_and_recovery(offline):
    session, intent, source, original = offline
    plan, keys = prepared(session)
    seal, seal_sha = maintenance.rehearse_plan(session, **keys)
    assert seal['status'] == 'PASSED'
    assert seal['document_call_count'] == 1
    assert seal['owner_constraint_probe_count'] == 2
    assert seal['rehearsal']['identity']['file_id'] != plan.source_identity.file_id
    assert inspect_v151_source(session.database).data == plan.retained
    with patch.object(
        maintenance, 'rebuild_locked', side_effect=AssertionError('No duplicate rehearsal')
    ):
        assert maintenance.rehearse_plan(session, **keys) == (seal, seal_sha)
    assert maintenance.recover_plan(session, **keys).status == 'NOT_APPLIED'
    result = maintenance.apply_plan(session, **keys)
    assert result.status == 'UPGRADED'
    with patch.object(
        maintenance, 'rebuild_locked', side_effect=AssertionError('No duplicate migration')
    ):
        repeat = maintenance.apply_plan(session, **keys)
        assert repeat.status == 'ALREADY_COMMITTED' and repeat.committed_at == result.committed_at
    assert maintenance.recover_plan(session, **keys).status == 'ALREADY_COMMITTED'
    assert inspect_v151_source(source).data == original
    assert len(list((session.package_path / 'receipts').glob('*.json'))) == 5


def test_apply_requires_actual_rehearsal_seal_and_source_changes_do_not_update_old_plan(offline):
    session, intent, source, original = offline
    plan, keys = prepared(session)
    with pytest.raises(Exception):
        maintenance.apply_plan(session, **keys)
    assert inspect_v151_source(session.database).data == plan.retained
    maintenance.rehearse_plan(session, **keys)
    with session.database.transaction(write=True) as connection:
        connection.execute("UPDATE requirements SET title='原计划后变更' WHERE id=1")
    with pytest.raises(MaintenancePreparationError, match='ORIGINAL_DATABASE_UNVERIFIED'):
        maintenance.apply_plan(session, **keys)
    assert maintenance.recover_plan(session, **keys).status == 'UNKNOWN'
    assert plans.load_plan(session, **keys)[0] == plan


def test_lost_external_receipt_after_original_commit_is_recovered_without_ddl(offline):
    session, intent, source, original = offline
    plan, keys = prepared(session)
    maintenance.rehearse_plan(session, **keys)
    with patch.object(
        maintenance, '_append_receipt', side_effect=OSError('Injected receipt failure')
    ):
        with pytest.raises(CommitOutcomeUnknown):
            maintenance.apply_plan(session, **keys)
    with patch.object(
        maintenance, 'rebuild_locked', side_effect=AssertionError('Never replay upgrade')
    ):
        recovered = maintenance.recover_plan(session, **keys)
        assert recovered.status == 'ALREADY_COMMITTED'
        assert recovered.retained_data_matches is True
    assert inspect_v151_source(source).data == original


def test_lost_commit_ack_never_creates_success_receipt_until_explicit_recovery(offline):
    session, intent, source, original = offline
    plan, keys = prepared(session)
    maintenance.rehearse_plan(session, **keys)
    before = tuple((session.package_path / 'receipts').iterdir())

    def lost(connection):
        connection.commit()
        raise CommitOutcomeUnknown('Injected durable commit acknowledgment lost')

    with patch.object(engine, '_commit_once', lost):
        with pytest.raises(CommitOutcomeUnknown):
            maintenance.apply_plan(session, **keys)
    assert tuple((session.package_path / 'receipts').iterdir()) == before
    assert maintenance.recover_plan(session, **keys).status == 'ALREADY_COMMITTED'


def test_later_legitimate_business_writes_and_new_audit_do_not_erase_historical_commit(offline):
    session, intent, source, original = offline
    plan, keys = prepared(session)
    maintenance.rehearse_plan(session, **keys)
    applied = maintenance.apply_plan(session, **keys)
    current = Database(session.database.path, schema_release=session.release)
    with current.transaction(write=True) as connection:
        root = RequirementRepository(connection).get(1)
        later = (
            (
                datetime.fromisoformat(root['updated_at'].replace('Z', '+00:00'))
                + timedelta(seconds=1)
            )
            .isoformat(timespec='milliseconds')
            .replace('+00:00', 'Z')
        )
        root = RequirementRepository(connection).update_attributes(
            root, {'title': '升级后的真实业务变更'}, later
        )
    audit = session.database.path.with_name(session.database.path.name + '.count-audit')
    audit.mkdir()
    with (audit / 'later-business.journal').open('xb') as stream:
        stream.write(b'legitimate later evidence')
    result = maintenance.recover_plan(session, **keys)
    assert result.status == 'ALREADY_COMMITTED' and result.retained_data_matches is False
    assert result.reason_code == 'CURRENT_DATA_CHANGED'
    assert result.committed_at == applied.committed_at
    with current.transaction() as connection:
        assert RequirementRepository(connection).get(1)['title'] == root['title']
    assert inspect_v151_source(source).data == original


def test_failed_rehearsal_preserves_partial_copy_without_passed_seal_and_new_attempt_uses_new_file(
    offline,
):
    session, intent, source, original = offline
    plan, keys = prepared(session)
    with patch.object(
        maintenance, '_document_read_digest', side_effect=RuntimeError('Injected read failure')
    ):
        with pytest.raises(RuntimeError, match='Injected'):
            maintenance.rehearse_plan(session, **keys)
    first = tuple(session.package_path.glob('rehearsal-*.sqlite'))
    assert len(first) == 1
    assert not (session.package_path / maintenance.REHEARSAL_SEAL).exists()
    assert inspect_v151_source(session.database).data == plan.retained
    seal, sha = maintenance.rehearse_plan(session, **keys)
    assert seal['status'] == 'PASSED'
    assert len(tuple(session.package_path.glob('rehearsal-*.sqlite'))) == 2
    assert first[0].is_file()


def test_tampered_rehearsal_blocks_apply_and_recover_without_changing_original(offline):
    session, intent, source, original = offline
    plan, keys = prepared(session)
    seal, sha = maintenance.rehearse_plan(session, **keys)
    from pathlib import Path

    with Path(seal['rehearsal']['identity']['canonical_path']).open('ab') as stream:
        stream.write(b'-tampered')
    for action in (maintenance.apply_plan, maintenance.recover_plan):
        with pytest.raises(MaintenancePreparationError, match='REHEARSAL_DATABASE_CHANGED'):
            action(session, **keys)
    assert inspect_v151_source(session.database).data == plan.retained
