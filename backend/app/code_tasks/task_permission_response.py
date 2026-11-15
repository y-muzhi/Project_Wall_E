"""API47 accepts one original permission decision and preserves each native result."""

from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown
from backend.app.shared.command_execution import (
    ConfigurationNotReady,
    execute_idempotent,
    operation_time,
)
from backend.app.shared.http_boundary import handle_http, idempotency_header, request_query
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import (
    MAX_SAFE_INTEGER,
    decimal_integer,
    object_fields,
    strict_enum,
    strict_integer,
    strict_json_loads,
    strict_json_object,
)

from .authorizations import project_grant
from .coding_model_wait import read_task_waits
from .command_registry import RegisteredCommand, registered_command
from .configuration_identities import require_schema
from .native_permission_objects import usable_workspace_refs
from .operation_protocol import operation_steps
from .task_native_issues import (
    PERMISSION_FIELDS,
    capture_native_issues,
    normalize_question,
    observe_permission,
)
from .task_native_issues import (
    _current as current_native_scope,
)
from .task_question_response import (
    QuestionResponseReceipt,
    _acknowledged,
    _owned,
    validate_question_receipt,
)
from .task_records import record_confirmed_control
from .task_resume_runtime import _operation, _step
from .task_start import start_conflict

PATH = '/api/v1/code-tasks/{task_id}/permissions/{permission_id}/responses'
CAPABILITY = 'APP-CODE-CMD-C47'
KIND = 'DECIDE_PERMISSION'
STEPS = operation_steps('CODING', KIND)
DECISIONS = ('ALLOW_ONCE', 'DENY')
permission_response_router = APIRouter(redirect_slashes=False)


@dataclass(frozen=True)
class PermissionResponseRequest:
    task_id: int
    permission_id: int
    expected_state_version: int
    session_id: int
    decision: str
    command: RegisteredCommand

    body_fields = ('expected_state_version', 'session_id', 'decision')

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {
            'task_id': self.task_id,
            'permission_id': self.permission_id,
            'expected_state_version': self.expected_state_version,
            'session_id': self.session_id,
            'decision': self.decision,
        }

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        task = decimal_integer(request.path_params['task_id'], 'task_id')
        permission = decimal_integer(request.path_params['permission_id'], 'permission_id')
        fields = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        command = registered_command(
            'POST',
            PATH.format(task_id=task, permission_id=permission),
            idempotency_header(request, lowercase=True),
        )
        return cls(
            task,
            permission,
            strict_integer(fields['expected_state_version'], 'expected_state_version'),
            strict_integer(fields['session_id'], 'session_id'),
            strict_enum(fields['decision'], 'decision', DECISIONS),
            command,
        )


def permission_granted(connection, task, permission):
    """Current persisted grant and a supported concrete object, before native recheck."""
    if (
        permission['requested_action'] not in ('READ', 'WRITE')
        or permission['native_observation'] is None
        or not usable_workspace_refs(strict_json_loads(permission['object_refs']))
    ):
        return False
    grant = connection.execute(
        """SELECT * FROM code_authorizations WHERE id=? AND task_id=?
           AND profile_version_id=? AND status='EFFECTIVE'""",
        (task['authorization_id'], task['id'], task['execution_profile_version_id']),
    ).fetchone()
    return grant is not None and project_grant(grant)['scope']['write_workspace_only']


def _permission(connection, task_id, identity):
    return connection.execute(
        'SELECT * FROM code_permissions WHERE id=? AND task_id=?', (identity, task_id)
    ).fetchone()


def _wait(connection, task, permission):
    rows = connection.execute(
        """SELECT id FROM code_waiting_items WHERE task_id=? AND kind='PERMISSION'
           AND source_kind='PERMISSION' AND source_id=? AND status='OPEN'""",
        (task, permission),
    ).fetchall()
    if len(rows) != 1:
        raise StorageUnavailable('Original permission wait differs')
    return rows[0]['id']


