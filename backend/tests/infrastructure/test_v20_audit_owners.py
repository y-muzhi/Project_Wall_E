"""Real owner FK graphs; no runnable model/profile or provider evidence is claimed."""

from pathlib import Path
from contextlib import closing
from unittest.mock import patch
import sqlite3

import pytest

from backend.app.infrastructure.audit_repository import AuditRepository
from backend.app.infrastructure.collaboration_admission import evidence_database
from backend.app.infrastructure.database import (
    Database,
    Migration,
    SchemaMismatch,
    StorageUnavailable,
)
from backend.app.infrastructure.schema_v20_release import (
    build_candidate,
    _load_verified_release,
    digest,
)
from backend.app.shared.command_execution import Rejected
from backend.tests.infrastructure.test_v20_schema_graph import graph, insert
from backend.tests.requirements.test_v15_foundation import tmp_path, setup
from backend.tests.documents.test_v15_documents import workspace
from backend.tests.infrastructure.test_v20_schema_migration import AT


def calls_for_all_owners(connection):
    connection.row_factory = sqlite3.Row
    connection.execute('BEGIN')
    insert(
        connection,
        'code_workspaces',
        id=1,
        task_id=1,
        base_snapshot_id=1,
        private_location_key='fixture',
        status='PREPARING',
        created_at=AT,
    )
    insert(
        connection,
        'code_instances',
        id=1,
        task_id=1,
        workspace_id=1,
        executor_version='fixture',
        control_generation=1,
        effective_profile_version_id=1,
        status='STARTING',
        created_at=AT,
    )
    insert(
        connection,
        'code_sessions',
        id=1,
        task_id=1,
        instance_id=1,
        role='BACKEND',
        control_generation=1,
        status='PREPARING',
        created_at=AT,
    )
    insert(
        connection,
        'testing_profile_versions',
        id=1,
        name='fixture',
        version=1,
        runner_refs='["fixture"]',
        environment_refs='[]',
        commands='[]',
        model_binding=None,
        limits='{}',
        admission_refs='[]',
        created_at=AT,
    )
    insert(
        connection,
        'testing_authorizations',
        id=1,
        testing_task_id=1,
        profile_version_id=1,
        scope_kind='TASK',
        validation_id=None,
        status='EFFECTIVE',
        budget_limit_cny='1.000000',
        actor_ref='fixture',
        approved_at=AT,
    )
    insert(
        connection,
        'testing_tasks',
        id=1,
        kind='PRODUCT',
        requirement_id=1,
        document_id=1,
        design_revision_id=1,
        target_kind='CANDIDATE',
        candidate_id=1,
        snapshot_id=None,
        purpose='DIAGNOSTIC',
        profile_version_id=1,
        authorization_id=1,
        budget_limit_cny='1.000000',
        status='DRAFT',
        phase='PLAN',
        state_version=1,
        control_generation=1,
        created_at=AT,
    )
    insert(
        connection,
        'code_operations',
        id=20,
        task_id=None,
        testing_task_id=1,
        resource_kind='TESTING_TASK',
        resource_id=1,
        session_id=None,
        operation_type='DRAFT_PLAN',
        idempotency_key='00000000-0000-4000-8000-000000000020',
        expected_state_version=1,
        fixed_input='{}',
        control_generation=1,
        status='PENDING',
        created_at=AT,
    )
    for identity, is_testing in ((2, False), (3, True)):
        insert(
            connection,
            'llm_uses',
            id=identity,
            guide_run_id=None,
            execution_session_id=None if is_testing else 1,
            testing_task_id=1 if is_testing else None,
            operation_id=20 if is_testing else 2,
            call_no=1,
            attempt_no=1,
            gateway_request_id=None if is_testing else 'fixture-gateway',
            protocol_version='TEST20-PLAN-1' if is_testing else 'OC20-MODEL-1',
            call_purpose='TEST_DESIGN' if is_testing else 'CODE',
            transport_status='COMPLETE',
            usage_status='NOT_REPORTED',
            capture_status='FULL',
            source_evidence_ref='fixture-evidence',
            provider='fixture',
            model_name='fixture',
            function_type='TEST_PLAN_DRAFT' if is_testing else 'CODE_EXECUTION',
            prompt_config='fixture',
            request_snapshot_json='{}',
            input_summary='fixture',
            context_manifest_json='{}',
            raw_response_json='{"kept":true}',
            parsed_output_json='{}' if is_testing else None,
            trusted_output_json='{}' if is_testing else None,
            parse_status='SUCCEEDED' if is_testing else 'NOT_APPLICABLE',
            validation_status='SUCCEEDED' if is_testing else 'NOT_APPLICABLE',
            call_status='SUCCEEDED',
            started_at=AT,
            ended_at=AT,
        )
    connection.execute(
        "UPDATE llm_uses SET raw_response_json='{}',parsed_output_json='{}',call_status='SUCCEEDED',ended_at=? WHERE id=1",
        (AT,),
    )
    assert not connection.execute('PRAGMA foreign_key_check').fetchall()
    connection.commit()


