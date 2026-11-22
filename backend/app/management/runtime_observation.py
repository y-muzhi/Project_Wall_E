"""Read bounded, actual Linux service and application facts for one original run."""

from contextlib import ExitStack
from hashlib import sha256
import http.client
import os
from pathlib import Path
import re
import select
import socket
import stat
import struct
import subprocess
import sys
from urllib.parse import urlsplit
from uuid import uuid4

from backend.app.infrastructure.environment_admission import read_start
from backend.app.infrastructure.environment_control import read_control
from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    absolute,
    canonical,
    decode,
    digest,
    exact,
    identity,
    protected_directory,
    read_entry,
    read_protected,
    require,
)
from backend.app.infrastructure.environment_installation import ACCESS_NAME, sha_value, uuid_value
from backend.app.infrastructure.environment_lock import NativeEnvironmentFiles
from backend.app.shared.validation import InvalidInput, strict_json_object

from .attachment_observation import (
    candidate_environment,
    machine_clock,
    now,
    observation_path,
    publish_observation,
    require_fresh,
)
from .operation_contract import INVALID, RESOURCE, SCOPE, installed_record, path_reference, version
from .registry import is_timestamp

POLICY = 'managed-runtime.v1.json'
SYSTEMCTL = Path('/usr/bin/systemctl')
SYSTEM_PYTHON = Path('/usr/bin/python3')
CGROUP_ROOT = Path('/sys/fs/cgroup')
UNKNOWN = 'MANAGED_PROCESS_UNVERIFIED'
READY = 'MANAGED_APPLICATION_READY'
NOT_READY = 'MANAGED_APPLICATION_UNVERIFIED'
STOPPED = 'MANAGED_STOP_CONFIRMED'
STATES = {'UNKNOWN': (UNKNOWN,), 'RUNNING': (READY, NOT_READY), 'STOPPED': (STOPPED,)}
PROPERTIES = (
    'Id',
    'LoadState',
    'ActiveState',
    'SubState',
    'MainPID',
    'InvocationID',
    'ControlGroup',
    'KillMode',
    'Type',
    'Restart',
    'User',
    'Group',
    'Delegate',
    'NoNewPrivileges',
)
BAD_SAMPLE = (
    EnvironmentFailure,
    OSError,
    ValueError,
    KeyError,
    TypeError,
    subprocess.SubprocessError,
    http.client.HTTPException,
    InvalidInput,
)


def load_policy(path, expected, catalog):
    require(path.is_absolute() and path.name == POLICY and sha_value(expected), INVALID)
    record = installed_record(path, expected)
    extra = ('release_open_policy',) if 'release_open_policy' in record else ()
    policy = exact(
        record,
        (
            'format_version',
            *catalog.scope,
            'candidate_ref',
            'candidate_sha256',
            'operation_id',
            'run_id',
            'boot_id',
            'invocation_id',
            'start_sha256',
            'systemctl_sha256',
            'launcher',
            'home',
            'temporary',
            'memory_bytes',
            'tasks',
            'cpu_quota_usec',
            'cpu_period_usec',
            *extra,
        ),
        INVALID,
    )
    require(type(policy['format_version']) is int and policy['format_version'] == 1, INVALID)
    require(all(policy[key] == value for key, value in catalog.scope.items()), SCOPE)
    require(
        all(
            uuid_value(policy[key])
            for key in ('candidate_ref', 'operation_id', 'run_id', 'boot_id')
        )
        and all(
            sha_value(policy[key])
            for key in ('candidate_sha256', 'start_sha256', 'systemctl_sha256')
        )
        and type(policy['invocation_id']) is str
        and re.fullmatch(r'[a-f0-9]{32}', policy['invocation_id']) is not None
        and any(ch != '0' for ch in policy['invocation_id'])
        and all(
            version(policy[key])
            for key in ('memory_bytes', 'tasks', 'cpu_quota_usec', 'cpu_period_usec')
        ),
        INVALID,
    )
    path_reference(policy['launcher'])
    absolute(policy['home'], INVALID)
    absolute(policy['temporary'], INVALID)
    if extra:
        from backend.app.infrastructure.environment_release_open import POLICY as OPEN_POLICY

        opened, pin = path_reference(policy['release_open_policy'])
        require(opened.name == OPEN_POLICY and pin == policy['start_sha256'], INVALID)
    return policy


