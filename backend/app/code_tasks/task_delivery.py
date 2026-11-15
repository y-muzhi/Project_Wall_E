"""Original Coding delivery preview and acceptance transactions."""

import re
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from backend.app.infrastructure.command_receipts import Rejection, read_registered_replay
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.infrastructure.windows_private_package import current_operator_sid
from backend.app.shared.command_execution import (
    ConfigurationNotReady,
    execute_idempotent,
    operation_time,
)
from backend.app.shared.time import utc_milliseconds
from backend.app.shared.validation import (
    MAX_SAFE_INTEGER,
    object_fields,
    reject,
    strict_boolean,
    strict_integer,
    strict_json_object,
)

from .authorizations import project_grant
from .configuration_identities import require_schema
from .operation_protocol import operation_steps
from .task_report_link import qualify_report, require_current_report_link
from .task_start import start_conflict

PREPARE = 'PREPARE_DELIVERY'
DELIVER = 'DELIVER'
ACTIVE = ('PENDING', 'RUNNING', 'UNKNOWN')
PREPARE_PATH = '/api/v1/code-tasks/{task_id}/delivery-plans'
ACCEPT_PATH = '/api/v1/code-tasks/{task_id}/accept'
PREVIEW_FIELDS = ('expected_state_version', 'candidate_id', 'test_report_id')
ACCEPT_FIELDS = (
    *PREVIEW_FIELDS,
    'delivery_plan_id',
    'expected_target_commit',
    'repository_quiescent_confirmed',
    'manual_risk_accepted',
)
NOT_FOUND = Rejection('NOT_FOUND', None)


def fixed_input(value, kind):
    fields = PREVIEW_FIELDS if kind == PREPARE else ACCEPT_FIELDS
    body = object_fields(value, 'body', fields, fields)
    fixed = {key: strict_integer(body[key], key) for key in PREVIEW_FIELDS}
    if kind == PREPARE:
        return fixed
    fixed['delivery_plan_id'] = strict_integer(body['delivery_plan_id'], 'delivery_plan_id')
    oid = body['expected_target_commit']
    if (
        type(oid) is not str
        or re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', oid) is None
        or not oid.strip('0')
    ):
        reject('expected_target_commit', 'INVALID_FORMAT', '需要固定目标提交')
    fixed['expected_target_commit'] = oid
    if not strict_boolean(body['repository_quiescent_confirmed'], 'repository_quiescent_confirmed'):
        reject('repository_quiescent_confirmed', 'OUT_OF_RANGE', '需要明确确认本次仓库合作窗口')
    fixed['repository_quiescent_confirmed'] = True
    fixed['manual_risk_accepted'] = strict_boolean(
        body['manual_risk_accepted'], 'manual_risk_accepted'
    )
    return fixed


def _operation(connection, request, task, kind, at, *, plan=None):
    identity = entity_id(connection, EntityKind.OPERATION_RECORD)
    raw = canonical_input(request.data)
    connection.execute(
        """INSERT INTO code_operations(id,task_id,resource_kind,resource_id,session_id,operation_type,
           idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at)
           VALUES(?,?,'TASK',?,?,?,?,?,?,?,'PENDING',?)""",
        (
            identity,
            task['id'],
            task['id'],
            task['active_session_id'],
            kind,
            request.command.key,
            task['state_version'],
            raw,
            task['control_generation'],
            at,
        ),
    )
    connection.executemany(
        """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input,external_identity)
           VALUES(?,?,?,'PENDING',?,?)""",
        [
            (
                identity,
                n,
                name,
                raw,
                canonical_input(plan) if kind == PREPARE and name == 'SEAL_TARGET' else None,
            )
            for n, name in enumerate(operation_steps('CODING', kind), 1)
        ],
    )
    return identity


