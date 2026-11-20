"""Only isolated copies: actual legacy writes, AI audit, recovery and native path guards."""

from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.documents.commands import create_document
from backend.app.infrastructure.database import Database, SchemaMismatch
from backend.app.infrastructure.formation_database import FormationDatabase
from backend.app.infrastructure.formation_schema_release import load_release
from backend.app.infrastructure.formation_upgrade_source import SOURCE_MANIFESTS
from backend.app.infrastructure.idempotency import Idempotency, Scope
from backend.app.infrastructure.process_lock import ProcessLock, ProcessAlreadyRunning
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.infrastructure.schema_v20_release import load_release as load_core
from backend.app.requirements.commands import create_requirement
from backend.tests.formation.test_v21_schema import released
from backend.tests.guide.test_v15_acceptance import accept
from backend.tests.guide.test_v15_counting import offline_gate
from backend.tests.guide.test_v15_execution import execute, Gateway
from backend.app.infrastructure import formation_upgrade as upgrade


@pytest.fixture
def source(tmp_path, monkeypatch, released):
    db = Database(tmp_path / 'source' / 'old.sqlite', schema_release=load_core())
    db.initialize()
    catalog = ResourceCatalog()
    body = {
        'title': '完整保留源',
        'requirement_type': 'NEW',
        'initial_idea': '  原始说明\r\n保留空格与换行。  ',
        'idempotency_key': str(uuid4()),
    }
    with ProcessLock.for_database(db.path) as lock:
        commands = Idempotency(db, lock)
        original = create_requirement(commands, body, catalog=catalog)
        assert original['code'] == 'CREATED', original
        doc = create_document(
            commands,
            {
                'requirement_id': 1,
                'name': '旧文档',
                'document_kind': 'DESIGN',
                'template_ref': None,
                'idempotency_key': str(uuid4()),
            },
            catalog=catalog,
        )
        assert doc['code'] == 'CREATED', doc
        offline_gate(monkeypatch)
        workspace = db, commands, catalog
        assert accept(workspace)['code'] == 'GUIDE_ACCEPTED'
        finished = execute(workspace, Gateway())
        assert finished['code'] == 'AI_FINISHED', finished
        with db.transaction(write=True) as connection:
            connection.execute(
                'INSERT INTO code_repositories VALUES(1,?,?,?,?,?)',
                (
                    '旧代码库',
                    r'C:\retained-repo',
                    r'C:\retained-repo\.git',
                    'sha1',
                    '2026-11-16T00:00:00.000Z',
                ),
            )
    monkeypatch.setattr(upgrade, 'load_release', lambda: released[0])
    return db, body, original, released[0]


def arguments(source, **changes):
    return {
        'source_manifest': next(iter(SOURCE_MANIFESTS)),
        'target_manifest': source[3].manifest_sha256,
        'maintenance_window_confirmed': True,
        **changes,
    }


@pytest.mark.parametrize('manifest', tuple(SOURCE_MANIFESTS))
def test_actual_legacy_rows_audits_full_ddl_and_old_receipt_replay_survive_copy(
    source, tmp_path, manifest
):
    db, body, original, release = source
    target = tmp_path / 'target-package' / 'new.sqlite'
    before = db.path.read_bytes()
    old_audit = db.path.with_name(db.path.name + '.count-audit')
    audit_bytes = {p.name: p.read_bytes() for p in old_audit.iterdir()}
    assert audit_bytes
    result = upgrade.copy_upgrade(db.path, target, **arguments(source, source_manifest=manifest))
    assert result.status == 'VERIFIED_TARGET'
    assert db.path.read_bytes() == before
    new_audit = target.with_name(target.name + '.count-audit')
    assert {p.name: p.read_bytes() for p in new_audit.iterdir()} == audit_bytes
    report = Path(result.report_path).read_text(encoding='utf-8')
    assert '\n' in report and 'VERIFIED_TARGET' in report
    assert body['initial_idea'] not in report
    actual = FormationDatabase(target, formation_release=release)
    with actual.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM formation_heads').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 1
        assert connection.execute('SELECT name FROM code_repositories').fetchone()[0] == '旧代码库'
    with ProcessLock.for_database(target) as lock:
        replay = create_requirement(Idempotency(actual, lock), body, catalog=ResourceCatalog())
        assert replay == original
    inspected = upgrade.inspect_target(
        db.path, target, upgrade_id=result.upgrade_id, **arguments(source, source_manifest=manifest)
    )
    assert inspected.status == 'VERIFIED_TARGET'
    assert inspected.source_data_sha256 == result.source_data_sha256
    assert db.path.read_bytes() == before