def trusted_executable(path, expected, *, script=False):
    require(path.resolve(strict=True) == path, RESOURCE)
    if script:
        require(digest(read_protected(path)) == expected, RESOURCE)
        return
    with protected_directory(path.parent):
        item = path.lstat()
        require(
            stat.S_ISREG(item.st_mode)
            and item.st_uid == 0
            and not item.st_mode & 0o022
            and sha256(path.read_bytes()).hexdigest() == expected,
            RESOURCE,
        )


def unit_facts(unit, *, properties=PROPERTIES, optional=()):
    command = [
        str(SYSTEMCTL),
        '--system',
        '--no-pager',
        'show',
        *('--property=' + field for field in properties),
        unit,
    ]
    status = subprocess.run(
        command,
        env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'TZ': 'UTC', 'SYSTEMD_COLORS': '0'},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=4,
        check=False,
    )
    require(len(status.stdout) < 8192, RESOURCE)
    values = {}
    for line in status.stdout.decode('utf-8').splitlines():
        field, equals, value = line.partition('=')
        require(equals and field in properties and field not in values, RESOURCE)
        values[field] = value
    require(values.get('Id') == unit and 'LoadState' in values, RESOURCE)
    if values['LoadState'] == 'not-found':
        require(status.returncode in (0, 1), RESOURCE)
    else:
        require(
            status.returncode == 0 and set(properties).difference(optional) <= values.keys(),
            RESOURCE,
        )
    return values


def expected_command(args, policy, environment, executable, launcher):
    opened = policy.get('release_open_policy')
    mode = '_serve' if opened is None else '_serve-release-open'
    proof = (
        ['--start-sha256', policy['start_sha256']]
        if opened is None
        else [
            '--release-open-policy',
            opened['path'],
            '--release-open-policy-sha256',
            opened['sha256'],
        ]
    )
    return [
        str(executable),
        '-I',
        '-B',
        '-S',
        str(launcher),
        mode,
        '--root',
        str(args.root),
        '--home',
        policy['home'],
        '--temporary',
        policy['temporary'],
        '--project',
        str(environment.project),
        '--anchor',
        str(environment.anchor),
        '--runtime-entry',
        str(args.runtime_entry),
        '--sha256',
        args.sha256,
        '--anchor-sha256',
        policy['_installation_sha256'],
        '--operation-id',
        policy['operation_id'],
        *proof,
    ]


def launch_wrapper(argv):
    return [str(SYSTEM_PYTHON), *argv[1:5], argv[5].removeprefix('_'), *argv[6:]]


def process_identity(pid, expected, executable, environment, group, *, parent=None, uid=None):
    path = Path('/proc') / str(pid)
    fields = {}
    for row in (path / 'status').read_text(encoding='utf-8').splitlines():
        key, _, value = row.partition(':')
        if key in ('Uid', 'Gid', 'PPid'):
            fields[key] = [int(part) for part in value.split()]
    expected_uid = environment.application_uid if uid is None else uid
    require(
        fields.get('Uid') == [expected_uid] * 4
        and fields.get('Gid') == [environment.group] * 4
        and (parent is None or fields.get('PPid') == [parent])
        and identity((path / 'exe').stat()) == identity(executable.stat())
        and (path / 'cmdline').read_bytes() == b'\0'.join(map(os.fsencode, expected)) + b'\0'
        and (path / 'cgroup').read_text(encoding='ascii').splitlines() == ['0::' + group],
        RESOURCE,
    )


def cgroup_processes(group):
    require(group.is_dir() and not group.is_symlink(), RESOURCE)
    require(not any(entry.is_dir() for entry in group.iterdir()), RESOURCE)
    return {int(part) for part in (group / 'cgroup.procs').read_text(encoding='ascii').split()}


def resource_limits(group, policy):
    memory = (group / 'memory.max').read_text(encoding='ascii').strip()
    tasks = (group / 'pids.max').read_text(encoding='ascii').strip()
    cpu = (group / 'cpu.max').read_text(encoding='ascii').split()
    require(
        memory == str(policy['memory_bytes'])
        and tasks == str(policy['tasks'])
        and cpu == [str(policy['cpu_quota_usec']), str(policy['cpu_period_usec'])],
        RESOURCE,
    )


