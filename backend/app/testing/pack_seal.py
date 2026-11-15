"""Original Testing pack sealing acceptance, execution, and atomic SQL publication."""

import sqlite3
from contextlib import ExitStack
from dataclasses import dataclass
from time import monotonic

from backend.app.code_tasks.configuration_identities import require_schema
from backend.app.code_tasks.operation_protocol import operation_steps
from backend.app.infrastructure.check_runner_bundle import CheckResourceError
from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.content_paths import ContentPathError
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.infrastructure.schema_transport import compact
from backend.app.infrastructure.windows_config_source import ConfigReadError
from backend.app.infrastructure.windows_local_paths import PathBoundaryError
from backend.app.infrastructure.windows_private_package import PackageSecurityError
from backend.app.infrastructure.windows_task_workspace_lease import WorkspaceWriteError
from backend.app.shared.code_errors import empty_conflict
from backend.app.shared.command_execution import (
    ConfigurationNotReady,
    execute_idempotent,
    operation_time,
)
from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_json_object

from .asset_installation import hold_compiler_sources
from .assets import NOT_FOUND
from .pack_compile import CompileError, basis_fingerprint, case_targets, compile_pack, plan_digest
from .pack_storage import hold_published_pack
from .plans import _version

STEPS = operation_steps('RESOURCE', 'SEAL_PACK')
RESOURCE_ERRORS = (
    CheckResourceError,
    ConfigReadError,
    ContentPathError,
    PackageSecurityError,
    PathBoundaryError,
    WorkspaceWriteError,
)
_SELECT = """SELECT * FROM code_operations
              WHERE resource_kind='TEST_PACK_VERSION' AND operation_type='SEAL_PACK'
              AND task_id IS NULL AND testing_task_id IS NULL"""


def _pack(connection, identity):
    return connection.execute(
        'SELECT * FROM testing_pack_versions WHERE id=?', (identity,)
    ).fetchone()


def _conflict(code, pack, operation=None):
    return Rejection(
        code,
        {
            **empty_conflict(),
            'current_state_version': pack['state_version'],
            'related_operation_id': operation,
        },
    )


def _installation(runtime):
    return getattr(runtime.catalog, 'testing_assets', None)


def _directory_token(directory):
    return {'volume_serial': directory.volume_serial, 'file_id': directory.file_id}


def _target_token(entry):
    return {
        'target': entry.target.wire(),
        'runner_source': _directory_token(entry.runner.directory),
        'fixture_source': _directory_token(entry.fixture_directory),
    }


def _target_tokens(installation, targets):
    selected = {target.target_ref for target in targets}
    return [
        _target_token(entry)
        for entry in sorted(
            installation.registered_targets, key=lambda item: item.target.target_ref
        )
        if entry.target.target_ref in selected
    ]