def _accept(connection, task, permission, request):
    version = increment(task['state_version'])
    identity = entity_id(connection, EntityKind.OPERATION_RECORD)
    at = max(operation_time(None), task['updated_at'])
    fixed = canonical_input(
        {
            **request.business_input(),
            'instance_id': permission['instance_id'],
            'native_permission_id': permission['native_permission_id'],
            'authorization_id': task['authorization_id'],
            'waiting_item_id': _wait(connection, task['id'], permission['id']),
            'actor': 'USER',
        }
    )
    if (
        connection.execute(
            """UPDATE code_tasks SET state_version=?,updated_at=? WHERE id=? AND state_version=?
               AND control_generation=? AND stop_requested_at IS NULL""",
            (version, at, task['id'], task['state_version'], task['control_generation']),
        ).rowcount
        != 1
        or connection.execute(
            """UPDATE code_permissions SET status='ANSWERING'
               WHERE id=? AND task_id=? AND status='OPEN'""",
            (permission['id'], task['id']),
        ).rowcount
        != 1
    ):
        raise StorageUnavailable('Original permission acceptance fence changed')
    connection.execute(
        """INSERT INTO code_operations(id,task_id,resource_kind,resource_id,session_id,operation_type,
           idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at)
           VALUES(?,?,'TASK',?,?,'DECIDE_PERMISSION',?,?,?,?,'PENDING',?)""",
        (
            identity,
            task['id'],
            task['id'],
            request.session_id,
            request.idempotency_key,
            task['state_version'],
            fixed,
            task['control_generation'],
            at,
        ),
    )
    connection.executemany(
        """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input)
           VALUES(?,?,?,'PENDING',?)""",
        ((identity, number, step, fixed) for number, step in enumerate(STEPS, 1)),
    )
    return Success(
        {
            'code': 'OPERATION_ACCEPTED',
            'data': {
                'task_id': task['id'],
                'operation_id': identity,
                'operation_status': 'PENDING',
                'task_status': task['status'],
                'state_version': version,
            },
            'details': None,
        },
        202,
    )


def decide_permission(runtime, request, *, available):
    require_schema(runtime)

    def accept(connection):
        task = connection.execute(
            'SELECT * FROM code_tasks WHERE id=?', (request.task_id,)
        ).fetchone()
        permission = _permission(connection, request.task_id, request.permission_id)
        if task is None or permission is None:
            return Rejection('NOT_FOUND', None)
        if task['status'] in ('COMPLETED', 'TERMINATED'):
            return start_conflict('TASK_ENDED', task)
        if task['status'] != 'WAITING' or task['stop_requested_at'] is not None:
            return start_conflict('INVALID_STATE', task)
        if request.expected_state_version != task['state_version']:
            return start_conflict('VERSION_CONFLICT', task)
        if (
            request.session_id != task['active_session_id']
            or request.session_id != permission['session_id']
        ):
            return start_conflict('SESSION_NOT_CURRENT', task)
        previous = connection.execute(
            """SELECT id FROM code_operations WHERE task_id=? AND status IN ('PENDING','RUNNING','UNKNOWN')
               ORDER BY id LIMIT 1""",
            (task['id'],),
        ).fetchone()
        if previous is not None:
            return start_conflict('OPERATION_CONFLICT', task, previous['id'])
        if permission['status'] != 'OPEN':
            return start_conflict('QUESTION_NOT_OPEN', task)
        owner = current_native_scope(connection, task['id'])
        if owner is None or not _owned(permission, owner[1]):
            return start_conflict('SESSION_NOT_CURRENT', task)
        if request.decision == 'ALLOW_ONCE' and not permission_granted(
            connection, task, permission
        ):
            return Rejection(
                'PERMISSION_NOT_GRANTED',
                {
                    'task_id': task['id'],
                    'authorization_id': task['authorization_id'],
                },
            )
        if task['state_version'] >= MAX_SAFE_INTEGER - 3:
            return start_conflict('INVALID_STATE', task)
        if not available:
            raise ConfigurationNotReady('Q20-OC')
        return _accept(connection, task, permission, request)

    return execute_idempotent(
        runtime.commands(),
        CAPABILITY,
        request,
        accept,
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset({'CONFIG_NOT_READY'}),
    )