def original_operation(connection, identity, kind):
    row = connection.execute(
        """SELECT * FROM code_operations WHERE id=? AND operation_type=?
           AND resource_kind='TASK' AND task_id=resource_id AND testing_task_id IS NULL""",
        (identity, kind),
    ).fetchone()
    if row is None:
        raise StorageUnavailable('Original Coding delivery operation is missing')
    fixed = fixed_input(strict_json_object(row['fixed_input']), kind)
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no', (identity,)
    ).fetchall()
    if (
        [(step['step_no'], step['step_type']) for step in steps]
        != list(enumerate(operation_steps('CODING', kind), 1))
        or row['fixed_input'] != canonical_input(fixed)
        or row['expected_state_version'] != fixed['expected_state_version']
        or any(step['fixed_input'] != row['fixed_input'] for step in steps)
    ):
        raise StorageUnavailable('Original Coding delivery operation input differs')
    return row, fixed, steps


def _deliver_authorization(connection, task):
    row = connection.execute(
        "SELECT * FROM code_authorizations WHERE id=? AND task_id=? AND status='EFFECTIVE'",
        (task['authorization_id'], task['id']),
    ).fetchone()
    profile = connection.execute(
        'SELECT delivery,limits FROM code_execution_profile_versions WHERE id=?',
        (task['execution_profile_version_id'],),
    ).fetchone()
    if row is None or profile is None or profile['delivery'] is None:
        return None
    grant = project_grant(row)
    if (
        grant['profile_version_id'] != task['execution_profile_version_id']
        or not grant['scope']['allow_local_delivery']
    ):
        return None
    limits = strict_json_object(profile['limits'])
    seconds = min(
        limits['max_delivery_window_seconds'],
        grant['scope']['limits']['max_delivery_window_seconds'],
    )
    return strict_integer(seconds, 'max_delivery_window_seconds', maximum=300)


def delivery_action_reasons(connection, task, available):
    if (
        task['status'] != 'AWAITING_ACCEPTANCE'
        or task['phase'] != 'ACCEPTANCE'
        or task['stop_requested_at'] is not None
    ):
        return 'INVALID_STATE', 'INVALID_STATE'
    if (
        task['current_delivery_id'] is not None
        or connection.execute(
            """SELECT 1 FROM code_operations WHERE task_id=? AND status IN ('PENDING','RUNNING','UNKNOWN')
           UNION ALL SELECT 1 FROM code_waiting_items WHERE task_id=? AND status='OPEN' LIMIT 1""",
            (task['id'], task['id']),
        ).fetchone()
    ):
        return 'OPERATION_CONFLICT', 'OPERATION_CONFLICT'
    if _deliver_authorization(connection, task) is None:
        return 'DELIVERY_NOT_AUTHORIZED', 'DELIVERY_NOT_AUTHORIZED'
    if not available:
        return 'CONFIG_NOT_READY', 'CONFIG_NOT_READY'
    return None, None if task['current_delivery_plan_id'] is not None else 'DELIVERY_PLAN_STALE'


def current_delivery_inputs(connection, runtime, data, task, admissions, held, *, active=0):
    if (
        task['status'] != 'AWAITING_ACCEPTANCE'
        or task['phase'] != 'ACCEPTANCE'
        or task['stop_requested_at'] is not None
        or task['state_version'] >= MAX_SAFE_INTEGER - 2
    ):
        return start_conflict('INVALID_STATE', task)
    if task['current_candidate_id'] != data['candidate_id']:
        return start_conflict('CANDIDATE_NOT_CURRENT', task)
    if task['current_test_report_id'] != data['test_report_id']:
        return start_conflict('TEST_SOURCE_MISMATCH', task)
    if task['current_delivery_id'] is not None:
        return start_conflict('OPERATION_CONFLICT', task)
    conflict = connection.execute(
        """SELECT id FROM code_operations WHERE task_id=? AND id<>? AND status IN ('PENDING','RUNNING','UNKNOWN')
           UNION ALL SELECT NULL FROM code_waiting_items WHERE task_id=? AND status='OPEN' LIMIT 1""",
        (task['id'], active, task['id']),
    ).fetchone()
    if conflict is not None:
        return start_conflict('OPERATION_CONFLICT', task, conflict[0])
    if _deliver_authorization(connection, task) is None:
        return Rejection(
            'DELIVERY_NOT_AUTHORIZED',
            {'task_id': task['id'], 'authorization_id': task['authorization_id']},
        )
    require_current_report_link(connection, task)
    candidate = connection.execute(
        'SELECT * FROM code_candidates WHERE id=? AND task_id=?', (data['candidate_id'], task['id'])
    ).fetchone()
    report = connection.execute(
        'SELECT * FROM testing_reports WHERE id=?', (data['test_report_id'],)
    ).fetchone()
    if candidate is None or report is None:
        return NOT_FOUND
    reason, view = qualify_report(
        connection, runtime.catalog, admissions, task, candidate, report, held
    )
    return (candidate, view) if reason is None else start_conflict(reason, task)