def controlled(environment, policy):
    with protected_directory(environment.environment_root) as parent:
        fd = os.open(
            'control', os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
        )
        try:
            require(identity(os.fstat(fd)) == environment.roots['control'], RESOURCE)
            if 'release_open_policy' in policy:
                return controlled_release(fd, environment, policy)
            raw = read_start(fd, environment, policy['operation_id'])
            require(digest(raw) == policy['start_sha256'], RESOURCE)
            start = decode(raw, RESOURCE)
            revision = start.get('control_revision')
            expected = {
                'format_version': 1,
                'environment_id': environment.environment_id,
                'data_generation': environment.data_generation,
                'deployment_id': environment.deployment_id,
                'configuration_sha256': environment.configuration_sha256,
                'operation_id': policy['operation_id'],
                'run_id': policy['run_id'],
                'control_revision': revision,
            }
            require(version(revision) and raw == canonical(expected), RESOURCE)
            current = read_control(fd, environment)
            require(current['operation_id'] == policy['operation_id'], RESOURCE)
            return current, revision
        finally:
            os.close(fd)


def controlled_release(fd, environment, policy):
    from backend.app.infrastructure.environment_release_open import (
        exact_open_time,
        expected_open_receipt,
        observed_transition,
        open_inputs,
    )

    path, pin = path_reference(policy['release_open_policy'])
    plan = open_inputs(environment, policy['operation_id'], path, pin)
    require(plan['run_id'] == policy['run_id'] and policy['start_sha256'] == pin, RESOURCE)
    transition = observed_transition(fd, environment, plan)
    current = read_control(fd, environment)
    revision = transition['after']['control_revision']
    require(current['operation_id'] == policy['operation_id'], RESOURCE)
    if current == transition['after']:
        return current, revision
    name = f'open-{plan["run_id"]}.v1.json'
    require(
        current['open_receipt_ref'] == name
        and current['last_opened_deployment_id'] == environment.deployment_id
        and current['control_revision'] > revision,
        RESOURCE,
    )
    receipt = read_entry(fd, name, owner=environment.application_uid, group=environment.group)
    exact_open_time(receipt, expected_open_receipt(environment, plan, transition, pin))
    return current, revision


def application_ready(environment, policy, pid, control, revision):
    if (
        control['admission'] != 'OPEN'
        or control['control_revision'] != revision + 1
        or control['open_receipt_ref'] != f'open-{policy["run_id"]}.v1.json'
        or environment.ingress_group is None
    ):
        return False
    runtime = environment.path('runtime')
    path = runtime / 'walle.sock'
    try:
        properties = path.lstat()
        require(
            identity(runtime.stat(follow_symlinks=False)) == environment.roots['runtime']
            and stat.S_ISSOCK(properties.st_mode)
            and stat.S_IMODE(properties.st_mode) == 0o660
            and properties.st_uid == environment.application_uid
            and properties.st_gid == environment.ingress_group,
            RESOURCE,
        )
        access = decode(read_protected(environment.anchor.parent / ACCESS_NAME), RESOURCE)
        principals = [
            item['principal_id']
            for item in access['principals']
            if item['client_kind'] == 'AUTOMATION'
        ]
        require(bool(principals), RESOURCE)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as upstream:
            upstream.settimeout(1.5)
            upstream.connect(str(path))
            credentials = upstream.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')
            )
            require(
                struct.unpack('3i', credentials)
                == (pid, environment.application_uid, environment.group),
                RESOURCE,
            )
            client = http.client.HTTPConnection('unused', timeout=1.5)
            client.sock = upstream
            client.request(
                'GET',
                '/api/v1/environment',
                headers={
                    'Host': urlsplit(access['public_origin']).netloc,
                    'X-WALL-E-Auth-Principal': principals[0],
                    'X-WALL-E-Client': 'automation-v1',
                },
            )
            response = client.getresponse()
            payload = response.read(65537)
        require(
            response.status == 200
            and len(payload) <= 65536
            and identity(path.lstat()) == identity(properties),
            RESOURCE,
        )
        envelope = strict_json_object(payload)
        data = envelope['data']
        return (
            envelope['success'] is True
            and envelope['error'] is None
            and data['environment_id'] == environment.environment_id
            and data['data_generation'] == environment.data_generation
            and data['configuration_sha256'] == environment.configuration_sha256
            and data['run_id'] == policy['run_id']
            and data['binding_protocol'] == 1
            and data['phase'] == 'READY'
            and data['maintenance']['control_revision'] == control['control_revision']
            and response.headers['X-WALL-E-Environment-ID'] == environment.environment_id
            and response.headers['X-WALL-E-Data-Generation'] == environment.data_generation
            and response.headers['X-WALL-E-Run-ID'] == policy['run_id']
        )
    except BAD_SAMPLE:
        return False