def original_permission_response(connection, operation):
    fixed = strict_json_object(operation['fixed_input'])
    public = {
        key: fixed[key]
        for key in (
            'task_id',
            'permission_id',
            'expected_state_version',
            'session_id',
            'decision',
        )
    }
    command = registered_command(
        'POST',
        PATH.format(task_id=public['task_id'], permission_id=public['permission_id']),
        operation['idempotency_key'],
    )
    original = _permission(connection, public['task_id'], public['permission_id'])
    receipt = connection.execute(
        """SELECT * FROM idempotency_records WHERE capability_id=? AND target_identity=? AND idempotency_key=?""",
        command.scope.identity,
    ).fetchone()
    if (
        operation['operation_type'] != KIND
        or operation['resource_kind'] != 'TASK'
        or operation['resource_id'] != public['task_id']
        or operation['task_id'] != public['task_id']
        or operation['testing_task_id'] is not None
        or operation['session_id'] != public['session_id']
        or operation['expected_state_version'] != public['expected_state_version']
        or public['decision'] not in DECISIONS
        or fixed['actor'] != 'USER'
        or original is None
        or original['session_id'] != public['session_id']
        or original['instance_id'] != fixed['instance_id']
        or original['control_generation'] != operation['control_generation']
        or original['native_permission_id'] != fixed['native_permission_id']
        or receipt is None
        or receipt['status'] != 'SUCCEEDED'
        or receipt['business_input_json'] != canonical_input(public)
    ):
        raise StorageUnavailable('Original permission response association differs')
    saved = strict_json_object(receipt['success_result_json'])
    Success(saved, receipt['http_status']).encoded()
    validate_question_receipt(command, saved['data'], receipt['http_status'])
    if (
        saved['code'] != 'OPERATION_ACCEPTED'
        or saved['data']['operation_id'] != operation['id']
        or saved['data']['state_version'] != public['expected_state_version'] + 1
    ):
        raise StorageUnavailable('Original permission response receipt differs')
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation['id'],),
    ).fetchall()
    if len(steps) != len(STEPS) or any(
        row['step_no'] != number
        or row['step_type'] != name
        or row['fixed_input'] != operation['fixed_input']
        for number, (row, name) in enumerate(zip(steps, STEPS), 1)
    ):
        raise StorageUnavailable('Original permission response steps differ')
    return fixed, public, original, steps


def _current(connection, identity):
    operation = connection.execute(
        'SELECT * FROM code_operations WHERE id=?', (identity,)
    ).fetchone()
    if operation is None or operation['status'] not in ('PENDING', 'RUNNING'):
        return None
    owner = current_native_scope(connection, operation['task_id'])
    if owner is None:
        return None
    fixed, _, original, steps = original_permission_response(connection, operation)
    task, scope, native = owner
    if (
        not _owned(original, scope)
        or original['status'] != 'ANSWERING'
        or task['authorization_id'] != fixed['authorization_id']
        or task['state_version'] <= operation['expected_state_version']
        or _wait(connection, task['id'], original['id']) != fixed['waiting_item_id']
    ):
        raise StorageUnavailable('Original permission response fence differs')
    return task, scope, native, original, steps, fixed


def _matches(row, normalized):
    return row['native_observation'] in (None, normalized['native_observation']) and all(
        row[field] == normalized[field] or (field == 'object_refs' and row[field] == '[]')
        for field in PERMISSION_FIELDS
    )