def _accept(connection, request, installation):
    pack = _pack(connection, request.identity)
    if pack is None:
        return NOT_FOUND
    plan = _version(connection, pack['plan_version_id'])
    if plan is None:
        raise StorageUnavailable('Original Testing plan is missing')
    if pack['status'] == 'REVOKED' or plan['status'] == 'REVOKED':
        return _conflict('TEST_ASSET_REVOKED', pack)
    if request.expected != pack['state_version']:
        return _conflict('VERSION_CONFLICT', pack)
    if (
        pack['status'] != 'DRAFT'
        or plan['status'] != 'PUBLISHED'
        or pack['state_version'] == MAX_SAFE_INTEGER
    ):
        return _conflict('INVALID_STATE', pack)
    active = connection.execute(
        _SELECT + " AND resource_id=? AND status IN ('PENDING','RUNNING','UNKNOWN')",
        (pack['id'],),
    ).fetchone()
    if active is not None:
        return _conflict('OPERATION_IN_PROGRESS', pack, active['id'])
    if installation is None or not installation.targets:
        raise ConfigurationNotReady('Q20-CHECKS')
    try:
        basis = basis_fingerprint(connection, plan)
        targets = case_targets(plan, installation.targets)
    except CompileError as error:
        return Rejection(
            'CHECK_CONFIGURATION_INVALID',
            {'field_errors': [{'field': error.field, 'reason': 'RELATION'}]},
        )
    operation = entity_id(connection, EntityKind.OPERATION_RECORD)
    at = max(operation_time(None), pack['created_at'])
    fixed = canonical_input(
        {
            'expected_state_version': request.expected,
            'plan_version_id': plan['id'],
            'pack_version': pack['version'],
            'plan_sha256': plan_digest(plan),
            'basis_fingerprint': basis,
            'targets': _target_tokens(installation, targets),
            'pack_root': _directory_token(installation.pack_directory),
        }
    )
    connection.execute(
        """INSERT INTO code_operations(id,resource_kind,resource_id,operation_type,idempotency_key,
           expected_state_version,fixed_input,status,created_at)
           VALUES(?,'TEST_PACK_VERSION',?,'SEAL_PACK',?,?,?,'PENDING',?)""",
        (operation, pack['id'], request.idempotency_key, request.expected, fixed, at),
    )
    connection.executemany(
        """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input)
           VALUES(?,?,?,'PENDING',?)""",
        [(operation, number, step, fixed) for number, step in enumerate(STEPS, 1)],
    )
    return Success(
        {
            'code': 'OPERATION_ACCEPTED',
            'data': {
                'operation_id': operation,
                'test_pack_version_id': pack['id'],
                'validation_id': None,
            },
            'details': None,
        },
        202,
    )


def seal_pack(runtime, request):
    require_schema(runtime)
    return execute_idempotent(
        runtime.commands(),
        request.command.route.capability_id,
        request,
        lambda connection: _accept(connection, request, _installation(runtime)),
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset({'CONFIG_NOT_READY'}),
    )


def operation_row(connection, identity):
    return connection.execute(_SELECT + ' AND id=?', (identity,)).fetchone()


def operation_steps_rows(connection, operation):
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation['id'],),
    ).fetchall()
    if len(steps) != len(STEPS) or any(
        row['step_no'] != number
        or row['step_type'] != step
        or row['fixed_input'] != operation['fixed_input']
        or row['external_identity'] is not None
        for number, (row, step) in enumerate(zip(steps, STEPS, strict=True), 1)
    ):
        raise StorageUnavailable('Original seal steps differ')
    return steps


class SealRejected(Exception):
    def __init__(self, code):
        self.code = code


@dataclass(frozen=True)
class SealWork:
    identity: int
    pack_id: int
    version: int
    plan: dict
    basis: str
    targets: tuple


def _original_basis(connection, operation):
    fixed = strict_json_object(operation['fixed_input'])
    pack = _pack(connection, operation['resource_id'])
    if pack is None:
        raise StorageUnavailable('Original pack is missing')
    plan = _version(connection, pack['plan_version_id'])
    if plan is None:
        raise StorageUnavailable('Original plan is missing')
    if pack['status'] == 'REVOKED' or plan['status'] == 'REVOKED':
        raise SealRejected('TEST_ASSET_REVOKED')
    if (
        pack['status'] != 'DRAFT'
        or plan['status'] != 'PUBLISHED'
        or pack['state_version'] != operation['expected_state_version']
        or pack['state_version'] != fixed['expected_state_version']
        or plan['id'] != fixed['plan_version_id']
        or pack['version'] != fixed['pack_version']
        or plan_digest(plan) != fixed['plan_sha256']
    ):
        raise SealRejected('INVALID_STATE')
    try:
        original = basis_fingerprint(connection, plan)
    except CompileError as error:
        raise SealRejected('CONTENT_NOT_READY') from error
    if original != fixed['basis_fingerprint']:
        raise SealRejected('CONTENT_NOT_READY')
    return fixed, pack, plan


