"""Run fixed Restic against an explicitly installed COS repository."""

import fcntl
import os
import re
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from backend.app.management.release_artifacts import snapshot_file

from .environment_backup_package import (
    principal_for_process,
    private_root,
    read_policy,
    validate_location,
)
from .environment_files import (
    absolute,
    decode,
    digest,
    exact,
    identity,
    read_entry,
    read_protected,
    relative,
    require,
)
from .environment_installation import identity_record, sha_value, uuid_value
from .environment_restic_contract import VERSION
from .environment_restic_restore import fixed_password, restic_arguments, restic_call

PROFILE = 'cos-restic-profile.v1.json'
HOST = 'restic-host.v1.json'
INVALID = 'OFFHOST_BACKUP_INTENT_MISMATCH'
UNVERIFIED = 'OFFHOST_BACKUP_UNVERIFIED'
REGION = re.compile(r'[a-z]{2}-[a-z][a-z0-9-]{1,25}[a-z0-9]')
BUCKET = re.compile(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?-[0-9]{5,20}')
PREFIX_PART = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}')
SECRET_VALUE = re.compile(r'[!-~]+')
MACHINE_ID = Path('/etc/machine-id')
COMMON_FIELDS = (
    'host',
    'storage',
    'restic',
    'password_file',
    'storage_credentials',
    'work_directory',
    'work_identity',
)
RESTORE_LIMITS = (
    ('max_restore_seconds', 3600),
    ('max_restore_bytes', 1024**4),
    ('max_files', 8192),
)


def protected_reference(value, filename):
    reference = exact(value, ('path', 'sha256'), INVALID)
    path = absolute(reference['path'], INVALID)
    require(path.name == filename and sha_value(reference['sha256']), INVALID)
    return path, reference['sha256']


def load_cos_profile(reference):
    path, pin = protected_reference(reference, PROFILE)
    profile = read_policy(
        path,
        pin,
        PROFILE,
        ('provider', 'region', 'bucket', 'prefix', 'repository_id', 'environment_id'),
    )
    prefix = relative(profile['prefix'], INVALID)
    region, bucket = profile['region'], profile['bucket']
    require(
        profile['provider'] == 'TENCENT_COS'
        and type(region) is str
        and REGION.fullmatch(region) is not None
        and type(bucket) is str
        and len(bucket) <= 63
        and BUCKET.fullmatch(bucket) is not None
        and len(prefix.parts) <= 8
        and len(profile['prefix']) <= 256
        and all(PREFIX_PART.fullmatch(part) for part in prefix.parts)
        and sha_value(profile['repository_id'])
        and uuid_value(profile['environment_id']),
        INVALID,
    )
    return profile


def machine_fingerprint():
    raw = read_protected(MACHINE_ID)
    require(re.fullmatch(rb'[0-9a-f]{32}\n?', raw) is not None, UNVERIFIED)
    return digest(raw.rstrip(b'\n'))


def load_host(reference, role, principal):
    path, pin = protected_reference(reference, HOST)
    host = read_policy(
        path,
        pin,
        HOST,
        ('host_id', 'role', 'machine_id_sha256', 'maintenance_uid', 'shared_gid'),
    )
    require(
        uuid_value(host['host_id'])
        and host['role'] == role
        and type(host['maintenance_uid']) is int
        and host['maintenance_uid'] == principal.maintenance_uid
        and type(host['shared_gid']) is int
        and host['shared_gid'] == principal.group
        and sha_value(host['machine_id_sha256'])
        and host['machine_id_sha256'] == machine_fingerprint(),
        INVALID,
    )
    return host


def secret_reference(value):
    reference = exact(value, ('path', 'identity'), INVALID)
    identity_record(reference['identity'], INVALID)
    return absolute(reference['path'], INVALID)


