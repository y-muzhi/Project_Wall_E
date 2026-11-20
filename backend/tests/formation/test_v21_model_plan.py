"""Whole-unit ordinary planning reads real accepted material and never writes or consumes IDs."""

from copy import deepcopy
from uuid import uuid4
import pytest

from backend.app.documents.commands import create_document
from backend.app.formation.model_plan import prepare_model
from backend.app.formation.path_scope import planned_references
from backend.app.guide.collaboration_context import read_canonical, compile_context
from backend.app.guide.progress_application import ProgressInvalid
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.shared.validation import InvalidInput
from backend.tests.formation.test_v21_discuss_acceptance import (
    database,
    released,
    base_workspace,
    workspace,
    request,
    accepted,
)
from backend.tests.formation.test_v21_schema import head
from backend.tests.formation.test_v21_path_commands import snapshot
from backend.tests.formation.test_v21_model_contracts import examples
from backend.tests.formation.test_v21_relation_reads import associated

__all__ = ['database', 'released', 'base_workspace', 'workspace']


def round_context(workspace, document_id=1, selected=None):
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, document_id)
    body = request(
        workspace, document_id=document_id, expected_discussion_version=root['discussion_version']
    )
    body['target']['discussion_step_ref'] = selected
    result = accepted(workspace, body)
    with workspace[0].transaction() as connection:
        value = read_canonical(connection, result['data']['guide_run_id'], workspace[2])
    return compile_context(value, workspace[2])


def plan(workspace, context, changes):
    before = snapshot(workspace[0])
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(
            1, context.canonical['authorization']['target_document_id']
        )
        result = prepare_model(
            connection,
            root,
            context,
            {'basis': context.canonical['formation']['basis'], 'changes': changes},
            workspace[2],
        )
    assert snapshot(workspace[0]) == before
    return result


def test_initialize_forward_references_and_same_round_recommendation_do_not_allocate(workspace):
    context = round_context(workspace)
    initial, recommendation = deepcopy(examples()[0]), deepcopy(examples()[10])
    recommendation['step_ref'] = 'new_step_1'
    source = context.input['current_request']['message_ref']
    initial['goal']['source_refs'] = recommendation['source_refs'] = [source]
    result = plan(workspace, context, [initial, recommendation])
    assert result.initializing and result.changed
    assert result.mapping == {'new_step_1': 's1', 'new_result_1': 's1.o1'}
    assert result.route.steps['s1']['status'] == 'IN_PROGRESS'
    assert result.route.head['current_step_ref'] == 's1'
    assert result.route.head['next_step_no'] == 2
    assert (
        result.recommendations[0]['source_refs'][0]['message_id']
        == context.canonical['current_message']['message_id']
    )


def test_neighbor_definition_is_read_and_only_planned_step_can_be_maintained(workspace):
    with workspace[0].transaction(write=True) as connection:
        head(connection)
        connection.execute(
            "INSERT INTO formation_steps VALUES(1,'s2',1,2,2,'后续步骤','PLANNED',NULL)"
        )
        connection.execute(
            "INSERT INTO formation_results VALUES(1,'s2','s2.o1','后续成果','CONTENT')"
        )
        connection.execute("INSERT INTO formation_step_edges VALUES(1,'s2','s1','DEPENDENCY')")
        connection.execute('UPDATE formation_heads SET next_step_no=3 WHERE document_id=1')
    context = round_context(workspace, selected='s1')
    included = context.input['project_position']['formation']['coverage']['included']
    assert any(
        item['ref'] == 's2' and item['definition']['title'] == '后续步骤' for item in included
    )
    change = deepcopy(examples()[2])
    change.update(
        step_ref='s2',
        title='完善后续步骤',
        add_results=[{'temp_ref': 'new_result_1', 'description': '补充成果', 'kind': 'ANALYSIS'}],
    )
    result = plan(workspace, context, [change])
    assert result.route.steps['s2']['definition_version'] == 2
    assert result.route.results['s2.o2']['kind'] == 'ANALYSIS'
    assert result.mapping['new_result_1'] == 's2.o2'
    change['step_ref'] = 's1'
    with pytest.raises(ProgressInvalid):
        plan(workspace, context, [change])