def original_targets(installation, fixed):
    if installation is None or _directory_token(installation.pack_directory) != fixed['pack_root']:
        raise SealRejected('CONFIG_NOT_READY')
    entries = {item.target.target_ref: item for item in installation.registered_targets}
    targets = []
    for row in fixed['targets']:
        entry = entries.get(row['target']['target_ref'])
        if entry is None or _target_token(entry) != row:
            raise SealRejected('CONFIG_NOT_READY')
        targets.append(entry.target)
    return tuple(targets)


def _start_step(connection, step, at):
    if step['status'] != 'PENDING':
        raise StorageUnavailable('Original seal step is already active')
    connection.execute(
        """UPDATE code_operation_steps SET status='RUNNING',started_at=?,last_observed_at=?
           WHERE operation_id=? AND step_no=?""",
        (at, at, step['operation_id'], step['step_no']),
    )


def _complete_step(connection, step, at, facts):
    encoded = canonical_input(facts)
    if step['status'] == 'SUCCEEDED' and step['result_ref'] == encoded:
        return
    if step['status'] != 'RUNNING' or step['result_ref'] is not None:
        raise StorageUnavailable('Original seal step facts differ')
    connection.execute(
        """UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,ended_at=?,last_observed_at=?
           WHERE operation_id=? AND step_no=?""",
        (encoded, at, at, step['operation_id'], step['step_no']),
    )


def _open_work(runtime, identity, installation):
    with runtime.database.transaction(write=True) as connection:
        operation = operation_row(connection, identity)
        if operation is None or operation['status'] not in ('PENDING', 'RUNNING'):
            return None
        steps = operation_steps_rows(connection, operation)
        if operation['status'] == 'PENDING':
            at = max(operation_time(None), operation['created_at'])
            connection.execute(
                "UPDATE code_operations SET status='RUNNING',started_at=? WHERE id=?",
                (at, identity),
            )
            _start_step(connection, steps[0], at)
    with runtime.database.transaction() as connection:
        operation = operation_row(connection, identity)
        fixed, pack, plan = _original_basis(connection, operation)
    return SealWork(
        identity,
        pack['id'],
        pack['version'],
        plan,
        fixed['basis_fingerprint'],
        original_targets(installation, fixed),
    )


def _record_compile(runtime, work, compiled):
    with runtime.database.transaction(write=True) as connection:
        operation = operation_row(connection, work.identity)
        steps = operation_steps_rows(connection, operation)
        fixed, _, _ = _original_basis(connection, operation)
        if (
            operation['status'] != 'RUNNING'
            or fixed['plan_sha256'] != compiled.plan_sha256
            or fixed['basis_fingerprint'] != compiled.basis_sha256
            or work.targets != compiled.targets
        ):
            raise StorageUnavailable('Original compiled closure changed')
        at = max(operation_time(None), operation['started_at'])
        _complete_step(connection, steps[0], at, {'plan_version_id': work.plan['id']})
        if steps[1]['status'] == 'PENDING':
            _start_step(connection, steps[1], at)
            steps = operation_steps_rows(connection, operation)
        _complete_step(connection, steps[1], at, {'sha256': compiled.sha256})
        if steps[2]['status'] == 'PENDING':
            _start_step(connection, steps[2], at)
        elif steps[2]['status'] != 'RUNNING':
            raise StorageUnavailable('Original seal file step differs')


