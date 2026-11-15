"""Public projections of the fixed Testing task and its own evidence."""

from backend.app.code_tasks.coding_model_ledger import budget_facts
from backend.app.code_tasks.configuration_identities import require_schema
from backend.app.code_tasks.costs import format_balance, format_money, parse_balance, parse_money
from backend.app.code_tasks.repository_operations import _time
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.shared.command_execution import operation_time
from backend.app.shared.http_projection import exact
from backend.app.shared.pagination import PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import (
    strict_enum,
    strict_integer,
    strict_json_loads,
    strict_json_object,
)

from .assets import NOT_FOUND, _read
from .plan_content import parse_fixed_basis
from .tasks import (
    PHASES,
    PURPOSES,
    STATUSES,
    TARGETS,
    TASK_TABLE_FIELDS,
    materials_for,
    optional_id,
    read_task_row,
)

SUMMARY = (
    'id',
    'requirement_id',
    'document_id',
    'target_kind',
    'candidate_id',
    'snapshot_id',
    'purpose',
    'status',
    'phase',
    'created_at',
    'report_id',
)
VIEW_FIELDS = (
    *TASK_TABLE_FIELDS,
    'available_actions',
    'runtime',
    'budget',
    'termination_operation_id',
    'draft_plan_result',
)
ACTIONS = (
    'DRAFT_PLAN',
    'ATTACH_ASSETS',
    'RUN_TEST',
    'INCREASE_TEST_BUDGET',
    'RESUME',
    'RECONCILE',
    'TERMINATE',
)
REASONS = (
    'TASK_STATE',
    'ASSET_NOT_READY',
    'MODEL_NOT_READY',
    'EXECUTION_NOT_READY',
    'BUDGET_NOT_READY',
    'OPERATION_UNKNOWN',
    'AUTHORIZATION_NOT_READY',
    'REFERENCE_SET_NOT_REGISTERED',
)
RUNTIME_FIELDS = (
    'environment_status',
    'activity_status',
    'stop_status',
    'cleanup_status',
    'reason_codes',
    'active_process_count',
    'observed_at',
)
BUDGET_FIELDS = (
    'budget_limit_cny',
    'settled_cny',
    'reserved_cny',
    'available_cny',
    'model_request_count',
    'request_limit',
)


def project_task_summary(value):
    row = exact(value, SUMMARY)
    for field in ('id', 'requirement_id', 'document_id'):
        strict_integer(row[field], field)
    for field in ('candidate_id', 'snapshot_id', 'report_id'):
        optional_id(row[field], field)
    strict_enum(row['target_kind'], 'target_kind', TARGETS)
    strict_enum(row['purpose'], 'purpose', PURPOSES)
    strict_enum(row['status'], 'status', STATUSES)
    strict_enum(row['phase'], 'phase', PHASES)
    _time(row['created_at'], nullable=False)
    if (
        (row['candidate_id'] is not None) != (row['target_kind'] == 'CANDIDATE')
        or (row['snapshot_id'] is not None) != (row['target_kind'] == 'SNAPSHOT')
        or (row['status'] == 'COMPLETED') != (row['report_id'] is not None)
    ):
        raise ValueError('Original Testing task summary differs')
    return row


def _validate_runtime(value):
    data = exact(value, RUNTIME_FIELDS)
    strict_enum(
        data['environment_status'],
        'environment_status',
        (
            'NOT_PREPARED',
            'PREPARING',
            'VERIFIED',
            'UNAVAILABLE',
            'UNKNOWN',
        ),
    )
    strict_enum(
        data['activity_status'],
        'activity_status',
        ('NOT_STARTED', 'ACTIVE', 'QUIESCENT', 'UNKNOWN'),
    )
    strict_enum(
        data['stop_status'],
        'stop_status',
        (
            'NONE',
            'REQUESTED',
            'ABORTING',
            'TERMINATING',
            'VERIFYING',
            'VERIFIED',
            'UNKNOWN',
        ),
    )
    strict_enum(
        data['cleanup_status'],
        'cleanup_status',
        ('NOT_STARTED', 'CLEANING', 'VERIFIED', 'FAILED', 'UNKNOWN'),
    )
    _time(data['observed_at'])
    if data['active_process_count'] is not None:
        strict_integer(data['active_process_count'], 'active_process_count', minimum=0)
        if data['observed_at'] is None:
            raise ValueError('Testing runtime has no original observation')
    reasons = data['reason_codes']
    if (
        type(reasons) is not list
        or any(type(item) is not str or not item for item in reasons)
        or reasons != sorted(set(reasons))
    ):
        raise ValueError('Original Testing observation reasons differ')