def test_unread_existing_identity_and_missing_alias_cannot_grant_mutation(workspace):
    with workspace[0].transaction(write=True) as connection:
        head(connection)
        connection.execute(
            "INSERT INTO formation_steps VALUES(1,'s2',1,2,2,'无关步骤','PLANNED',NULL)"
        )
        connection.execute("INSERT INTO formation_results VALUES(1,'s2','s2.o1','成果','CONTENT')")
        connection.execute('UPDATE formation_heads SET next_step_no=3 WHERE document_id=1')
    context = round_context(workspace, selected='s1')
    change = deepcopy(examples()[2])
    change['step_ref'] = 's2'
    with pytest.raises(ProgressInvalid):
        plan(workspace, context, [change])
    change = deepcopy(examples()[4])
    change['source_refs'] = ['m999999']
    with pytest.raises(ProgressInvalid):
        plan(workspace, context, [change])


def test_issue_and_branch_forward_declarations_resolve_then_keep_user_boundaries(workspace):
    context = round_context(workspace)
    values = examples()
    initial = deepcopy(values[0])
    initial['goal']['source_refs'] = [context.input['current_request']['message_ref']]
    source = context.input['current_request']['message_ref']
    branch, issue = deepcopy(values[6]), deepcopy(values[4])
    branch.update(origin_step_ref='new_step_1', return_step_ref='new_step_1', source_refs=[source])
    issue.update(step_ref='new_step_1', branch_ref='new_branch_1', source_refs=[source])
    result = plan(workspace, context, [initial, issue, branch])
    assert list(result.mapping) == ['new_step_1', 'new_result_1', 'new_issue_1', 'new_branch_1']
    assert result.route.issues['i1']['branch_ref'] == 'b1'
    assert result.route.branches['b1']['return_step_ref'] == 's1'
    assert (
        result.route.issues['i1']['disposition'] == result.route.branches['b1']['status'] == 'OPEN'
    )
    focused = {'type': 'SET_BRANCH_FOCUS', 'branch_ref': 'new_branch_1', 'reason': '需要讨论'}
    with pytest.raises(ProgressInvalid):
        plan(workspace, context, [initial, issue, branch, focused])


def test_real_body_alias_association_is_verified_but_never_written_during_planning(workspace):
    created = create_document(
        workspace[1],
        {
            'requirement_id': 1,
            'name': '可关联的实际文档',
            'document_kind': 'REQUIREMENT_BRIEF',
            'template_ref': workspace[2].collaboration.reference('structure.brief'),
            'idempotency_key': str(uuid4()),
        },
        catalog=workspace[2],
    )
    assert created['code'] == 'CREATED', created
    doc = created['data']['document']['id']
    context = round_context(workspace, doc)
    initial = deepcopy(examples()[0])
    initial['goal']['source_refs'] = [context.input['current_request']['message_ref']]
    link = deepcopy(examples()[11])
    link.update(
        step_ref='new_step_1',
        result_refs=['new_result_1'],
        document_refs=[context.input['documents'][0]['blocks'][0]['ref']],
        source_refs=[context.input['current_request']['message_ref']],
    )
    result = plan(workspace, context, [initial, link])
    assert result.associations[0]['verified'].document_id == doc
    assert result.associations[0]['verified'].step_ref == 's1'


