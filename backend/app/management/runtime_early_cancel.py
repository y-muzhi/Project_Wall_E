"""Close a verified application group before the original launch admits work."""

from contextlib import ExitStack
import os
import re
import select
from uuid import uuid4

from backend.app.infrastructure.environment_admission import preparation_retirement
from backend.app.infrastructure.environment_files import canonical, digest, exact, require
from backend.app.infrastructure.environment_installation import uuid_value
from backend.app.infrastructure.environment_lock import NativeEnvironmentFiles

from .attachment_observation import machine_clock, now
from .operation_contract import RESOURCE, path_reference
from .registry import is_timestamp
from .runtime_observation import (
    CGROUP_ROOT,
    PROPERTIES,
    SYSTEM_PYTHON,
    SYSTEMCTL,
    cgroup_processes,
    process_identity,
    resource_limits,
    trusted_executable,
    unit_facts,
)
from .runtime_preparation_cancel import no_application, preparation_cancel_binding, run_retirement
from .runtime_start import (
    SYSTEMD_RUN,
    control_directory,
    original_record,
    preparation_baseline,
    preparation_unit_quiet,
    prepared,
    record_at,
    run_bounded,
    startup_command,
    verify_accounts_and_paths,
    write_record,
)

EARLY_STOPPED = 'MANAGED_EARLY_APPLICATION_STOP_CONFIRMED'
UNVERIFIED = 'MANAGEMENT_EARLY_CANCEL_UNVERIFIED'
UNIT_PROPERTIES = (*PROPERTIES, 'SendSIGKILL', 'SendSIGHUP', 'KillSignal', 'MemoryMax', 'TasksMax')


def verify_process_group(unit, args, plan, environment, launcher, executable, start):
    group_name = '/system.slice/' + unit
    group = CGROUP_ROOT / group_name.removeprefix('/')
    facts = unit_facts(unit, properties=UNIT_PROPERTIES)
    expected = {
        'LoadState': 'loaded',
        'ActiveState': 'active',
        'SubState': 'running',
        'Type': 'exec',
        'User': str(environment.application_uid),
        'Group': str(environment.group),
        'Restart': 'no',
        'KillMode': 'control-group',
        'SendSIGKILL': 'no',
        'SendSIGHUP': 'no',
        'Delegate': 'no',
        'NoNewPrivileges': 'yes',
        'ControlGroup': group_name,
        'MemoryMax': str(plan['memory_bytes']),
        'TasksMax': str(plan['tasks']),
    }
    invocation = facts.get('InvocationID', '')
    require(
        all(facts.get(key) == value for key, value in expected.items())
        and facts['KillSignal'] in ('15', 'SIGTERM')
        and facts['MainPID'].isdecimal()
        and int(facts['MainPID']) > 1
        and re.fullmatch(r'[0-9a-f]{32}', invocation) is not None
        and invocation != '0' * 32,
        UNVERIFIED,
    )
    main = int(facts['MainPID'])
    pids = cgroup_processes(group)
    require(main in pids and 1 <= len(pids) <= 2, UNVERIFIED)
    command = startup_command(
        args, plan, start['prepared'], environment, launcher, executable, unit
    )
    parent = command[command.index('--') + 1 :]
    target = [str(executable), *parent[1:5], '_serve', *parent[6:]]
    with ExitStack() as owned:
        poller = select.poll()
        for pid in pids:
            handle = os.pidfd_open(pid)
            owned.callback(os.close, handle)
            poller.register(handle, select.POLLIN)
        require(not poller.poll(0), UNVERIFIED)
        process_identity(main, parent, SYSTEM_PYTHON, environment, group_name, parent=1)
        for child in pids - {main}:
            process_identity(child, target, executable, environment, group_name, parent=main)
        resource_limits(
            group,
            {
                'memory_bytes': plan['memory_bytes'],
                'tasks': plan['tasks'],
                'cpu_quota_usec': plan['cpu_percent'] * 1000,
                'cpu_period_usec': 100_000,
            },
        )
        require(
            not poller.poll(0)
            and cgroup_processes(group) == pids
            and unit_facts(unit, properties=UNIT_PROPERTIES) == facts,
            UNVERIFIED,
        )
    return invocation


def verify_early_control(environment, native, baseline):
    with control_directory(environment) as control:
        current, target, state = preparation_retirement(
            environment,
            control,
            baseline['start_operation_id'],
            baseline['control_operation_id'],
            baseline['control_revision'],
            baseline['control_sha256'],
        )
        require(
            state == 'RETIRED'
            and current != target
            and environment.lock(native).observer_pid() is None
            and not os.path.lexists(environment.path('runtime') / 'walle.sock'),
            UNVERIFIED,
        )


