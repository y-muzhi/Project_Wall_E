"""Opaque config/call reference digests; no secrets or provider IO."""

from dataclasses import asdict
import json

import pytest

from backend.app.infrastructure import schema_v20_references as references
from backend.app.infrastructure.schema_v20_assets import capture_audit, MaintenancePreparationError
from backend.app.infrastructure import schema_v20_upgrade as engine
from backend.tests.infrastructure.test_v20_upgrade_engine import offline, release
from backend.tests.requirements.test_v15_foundation import tmp_path, setup
from backend.tests.documents.test_v15_documents import workspace


def admission(session, database):
    root = session.database.path.with_name(session.database.path.name + '.count-audit')
    root.mkdir()
    record = {
        'schema_version': 1,
        'source_database': str(database),
        'llm_use_id': 1,
        'approved_at': '2026-11-04T01:00:00.000Z',
        'admission': {},
    }
    # Only reference integrity/readability is under test; not a valid LIVE admission.
    with (root / ('collaboration-' + 'a' * 64 + '.admission.json')).open('xb') as stream:
        stream.write(json.dumps(record, ensure_ascii=False).encode())
    return capture_audit(session)


def test_explicit_config_is_only_hashed_and_changed_bytes_are_rejected(offline):
    session, intent, source, original = offline
    config = session.package_path.parent / 'configuration.ref'
    secret_like = b'private fixture value that must not appear in metadata'
    with config.open('xb') as stream:
        stream.write(secret_like)
    audit = capture_audit(session)
    result = references.capture_registered_references(session, audit, configuration_paths=(config,))
    assert len(result) == 1 and result[0].kind == 'CONFIG_FILE'
    assert secret_like.decode() not in json.dumps(asdict(result[0]))
    references.verify_registered_references(session, result)
    with config.open('ab') as stream:
        stream.write(b'-changed')
    with pytest.raises(MaintenancePreparationError, match='REGISTERED_REFERENCE_CHANGED'):
        references.verify_registered_references(session, result)


def test_internal_document_call_reference_survives_151_to_200_with_same_original_fields(offline):
    session, intent, source, original = offline
    audit = admission(session, session.database.path)
    result = references.capture_registered_references(session, audit, configuration_paths=())
    assert len(result) == 1 and result[0].kind == 'INTERNAL_CALL'
    engine.rebuild_locked(session, intent)
    references.verify_registered_references(session, result)
    assert result[0].llm_use_id == 1


def test_external_original_call_is_read_only_and_not_a_recursive_directory_copy(offline):
    session, intent, source, original = offline
    audit = admission(session, source.path)
    result = references.capture_registered_references(session, audit, configuration_paths=())
    assert len(result) == 1 and result[0].kind == 'DOCUMENT_CALL'
    assert result[0].path == str(source.path)
    references.verify_registered_references(session, result)
    with source.transaction(write=True) as connection:
        connection.execute("UPDATE requirements SET title='无关文档属性变化' WHERE id=1")
    references.verify_registered_references(session, result)
    with source.transaction(write=True) as connection:
        connection.execute("UPDATE llm_uses SET input_summary='实际被引用行变化' WHERE id=1")
    with pytest.raises(MaintenancePreparationError, match='REGISTERED_REFERENCE_CHANGED'):
        references.verify_registered_references(session, result)
    assert not (session.package_path / 'count-audit-copy').exists()


def test_main_database_cannot_be_mislabeled_as_an_opaque_configuration_file(offline):
    session, intent, source, original = offline
    audit = capture_audit(session)
    with pytest.raises(MaintenancePreparationError, match='CONFIG_REFERENCE_MUST_NOT_BE_DATABASE'):
        references.capture_registered_references(
            session, audit, configuration_paths=(session.database.path,)
        )
