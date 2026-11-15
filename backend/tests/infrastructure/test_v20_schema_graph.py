"""New SQL graph constraints on a real nonempty legacy fixture.

Execution profiles below are deliberately not runnable; this suite tests storage
constraints and cannot be used as model, Git or runtime admission evidence.
"""

from contextlib import closing
import sqlite3
import json
import pytest

from backend.tests.requirements.test_v15_foundation import tmp_path, setup
from backend.tests.documents.test_v15_documents import workspace
from backend.tests.infrastructure.test_v20_schema_migration import seeded_source, AT
from backend.app.infrastructure.database import _statements
from backend.app.infrastructure.schema_v20_assembly import upgrade_sql
from backend.app.infrastructure.schema_inspection import verify_integrity

KEY = '00000000-0000-4000-8000-000000000091'


def insert(connection, table, **values):
    connection.execute(
        f'INSERT INTO "{table}"({",".join(values)}) VALUES({",".join("?" for _ in values)})',
        tuple(values.values()),
    )


def operation(connection, identity, task_id, kind, resource, resource_id):
    insert(
        connection,
        'code_operations',
        id=identity,
        task_id=task_id,
        testing_task_id=None,
        resource_kind=resource,
        resource_id=resource_id,
        session_id=None,
        operation_type=kind,
        idempotency_key=KEY,
        expected_state_version=1 if task_id else None,
        fixed_input='{}',
        control_generation=1 if task_id else None,
        status='SUCCEEDED',
        created_at=AT,
    )


@pytest.fixture
def graph(workspace, tmp_path):
    seeded_source(workspace)
    target = workspace[0].backup_to(tmp_path / 'graph.sqlite')
    with closing(sqlite3.connect(target, isolation_level=None)) as connection:
        connection.execute('PRAGMA foreign_keys=OFF')
        connection.execute('BEGIN')
        for statement in _statements(upgrade_sql()):
            connection.execute(statement)
        connection.commit()
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('BEGIN')
        insert(
            connection,
            'code_repositories',
            id=1,
            name='fixture',
            canonical_root='fixture-root',
            git_common_dir='fixture-git',
            object_format='sha1',
            created_at=AT,
        )
        insert(connection, 'code_check_sets', id=1, name='checks', created_at=AT)
        insert(
            connection,
            'code_check_set_versions',
            id=1,
            check_set_id=1,
            version=1,
            owner_module='CODING',
            protocol_version='CHECK20-CONTROL-1',
            items='[]',
            coverage_plan='[]',
            created_at=AT,
        )
        insert(connection, 'code_execution_profiles', id=1, name='profile', created_at=AT)
        insert(
            connection,
            'code_execution_profile_versions',
            id=1,
            profile_id=1,
            version=1,
            executor='{}',
            git='{}',
            models='{}',
            environment='{}',
            commands='[]',
            capture_rules='{}',
            delivery=None,
            check_set_version_id=1,
            limits='{}',
            capability_evidence_refs='[]',
            created_at=AT,
        )
        operation(connection, 1, None, 'REGISTER_BASE', 'REPOSITORY', 1)
        insert(
            connection,
            'code_snapshots',
            id=1,
            repository_id=1,
            registration_operation_id=1,
            content_profile_version_id=1,
            commit_oid='a' * 40,
            content_tree_oid='b' * 40,
            retention_ref='refs/walle/baselines/1',
            content_policy_version='GIT20-BASELINE-1',
            registered_at=AT,
            created_at=AT,
        )
        for identity in (1, 2):
            insert(
                connection,
                'code_authorizations',
                id=identity,
                task_id=identity,
                profile_version_id=1,
                scope='{}',
                status='BOUND_PENDING_APPLY',
                approved_at=AT,
                actor_ref='fixture',
            )
            insert(
                connection,
                'code_tasks',
                id=identity,
                requirement_id=1,
                document_id=identity,
                design_revision_id=identity,
                repository_id=1,
                base_snapshot_id=1,
                target_branch='refs/heads/main',
                execution_profile_version_id=1,
                authorization_id=identity,
                budget_limit_cny='1.000000',
                status='PENDING',
                phase='PREPARING',
                state_version=1,
                control_generation=1,
                created_at=AT,
                updated_at=AT,
            )
            operation(connection, identity + 1, identity, 'CAPTURE_AND_CHECK', 'TASK', identity)
            insert(
                connection,
                'code_candidates',
                id=identity,
                task_id=identity,
                base_snapshot_id=1,
                capture_operation_id=identity + 1,
                content_store_key='fixture',
                content_tree_oid='c' * 40,
                parent_candidate_id=None,
                role='BACKEND',
                control_generation=1,
                content_policy_version='CONTENT20-STORE-1',
                manifest_sha256='d' * 64,
                captured_at=AT,
                file_count=0,
                byte_count=0,
                created_at=AT,
            )
        verify_integrity(connection)
        connection.commit()
        yield connection


