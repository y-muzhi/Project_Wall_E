"""Immutable initial TaskView for C32. Subsequent reads use current facts."""

from backend.app.infrastructure.git_ref_protocol import branch_ref
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import strict_integer

from .costs import format_money, parse_money
from .repository_operations import _time

TASK_IDS = (
    'id',
    'document_id',
    'requirement_id',
    'design_revision_id',
    'repository_id',
    'base_snapshot_id',
    'execution_profile_version_id',
    'authorization_id',
)
ROW_FIELDS = (
    *TASK_IDS,
    'status',
    'phase',
    'state_version',
    'created_at',
    'updated_at',
    'current_candidate_id',
    'target_branch',
    'workspace_id',
    'active_session_id',
    'control_generation',
    'resume_phase',
    'started_at',
    'ended_at',
    'stop_requested_at',
    'stopped_at',
    'last_observed_at',
)
TASK_ACTIONS = (
    'START',
    'RESUME',
    'ANSWER_QUESTION',
    'DECIDE_PERMISSION',
    'APPLY_CONFIGURATION',
    'INCREASE_BUDGET',
    'PREPARE_HANDOFF',
    'LINK_HANDOFF',
    'REGISTER_DEFECT',
    'VERIFY_CANDIDATE',
    'CAPTURE_AND_CHECK',
    'REPAIR',
    'HANDOFF_ROLE',
    'PREPARE_DELIVERY',
    'ACCEPT',
    'SUBMIT_FOR_TESTING',
    'LINK_TEST_REPORT',
    'TERMINATE',
    'RECONCILE',
)
INITIAL_ENABLED = {'APPLY_CONFIGURATION', 'INCREASE_BUDGET', 'TERMINATE', 'RECONCILE'}


def initial_task_view(row, materials, differences, ready):
    limit = row['budget_limit_cny']
    actions = []
    for action in TASK_ACTIONS:
        if action == 'START':
            reason = None if ready else 'CONFIG_NOT_READY'
        elif action == 'LINK_HANDOFF':
            reason = 'PRECONDITION_FAILED'
        else:
            reason = None if action in INITIAL_ENABLED else 'INVALID_STATE'
        actions.append(
            {'action': action, 'enabled': reason is None, 'reason_code': reason, 'related_id': None}
        )
    return {
        **{field: row[field] for field in ROW_FIELDS},
        'material_refs': list(materials),
        'current_refs': dict.fromkeys(
            ('verification_id', 'test_report_id', 'delivery_plan_id', 'delivery_id')
        ),
        'configuration_application': None,
        'runtime': {
            'isolation_mode': 'WINDOWS_LPAC',
            'environment_status': 'NOT_PREPARED',
            'activity_status': 'NOT_STARTED',
            'stop_status': 'NONE',
            'cleanup_status': 'NOT_STARTED',
            'reason_codes': [],
            'active_process_count': None,
            'observed_at': None,
        },
        'waiting_items': [],
        'active_operations': [],
        'budget': {
            'limit_cny': limit,
            'settled_cny': '0.000000',
            'reserved_cny': '0.000000',
            'available_cny': limit,
            'unresolved_call_count': 0,
        },
        'current_basis_difference': differences,
        'available_actions': actions,
        'termination_operation_id': None,
        'verification_purposes': [
            {'action': action, 'purpose': 'HANDOFF', 'enabled': False, 'reason_code': 'TASK_STATE'}
            for action in ('CAPTURE_AND_CHECK', 'VERIFY_CANDIDATE')
        ],
    }


def _validate_fixed_view(data, document_id):
    for field in TASK_IDS:
        strict_integer(data[field], field)
    if data['document_id'] != document_id:
        raise ValueError('Original task document differs')
    _time(data['created_at'], nullable=False)
    _time(data['updated_at'], nullable=False)
    if data['updated_at'] < data['created_at']:
        raise ValueError('Task update precedes creation')
    branch_ref(data['target_branch'])
    limit = data['budget']['limit_cny']
    amount = parse_money(limit, 'budget_limit_cny')
    if limit != format_money(amount):
        raise ValueError('Original task budget is not canonical')
    materials = data['material_refs']
    differences = data['current_basis_difference']
    if type(materials) is not list or type(differences) is not list:
        raise ValueError('Original fixed design scope differs')
    fixed = {document_id: data['design_revision_id']}
    for item in materials:
        exact(item, ('document_id', 'revision_id'))
        doc = strict_integer(item['document_id'], 'document_id')
        if doc in fixed:
            raise ValueError('Original fixed material is duplicated')
        fixed[doc] = strict_integer(item['revision_id'], 'revision_id')
    seen = set()
    for item in differences:
        exact(item, ('document_id', 'fixed_revision_id', 'current_revision_id'))
        doc = strict_integer(item['document_id'], 'document_id')
        basis = strict_integer(item['fixed_revision_id'], 'fixed_revision_id')
        current = strict_integer(item['current_revision_id'], 'current_revision_id')
        if doc in seen or fixed.get(doc) != basis or current == basis:
            raise ValueError('Original design difference crosses its fixed scope')
        seen.add(doc)
    return limit, materials, differences