def _cas(connection, task, at, *, delivery=None):
    version = increment(task['state_version'])
    changed = connection.execute(
        """UPDATE code_tasks SET state_version=?,updated_at=?,current_delivery_id=?
           WHERE id=? AND state_version=? AND control_generation=? AND stop_requested_at IS NULL
           AND current_candidate_id=? AND current_test_report_id=? AND current_delivery_id IS NULL
           AND status='AWAITING_ACCEPTANCE' AND phase='ACCEPTANCE'""",
        (
            version,
            at,
            delivery,
            task['id'],
            task['state_version'],
            task['control_generation'],
            task['current_candidate_id'],
            task['current_test_report_id'],
        ),
    )
    if changed.rowcount != 1:
        raise StorageUnavailable('Original Coding delivery acceptance was fenced')
    return version


def _receipt(task, operation, version, **refs):
    return Success(
        {
            'code': 'OPERATION_ACCEPTED',
            'data': {
                'task_id': task['id'],
                'operation_id': operation,
                'operation_status': 'PENDING',
                'task_status': task['status'],
                'state_version': version,
                **refs,
            },
            'details': None,
        },
        202,
    )


def _new_preview(connection, request, task, at):
    repo = connection.execute(
        'SELECT object_format FROM code_repositories WHERE id=?', (task['repository_id'],)
    ).fetchone()
    snapshot = connection.execute(
        'SELECT content_profile_version_id FROM code_snapshots WHERE id=?',
        (task['base_snapshot_id'],),
    ).fetchone()
    if repo is None or snapshot is None:
        raise StorageUnavailable('Original delivery repository or baseline is missing')
    claim = {
        'plan_id': entity_id(connection, EntityKind.DELIVERY_PLAN),
        'content_store_key': uuid4().hex,
        'object_format': repo['object_format'],
        'content_profile_version_id': snapshot['content_profile_version_id'],
    }
    operation = _operation(connection, request, task, PREPARE, at, plan=claim)
    return _receipt(task, operation, _cas(connection, task, at))


@dataclass(frozen=True)
class DeliveryTargetObservation:
    plan_id: int
    target_commit: str
    tree_oid: str
    observed_at: str
    controller_epoch: str
    checked_out: bool = False


def _plan(connection, task, data):
    row = connection.execute(
        'SELECT * FROM code_delivery_plans WHERE id=? AND task_id=?',
        (data['delivery_plan_id'], task['id']),
    ).fetchone()
    if row is None:
        return NOT_FOUND
    if (
        row['id'] != task['current_delivery_plan_id']
        or row['candidate_id'] != data['candidate_id']
        or row['test_report_id'] != data['test_report_id']
        or row['repository_id'] != task['repository_id']
        or row['target_branch'] != task['target_branch']
        or row['expected_target_commit'] != data['expected_target_commit']
    ):
        return start_conflict('DELIVERY_PLAN_STALE', task)
    original, fixed, steps = original_operation(connection, row['operation_id'], PREPARE)
    if (
        original['status'] != 'SUCCEEDED'
        or original['task_id'] != task['id']
        or original['control_generation'] != task['control_generation']
        or any(step['status'] != 'SUCCEEDED' for step in steps)
        or (fixed['candidate_id'], fixed['test_report_id'])
        != (row['candidate_id'], row['test_report_id'])
    ):
        raise StorageUnavailable('Original delivery plan publication differs')
    return row


