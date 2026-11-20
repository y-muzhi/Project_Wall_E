"""Fixed SQLite Schema210 construction, transaction and immutable-boundary evidence."""

from pathlib import Path
import json
import sqlite3
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest

from backend.app.infrastructure.database import Database, SchemaMismatch, CommitOutcomeUnknown
from backend.app.infrastructure.formation_database import FormationDatabase
from backend.app.infrastructure.formation_schema_release import build_candidate, load_verified
from backend.app.infrastructure.idempotency import Idempotency
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.infrastructure.schema_v20_release import digest, load_release as load_core
from backend.app.requirements.commands import create_requirement
from backend.app.documents.commands import create_document


@pytest.fixture(scope='module')
def released():
    files = build_candidate('db21-test')
    with TemporaryDirectory(prefix='w21-release-') as directory:
        root = Path(directory)
        for name, content in files.items():
            with (root / name).open('xb') as stream:
                stream.write(content)
        yield load_verified(root, digest(files['manifest.json'])), files, root


@pytest.fixture
def database(released):
    with TemporaryDirectory(prefix='w21-database-') as directory:
        db = FormationDatabase(Path(directory) / 'v21.sqlite', formation_release=released[0])
        assert db.initialize()['schema_version'] == 210
        yield db


@pytest.fixture
def workspace(database):
    with ProcessLock.for_database(database.path) as lock:
        commands = Idempotency(database, lock)
        catalog = ResourceCatalog()
        result = create_requirement(
            commands,
            {
                'title': '形成设计',
                'requirement_type': 'NEW',
                'initial_idea': '整理本版本设计',
                'idempotency_key': str(uuid4()),
            },
            catalog=catalog,
        )
        assert result['code'] == 'CREATED', result
        for name in ('需求', '设计'):
            result = create_document(
                commands,
                {
                    'requirement_id': 1,
                    'name': name,
                    'document_kind': 'DESIGN',
                    'template_ref': None,
                    'idempotency_key': str(uuid4()),
                },
                catalog=catalog,
            )
            assert result['code'] == 'CREATED', result
        yield database, commands, catalog


def head(connection, document_id=1):
    connection.execute(
        'INSERT INTO formation_heads(document_id,version,goal_version,goal_text,goal_sources_json,'
        'current_step_ref,active_branch_ref,next_step_no,next_branch_no,next_issue_no,next_artifact_no) '
        "VALUES(?,1,1,'形成设计','[]',NULL,NULL,2,1,1,1)",
        (document_id,),
    )
    connection.execute(
        'INSERT INTO formation_steps(document_id,step_ref,definition_version,next_result_no,position,'
        "title,status,closure_event_id) VALUES(?,'s1',1,2,1,'讨论方案','PLANNED',NULL)",
        (document_id,),
    )
    connection.execute(
        'INSERT INTO formation_results(document_id,step_ref,result_ref,description,kind) '
        "VALUES(?,'s1','s1.o1','方案说明','CONTENT')",
        (document_id,),
    )


def test_candidate_keeps_core_and_adds_21_business_tables_and_release_marker(released):
    release, files, _ = released
    core = load_core()
    assert release.fresh.startswith(core.fresh)
    core_tables = {table.name for table in core.expected_schema.tables}
    all_tables = {table.name for table in release.expected_schema.tables}
    assert core_tables < all_tables
    assert len(all_tables - core_tables) == 22
    assert len(all_tables) == 94
    from backend.app.infrastructure.formation_schema_release import SOURCE_NAMES

    assert set(json.loads(files['manifest.json'])['sources']) == set(SOURCE_NAMES)


def test_fresh_reopens_and_existing_schema200_is_never_implicitly_upgraded(database, released):
    assert database.initialize()['initialized'] is False
    with database.transaction() as connection:
        assert [
            row[0]
            for row in connection.execute('SELECT version FROM schema_migrations ORDER BY version')
        ] == [200, 210]
        assert (
            connection.execute('SELECT origin FROM formation_schema_state').fetchone()[0]
            == 'FRESH_V21'
        )
    with TemporaryDirectory(prefix='w21-source-') as directory:
        path = Path(directory) / 'source.sqlite'
        original = Database(path, schema_release=load_core())
        original.initialize()
        before = path.read_bytes()
        target = FormationDatabase(path, formation_release=released[0])
        with pytest.raises(SchemaMismatch):
            target.initialize()
        assert path.read_bytes() == before
        with original.transaction() as connection:
            assert (
                connection.execute(
                    'SELECT count(*) FROM sqlite_schema WHERE name LIKE ?', ('formation_%',)
                ).fetchone()[0]
                == 0
            )