def _validate_budget(value, limit):
    row = exact(value, BUDGET_FIELDS)
    amounts = [parse_money(row[field], field) for field in BUDGET_FIELDS[:3]]
    if (
        any(
            format_money(amount) != row[field]
            for field, amount in zip(BUDGET_FIELDS[:3], amounts, strict=True)
        )
        or row['budget_limit_cny'] != limit
        or parse_balance(row['available_cny']) != amounts[0] - amounts[1] - amounts[2]
    ):
        raise ValueError('Original Testing budget differs')
    strict_integer(row['model_request_count'], 'model_request_count', minimum=0)
    strict_integer(row['request_limit'], 'request_limit', minimum=0)


def project_task_view(value, identity):
    row = exact(value, VIEW_FIELDS)
    project_task_summary({key: row[key] for key in SUMMARY})
    if row['id'] != identity:
        raise ValueError('Original Testing task identity differs')
    kind = strict_enum(row['kind'], 'kind', ('PRODUCT', 'PACK_VALIDATION'))
    fixed = parse_fixed_basis(row)
    if any(row[key] != value for key, value in fixed.items()):
        raise ValueError('Original Testing design basis differs')
    for field in ('profile_version_id', 'authorization_id', 'state_version', 'control_generation'):
        strict_integer(row[field], field)
    for field in (
        'plan_version_id',
        'test_pack_version_id',
        'previous_testing_task_id',
        'validation_id',
        'active_operation_id',
        'draft_plan_operation_id',
        'current_verification_id',
        'termination_operation_id',
    ):
        optional_id(row[field], field)
    if (
        (kind == 'PACK_VALIDATION') != (row['purpose'] == 'PACK_VALIDATION')
        or (kind == 'PACK_VALIDATION') != (row['validation_id'] is not None)
        or (row['plan_version_id'] is None) != (row['test_pack_version_id'] is None)
        or row['previous_testing_task_id'] == identity
    ):
        raise ValueError('Original Testing references differ')
    for field in ('stop_requested_at', 'stopped_at', 'ended_at'):
        _time(row[field])
    if any(
        row[field] is not None and row[field] < row['created_at']
        for field in ('stop_requested_at', 'stopped_at', 'ended_at')
    ):
        raise ValueError('Original Testing chronology differs')
    if row['status'] == 'TERMINATED' and (
        row['stop_requested_at'] is None
        or row['stopped_at'] is None
        or row['ended_at'] is None
        or not row['stop_requested_at'] <= row['stopped_at'] <= row['ended_at']
    ):
        raise ValueError('Original Testing termination is unverified')
    if row['status'] in ('COMPLETED', 'TERMINATED') and row['phase'] != 'FINISHED':
        raise ValueError('Original Testing terminal phase differs')
    actions = row['available_actions']
    if type(actions) is not list or len(actions) != len(ACTIONS):
        raise ValueError('Original Testing action list differs')
    for action, expected in zip(actions, ACTIONS, strict=True):
        exact(action, ('action', 'enabled', 'reason_code'))
        if (
            action['action'] != expected
            or type(action['enabled']) is not bool
            or (
                action['reason_code'] is None
                if action['enabled']
                else action['reason_code'] in REASONS
            )
            is False
        ):
            raise ValueError('Original Testing action is invalid')
    draft = row['draft_plan_result']
    if draft is not None:
        exact(draft, ('operation_id', 'plan_id', 'plan_version_id'))
        for field in draft:
            strict_integer(draft[field], field)
        if draft['operation_id'] != row['draft_plan_operation_id']:
            raise ValueError('Original Testing draft operation differs')
    _validate_runtime(row['runtime'])
    _validate_budget(row['budget'], row['budget_limit_cny'])
    return row