def _save_seal(runtime, work, compiled, reference):
    with runtime.database.transaction(write=True) as connection:
        operation = operation_row(connection, work.identity)
        steps = operation_steps_rows(connection, operation)
        _, pack, _ = _original_basis(connection, operation)
        if operation['status'] != 'RUNNING' or (
            steps[1]['result_ref'] != canonical_input({'sha256': compiled.sha256})
        ):
            raise StorageUnavailable('Original compiled pack differs before final commit')
        at = max(operation_time(None), steps[2]['started_at'])
        check_set = entity_id(connection, EntityKind.CHECK_SET)
        check_version = entity_id(connection, EntityKind.CHECK_SET_VERSION)
        connection.execute(
            'INSERT INTO code_check_sets(id,name,created_at) VALUES(?,?,?)',
            (check_set, f'Testing pack {pack["id"]}', at),
        )
        content = compiled.check_set.value()
        connection.execute(
            """INSERT INTO code_check_set_versions(id,check_set_id,version,owner_module,
               protocol_version,items,coverage_plan,created_at)
               VALUES(?,?,1,'TESTING',?,?,?,?)""",
            (
                check_version,
                check_set,
                content['protocol_version'],
                compact(content['items']),
                compact(content['coverage_plan']),
                at,
            ),
        )
        saved = connection.execute(
            """UPDATE testing_pack_versions SET status='SEALED',check_set_version_id=?,
               content_ref=?,sha256=?,state_version=? WHERE id=? AND status='DRAFT'
               AND state_version=?""",
            (
                check_version,
                reference,
                compiled.sha256,
                increment(pack['state_version']),
                pack['id'],
                pack['state_version'],
            ),
        )
        if saved.rowcount != 1:
            raise StorageUnavailable('Original pack changed before sealing')
        _complete_step(connection, steps[2], at, {'sha256': compiled.sha256})
        _start_step(connection, steps[3], at)
        last = operation_steps_rows(connection, operation)[-1]
        _complete_step(
            connection,
            last,
            at,
            {'test_pack_version_id': pack['id'], 'check_set_version_id': check_version},
        )
        connection.execute(
            "UPDATE code_operations SET status='SUCCEEDED',ended_at=? WHERE id=?",
            (at, operation['id']),
        )


def _fail(runtime, identity, code):
    with runtime.database.transaction(write=True) as connection:
        operation = operation_row(connection, identity)
        if operation is None or operation['status'] != 'RUNNING':
            return
        steps = operation_steps_rows(connection, operation)
        current = next((step for step in steps if step['status'] == 'RUNNING'), None)
        if current is None:
            raise StorageUnavailable('Original seal operation has no active step')
        at = max(operation_time(None), current['started_at'])
        connection.execute(
            """UPDATE code_operation_steps SET status='FAILED',ended_at=?,last_observed_at=?
               WHERE operation_id=? AND step_no=?""",
            (at, at, identity, current['step_no']),
        )
        connection.execute(
            "UPDATE code_operations SET status='FAILED',ended_at=?,failure_code=? WHERE id=?",
            (at, code, identity),
        )


def advance_pending_pack_seals(runtime, cancelled):
    """Advance one original action under the lifespan's existing process ownership."""
    if _installation(runtime) is None or cancelled():
        return False
    with runtime.database.transaction() as connection:
        original = connection.execute(
            _SELECT + " AND status IN ('PENDING','RUNNING') ORDER BY id LIMIT 1"
        ).fetchone()
    if original is None:
        return False
    identity = original['id']
    deadline = monotonic() + 30

    def checkpoint():
        if cancelled() or monotonic() >= deadline:
            raise CheckResourceError('TESTING_PACK_SEAL_INTERRUPTED')

    try:
        installation = _installation(runtime)
        work = _open_work(runtime, identity, installation)
        if work is None:
            return False
        compiled = compile_pack(
            work.plan,
            work.targets,
            pack_id=work.pack_id,
            version=work.version,
            basis_sha256=work.basis,
        )
        _record_compile(runtime, work, compiled)
        with ExitStack() as files:
            with hold_compiler_sources(
                installation, compiled.targets, deadline=deadline, cancelled=cancelled
            ):
                reference = files.enter_context(
                    hold_published_pack(installation, compiled, identity, checkpoint)
                )
            checkpoint()
            _save_seal(runtime, work, compiled, reference)
    except SealRejected as error:
        _fail(runtime, identity, error.code)
    except (CompileError, ValueError):
        _fail(runtime, identity, 'CHECK_CONFIGURATION_INVALID')
    except RESOURCE_ERRORS:
        if cancelled():
            return False
        _fail(runtime, identity, 'CONTENT_NOT_READY')
    except (OSError, sqlite3.Error, StorageUnavailable):
        # The original pack and immutable finished members remain eligible for
        # exact observation on a later tick. No replacement action is accepted.
        return False
    return True