def _new_delivery(connection, request, task, view, observation, at):
    data = request.data
    plan = _plan(connection, task, data)
    if type(plan) is Rejection:
        return plan
    if type(observation) is str:
        return start_conflict(observation, task)
    if type(observation) is not DeliveryTargetObservation or observation.plan_id != plan['id']:
        return start_conflict('DELIVERY_PLAN_STALE', task)
    if observation.checked_out:
        return start_conflict('TARGET_CHECKED_OUT', task)
    if (observation.target_commit, observation.tree_oid) != (
        plan['expected_target_commit'],
        plan['target_tree_oid'],
    ):
        return start_conflict('TARGET_CHANGED', task)
    if bool(view['manual_coverage_ids']) != data['manual_risk_accepted']:
        return Rejection(
            'INVALID_INPUT',
            {
                'field_errors': [{'field': 'manual_risk_accepted', 'reason': 'RANGE'}],
            },
        )
    seconds = _deliver_authorization(connection, task)
    if seconds is None:
        return Rejection(
            'DELIVERY_NOT_AUTHORIZED',
            {'task_id': task['id'], 'authorization_id': task['authorization_id']},
        )
    horizon = timedelta(seconds=seconds)
    if (
        not observation.observed_at
        <= at
        < utc_milliseconds(datetime.fromisoformat(observation.observed_at) + horizon)
    ):
        return start_conflict('DELIVERY_WINDOW_REQUIRED', task)
    expires = utc_milliseconds(datetime.fromisoformat(at) + horizon)
    operation = _operation(connection, request, task, DELIVER, at)
    acceptance = entity_id(connection, EntityKind.ACCEPTANCE)
    delivery = entity_id(connection, EntityKind.DELIVERY)
    window = entity_id(connection, EntityKind.DELIVERY_WINDOW)
    connection.execute(
        """INSERT INTO code_acceptances(id,task_id,candidate_id,test_report_id,delivery_plan_id,
           manual_risk_accepted,actor_ref,accepted_at) VALUES(?,?,?,?,?,?,?,?)""",
        (
            acceptance,
            task['id'],
            plan['candidate_id'],
            plan['test_report_id'],
            plan['id'],
            int(data['manual_risk_accepted']),
            current_operator_sid(),
            at,
        ),
    )
    connection.execute(
        """INSERT INTO code_deliveries(id,task_id,acceptance_id,delivery_plan_id,operation_id,
           status,git_write_status,postcheck_status,created_at,current_window_id)
           VALUES(?,?,?,?,?,'PENDING','NOT_DISPATCHED','NOT_RUN',?,?)""",
        (delivery, task['id'], acceptance, plan['id'], operation, at, window),
    )
    connection.execute(
        """INSERT INTO code_delivery_windows(id,delivery_id,operation_id,confirmed_at,expires_at,controller_epoch_ref)
           VALUES(?,?,?,?,?,?)""",
        (window, delivery, operation, at, expires, observation.controller_epoch),
    )
    return _receipt(
        task,
        operation,
        _cas(connection, task, at, delivery=delivery),
        acceptance_id=acceptance,
        delivery_id=delivery,
    )


def accept_delivery_command(runtime, request, *, worker):
    require_schema(runtime)
    if request.kind == DELIVER and getattr(worker, 'accepts_delivery_previews', False):
        original = read_registered_replay(runtime.commands(), request.command.scope, request.data)
        if original is not None:
            return original.result
        observation = worker.observe_delivery_plan(
            request.task_id, request.data['delivery_plan_id']
        )
    else:
        observation = None
    with ExitStack() as held:

        def apply(connection):
            task = connection.execute(
                'SELECT * FROM code_tasks WHERE id=?', (request.task_id,)
            ).fetchone()
            if task is None:
                return NOT_FOUND
            if task['status'] in ('TERMINATED', 'COMPLETED'):
                return start_conflict('TASK_ENDED', task)
            if task['state_version'] != request.data['expected_state_version']:
                return start_conflict('VERSION_CONFLICT', task)
            check = current_delivery_inputs(
                connection, runtime, request.data, task, request.admissions, held
            )
            if type(check) is Rejection:
                return check
            if not getattr(worker, 'accepts_delivery_previews', False):
                raise ConfigurationNotReady('Q20-GIT', 'Q20-CONTENT')
            at = max(operation_time(None), task['updated_at'])
            if request.kind == PREPARE:
                return _new_preview(connection, request, task, at)
            if (
                type(observation) is DeliveryTargetObservation
                and observation.controller_epoch != worker.delivery_epoch
            ):
                return start_conflict('DELIVERY_WINDOW_REQUIRED', task)
            return _new_delivery(connection, request, task, check[1], observation, at)

        return execute_idempotent(
            runtime.commands(),
            request.command.route.capability_id,
            request,
            apply,
            target_identity=request.command.scope.target_identity,
            allowed_failures=frozenset({'CONFIG_NOT_READY'}),
        )


