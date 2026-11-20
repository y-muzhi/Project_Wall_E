"""Read-only action availability shares the same real occupancy checks as commands."""

from backend.app.documents.guards import inspect_idle
from backend.app.shared.command_execution import Rejected


def work_reason(connection, root):
    try:
        inspect_idle(
            connection,
            root,
            remaining_conflicts=frozenset({'MANUAL_DRAFT', 'GUIDE_RUN', 'SUGGESTION_BATCH'}),
        )
    except Rejected as error:
        return error.code
    return None


def action(name, reason=None):
    return {'action': name, 'available': reason is None, 'reason': reason}


def step_actions(step, busy=None):
    allowed = {
        'START_STEP': step['status'] == 'PLANNED',
        'PAUSE_STEP': step['status'] == 'IN_PROGRESS',
        'RESUME_STEP': step['status'] == 'PAUSED',
        'REOPEN_STEP': step['status'] == 'COMPLETED',
        'COMPLETE_STEP': step['status'] in ('PLANNED', 'IN_PROGRESS', 'PAUSED'),
        'SWITCH_STEP': True,
    }
    return [
        action(name, busy or (None if permitted else 'INVALID_TRANSITION'))
        for name, permitted in allowed.items()
    ]


def branch_actions(connection, document_id, branch, head, busy=None):
    owner = connection.execute(
        'SELECT status FROM formation_steps WHERE document_id=? AND step_ref=?',
        (document_id, branch['return_step_ref']),
    ).fetchone()
    viable = owner is not None and owner[0] != 'CANCELLED'
    mismatch = connection.execute(
        "SELECT 1 FROM formation_issues WHERE document_id=? AND branch_ref=? AND disposition='OPEN' AND step_ref<>? LIMIT 1",
        (document_id, branch['branch_ref'], branch['return_step_ref']),
    ).fetchone()
    allowed = {
        'ENTER_BRANCH': viable and branch['status'] == 'OPEN',
        'RETURN_FROM_BRANCH': head['active_branch_ref'] == branch['branch_ref'],
        'DISPOSE_BRANCH': branch['status'] == 'OPEN',
        'RESUME_BRANCH': viable
        and branch['status'] in ('DEFERRED', 'RESOLVED')
        and mismatch is None,
    }
    return [
        action(name, busy or (None if permitted else 'INVALID_TRANSITION'))
        for name, permitted in allowed.items()
    ]


def issue_actions(connection, document_id, issue, busy=None):
    owner = connection.execute(
        'SELECT status FROM formation_steps WHERE document_id=? AND step_ref=?',
        (document_id, issue['step_ref']),
    ).fetchone()
    branch = (
        None
        if issue['branch_ref'] is None
        else connection.execute(
            'SELECT status,return_step_ref FROM formation_branches WHERE document_id=? AND branch_ref=?',
            (document_id, issue['branch_ref']),
        ).fetchone()
    )
    allowed = (
        owner is not None
        and owner[0] != 'CANCELLED'
        and issue['disposition'] in ('OPEN', 'DEFERRED')
    )
    reason = busy or (None if allowed else 'INVALID_TRANSITION')
    if (
        reason is None
        and branch is not None
        and branch['status'] == 'OPEN'
        and branch['return_step_ref'] != issue['step_ref']
    ):
        reason = 'BRANCH_RETURN_MISMATCH'
    return [action('RESUME_ISSUE', reason)]