def test_document_mutations_cannot_interpret_coding_or_testing_calls(graph):
    calls_for_all_owners(graph)
    graph.execute('BEGIN')
    audits = AuditRepository(graph)
    assert audits.get(1)['guide_run_id'] is not None
    for identity in (2, 3):
        before = dict(graph.execute('SELECT * FROM llm_uses WHERE id=?', (identity,)).fetchone())
        assert audits.get(identity) is None
        for operation in (
            lambda: audits.record_transport(identity, {}, AT, profile=object(), succeeded=True),
            lambda: audits.parse_response(identity, AT),
            lambda: audits.record_validation_failure(identity, AT),
            lambda: audits.record_admission_failure(identity, AT),
        ):
            with pytest.raises(Rejected) as error:
                operation()
            assert error.value.code == 'NOT_FOUND'
        assert (
            dict(graph.execute('SELECT * FROM llm_uses WHERE id=?', (identity,)).fetchone())
            == before
        )
    assert audits.get(2, owner_kind='CODING', owner_id=1)['execution_session_id'] == 1
    assert audits.get(2, owner_kind='CODING', owner_id=2) is None
    assert audits.get(3, owner_kind='TESTING', owner_id=1)['testing_task_id'] == 1
    assert audits.get(2, owner_kind='TESTING', owner_id=1) is None
    assert audits.get(3, owner_kind='CODING', owner_id=1) is None
    with pytest.raises(ValueError):
        audits.get(3, owner_kind='TESTING')
    graph.rollback()


def test_old_raw_retention_only_prunes_document_branch(graph):
    calls_for_all_owners(graph)
    before = [
        tuple(row) for row in graph.execute('SELECT * FROM llm_uses WHERE id IN(2,3) ORDER BY id')
    ]
    graph.execute('BEGIN')
    assert AuditRepository(graph).prune_raw('2027-01-01T00:00:00.000Z') == 1
    graph.commit()
    assert tuple(
        graph.execute(
            'SELECT raw_response_json,parsed_output_json FROM llm_uses WHERE id=1'
        ).fetchone()
    ) == (None, None)
    assert [
        tuple(row) for row in graph.execute('SELECT * FROM llm_uses WHERE id IN(2,3) ORDER BY id')
    ] == before


@pytest.mark.parametrize('version', [150, 151, 200])
def test_exact_frozen_or_released_evidence_is_read_only_and_never_business_storage(
    tmp_path, version
):
    release = None
    if version == 200:
        bundle = tmp_path / 'release'
        bundle.mkdir()
        files = build_candidate('evidence-test')
        for name, content in files.items():
            with (bundle / name).open('xb') as stream:
                stream.write(content)
        release = _load_verified_release(bundle, digest(files['manifest.json']))
        database = Database(tmp_path / 'source.sqlite', schema_release=release)
    elif version == 150:
        schema = (
            Path(__file__).resolve().parents[2] / 'app/infrastructure/schemas/v1_5_evidence_150.sql'
        )
        database = Database(tmp_path / 'source.sqlite', migration=Migration(schema, 150))
    else:
        database = Database(tmp_path / 'source.sqlite')
    database.initialize()
    before = database.path.read_bytes()
    with patch('backend.app.infrastructure.schema_v20_release.load_release', return_value=release):
        source = evidence_database(database.path)
    assert source.read_only
    with source.transaction() as connection:
        assert (
            connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
            == version
        )
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute('DELETE FROM schema_migrations')
        # Even bypassing the application guard cannot turn a mode=ro connection into a writer.
        connection.set_authorizer(None)
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute('PRAGMA query_only=OFF')
            connection.execute('DELETE FROM schema_migrations')
    with pytest.raises(StorageUnavailable):
        with source.transaction(write=True):
            pytest.fail('Evidence must never supply a write transaction')
    with pytest.raises(StorageUnavailable):
        source.initialize()
    assert database.path.read_bytes() == before


def test_changed_frozen_metadata_and_unknown_history_are_not_guessed(tmp_path):
    database = Database(tmp_path / 'source.sqlite')
    database.initialize()
    with closing(sqlite3.connect(database.path, isolation_level=None)) as connection:
        connection.execute('UPDATE schema_migrations SET checksum=?', ('0' * 64,))
    selected = evidence_database(database.path)
    with pytest.raises(SchemaMismatch):
        with selected.transaction():
            pytest.fail('Frozen checksum must be checked in the actual snapshot')
    with closing(sqlite3.connect(database.path, isolation_level=None)) as connection:
        connection.execute('UPDATE schema_migrations SET version=999')
    with pytest.raises(SchemaMismatch):
        evidence_database(database.path)
    with pytest.raises(SchemaMismatch):
        evidence_database(Path('relative.sqlite'))
