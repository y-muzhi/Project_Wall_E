"""User-owned COMPLETE_STEP: real closure, remaining work, focus, D/F and receipt."""

from copy import deepcopy

from backend.app.documents.guards import assert_idle
from backend.app.documents.markdown import DocumentInvalid
from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.identifiers import (
    EntityKind,
    entity_id,
    increment,
    require_write_transaction,
)
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.requirements.source_refs import verify_source_refs
from backend.app.shared.command_execution import Rejected
from backend.app.shared.validation import strict_json_object

from .closure_snapshot import ClosureBuilder, write_closure
from .closure_sources import source_reader
from .events import scalar_snapshot
from .graph import validate_graph
from .native_state import StateMutation, conflict
from .path_events import allocate_event_ids, write_facts, write_headers
from .path_facts import RouteFact
from .repository import FormationRepository
from .state_commands import receipt, version_basis


def remaining_changes(steps, branches, issues, command):
    changes = []
    for kind, field, rows, owner, state_field in (
        ('ISSUE', 'issue_dispositions', issues, 'step_ref', 'disposition'),
        ('BRANCH', 'branch_dispositions', branches, 'return_step_ref', 'status'),
    ):
        for action in command[field]:
            row = rows.get(action['ref'])
            if row is None or row[owner] != command['step_ref']:
                conflict('TARGET_CHANGED', command['step_ref'])
            disposition = action['disposition']
            if disposition == 'KEEP_OPEN':
                continue
            if row[state_field] not in ('OPEN', 'DEFERRED'):
                conflict('INVALID_TRANSITION', command['step_ref'])
            if disposition == 'TRANSFER':
                target = steps.get(action['to_step_ref'])
                if (
                    target is None
                    or target['status'] == 'CANCELLED'
                    or action['to_step_ref'] == row[owner]
                ):
                    conflict('INVALID_TRANSITION', action['to_step_ref'])
                event = 'ISSUE_MOVED' if kind == 'ISSUE' else 'BRANCH_RETURN_CHANGED'
            else:
                event = (
                    'ISSUE_DISPOSITION_CHANGED' if kind == 'ISSUE' else 'BRANCH_DISPOSITION_CHANGED'
                )
                if (
                    kind == 'ISSUE'
                    and row[state_field] == disposition
                    and row['disposition_reason'] == action['reason']
                ):
                    continue
            changes.append((kind, event, action))
    return tuple(changes)


