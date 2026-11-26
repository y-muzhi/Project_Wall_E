"""Observe and stop the known in-flight startup preparation service."""

import re
from pathlib import Path

from backend.app.infrastructure.environment_files import canonical, digest, exact, require

from .attachment_observation import machine_clock, now
from .registry import is_timestamp
from .runtime_observation import (
    CGROUP_ROOT,
    SYSTEMCTL,
    SYSTEM_PYTHON,
    cgroup_processes,
    process_identity,
    resource_limits,
    unit_facts,
)
from .runtime_start import (
    PREPARATION_PROPERTIES,
    PREPARATION_UNVERIFIED,
    observe_preparation,
    preparation_properties,
    preparation_unit_identity,
    preparation_unit_quiet,
    record_at,
    run_bounded,
    write_record,
)


def preparation_process(pid, argv, executable, environment, group, parent):
    process_identity(
        pid, argv, executable, environment, group, parent=parent, uid=environment.maintenance_uid
    )
    status = dict(
        row.split(':', 1)
        for row in (Path('/proc') / str(pid) / 'status').read_text(encoding='ascii').splitlines()
    )
    require(
        not status['Groups'].strip()
        and status['NoNewPrivs'].strip() == '1'
        and all(int(status[key], 16) == 0 for key in ('CapInh', 'CapPrm', 'CapEff', 'CapAmb')),
        PREPARATION_UNVERIFIED,
    )


def active_preparation(unit, properties, plan, environment, command, executable):
    expected_group = '/system.slice/' + unit
    facts = preparation_unit_identity(unit, properties)
    require(
        facts['ActiveState'] == 'activating'
        and facts['SubState'] == 'start'
        and facts['ControlGroup'] == expected_group
        and facts['MainPID'].isdecimal()
        and int(facts['MainPID']) > 1,
        PREPARATION_UNVERIFIED,
    )
    group = CGROUP_ROOT / expected_group.removeprefix('/')
    main = int(facts['MainPID'])
    processes = cgroup_processes(group)
    require(main in processes and 1 <= len(processes) <= 2, PREPARATION_UNVERIFIED)
    launcher = command[command.index('--') + 1 :]
    preparation_process(main, launcher, SYSTEM_PYTHON, environment, expected_group, parent=1)
    for process in processes - {main}:
        target = [str(executable), *launcher[1:5], '_prepare-start', *launcher[6:]]
        preparation_process(process, target, executable, environment, expected_group, parent=main)
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
        cgroup_processes(group) == processes
        and unit_facts(unit, properties=PREPARATION_PROPERTIES) == facts,
        PREPARATION_UNVERIFIED,
    )
    return facts['InvocationID']


def preparation_stop_intent(fd, preparation, key):
    name = 'cancel-prep-unit-' + preparation['start_operation_id'] + '.v1.json'
    record = record_at(fd, name)
    if record is None:
        return name, None
    expected = {
        'format_version': 1,
        'control_key': key,
        'preparation_sha256': digest(canonical(preparation)),
        'unit': preparation['unit'],
        'boot_id': preparation['boot_id'],
    }
    exact(record, (*expected, 'invocation_id', 'observed_at'), PREPARATION_UNVERIFIED)
    require(
        all(record[field] == value for field, value in expected.items())
        and type(record['invocation_id']) is str
        and re.fullmatch(r'[0-9a-f]{32}', record['invocation_id']) is not None
        and record['invocation_id'] != '0' * 32
        and is_timestamp(record['observed_at']),
        PREPARATION_UNVERIFIED,
    )
    return name, record


def close_active_preparation(fd, preparation, key, plan, environment, command, executable):
    unit = preparation['unit']
    boot = preparation['boot_id']
    require(preparation['state'] == 'ISSUED' and machine_clock()[0] == boot, PREPARATION_UNVERIFIED)
    properties = preparation_properties(plan, preparation['command_sha256'])
    name, record = preparation_stop_intent(fd, preparation, key)
    if record is None:
        invocation = active_preparation(unit, properties, plan, environment, command, executable)
        record = {
            'format_version': 1,
            'control_key': key,
            'preparation_sha256': digest(canonical(preparation)),
            'unit': unit,
            'boot_id': boot,
            'invocation_id': invocation,
            'observed_at': now(),
        }
        write_record(fd, name, record)
    invocation = record['invocation_id']
    if not preparation_unit_quiet(unit, invocation, cancelled=True):
        facts = preparation_unit_identity(unit, properties)
        require(facts['InvocationID'] == invocation, PREPARATION_UNVERIFIED)
        if facts['ActiveState'] == 'activating':
            require(
                active_preparation(unit, properties, plan, environment, command, executable)
                == invocation,
                PREPARATION_UNVERIFIED,
            )
            run_bounded([str(SYSTEMCTL), '--system', '--no-pager', 'stop', unit], 25)
        elif facts['ActiveState'] == 'active':
            require(observe_preparation(unit, properties) == invocation, PREPARATION_UNVERIFIED)
            run_bounded([str(SYSTEMCTL), '--system', '--no-pager', 'stop', unit], 25)
    require(
        machine_clock()[0] == boot and preparation_unit_quiet(unit, invocation, cancelled=True),
        PREPARATION_UNVERIFIED,
    )
    closed_name = 'cancel-prep-closed-' + preparation['start_operation_id'] + '.v1.json'
    closed = {**record, 'state': 'CLOSED'}
    prior = record_at(fd, closed_name)
    if prior is None:
        write_record(fd, closed_name, closed)
    else:
        require(prior == closed, PREPARATION_UNVERIFIED)
    return closed


def preparation_stopped(fd, preparation, key):
    _, record = preparation_stop_intent(fd, preparation, key)
    if record is None:
        return None
    original = preparation['start_operation_id']
    closed = record_at(fd, 'cancel-prep-closed-' + original + '.v1.json')
    require(closed == {**record, 'state': 'CLOSED'}, PREPARATION_UNVERIFIED)
    return closed
