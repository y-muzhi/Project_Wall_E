"""Explicit Testing pack lifecycle controls and durable resource operations."""

from backend.app.code_tasks.configuration_identities import require_schema
from backend.app.code_tasks.operation_protocol import operation_steps
from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.shared.code_errors import empty_conflict
from backend.app.shared.command_execution import execute_idempotent, operation_time
from backend.app.shared.validation import MAX_SAFE_INTEGER

from .asset_invalidation import invalidate_bound_tasks
from .assets import NOT_FOUND, public_pack

REVOKE_PACK = 'REVOKE_PACK'


def pack_rejection(code, row):
    return Rejection(code, {**empty_conflict(), 'current_state_version': row['state_version']})


def save_lifecycle_operation(connection, request, pack, status, action, at):
    identity = entity_id(connection, EntityKind.OPERATION_RECORD)
    fixed = canonical_input(request.business_input())
    result = canonical_input(
        {
            'test_pack_version_id': pack['id'],
            'state_version': increment(pack['state_version']),
            'status': status,
        }
    )
    connection.execute(
        """INSERT INTO code_operations(id,resource_kind,resource_id,operation_type,idempotency_key,
           expected_state_version,fixed_input,status,created_at,started_at,ended_at)
           VALUES(?,'TEST_PACK_VERSION',?,?,?,?,?,'SUCCEEDED',?,?,?)""",
        (
            identity,
            pack['id'],
            action,
            request.idempotency_key,
            pack['state_version'],
            fixed,
            at,
            at,
            at,
        ),
    )
    connection.executemany(
        """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input,
           result_ref,started_at,ended_at,last_observed_at) VALUES(?,?,?,'SUCCEEDED',?,?,?,?,?)""",
        [
            (identity, number, step, fixed, result, at, at, at)
            for number, step in enumerate(operation_steps('RESOURCE', action), 1)
        ],
    )


def _revoke(connection, request, pack):
    if pack['status'] == 'REVOKED':
        return pack_rejection('TEST_ASSET_REVOKED', pack)
    at = max(operation_time(None), pack['published_at'] or pack['created_at'])
    save_lifecycle_operation(connection, request, pack, 'REVOKED', REVOKE_PACK, at)
    saved = connection.execute(
        """UPDATE testing_pack_versions SET status='REVOKED',state_version=?,
           revoked_at=?,revocation_reason=? WHERE id=? AND state_version=? AND status=?""",
        (
            increment(pack['state_version']),
            at,
            request.reason,
            pack['id'],
            pack['state_version'],
            pack['status'],
        ),
    )
    if saved.rowcount != 1:
        raise StorageUnavailable('Original Testing pack changed during revocation')
    invalidate_bound_tasks(connection, pack_version=pack['id'])
    return None


def mutate_pack(runtime, request, update):
    require_schema(runtime)

    def save(connection):
        pack = connection.execute(
            'SELECT * FROM testing_pack_versions WHERE id=?', (request.identity,)
        ).fetchone()
        if pack is None:
            return NOT_FOUND
        if pack['state_version'] != request.expected:
            return pack_rejection('VERSION_CONFLICT', pack)
        if pack['state_version'] == MAX_SAFE_INTEGER:
            return pack_rejection('INVALID_STATE', pack)
        rejected = update(connection, request, pack)
        if rejected is not None:
            return rejected
        original = connection.execute(
            'SELECT * FROM testing_pack_versions WHERE id=?', (pack['id'],)
        ).fetchone()
        data = public_pack(
            connection, original, installation=getattr(runtime.catalog, 'testing_assets', None)
        )
        return Success({'code': 'UPDATED', 'data': data, 'details': None}, 200)

    return execute_idempotent(
        runtime.commands(),
        request.command.route.capability_id,
        request,
        save,
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset(),
    )


def revoke_pack(runtime, request):
    return mutate_pack(runtime, request, _revoke)
