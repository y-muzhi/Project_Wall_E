"""Open a pinned P1 Linux installation and its fixed environment roots."""

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat

from .environment_files import (
    SHA256,
    absolute,
    check_ext4,
    decode,
    digest,
    exact,
    identity,
    no_acl,
    protected_directory,
    read_protected,
    relative,
    require,
)
from .environment_lock import EnvironmentLock, PROTOCOL

UUID_V4 = re.compile(r'[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}')
IDENTITY_NUM = re.compile(r'0|[1-9][0-9]{0,19}')
CAPABILITIES = {'DOCUMENT_READ', 'DOCUMENT_WRITE'}
PURPOSES = {'DEVELOPMENT', 'INTEGRATION'}
DIRECTORIES = ('lock', 'control', 'data', 'runtime', 'log', 'temporary', 'frontend', 'maintenance')
ANCHOR_NAME = 'installation.v1.json'
CONFIG_NAME = 'configuration.v1.json'
ACCESS_NAME = 'access-policy.v1.json'
HOLD_NAME = 'host-hold.v1.json'


def uuid_value(value):
    return type(value) is str and UUID_V4.fullmatch(value) is not None


def sha_value(value):
    return type(value) is str and SHA256.fullmatch(value) is not None


def version_record(record, fields, code):
    exact(record, ('format_version', *fields), code)
    require(type(record['format_version']) is int and record['format_version'] == 1, code)


def identity_record(record, code):
    exact(record, ('device', 'inode'), code)
    require(
        all(type(value) is str and IDENTITY_NUM.fullmatch(value) for value in record.values()), code
    )


@dataclass(frozen=True)
class Installation:
    anchor: Path
    anchor_sha256: str
    configuration_sha256: str
    description: dict
    roots: dict
    environment_id: str
    data_generation: str
    deployment_id: str
    application_uid: int
    maintenance_uid: int
    group: int
    lock_identity: dict
    project: Path
    schema: Path

    def path(self, kind):
        return self.anchor.parent / kind

    @property
    def database_relative(self):
        return relative(self.description['database_relative_path'], 'INVALID_ENVIRONMENT_CONFIG')

    @property
    def database(self):
        return self.path('data') / self.database_relative

    def expected_directory(self, kind):
        if kind == 'lock':
            return 0, self.group, 0o550
        if kind in ('control', 'data'):
            return 0, self.group, 0o2770
        if kind == 'maintenance':
            return self.maintenance_uid, self.group, 0o700
        if kind == 'frontend':
            return 0, 0, 0o755
        return self.application_uid, self.group, 0o700

    def check_identity(self, *, maintenance):
        uid = self.maintenance_uid if maintenance else self.application_uid
        require(
            os.geteuid() == uid
            and os.getegid() == self.group
            and set(os.getgroups()) <= {self.group},
            'ENVIRONMENT_IDENTITY_NOT_ADMITTED',
        )

    @contextmanager
    def directory(self, native, kind):
        requested = self.path(kind)
        with protected_directory(self.anchor.parent) as parent:
            flags = os.O_RDONLY | os.O_DIRECTORY
            fd = native.open_beneath(parent, kind, flags)
            try:
                metadata = os.fstat(fd)
                require(
                    (metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode))
                    == self.expected_directory(kind)
                    and identity(metadata) == self.roots[kind]
                    and identity(requested.stat(follow_symlinks=False)) == self.roots[kind],
                    'ENVIRONMENT_ROOT_IDENTITY_MISMATCH',
                )
                check_ext4(fd)
                no_acl(fd)
                yield fd
            finally:
                os.close(fd)

    def lock(self, native):
        return EnvironmentLock(
            native, self.path('lock'), self.roots['lock'], self.lock_identity, self.group
        )

    def check_hold(self):
        code = 'HOST_RECOVERY_HOLD'
        record = decode(read_protected(self.anchor.parent.parent / HOLD_NAME), code)
        version_record(record, ('recovery_hold', 'allowed_deployments'), code)
        require(
            type(record['recovery_hold']) is bool and type(record['allowed_deployments']) is list,
            code,
        )
        allowed = set()
        for item in record['allowed_deployments']:
            exact(item, ('environment_id', 'data_generation', 'deployment_id'), code)
            key = (item['environment_id'], item['data_generation'], item['deployment_id'])
            require(all(uuid_value(value) for value in key) and key not in allowed, code)
            allowed.add(key)
        require(
            not record['recovery_hold']
            or (self.environment_id, self.data_generation, self.deployment_id) in allowed,
            code,
        )


def _access_policy(anchor, config, environment_id):
    code = 'INVALID_ENVIRONMENT_ACCESS'
    ref = exact(config['access_policy_ref'], ('name', 'sha256'), code)
    require(ref['name'] == ACCESS_NAME and sha_value(ref['sha256']), code)
    raw = read_protected(anchor.parent / ACCESS_NAME)
    require(digest(raw) == ref['sha256'], code)
    record = decode(raw, code)
    version_record(
        record, ('environment_id', 'public_origin', 'principals', 'upstream_socket'), code
    )
    require(
        record['environment_id'] == environment_id
        and record['public_origin'] == f'https://e-{environment_id}.walle-dev.test:9443'
        and record['upstream_socket'] == str(anchor.parent / 'runtime' / 'walle.sock')
        and type(record['principals']) is list
        and bool(record['principals']),
        code,
    )
    seen = set()
    for principal in record['principals']:
        exact(principal, ('principal_id', 'client_kind', 'permission'), code)
        name = principal['principal_id']
        require(
            type(name) is str
            and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}', name)
            and name not in seen
            and principal['client_kind'] in ('WEB', 'AUTOMATION')
            and principal['permission'] in ('READ_ONLY', 'DEVELOP'),
            code,
        )
        seen.add(name)