def test_current_candidate_cannot_point_to_another_task(graph):
    graph.execute('BEGIN')
    graph.execute('UPDATE code_tasks SET current_candidate_id=1 WHERE id=1')
    graph.commit()
    graph.execute('BEGIN')
    graph.execute('UPDATE code_tasks SET current_candidate_id=2 WHERE id=1')
    with pytest.raises(sqlite3.IntegrityError):
        graph.commit()
    graph.rollback()
    graph.execute('BEGIN')
    verify_integrity(graph)
    graph.rollback()


def test_candidate_bytes_and_identity_are_immutable_and_retained(graph):
    for statement in (
        "UPDATE code_candidates SET content_tree_oid='" + 'e' * 40 + "' WHERE id=1",
        "UPDATE code_candidates SET manifest_sha256='" + 'e' * 64 + "' WHERE id=1",
        'DELETE FROM code_candidates WHERE id=1',
    ):
        with pytest.raises(sqlite3.IntegrityError):
            graph.execute(statement)


def test_original_steps_are_contiguous_and_owner_specific(graph):
    operation(graph, 9, 1, 'TERMINATE', 'TASK', 1)
    common = dict(operation_id=9, status='PENDING', fixed_input='{}')
    with pytest.raises(sqlite3.IntegrityError):
        insert(graph, 'code_operation_steps', **common, step_no=1, step_type='FENCE')
    with pytest.raises(sqlite3.IntegrityError):
        insert(graph, 'code_operation_steps', **common, step_no=2, step_type='REVOKE_GATEWAY')
    insert(graph, 'code_operation_steps', **common, step_no=1, step_type='BLOCK_NEW')
    insert(graph, 'code_operation_steps', **common, step_no=2, step_type='REVOKE_GATEWAY')


def test_polymorphic_observation_cannot_borrow_another_task_operation(graph):
    insert(
        graph,
        'code_workspaces',
        id=1,
        task_id=1,
        base_snapshot_id=1,
        private_location_key='fixture',
        status='PREPARING',
        created_at=AT,
    )
    insert(
        graph,
        'code_instances',
        id=1,
        task_id=1,
        workspace_id=1,
        executor_version='1.19.5',
        control_generation=1,
        effective_profile_version_id=1,
        status='STARTING',
        created_at=AT,
    )
    row = dict(
        id=1,
        task_id=1,
        instance_id=1,
        control_generation=1,
        kind='CONTROL',
        text='storage test observation',
        observed_at=AT,
        source_kind='OPERATION',
    )
    with pytest.raises(sqlite3.IntegrityError):
        insert(graph, 'code_execution_records', **row, source_id=3)
    with pytest.raises(sqlite3.IntegrityError):
        insert(graph, 'code_execution_records', **row, source_id=999)
    insert(graph, 'code_execution_records', **row, source_id=2)


def test_waiting_source_and_open_uniqueness_are_owner_scoped(graph):
    row = dict(
        task_id=1,
        testing_task_id=None,
        kind='OPERATION_RESULT',
        source_kind='OPERATION',
        resume_phase='PREPARING',
        status='OPEN',
        created_at=AT,
    )
    with pytest.raises(sqlite3.IntegrityError):
        insert(graph, 'code_waiting_items', id=1, **row, source_id=3)
    insert(graph, 'code_waiting_items', id=1, **row, source_id=2)
    with pytest.raises(sqlite3.IntegrityError):
        insert(graph, 'code_waiting_items', id=2, **row, source_id=2)


def test_defect_basis_has_real_foreign_keys_and_evidence_is_owner_bound(graph):
    quote = graph.execute(
        'SELECT substr(markdown_snapshot,1,12) FROM revisions WHERE id=1'
    ).fetchone()[0]
    basis = json.dumps({'document_id': 1, 'revision_id': 1, 'quote': quote}, ensure_ascii=False)
    insert(
        graph,
        'code_defects',
        id=1,
        task_id=1,
        candidate_id=1,
        actual_behavior='Observed mismatch',
        expected_behavior='Fixed design behavior',
        basis_ref=basis,
        created_at=AT,
        actor_ref='fixture',
    )
    assert graph.execute(
        'SELECT basis_document_id,basis_revision_id FROM code_defects WHERE id=1'
    ).fetchone() == (1, 1)
    with pytest.raises(sqlite3.IntegrityError):
        insert(
            graph,
            'code_defect_evidence_refs',
            defect_id=1,
            ordinal=1,
            kind='OPERATION',
            source_id=3,
        )
    insert(
        graph, 'code_defect_evidence_refs', defect_id=1, ordinal=1, kind='OPERATION', source_id=2
    )
    with pytest.raises(sqlite3.IntegrityError):
        insert(
            graph,
            'code_defect_evidence_refs',
            defect_id=1,
            ordinal=3,
            kind='OPERATION',
            source_id=2,
        )
    bad = json.dumps({'document_id': 1, 'revision_id': 1, 'quote': 'not-an-original-substring'})
    with pytest.raises(sqlite3.IntegrityError):
        insert(
            graph,
            'code_defects',
            id=2,
            task_id=1,
            candidate_id=1,
            actual_behavior='Mismatch',
            expected_behavior='Expected',
            basis_ref=bad,
            created_at=AT,
            actor_ref='fixture',
        )