def running_sample(native, environment, policy, unit, facts, group, argv, executable):
    gid = str(environment.group)
    require(
        all(
            facts.get(key) == expected
            for key, expected in {
                'LoadState': 'loaded',
                'ActiveState': 'active',
                'SubState': 'running',
                'KillMode': 'control-group',
                'Type': 'exec',
                'Restart': 'no',
                'User': str(environment.application_uid),
                'Group': gid,
                'Delegate': 'no',
                'NoNewPrivileges': 'yes',
                'InvocationID': policy['invocation_id'],
                'ControlGroup': '/system.slice/' + unit,
            }.items()
        ),
        RESOURCE,
    )
    leader = int(facts['MainPID'])
    require(leader > 1 and str(leader) == facts['MainPID'], RESOURCE)
    application = environment.lock(native).observer_pid()
    require(type(application) is int and application > 1 and application != leader, RESOURCE)
    processes = {leader, application}
    host_command = launch_wrapper(argv)
    with ExitStack() as owned:
        watcher = select.poll()
        for pid in processes:
            handle = os.pidfd_open(pid)
            owned.callback(os.close, handle)
            watcher.register(handle, select.POLLIN)
        require(not watcher.poll(0), RESOURCE)
        process_identity(leader, host_command, SYSTEM_PYTHON, environment, facts['ControlGroup'])
        process_identity(
            application, argv, executable, environment, facts['ControlGroup'], parent=leader
        )
        require(cgroup_processes(group) == processes, RESOURCE)
        resource_limits(group, policy)
        current, revision = controlled(environment, policy)
        ready = application_ready(environment, policy, application, current, revision)
        require(
            not watcher.poll(0)
            and unit_facts(unit) == facts
            and cgroup_processes(group) == processes
            and environment.lock(native).observer_pid() == application,
            RESOURCE,
        )
        resource_limits(group, policy)
        require(controlled(environment, policy)[0] == current, RESOURCE)
        return 'RUNNING', READY if ready else NOT_READY


def stopped_sample(native, environment, policy, unit, facts, group, previous):
    require(previous and previous['seen_running'], RESOURCE)
    require(
        facts['LoadState'] in ('loaded', 'not-found')
        and facts.get('ActiveState') == 'inactive'
        and facts.get('MainPID', '0') == '0',
        RESOURCE,
    )
    require(facts.get('InvocationID', '') in ('', '0' * 32, policy['invocation_id']), RESOURCE)
    if group.exists():
        require(not cgroup_processes(group), RESOURCE)
    current, revision = controlled(environment, policy)
    require(
        current['admission'] == 'CLOSED'
        and current['closed_reason'] == 'NORMAL_STOP'
        and current['control_revision'] == revision + 3
        and current['open_receipt_ref'] == f'open-{policy["run_id"]}.v1.json',
        RESOURCE,
    )
    socket_path = environment.path('runtime') / 'walle.sock'
    require(
        not os.path.lexists(socket_path)
        and environment.lock(native).observer_pid() is None
        and unit_facts(unit) == facts
        and controlled(environment, policy)[0] == current
        and (not group.exists() or not cgroup_processes(group)),
        RESOURCE,
    )
    return 'STOPPED', STOPPED


def runtime_observation(catalog, environment):
    try:
        raw = installed_record(observation_path(catalog, 'runtime-' + environment))
        exact(
            raw,
            (
                'format_version',
                *catalog.scope,
                'proof_id',
                'environment_id',
                'candidate_ref',
                'policy_sha256',
                'boot_id',
                'observed_at',
                'observed_monotonic_ms',
                'run_id',
                'deployment_id',
                'data_generation',
                'configuration_sha256',
                'program_sha256',
                'state',
                'reason_code',
                'seen_running',
            ),
            RESOURCE,
        )
        require(
            type(raw['format_version']) is int
            and raw['format_version'] == 1
            and all(raw[key] == value for key, value in catalog.scope.items())
            and raw['environment_id'] == environment
            and all(
                uuid_value(raw[key])
                for key in (
                    'proof_id',
                    'candidate_ref',
                    'boot_id',
                    'run_id',
                    'deployment_id',
                    'data_generation',
                )
            )
            and all(
                sha_value(raw[key])
                for key in ('policy_sha256', 'configuration_sha256', 'program_sha256')
            )
            and type(raw['seen_running']) is bool
            and version(raw['observed_monotonic_ms'])
            and raw['reason_code'] in STATES[raw['state']]
            and is_timestamp(raw['observed_at'])
            and (raw['state'] == 'UNKNOWN' or raw['seen_running']),
            RESOURCE,
        )
        return raw
    except BAD_SAMPLE:
        return None


