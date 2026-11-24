"""Native state unit: actual message, state, versions and immutable audit on one connection."""

from backend.app.documents.guards import assert_idle
from backend.app.infrastructure.identifiers import (
    EntityKind,
    entity_id,
    require_write_transaction,
)
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.shared.command_execution import Rejected

from .events import record_state_event
from .native_state import apply_state_command
from .repository import FormationRepository

STATE_ACTIONS = frozenset(
    (
        'START_STEP',
        'PAUSE_STEP',
        'RESUME_STEP',
        'SWITCH_STEP',
        'REOPEN_STEP',
        'ENTER_BRANCH',
        'RETURN_FROM_BRANCH',
        'DISPOSE_BRANCH',
        'RESUME_BRANCH',
        'RESUME_ISSUE',
    )
)

ACTION_LABELS = {
    'START_STEP': '开始步骤',
    'PAUSE_STEP': '暂停步骤',
    'RESUME_STEP': '恢复步骤',
    'SWITCH_STEP': '切换讨论目标',
    'REOPEN_STEP': '重新打开步骤',
    'ENTER_BRANCH': '进入支线',
    'RETURN_FROM_BRANCH': '返回步骤讨论',
    'DISPOSE_BRANCH': '处置支线',
    'RESUME_BRANCH': '继续支线',
    'RESUME_ISSUE': '恢复问题',
}


def action_text(command, steps, branches, issues):
    action = command['action']
    if action == 'SWITCH_STEP' and command['step_ref'] is None:
        return '讨论整份文档'
    if action in ('START_STEP', 'PAUSE_STEP', 'RESUME_STEP', 'SWITCH_STEP', 'REOPEN_STEP'):
        return ACTION_LABELS[action] + '：' + steps[command['step_ref']]['title']
    if action == 'RESUME_ISSUE':
        return '恢复问题：' + issues[command['issue_ref']]['description']
    branch = branches[command['branch_ref']]
    if action == 'DISPOSE_BRANCH':
        label = '暂缓支线' if command['disposition'] == 'DEFERRED' else '放弃支线'
        return label + '：' + branch['question'] + '。原因：' + command['reason']
    return ACTION_LABELS[action] + '：' + branch['question']


def version_basis(root, head, document):
    return {
        'discussion_version': root['discussion_version'],
        'formation_version': head['version'],
        'goal_version': head['goal_version'],
        'document_revision_id': document['revision_id'],
        'content_version': document['content_version'],
    }


def apply(
    connection,
    root,
    command,
    key,
    at,
    *,
    transaction=None,
    assistant_id=None,
    run_id=None,
    source=None,
):
    """Called inside the existing command executor; this function never commits or claims."""
    require_write_transaction(connection)
    if command['action'] not in STATE_ACTIONS:
        raise ValueError('State handler requires its registered command subset')
    if at < root['updated_at']:
        raise ValueError('Native activity cannot precede the current stored activity')
    if transaction is None:
        assert_idle(
            connection,
            root,
            remaining_conflicts=frozenset({'MANUAL_DRAFT', 'GUIDE_RUN', 'SUGGESTION_BATCH'}),
        )
    document_id = root['assistant_document_id']
    document = connection.execute(
        'SELECT d.content_version,r.id AS revision_id FROM requirement_documents d JOIN revisions r '
        'ON r.document_id=d.id AND r.source_content_version=d.content_version WHERE d.id=? '
        "AND d.requirement_id=? AND d.document_type='CURRENT' AND d.archived_at IS NULL",
        (document_id, root['id']),
    ).fetchone()
    if document is None:
        raise Rejected('NOT_FOUND')
    repository = FormationRepository(connection)
    head, steps, branches, issues, edges = repository.graph(document_id)
    before = (head, steps, branches, issues)
    allocated_event_id = None

    def event_identity():
        nonlocal allocated_event_id
        if allocated_event_id is None:
            allocated_event_id = entity_id(connection, EntityKind.DOCUMENT_AUDIT)
        return allocated_event_id

    mutation = apply_state_command(
        *before,
        command,
        event_identity,
        dependencies=edges['DEPENDENCY'],
        replacements=edges['REPLACES'],
    )
    if not mutation.changed:
        return receipt(root, head, document, None, (), changed=False)
    event_id = event_identity()
    message_id = assistant_id
    if transaction is None:
        message_id = entity_id(connection, EntityKind.MESSAGE)
        MessageRepository(connection).create_user_text(
            message_id,
            root['id'],
            None,
            action_text(command, steps, branches, issues),
            key,
            at,
            document_id=document_id,
            topic_refs=(),
            document_ids=(document_id,),
        )
    repository.save_state(document_id, before, mutation)
    if transaction is None:
        updated = RequirementRepository(connection).advance_discussion(root, at)
    else:
        transaction.touch(at)
        updated = transaction.root()
    current_head = repository.head(document_id, required=True)
    record_state_event(
        connection,
        event_id=event_id,
        root=root,
        before=before,
        mutation=mutation,
        message_id=message_id,
        key=key,
        at=at,
        reason=command.get('reason', ACTION_LABELS[command['action']]),
        version_before=version_basis(root, head, document)
        if transaction is None
        else transaction.before,
        source_run_id=run_id,
        source=source,
        version_after=version_basis(updated, current_head, document),
        command=command,
    )
    return receipt(updated, current_head, document, message_id, (event_id,), changed=True)


def receipt(root, head, document, message_id, event_ids, *, changed):
    return {
        'schema': 'formation_program_receipt_v21_1',
        'processing': 'PROGRAM',
        'requirement_id': root['id'],
        'document_id': root['assistant_document_id'],
        'discussion_version': root['discussion_version'],
        'formation_version': head['version'],
        'content_version': document['content_version'],
        'operation': 'NATIVE_FORMATION',
        'result': 'APPLIED' if changed else 'NO_CHANGE',
        'user_message_id': message_id,
        'effects': {
            'content_changed': False,
            'revision_id': None,
            'formation_changed': changed,
            'proposal_disposition': None,
        },
        'event_ids': list(event_ids),
        'reference_map': [],
    }