def _observed_items(connection, task, scope, original, raw, decision):
    items = []
    for native in raw:
        normalized = observe_permission(native)
        stored = connection.execute(
            """SELECT * FROM code_permissions WHERE task_id=? AND session_id=? AND native_permission_id=?""",
            (task['id'], scope.session_id, normalized['native_permission_id']),
        ).fetchone()
        if stored is None or not _owned(stored, scope) or not _matches(stored, normalized):
            raise StorageUnavailable('Original permission observation differs')
        if stored['id'] != original['id'] and (decision != 'DENY' or stored['status'] != 'OPEN'):
            continue
        items.append(
            {
                'permission_id': stored['id'],
                'waiting_id': _wait(connection, task['id'], stored['id']),
                'native_permission_id': normalized['native_permission_id'],
            }
        )
    return sorted(items, key=lambda item: item['permission_id'])


def _observed(steps):
    if steps[0]['result_ref'] is None:
        return []
    return strict_json_object(steps[0]['result_ref'])['items']


def _receipts(steps):
    if steps[1]['result_ref'] is None:
        return {}
    return strict_json_object(steps[1]['result_ref'])['receipts']


def _permission_results(steps, decision, receipts):
    items = _observed(steps)
    if any(
        not _acknowledged(row) or (decision == 'DENY' and row['source'] != 'NATIVE_EVENT')
        for row in receipts.values()
    ):
        raise StorageUnavailable('Original permission confirmation differs')
    if not set(receipts).issubset({item['native_permission_id'] for item in items}):
        raise StorageUnavailable('Original permission confirmation crosses observation')
    return {
        'confirmed_permission_ids': [
            item['permission_id'] for item in items if item['native_permission_id'] in receipts
        ],
        'pending_permission_ids': [
            item['permission_id'] for item in items if item['native_permission_id'] not in receipts
        ],
    }


def _failed(connection, identity, original, steps, failure, at):
    connection.execute(
        "UPDATE code_permissions SET status=? WHERE id=? AND status='ANSWERING'",
        ('UNKNOWN' if failure == 'QUESTION_NOT_OPEN' else 'OPEN', original['id']),
    )
    if steps[0]['status'] == 'PENDING':
        _step(connection, identity, 1, 'FAILED', at)
    else:
        _step(connection, identity, 2, 'FAILED', at)
    _operation(connection, identity, 'FAILED', at, failure)


def _apply_results(connection, identity, task_id, steps, decision, at, receipts):
    results = _permission_results(steps, decision, receipts)
    for item in _observed(steps):
        permission_id = item['permission_id']
        proof = receipts.get(item['native_permission_id'])
        status = 'UNKNOWN' if proof is None else 'REJECTED' if decision == 'DENY' else 'RESOLVED'
        if (
            connection.execute(
                """UPDATE code_permissions SET status=?,resolved_at=? WHERE task_id=?
               AND id=? AND status='ANSWERING'""",
                (status, None if proof is None else at, task_id, permission_id),
            ).rowcount
            != 1
        ):
            raise StorageUnavailable('Original permission state changed')
        if proof is None:
            continue
        if (
            connection.execute(
                """UPDATE code_waiting_items SET status='RESOLVED',resolved_at=?,resolution_ref=?
               WHERE id=? AND task_id=? AND kind='PERMISSION' AND source_id=? AND status='OPEN'""",
                (
                    at,
                    canonical_input({'operation_id': identity, 'outcome': decision}),
                    item['waiting_id'],
                    task_id,
                    permission_id,
                ),
            ).rowcount
            != 1
        ):
            raise StorageUnavailable('Original permission wait changed')
    complete = not results['pending_permission_ids']
    _step(
        connection,
        identity,
        2,
        'SUCCEEDED' if complete else 'UNKNOWN',
        at,
        result={'receipts': receipts},
    )
    if complete:
        _step(connection, identity, 3, 'SUCCEEDED', at, result=results)
    _operation(
        connection,
        identity,
        'SUCCEEDED' if complete else 'UNKNOWN',
        at,
        None if complete else 'EXTERNAL_RESULT_UNKNOWN',
    )
    return complete


