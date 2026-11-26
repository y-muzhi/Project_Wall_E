"""Retire the exact prepared start before it has dispatched an application."""

import os

from backend.app.infrastructure.environment_admission import preparation_retirement
from backend.app.infrastructure.environment_files import canonical, digest, require
from backend.app.infrastructure.environment_lock import NativeEnvironmentFiles

from .attachment_observation import machine_clock
from .operation_contract import RESOURCE, path_reference
from .runtime_observation import SYSTEMCTL, trusted_executable, unit_facts
from .runtime_preparation_process import (
    close_active_preparation,
    preparation_stop_intent,
    preparation_stopped,
)
from .runtime_start import (
    SYSTEMD_RUN,
    control_directory,
    finish_preparation,
    launch_preparation_unit,
    observe_preparation,
    preparation_baseline,
    preparation_command,
    preparation_properties,
    preparation_record,
    preparation_reference,
    preparation_unit_quiet,
    prepare_command,
    record_at,
    stop_preparation_unit,
    verify_accounts_and_paths,
    write_record,
)

RETIRED = 'MANAGED_START_PREPARATION_RETIRED'
UNVERIFIED = 'MANAGEMENT_PREPARATION_CANCEL_UNVERIFIED'


def no_application(environment, unit):
    require(
        unit_facts(unit)['LoadState'] == 'not-found'
        and preparation_unit_quiet(unit)
        and not os.path.lexists(environment.path('runtime') / 'walle.sock'),
        UNVERIFIED,
    )


def cancellation_name(operation):
    return 'cancel-preparation-' + operation + '.v1.json'


def preparation_cancel_binding(fd, common, boot, key, baseline):
    operation = common['start_operation_id']
    preparation = record_at(fd, 'prepare-' + operation + '.v1.json')
    binding = {
        **common,
        'boot_id': boot,
        'control_key': key,
        'baseline_sha256': digest(canonical(baseline)),
        'preparation_sha256': None,
    }
    if preparation is None:
        return binding
    require(
        all(preparation.get(field) == value for field, value in common.items())
        and preparation.get('boot_id') == boot,
        UNVERIFIED,
    )
    if preparation['state'] == 'ISSUED':
        stopped = preparation_stopped(fd, preparation, key)
        require(stopped is not None, UNVERIFIED)
        binding['preparation_stop_sha256'] = digest(canonical(stopped))
    else:
        require(preparation['state'] == 'RELEASED', UNVERIFIED)
    binding['preparation_sha256'] = digest(canonical(preparation))
    return binding


def retirement_outcome(environment, native, app_unit, baseline):
    operation = baseline['start_operation_id']
    with environment.lock(native) as lock, control_directory(environment) as fd:
        no_application(environment, app_unit)
        current, target, state = preparation_retirement(
            environment,
            fd,
            operation,
            baseline['control_operation_id'],
            baseline['control_revision'],
            baseline['control_sha256'],
        )
        lock.assert_owned()
    return current == target, state, target['control_revision']


def run_retirement(fd, binding, args, plan, environment, launcher, baseline, app_unit):
    operation = baseline['start_operation_id']
    unit = f'walle-retire-{baseline["environment_id"]}-{operation}.service'
    native = NativeEnvironmentFiles(args.root)
    completed, state, revision = retirement_outcome(environment, native, app_unit, baseline)
    command = preparation_command(args, plan, environment, launcher, 'retire-start')
    command.extend(
        (
            '--before-control-sha256',
            baseline['control_sha256'],
            '--before-operation-id',
            baseline['control_operation_id'],
            '--before-revision',
            str(baseline['control_revision']),
        )
    )
    command_sha = digest(canonical({'argv': command}))
    properties = preparation_properties(plan, command_sha)
    dispatch = {**binding, 'unit': unit, 'command_sha256': command_sha}
    dispatch_name = 'retire-issued-' + operation + '.v1.json'
    issued = record_at(fd, dispatch_name)
    require(state != 'RETIRED' or binding['preparation_sha256'] is not None, UNVERIFIED)
    if issued is None:
        require(not completed or state == 'UNCHANGED', UNVERIFIED)
        require(
            unit_facts(unit)['LoadState'] == 'not-found' and preparation_unit_quiet(unit),
            UNVERIFIED,
        )
        if not completed:
            write_record(fd, dispatch_name, dispatch)
            launch_preparation_unit(unit, properties, command)
    else:
        require(issued == dispatch, UNVERIFIED)
    if not preparation_unit_quiet(unit):
        invocation = observe_preparation(unit, properties)
        stop_preparation_unit(unit, properties, invocation)
    completed, outcome, control_revision = retirement_outcome(
        environment, native, app_unit, baseline
    )
    require(
        completed
        and outcome == state
        and control_revision == revision
        and preparation_unit_quiet(unit),
        UNVERIFIED,
    )
    return outcome, control_revision


