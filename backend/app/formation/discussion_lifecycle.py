"""Bind a native lifecycle command to a completed interpretation of this exact owned round."""

from copy import deepcopy
from backend.app.guide.progress_application import ProgressInvalid
from .discussion_route import user_directive
from .model_evidence import ModelEvidence
from .native_contracts import native_command


def prepare(connection, root, context, delta, catalog, transaction):
    source = user_directive(context, delta['directive'])
    frozen = context.canonical['formation']['basis']
    if delta['basis'] != frozen or any(transaction.before[k] != v for k, v in frozen.items()):
        raise ProgressInvalid('The lifecycle command no longer matches its accepted document')
    command = deepcopy(delta['command'])
    evidence = ModelEvidence(connection, root, context, catalog)
    for name, kind in [
        ('step_ref', 'STEP'),
        ('next_step_ref', 'STEP'),
        ('issue_ref', 'ISSUE'),
        ('branch_ref', 'BRANCH'),
    ]:
        if command.get(name) is not None:
            evidence.require_visible(kind, command[name])
    if command['action'] == 'COMPLETE_STEP':
        formation = context.canonical['formation']
        definitions = [
            formation['selected_step'],
            *(
                r.get('definition')
                for r in formation['coverage']['included']
                if r['kind'] == 'STEP'
            ),
        ]
        step = next((s for s in definitions if s and s['step_ref'] == command['step_ref']), None)
        if step is None or command['next_step_ref'] == command['step_ref']:
            raise ProgressInvalid('Completion needs a visible step and a distinct next target')
        command.update(
            expected_definition_version=step['definition_version'],
            expected_goal_version=frozen['goal_version'],
            expected_content_version=frozen['content_version'],
        )
        for row in command['result_dispositions']:
            if row['result_ref'] not in {r['result_ref'] for r in step['expected_results']}:
                raise ProgressInvalid('Completion refers to an unread result')
            row['source_refs'] = evidence.sources(row['source_refs'])
            for ref in row['artifact_refs']:
                evidence.require_visible('ARTIFACT', ref)
        for field, kind in [('issue_dispositions', 'ISSUE'), ('branch_dispositions', 'BRANCH')]:
            for row in command[field]:
                evidence.require_visible(kind, row['ref'])
                if row['to_step_ref']:
                    evidence.require_visible('STEP', row['to_step_ref'])
    return native_command({'type': 'FORMATION', **command}), source


def check_owner(connection, root, run, assistant_id, source):
    active = connection.execute(
        "SELECT 1 FROM guide_runs r JOIN conversation_messages m ON m.guide_run_id=r.id AND m.document_id=r.document_id AND m.requirement_id=r.requirement_id WHERE r.id=? AND r.document_id=? AND r.requirement_id=? AND r.status='RUNNING' AND r.trigger_message_id=? AND m.id=? AND m.role='ASSISTANT'",
        (run['id'], root['assistant_document_id'], root['id'], source['message_id'], assistant_id),
    ).fetchone()
    if not active or (root['active_operation_type'], root['active_operation_id']) != (
        'GUIDE_RUN',
        run['id'],
    ):
        raise ProgressInvalid('The accepted discussion no longer owns the document')


def store(connection, root, prepared, run, assistant_id, catalog, transaction, at):
    from . import completion_commands, state_commands

    command, source = prepared
    check_owner(connection, root, run, assistant_id, source)
    args = dict(transaction=transaction, assistant_id=assistant_id, run_id=run['id'], source=source)
    if command['action'] == 'COMPLETE_STEP':
        result = completion_commands.apply(
            connection, root, command, run['idempotency_key'], at, resources=catalog, **args
        )
    else:
        result = state_commands.apply(connection, root, command, run['idempotency_key'], at, **args)
    return {
        'result': result['result'],
        'formation_changed': result['effects']['formation_changed'],
        'reference_map': [],
        'event_ids': result['event_ids'],
    }