def close_stopped_pending_delivery(connection, task, at):
    active = connection.execute(
        """SELECT 1 FROM code_operations WHERE task_id=? AND operation_type='PREPARE_DELIVERY'
           AND status IN ('PENDING','RUNNING','UNKNOWN') LIMIT 1""",
        (task['id'],),
    ).fetchone()
    if active is not None:
        raise StorageUnavailable('Original delivery preview resources require cleanup')
    if task['current_delivery_id'] is None:
        return
    delivery = connection.execute(
        'SELECT * FROM code_deliveries WHERE id=? AND task_id=?',
        (task['current_delivery_id'], task['id']),
    ).fetchone()
    if delivery is None:
        raise StorageUnavailable('Original pending delivery is missing')
    if delivery['status'] in ('BLOCKED', 'CANCELLED'):
        return
    operation, _, steps = original_operation(connection, delivery['operation_id'], DELIVER)
    if (
        delivery['status'] == 'SUCCEEDED'
        and delivery['git_write_status'] == 'CONFIRMED'
        and delivery['delivered_at'] is not None
        and all(step['status'] == 'SUCCEEDED' for step in steps[:7])
    ):
        # The verified branch write remains delivered. Only the unfinished
        # natural cleanup yields to the already accepted user termination.
        if operation['status'] in ('RUNNING', 'UNKNOWN'):
            connection.execute(
                """UPDATE code_operation_steps SET status='CANCELLED',ended_at=?,last_observed_at=?
                   WHERE operation_id=? AND step_no=8 AND status IN ('PENDING','RUNNING','UNKNOWN')""",
                (at, at, operation['id']),
            )
            connection.execute(
                "UPDATE code_operations SET status='CANCELLED',ended_at=?,failure_code='TASK_ENDED' WHERE id=?",
                (at, operation['id']),
            )
        return
    from .coding_job_evidence import read_closed_candidate_job_ids

    safe_unstarted = (
        delivery['git_write_status'] == 'NOT_DISPATCHED'
        and steps[5]['external_identity'] is None
        and read_closed_candidate_job_ids(connection, task['id']) is not None
    )
    safe_aborted = (
        delivery['git_write_status'] == 'ABORTED_UNSENT'
        and steps[5]['external_identity'] is None
        and read_closed_candidate_job_ids(connection, task['id']) is not None
    )
    if (
        delivery['status'] != 'PENDING'
        or operation['status'] not in ('PENDING', 'UNKNOWN')
        or not (safe_unstarted or safe_aborted)
    ):
        raise StorageUnavailable('Original delivery may have written the target')
    connection.execute(
        "UPDATE code_deliveries SET status='CANCELLED' WHERE id=?", (delivery['id'],)
    )
    connection.execute(
        """UPDATE code_operation_steps SET status='CANCELLED',ended_at=?,last_observed_at=?
           WHERE operation_id=? AND status IN ('PENDING','UNKNOWN')""",
        (at, at, operation['id']),
    )
    connection.execute(
        """UPDATE code_operations SET status='CANCELLED',ended_at=?,failure_code='TASK_ENDED'
           WHERE id=? AND status IN ('PENDING','UNKNOWN')""",
        (at, operation['id']),
    )
