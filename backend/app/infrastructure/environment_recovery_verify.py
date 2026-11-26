"""Start and independently verify the closed read-only recovery replica."""

import fcntl
import json
import os
import stat
import subprocess
from contextlib import ExitStack
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace
from urllib.parse import urlsplit

from backend.app.management.attachment_observation import now
from backend.app.management.release_artifacts import snapshot_file

from .environment_backup_package import private_root, validate_location
from .environment_control import read_control, stopped_for_policy
from .environment_files import (
    MAX_REVISION,
    EnvironmentFailure,
    canonical,
    decode,
    digest,
    identity,
    persisted_write,
    protected_directory,
    read_protected,
    require,
)
from .environment_installation import (
    ANCHOR_NAME,
    RECOVERY_EVIDENCE,
    gateway_verifier_names,
    load_installation,
    read_access_policy,
    sha_value,
    uuid_value,
    version_record,
)
from .environment_lock import NativeEnvironmentFiles
from .environment_recovery_installation import INSTALL_RECEIPT, checked_ref
from .environment_recovery_probe import check_application, unix_reply
from .environment_recovery_read import (
    POLICY as READ_POLICY,
)
from .environment_recovery_read import (
    TUPLE_FIELDS,
    protected_receipt,
    read_policy,
)
from .environment_restore import RECEIPT

POLICY = 'recovery-verification-policy.v1.json'
INVALID = 'RECOVERY_VERIFICATION_INTENT_MISMATCH'
UNVERIFIED = 'RECOVERY_VERIFICATION_UNVERIFIED'
SETPRIV = Path('/usr/bin/setpriv')
HOST_PYTHON = '/usr/bin/python3'
ENVIRONMENT_SOURCE = (
    'import json,runpy,sys; from pathlib import Path; '
    'entry=runpy.run_path(sys.argv[1]); '
    'print(json.dumps(entry["minimum_environment"](Path(sys.argv[2]),Path(sys.argv[3]))))'
)
MINIMAL_HOST = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'TZ': 'UTC'}


def verification_inputs(args):
    require(args.anchor.name == POLICY and sha_value(args.anchor_sha256), INVALID)
    raw = read_protected(args.anchor)
    require(digest(raw) == args.anchor_sha256, INVALID)
    plan = decode(raw, INVALID)
    version_record(
        plan,
        (
            'verification_id',
            'installation',
            'read_policy_sha256',
            'home',
            'home_identity',
            'temporary',
            'temporary_identity',
            'requirement_id',
            'document_id',
            'markdown_sha256',
        ),
        INVALID,
    )
    require(
        uuid_value(plan['verification_id'])
        and all(sha_value(plan[key]) for key in ('read_policy_sha256', 'markdown_sha256'))
        and all(
            type(plan[key]) is int and 1 <= plan[key] <= MAX_REVISION
            for key in ('requirement_id', 'document_id')
        ),
        INVALID,
    )
    anchor, expected = checked_ref(plan['installation'], ANCHOR_NAME)
    installation = load_installation(anchor, expected, args.sha256, args.project)
    bind = installation.description.get('recovery_replica')
    require(
        bind is not None
        and installation.ingress_group is None
        and installation.description['program_source']['sha256'] == args.program_sha256
        and plan['verification_id'] not in (bind['operation_id'], bind['run_id']),
        INVALID,
    )
    bounds = (
        anchor.parent.parent,
        args.anchor.parent,
        args.root,
        args.project,
        installation.schema,
    )
    home = validate_location(plan, 'home', 'home_identity', bounds)
    temporary = validate_location(plan, 'temporary', 'temporary_identity', (*bounds, home))
    return plan, installation, home, temporary


def subject(installation, policy_sha):
    base = installation.anchor.parent / RECOVERY_EVIDENCE
    prepared = decode(read_protected(base / INSTALL_RECEIPT), UNVERIFIED)
    verify = base / READ_POLICY
    require(
        prepared['status'] == 'RECOVERY_REPLICA_PREPARED'
        and prepared['anchor_sha256'] == installation.anchor_sha256
        and prepared['recovery_read_policy_sha256'] == policy_sha
        and prepared['recovery_read_policy'] == str(verify),
        INVALID,
    )
    policy = read_policy(verify, policy_sha)
    bind = installation.description['recovery_replica']
    require(
        all(policy[key] == getattr(installation, key) for key in TUPLE_FIELDS)
        and policy['installation_sha256'] == installation.anchor_sha256
        and policy['rehearsal_receipt']['path'] == str(base / RECEIPT)
        and policy['rehearsal_receipt']['sha256'] == bind['rehearsal_receipt_sha256']
        and policy['operation_id'] == prepared['operation_id'] == bind['operation_id']
        and policy['run_id'] == prepared['run_id'] == bind['run_id'],
        UNVERIFIED,
    )
    receipt = decode(protected_receipt(policy['rehearsal_receipt']), UNVERIFIED)
    require(receipt['backup_manifest_sha256'] == bind['backup_manifest_sha256'], UNVERIFIED)
    return base, verify, policy, receipt