def apply(
    connection,
    root,
    command,
    key,
    at,
    *,
    resources,
    transaction=None,
    assistant_id=None,
    run_id=None,
    source=None,
):
    require_write_transaction(connection)
    if command['action'] != 'COMPLETE_STEP':
        raise ValueError('Completion handler requires its strict native action')
    if at < root['updated_at']:
        raise ValueError('Completion cannot precede the stored activity')
    if transaction is None:
        assert_idle(
            connection,
            root,
            remaining_conflicts=frozenset({'MANUAL_DRAFT', 'GUIDE_RUN', 'SUGGESTION_BATCH'}),
        )
    repository = FormationRepository(connection)
    head, steps, branches, issues, edges = repository.graph(root['assistant_document_id'])
    ref = command['step_ref']
    step = steps.get(ref)
    if step is None:
        conflict('TARGET_CHANGED', ref)
    if step['status'] not in ('PLANNED', 'IN_PROGRESS', 'PAUSED'):
        conflict('INVALID_TRANSITION', ref)
    if step['definition_version'] != command['expected_definition_version']:
        conflict('STEP_DEFINITION_CHANGED', ref)
    if head['goal_version'] != command['expected_goal_version']:
        conflict('GOAL_CHANGED', ref)
    document = connection.execute(
        'SELECT d.*,r.id AS revision_id FROM requirement_documents d JOIN revisions r '
        'ON r.document_id=d.id AND r.source_content_version=d.content_version WHERE d.id=? '
        "AND d.requirement_id=? AND d.document_type='CURRENT' AND d.archived_at IS NULL",
        (root['assistant_document_id'], root['id']),
    ).fetchone()
    if document is None:
        raise Rejected('NOT_FOUND')
    if document['content_version'] != command['expected_content_version']:
        raise Rejected('CONTENT_VERSION_CONFLICT')
    next_step = command['next_step_ref']
    if next_step is not None and next_step not in steps:
        conflict('TARGET_CHANGED', next_step)
    results = {
        row['result_ref']: dict(row)
        for row in connection.execute(
            'SELECT * FROM formation_results WHERE document_id=? AND step_ref=?',
            (root['assistant_document_id'], ref),
        )
    }
    for action in command['result_dispositions']:
        if action['result_ref'] not in results:
            conflict('TARGET_CHANGED', ref)
        verify_source_refs(
            connection, root['id'], action['source_refs'], resources=resources.collaboration
        )
        for artifact_ref in action['artifact_refs']:
            actual = connection.execute(
                'SELECT 1 FROM formation_artifact_results ar JOIN formation_artifacts a '
                'ON a.document_id=ar.document_id AND a.artifact_ref=ar.artifact_ref '
                'WHERE ar.document_id=? AND ar.result_ref=? AND ar.artifact_ref=? AND a.step_ref=?',
                (root['assistant_document_id'], action['result_ref'], artifact_ref, ref),
            ).fetchone()
            if actual is None:
                raise Rejected('SOURCE_INVALID')
    changes = remaining_changes(steps, branches, issues, command)
    keys = [('STEP_COMPLETED', ref), *((event, action['ref']) for _, event, action in changes)]
    new_head, new_steps, new_branches, new_issues = deepcopy((head, steps, branches, issues))
    if next_step is not None:
        new_head['current_step_ref'], new_head['active_branch_ref'] = next_step, None
        if (head['current_step_ref'], head['active_branch_ref']) != (next_step, None):
            keys.append(('DISCUSSION_STEP_SELECTED', next_step))
    elif head['current_step_ref'] == ref:
        new_head['current_step_ref'] = new_head['active_branch_ref'] = None
    ids = allocate_event_ids(connection, tuple(keys))
    completion_id = ids[('STEP_COMPLETED', ref)]
    new_steps[ref]['status'] = 'COMPLETED'
    new_steps[ref]['closure_event_id'] = completion_id
    for kind, event, action in changes:
        row = (new_issues if kind == 'ISSUE' else new_branches)[action['ref']]
        if action['disposition'] == 'TRANSFER':
            row['step_ref' if kind == 'ISSUE' else 'return_step_ref'] = action['to_step_ref']
            if (
                kind == 'BRANCH'
                and new_head['active_branch_ref'] == action['ref']
                and new_head['current_step_ref'] != action['to_step_ref']
            ):
                new_head['active_branch_ref'] = None
        else:
            row['disposition' if kind == 'ISSUE' else 'status'] = action['disposition']
            row['disposition_event_id'] = ids[(event, action['ref'])]
            if kind == 'ISSUE':
                row['disposition_reason'] = action['reason']
            else:
                row['state_event_id'] = ids[(event, action['ref'])]
                if new_head['active_branch_ref'] == action['ref']:
                    new_head['active_branch_ref'] = None
    validate_graph(
        new_steps,
        new_branches,
        new_issues,
        current_step_ref=new_head['current_step_ref'],
        active_branch_ref=new_head['active_branch_ref'],
        dependencies=edges['DEPENDENCY'],
        replacements=edges['REPLACES'],
    )
    text = '结束步骤：' + step['title']
    if next_step is not None:
        text += '；继续讨论：' + steps[next_step]['title']
    message_id = assistant_id
    if transaction is None:
        message_id = entity_id(connection, EntityKind.MESSAGE)
        MessageRepository(connection).create_user_text(
            message_id,
            root['id'],
            None,
            text,
            key,
            at,
            document_id=root['assistant_document_id'],
            topic_refs=(),
            document_ids=(root['assistant_document_id'],),
        )
    current_blocks = None
    try:
        current_blocks = validate_snapshot(
            document['markdown_content'],
            strict_json_object(document['block_state_json']),
            DocumentSources(
                connection, root['id'], resources, document_id=root['assistant_document_id']
            ),
        ).by_id
    except DocumentInvalid:
        # Missing/unverifiable evidence never fabricates LANDED or gates a user-owned ending.
        current_blocks = None
    facts = [
        RouteFact(
            'STEP',
            ref,
            scalar_snapshot('STEP', step),
            scalar_snapshot('STEP', new_steps[ref]),
            ('STEP_COMPLETED', ref),
        )
    ]
    reasons = {}
    for kind, event, action in changes:
        original = (issues if kind == 'ISSUE' else branches)[action['ref']]
        changed = (new_issues if kind == 'ISSUE' else new_branches)[action['ref']]
        facts.append(
            RouteFact(
                kind,
                action['ref'],
                scalar_snapshot(kind, original),
                scalar_snapshot(kind, changed),
                (event, action['ref']),
            )
        )
        reasons[(event, action['ref'])] = action['reason'] or text
    before_basis = (
        version_basis(root, head, document) if transaction is None else transaction.before
    )
    after_basis = {
        **before_basis,
        'discussion_version': increment(root['discussion_version']),
        'formation_version': increment(head['version']),
    }
    with source_reader(connection, resources) as sources:
        plan = ClosureBuilder(
            connection,
            root=root,
            step=step,
            document=document,
            command=command,
            event_id=completion_id,
            message_id=message_id,
            sources=sources,
            current_blocks=current_blocks,
        ).prepare()
        views = write_headers(
            connection,
            root=root,
            command=command,
            event_ids=ids,
            facts=facts,
            extra_counts={},
            message_id=message_id,
            key=key,
            at=at,
            reason=text,
            version_before=before_basis,
            version_after=after_basis,
            head_before=head,
            head_after=new_head,
            closures={('STEP_COMPLETED', ref): plan.head},
            reasons=reasons,
            actor='AI' if transaction else 'USER',
            source_run_id=run_id,
            sources={key: [source] for key in ids} if transaction else None,
        )
        write_closure(connection, root['assistant_document_id'], plan)
        repository.save_state(
            root['assistant_document_id'],
            (head, steps, branches, issues),
            StateMutation('STEP_COMPLETED', new_head, new_steps, new_branches, new_issues, True),
        )
        if transaction is None:
            updated = RequirementRepository(connection).advance_discussion(root, at)
        else:
            transaction.touch(at)
            updated = transaction.root()
        references = [(completion_id, 'STEP', ref)]
        for selected in (head['current_step_ref'], new_head['current_step_ref']):
            if selected is not None:
                references.append((completion_id, 'STEP', selected))
        if ('DISCUSSION_STEP_SELECTED', next_step) in ids:
            references.append((ids[('DISCUSSION_STEP_SELECTED', next_step)], 'STEP', next_step))
        write_facts(
            connection, root['assistant_document_id'], ids, views, facts, references=references
        )
    current = repository.head(root['assistant_document_id'], required=True)
    if version_basis(updated, current, document) != after_basis:
        raise ValueError('Completed step versions differ from their immutable batch')
    return receipt(updated, current, document, message_id, tuple(ids.values()), changed=True)
