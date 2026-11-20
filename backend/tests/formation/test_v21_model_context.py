"""Accepted source facts project into the original eight-count, two-message execution chain."""

import asyncio
from copy import deepcopy
import json
from uuid import uuid4
import pytest

from backend.app.guide.collaboration_context import read_canonical, compile_context
from backend.app.guide.collaboration_counting import compile_counted, verify_counted
from backend.app.guide.commands import create_guide_run, cancel_guide_run
from backend.app.formation.commands import update_path
from backend.app.infrastructure.model_profile import ModelProfile, DEFAULT_PROFILE
from backend.app.infrastructure.resources import ConfigInvalid
from backend.tests.formation.test_v21_discuss_acceptance import (
    database,
    released,
    base_workspace,
    workspace,
    request,
    accepted,
)
from backend.tests.formation.test_v21_schema import head
from backend.tests.formation.test_v21_path_commands import request as path_request, snapshot
from backend.tests.guide.test_v15_counting import Counter

__all__ = ['database', 'released', 'base_workspace', 'workspace']


def canonical(workspace, body=None):
    result = accepted(workspace, request(workspace) if body is None else body)
    with workspace[0].transaction() as connection:
        value = read_canonical(connection, result['data']['guide_run_id'], workspace[2])
    return result, value


def test_wire_keeps_eight_roots_and_eight_actual_texts_without_authority(workspace):
    result, value = canonical(workspace)
    context = compile_context(value, workspace[2])
    wire = context.input
    assert list(wire) == [
        'schema_version',
        'structure',
        'goal_and_decisions',
        'project_position',
        'current_topic',
        'documents',
        'recent_history',
        'current_request',
    ]
    assert len(context.texts) == 8
    assert wire['project_position']['formation']['basis']['formation_version'] is None
    assert wire['current_request']['formation_selection'] == result['data']['accepted_target']
    assert all(
        not block['writable'] for document in wire['documents'] for block in document['blocks']
    )
    assert context.input_json == workspace[2].collaboration.serialize('Wire', wire)
    assert context.basis['canonical']['layout_version'] == 'formation_context_v21_1'
    assert 'protected_semantic_digest' not in context.input_json
    assert 'publication_binding' not in context.input_json
    assert context.texts[1] == context.input_json


def test_goal_sources_are_actual_visible_aliases_canonical_remains_detached(workspace):
    with workspace[0].transaction(write=True) as connection:
        head(connection)
        connection.execute(
            'UPDATE formation_heads SET goal_sources_json=? WHERE document_id=1',
            (json.dumps([{'kind': 'MESSAGE', 'message_id': 1}]),),
        )
    body = request(workspace)
    body['target']['discussion_step_ref'] = 's1'
    result, value = canonical(workspace, body)
    before = deepcopy(value)
    context = compile_context(value, workspace[2])
    assert value == before
    formed = context.input['project_position']['formation']
    assert formed['goal']['source_refs'] == ['m1']
    assert value['formation']['goal']['source_refs'] == [{'kind': 'MESSAGE', 'message_id': 1}]
    assert formed['selected_step']['status'] == 'IN_PROGRESS'
    assert formed['coverage']['included'] == [{'kind': 'STEP', 'ref': 's1'}]
    assert (
        context.input['current_request']['formation_selection'] == result['data']['accepted_target']
    )


def test_saved_material_replays_original_goal_after_actual_cancel_and_route_change(workspace):
    with workspace[0].transaction(write=True) as connection:
        head(connection)
    result, value = canonical(workspace)
    original = compile_context(value, workspace[2])
    cancelled = cancel_guide_run(
        workspace[1],
        {'guide_run_id': result['data']['guide_run_id'], 'idempotency_key': str(uuid4())},
    )
    assert cancelled['code'] == 'GUIDE_CANCELLED', cancelled
    changed = update_path(
        workspace[1],
        path_request(
            workspace, [{'type': 'SET_GOAL', 'text': '后来的真实新目标', 'source_refs': []}]
        ),
        catalog=workspace[2],
    )
    assert changed['code'] == 'UPDATED', changed
    with workspace[0].transaction() as connection:
        replay = read_canonical(
            connection, result['data']['guide_run_id'], workspace[2], require_current=False
        )
    assert compile_context(replay, workspace[2]).input_json == original.input_json