@pytest.mark.parametrize(
    'change',
    [
        {'source_manifest': '0' * 64},
        {'target_manifest': '0' * 64},
        {'maintenance_window_confirmed': False},
    ],
)
def test_unknown_manifest_or_missing_window_refuses_before_target_preparation(
    source, tmp_path, change
):
    target = tmp_path / 'unprepared' / 'target.sqlite'
    with pytest.raises((SchemaMismatch, ValueError)):
        upgrade.copy_upgrade(source[0].path, target, **arguments(source, **change))
    assert not target.parent.exists()


def test_existing_target_and_same_source_are_never_overwritten(source, tmp_path):
    db = source[0]
    target = tmp_path / 'already' / 'new.sqlite'
    target.parent.mkdir()
    with target.open('xb') as stream:
        stream.write(b'keep original target')
    with pytest.raises(SchemaMismatch):
        upgrade.copy_upgrade(db.path, target, **arguments(source))
    assert target.read_bytes() == b'keep original target'
    with pytest.raises(ValueError):
        upgrade.copy_upgrade(db.path, db.path, **arguments(source))


def test_current_os_lock_and_unreconciled_processing_refuse_without_cancelling(source, tmp_path):
    db = source[0]
    with ProcessLock.for_database(db.path) as lock:
        with pytest.raises(ProcessAlreadyRunning):
            upgrade.copy_upgrade(db.path, tmp_path / 'locked' / 'new.sqlite', **arguments(source))
        Idempotency(db, lock).claim(
            Scope('APP-REQ-CMD-C01', 'new-requirement', str(uuid4())), {'title': '待核实请求'}
        )
    before = db.path.read_bytes()
    target = tmp_path / 'processing' / 'new.sqlite'
    with pytest.raises(SchemaMismatch, match='idempotency_records'):
        upgrade.copy_upgrade(db.path, target, **arguments(source))
    assert not target.exists()
    assert db.path.read_bytes() == before
    with db.transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM idempotency_records WHERE status='PROCESSING'"
            ).fetchone()[0]
            == 1
        )


def test_failure_before_ddl_preserves_a_source_copy_and_inspection_never_applies_it(
    source, tmp_path, monkeypatch
):
    db, _, _, release = source
    target = tmp_path / 'interrupted' / 'new.sqlite'
    identity = str(uuid4())
    before = db.path.read_bytes()

    def fail(*args):
        raise OSError('injected before target DDL')

    monkeypatch.setattr(upgrade, '_apply_extension', fail)
    with pytest.raises(OSError):
        upgrade.copy_upgrade(db.path, target, upgrade_id=identity, **arguments(source))
    assert target.is_file()
    assert db.path.read_bytes() == before
    copied = Database(target, schema_release=release.core)
    with copied.transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM sqlite_schema WHERE name='formation_schema_state'"
            ).fetchone()[0]
            == 0
        )
    result = upgrade.inspect_target(db.path, target, upgrade_id=identity, **arguments(source))
    assert result.status == 'COPIED_SOURCE_NOT_UPGRADED'
    with copied.transaction() as connection:
        assert (
            connection.execute(
                'SELECT count(*) FROM schema_migrations WHERE version=210'
            ).fetchone()[0]
            == 0
        )


def test_lost_final_receipt_recovers_only_the_committed_target_and_wrong_intent_is_refused(
    source, tmp_path, monkeypatch
):
    db = source[0]
    target = tmp_path / 'lost-result' / 'new.sqlite'
    identity = str(uuid4())
    write = upgrade._write_report

    def lose_result(session, name, lines):
        if name == 'upgrade-result.md':
            raise OSError('injected result publication loss')
        return write(session, name, lines)

    monkeypatch.setattr(upgrade, '_write_report', lose_result)
    before = db.path.read_bytes()
    with pytest.raises(OSError):
        upgrade.copy_upgrade(db.path, target, upgrade_id=identity, **arguments(source))
    result = upgrade.inspect_target(db.path, target, upgrade_id=identity, **arguments(source))
    assert result.status == 'VERIFIED_TARGET'
    with pytest.raises(SchemaMismatch, match='original source and upgrade intent'):
        upgrade.inspect_target(db.path, target, upgrade_id=str(uuid4()), **arguments(source))
    assert db.path.read_bytes() == before


