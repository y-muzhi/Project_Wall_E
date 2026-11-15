"""Prove a Testing cancellation from the complete original command cohort."""

from backend.app.infrastructure.check_runner_bundle import valid_sha256
from backend.app.shared.validation import strict_json_object

from .run_ownership import read_original_run

RUN_POLICY = 'TEST20-CLI-STOP-1'


def _closure(connection, case, run):
    command = case.command
    if command['ended_at'] is None or command['status'] in ('PENDING', 'RUNNING'):
        return None
    observations = connection.execute(
        """SELECT * FROM code_runtime_observations WHERE testing_task_id=? AND task_id IS NULL
           AND operation_id=? AND command_id=? AND control_generation=?
           AND kind IN ('STOP','CLEANUP') ORDER BY id""",
        (run.task['id'], run.operation['id'], command['id'], run.operation['control_generation']),
    ).fetchall()
    if [item['kind'] for item in observations] != ['STOP', 'CLEANUP']:
        return None
    binding = command['runtime_binding']
    binding_ref = None if binding is None else strict_json_object(binding)['guard_run_ref']
    for observed in observations:
        reference = observed['evidence_ref']
        if (
            observed['result'] != 'VERIFIED'
            or observed['instance_id'] is not None
            or observed['runtime_binding_ref'] != binding_ref
            or observed['active_process_count'] != 0
            or not command['ended_at'] <= observed['observed_at'] <= run.verification['ended_at']
            or not reference.startswith('testing-check:sha256:')
            or not valid_sha256(reference.removeprefix('testing-check:sha256:'))
        ):
            return None
    if observations[0]['evidence_ref'] != observations[1]['evidence_ref']:
        return None
    return {
        'command_id': command['id'],
        'runtime_binding_ref': binding_ref,
        'stop_observation_id': observations[0]['id'],
        'cleanup_observation_id': observations[1]['id'],
    }


def original_run_stop_scope(connection, task, operation, fixed):
    prior = fixed['prior_operation_id']
    if prior is None:
        return None
    row = connection.execute(
        """SELECT fixed_input FROM code_operations WHERE id=? AND task_id IS NULL
           AND testing_task_id=? AND operation_type='RUN_TEST' AND status='CANCELLED'""",
        (prior, task['id']),
    ).fetchone()
    if row is None or 'facts' not in strict_json_object(row['fixed_input']):
        return None
    run = read_original_run(connection, prior)
    if (
        run is None
        or run.operation['control_generation'] > fixed['prior_generation']
        or fixed['prior_generation'] + 1 != operation['control_generation']
        or run.verification['status'] != 'CANCELLED'
        or run.verification['ended_at'] is None
        or run.verification['stop_status'] != 'VERIFIED'
        or run.verification['cleanup_status'] != 'VERIFIED'
    ):
        return None
    foreign = connection.execute(
        'SELECT 1 FROM code_commands WHERE testing_task_id=? AND operation_id<>?',
        (task['id'], prior),
    ).fetchone()
    unsettled = connection.execute(
        """SELECT 1 FROM code_task_reservations WHERE testing_task_id=?
           AND status IN ('RESERVED','UNKNOWN')""",
        (task['id'],),
    ).fetchone()
    if foreign is not None or unsettled is not None:
        return None
    closures = [
        _closure(connection, member, run)
        for case in run.cases
        for member in (case, *case.applications)
    ]
    if not closures or any(value is None for value in closures):
        return None
    return {
        'policy': RUN_POLICY,
        'testing_task_id': task['id'],
        'operation_id': operation['id'],
        'closed_generation': operation['control_generation'],
        'prior_generation': fixed['prior_generation'],
        'run_operation_id': prior,
        'command_closures': closures,
    }
