"""Role-scoped, path-free projections of the independent management registry."""

from base64 import urlsafe_b64decode, urlsafe_b64encode
import binascii
from datetime import datetime, timezone
import re

from backend.app.infrastructure.environment_control import normal_stop
from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    decode,
    digest,
    exact,
    require,
)
from backend.app.infrastructure.environment_installation import uuid_value

from .attachment_observation import candidate_environment, now, observe_for_attach
from .host_capacity import available_memory_bytes
from .operation_contract import CONFLICT, DENIED, INVALID, MISSING, RESOURCE, UNAVAILABLE
from .operation_store import (
    conflicting_action,
    decoded,
    environment_row,
    may_read_environment,
    may_read_operation,
    operation_by_key,
    operation_result,
    operation_summary,
)
from .registry import is_timestamp
from .release_maintenance_view import confirmed_current_control
from .runtime_capacity import capacity_totals, held_capacity, load_capacity
from .runtime_observation import project_runtime

READ_ACTIONS = ('ATTACH', 'REGISTER_DELIVERY', 'START', 'STOP', 'RELEASE', 'BACKUP', 'RESTORE')
STATUSES = (
    'WAITING_CAPACITY',
    'ACCEPTED',
    'RUNNING',
    'SUCCEEDED',
    'FAILED',
    'CANCELLED',
    'UNKNOWN',
)
ENVIRONMENT_FILTERS = {
    'purpose': ('DEVELOPMENT', 'INTEGRATION', 'CANDIDATE', 'PRODUCTION'),
    'registration_state': ('ACTIVE', 'ARCHIVED'),
    'task_id': None,
}
OPERATION_FILTERS = {'environment_id': None, 'status': STATUSES}


def available_actions(principal, *, candidates=False, delivery_row=None, busy=False, runtime=None):
    attach = DENIED
    if principal.role == 'MANAGER':
        attach = None if candidates else RESOURCE
    delivery = DENIED
    if principal.role in ('MANAGER', 'DEVELOPER') and delivery_row is not None:
        if delivery_row['writer_principal'] == principal.id:
            available = (
                delivery_row['purpose'] in ('DEVELOPMENT', 'INTEGRATION')
                and delivery_row['registration_state'] == 'ACTIVE'
                and delivery_row['preparation_state'] == 'PREPARED'
                and delivery_row['assignment_control_state'] == 'OPEN'
            )
            delivery = UNAVAILABLE
            if available:
                delivery = CONFLICT if busy else None
    reasons = {
        'CREATE': UNAVAILABLE,
        'ATTACH': attach,
        'START': UNAVAILABLE if runtime is None else runtime['START'],
        'STOP': UNAVAILABLE if runtime is None else runtime['STOP'],
        'HANDOFF': UNAVAILABLE,
        'REGISTER_DELIVERY': delivery,
        'ARCHIVE': UNAVAILABLE,
        'CLEANUP': UNAVAILABLE,
    }
    return [
        {'action': action, 'enabled': reason is None, 'reason_code': reason}
        for action, reason in reasons.items()
    ]


def select_arguments(params, allowed, scope, principal, qualifier):
    values = {}
    for key, value in params.multi_items():
        require(key not in values and (key in allowed or key in ('limit', 'cursor')), INVALID)
        values[key] = value
    limit = values.pop('limit', '20')
    cursor = values.pop('cursor', None)
    require(re.fullmatch(r'[1-9][0-9]{0,2}', limit) is not None and int(limit) <= 100, INVALID)
    for key, value in values.items():
        accepted = allowed[key]
        require(uuid_value(value) if accepted is None else value in accepted, INVALID)
    context = digest(
        canonical(
            {
                'scope': scope,
                'kind': qualifier,
                'principal': principal.id,
                'role': principal.role,
                'visible': sorted(principal.visible),
                'filters': values,
            }
        )
    )
    last = None
    if cursor is not None:
        require(len(cursor) <= 400 and re.fullmatch(r'[A-Za-z0-9_-]+', cursor) is not None, INVALID)
        try:
            payload = urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4))
        except (binascii.Error, ValueError):
            require(False, INVALID)
        observed = exact(decode(payload, INVALID), ('context', 'last'), INVALID)
        last = observed['last']
        require(observed['context'] == context and type(last) is list, INVALID)
        if qualifier == 'environment':
            require(len(last) == 1 and uuid_value(last[0]), INVALID)
        else:
            require(len(last) == 2 and is_timestamp(last[0]) and uuid_value(last[1]), INVALID)
    return int(limit), values, last, context