def _finish(connection, identity, current, at, receipts):
    task, scope, _, _, steps, fixed = current
    complete = _apply_results(
        connection, identity, task['id'], steps, fixed['decision'], at, receipts
    )
    if complete:
        record_confirmed_control(
            connection, scope, identity, '原执行会话已确认收到本次权限决定。', at
        )
    waiting = bool(read_task_waits(connection, task['id']))
    if (
        connection.execute(
            """UPDATE code_tasks SET status=?,resume_phase=?,state_version=?,updated_at=?,last_observed_at=?
           WHERE id=? AND state_version=? AND control_generation=? AND stop_requested_at IS NULL""",
            (
                'WAITING' if waiting else 'RUNNING',
                task['phase'] if waiting else None,
                increment(task['state_version']),
                at,
                at,
                task['id'],
                task['state_version'],
                task['control_generation'],
            ),
        ).rowcount
        != 1
    ):
        raise StorageUnavailable('Original permission completion fence changed')


def advance_permission_responses(runtime, driver, *, cancelled):
    if cancelled():
        return False
    db = runtime.database
    with db.transaction() as connection:
        candidate = connection.execute(
            """SELECT o.id FROM code_operations o JOIN code_tasks t ON t.id=o.task_id
               WHERE o.operation_type='DECIDE_PERMISSION' AND o.status IN ('PENDING','RUNNING')
               AND t.control_generation=o.control_generation AND t.stop_requested_at IS NULL
               ORDER BY o.id LIMIT 1"""
        ).fetchone()
        current = None if candidate is None else _current(connection, candidate['id'])
    if current is None:
        return False
    identity = candidate['id']
    _, scope, native, original, steps, fixed = current
    if steps[0]['status'] == 'SUCCEEDED':
        # Do not rewrite the fixed native observation or repeat an uncertain POST.
        with db.transaction(write=True) as connection:
            current = _current(connection, identity)
            if current is None or cancelled():
                return False
            at = max(operation_time(None), current[0]['updated_at'])
            if steps[1]['external_identity'] is not None:
                _finish(connection, identity, current, at, _receipts(steps))
            else:
                _failed(connection, identity, original, steps, 'CONFIG_NOT_READY', at)
        return True

    def checkpoint():
        if cancelled():
            raise TaskExecutionError('ORIGINAL_PERMISSION_RESPONSE_CANCELLED')
        with db.transaction() as connection:
            value = _current(connection, identity)
            if value is None or value[1] != scope:
                raise TaskExecutionError('ORIGINAL_PERMISSION_RESPONSE_FENCED')

    observed = None
    failure = 'CONFIG_NOT_READY'
    try:
        if driver.session_available(scope.operation_id):
            questions, permissions = driver.observe_native_issues(scope, native, checkpoint)
            observed = (
                [normalize_question(row) for row in questions],
                [observe_permission(row) for row in permissions],
            )
            original_native = next(
                (row for row in permissions if row['id'] == original['native_permission_id']), None
            )
            if original_native is None:
                failure = 'QUESTION_NOT_OPEN'
            elif not _matches(original, observe_permission(original_native)):
                observed = None
                failure = 'QUESTION_NOT_OPEN'
            else:
                failure = None
    except (TaskExecutionError, LaunchOutcomeUnknown, OSError, ValueError, TypeError, KeyError):
        observed = None

    with db.transaction(write=True) as connection:
        current = _current(connection, identity)
        if current is None or current[1] != scope or cancelled():
            return False
        task, _, _, original, steps, fixed = current
        at = max(operation_time(None), task['updated_at'])
        if observed is not None:
            capture_native_issues(connection, task, scope, *observed, at)
        if failure is not None:
            _failed(connection, identity, original, steps, failure, at)
            return True
        if fixed['decision'] == 'ALLOW_ONCE' and not permission_granted(connection, task, original):
            _failed(connection, identity, original, steps, 'PERMISSION_NOT_GRANTED', at)
            return True
        items = _observed_items(connection, task, scope, original, permissions, fixed['decision'])
        if not any(item['permission_id'] == original['id'] for item in items):
            raise StorageUnavailable('Original selected permission observation missing')
        _step(connection, identity, 1, 'SUCCEEDED', at, result={'items': items})
        _operation(connection, identity, 'RUNNING', at)

    def claim():
        with db.transaction(write=True) as connection:
            value = _current(connection, identity)
            if value is None or value[1] != scope or cancelled():
                raise TaskExecutionError('ORIGINAL_PERMISSION_RESPONSE_FENCED')
            task, _, _, selected, steps, fixed = value
            if steps[1]['external_identity'] is not None or _observed(steps) != items:
                raise StorageUnavailable('Original permission claim differs')
            if fixed['decision'] == 'ALLOW_ONCE' and not permission_granted(
                connection, task, selected
            ):
                raise TaskExecutionError('ORIGINAL_PERMISSION_OBJECT_UNVERIFIED')
            for item in items:
                if item['permission_id'] == selected['id']:
                    continue
                if (
                    connection.execute(
                        "UPDATE code_permissions SET status='ANSWERING' WHERE task_id=? AND id=? AND status='OPEN'",
                        (task['id'], item['permission_id']),
                    ).rowcount
                    != 1
                ):
                    raise StorageUnavailable('Original rejection cohort changed')
            at = max(operation_time(None), task['updated_at'])
            _step(
                connection,
                identity,
                2,
                'RUNNING',
                at,
                intent={'permission_id': selected['id'], 'session_id': scope.session_id},
            )

    receipts = {}
    native_ids = tuple(item['native_permission_id'] for item in items)

    def record(request, evidence):
        checkpoint()
        if (
            request in receipts
            or request not in native_ids
            or not _acknowledged(evidence)
            or (fixed['decision'] == 'DENY' and evidence['source'] != 'NATIVE_EVENT')
        ):
            raise StorageUnavailable('Original permission receipt differs')
        receipts[request] = evidence

    reply = 'once' if fixed['decision'] == 'ALLOW_ONCE' else 'reject'
    pre_dispatch_failure = 'CONFIG_NOT_READY'
    try:
        driver.decide_native_permission(
            scope,
            (native, original_native, native_ids, reply),
            checkpoint,
            claim,
            record,
        )
    except (
        TaskExecutionError,
        LaunchOutcomeUnknown,
        OSError,
        ValueError,
        TypeError,
        KeyError,
    ) as error:
        if str(error) in (
            'ORIGINAL_PERMISSION_OBJECT_DIFFERS',
            'ORIGINAL_PERMISSION_OBJECT_UNVERIFIED',
            'ORIGINAL_OPENCODE_WORKTREE_UNVERIFIED',
        ):
            pre_dispatch_failure = 'PERMISSION_NOT_GRANTED'
    with db.transaction(write=True) as connection:
        current = _current(connection, identity)
        if current is None or current[1] != scope or cancelled():
            return False
        task, _, _, original, steps, _ = current
        at = max(operation_time(None), task['updated_at'])
        if steps[1]['external_identity'] is None:
            _failed(connection, identity, original, steps, pre_dispatch_failure, at)
        else:
            _finish(connection, identity, current, at, receipts)
    return True