def test_read_active_review_uses_original_owner_and_current_range_aliases(workspace):
    doc = associated(workspace)
    context = round_context(workspace, doc, selected='s1')
    visible = context.input['documents'][0]['blocks']
    change = deepcopy(examples()[11])
    change.update(
        document_refs=[row['ref'] for row in visible[:2]],
        source_refs=[context.input['current_request']['message_ref']],
        review_of='a1',
    )
    result = plan(workspace, context, [change])
    assert result.associations[0]['reviewed']['artifact_ref'] == 'a1'
    changed = deepcopy(change)
    changed['document_refs'] = ['d999v1b1']
    with pytest.raises(ProgressInvalid):
        plan(workspace, context, [changed])


def test_expanded_results_obey_original_batch_and_per_step_limits(workspace):
    context = round_context(workspace)
    initial = deepcopy(examples()[0])
    initial['goal']['source_refs'] = [context.input['current_request']['message_ref']]
    update = deepcopy(examples()[2])
    update.update(
        step_ref='new_step_1',
        title=None,
        add_results=[
            {'temp_ref': f'new_result_{number}', 'description': f'成果{number}', 'kind': 'CONTENT'}
            for number in range(2, 21)
        ],
    )
    result = plan(workspace, context, [update, initial])
    assert len(result.route.results) == 20
    assert result.route.steps['s1']['next_result_no'] == 21
    update['add_results'].append(
        {'temp_ref': 'new_result_21', 'description': '超过步骤边界', 'kind': 'CONTENT'}
    )
    with pytest.raises((InvalidInput, ProgressInvalid)):
        plan(workspace, context, [initial, update])


def test_pure_scope_numbering_is_identical_to_manual_commit_calculation(workspace):
    context = round_context(workspace)
    initial = deepcopy(examples()[0])
    initial['goal']['source_refs'] = [context.input['current_request']['message_ref']]
    result = plan(workspace, context, [initial])
    mapping, _, next_step = planned_references(
        result.before[0], result.route.scope, result.before[1]
    )
    assert mapping == result.mapping
    assert next_step == result.route.head['next_step_no']


def test_path_publication_can_reference_a_carried_dependency_but_cannot_modify_its_unread_definition(
    workspace,
):
    from backend.app.formation.model_publication import prepare_publication
    from backend.tests.formation.test_v21_proposal_contracts import group

    with workspace[0].transaction(write=True) as connection:
        head(connection)
        connection.execute(
            "INSERT INTO formation_steps VALUES(1,'s2',1,2,2,'只携带依赖身份','IN_PROGRESS',NULL)"
        )
        connection.execute(
            "INSERT INTO formation_results VALUES(1,'s2','s2.o1','未发送的成果定义','CONTENT')"
        )
        connection.execute("INSERT INTO formation_step_edges VALUES(1,'s1','s2','DEPENDENCY')")
        connection.execute('UPDATE formation_heads SET next_step_no=3 WHERE document_id=1')
    context = round_context(workspace, selected='s1')
    assert context.canonical['formation']['selected_step']['dependencies'] == ['s2']
    assert all(row['ref'] != 's2' for row in context.canonical['formation']['coverage']['included'])
    card = group('FORMATION_PATH_CHANGE')
    card['action_payload']['basis'] = deepcopy(context.canonical['formation']['basis'])
    card['action_payload']['changes'][0]['dependencies'] = ['s2']
    before = snapshot(workspace[0])
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, 1)
        run = connection.execute('SELECT * FROM guide_runs WHERE id=1').fetchone()
        stored, _ = prepare_publication(
            connection,
            root,
            run,
            context,
            card,
            workspace[2],
            plan=None,
            reference_map={},
            discussion=root['discussion_state_json'],
        )
        assert stored['action_payload']['changes'][0]['dependencies'] == ['s2']
        card['action_payload']['changes'] = [
            {'type': 'RENAME_STEP', 'step_ref': 's2', 'title': '不应凭身份改名'}
        ]
        with pytest.raises(ProgressInvalid):
            prepare_publication(
                connection,
                root,
                run,
                context,
                card,
                workspace[2],
                plan=None,
                reference_map={},
                discussion=root['discussion_state_json'],
            )
    assert snapshot(workspace[0]) == before
