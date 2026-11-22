"""Capture and validate short-lived, host-installed attachment observations."""

from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import tempfile
from time import monotonic_ns
from uuid import uuid4

from backend.app.infrastructure.environment_control import read_control
from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    absolute,
    canonical,
    decode,
    digest,
    exact,
    identity,
    persisted_write,
    protected_directory,
    read_entry,
    require,
)
from backend.app.infrastructure.environment_installation import (
    load_installation as load_environment,
    sha_value,
    validate_target_file,
)
from backend.app.shared.time import utc_milliseconds

from .operation_contract import RESOURCE, installed_record, path_reference, version

FRESH_MS = 120_000
PATH_SCOPE = 'HOST_FILESYSTEM'
PROOF_VERSION = 1


def now():
    return utc_milliseconds(datetime.now(timezone.utc))


def machine_clock():
    boot = Path('/proc/sys/kernel/random/boot_id').read_text(encoding='ascii').strip()
    return boot, monotonic_ns() // 1_000_000


def require_fresh(proof):
    boot, time = machine_clock()
    require(
        proof['boot_id'] == boot
        and version(proof['observed_monotonic_ms'])
        and 0 <= time - proof['observed_monotonic_ms'] <= FRESH_MS,
        RESOURCE,
    )


def candidate_environment(candidate, runtime_sha):
    anchor, anchor_sha = path_reference(candidate['installation'])
    descriptor = installed_record(anchor, anchor_sha)
    program = absolute(descriptor.get('project'), RESOURCE)
    return load_environment(anchor, anchor_sha, runtime_sha, program)


def resource(kind, scope, locator, object_identity=None):
    return {'kind': kind, 'scope': scope, 'locator': locator, 'object_identity': object_identity}


def path_resource(kind, path, object_identity=None):
    return resource(kind, PATH_SCOPE, path.as_posix().removeprefix('/'), object_identity)


def roots_for(environment):
    return {
        kind: identity(environment.path(kind).stat(follow_symlinks=False))
        for kind in environment.roots
    }


def directory_facts(environment):
    meta = environment.environment_root.stat(follow_symlinks=False)
    require(stat.S_ISDIR(meta.st_mode) and meta.st_uid == 0, RESOURCE)
    roots = roots_for(environment)
    require(roots == environment.roots, RESOURCE)
    root = identity(meta)
    return root, roots


def public_facts(environment):
    return {
        'environment_id': environment.environment_id,
        'data_generation': environment.data_generation,
        'deployment_id': environment.deployment_id,
        'purpose': environment.description['purpose'],
        'configuration_sha256': environment.configuration_sha256,
        'program_sha256': environment.description['program_source']['sha256'],
    }


def observation_path(catalog, reference):
    return catalog.directory / 'observations' / (reference + '.json')


def private_control(environment):
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    with protected_directory(environment.environment_root) as parent:
        fd = os.open('control', flags, dir_fd=parent)
        try:
            require(identity(os.fstat(fd)) == environment.roots['control'], RESOURCE)
            return read_control(fd, environment)
        finally:
            os.close(fd)


def stopped_sample(environment):
    control = private_control(environment)
    socket = environment.path('runtime') / 'walle.sock'
    try:
        socket.lstat()
    except FileNotFoundError:
        pass
    else:
        raise EnvironmentFailure(RESOURCE)
    require(
        control['admission'] == 'CLOSED' and control['closed_reason'] == 'NORMAL_STOP', RESOURCE
    )
    database = validate_target_file(environment, environment.database.stat(follow_symlinks=False))
    return control['control_revision'], database, directory_facts(environment)