def retire_permission_responses(
    connection, task_id, session_id, generation, *, at=None, session_scopes=None
):
    allowed = {(session_id, generation)} if session_scopes is None else set(session_scopes)
    rows = connection.execute(
        """SELECT * FROM code_operations WHERE task_id=? AND operation_type='DECIDE_PERMISSION'
           AND status IN ('PENDING','RUNNING','UNKNOWN') ORDER BY id""",
        (task_id,),
    ).fetchall()
    for operation in rows:
        fixed, _, original, steps = original_permission_response(connection, operation)
        if (operation['session_id'], operation['control_generation']) not in allowed:
            raise StorageUnavailable('Original permission response crosses stop scope')
        if at is None or operation['status'] == 'UNKNOWN':
            continue
        if steps[1]['external_identity'] is not None:
            _apply_results(
                connection, operation['id'], task_id, steps, fixed['decision'], at, _receipts(steps)
            )
        elif steps[0]['status'] == 'SUCCEEDED':
            _failed(connection, operation['id'], original, steps, 'TASK_ENDED', at)
        else:
            connection.execute(
                """UPDATE code_operations SET status='CANCELLED',ended_at=?,failure_code='TASK_ENDED' WHERE id=?""",
                (at, operation['id']),
            )
            connection.execute(
                "UPDATE code_permissions SET status='OBSOLETE' WHERE id=? AND status='ANSWERING'",
                (original['id'],),
            )


