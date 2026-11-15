"""Read-only CHECK_CONDITIONS in the original START scope."""

from time import monotonic

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.guard_task_sources import TaskSourceError, TaskSourcePins
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.opencode_binary import OpenCodeBinaryError, open_opencode_binary
from backend.app.infrastructure.opencode_managed_config import opencode_managed_source_clear
from backend.app.infrastructure.opencode_protocol_source import (
    OpenCodeProtocolSourceError,
    verify_opencode_protocol_source,
)
from backend.app.infrastructure.opencode_runtime_bundle import (
    OpenCodeRuntimeBundleError,
    verify_opencode_runtime_bundle,
)
from backend.app.infrastructure.windows_config_source import ConfigReadError
from backend.app.infrastructure.windows_executable_pin import ExecutablePinError
from backend.app.infrastructure.windows_job import probe_lpac_creation_attributes
from backend.app.infrastructure.windows_local_paths import FileIdentity, PathBoundaryError
from backend.app.infrastructure.windows_private_package import PackageSecurityError
from backend.app.infrastructure.windows_wfp import probe_wfp_ale_layers
from backend.app.shared.command_execution import ConfigurationNotReady, operation_time
from backend.app.shared.validation import strict_integer, strict_json_object

from .costs import format_money, parse_money
from .task_basis import TaskBasisUnavailable
from .task_basis_package import read_basis_package
from .task_budget import start_budget_versions
from .task_start import _check_start_readiness, original_start_steps
from .task_start_basis import _active, _original_basis
from .workspace_materialization import (
    WorkspaceMaterializationError,
    read_workspace_manifest,
    verify_workspace_tree,
)


class _Fenced(RuntimeError):
    pass


def _candidate(connection):
    return connection.execute(
        """SELECT o.id FROM code_operations o JOIN code_tasks t ON t.id=o.task_id
           JOIN code_operation_steps basis ON basis.operation_id=o.id AND basis.step_no=2
           JOIN code_operation_steps checks ON checks.operation_id=o.id AND checks.step_no=3
           WHERE o.resource_kind='TASK' AND o.operation_type='START' AND o.status='RUNNING'
           AND basis.status='SUCCEEDED' AND checks.status='PENDING'
           AND t.status='PENDING' AND t.phase='PREPARING' AND t.stop_requested_at IS NULL
           ORDER BY o.id LIMIT 1"""
    ).fetchone()


def _state(connection, operation_id, parent):
    original = _original_basis(connection, operation_id)
    try:
        _active(original, parent, step_status='SUCCEEDED')
    except TaskBasisUnavailable as error:
        raise _Fenced('Original START conditions are fenced') from error
    operation, task, basis, allocation = original
    _, steps = original_start_steps(connection, operation)
    checks = steps[2]
    if not start_budget_versions(connection, task, operation, offset=2):
        raise _Fenced('Original START conditions version differs')
    if checks['status'] != 'PENDING' or any(
        checks[field] is not None
        for field in (
            'external_identity',
            'result_ref',
            'started_at',
            'ended_at',
            'last_observed_at',
        )
    ):
        raise _Fenced('Original START conditions were already recorded')
    fixed = {
        field: task[field]
        for field in (
            'control_generation',
            'workspace_id',
            'execution_profile_version_id',
            'authorization_id',
        )
    }
    return (
        fixed,
        task,
        allocation,
        steps[0]['result_ref'],
        basis['external_identity'],
        basis['result_ref'],
        basis['ended_at'],
    )


def _limits(connection, profile_id):
    row = connection.execute(
        'SELECT limits FROM code_execution_profile_versions WHERE id=?', (profile_id,)
    ).fetchone()
    if row is None:
        raise StorageUnavailable('Original START limit profile is unavailable')
    try:
        values = strict_json_object(row['limits'])
        return {
            name: strict_integer(values[name], name)
            for name in (
                'max_capture_seconds',
                'max_snapshot_files',
                'max_snapshot_bytes',
                'max_file_bytes',
            )
        }
    except (ValueError, TypeError, KeyError) as error:
        raise StorageUnavailable('Original START content limits differ') from error


