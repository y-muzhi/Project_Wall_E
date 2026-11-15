"""Accept an original independent Testing run only with a complete execution path."""

from contextlib import ExitStack
from time import monotonic

from backend.app.code_tasks.configuration_identities import require_schema
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.shared.command_execution import ConfigurationNotReady, execute_idempotent
from backend.app.shared.validation import MAX_SAFE_INTEGER

from .assets import NOT_FOUND
from .cli_plan import read_fixed_profile, select_cli_plan
from .pack_compile import CompileError
from .pack_definitions import hold_compiled_pack_assets
from .pack_seal import RESOURCE_ERRORS
from .pack_validation import original_validation
from .plan_content import BASIS_FIELDS
from .plans import _version
from .reports import _held_pack
from .run_records import accept_cli_run
from .run_target import fixed_run_target
from .tasks import (
    _fixed_target,
    grant_rejection,
    matching_product_assets,
    materials_for,
    read_task_row,
    task_conflict,
)


def _authorized(connection, task):
    grant = connection.execute(
        "SELECT * FROM testing_authorizations WHERE id=? AND profile_version_id=? AND status='EFFECTIVE'",
        (task['authorization_id'], task['profile_version_id']),
    ).fetchone()
    if grant is None:
        return False
    if task['kind'] == 'PRODUCT':
        return grant['scope_kind'] == 'TASK' and grant['testing_task_id'] == task['id']
    return (
        grant['scope_kind'] == 'PACK_VALIDATION'
        and grant['validation_id'] == task['validation_id']
        and grant['budget_limit_cny'] == '0.000000'
    )


def _validation_assets(connection, task, plan, pack):
    original = original_validation(connection, task['validation_id'])
    if original is None:
        raise StorageUnavailable('Original Testing validation scope is missing')
    group, operation, fixed, children = original
    if (
        plan['status'] != 'PUBLISHED'
        or pack['status'] != 'SEALED'
        or pack['plan_version_id'] != plan['id']
        or group['test_pack_version_id'] != pack['id']
        or group['profile_version_id'] != task['profile_version_id']
        or group['result'] not in ('PENDING', 'RUNNING')
        or operation['status'] not in ('PENDING', 'RUNNING')
        or fixed['pack_sha256'] != pack['sha256']
        or not any(child['id'] == task['id'] for child in children)
    ):
        return task_conflict('TEST_SOURCE_MISMATCH', task)
    return None


def _inspect(
    connection, catalog, identity, expected, runtime_resources, *, request=None, assets=None
):
    task = read_task_row(connection, identity)
    if task is None:
        return NOT_FOUND
    if assets is not None:
        task = {**dict(task), **assets}
    if task['status'] in ('COMPLETED', 'TERMINATED'):
        return task_conflict('TASK_ENDED', task)
    if task['state_version'] != expected:
        return task_conflict('VERSION_CONFLICT', task)
    if (
        task['status']
        not in (('DRAFT', 'READY') if assets is None else ('DRAFT', 'READY', 'WAITING'))
        or task['state_version'] >= MAX_SAFE_INTEGER - 1
        or task['stop_requested_at'] is not None
        or task['active_operation_id'] is not None
        or task['current_verification_id'] is not None
        or task['plan_version_id'] is None
        or task['test_pack_version_id'] is None
        or connection.execute(
            "SELECT 1 FROM code_operations WHERE testing_task_id=? AND operation_type='RUN_TEST'",
            (task['id'],),
        ).fetchone()
        is not None
    ):
        return task_conflict('INVALID_STATE', task)
    plan = _version(connection, task['plan_version_id'])
    pack = connection.execute(
        'SELECT * FROM testing_pack_versions WHERE id=?', (task['test_pack_version_id'],)
    ).fetchone()
    if plan is None or pack is None:
        raise StorageUnavailable('Fixed Testing assets are missing')
    if plan['status'] == 'REVOKED' or pack['status'] == 'REVOKED':
        return task_conflict(
            'TEST_ASSET_REVOKED', task, entity='PLAN', identity=task['plan_version_id']
        )
    if assets is None and task['status'] != 'READY':
        return task_conflict('INVALID_STATE', task)
    if not _authorized(connection, task):
        return grant_rejection(task['authorization_id'])
    fixed = {**dict(task), 'material_refs': materials_for(connection, task['id'])}
    if any(fixed[key] != plan[key] for key in BASIS_FIELDS):
        return task_conflict('TEST_SOURCE_MISMATCH', task)
    problem = (
        matching_product_assets(connection, fixed)
        if task['kind'] == 'PRODUCT'
        else _validation_assets(connection, task, plan, pack)
    )
    if problem is not None:
        return problem
    source_error = _fixed_target(connection, fixed)
    if source_error is not None:
        return source_error
    installation = getattr(catalog, 'testing_assets', None)
    if installation is None:
        raise ConfigurationNotReady('Q20-CHECKS')
    try:
        with ExitStack() as held:
            compiled = held.enter_context(
                hold_compiled_pack_assets(connection, installation, pack, deadline=monotonic() + 5)
            )
            if runtime_resources is None or (
                task['target_kind'] == 'SNAPSHOT' and not runtime_resources.snapshots
            ):
                raise ConfigurationNotReady('Q20-CHECKS')
            profile = read_fixed_profile(connection, task['profile_version_id'])
            selection = select_cli_plan(
                compiled,
                profile,
                runtime_resources.admissions,
                runtime_resources.browser_admissions,
            )
            if selection is None:
                raise ConfigurationNotReady('Q20-CHECKS')
            if task['kind'] == 'PRODUCT' and not _held_pack(connection, catalog, pack, held=held):
                return task_conflict('CONTENT_NOT_READY', task)
            target = fixed_run_target(connection, fixed)
            if request is None:
                return None
            return accept_cli_run(
                connection,
                request,
                fixed,
                pack,
                compiled,
                selection,
                runtime_resources.owner,
                target,
            )
    except (OSError, CompileError, *RESOURCE_ERRORS):
        return task_conflict('CONTENT_NOT_READY', task)


def run_reason(connection, catalog, task, runtime_resources, *, assets=None):
    if runtime_resources is None:
        return 'EXECUTION_NOT_READY'
    try:
        outcome = _inspect(
            connection, catalog, task['id'], task['state_version'], runtime_resources, assets=assets
        )
    except ConfigurationNotReady:
        return 'EXECUTION_NOT_READY'
    if outcome is None:
        return None
    return (
        'AUTHORIZATION_NOT_READY'
        if outcome.result.get('code') == 'AUTHORIZATION_NOT_APPLICABLE'
        else 'ASSET_NOT_READY'
    )


def run_testing_task(runtime, request, *, runtime_resources=None):
    require_schema(runtime)
    return execute_idempotent(
        runtime.commands(),
        request.command.route.capability_id,
        request,
        lambda connection: _inspect(
            connection,
            runtime.catalog,
            request.identity,
            request.expected,
            runtime_resources,
            request=request,
        ),
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset({'CONFIG_NOT_READY'}),
    )