def public_permission_response(connection, operation):
    fixed, public, _, steps = original_permission_response(connection, operation)
    results = _permission_results(steps, fixed['decision'], _receipts(steps))
    observed = [item['permission_id'] for item in _observed(steps)]
    projections = (
        {'permission_ids': observed} if steps[0]['status'] == 'SUCCEEDED' else None,
        results if steps[1]['status'] in ('SUCCEEDED', 'UNKNOWN') else None,
        results if steps[2]['status'] == 'SUCCEEDED' else None,
    )
    if steps[2]['status'] == 'SUCCEEDED' and strict_json_object(steps[2]['result_ref']) != results:
        raise StorageUnavailable('Original permission final result differs')
    return project_permission_response(
        {
            **dict(operation),
            'fixed_input': public,
            'content_capture': None,
            'steps': [
                {
                    **dict(row),
                    'fixed_input': public,
                    'external_identity': {} if row['external_identity'] is not None else None,
                    'result_ref': result,
                }
                for row, result in zip(steps, projections, strict=True)
            ],
        },
        operation['id'],
    )


def _identities(values):
    if type(values) is not list:
        raise ValueError('Original permission result identity array differs')
    for identity in values:
        strict_integer(identity, 'permission_id')
    if values != sorted(set(values)):
        raise ValueError('Original permission result identity order differs')
    return values


