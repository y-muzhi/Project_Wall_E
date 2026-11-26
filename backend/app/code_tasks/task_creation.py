"""Fixed Coding task admission and its original 201 response."""

import sqlite3

from backend.app.infrastructure.command_receipts import Rejection, read_registered_replay
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success
from backend.app.infrastructure.identifiers import CapacityExhausted, EntityKind, entity_id
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.infrastructure.review_schema import supports_review_layout
from backend.app.shared.code_errors import empty_conflict
from backend.app.shared.command_execution import ConfigurationNotReady, operation_time

from .authorization_scope import profile_scope_error, resource_scope_error
from .authorizations import project_grant
from .configuration_identities import require_schema
from .execution_profile_resources import reference_error
from .execution_profile_versions import _project as project_profile
from .initial_task_view import initial_task_view
from .repository_baseline_query import BaselineQueryResult, BaselineSnapshotMissing
from .repository_baseline_validation import read_registered_baseline
from .repository_registration_worker import RepositoryRegistrationWorker
from .repository_snapshot_reads import GUARD_ERRORS, SOURCE_ERRORS
from .task_basis import fixed_design_basis

TASK_INPUT_FIELDS = (
    'design_revision_id',
    'material_refs',
    'repository_id',
    'base_snapshot_id',
    'target_branch',
    'execution_profile_version_id',
    'authorization_id',
    'budget_limit_cny',
)


def _conflict(code, kind, identity, **facts):
    return Rejection(
        code,
        {**empty_conflict(), 'related_entity_kind': kind, 'related_entity_id': identity, **facts},
    )


def _authorized_profile(connection, runtime, request):
    row = connection.execute(
        'SELECT * FROM code_execution_profile_versions WHERE id=?',
        (request.execution_profile_version_id,),
    ).fetchone()
    grant_row = connection.execute(
        'SELECT * FROM code_authorizations WHERE id=?', (request.authorization_id,)
    ).fetchone()
    if row is None or grant_row is None:
        return Rejection('NOT_FOUND', None)
    grant = project_grant(grant_row)
    denied = Rejection(
        'AUTHORIZATION_NOT_APPLICABLE', {'task_id': None, 'authorization_id': grant['id']}
    )
    if (
        grant['status'] != 'APPROVED_UNBOUND'
        or grant['profile_version_id'] != request.execution_profile_version_id
    ):
        return denied
    snapshots = {}
    profile = project_profile(row, connection, runtime.catalog, snapshots)
    resources = snapshots['execution']
    if reference_error(connection, profile, resources) is not None:
        raise ConfigurationNotReady('Q20-CONFIG')
    if profile_scope_error(grant['scope'], profile) or resource_scope_error(
        grant['scope'], resources
    ):
        return denied
    return profile