def settle_preparation(fd, args, entry, common, boot, key, plan, environment, command, *, recorded):
    expected = preparation_reference(common, boot, command)
    unit = expected['unit']
    prepare = preparation_record(fd, expected)
    if prepare is None:
        require(
            unit_facts(unit)['LoadState'] == 'not-found' and preparation_unit_quiet(unit),
            UNVERIFIED,
        )
        return unit, None
    _, prior_stop = preparation_stop_intent(fd, prepare, key)
    if prior_stop is not None or (
        prepare['state'] == 'ISSUED' and unit_facts(unit).get('ActiveState') == 'activating'
    ):
        if recorded:
            closed = preparation_stopped(fd, prepare, key)
        else:
            manifest, _ = entry['verify_runtime'](args.root, args.sha256)
            executable = args.root / manifest['python']['executable_ref']
            closed = close_active_preparation(
                fd, prepare, key, plan, environment, command, executable
            )
        require(closed is not None, UNVERIFIED)
        invocation = closed['invocation_id']
        require(preparation_unit_quiet(unit, invocation, cancelled=True), UNVERIFIED)
        return unit, invocation
    if not recorded:
        finish_preparation(fd, common, plan, environment, command, launch=False)
    require(preparation_unit_quiet(unit), UNVERIFIED)
    return unit, None


def cancel_preparation(fd, args, entry, plan, environment, common, boot, key):
    operation = common['start_operation_id']
    baseline = preparation_baseline(fd, common, boot)
    require(baseline is not None and machine_clock()[0] == boot, UNVERIFIED)
    launcher, launcher_pin = path_reference(plan['launcher'])
    require(launcher == environment.project / 'tools/linux_runtime/serve_environment.py', RESOURCE)
    trusted_executable(launcher, launcher_pin, script=True)
    trusted_executable(SYSTEMCTL, plan['systemctl_sha256'])
    trusted_executable(SYSTEMD_RUN, plan['systemd_run_sha256'])
    verify_accounts_and_paths(plan, environment)
    require(
        entry['verify_program'](environment.project)
        == environment.description['program_source']['sha256'],
        RESOURCE,
    )
    app_unit = f'walle-env-{environment.environment_id}-{operation}.service'
    no_application(environment, app_unit)
    name = cancellation_name(operation)
    frozen = record_at(fd, name)
    prep_unit, invocation = settle_preparation(
        fd,
        args,
        entry,
        common,
        boot,
        key,
        plan,
        environment,
        prepare_command(args, plan, environment, launcher, baseline),
        recorded=frozen is not None,
    )
    binding = preparation_cancel_binding(fd, common, boot, key, baseline)
    if frozen is None:
        write_record(fd, name, binding)
    else:
        require(frozen == binding, UNVERIFIED)
    state, control_revision = run_retirement(
        fd, binding, args, plan, environment, launcher, baseline, app_unit
    )
    require(
        machine_clock()[0] == boot
        and preparation_unit_quiet(prep_unit, invocation, cancelled=invocation is not None),
        UNVERIFIED,
    )
    return {
        'reason_code': RETIRED,
        'control_revision': control_revision,
        'retirement_state': state,
        'retirement_sha256': digest(canonical(binding)),
    }


def matches_preparation_cancel(fd, common, key, proof):
    operation = common['start_operation_id']
    boot = proof['boot_id']
    baseline = preparation_baseline(fd, common, boot)
    require(baseline is not None, UNVERIFIED)
    bound = preparation_cancel_binding(fd, common, boot, key, baseline)
    offset = 2 if proof['retirement_state'] == 'RETIRED' else 0
    return (
        record_at(fd, cancellation_name(operation)) == bound
        and proof['retirement_sha256'] == digest(canonical(bound))
        and proof['control_revision'] == baseline['control_revision'] + offset
        and (proof['retirement_state'] != 'RETIRED' or bound['preparation_sha256'] is not None)
    )