def next_cursor(context, last):
    return (
        urlsafe_b64encode(canonical({'context': context, 'last': last}))
        .rstrip(b'=')
        .decode('ascii')
    )


def visible_filter(principal, alias, *, ownership=False):
    if principal.role == 'MANAGER':
        return '1=1', []
    expressions, values = [], []
    if principal.visible:
        expressions.append(
            f'{alias}.environment_id IN (' + ','.join('?' for _ in principal.visible) + ')'
        )
        values.extend(principal.visible)
    if principal.role == 'DEVELOPER' and ownership:
        expressions.append(f'{alias}.writer_principal = ?')
        values.append(principal.id)
    return ('(' + ' OR '.join(expressions) + ')', values) if expressions else ('1=0', [])


def prepare_observation(connection, environment):
    rows = connection.execute(
        'SELECT result_json FROM management_steps JOIN management_operations USING(operation_id) '
        "WHERE environment_id = ? AND step_kind = 'ATTACH_REGISTERED' "
        'ORDER BY created_at DESC, operation_id DESC LIMIT 1',
        (environment,),
    ).fetchone()
    if rows is None:
        return {
            'source': None,
            'observed_at': None,
            'freshness': 'UNAVAILABLE',
            'runtime_state': 'UNKNOWN',
            'run_id': None,
            'reason_code': 'MANAGED_PROCESS_UNVERIFIED',
        }
    evidence = decoded(rows['result_json'])
    at = evidence['observed_at']
    require(is_timestamp(at), INVALID)
    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(at)).total_seconds()
    return {
        'source': 'ATTACHMENT',
        'observed_at': at,
        'freshness': 'FRESH' if 0 <= elapsed <= 120 else 'STALE',
        'runtime_state': 'UNKNOWN',
        'run_id': None,
        'reason_code': 'MANAGED_PROCESS_UNVERIFIED',
    }


def runtime_actions(catalog, principal, row, busy, observation):
    if principal.role != 'MANAGER' and not (
        principal.role == 'DEVELOPER' and row['writer_principal'] == principal.id
    ):
        return {'START': DENIED, 'STOP': DENIED}
    eligible = (
        row['purpose'] in ('DEVELOPMENT', 'INTEGRATION')
        and row['registration_state'] == 'ACTIVE'
        and row['preparation_state'] == 'PREPARED'
        and row['assignment_control_state'] == 'OPEN'
        and row['configuration_ref'] is not None
    )
    if not eligible or busy:
        reason = CONFLICT if eligible else UNAVAILABLE
        return {'START': reason, 'STOP': reason}
    current = confirmed_current_control(catalog, row)
    running = (
        observation is not None
        and observation['freshness'] == 'FRESH'
        and observation['runtime_state'] == 'RUNNING'
    )
    return {
        'START': None
        if (
            not running
            and catalog.capacity_policy_sha256 is not None
            and current is not None
            and normal_stop(current)
        )
        else RESOURCE,
        'STOP': None
        if running and observation['reason_code'] == 'MANAGED_APPLICATION_READY'
        else RESOURCE,
    }


def business_entry(catalog, row, work):
    if (
        row['registration_state'] != 'ACTIVE'
        or row['preparation_state'] != 'PREPARED'
        or row['configuration_ref'] is None
    ):
        return None
    registered = catalog.business_entries.get(row['environment_id'])
    if registered is None:
        return None
    restored = work.get('restored_business_entry')
    candidates = (
        registered,
        restored if restored and restored['origin'] == registered['origin'] else None,
    )
    for entry in candidates:
        if (
            entry is not None
            and entry['data_generation'] == work['data_generation']
            and entry['deployment_id'] == work['deployment_id']
            and entry['configuration_sha256'] == row['configuration_sha256']
        ):
            return entry['origin']
    return None