def project_permission_response(value, identity):
    from .repository_operations import OPERATION_FIELDS, STEP_FIELDS, _time

    row = exact(value, OPERATION_FIELDS)
    fixed = exact(
        row['fixed_input'],
        (
            'task_id',
            'permission_id',
            'expected_state_version',
            'session_id',
            'decision',
        ),
    )
    for name in ('task_id', 'permission_id', 'expected_state_version', 'session_id'):
        strict_integer(fixed[name], name)
    strict_enum(fixed['decision'], 'decision', DECISIONS)
    strict_integer(row['control_generation'], 'control_generation')
    if (
        row['id'] != identity
        or row['operation_type'] != KIND
        or row['resource_kind'] != 'TASK'
        or row['task_id'] != fixed['task_id']
        or row['resource_id'] != fixed['task_id']
        or row['session_id'] != fixed['session_id']
        or row['expected_state_version'] != fixed['expected_state_version']
        or row['testing_task_id'] is not None
        or row['content_capture'] is not None
    ):
        raise ValueError('Original permission operation projection differs')
    registered_command(
        'POST',
        PATH.format(task_id=fixed['task_id'], permission_id=fixed['permission_id']),
        row['idempotency_key'],
    )
    profiles = {
        'PENDING': (('PENDING', 'PENDING', 'PENDING'),),
        'RUNNING': (('SUCCEEDED', 'PENDING', 'PENDING'), ('SUCCEEDED', 'RUNNING', 'PENDING')),
        'UNKNOWN': (('SUCCEEDED', 'UNKNOWN', 'PENDING'),),
        'FAILED': (('FAILED', 'PENDING', 'PENDING'), ('SUCCEEDED', 'FAILED', 'PENDING')),
        'CANCELLED': (('PENDING', 'PENDING', 'PENDING'),),
        'SUCCEEDED': (('SUCCEEDED', 'SUCCEEDED', 'SUCCEEDED'),),
    }
    failures = {
        'FAILED': ('QUESTION_NOT_OPEN', 'CONFIG_NOT_READY', 'PERMISSION_NOT_GRANTED', 'TASK_ENDED'),
        'CANCELLED': ('TASK_ENDED',),
        'UNKNOWN': ('EXTERNAL_RESULT_UNKNOWN',),
    }
    status = row['status']
    if (
        status not in profiles
        or type(row['steps']) is not list
        or len(row['steps']) != 3
        or row['failure_code'] not in failures.get(status, (None,))
    ):
        raise ValueError('Original permission operation state differs')
    steps = [exact(step, STEP_FIELDS) for step in row['steps']]
    phases = tuple(step['status'] for step in steps)
    if phases not in profiles[status]:
        raise ValueError('Original permission step states differ')
    created, started, ended = (row[name] for name in ('created_at', 'started_at', 'ended_at'))
    for date, present in (
        (created, True),
        (started, status not in ('PENDING', 'CANCELLED')),
        (ended, status in ('SUCCEEDED', 'FAILED', 'CANCELLED')),
    ):
        _time(date, nullable=not present)
        if present != (date is not None):
            raise ValueError('Original permission operation chronology differs')
    if not created <= (started or created) <= (ended or started or created):
        raise ValueError('Original permission operation chronology differs')
    for number, (step, name, phase) in enumerate(zip(steps, STEPS, phases, strict=True), 1):
        step_started, step_ended, observed = (
            step[key] for key in ('started_at', 'ended_at', 'last_observed_at')
        )
        complete = phase in ('SUCCEEDED', 'FAILED')
        dispatched = number == 2 and phase in ('RUNNING', 'SUCCEEDED', 'UNKNOWN')
        if (
            step['operation_id'] != identity
            or step['step_no'] != number
            or step['step_type'] != name
            or step['fixed_input'] != fixed
            or step['external_identity'] != ({} if dispatched else None)
            or (step_started is None) != (phase == 'PENDING')
            or (observed is None) != (phase == 'PENDING')
            or (step_ended is not None) != complete
        ):
            raise ValueError('Original permission step projection differs')
        for date in (step_started, step_ended, observed):
            _time(date)
        if (
            not created
            <= (step_started or created)
            <= (step_ended or observed or created)
            <= (observed or created)
        ):
            raise ValueError('Original permission step chronology differs')
    read_result, send_result, final_result = (step['result_ref'] for step in steps)
    if phases[0] == 'SUCCEEDED':
        observed_ids = _identities(exact(read_result, ('permission_ids',))['permission_ids'])
        if fixed['permission_id'] not in observed_ids or (
            fixed['decision'] == 'ALLOW_ONCE' and len(observed_ids) != 1
        ):
            raise ValueError('Original permission observation crosses the operation')
    elif read_result is not None:
        raise ValueError('Original permission observation was not confirmed')
    if phases[1] in ('SUCCEEDED', 'UNKNOWN'):
        result = exact(send_result, ('confirmed_permission_ids', 'pending_permission_ids'))
        confirmed = _identities(result['confirmed_permission_ids'])
        pending = _identities(result['pending_permission_ids'])
        if (
            sorted(confirmed + pending) != observed_ids
            or bool(pending) != (phases[1] == 'UNKNOWN')
            or final_result != (result if status == 'SUCCEEDED' else None)
        ):
            raise ValueError('Original permission confirmation crosses the operation')
    elif send_result is not None or final_result is not None:
        raise ValueError('Original permission confirmation is unexpected')
    return row


class PermissionResponseReceipt(QuestionResponseReceipt):
    errors = QuestionResponseReceipt.errors - {'BASIS_REF_INVALID'}


@permission_response_router.post(PATH)
async def permission_response_http(request: Request):
    from .repository_registration_worker import RepositoryRegistrationWorker

    worker = getattr(request.app.state, 'walle_repository_registration', None)
    available = isinstance(worker, RepositoryRegistrationWorker) and worker.accepts_native_responses

    def invoke(runtime, parsed):
        return decide_permission(runtime, parsed, available=available)

    result = await handle_http(
        request, PermissionResponseRequest, PermissionResponseReceipt, invoke
    )
    if result.status_code == 202 and available:
        worker.wake()
    return result
