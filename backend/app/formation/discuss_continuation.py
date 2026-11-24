"""Derive new formation continuations from actual frozen requests, never legacy target shapes."""

from copy import deepcopy

from backend.app.infrastructure.model_profile import DEFAULT_PROFILE
from backend.app.shared.command_execution import Rejected
from backend.app.shared.validation import strict_json_object

from .discuss_contracts import formation_discuss_input
from .repository import FormationRepository


def derive_discussion(connection, previous, root, instruction, key, version, *, retry=False):
    basis = strict_json_object(previous['execution_basis_json'])
    if 'formation' not in basis or retry and previous['operation'] != 'DISCUSS':
        return None
    frozen = basis['formation']['basis']
    if retry:
        head = FormationRepository(connection).head(root['assistant_document_id'])
        current = connection.execute(
            'SELECT d.content_version,r.id FROM requirement_documents d JOIN revisions r '
            'ON r.document_id=d.id AND r.source_content_version=d.content_version WHERE d.id=?',
            (root['assistant_document_id'],),
        ).fetchone()
        if (
            None if head is None else head['version'],
            current['id'],
            current['content_version'],
        ) != (
            frozen['formation_version'],
            frozen['document_revision_id'],
            frozen['content_version'],
        ):
            raise Rejected('STATE_CONFLICT')
    original = basis.get('formation_request')
    target = (
        deepcopy(basis['formation_selection'])
        if basis['formation_selection'] is not None
        else {
            'discussion_step_ref': None,
            'discussion_branch_ref': None,
            'branch_intent': None,
            'branch_resume_basis': None,
        }
    )
    target['branch_resume_basis'] = None
    if target['branch_intent'] == 'RESUME':
        target['branch_intent'] = 'ENTER'
    binding = root['discussion_state_json']['binding']
    return formation_discuss_input(
        {
            'requirement_id': root['id'],
            'document_id': root['assistant_document_id'],
            'expected_discussion_version': version,
            'operation': 'DISCUSS',
            'instruction': instruction,
            'target': target,
            'scope': basis['request']['scope'] if retry else binding['scope'],
            'source_refs': (original or basis['request'])['source_refs']
            if retry
            else binding['source_refs'],
            'proposal_ref': None if not retry or original is None else original['proposal_ref'],
            'proposal_intent': None
            if not retry or original is None
            else original['proposal_intent'],
            'acknowledge_source_changes': False,
            'idempotency_key': key,
        }
    )


def formation_catalog(catalog):
    if catalog.collaboration.formation_driven:
        return catalog
    return catalog.for_formation_profile(
        getattr(catalog, '_collaboration_profile', None) or DEFAULT_PROFILE, discussion_routes=True
    )