def environment_summary(connection, catalog, row, principal):
    work = decoded(row['work_package_json'])
    observation = project_runtime(catalog, row, work)
    busy = conflicting_action(connection, row['environment_id'])
    return {
        **{
            key: row[key]
            for key in (
                'environment_id',
                'purpose',
                'display_name',
                'task_id',
                'record_version',
                'assignment_generation',
                'registration_state',
                'preparation_state',
                'configuration_sha256',
            )
        },
        'owner_label': work['owner_label'],
        'baseline_commit': work['baseline_commit'],
        'program_sha256': row['program_source'],
        'observation': observation or prepare_observation(connection, row['environment_id']),
        'allowed_actions': available_actions(
            principal,
            delivery_row=row,
            busy=busy,
            runtime=runtime_actions(catalog, principal, row, busy, observation),
        ),
        'business_url': business_entry(catalog, row, work),
    }


def environments(connection, catalog, principal, params):
    limit, filters, cursor, context = select_arguments(
        params, ENVIRONMENT_FILTERS, catalog.scope, principal, 'environment'
    )
    predicate, values = visible_filter(principal, 'env', ownership=True)
    where = [predicate]
    for key, value in filters.items():
        where.append(f'env.{key} = ?')
        values.append(value)
    if cursor:
        where.append('env.environment_id > ?')
        values.append(cursor[0])
    rows = connection.execute(
        'SELECT env.* FROM managed_environments AS env WHERE '
        + ' AND '.join(where)
        + ' ORDER BY env.environment_id LIMIT ?',
        (*values, limit + 1),
    ).fetchall()
    shown = rows[:limit]
    return {
        'environments': [environment_summary(connection, catalog, row, principal) for row in shown],
        'next_cursor': next_cursor(context, [shown[-1]['environment_id']])
        if len(rows) > limit
        else None,
    }


def environment_detail(connection, catalog, principal, identifier):
    require(uuid_value(identifier), INVALID)
    row = environment_row(connection, identifier)
    require(row is not None, MISSING)
    require(may_read_environment(principal, row), DENIED)
    work = decoded(row['work_package_json'])
    owners = connection.execute(
        'SELECT resource_id, kind, released_at FROM resource_claims WHERE environment_id = ? ORDER BY kind, resource_id',
        (identifier,),
    ).fetchall()
    return {
        **environment_summary(connection, catalog, row, principal),
        'work': {
            key: work[key]
            for key in ('goal', 'scope', 'checks', 'branch', 'data_generation', 'deployment_id')
        },
        'resources': [
            {
                'resource_id': item['resource_id'],
                'kind': item['kind'],
                'claimed': item['released_at'] is None,
            }
            for item in owners
        ],
    }


def environment_backups(connection, catalog, principal, identifier, params):
    require(uuid_value(identifier), INVALID)
    row = environment_row(connection, identifier)
    require(row is not None, MISSING)
    require(may_read_environment(principal, row), DENIED)
    reference = catalog.backup_indexes.get(identifier)
    pin = reference[1] if reference is not None else None
    scope = {**catalog.scope, 'environment_id': identifier, 'backup_index_sha256': pin}
    limit, _, cursor, context = select_arguments(params, {}, scope, principal, 'backup')
    from .backup_reconciliation import managed_backup_history

    summary, items = managed_backup_history(connection, catalog, identifier, now())
    if cursor is not None:
        items = [
            point for point in items if (point['cutoff_at'], point['backup_id']) < tuple(cursor)
        ]
    shown = items[:limit]
    return {
        'environment_id': identifier,
        'backups': shown,
        'backup_status': summary,
        'next_cursor': next_cursor(context, [shown[-1]['cutoff_at'], shown[-1]['backup_id']])
        if len(items) > limit
        else None,
    }


def operations(connection, catalog, principal, params):
    limit, filters, cursor, context = select_arguments(
        params, OPERATION_FILTERS, catalog.scope, principal, 'operation'
    )
    predicate, bindings = visible_filter(principal, 'env', ownership=True)
    if principal.role != 'MANAGER':
        predicate = f'({predicate} OR (op.principal = ? AND op.original_read_allowed = 1))'
        bindings.append(principal.id)
    where = [
        predicate,
        'op.registry_generation = ?',
        'op.action IN (' + ','.join('?' for _ in READ_ACTIONS) + ')',
    ]
    bindings.append(catalog.scope['registry_generation'])
    bindings.extend(READ_ACTIONS)
    for key, value in filters.items():
        where.append(f'op.{key} = ?')
        bindings.append(value)
    if cursor:
        where.append('(op.created_at, op.operation_id) < (?, ?)')
        bindings.extend(cursor)
    rows = connection.execute(
        'SELECT op.* FROM management_operations AS op JOIN managed_environments AS env USING(environment_id) WHERE '
        + ' AND '.join(where)
        + ' ORDER BY op.created_at DESC, op.operation_id DESC LIMIT ?',
        (*bindings, limit + 1),
    ).fetchall()
    shown = rows[:limit]
    return {
        'operations': [operation_summary(row) for row in shown],
        'next_cursor': next_cursor(context, [shown[-1]['created_at'], shown[-1]['operation_id']])
        if len(rows) > limit
        else None,
    }