def early_binding(fd, common, start, control_key):
    operation = common['start_operation_id']
    boot = start['boot_id']
    baseline = preparation_baseline(fd, common, boot)
    preparation = record_at(fd, 'prepare-' + operation + '.v1.json')
    require(
        baseline is not None
        and preparation is not None
        and preparation.get('state') == 'RELEASED'
        and preparation.get('receipt_sha256') == start['prepared']['start_sha256']
        and start['prepared']['control_revision'] == baseline['control_revision'] + 1,
        UNVERIFIED,
    )
    binding = {
        **preparation_cancel_binding(fd, common, boot, control_key, baseline),
        'unit': f'walle-env-{common["environment_id"]}-{operation}.service',
        'run_id': start['prepared']['run_id'],
        'start_sha256': start['prepared']['start_sha256'],
    }
    return baseline, binding


def early_witness(fd, binding):
    operation = binding['start_operation_id']
    name = 'cancel-early-unit-' + operation + '.v1.json'
    prior = record_at(fd, name)
    if prior is not None:
        exact(prior, (*binding, 'invocation_id', 'observed_at', 'proof_id'), UNVERIFIED)
        invocation = prior['invocation_id']
        require(
            all(prior[key] == value for key, value in binding.items())
            and type(invocation) is str
            and re.fullmatch(r'[0-9a-f]{32}', invocation) is not None
            and invocation != '0' * 32
            and is_timestamp(prior['observed_at'])
            and uuid_value(prior['proof_id']),
            UNVERIFIED,
        )
    return name, prior


def early_effect(fd, common, key):
    operation = common['start_operation_id']
    proof = record_at(fd, 'cancel-early-' + operation + '.v1.json')
    if proof is None:
        return None
    start = original_record(fd, 'start-' + operation + '.v1.json', common)
    require(start is not None and start['state'] == 'STARTING', UNVERIFIED)
    baseline, binding = early_binding(fd, common, start, key)
    _, witness = early_witness(fd, binding)
    require(witness is not None, UNVERIFIED)
    exact(
        proof,
        (*binding, 'witness_sha256', 'control_revision', 'observed_at', 'proof_id', 'reason_code'),
        UNVERIFIED,
    )
    require(
        all(proof[key] == value for key, value in binding.items())
        and proof['witness_sha256'] == digest(canonical(witness))
        and proof['control_revision'] == baseline['control_revision'] + 2
        and proof['reason_code'] == EARLY_STOPPED
        and is_timestamp(proof['observed_at'])
        and uuid_value(proof['proof_id']),
        UNVERIFIED,
    )
    return witness, proof


def close_early_application(fd, args, entry, plan, environment, common, start, key, executable):
    baseline, binding = early_binding(fd, common, start, key)
    boot = start['boot_id']
    require(machine_clock()[0] == boot, UNVERIFIED)
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
    unit = binding['unit']
    native = NativeEnvironmentFiles(args.root)
    name, witness = early_witness(fd, binding)
    if witness is None:
        verify_early_control(environment, native, baseline)
        require(
            prepared(environment, common['start_operation_id']) == start['prepared'], UNVERIFIED
        )
        invocation = verify_process_group(
            unit, args, plan, environment, launcher, executable, start
        )
        witness = {
            **binding,
            'invocation_id': invocation,
            'observed_at': now(),
            'proof_id': str(uuid4()),
        }
        write_record(fd, name, witness)
    if not preparation_unit_quiet(unit, witness['invocation_id'], cancelled=True):
        require(
            verify_process_group(unit, args, plan, environment, launcher, executable, start)
            == witness['invocation_id'],
            UNVERIFIED,
        )
        run_bounded([str(SYSTEMCTL), '--system', '--no-pager', 'stop', unit], 25)
    no_application(environment, unit)
    state, version = run_retirement(fd, binding, args, plan, environment, launcher, baseline, unit)
    require(state == 'RETIRED' and machine_clock()[0] == boot, UNVERIFIED)
    proof = {
        **binding,
        'witness_sha256': digest(canonical(witness)),
        'control_revision': version,
        'observed_at': now(),
        'proof_id': str(uuid4()),
        'reason_code': EARLY_STOPPED,
    }
    write_record(fd, 'cancel-early-' + common['start_operation_id'] + '.v1.json', proof)
    return proof
