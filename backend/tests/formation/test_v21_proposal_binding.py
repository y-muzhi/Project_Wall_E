"""Publication fingerprints protect use, not global counters or proposal UI flags."""

from dataclasses import replace
from copy import deepcopy

import pytest

from backend.app.formation.proposal_binding import publish_binding, check_binding, digest
from backend.app.formation.proposal_sources import ReferencedProposal
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.shared.command_execution import Rejected
from backend.tests.formation.test_v21_schema import database, released, workspace, head

__all__ = ['database', 'released', 'workspace']


def bound(connection, resources):
    head(connection)
    connection.execute("INSERT INTO formation_steps VALUES(1,'s2',1,2,2,'其他步骤','PLANNED',NULL)")
    connection.execute("INSERT INTO formation_results VALUES(1,'s2','s2.o1','其他成果','CONTENT')")
    connection.execute('UPDATE formation_heads SET next_step_no=3')
    root = RequirementRepository(connection).get_for_document(1, 1)
    revision = connection.execute('SELECT id FROM revisions WHERE document_id=1').fetchone()[0]
    payload = {
        'step_ref': 's1',
        'result_refs': ['s1.o1'],
        'source_refs': [],
        'goal_version': 1,
        'definition_version': 1,
        'document_revision_id': revision,
        'content_version': 1,
    }
    ref = {'message_id': 100, 'card_key': 'original'}
    binding = publish_binding(connection, root, 'STAGED_WRITE', payload, ref, 1, resources)
    proposal = ReferencedProposal(1, ref, 'PENDING', True, digest(binding), binding, payload)
    return root, proposal


def test_unrelated_order_focus_counters_self_flags_and_completed_owner_keep_original_binding(
    workspace,
):
    with workspace[0].transaction(write=True) as connection:
        root, proposal = bound(connection, workspace[2])
        original = deepcopy(proposal.binding)
        connection.execute("UPDATE formation_heads SET version=2,current_step_ref='s2'")
        connection.execute(
            "UPDATE formation_steps SET title='新显示名称',status='COMPLETED' WHERE step_ref='s1'"
        )
        connection.execute(
            "UPDATE formation_steps SET title='无关改名',definition_version=2 WHERE step_ref='s2'"
        )
        value = check_binding(
            connection,
            root,
            replace(proposal, needs_revision=False, disposition='DEFERRED'),
            'STAGED_WRITE',
            workspace[2],
        )
        assert value == original['protected_semantic_digest']
        assert proposal.binding == original


@pytest.mark.parametrize(
    'sql',
    [
        "UPDATE formation_heads SET goal_version=2,goal_text='新用途'",
        "UPDATE formation_steps SET definition_version=2 WHERE step_ref='s1'",
        "INSERT INTO formation_step_edges VALUES(1,'s2','s1','DEPENDENCY')",
    ],
)
def test_related_changes_including_new_incoming_relation_invalidate_original_projection(
    workspace, sql
):
    with workspace[0].transaction(write=True) as connection:
        root, proposal = bound(connection, workspace[2])
        connection.execute(sql)
        with pytest.raises(Rejected):
            check_binding(connection, root, proposal, 'STAGED_WRITE', workspace[2])


def test_lifecycle_permission_is_separate_and_never_rebases_original_binding(workspace):
    with workspace[0].transaction(write=True) as connection:
        root, proposal = bound(connection, workspace[2])
        connection.execute(
            "UPDATE formation_steps SET status='CANCELLED',position=-1 WHERE step_ref='s1'"
        )
        with pytest.raises(Rejected) as error:
            check_binding(connection, root, proposal, 'STAGED_WRITE', workspace[2])
        assert error.value.details['reason'] == 'INVALID_TRANSITION'


def test_damaged_binding_cannot_be_rebuilt_from_current_data(workspace):
    with workspace[0].transaction(write=True) as connection:
        root, proposal = bound(connection, workspace[2])
        damaged = deepcopy(proposal.binding)
        damaged['protected_semantic_digest'] = '0' * 64
        with pytest.raises(ValueError):
            check_binding(
                connection, root, replace(proposal, binding=damaged), 'STAGED_WRITE', workspace[2]
            )
        del damaged['step_definitions']
        with pytest.raises(ValueError):
            check_binding(
                connection, root, replace(proposal, binding=damaged), 'STAGED_WRITE', workspace[2]
            )


def test_publication_rejects_wrong_owner_definition_and_invalid_lifecycle(workspace):
    with workspace[0].transaction(write=True) as connection:
        root, proposal = bound(connection, workspace[2])
        payload = {**proposal.payload, 'definition_version': 2}
        with pytest.raises(Rejected) as error:
            publish_binding(
                connection, root, 'STAGED_WRITE', payload, proposal.reference, 1, workspace[2]
            )
        assert error.value.code == 'SOURCE_INVALID'
        connection.execute(
            "UPDATE formation_steps SET status='CANCELLED',position=-1 WHERE step_ref='s1'"
        )
        with pytest.raises(Rejected) as error:
            publish_binding(
                connection,
                root,
                'STAGED_WRITE',
                proposal.payload,
                proposal.reference,
                1,
                workspace[2],
            )
        assert error.value.details['reason'] == 'INVALID_TRANSITION'
