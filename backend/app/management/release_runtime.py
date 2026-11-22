"""Dispatch a selected, verified release through its original fixed host unit."""

import os
from dataclasses import dataclass
from pathlib import Path
from subprocess import SubprocessError

from backend.app.infrastructure.environment_control import read_control
from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    absolute,
    canonical,
    digest,
    exact,
    require,
)
from backend.app.infrastructure.environment_installation import (
    Installation,
    sha_value,
    uuid_value,
    version_record,
)
from backend.app.infrastructure.environment_lock import NativeEnvironmentFiles
from backend.app.infrastructure.environment_release_check import CHECK_SOCKET
from backend.app.infrastructure.environment_release_open import (
    POLICY as OPEN_POLICY,
    observed_transition,
    open_inputs,
    opening_evidence,
)

from .attachment_observation import invoke_observer, machine_clock
from .operation_contract import INVALID, RESOURCE, installed_record, path_reference
from .registry import is_timestamp
from .release_configuration import CHANGED
from .release_execution import (
    admitted_release,
    environment_command,
    manager_command,
    optional_fact,
    release_execution,
    write_fact,
)
from .release_open_admission import OPEN_AUTHORIZED, OPEN_BLOCKED, TARGET
from .release_selection import read_selection
from .runtime_capacity import DIMENSIONS, load_capacity
from .runtime_observation import (
    POLICY as RUNTIME_POLICY,
    READY,
    SYSTEMCTL,
    trusted_executable,
    unit_facts,
)
from .runtime_start import (
    SYSTEMD_RUN,
    control_directory,
    run_bounded,
    runtime_result,
    startup_command,
    verify_accounts_and_paths,
)

POLICY = 'managed-release-open.v1.json'
DISPATCH = 'release-launch-issued.v1.json'
OPENED = 'release-opened.v1.json'
OPENED_STATUS = 'MANAGED_RELEASE_OPEN_CONFIRMED'
UNVERIFIED = 'MANAGED_RELEASE_OPEN_UNVERIFIED'
PATHS = ('home', 'temporary', 'maintenance_home', 'maintenance_temporary')
EXECUTABLE_PINS = ('systemctl_sha256', 'systemd_run_sha256')
OPEN_FIELDS = (
    'status',
    'operation_id',
    'run_id',
    *TARGET,
    'admission',
    'control_revision',
    'open_receipt_sha256',
    'opened_at',
)
OBSERVATION_FIELDS = ('proof_id', 'environment_id', 'observed_at', 'state', 'reason_code')


def load_launch(catalog, args, environment):
    path = args.managed_release_open_policy
    require(path.is_absolute() and path.name == POLICY, INVALID)
    policy = installed_record(path, args.managed_release_open_policy_sha256)
    version_record(
        policy,
        (
            *catalog.scope,
            'operation_id',
            'release_open_policy',
            'launcher',
            *PATHS,
            *EXECUTABLE_PINS,
        ),
        INVALID,
    )
    require(
        policy['operation_id'] == args.release_operation_id
        and all(policy[key] == value for key, value in catalog.scope.items())
        and all(sha_value(policy[key]) for key in EXECUTABLE_PINS),
        INVALID,
    )
    for key in PATHS:
        absolute(policy[key], INVALID)
    launcher, launcher_pin = path_reference(policy['launcher'])
    require(launcher == environment.project / 'tools/linux_runtime/serve_environment.py', RESOURCE)
    open_path, open_pin = path_reference(policy['release_open_policy'])
    require(open_path.name == OPEN_POLICY, INVALID)
    trusted_executable(launcher, launcher_pin, script=True)
    trusted_executable(SYSTEMCTL, policy['systemctl_sha256'])
    trusted_executable(SYSTEMD_RUN, policy['systemd_run_sha256'])
    verify_accounts_and_paths(policy, environment)
    return policy, launcher, open_path, open_pin


def check_closed(args, environment, unit, plan, selected):
    native = NativeEnvironmentFiles(args.root)
    with environment.lock(native) as lock, control_directory(environment) as fd:
        transition = observed_transition(fd, environment, plan)
        control = read_control(fd, environment)
        require(
            control == transition['after']
            and control['control_revision'] == selected['control_revision']
            and (control['admission'], control['closed_reason'], control['outbound_hold'])
            == ('CLOSED', 'RECOVERY_REQUIRED', True)
            and all(
                not os.path.lexists(environment.path('runtime') / name)
                for name in ('walle.sock', CHECK_SOCKET)
            )
            and unit_facts(unit)['LoadState'] == 'not-found',
            CHANGED,
        )
        opening_evidence(plan, environment, transition)
        lock.assert_owned()
        require(read_control(fd, environment) == control, CHANGED)


def confirmed_opening(opened, runtime, observation, request, selection):
    exact(opened, OPEN_FIELDS, UNVERIFIED)
    exact(observation, OBSERVATION_FIELDS, UNVERIFIED)
    exact(runtime, ('path', 'sha256'), UNVERIFIED)
    require(
        opened['status'] == 'RELEASE_OPEN_CONFIRMED'
        and opened['admission'] == 'OPEN'
        and opened['control_revision'] == selection['control_revision'] + 1
        and all(opened[key] == request[key] for key in ('operation_id', 'run_id', *TARGET))
        and is_timestamp(opened['opened_at'])
        and sha_value(opened['open_receipt_sha256'])
        and Path(runtime['path']).name == RUNTIME_POLICY
        and sha_value(runtime['sha256'])
        and observation['environment_id'] == request['environment_id']
        and uuid_value(observation['proof_id'])
        and is_timestamp(observation['observed_at'])
        and observation['state'] == 'RUNNING'
        and observation['reason_code'] == READY,
        UNVERIFIED,
    )
    return {
        'format_version': 1,
        'status': OPENED_STATUS,
        'request_sha256': digest(canonical(request)),
        'selection_receipt_sha256': request['selection_receipt_sha256'],
        'opening': opened,
        'runtime': runtime,
        'observation': observation,
    }