def invoke_observer(uid, gid, command, area, *, input_bytes=None, timeout=35):
    with tempfile.TemporaryDirectory(dir=area, prefix='probe-') as path:
        root = Path(path)
        root.chmod(0o755)
        paths = [root / name for name in ('home', 'tmp')]
        for item in paths:
            item.mkdir(mode=0o700)
            os.chown(item, uid, gid)
        executable = [
            '/usr/bin/setpriv',
            '--reuid',
            str(uid),
            '--regid',
            str(gid),
            '--clear-groups',
            '--no-new-privs',
            '--',
            '/usr/bin/python3',
            '-I',
            '-B',
            '-S',
            *map(str, command),
            '--home',
            str(paths[0]),
            '--temporary',
            str(paths[1]),
        ]
        result = subprocess.run(
            executable,
            env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'TZ': 'UTC'},
            cwd='/',
            **({'stdin': subprocess.DEVNULL} if input_bytes is None else {'input': input_bytes}),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
        require(result.returncode == 0 and 0 < len(result.stdout) <= 128 * 1024, RESOURCE)
        try:
            return json.loads(result.stdout)
        except (UnicodeError, ValueError) as error:
            raise EnvironmentFailure(RESOURCE) from error


def verified_workspace(reference, args, area):
    source, source_sha = reference
    policy = installed_record(source, source_sha)
    uid = policy.get('uid')
    require(type(uid) is int and uid > 0, RESOURCE)
    gid = pwd.getpwuid(uid).pw_gid
    facts = invoke_observer(
        uid,
        gid,
        [
            Path(__file__).resolve().parents[3] / 'tools/linux_runtime/manage_registry.py',
            'workspace',
            '--project',
            args.project,
            '--program-sha256',
            args.program_sha256,
            '--runtime-entry',
            args.runtime_entry,
            '--root',
            args.root,
            '--sha256',
            args.sha256,
            '--anchor',
            source,
            '--anchor-sha256',
            source_sha,
        ],
        area,
    )
    signed = dict(facts)
    signature = signed.pop('evidence_sha256')
    signed.pop('observed_at')
    require(
        digest(canonical(signed)) == signature
        and facts['repository_ref'] == policy['repository_ref'],
        RESOURCE,
    )
    return policy, facts


def capture(catalog, reference, args, runtime_entry):
    require(os.geteuid() == 0, RESOURCE)
    expected = catalog.candidates.get(reference)
    require(expected is not None, RESOURCE)
    candidate = catalog.candidate(reference, expected)
    environment = candidate_environment(candidate, args.sha256)
    require(
        runtime_entry['verify_program'](environment.project)
        == public_facts(environment)['program_sha256'],
        RESOURCE,
    )
    area = catalog.directory / 'observations'
    boot, started = machine_clock()
    before = stopped_sample(environment)
    diagnosis = invoke_observer(
        environment.application_uid,
        environment.group,
        [
            args.runtime_entry,
            'environment',
            '--action',
            'diagnose',
            '--project',
            environment.project,
            '--root',
            args.root,
            '--sha256',
            args.sha256,
            '--anchor',
            environment.anchor,
            '--anchor-sha256',
            environment.anchor_sha256,
        ],
        area,
    )
    require(
        diagnosis['status'] == 'DATABASE_READY'
        and diagnosis['admission'] == 'CLOSED'
        and diagnosis['environment_id'] == environment.environment_id
        and diagnosis['data_generation'] == environment.data_generation,
        RESOURCE,
    )
    repository, git = verified_workspace(path_reference(candidate['workspace']), args, area)
    row = next(
        (
            item
            for item in repository['worktrees']
            if item['environment_id'] == environment.environment_id
        ),
        None,
    )
    found = next(
        (item for item in git['worktrees'] if item['environment_id'] == environment.environment_id),
        None,
    )
    require(
        row is not None
        and found is not None
        and row['purpose'] == environment.description['purpose']
        and found['commit'] == candidate['baseline_commit'],
        RESOURCE,
    )
    after = stopped_sample(environment)
    ended_boot, ended = machine_clock()
    require(before == after and boot == ended_boot and 0 <= ended - started <= FRESH_MS, RESOURCE)
    control, database, (root, roots) = after
    workspace = absolute(row['path'], RESOURCE)
    claims = [
        path_resource('INSTALLATION_ROOT', environment.environment_root, root),
        path_resource('WORKTREE', workspace, row['identity']),
        path_resource('DATA_ROOT', environment.path('data'), roots['data']),
        path_resource('CONTROL_ROOT', environment.path('control'), roots['control']),
        path_resource('BUSINESS_DATABASE', environment.database, database),
        path_resource(
            'STABLE_LOCK', environment.path('lock') / 'environment.lock', environment.lock_identity
        ),
        path_resource('UPSTREAM_SOCKET', environment.path('runtime') / 'walle.sock'),
        resource('GIT_BRANCH', 'REPOSITORY:' + git['repository_ref'], found['branch']),
        resource(
            'PUBLIC_ORIGIN', 'HTTPS', 'e-' + environment.environment_id + '.walle-dev.test:9443'
        ),
    ]
    proof = {
        'format_version': PROOF_VERSION,
        **catalog.scope,
        'proof_id': str(uuid4()),
        'candidate_ref': reference,
        'candidate_sha256': expected,
        'boot_id': boot,
        'observed_at': now(),
        'observed_monotonic_ms': ended,
        **public_facts(environment),
        'control_revision': control,
        'database_initialized_at': diagnosis['initialized_at'],
        'installation_identity': root,
        'root_identities': roots,
        'repository_ref': git['repository_ref'],
        'worktree_evidence_sha256': git['evidence_sha256'],
        'branch': found['branch'],
        'commit': found['commit'],
        'claims': claims,
    }
    publish_observation(catalog, reference, proof)
    return {
        key: proof[key] for key in ('proof_id', 'environment_id', 'candidate_ref', 'observed_at')
    }