def operation_detail(connection, catalog, principal, identity, *, by_key):
    require(uuid_value(identity), INVALID)
    if by_key:
        row = operation_by_key(connection, catalog.scope['registry_generation'], identity)
    else:
        row = connection.execute(
            'SELECT * FROM management_operations WHERE operation_id = ? AND registry_generation = ?',
            (identity, catalog.scope['registry_generation']),
        ).fetchone()
    require(row is not None, MISSING)
    require(may_read_operation(connection, principal, row), DENIED)
    require(row['action'] in READ_ACTIONS, UNAVAILABLE)
    return operation_result(connection, row)


def candidate_projection(connection, catalog, reference, expected, runtime_sha):
    candidate = catalog.candidate(reference, expected)
    view = {
        'candidate_ref': reference,
        'sha256': expected,
        'display_name': candidate['display_name'],
        'environment_id': None,
        'record_version': None,
        'observed_at': None,
        'state': 'EVIDENCE_REQUIRED',
    }
    intent = {'candidate_ref': reference, 'expected_candidate_sha256': expected}
    try:
        environment = candidate_environment(candidate, runtime_sha)
        current = environment_row(connection, environment.environment_id)
        if current is not None:
            view['environment_id'] = current['environment_id']
            view['record_version'] = current['record_version']
            if current['registration_state'] == 'ACTIVE':
                view['state'] = 'REGISTERED'
                return view
            if conflicting_action(connection, current['environment_id']):
                view['state'] = 'BLOCKED'
                return view
        owner = catalog.access(candidate['owner_principal'])
        require(owner.role in ('MANAGER', 'DEVELOPER'), DENIED)
        proof = observe_for_attach(catalog, intent, candidate, runtime_sha)
        require(is_timestamp(proof['observed_at']), RESOURCE)
        view['observed_at'] = proof['observed_at']
        view['state'] = 'REATTACH_READY' if current is not None else 'READY'
    except (EnvironmentFailure, OSError, ValueError, KeyError, TypeError):
        pass  # A candidate's missing evidence cannot hide the other installed entries.
    return view


def catalog_projection(connection, catalog, principal, runtime_sha):
    if principal.role != 'MANAGER':
        return {'candidates': []}
    return {
        'candidates': [
            candidate_projection(connection, catalog, ref, expected, runtime_sha)
            for ref, expected in sorted(catalog.candidates.items())
        ]
    }


def capacity(connection, catalog, principal):
    predicate, bindings = visible_filter(principal, 'env', ownership=True)
    waiting = connection.execute(
        'SELECT COUNT(*) FROM management_operations AS op JOIN managed_environments AS env USING(environment_id) '
        "WHERE op.status = 'WAITING_CAPACITY' AND op.registry_generation = ? AND " + predicate,
        (catalog.scope['registry_generation'], *bindings),
    ).fetchone()[0]
    try:
        available = available_memory_bytes()
    except (EnvironmentFailure, OSError):
        available = None
    total = None
    reserved = None
    try:
        policy = load_capacity(catalog)
        counts, _pending_memory = capacity_totals(held_capacity(connection))
        total = policy.limits['memory_bytes']
        reserved = counts['memory_bytes']
    except EnvironmentFailure:
        # The kernel observation remains meaningful when managed totals cannot be verified.
        pass
    return {
        'observed_at': now() if available is not None else None,
        'total': total,
        'reserved': reserved,
        'available': available,
        'waiting_count': waiting,
        'reason_code': 'HOST_CAPACITY_UNVERIFIED' if available is None else 'HOST_MEMORY_OBSERVED',
    }