def capture_runtime(catalog, args, entry):
    require(os.geteuid() == 0 and sys.platform == 'linux', RESOURCE)
    policy = load_policy(args.runtime_policy, args.runtime_policy_sha256, catalog)
    candidate = catalog.candidate(policy['candidate_ref'], policy['candidate_sha256'])
    environment = candidate_environment(candidate, args.sha256)
    policy['_installation_sha256'] = candidate['installation']['sha256']
    launcher, launcher_sha = path_reference(policy['launcher'])
    trusted_executable(launcher, launcher_sha, script=True)
    trusted_executable(SYSTEMCTL, policy['systemctl_sha256'])
    require(
        entry['verify_program'](environment.project)
        == environment.description['program_source']['sha256'],
        RESOURCE,
    )
    manifest, _ = entry['verify_runtime'](args.root, args.sha256)
    executable = args.root / manifest['python']['executable_ref']
    argv = expected_command(args, policy, environment, executable, launcher)
    native = NativeEnvironmentFiles(args.root)
    boot, _ = machine_clock()
    require(boot == policy['boot_id'], RESOURCE)
    previous = runtime_observation(catalog, environment.environment_id)
    if previous and (
        previous['boot_id'] != boot or previous['policy_sha256'] != args.runtime_policy_sha256
    ):
        previous = None
    unit = f'walle-env-{environment.environment_id}-{policy["operation_id"]}.service'
    group = CGROUP_ROOT / 'system.slice' / unit
    try:
        facts = unit_facts(unit)
        if facts.get('ActiveState') == 'active':
            state, reason = running_sample(
                native, environment, policy, unit, facts, group, argv, executable
            )
        else:
            state, reason = stopped_sample(
                native, environment, policy, unit, facts, group, previous
            )
    except BAD_SAMPLE:
        state, reason = 'UNKNOWN', UNKNOWN
    current_boot, ended = machine_clock()
    require(current_boot == boot, RESOURCE)
    result = {
        'format_version': 1,
        **catalog.scope,
        'proof_id': str(uuid4()),
        'environment_id': environment.environment_id,
        'candidate_ref': policy['candidate_ref'],
        'policy_sha256': args.runtime_policy_sha256,
        'boot_id': boot,
        'observed_at': now(),
        'observed_monotonic_ms': ended,
        'run_id': policy['run_id'],
        'deployment_id': environment.deployment_id,
        'data_generation': environment.data_generation,
        'configuration_sha256': environment.configuration_sha256,
        'program_sha256': environment.description['program_source']['sha256'],
        'state': state,
        'reason_code': reason,
        'seen_running': state == 'RUNNING' or bool(previous and previous['seen_running']),
    }
    publish_observation(catalog, 'runtime-' + environment.environment_id, result)
    return {
        key: result[key]
        for key in ('proof_id', 'environment_id', 'observed_at', 'state', 'reason_code')
    }


def project_runtime(catalog, row, work):
    proof = runtime_observation(catalog, row['environment_id'])
    if proof is None or row['configuration_ref'] is None:
        return None
    configuration = decode(row['configuration_ref'].encode('utf-8'), RESOURCE)
    if (
        proof['candidate_ref'] != configuration.get('candidate_ref')
        or proof['deployment_id'] != work['deployment_id']
        or proof['data_generation'] != work['data_generation']
        or proof['configuration_sha256'] != row['configuration_sha256']
        or proof['program_sha256'] != row['program_source']
    ):
        return None
    try:
        require_fresh(proof)
        freshness = 'FRESH'
    except BAD_SAMPLE:
        freshness = 'STALE'
    return {
        'source': 'HOST',
        'observed_at': proof['observed_at'],
        'freshness': freshness,
        'runtime_state': proof['state'],
        'run_id': proof['run_id'] if proof['seen_running'] else None,
        'reason_code': proof['reason_code'],
    }
