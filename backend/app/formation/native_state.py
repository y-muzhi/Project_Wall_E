"""Native lifecycle/focus transitions, evaluated against the complete current graph."""

from copy import deepcopy
from dataclasses import dataclass

from backend.app.shared.command_execution import Rejected
from backend.app.shared.validation import strict_integer

from .graph import validate_graph


def conflict(reason, step_ref=None):
    raise Rejected(
        'STATE_CONFLICT', details={'reason': reason, 'step_ref': step_ref, 'proposal': None}
    )


@dataclass(frozen=True)
class StateMutation:
    action: str
    head: dict
    steps: dict
    branches: dict
    issues: dict
    changed: bool


def apply_state_command(
    head, steps, branches, issues, command, event_id_factory, *, dependencies, replacements
):
    """The caller supplies a memoized transaction allocator; unchanged commands consume no IDs."""

    allocated_event_id = None

    def event_id():
        nonlocal allocated_event_id
        if allocated_event_id is None:
            allocated_event_id = strict_integer(event_id_factory(), 'event_id')
        return allocated_event_id

    before = (head, steps, branches, issues)
    head, steps, branches, issues = deepcopy(before)
    action = command['action']

    def step(ref):
        value = steps.get(ref)
        if value is None:
            conflict('TARGET_CHANGED', ref)
        return value

    def branch(ref):
        value = branches.get(ref)
        if value is None:
            conflict('BRANCH_STATE_CHANGED')
        return value

    def select(ref, branch_ref=None):
        if ref is not None:
            step(ref)
        head['current_step_ref'] = ref
        head['active_branch_ref'] = branch_ref

    transitions = {
        'START_STEP': ('PLANNED', 'IN_PROGRESS', 'STEP_STARTED'),
        'PAUSE_STEP': ('IN_PROGRESS', 'PAUSED', 'STEP_PAUSED'),
        'RESUME_STEP': ('PAUSED', 'IN_PROGRESS', 'STEP_RESUMED'),
        'REOPEN_STEP': ('COMPLETED', 'IN_PROGRESS', 'STEP_REOPENED'),
    }
    if action in transitions:
        ref = command['step_ref']
        current = step(ref)
        required, next_status, event_action = transitions[action]
        if current['status'] != required:
            conflict('INVALID_TRANSITION', ref)
        current['status'] = next_status
        if action == 'REOPEN_STEP':
            current['closure_event_id'] = None
        if action == 'PAUSE_STEP':
            if head['current_step_ref'] == ref:
                select(None)
        else:
            select(ref)
    elif action == 'SWITCH_STEP':
        select(command['step_ref'])
        event_action = 'DISCUSSION_STEP_SELECTED'
    elif action == 'ENTER_BRANCH':
        selected = branch(command['branch_ref'])
        if selected['return_step_ref'] != command['step_ref']:
            conflict('BRANCH_RETURN_MISMATCH', command['step_ref'])
        if selected['status'] != 'OPEN':
            conflict('BRANCH_STATE_CHANGED', command['step_ref'])
        if step(command['step_ref'])['status'] == 'CANCELLED':
            conflict('INVALID_TRANSITION', command['step_ref'])
        select(command['step_ref'], command['branch_ref'])
        event_action = 'BRANCH_ENTERED'
    elif action == 'RETURN_FROM_BRANCH':
        if command['branch_ref'] != head['active_branch_ref']:
            conflict('TARGET_CHANGED')
        branch(command['branch_ref'])
        head['active_branch_ref'] = None
        event_action = 'BRANCH_RETURNED'
    elif action == 'DISPOSE_BRANCH':
        selected = branch(command['branch_ref'])
        if selected['status'] != 'OPEN':
            conflict('INVALID_TRANSITION')
        selected['status'] = command['disposition']
        selected['disposition_event_id'] = event_id()
        selected['state_event_id'] = event_id()
        if head['active_branch_ref'] == command['branch_ref']:
            head['active_branch_ref'] = None
        event_action = 'BRANCH_DISPOSITION_CHANGED'
    elif action == 'RESUME_BRANCH':
        selected = branch(command['branch_ref'])
        ref = command['step_ref']
        if selected['return_step_ref'] != ref:
            conflict('BRANCH_RETURN_MISMATCH', ref)
        if (
            selected['status'] != command['expected_branch_status']
            or selected['state_event_id'] != command['expected_branch_event_id']
        ):
            conflict('BRANCH_STATE_CHANGED', ref)
        if selected['status'] not in ('DEFERRED', 'RESOLVED') or step(ref)['status'] == 'CANCELLED':
            conflict('INVALID_TRANSITION', ref)
        for issue in issues.values():
            if (
                issue['branch_ref'] == command['branch_ref']
                and issue['disposition'] == 'OPEN'
                and issue['step_ref'] != ref
            ):
                conflict('BRANCH_RETURN_MISMATCH', ref)
        event_action = 'BRANCH_RESUMED' if selected['status'] == 'DEFERRED' else 'BRANCH_REOPENED'
        selected['status'] = 'OPEN'
        selected['state_event_id'] = event_id()
        selected['disposition_event_id'] = None
        selected['result_summary'] = None
        selected['result_sources_json'] = '[]'
        if command['enter_after_resume']:
            select(ref, command['branch_ref'])
    elif action == 'RESUME_ISSUE':
        selected = issues.get(command['issue_ref'])
        if selected is None:
            conflict('TARGET_CHANGED')
        if selected['disposition'] not in ('OPEN', 'DEFERRED'):
            conflict('INVALID_TRANSITION', selected['step_ref'])
        if step(selected['step_ref'])['status'] == 'CANCELLED':
            conflict('INVALID_TRANSITION', selected['step_ref'])
        linked = branches.get(selected['branch_ref'])
        if (
            linked is not None
            and linked['status'] == 'OPEN'
            and linked['return_step_ref'] != selected['step_ref']
        ):
            conflict('BRANCH_RETURN_MISMATCH', selected['step_ref'])
        if selected['disposition'] == 'DEFERRED':
            selected['disposition'] = 'OPEN'
            selected['disposition_reason'] = None
            selected['disposition_event_id'] = None
        event_action = 'ISSUE_RESUMED'
    else:
        raise ValueError('Route, closure and proposal commands use their own transaction handlers')
    validate_graph(
        steps,
        branches,
        issues,
        current_step_ref=head['current_step_ref'],
        active_branch_ref=head['active_branch_ref'],
        dependencies=dependencies,
        replacements=replacements,
    )
    return StateMutation(
        event_action,
        head,
        steps,
        branches,
        issues,
        (head, steps, branches, issues) != before,
    )