def test_optional_issue_material_has_explicit_omission_and_no_lifetime_cap(workspace):
    with workspace[0].transaction(write=True) as connection:
        head(connection)
        connection.executemany(
            "INSERT INTO formation_issues VALUES(1,?,'s1',NULL,?,'[]',0,'OPEN',NULL,'[]',NULL)",
            [(f'i{number}', f'待明确事项{number}') for number in range(1, 121)],
        )
        connection.execute('UPDATE formation_heads SET next_issue_no=121 WHERE document_id=1')
    body = request(workspace)
    body['target']['discussion_step_ref'] = 's1'
    _, value = canonical(workspace, body)
    assert len(value['formation']['coverage']['included']) == 100
    assert len(value['formation']['related_issues']) == 99
    assert (
        next(row for row in value['formation']['coverage']['omitted'] if row['kind'] == 'ISSUE')[
            'count'
        ]
        == 21
    )


def test_required_material_overflow_rolls_back_before_any_count_or_chat(workspace):
    with workspace[0].transaction(write=True) as connection:
        head(connection)
        connection.executemany(
            "INSERT INTO formation_issues VALUES(1,?,'s1',NULL,?,'[]',1,'OPEN',NULL,'[]',NULL)",
            [(f'i{number}', f'阻塞事项{number}') for number in range(1, 102)],
        )
        connection.execute('UPDATE formation_heads SET next_issue_no=102 WHERE document_id=1')
    body = request(workspace)
    body['target']['discussion_step_ref'] = 's1'
    before = snapshot(workspace[0])
    result = create_guide_run(workspace[1], body, catalog=workspace[2])
    assert result['code'] == 'CAPACITY_EXHAUSTED', result
    assert snapshot(workspace[0]) == before


def test_new_release_blocks_count_without_its_live_admission_then_replays_exact_eight_texts(
    workspace,
):
    _, value = canonical(workspace)
    counter = Counter(['OK'])
    profile = ModelProfile('private-offline-context-fixture', DEFAULT_PROFILE)
    with pytest.raises(ConfigInvalid):
        asyncio.run(compile_counted(value, workspace[2], profile, counter=counter))
    assert counter.calls == []

    async def offline_only():
        return None

    counted = asyncio.run(
        compile_counted(value, workspace[2], profile, counter=counter, admission_guard=offline_only)
    )
    assert len(counter.calls) == 1
    evidence = verify_counted(counted, workspace[2], profile)
    assert evidence['layout'] == 'formation_context_v21_1'
    assert counter.calls[0] == counted.texts
    assert evidence['release_sha256'] == workspace[2].collaboration.release_sha256
    assert evidence['compatibility_proved'] is False


def test_adjusted_other_step_hard_evidence_precedes_selected_optional_material(workspace):
    from backend.app.formation.model_material import capture_material
    from backend.app.infrastructure.requirement_repository import RequirementRepository

    with workspace[0].transaction(write=True) as connection:
        head(connection)
        connection.execute(
            "INSERT INTO formation_steps VALUES(1,'s2',1,2,2,'被调整的步骤','PLANNED',NULL)"
        )
        connection.execute(
            "INSERT INTO formation_results VALUES(1,'s2','s2.o1','另一成果','CONTENT')"
        )
        connection.executemany(
            "INSERT INTO formation_issues VALUES(1,?,'s1',NULL,?,'[]',0,'OPEN',NULL,'[]',NULL)",
            [(f'i{number}', f'普通事项{number}') for number in range(1, 101)],
        )
        connection.execute(
            "INSERT INTO formation_issues VALUES(1,'i101','s2',NULL,'必须处理的阻塞','[]',1,'OPEN',NULL,'[]',NULL)"
        )
        connection.execute('UPDATE formation_heads SET next_step_no=3,next_issue_no=102')
        root = RequirementRepository(connection).get_for_document(1, 1)
        material = capture_material(
            connection,
            root,
            {
                'discussion_step_ref': 's1',
                'discussion_branch_ref': None,
                'branch_intent': None,
                'branch_resume_basis': None,
            },
            workspace[2],
            required_steps=['s2'],
        )
    assert len(material['coverage']['included']) == 100
    assert {'kind': 'ISSUE', 'ref': 'i101'} in material['coverage']['included']
    issue = next(row for row in material['related_issues'] if row['issue_ref'] == 'i101')
    assert issue['blocking'] and issue['step_ref'] == 's2'
    assert (
        next(row for row in material['coverage']['omitted'] if row['kind'] == 'ISSUE')['count'] == 3
    )