def validate_initial_task(data, document_id, *, require_new=True):
    version = strict_integer(data['state_version'], 'state_version')
    if (
        data['status'] != 'PENDING'
        or data['phase'] != 'PREPARING'
        or (require_new and version != 1)
        or strict_integer(data['control_generation'], 'control_generation') != 1
        or (version == 1 and data['created_at'] != data['updated_at'])
        or any(
            data[field] is not None
            for field in ROW_FIELDS
            if field
            not in (
                *TASK_IDS,
                'status',
                'phase',
                'state_version',
                'control_generation',
                'created_at',
                'updated_at',
                'target_branch',
            )
        )
    ):
        raise ValueError('Original task creation state differs')
    limit, materials, differences = _validate_fixed_view(data, document_id)
    ready = data['available_actions'][0]['enabled']
    if type(ready) is not bool:
        raise ValueError('Original START availability is not boolean')
    expected = initial_task_view({**data, 'budget_limit_cny': limit}, materials, differences, ready)
    if data != expected:
        raise ValueError('Original creation projection differs')


def stopping_task_view(row, materials, differences, operation_id, operation_status):
    terminal = row['status'] == 'TERMINATED'
    data = initial_task_view(row, materials, differences, False)
    data['termination_operation_id'] = operation_id
    data['available_actions'] = [
        {
            'action': action,
            'enabled': action == 'RECONCILE' or (action == 'TERMINATE' and not terminal),
            'reason_code': (
                None
                if action == 'RECONCILE' or (action == 'TERMINATE' and not terminal)
                else 'TASK_ENDED'
                if terminal
                else 'INVALID_STATE'
            ),
            'related_id': operation_id if action == 'TERMINATE' else None,
        }
        for action in TASK_ACTIONS
    ]
    data['runtime'].update(
        stop_status='VERIFIED' if terminal else 'REQUESTED',
        cleanup_status='VERIFIED' if terminal else 'NOT_STARTED',
        active_process_count=0 if terminal else None,
        observed_at=row['last_observed_at'],
    )
    if not terminal:
        data['active_operations'] = [
            {'id': operation_id, 'operation_type': 'TERMINATE', 'status': operation_status}
        ]
    return data


def validate_stopped_task(data, task_id, *, terminal):
    if terminal and data['workspace_id'] is not None:
        from .task_stop_view import validate_owned_stop_view

        if data['status'] != 'TERMINATED':
            raise ValueError('Original completed stop is not terminal')
        validate_owned_stop_view(data, task_id)
        return
    if strict_integer(data['id'], 'id') != task_id:
        raise ValueError('Original stop task identity differs')
    limit, materials, differences = _validate_fixed_view(data, data['document_id'])
    operation_id = strict_integer(data['termination_operation_id'], 'termination_operation_id')
    if (
        data['status'] != ('TERMINATED' if terminal else 'STOPPING')
        or data['phase'] != ('FINISHED' if terminal else 'PREPARING')
        or strict_integer(data['state_version'], 'state_version') < (3 if terminal else 2)
        or strict_integer(data['control_generation'], 'control_generation') != 2
        or any(
            data[field] is not None
            for field in (
                'current_candidate_id',
                'workspace_id',
                'active_session_id',
                'resume_phase',
                'started_at',
            )
        )
    ):
        raise ValueError('Original empty-scope task state differs')
    requested = data['stop_requested_at']
    _time(requested, nullable=False)
    if requested < data['created_at'] or requested > data['updated_at']:
        raise ValueError('Invalid original stop instant')
    if terminal:
        ended = data['ended_at']
        _time(ended, nullable=False)
        if (
            ended < requested
            or data['stopped_at'] != ended
            or data['last_observed_at'] != ended
            or data['updated_at'] < ended
        ):
            raise ValueError('Terminal task stop chronology differs')
        operation_status = 'SUCCEEDED'
    else:
        if any(data[field] is not None for field in ('stopped_at', 'ended_at', 'last_observed_at')):
            raise ValueError('Stopping task cannot claim completion')
        (operation,) = data['active_operations']
        operation_status = operation['status']
        if operation_status not in ('PENDING', 'RUNNING'):
            raise ValueError('Unexpected empty-scope stop progress')
    expected = stopping_task_view(
        {**data, 'budget_limit_cny': limit}, materials, differences, operation_id, operation_status
    )
    if data != expected:
        raise ValueError('Original stopped task projection differs')