def _validate_description(anchor, config, record, runtime_sha256):
    code = 'INVALID_ENVIRONMENT_CONFIG'
    version_record(
        config,
        (
            'environment_id',
            'data_generation',
            'purpose',
            'required_capabilities',
            'enabled_capabilities',
            'program_source',
            'runtime_manifest_sha256',
            'schema_manifest_sha256',
            'database_relative_path',
            'access_policy_ref',
            'model_permission_ref',
            *(f'{kind}_root' for kind in DIRECTORIES[:-1]),
        ),
        code,
    )
    require(
        config['purpose'] in PURPOSES
        and all(config[field] == record[field] for field in ('environment_id', 'data_generation'))
        and config['runtime_manifest_sha256'] == runtime_sha256 == record['runtime_manifest_sha256']
        and config['schema_manifest_sha256'] == record['schema_manifest_sha256']
        and config['model_permission_ref'] is None,
        code,
    )
    for field in ('required_capabilities', 'enabled_capabilities'):
        values = config[field]
        require(
            type(values) is list
            and len(values) == 2
            and all(type(value) is str for value in values)
            and set(values) == CAPABILITIES,
            code,
        )
    for kind in DIRECTORIES[:-1]:
        require(config[f'{kind}_root'] == str(anchor.parent / kind), code)
    database = relative(config['database_relative_path'], code)
    require(len(database.parts) == 1 and database.suffix == '.sqlite', code)
    source = exact(config['program_source'], ('kind', 'sha256'), code)
    require(
        source['kind'] == 'WORKSPACE_SNAPSHOT' and source['sha256'] == record['program_sha256'],
        code,
    )
    _access_policy(anchor, config, record['environment_id'])


def load_installation(anchor, expected, runtime_sha256, project):
    code = 'INSTALLATION_ANCHOR_MISMATCH'
    require(anchor.name == ANCHOR_NAME and sha_value(expected), code)
    raw = read_protected(anchor)
    require(digest(raw) == expected, code)
    record = decode(raw, code)
    version_record(
        record,
        (
            'environment_id',
            'data_generation',
            'deployment_id',
            'configuration_sha256',
            'runtime_manifest_sha256',
            'schema_manifest_sha256',
            'program_sha256',
            'lock_protocol',
            'lock_identity',
            'root_identities',
            'application_uid',
            'maintenance_uid',
            'shared_gid',
            'project',
            'schema',
        ),
        code,
    )
    require(
        all(
            uuid_value(record[field])
            for field in ('environment_id', 'data_generation', 'deployment_id')
        ),
        code,
    )
    require(
        all(
            sha_value(record[field])
            for field in (
                'configuration_sha256',
                'runtime_manifest_sha256',
                'schema_manifest_sha256',
                'program_sha256',
            )
        ),
        code,
    )
    application_uid, maintenance_uid, gid = (
        record[field] for field in ('application_uid', 'maintenance_uid', 'shared_gid')
    )
    require(
        all(
            type(value) is int and 1 <= value < 2**31
            for value in (application_uid, maintenance_uid, gid)
        )
        and application_uid != maintenance_uid
        and record['lock_protocol'] == PROTOCOL
        and record['project'] == str(project),
        code,
    )
    roots = exact(record['root_identities'], DIRECTORIES, code)
    for metadata in (*roots.values(), record['lock_identity']):
        identity_record(metadata, code)
    require(len({tuple(item.values()) for item in roots.values()}) == len(DIRECTORIES), code)
    config_raw = read_protected(anchor.parent / CONFIG_NAME)
    require(digest(config_raw) == record['configuration_sha256'], code)
    config = decode(config_raw, 'INVALID_ENVIRONMENT_CONFIG')
    _validate_description(anchor, config, record, runtime_sha256)
    schema = absolute(record['schema'], code)
    with protected_directory(schema):
        pass
    return Installation(
        anchor,
        expected,
        record['configuration_sha256'],
        config,
        roots,
        record['environment_id'],
        record['data_generation'],
        record['deployment_id'],
        application_uid,
        maintenance_uid,
        gid,
        record['lock_identity'],
        project,
        schema,
    )


def validate_target_file(installation, metadata):
    require(
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_nlink == 1
        and metadata.st_uid in (installation.application_uid, installation.maintenance_uid)
        and metadata.st_gid == installation.group
        and stat.S_IMODE(metadata.st_mode) == 0o660,
        'TARGET_OWNERSHIP_UNVERIFIED',
    )
    return identity(metadata)


def database_identity(installation, data_fd):
    path = str(installation.database_relative)
    try:
        metadata = os.stat(path, dir_fd=data_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    return validate_target_file(installation, metadata)