def publish_observation(catalog, reference, proof):
    path = observation_path(catalog, reference)
    with protected_directory(path.parent) as directory:
        fcntl.flock(directory, fcntl.LOCK_EX)
        try:
            original = read_entry(directory, path.name, owner=0)
        except FileNotFoundError:
            original = None
        if original is not None:
            previous = decode(original, RESOURCE)
            require(
                previous['boot_id'] != proof['boot_id']
                or previous['observed_monotonic_ms'] < proof['observed_monotonic_ms'],
                RESOURCE,
            )
        persisted_write(
            directory, path.name, canonical(proof), mode=0o444, replace=original is not None
        )


def observe_for_attach(catalog, intent, candidate, runtime_sha):
    reference = intent['candidate_ref']
    proof = exact(
        installed_record(observation_path(catalog, reference)),
        (
            'format_version',
            *catalog.scope,
            'proof_id',
            'candidate_ref',
            'candidate_sha256',
            'boot_id',
            'observed_at',
            'observed_monotonic_ms',
            'environment_id',
            'data_generation',
            'deployment_id',
            'purpose',
            'configuration_sha256',
            'program_sha256',
            'control_revision',
            'database_initialized_at',
            'installation_identity',
            'root_identities',
            'repository_ref',
            'worktree_evidence_sha256',
            'branch',
            'commit',
            'claims',
        ),
        RESOURCE,
    )
    require(
        proof['format_version'] == PROOF_VERSION
        and proof['candidate_ref'] == reference
        and proof['candidate_sha256'] == intent['expected_candidate_sha256']
        and all(proof[key] == value for key, value in catalog.scope.items())
        and sha_value(proof['worktree_evidence_sha256'])
        and proof['commit'] == candidate['baseline_commit'],
        RESOURCE,
    )
    require_fresh(proof)
    environment = candidate_environment(candidate, runtime_sha)
    require(all(proof[key] == value for key, value in public_facts(environment).items()), RESOURCE)
    root, roots = directory_facts(environment)
    require(root == proof['installation_identity'] and roots == proof['root_identities'], RESOURCE)
    return proof
