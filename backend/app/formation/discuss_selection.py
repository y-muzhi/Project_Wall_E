"""Reuse native state transitions when an actual discussion is accepted, once per C01 transaction."""

from dataclasses import dataclass

from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.shared.command_execution import Rejected

from .events import scalar_snapshot, source_members
from .native_state import StateMutation, apply_state_command
from .path_events import allocate_event_ids, write_facts, write_headers
from .path_facts import RouteFact
from .repository import FormationRepository
from .state_commands import version_basis


@dataclass(frozen=True)
class SelectionPlan:
    before: tuple | None
    commands: tuple
    normalized: dict


def prepare_selection(connection, root, selection):
    repository = FormationRepository(connection)
    head = repository.head(root['assistant_document_id'])
    step_ref = selection['discussion_step_ref']
    branch_ref = selection['discussion_branch_ref']
    if head is None:
        if step_ref is not None or branch_ref is not None:
            _conflict('FORMATION_NOT_INITIALIZED', step_ref)
        return SelectionPlan(None, (), dict(selection))
    graph = repository.graph(root['assistant_document_id'])
    head, steps, branches, issues, edges = graph
    commands = []
    if step_ref is not None:
        step = steps.get(step_ref)
        if step is None:
            _conflict('TARGET_CHANGED', step_ref)
        if step['status'] in ('PLANNED', 'PAUSED'):
            commands.append(
                {
                    'action': 'START_STEP' if step['status'] == 'PLANNED' else 'RESUME_STEP',
                    'step_ref': step_ref,
                }
            )
    if branch_ref is None:
        if not commands:
            commands.append({'action': 'SWITCH_STEP', 'step_ref': step_ref})
    elif selection['branch_intent'] == 'RESUME':
        branch = branches.get(branch_ref)
        if branch is None:
            _conflict('BRANCH_STATE_CHANGED', step_ref)
        commands.append(
            {
                'action': 'RESUME_BRANCH',
                'step_ref': step_ref,
                'branch_ref': branch_ref,
                'expected_branch_status': selection['branch_resume_basis'][
                    'expected_branch_status'
                ],
                'expected_branch_event_id': selection['branch_resume_basis'][
                    'expected_branch_event_id'
                ],
                'enter_after_resume': True,
            }
        )
    else:
        commands.append({'action': 'ENTER_BRANCH', 'step_ref': step_ref, 'branch_ref': branch_ref})
    # Pure native planning checks the complete graph before allocating anything.
    current = (head, steps, branches, issues)
    for command in commands:
        result = apply_state_command(
            *current,
            command,
            lambda: 1,
            dependencies=edges['DEPENDENCY'],
            replacements=edges['REPLACES'],
        )
        current = (result.head, result.steps, result.branches, result.issues)
    normalized = dict(selection)
    if branch_ref is not None:
        normalized.update(branch_intent='ENTER', branch_resume_basis=None)
    return SelectionPlan(graph, tuple(commands), normalized)


def _conflict(reason, step_ref=None):
    raise Rejected(
        'STATE_CONFLICT', details={'reason': reason, 'step_ref': step_ref, 'proposal': None}
    )


def apply_selection(connection, root_before, plan, message_id, run_id, key, at):
    if plan.before is None:
        return lambda: ()
    head, steps, branches, issues, edges = plan.before
    current = (head, steps, branches, issues)
    transitions = []
    for command in plan.commands:
        mutation = apply_state_command(
            *current,
            command,
            lambda: 1,
            dependencies=edges['DEPENDENCY'],
            replacements=edges['REPLACES'],
        )
        if mutation.changed:
            transitions.append((command, mutation.action))
        current = (mutation.head, mutation.steps, mutation.branches, mutation.issues)
    if not transitions:
        return lambda: ()
    keys = [(action, str(index)) for index, (_, action) in enumerate(transitions)]
    identities = allocate_event_ids(connection, keys)
    current = (head, steps, branches, issues)
    owners = {}
    for index, (command, _) in enumerate(transitions):
        owner = keys[index]
        mutation = apply_state_command(
            *current,
            command,
            lambda owner=owner: identities[owner],
            dependencies=edges['DEPENDENCY'],
            replacements=edges['REPLACES'],
        )
        for kind, before, after in (
            ('STEP', current[1], mutation.steps),
            ('BRANCH', current[2], mutation.branches),
            ('ISSUE', current[3], mutation.issues),
        ):
            for ref, value in after.items():
                if before[ref] != value:
                    owners[(kind, ref)] = owner
        current = (mutation.head, mutation.steps, mutation.branches, mutation.issues)
    final = StateMutation(keys[-1][0], *current, True)
    repository = FormationRepository(connection)
    document_id = root_before['assistant_document_id']
    repository.save_state(document_id, (head, steps, branches, issues), final)
    document = connection.execute(
        'SELECT d.content_version,r.id AS revision_id FROM requirement_documents d JOIN revisions r '
        'ON r.document_id=d.id AND r.source_content_version=d.content_version WHERE d.id=?',
        (document_id,),
    ).fetchone()
    root_after = RequirementRepository(connection).get_for_document(root_before['id'], document_id)
    after_head = repository.head(document_id, required=True)
    facts = []
    for kind, previous, following in (
        ('STEP', steps, final.steps),
        ('BRANCH', branches, final.branches),
        ('ISSUE', issues, final.issues),
    ):
        for ref, old in previous.items():
            new = following[ref]
            if old == new:
                continue
            members = ()
            if kind == 'BRANCH' and old['result_sources_json'] != new['result_sources_json']:
                members = tuple(
                    source_members(
                        'BRANCH_RESULT_SOURCE',
                        old['result_sources_json'],
                        new['result_sources_json'],
                    )
                )
            facts.append(
                RouteFact(
                    kind,
                    ref,
                    scalar_snapshot(kind, old),
                    scalar_snapshot(kind, new),
                    owners[(kind, ref)],
                    members,
                )
            )

    def finish_events():
        views = write_headers(
            connection,
            root=root_before,
            command={'type': 'FORMATION_DISCUSS_TARGET', 'target': plan.normalized},
            event_ids=identities,
            facts=facts,
            extra_counts={},
            message_id=message_id,
            key=key,
            at=at,
            reason='接受文档形成讨论目标',
            version_before=version_basis(root_before, head, document),
            version_after=version_basis(root_after, after_head, document),
            head_before=head,
            head_after=after_head,
            actor='USER',
            source_run_id=run_id,
        )
        refs = set()
        for event_id in identities.values():
            for ref in (head['current_step_ref'], after_head['current_step_ref']):
                if ref is not None:
                    refs.add((event_id, 'STEP', ref))
            for ref in (head['active_branch_ref'], after_head['active_branch_ref']):
                if ref is not None:
                    refs.add((event_id, 'BRANCH', ref))
        write_facts(connection, document_id, identities, views, facts, references=refs)
        return tuple(identities.values())

    return finish_events