def storage_environment(raw, work):
    record = exact(
        decode(raw, INVALID), ('access_key_id', 'secret_access_key', 'session_token'), INVALID
    )
    for field, limit in (
        ('access_key_id', 128),
        ('secret_access_key', 256),
        ('session_token', 3072),
    ):
        value = record[field]
        if field == 'session_token' and value is None:
            continue
        require(
            type(value) is str and 1 <= len(value) <= limit and SECRET_VALUE.fullmatch(value),
            INVALID,
        )
    environment = {
        'HOME': str(work),
        'TMPDIR': str(work),
        'LANG': 'C.UTF-8',
        'LC_ALL': 'C.UTF-8',
        'AWS_ACCESS_KEY_ID': record['access_key_id'],
        'AWS_SECRET_ACCESS_KEY': record['secret_access_key'],
    }
    if record['session_token'] is not None:
        environment['AWS_SESSION_TOKEN'] = record['session_token']
    return environment


def protected_fact(directory, name, principal):
    try:
        raw = read_entry(
            directory,
            name,
            owner=principal.maintenance_uid,
            group=principal.group,
            reject_writers=0o377,
        )
    except FileNotFoundError:
        return None
    return decode(raw, UNVERIFIED)


def cos_arguments(binary, password, profile):
    region = profile['region']
    repository = f's3:https://cos.{region}.myqcloud.com/{profile["bucket"]}/{profile["prefix"]}'
    return [
        *restic_arguments(binary, password, repository),
        '-o',
        's3.bucket-lookup=dns',
        '-o',
        f's3.region={region}',
    ]


@dataclass(frozen=True)
class OffhostRestic:
    host: dict
    profile: dict
    binary: Path
    password: Path
    secrets: Path
    work: Path
    principal: object
    package_boundaries: tuple


def admitted_restic(args, plan, role):
    principal = principal_for_process()
    host = load_host(plan['host'], role, principal)
    profile = load_cos_profile(plan['storage'])
    restic = exact(plan['restic'], ('path', 'sha256', 'version'), INVALID)
    require(restic['version'] == VERSION and sha_value(restic['sha256']), INVALID)
    binary = absolute(restic['path'], INVALID)
    password = secret_reference(plan['password_file'])
    secrets = secret_reference(plan['storage_credentials'])
    require(
        password != secrets
        and plan['password_file']['identity'] != plan['storage_credentials']['identity'],
        INVALID,
    )
    boundaries = (
        args.root,
        args.project,
        args.home,
        args.temporary,
        args.anchor.parent,
        binary.parent,
        password.parent,
        secrets.parent,
        absolute(plan['host']['path'], INVALID).parent,
        absolute(plan['storage']['path'], INVALID).parent,
    )
    work = validate_location(plan, 'work_directory', 'work_identity', boundaries)
    return OffhostRestic(
        host, profile, binary, password, secrets, work, principal, (*boundaries, work)
    )


@contextmanager
def locked_restic(plan, inputs, role):
    program = plan['restic']['sha256']
    require(snapshot_file(inputs.binary, 0o555)[0] == program, INVALID)
    with ExitStack() as opened:
        opened.enter_context(
            fixed_password(inputs.password, plan['password_file']['identity'], inputs.principal)
        )
        secret = opened.enter_context(
            fixed_password(
                inputs.secrets, plan['storage_credentials']['identity'], inputs.principal
            )
        )
        private_environment = storage_environment(os.read(secret, 4097), inputs.work)
        directory = opened.enter_context(
            private_root(inputs.work, plan['work_identity'], inputs.principal)
        )
        fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)

        def call(command, deadline, cwd, code):
            return restic_call(command, deadline, cwd, code, environment=private_environment)

        def recheck():
            require(
                snapshot_file(inputs.binary, 0o555)[0] == program
                and identity(inputs.work.stat(follow_symlinks=False))
                == identity(os.fstat(directory))
                == plan['work_identity']
                and load_host(plan['host'], role, inputs.principal) == inputs.host
                and load_cos_profile(plan['storage']) == inputs.profile,
                UNVERIFIED,
            )

        actual = call([str(inputs.binary), 'version'], 12, inputs.work, INVALID)
        require(actual.startswith(f'restic {VERSION} '.encode('ascii')), INVALID)
        command = cos_arguments(inputs.binary, inputs.password, inputs.profile)
        yield directory, command, call, recheck
        recheck()