def test_bad_actual_source_schema_is_not_accepted_from_its_version_integer(source, tmp_path):
    db = source[0]
    raw = db._connect()
    try:
        raw.execute('CREATE TABLE unexpected_source(data TEXT)')
    finally:
        raw.close()
    before = db.path.read_bytes()
    target = tmp_path / 'bad-source' / 'new.sqlite'
    with pytest.raises(SchemaMismatch):
        upgrade.copy_upgrade(db.path, target, **arguments(source))
    assert not target.exists()
    assert db.path.read_bytes() == before


def test_actual_extension_failure_rolls_back_all_new_ddl_and_marker(source, tmp_path, monkeypatch):
    db = source[0]
    target = tmp_path / 'transaction-failed' / 'new.sqlite'
    identity = str(uuid4())
    before = db.path.read_bytes()

    def fail_final_check(connection, release):
        assert connection.execute('SELECT count(*) FROM formation_schema_state').fetchone()[0] == 1
        raise SchemaMismatch('injected after complete DDL and marker, before commit')

    monkeypatch.setattr(upgrade, 'check_v21', fail_final_check)
    with pytest.raises(SchemaMismatch, match='injected after complete DDL'):
        upgrade.copy_upgrade(db.path, target, upgrade_id=identity, **arguments(source))
    copied = Database(target, schema_release=source[3].core)
    with copied.transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM sqlite_schema WHERE name LIKE 'formation_%'"
            ).fetchone()[0]
            == 0
        )
    assert db.path.read_bytes() == before
    assert (
        upgrade.inspect_target(db.path, target, upgrade_id=identity, **arguments(source)).status
        == 'COPIED_SOURCE_NOT_UPGRADED'
    )


def test_real_inflight_ai_is_preserved_and_not_cancelled_by_copy(source, tmp_path):
    db = source[0]
    with ProcessLock.for_database(db.path) as lock:
        with db.transaction() as connection:
            d = connection.execute(
                'SELECT discussion_version FROM requirement_documents WHERE id=1'
            ).fetchone()[0]
        accepted = accept(
            (db, Idempotency(db, lock), ResourceCatalog()), expected_discussion_version=d
        )
        assert accepted['code'] == 'GUIDE_ACCEPTED', accepted
    target = tmp_path / 'active-ai' / 'new.sqlite'
    before = db.path.read_bytes()
    with pytest.raises(SchemaMismatch, match='guide_runs'):
        upgrade.copy_upgrade(db.path, target, **arguments(source))
    assert not target.exists()
    assert db.path.read_bytes() == before
    with db.transaction() as connection:
        assert (
            connection.execute("SELECT count(*) FROM guide_runs WHERE status='RUNNING'").fetchone()[
                0
            ]
            == 1
        )


def test_existing_target_parent_is_not_repaired_or_reused(source, tmp_path):
    db = source[0]
    target = tmp_path / 'existing-public-directory' / 'new.sqlite'
    target.parent.mkdir()
    with pytest.raises(SchemaMismatch, match='brand-new'):
        upgrade.copy_upgrade(db.path, target, **arguments(source))
    assert not target.exists()


def test_real_cli_uses_compiled_manifest_and_inspects_without_replaying_ddl(source, tmp_path):
    import subprocess
    import sys

    target = tmp_path / 'cli-package' / 'new.sqlite'
    identity = str(uuid4())
    root = Path(__file__).resolve().parents[3]
    manifest = load_release().manifest_sha256
    args = [
        str(root / '.venv/Scripts/python.exe'),
        '-B',
        str(root / 'tools/db-v21.py'),
        'copy',
        '--source',
        str(source[0].path),
        '--target',
        str(target),
        '--source-manifest',
        next(iter(SOURCE_MANIFESTS)),
        '--target-manifest',
        manifest,
        '--upgrade-id',
        identity,
        '--maintenance-window-confirmed',
    ]
    result = subprocess.run(
        args, cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=60
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stdout.splitlines()[0] == 'VERIFIED_TARGET'
    before = target.read_bytes()
    args[3] = 'inspect'
    result = subprocess.run(
        args, cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=60
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stdout.splitlines()[0] == 'VERIFIED_TARGET'
    assert target.read_bytes() == before