def _runtime(connection, task, *, stop_unknown):
    rows = connection.execute(
        """SELECT * FROM code_runtime_observations
           WHERE id IN (SELECT MAX(id) FROM code_runtime_observations
                        WHERE testing_task_id=? AND task_id IS NULL AND control_generation=?
                        GROUP BY kind)
           ORDER BY observed_at,id""",
        (task['id'], task['control_generation']),
    ).fetchall()
    latest = {row['kind']: row for row in rows}
    prepare, quiet, stop, cleanup = (
        latest.get(kind) for kind in ('PREPARE', 'QUIESCE', 'STOP', 'CLEANUP')
    )
    owned_activity = connection.execute(
        """SELECT status,started_at FROM code_commands WHERE testing_task_id=? AND task_id IS NULL
           AND status IN ('RUNNING','UNKNOWN') AND ended_at IS NULL ORDER BY id DESC LIMIT 1""",
        (task['id'],),
    ).fetchone()
    activity = 'NOT_STARTED'
    if owned_activity is not None:
        activity = 'ACTIVE' if owned_activity['status'] == 'RUNNING' else 'UNKNOWN'
    elif quiet is not None:
        activity = 'QUIESCENT' if quiet['result'] == 'VERIFIED' else 'UNKNOWN'
    elif stop is not None and prepare is not None:
        activity = 'QUIESCENT' if stop['result'] == 'VERIFIED' else 'UNKNOWN'
    elif prepare is not None:
        activity = 'UNKNOWN'
    reasons = {
        reason for row in rows for reason in strict_json_loads(row['reason_codes'], 'reason_codes')
    }
    return {
        'environment_status': prepare['result']
        if prepare is not None
        else (
            'PREPARING'
            if task['status'] == 'RUNNING' and task['phase'] == 'PREPARE'
            else 'NOT_PREPARED'
        ),
        'activity_status': activity,
        'stop_status': ('VERIFIED' if stop['result'] == 'VERIFIED' else 'UNKNOWN')
        if stop is not None
        else (
            'UNKNOWN' if stop_unknown else ('REQUESTED' if task['status'] == 'STOPPING' else 'NONE')
        ),
        'cleanup_status': (
            {'VERIFIED': 'VERIFIED', 'UNAVAILABLE': 'FAILED', 'UNKNOWN': 'UNKNOWN'}[
                cleanup['result']
            ]
            if cleanup is not None
            else 'NOT_STARTED'
        ),
        'reason_codes': sorted(reasons),
        'active_process_count': rows[-1]['active_process_count'] if rows else None,
        'observed_at': rows[-1]['observed_at'] if rows else None,
    }


def _actions(task, authorized, *, run_reason, can_resume, can_reconcile, draft_reason):
    status = task['status']
    terminal = status in ('COMPLETED', 'TERMINATED')
    controlled = status in ('DRAFT', 'READY', 'WAITING') and task['current_verification_id'] is None
    no_operation = task['active_operation_id'] is None
    blocked_run = 'ASSET_NOT_READY' if task['test_pack_version_id'] is None else run_reason
    product = task['kind'] == 'PRODUCT'
    reasons = {
        'DRAFT_PLAN': (
            draft_reason
            if product and status == 'DRAFT' and no_operation and task['plan_version_id'] is None
            else 'TASK_STATE'
        ),
        'ATTACH_ASSETS': None if product and controlled and no_operation else 'TASK_STATE',
        'RUN_TEST': (
            blocked_run
            if status == 'READY' and no_operation
            else 'ASSET_NOT_READY'
            if status == 'DRAFT' and no_operation
            else 'TASK_STATE'
        ),
        'INCREASE_TEST_BUDGET': None
        if product and not terminal and status != 'STOPPING'
        else 'TASK_STATE',
        'RESUME': None
        if can_resume
        else 'OPERATION_UNKNOWN'
        if status == 'WAITING'
        else 'TASK_STATE',
        'RECONCILE': None if can_reconcile else 'OPERATION_UNKNOWN',
        'TERMINATE': ('TASK_STATE' if terminal or status == 'STOPPING' else None),
    }
    if not authorized:
        for action in ('DRAFT_PLAN', 'ATTACH_ASSETS', 'RUN_TEST'):
            if reasons[action] != 'TASK_STATE':
                reasons[action] = 'AUTHORIZATION_NOT_READY'
    return [
        {'action': action, 'enabled': reasons[action] is None, 'reason_code': reasons[action]}
        for action in ACTIONS
    ]


def _draft(connection, task):
    original = task['draft_plan_operation_id']
    if original is None:
        return None
    row = connection.execute(
        """SELECT o.status,s.result_ref FROM code_operations o
           JOIN code_operation_steps s ON s.operation_id=o.id AND s.step_type='SAVE_DRAFT'
           WHERE o.id=? AND o.testing_task_id=? AND o.task_id IS NULL AND o.operation_type='DRAFT_PLAN'""",
        (original, task['id']),
    ).fetchone()
    if row is None:
        raise StorageUnavailable('Original Testing draft operation is missing')
    if row['status'] != 'SUCCEEDED':
        return None
    refs = exact(strict_json_object(row['result_ref']), ('plan_id', 'plan_version_id'))
    return {'operation_id': original, **refs}


