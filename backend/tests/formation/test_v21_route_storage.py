"""Actual route storage, local ID allocation and rank uniqueness on Schema210."""

from copy import deepcopy

import pytest

from backend.app.formation.path_plan import prepare_route
from backend.app.formation.repository import FormationRepository
from backend.app.formation.route_storage import persist_route, resolve_route
from backend.tests.formation.test_v21_contracts import add_step
from backend.tests.formation.test_v21_schema import database, released, workspace, head

__all__ = ['database', 'released', 'workspace']


def current(connection):
    repository = FormationRepository(connection)
    state, steps, branches, issues, edges = repository.graph(1)
    results = {
        row['result_ref']: dict(row)
        for row in connection.execute('SELECT * FROM formation_results WHERE document_id=1')
    }
    return state, steps, results, branches, issues, set(edges['DEPENDENCY']), set(edges['REPLACES'])


def save(connection, changes):
    before = current(connection)
    planned = prepare_route(*before, changes, [])
    mapping, counters = FormationRepository(connection).allocate_path_references(1, planned.scope)
    resolved = resolve_route(planned, mapping, counters)
    persist_route(
        connection,
        before=before,
        resolved=resolved,
        verified_links=(),
        link_event_ids=(),
        summaries={},
    )
    return mapping, resolved


def test_actual_forward_ids_and_order_save_without_disabling_unique_index(workspace):
    db = workspace[0]
    with db.transaction(write=True) as connection:
        head(connection)
    first = add_step()
    first['before_step_ref'] = 's1'
    first['title'] = 'new_step_1'
    with db.transaction(write=True) as connection:
        mapping, resolved = save(connection, [first])
        assert mapping == {'new_step_1': 's2', 'new_result_1': 's2.o1'}
        assert resolved.steps['s2']['title'] == 'new_step_1'
    with db.transaction() as connection:
        assert [
            tuple(row)
            for row in connection.execute(
                'SELECT step_ref,position FROM formation_steps ORDER BY position'
            )
        ] == [('s2', 1), ('s1', 2)]
        assert connection.execute('SELECT next_step_no,version FROM formation_heads').fetchone()[
            :
        ] == (3, 2)
        assert (
            connection.execute(
                "SELECT next_result_no FROM formation_steps WHERE step_ref='s2'"
            ).fetchone()[0]
            == 2
        )
        assert connection.execute('SELECT count(*) FROM revisions').fetchone()[0] == 2


def test_rollback_after_real_route_save_restores_rows_counter_and_positions(workspace):
    db = workspace[0]
    with db.transaction(write=True) as connection:
        head(connection)
    with db.transaction() as connection:
        before = deepcopy(current(connection))
    with pytest.raises(RuntimeError, match='after route'):
        with db.transaction(write=True) as connection:
            save(connection, [add_step()])
            raise RuntimeError('injected after route')
    with db.transaction() as connection:
        assert current(connection) == before


def test_existing_result_allocator_and_definition_advance_only_in_shared_transaction(workspace):
    db = workspace[0]
    with db.transaction(write=True) as connection:
        head(connection)
        mapping, resolved = save(
            connection,
            [
                {
                    'type': 'ADD_RESULT',
                    'step_ref': 's1',
                    'temp_result_ref': 'new_result_1',
                    'description': '独立分析依据',
                    'kind': 'ANALYSIS',
                }
            ],
        )
        assert mapping == {'new_result_1': 's1.o2'}
        assert resolved.steps['s1']['definition_version'] == 2
    with db.transaction() as connection:
        row = connection.execute(
            'SELECT next_result_no,definition_version FROM formation_steps'
        ).fetchone()
        assert tuple(row) == (3, 2)
        assert [
            row[0]
            for row in connection.execute(
                'SELECT result_ref FROM formation_results ORDER BY result_ref'
            )
        ] == ['s1.o1', 's1.o2']


def test_symbolic_plan_cannot_use_partial_or_reused_identity_allocation(workspace):
    db = workspace[0]
    with db.transaction(write=True) as connection:
        head(connection)
        before = current(connection)
        plan = prepare_route(*before, [add_step()], [])
        with pytest.raises(ValueError):
            resolve_route(plan, {'new_step_1': 's1', 'new_result_1': 's1.o1'}, {'new_step_1': 2})
        with pytest.raises(ValueError):
            resolve_route(plan, {'new_step_1': 's2'}, {'new_step_1': 2})