def _persist_task(connection, runtime, request, verified, check_active):
    check_active()
    if request.normalized_budget == '0.000000' and not supports_review_layout(connection):
        raise ConfigurationNotReady('Q20-CONFIG')
    design = fixed_design_basis(
        connection, request.document_id, request.design_revision_id, request.material_refs
    )
    if isinstance(design, Rejection):
        return design
    active = connection.execute(
        "SELECT id FROM code_tasks WHERE document_id=? AND status NOT IN ('COMPLETED','TERMINATED')",
        (request.document_id,),
    ).fetchone()
    if active is not None:
        return _conflict('ACTIVE_TASK_EXISTS', 'TASK', active['id'], task_id=active['id'])
    snapshot = read_registered_baseline(connection, request.base_snapshot_id)
    if snapshot is None or snapshot['repository_id'] != request.repository_id:
        return Rejection('NOT_FOUND', None)
    if dict(snapshot) != verified.snapshot:
        raise StorageUnavailable('Original verified baseline differs in creation transaction')
    profile = _authorized_profile(connection, runtime, request)
    if isinstance(profile, Rejection):
        return profile

    try:
        task_id = entity_id(connection, EntityKind.CODE_TASK)
    except CapacityExhausted:
        return Rejection('PRECONDITION_FAILED', empty_conflict())
    now = operation_time(None)
    connection.execute(
        """INSERT INTO code_tasks(
           id,requirement_id,document_id,design_revision_id,repository_id,base_snapshot_id,
           target_branch,execution_profile_version_id,authorization_id,budget_limit_cny,
           status,phase,state_version,control_generation,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,'PENDING','PREPARING',1,1,?,?)""",
        (
            task_id,
            design.requirement_id,
            request.document_id,
            request.design_revision_id,
            request.repository_id,
            request.base_snapshot_id,
            request.target_branch,
            request.execution_profile_version_id,
            request.authorization_id,
            request.normalized_budget,
            now,
            now,
        ),
    )
    connection.executemany(
        'INSERT INTO code_task_materials(task_id,document_id,revision_id) VALUES(?,?,?)',
        [(task_id, item['document_id'], item['revision_id']) for item in request.material_refs],
    )
    bound = connection.execute(
        """UPDATE code_authorizations SET task_id=?,status='BOUND_PENDING_APPLY'
           WHERE id=? AND status='APPROVED_UNBOUND' AND task_id IS NULL AND profile_version_id=?""",
        (task_id, request.authorization_id, request.execution_profile_version_id),
    )
    if bound.rowcount != 1:
        raise StorageUnavailable('Original authorization binding changed inside write transaction')
    row = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
    data = initial_task_view(row, request.material_refs, design.differences, profile['ready'])
    check_active()
    return Success({'code': 'CREATED', 'data': data, 'details': None}, 201)


def _failure(code, details=None):
    return {'code': code, 'data': None, 'details': details}


def create_fixed_task(runtime, request, worker, cancelled):
    require_schema(runtime)
    executor = runtime.commands()
    scope, business_input = request.command.scope, request.business_input()

    def save(operation):
        return executor.execute(scope, business_input, operation).result

    def finish(verified, check_active):
        if type(verified) is not BaselineQueryResult:
            raise StorageUnavailable('Original baseline query did not return verified evidence')
        return save(
            lambda connection: _persist_task(connection, runtime, request, verified, check_active)
        )

    try:
        replay = read_registered_replay(executor, scope, business_input)
        if replay is not None:
            return replay.result
        with runtime.database.transaction() as connection:
            snapshot = read_registered_baseline(connection, request.base_snapshot_id)
        if snapshot is None or snapshot['repository_id'] != request.repository_id:
            return save(lambda connection: Rejection('NOT_FOUND', None))
        if type(worker) is not RepositoryRegistrationWorker:
            raise ConfigurationNotReady('Q20-WINDOWS', 'Q20-GIT')
        try:
            return worker.read_snapshot(
                request.base_snapshot_id, cancelled=cancelled, finish=finish
            )
        except SOURCE_ERRORS:
            if cancelled.is_set():
                raise ConfigurationNotReady('Q20-WINDOWS', 'Q20-GIT')
            return save(
                lambda connection: _conflict(
                    'CONTENT_NOT_READY', 'SNAPSHOT', request.base_snapshot_id
                )
            )
        except BaselineSnapshotMissing:
            return save(lambda connection: Rejection('NOT_FOUND', None))
        except GUARD_ERRORS as error:
            # A deadline or lost connection can follow the short commit. Prefer
            # the durable original if available and otherwise leave the key usable.
            replay = read_registered_replay(executor, scope, business_input)
            if replay is not None:
                return replay.result
            raise ConfigurationNotReady('Q20-WINDOWS', 'Q20-GIT') from error
    except ConfigurationNotReady as error:
        return _failure(error.code, error.details)
    except ConfigInvalid:
        return _failure('CONFIG_NOT_READY', {'capability_codes': ['Q20-CONFIG']})
    except (StorageUnavailable, sqlite3.Error):
        return _failure('STORAGE_UNAVAILABLE', {'capability_codes': ['DATABASE']})