def known_opened(fd, request, selection):
    known = optional_fact(fd, OPENED)
    if known is not None:
        require(
            known
            == confirmed_opening(
                known['opening'], known['runtime'], known['observation'], request, selection
            ),
            UNVERIFIED,
        )
    return known


def confirm_dispatch(catalog, args, entry, setup, request, selection, *, wait):
    plan, booted, environment, unit, launcher = setup
    ref, observed = runtime_result(
        catalog,
        args,
        entry,
        plan,
        booted,
        environment,
        unit,
        request['boot_id'],
        wait=wait,
        wait_seconds=30,
    )
    open_path, open_pin = path_reference(booted['release_open_policy'])
    opened = invoke_observer(
        environment.maintenance_uid,
        environment.group,
        environment_command(
            'observe-release-open',
            args,
            launcher,
            environment,
            '--release-open-operation',
            request['operation_id'],
            '--release-open-policy',
            open_path,
            '--release-open-policy-sha256',
            open_pin,
        ),
        catalog.directory / 'observations',
    )
    return confirmed_opening(opened, ref, observed, request, selection)


@dataclass(frozen=True)
class SelectedDeployment:
    environment: Installation
    selection: dict
    attachment: dict
    profile_ref: str
    admission_action: str


def start_selected_deployment(catalog, registry, args, entry, manager, fd, target):
    operation = args.release_operation_id
    environment = target.environment
    selection = target.selection
    policy, launcher, open_path, open_pin = load_launch(catalog, args, environment)
    plan = open_inputs(environment, operation, open_path, open_pin)
    require(
        plan['control_sha256'] == selection['control_sha256']
        and plan['transition_sha256'] == selection['transition_sha256'],
        CHANGED,
    )
    original = {
        'operation_id': operation,
        'run_id': plan['run_id'],
        'open_policy_sha256': open_pin,
        'selection_receipt_sha256': digest(canonical(selection)),
        'launch_policy_sha256': args.managed_release_open_policy_sha256,
        **{key: selection[key] for key in TARGET},
    }
    unit = f'walle-env-{environment.environment_id}-{operation}.service'
    previous = optional_fact(fd, DISPATCH)
    if previous is not None:
        require(
            previous['format_version'] == 1
            and previous['unit'] == unit
            and all(previous['request'][key] == value for key, value in original.items()),
            CHANGED,
        )
        known = known_opened(fd, previous['request'], selection)
        if known is not None:
            os.fsync(fd)
            return known
    capacity = load_capacity(catalog)
    limits = capacity.profile(
        {
            'purpose': environment.description['purpose'],
            'profile_ref': target.profile_ref,
        }
    )
    request = {
        **original,
        'boot_id': machine_clock()[0],
        'limits': limits,
        'capacity_sha256': capacity.sha256,
    }
    dispatch = {'format_version': 1, 'request': request, 'unit': unit}
    if previous is None:
        check_closed(args, environment, unit, plan, selection)
    else:
        require(previous == dispatch, CHANGED)
    stage = {
        **policy,
        **{key: limits[key] for key in DIMENSIONS if key != 'run_slots'},
        'candidate_ref': target.attachment['candidate_ref'],
        'candidate_sha256': target.attachment['sha256'],
    }
    booted = {
        'operation_id': operation,
        'run_id': plan['run_id'],
        'start_sha256': open_pin,
        'release_open_policy': policy['release_open_policy'],
    }
    if previous is None:
        decision = invoke_observer(
            registry.uid,
            registry.gid,
            manager_command(target.admission_action, args, manager),
            catalog.directory / 'observations',
            input_bytes=canonical(request),
        )
        if decision.get('status') == OPEN_BLOCKED:
            exact(decision, ('status', 'missing'), RESOURCE)
            require(
                type(decision['missing']) is list
                and bool(decision['missing'])
                and all(key in DIMENSIONS for key in decision['missing']),
                RESOURCE,
            )
            return decision
        require(decision == {'status': OPEN_AUTHORIZED, 'request': request}, RESOURCE)
        manifest, _ = entry['verify_runtime'](args.root, args.sha256)
        executable = args.root / manifest['python']['executable_ref']
        require(request['boot_id'] == machine_clock()[0], RESOURCE)
        # The write precedes the external effect. Retries only observe this same unit.
        write_fact(fd, DISPATCH, dispatch)
        run_bounded(
            startup_command(args, stage, booted, environment, launcher, executable, unit), 15
        )
    try:
        result = confirm_dispatch(
            catalog,
            args,
            entry,
            (stage, booted, environment, unit, manager),
            request,
            selection,
            wait=previous is None,
        )
        write_fact(fd, OPENED, result)
    except (EnvironmentFailure, OSError, RuntimeError, ValueError, SubprocessError) as error:
        raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
    return known_opened(fd, request, selection)


def start_managed_release(catalog, registry, args, entry, manager):
    operation = args.release_operation_id
    require(os.geteuid() == 0 and uuid_value(operation), INVALID)
    with release_execution(catalog, operation) as (_, fd):
        admitted = admitted_release(catalog, registry, args, entry, manager)
        selection = read_selection(fd, admitted)
        require(selection is not None, RESOURCE)
        target = SelectedDeployment(
            admitted.pair.target,
            selection,
            admitted.configuration.target_reference,
            admitted.configuration.target['profile_ref'],
            '_admit-release-open',
        )
        return start_selected_deployment(catalog, registry, args, entry, manager, fd, target)