def replica_state(installation, policy):
    installation.check_hold()
    with protected_directory(installation.path('control')) as directory:
        require(identity(os.fstat(directory)) == installation.roots['control'], UNVERIFIED)
        control = read_control(directory, installation)
        reference = {'operation_id': policy['operation_id'], 'plan_sha256': control['plan_sha256']}
        require(
            stopped_for_policy(directory, control, reference)
            and control['outbound_hold'] is True
            and digest(canonical(control)) == policy['control_sha256'],
            UNVERIFIED,
        )
    with protected_directory(installation.path('data')) as directory:
        require(
            identity(os.fstat(directory)) == installation.roots['data']
            and set(os.listdir(directory)) == {installation.database.name},
            UNVERIFIED,
        )
        props = os.stat(installation.database.name, dir_fd=directory, follow_symlinks=False)
        require(
            (props.st_uid, props.st_gid) == (0, installation.group)
            and identity(props) == policy['database']['identity'],
            UNVERIFIED,
        )
        measured, _ = snapshot_file(installation.database, 0o440, policy['database']['bytes'])
        require(measured == policy['database']['sha256'], UNVERIFIED)


def private_environment(installation, args, home, temporary):
    with protected_directory(SETPRIV.parent):
        props = SETPRIV.lstat()
        require(
            stat.S_ISREG(props.st_mode)
            and props.st_uid == 0
            and props.st_nlink == 1
            and not stat.S_IMODE(props.st_mode) & 0o022,
            INVALID,
        )
    credentials = [
        str(SETPRIV),
        '--reuid',
        str(installation.application_uid),
        '--regid',
        str(installation.group),
        '--clear-groups',
        '--no-new-privs',
        '--',
    ]
    checked = subprocess.run(
        [
            *credentials,
            HOST_PYTHON,
            '-I',
            '-B',
            '-S',
            '-c',
            ENVIRONMENT_SOURCE,
            str(args.runtime_entry),
            str(home),
            str(temporary),
        ],
        env=MINIMAL_HOST,
        capture_output=True,
        check=False,
        timeout=12,
    )
    require(checked.returncode == 0 and len(checked.stdout) <= 4096, UNVERIFIED)
    environment = json.loads(checked.stdout)
    require(
        environment == {**MINIMAL_HOST, 'HOME': str(home), 'TMPDIR': str(temporary)}, UNVERIFIED
    )
    return credentials, environment


def await_peer(job, socket_path, lock, reply):
    deadline = monotonic() + 35
    while monotonic() < deadline:
        require(job.poll() is None, 'RECOVERY_APPLICATION_START_FAILED')
        if os.path.lexists(socket_path) and lock.observer_pid() == job.pid:
            require(stat.S_ISSOCK(socket_path.lstat().st_mode), UNVERIFIED)
            try:
                reply('GET', '/api/v1/environment')
            except (ConnectionRefusedError, FileNotFoundError):
                pass
            else:
                return
        sleep(0.1)
    raise EnvironmentFailure('RECOVERY_APPLICATION_START_TIMED_OUT')


def stop_owned(job):
    if job.poll() is None:
        job.terminate()
    try:
        return job.wait(timeout=16)
    except subprocess.TimeoutExpired:
        job.kill()
        job.wait(timeout=8)
        raise EnvironmentFailure('RECOVERY_APPLICATION_STOP_UNVERIFIED', uncertain=True) from None


@dataclass(frozen=True)
class FixedReadProbe:
    action: str
    socket_name: str
    policy_flag: str
    policy_path: Path
    policy_sha256: str
    operation_id: str
    private_socket: bool = False


def verification_principal(access, environment_id, *, private_socket):
    verifiers = gateway_verifier_names(access)
    if private_socket:
        require(verifiers, UNVERIFIED)
        return min(verifiers)
    principal = 'automation-' + environment_id
    require(principal in verifiers, UNVERIFIED)
    return principal