def task_view(
    connection,
    row,
    *,
    run_reason='EXECUTION_NOT_READY',
    can_resume=False,
    draft_reason='MODEL_NOT_READY',
):
    task = dict(row)
    task['material_refs'] = materials_for(connection, task['id'])
    source = connection.execute(
        """SELECT p.limits,a.status,a.testing_task_id,a.validation_id FROM testing_profile_versions p
           JOIN testing_authorizations a ON a.profile_version_id=p.id
           WHERE p.id=? AND a.id=?""",
        (task['profile_version_id'], task['authorization_id']),
    ).fetchone()
    if source is None or (source['testing_task_id'], source['validation_id']) != (
        (task['id'], None) if task['kind'] == 'PRODUCT' else (None, task['validation_id'])
    ):
        raise StorageUnavailable('Original Testing authorization ownership differs')
    limit = parse_money(task['budget_limit_cny'])
    facts = budget_facts(connection, task['id'], limit, owner='TESTING')
    stop = connection.execute(
        """SELECT id,status FROM code_operations WHERE testing_task_id=? AND task_id IS NULL
           AND operation_type='TERMINATE'""",
        (task['id'],),
    ).fetchall()
    if len(stop) > 1:
        raise StorageUnavailable('Original Testing stop is not unique')
    can_reconcile = (
        connection.execute(
            """SELECT 1 FROM code_operations WHERE testing_task_id=? AND task_id IS NULL
           AND resource_kind='TESTING_TASK' AND resource_id=testing_task_id
           AND (operation_type NOT IN ('RESUME','RECONCILE')
                OR status IN ('SUCCEEDED','FAILED','CANCELLED'))""",
            (task['id'],),
        ).fetchone()
        is not None
    )
    projected = {
        **task,
        'available_actions': _actions(
            task,
            source['status'] == 'EFFECTIVE',
            run_reason=run_reason,
            draft_reason=draft_reason,
            can_resume=can_resume,
            can_reconcile=can_reconcile,
        ),
        'runtime': _runtime(
            connection, task, stop_unknown=bool(stop and stop[0]['status'] == 'UNKNOWN')
        ),
        'budget': {
            'budget_limit_cny': task['budget_limit_cny'],
            'settled_cny': format_money(facts.settled),
            'reserved_cny': format_money(facts.reserved),
            'available_cny': format_balance(facts.available),
            'model_request_count': facts.requests,
            'request_limit': strict_json_object(source['limits'])['max_model_requests'],
        },
        'termination_operation_id': stop[0]['id'] if stop else None,
        'draft_plan_result': _draft(connection, task),
    }
    return project_task_view(projected, task['id'])


def read_task(runtime, request, *, runtime_resources=None):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        row = read_task_row(connection, request.identity)
        if row is None:
            return NOT_FOUND.result
        try:
            reason = 'EXECUTION_NOT_READY'
            if row['status'] == 'READY' and runtime_resources is not None:
                from .task_run import run_reason

                reason = run_reason(connection, runtime.catalog, row, runtime_resources)
            from .planning import draft_inputs
            from .task_recovery import resume_available

            _, draft_reason = draft_inputs(connection, runtime.catalog, row, operation_time(None))
            return _read(
                task_view(
                    connection,
                    row,
                    run_reason=reason,
                    draft_reason='ASSET_NOT_READY'
                    if draft_reason == 'CONTENT_NOT_READY'
                    else draft_reason,
                    can_resume=resume_available(connection, row, runtime_resources),
                )
            )
        except (TypeError, ValueError, KeyError) as error:
            raise StorageUnavailable('Original Testing task facts are unreadable') from error


def list_tasks(runtime, request):
    require_schema(runtime)
    filters = tuple(request.filters.items())
    where = (' WHERE ' + ' AND '.join(f'{column}=?' for column, _ in filters)) if filters else ''
    args = tuple(value for _, value in filters)
    with runtime.database.transaction() as connection:
        total = connection.execute('SELECT count(*) FROM testing_tasks' + where, args).fetchone()[0]
        rows = connection.execute(
            'SELECT '
            + ','.join(SUMMARY)
            + ' FROM testing_tasks'
            + where
            + ' ORDER BY id LIMIT ? OFFSET ?',
            (*args, PAGE_SIZE, page_offset(request.page)),
        )
        return _read(
            {
                **page_metadata(request.page, total),
                'items': [project_task_summary(dict(row)) for row in rows],
            }
        )