def test_modified_package_rejected_before_opening_any_database(released):
    release, files, _ = released
    with TemporaryDirectory(prefix='w21-tamper-') as directory:
        root = Path(directory)
        for name, content in files.items():
            with (root / name).open('xb') as stream:
                stream.write(content + (b'\n-- changed' if name == 'upgrade-200.v1.sql' else b''))
        with pytest.raises(SchemaMismatch):
            load_verified(root, release.manifest_sha256)


def test_unknown_schema_objects_and_changed_history_are_rejected(database):
    raw = database._connect()
    try:
        raw.execute('CREATE TABLE unexpected(value TEXT)')
    finally:
        raw.close()
    with pytest.raises(SchemaMismatch):
        with database.transaction():
            pass


def test_same_connection_rollback_restores_local_ids_and_original_document(workspace):
    db, _, _ = workspace
    with pytest.raises(RuntimeError, match='injected failure'):
        with db.transaction(write=True) as connection:
            head(connection)
            connection.execute('UPDATE formation_heads SET next_step_no=3 WHERE document_id=1')
            raise RuntimeError('injected failure')
    with db.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM formation_heads').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM formation_steps').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM requirement_documents').fetchone()[0] == 2


def test_foreign_keys_reject_cross_document_result_and_invalid_refs(workspace):
    db, _, _ = workspace
    with db.transaction(write=True) as connection:
        head(connection, 1)
        head(connection, 2)
    with pytest.raises(CommitOutcomeUnknown):
        with db.transaction(write=True) as connection:
            connection.execute(
                "INSERT INTO formation_results VALUES(2,'s2','s2.o1','不属于此文档','CONTENT')"
            )
    for bad in ('s0', 's01', 's9007199254740992', 'new_step_1'):
        with pytest.raises(sqlite3.IntegrityError):
            with db.transaction(write=True) as connection:
                connection.execute(
                    'INSERT INTO formation_steps VALUES(?,?,1,1,2,?,?,NULL)',
                    (1, bad, '非法持久身份', 'PLANNED'),
                )


def test_current_step_fk_is_deferred_but_missing_focus_cannot_commit(workspace):
    db, _, _ = workspace
    with db.transaction(write=True) as connection:
        head(connection)
        connection.execute("UPDATE formation_heads SET current_step_ref='s2' WHERE document_id=1")
        connection.execute(
            "INSERT INTO formation_steps VALUES(1,'s2',1,1,2,'下一步','PLANNED',NULL)"
        )
    # Database wraps a COMMIT error as unknown; raw transaction proves FK semantics precisely.
    raw = db._connect()
    try:
        raw.execute('BEGIN IMMEDIATE')
        raw.execute("UPDATE formation_heads SET current_step_ref='s3' WHERE document_id=1")
        with pytest.raises(sqlite3.IntegrityError):
            raw.commit()
        raw.rollback()
    finally:
        raw.close()


def test_immutable_origin_marker_cannot_be_rewritten_or_removed(database):
    for sql in (
        "UPDATE formation_schema_state SET origin='UPGRADED_V200',upgrade_id='fake',source_data_sha256='fake'",
        'DELETE FROM formation_schema_state',
    ):
        with pytest.raises(sqlite3.IntegrityError):
            with database.transaction(write=True) as connection:
                connection.execute(sql)


def test_mutable_artifact_status_requires_reason_and_original_origin_is_frozen(workspace):
    db, _, _ = workspace
    with db.transaction(write=True) as connection:
        head(connection)
        revision = connection.execute(
            'SELECT id FROM revisions WHERE document_id=1 ORDER BY id DESC'
        ).fetchone()[0]
        # An actual native audit identity is supplied by a real user action fact.
        connection.execute(
            'INSERT INTO document_change_audits(id,requirement_id,document_id,source_type,source_id,'
            'reason_code,before_content_version,after_content_version,created_at,event_type,revision_id,guide_run_id,payload_json) '
            "VALUES(100,1,1,'USER_ACTION',1,'DISCUSSION_UPDATED',NULL,NULL,'2026-11-15T00:00:00.000Z','DISCUSSION_UPDATED',NULL,NULL,'{}')"
        )
        connection.execute(
            'INSERT INTO formation_artifacts VALUES(?,?,?,?,?,?,?,?,?,?)',
            (1, 'a1', 's1', 100, revision, '0' * 64, '方案依据', revision, 'CURRENT', None),
        )
    for sql in (
        "UPDATE formation_artifacts SET freshness='NEEDS_REVIEW' WHERE document_id=1",
        "UPDATE formation_artifacts SET origin_digest='" + '1' * 64 + "' WHERE document_id=1",
        "UPDATE formation_artifacts SET freshness='CURRENT',review_reason='CHANGED' WHERE document_id=1",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            with db.transaction(write=True) as connection:
                connection.execute(sql)