def probe_fixed_reader(args, entry, installation, home, temporary, probe, check):
    native = NativeEnvironmentFiles(args.root)
    lock = installation.lock(native)
    socket_path = installation.path('runtime') / probe.socket_name
    require(lock.observer_pid() is None and not os.path.lexists(socket_path), UNVERIFIED)
    credentials, environment = private_environment(installation, args, home, temporary)
    manifest, _ = entry['verify_runtime'](args.root, args.sha256)
    executable = args.root / manifest['python']['executable_ref']
    launcher = installation.project / 'tools/linux_runtime/serve_environment.py'
    command = [
        *credentials,
        str(executable),
        *entry['FLAGS'],
        str(launcher),
        probe.action,
        '--root',
        str(args.root),
        '--sha256',
        args.sha256,
        '--home',
        str(home),
        '--temporary',
        str(temporary),
        '--project',
        str(installation.project),
        '--anchor',
        str(installation.anchor),
        '--anchor-sha256',
        installation.anchor_sha256,
        '--runtime-entry',
        str(args.runtime_entry),
        '--operation-id',
        probe.operation_id,
        probe.policy_flag,
        str(probe.policy_path),
        probe.policy_flag + '-sha256',
        probe.policy_sha256,
    ]
    access = read_access_policy(installation)
    principal = verification_principal(
        access, installation.environment_id, private_socket=probe.private_socket
    )
    headers = {
        'Host': urlsplit(access['public_origin']).netloc,
        'X-WALL-E-Auth-Principal': principal,
        'X-WALL-E-Client': 'automation-v1',
        'X-WALL-E-Environment-ID': installation.environment_id,
        'X-WALL-E-Binding-Protocol': '1',
    }
    with subprocess.Popen(
        command,
        env=environment,
        cwd=temporary,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    ) as job:
        peer = (job.pid, installation.application_uid, installation.group)

        def reply(method, target, *, data_generation=installation.data_generation):
            return unix_reply(
                socket_path,
                peer,
                method,
                target,
                {**headers, 'X-WALL-E-Data-Generation': data_generation},
            )

        try:
            await_peer(job, socket_path, lock, reply)
            if probe.private_socket:
                facts = socket_path.lstat()
                require(
                    facts.st_uid == installation.application_uid
                    and facts.st_gid == (installation.ingress_group or installation.group)
                    and stat.S_IMODE(facts.st_mode) == 0o600,
                    UNVERIFIED,
                )
            verified = check(reply)
            require(job.poll() is None and lock.observer_pid() == job.pid, UNVERIFIED)
        finally:
            stopped = stop_owned(job)
        require(
            stopped == 0 and lock.observer_pid() is None and not os.path.lexists(socket_path),
            'RECOVERY_APPLICATION_STOP_UNVERIFIED',
        )
    return verified


def probe_replica(args, entry, installation, home, temporary, read_path, policy, receipt, plan):
    probe = FixedReadProbe(
        '_serve-recovery',
        'walle.sock',
        '--recovery-read-policy',
        read_path,
        plan['read_policy_sha256'],
        policy['operation_id'],
    )
    check = partial(
        check_application,
        policy=policy,
        read_sha=probe.policy_sha256,
        wrong_generation=receipt['source_data_generation'],
        plan=plan,
    )
    return probe_fixed_reader(args, entry, installation, home, temporary, probe, check)


def verify_recovery_replica(args, entry):
    require(os.geteuid() == 0, INVALID)
    plan, installation, home, temporary = verification_inputs(args)
    principal = SimpleNamespace(
        maintenance_uid=installation.application_uid, group=installation.group
    )
    with ExitStack() as resources:
        root = resources.enter_context(protected_directory(installation.anchor.parent))
        fcntl.flock(root, fcntl.LOCK_EX | fcntl.LOCK_NB)
        resources.enter_context(private_root(home, plan['home_identity'], principal))
        resources.enter_context(private_root(temporary, plan['temporary_identity'], principal))
        evidence, policy_path, policy, receipt = subject(installation, plan['read_policy_sha256'])
        replica_state(installation, policy)
        directory = resources.enter_context(protected_directory(evidence))
        name = f'local-verified-{plan["verification_id"]}.v1.json'
        try:
            existed = read_protected(evidence / name)
        except FileNotFoundError:
            existed = None
        base = {
            'format_version': 1,
            'status': 'LOCAL_VERIFIED',
            'verification_id': plan['verification_id'],
            'verification_policy_sha256': args.anchor_sha256,
            'backup_id': receipt['backup_id'],
            'backup_manifest_sha256': receipt['backup_manifest_sha256'],
            'runtime_manifest_sha256': args.sha256,
            'schema_manifest_sha256': installation.description['schema_manifest_sha256'],
            'program_snapshot_sha256': args.program_sha256,
            'frontend_index_sha256': installation.description['recovery_replica'][
                'frontend_index_sha256'
            ],
            'rehearsal_receipt_sha256': policy['rehearsal_receipt']['sha256'],
            'recovery_read_policy_sha256': plan['read_policy_sha256'],
            **{field: policy[field] for field in (*TUPLE_FIELDS, 'control_revision', 'run_id')},
            'verified_scopes': policy['verified_scopes'],
            'database_sha256': policy['database']['sha256'],
            'logical_content_sha256': receipt['content_sha256'],
            'document_lookup': {
                key: plan[key] for key in ('requirement_id', 'document_id', 'markdown_sha256')
            },
            'outbound_hold_required': True,
        }
        if existed is not None:
            recorded = decode(existed, UNVERIFIED)
            fields = tuple(key for key in base if key != 'format_version')
            version_record(recorded, (*fields, 'verified_at'), UNVERIFIED)
            require(
                type(recorded['verified_at']) is str
                and all(recorded[key] == value for key, value in base.items()),
                UNVERIFIED,
            )
            return recorded
        details = probe_replica(
            args, entry, installation, home, temporary, policy_path, policy, receipt, plan
        )
        replica_state(installation, policy)
        require(
            details == base['document_lookup']
            and subject(installation, plan['read_policy_sha256'])
            == (evidence, policy_path, policy, receipt),
            UNVERIFIED,
        )
        recorded = {**base, 'verified_at': now()}
        persisted_write(directory, name, canonical(recorded), mode=0o444)
        try:
            require(read_protected(evidence / name) == canonical(recorded), UNVERIFIED)
        except (EnvironmentFailure, OSError) as error:
            raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
        return recorded