def _verify_workspace(parent, allocation, receipt, checkpoint, limits):
    source = read_workspace_manifest(parent, allocation, receipt, checkpoint, limits)
    actual = verify_workspace_tree(source.path, source.directory, source.entries, checkpoint)
    if actual != source.directory:
        raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_PUBLISHED_IDENTITY_DIFFERS')


def _capabilities(
    connection, runtime, task, system_config_clear, bundle_verified, *, launch_available
):
    codes = set() if launch_available else {'Q20-WINDOWS', 'Q20-OC'}
    if not system_config_clear or not bundle_verified:
        codes.add('Q20-CONFIG')
    try:
        _check_start_readiness(connection, runtime.catalog, task, True)
    except ConfigurationNotReady as error:
        codes.update(error.details['capability_codes'])
    budget = parse_money(task['budget_limit_cny'], 'budget_limit_cny')
    if budget <= 0 or format_money(budget) != task['budget_limit_cny']:
        codes.add('Q20-CONFIG')
    if (
        connection.execute(
            'SELECT 1 FROM code_task_reservations WHERE task_id=? LIMIT 1', (task['id'],)
        ).fetchone()
        is not None
    ):
        codes.add('Q20-MODEL')
    return sorted(codes)


def advance_start_conditions(
    runtime, parent, *, cancelled, executor_binary=None, launch_installation=None
):
    """Persist content and installation conditions before any instance allocation."""
    if cancelled():
        return False
    runtime.commands()._owned()
    with runtime.database.transaction() as connection:
        candidate = _candidate(connection)
        if candidate is None:
            return False
        operation_id = candidate['id']

    def state(connection):
        if cancelled():
            raise _Fenced('Original START conditions were cancelled')
        return _state(connection, operation_id, parent)

    try:
        with runtime.database.transaction() as connection:
            original = state(connection)
            profile_id = original[0]['execution_profile_version_id']
            limits = _limits(connection, profile_id)
            executor = None
            if executor_binary is not None:
                stored = connection.execute(
                    'SELECT executor FROM code_execution_profile_versions WHERE id=?', (profile_id,)
                ).fetchone()
                executor = strict_json_object(stored['executor'])
        fixed, _, allocation, workspace, binding, basis, basis_at = original
        deadline = monotonic() + limits['max_capture_seconds']

        def checkpoint():
            if monotonic() >= deadline:
                raise WorkspaceMaterializationError('ORIGINAL_START_CONTENT_CHECK_TIMED_OUT')
            with runtime.database.transaction() as connection:
                current = state(connection)
                if current[0] != fixed or current[2:] != original[2:]:
                    raise _Fenced('Original START conditions changed')

        content_ready = False
        try:
            checkpoint()
            workspace_receipt = strict_json_object(workspace)
            basis_seal = strict_json_object(basis)['seal']
            with TaskSourcePins(
                allocation.parent,
                allocation.nonce,
                workspace=FileIdentity(**workspace_receipt['directory']),
                workspace_tree=FileIdentity(**workspace_receipt['tree_record']['file']),
                basis_seal=FileIdentity(**basis_seal['file']),
            ) as sources:
                _verify_workspace(parent, allocation, workspace, checkpoint, limits)
                read_basis_package(parent, strict_json_object(binding), basis_seal, checkpoint)
                sources.verify()
        except (
            TaskBasisUnavailable,
            TaskSourceError,
            WorkspaceMaterializationError,
            ConfigReadError,
            PackageSecurityError,
            PathBoundaryError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
        ) as error:
            if getattr(error, 'retained_owner', None) is not None:
                raise
        else:
            content_ready = True
        binary_verified = False
        if executor is not None:
            try:
                checkpoint()
                with open_opencode_binary(
                    executor_binary, executor, deadline=deadline, cancelled=cancelled
                ) as pin:
                    pin.verify()
                    checkpoint()
            except (
                OpenCodeBinaryError,
                ExecutablePinError,
                WorkspaceMaterializationError,
                PathBoundaryError,
                ConfigReadError,
                OSError,
                ValueError,
                TypeError,
                KeyError,
            ) as error:
                if getattr(error, 'retained_owner', None) is not None:
                    raise
            else:
                binary_verified = True
        protocol_verified = False
        if executor is not None and executor_binary.openapi is not None:
            try:
                checkpoint()
                if executor_binary.matches(executor):
                    verify_opencode_protocol_source(
                        executor_binary.openapi,
                        deadline=deadline,
                        cancelled=cancelled,
                    )
                    checkpoint()
                    protocol_verified = True
            except (
                OpenCodeProtocolSourceError,
                WorkspaceMaterializationError,
                PathBoundaryError,
                ConfigReadError,
                OSError,
                ValueError,
                TypeError,
                KeyError,
            ) as error:
                if getattr(error, 'retained_owner', None) is not None:
                    raise
        bundle_verified = False
        if executor is not None and executor_binary.bundle is not None:
            try:
                checkpoint()
                if executor_binary.matches(executor):
                    verify_opencode_runtime_bundle(
                        executor_binary.bundle,
                        executor['runtime_bundle_ref'],
                        deadline=deadline,
                        cancelled=cancelled,
                    )
                    checkpoint()
                    bundle_verified = True
            except (
                OpenCodeRuntimeBundleError,
                WorkspaceMaterializationError,
                PathBoundaryError,
                ConfigReadError,
                OSError,
                ValueError,
                TypeError,
                KeyError,
            ) as error:
                if getattr(error, 'retained_owner', None) is not None:
                    raise
        system_config_clear = opencode_managed_source_clear()
        lpac_attributes_available = probe_lpac_creation_attributes()
        wfp_layers_readable = probe_wfp_ale_layers()
        launch_available = (
            launch_installation is not None
            and launch_installation.matches(executor)
            and binary_verified
            and protocol_verified
            and bundle_verified
            and lpac_attributes_available
        )
        with runtime.database.transaction(write=True) as connection:
            current = state(connection)
            if current[0] != fixed or current[2:] != original[2:]:
                raise _Fenced('Original START conditions changed before saving')
            codes = _capabilities(
                connection,
                runtime,
                current[1],
                system_config_clear,
                bundle_verified,
                launch_available=launch_available,
            )
            if not content_ready:
                codes = sorted(set(codes) | {'Q20-CONTENT'})
            failure = None
            if codes:
                failure = 'CONFIG_NOT_READY' if content_ready else 'CONTENT_NOT_READY'
            now = max(operation_time(None), basis_at, current[1]['updated_at'])
            report = canonical_input(
                {
                    'fixed_content_verified': content_ready,
                    'capability_codes': codes,
                    'system_config_clear': system_config_clear,
                    'executor_binary_verified': binary_verified,
                    'executor_protocol_source_verified': protocol_verified,
                    'executor_runtime_bundle_verified': bundle_verified,
                    'lpac_creation_attributes_available': lpac_attributes_available,
                    'wfp_local_ale_layers_readable': wfp_layers_readable,
                    **({'runtime_launch_admission': True} if failure is None else {}),
                }
            )
            connection.execute(
                """UPDATE code_operation_steps SET status=?,result_ref=?,
                   started_at=?,ended_at=?,last_observed_at=? WHERE operation_id=? AND step_no=3""",
                ('SUCCEEDED' if failure is None else 'FAILED', report, now, now, now, operation_id),
            )
            if failure is not None:
                connection.execute(
                    "UPDATE code_operations SET status='FAILED',failure_code=?,ended_at=? WHERE id=?",
                    (failure, now, operation_id),
                )
    except _Fenced:
        return False
    return True
