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
    canonical,
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
WORKSPACE_PURPOSES = {'DEVELOPMENT', 'INTEGRATION'}
CANDIDATE_PURPOSE = 'CANDIDATE'
PURPOSES = {*WORKSPACE_PURPOSES, CANDIDATE_PURPOSE}
CANDIDATE_BINDING_FIELDS = (
    'operation_id',
    'release_id',
    'delivery_operation_id',
    'policy_sha256',
    'candidate_sha256',
    'manifest_sha256',
    'frontend_index_sha256',
)
RECOVERY_BINDING_FIELDS = (
    'operation_id',
    'run_id',
    'preparation_policy_sha256',
    'backup_manifest_sha256',
    'rehearsal_receipt_sha256',
    'frontend_index_sha256',
)
DEPLOYMENT_BINDING_FIELDS = (
    'base_installation_sha256',
    'base_project',
    'source_deployment_id',
    'source_configuration_sha256',
    'preparation_policy_sha256',
    'authorization_mode',
    'release_id',
    'manifest_sha256',
    'frontend_index_sha256',
)
DIRECTORIES = ('lock', 'control', 'data', 'runtime', 'log', 'temporary', 'frontend', 'maintenance')
DEPLOYMENTS = 'deployments'
GENERATIONS = 'data-generations'
GENERATION_RECEIPT = 'restore-generation.v1.json'
RESTORE_MODE = 'RESTORE_DATA'
ANCHOR_NAME = 'installation.v1.json'
CONFIG_NAME = 'configuration.v1.json'
ACCESS_NAME = 'access-policy.v1.json'
HOLD_NAME = 'host-hold.v1.json'
RECOVERY_EVIDENCE = 'recovery-evidence'
RECOVERY_FRONTEND_INDEX = 'frontend-index.v1.json'


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
    ingress_group: int | None = None
    restore_generation_sha256: str | None = None

    @property
    def environment_root(self):
        if 'deployment_slot' in self.description:
            return self.anchor.parent.parent.parent
        return self.anchor.parent

    def path(self, kind):
        if kind == 'data' and self.restore_generation_sha256 is not None:
            return restored_data_root(self.environment_root, self.data_generation)
        parent = self.anchor.parent if kind == 'frontend' else self.environment_root
        return parent / kind

    @property
    def database_relative(self):
        return relative(self.description['database_relative_path'], 'INVALID_ENVIRONMENT_CONFIG')

    @property
    def database(self):
        return self.path('data') / self.database_relative

    def expected_directory(self, kind):
        if kind == 'lock' or (
            kind in ('control', 'data') and 'recovery_replica' in self.description
        ):
            return 0, self.group, 0o550
        if kind in ('control', 'data'):
            return 0, self.group, 0o2770
        if kind == 'maintenance':
            return self.maintenance_uid, self.group, 0o700
        if kind == 'frontend':
            return 0, 0, 0o755
        if kind == 'runtime' and self.ingress_group is not None:
            return self.application_uid, self.ingress_group, 0o2710
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
        with protected_directory(requested.parent) as parent:
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

    def check_hold(self, *, offline=False):
        from .environment_host_hold import enforce_host_hold, host_hold_record

        root = self.environment_root.parent
        record = host_hold_record(
            read_protected(root / HOLD_NAME), identity(root.stat(follow_symlinks=False))
        )
        enforce_host_hold(record, self, offline=offline)

    def host_admission(self):
        from .environment_host_hold import ordinary_host_admission

        return ordinary_host_admission(self)


def _access_policy(anchor, environment_root, config, environment_id):
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
        and record['upstream_socket'] == str(environment_root / 'runtime' / 'walle.sock')
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


def _validate_description(anchor, environment_root, config, record, runtime_sha256):
    code = 'INVALID_ENVIRONMENT_CONFIG'
    candidate = config.get('purpose') == CANDIDATE_PURPOSE
    replica = 'recovery_replica' in config
    slot = 'deployment_slot' in config
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
            *(('release_validation',) if candidate else ()),
            *(('recovery_replica',) if replica else ()),
            *(('deployment_slot',) if slot else ()),
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
        root = anchor.parent if kind == 'frontend' else environment_root
        expected = root / kind
        if kind == 'data' and 'restore_generation_sha256' in record:
            expected = restored_data_root(environment_root, record['data_generation'])
        require(config[f'{kind}_root'] == str(expected), code)
    database = relative(config['database_relative_path'], code)
    require(len(database.parts) == 1 and database.suffix == '.sqlite', code)
    source = exact(config['program_source'], ('kind', 'sha256'), code)
    require(
        source['kind'] == ('FIXED_RELEASE' if candidate or slot else 'WORKSPACE_SNAPSHOT')
        and source['sha256'] == record['program_sha256'],
        code,
    )
    if candidate:
        binding = exact(config['release_validation'], CANDIDATE_BINDING_FIELDS, code)
        require(
            all(uuid_value(binding[field]) for field in CANDIDATE_BINDING_FIELDS[:3])
            and all(sha_value(binding[field]) for field in CANDIDATE_BINDING_FIELDS[3:]),
            code,
        )
    if replica:
        binding = exact(config['recovery_replica'], RECOVERY_BINDING_FIELDS, code)
        require(
            config['purpose'] in WORKSPACE_PURPOSES
            and record['ingress_gid'] is None
            and all(uuid_value(binding[key]) for key in RECOVERY_BINDING_FIELDS[:2])
            and all(sha_value(binding[key]) for key in RECOVERY_BINDING_FIELDS[2:]),
            code,
        )
    _access_policy(anchor, environment_root, config, record['environment_id'])


def load_installation(anchor, expected, runtime_sha256, project, *, allow_slot=True):
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
            'ingress_gid',
            'project',
            'schema',
            *(('restore_generation_sha256',) if 'restore_generation_sha256' in record else ()),
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
    ingress = record['ingress_gid']
    require(
        ingress is None or (type(ingress) is int and 1 <= ingress < 2**31 and ingress != gid), code
    )
    roots = exact(record['root_identities'], DIRECTORIES, code)
    for metadata in (*roots.values(), record['lock_identity']):
        identity_record(metadata, code)
    require(len({tuple(item.values()) for item in roots.values()}) == len(DIRECTORIES), code)
    config_raw = read_protected(anchor.parent / CONFIG_NAME)
    require(digest(config_raw) == record['configuration_sha256'], code)
    config = decode(config_raw, 'INVALID_ENVIRONMENT_CONFIG')
    environment_root = anchor.parent
    if 'deployment_slot' in config:
        require(allow_slot, code)
        environment_root = validate_deployment_slot(anchor, config, record, runtime_sha256)
    else:
        require('restore_generation_sha256' not in record, code)
    _validate_description(anchor, environment_root, config, record, runtime_sha256)
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
        ingress,
        record.get('restore_generation_sha256'),
    )


def restored_data_root(environment_root, generation):
    return environment_root / GENERATIONS / generation / 'data'


def read_restore_generation(environment_root, environment_id, generation, *, expected=None):
    code = 'RESTORE_GENERATION_RECEIPT_MISMATCH'
    require(uuid_value(generation), code)
    data_root = restored_data_root(environment_root, generation)
    raw = read_protected(data_root.parent / GENERATION_RECEIPT)
    receipt = decode(raw, code)
    hashes = (
        'source_control_sha256',
        'target_configuration_sha256',
        'target_database_sha256',
        'target_asset_index_sha256',
        'restore_target_data_sha256',
        'restore_readiness_sha256',
        'generation_policy_sha256',
    )
    version_record(
        receipt,
        (
            *hashes,
            'status',
            'operation_id',
            'environment_id',
            'source_database_identity',
            'target_data_generation',
            'target_deployment_id',
            'data_root',
            'outbound_hold_required',
            'data_identity',
            'database_identity',
        ),
        code,
    )
    measured = digest(raw)
    require(
        raw == canonical(receipt)
        and (expected is None or measured == expected)
        and receipt['status'] == 'RESTORE_GENERATION_PREPARED_CLOSED'
        and receipt['environment_id'] == environment_id
        and receipt['target_data_generation'] == generation
        and receipt['data_root'] == str(data_root)
        and receipt['outbound_hold_required'] is True
        and all(uuid_value(receipt[field]) for field in ('operation_id', 'target_deployment_id'))
        and all(sha_value(receipt[field]) for field in hashes),
        code,
    )
    for field in ('source_database_identity', 'data_identity', 'database_identity'):
        identity_record(receipt[field], code)
    require(receipt['database_identity'] != receipt['source_database_identity'], code)
    return receipt, measured


def validate_deployment_slot(anchor, config, record, runtime_sha256):
    code = 'INSTALLATION_ANCHOR_MISMATCH'
    bind = exact(config['deployment_slot'], DEPLOYMENT_BINDING_FIELDS, code)
    environment_root = anchor.parent.parent.parent
    require(
        anchor.parent.name == record['deployment_id']
        and anchor.parent.parent.name == DEPLOYMENTS
        and environment_root.name == record['environment_id']
        and config['purpose'] in WORKSPACE_PURPOSES
        and 'recovery_replica' not in config
        and all(
            sha_value(bind[key])
            for key in (
                'base_installation_sha256',
                'source_configuration_sha256',
                'preparation_policy_sha256',
                'manifest_sha256',
                'frontend_index_sha256',
            )
        )
        and uuid_value(bind['source_deployment_id'])
        and bind['source_deployment_id'] != record['deployment_id']
        and uuid_value(bind['release_id'])
        and bind['authorization_mode'] in ('SAME_SCHEMA', 'ROLLBACK_CODE', RESTORE_MODE),
        code,
    )
    base = load_installation(
        environment_root / ANCHOR_NAME,
        bind['base_installation_sha256'],
        runtime_sha256,
        absolute(bind['base_project'], code),
        allow_slot=False,
    )
    restored = record['data_generation'] != base.data_generation
    if restored:
        expected = record.get('restore_generation_sha256')
        require(sha_value(expected), code)
        receipt, _ = read_restore_generation(
            environment_root, base.environment_id, record['data_generation'], expected=expected
        )
        require(
            receipt['data_identity'] == record['root_identities']['data']
            and receipt['data_identity'] != base.roots['data'],
            code,
        )
        if bind['authorization_mode'] == RESTORE_MODE:
            require(
                (receipt['target_deployment_id'], receipt['target_configuration_sha256'])
                == (record['deployment_id'], record['configuration_sha256']),
                code,
            )
    else:
        require(
            'restore_generation_sha256' not in record
            and bind['authorization_mode'] != RESTORE_MODE,
            code,
        )
    require(
        record['deployment_id'] != base.deployment_id
        and record['environment_id'] == base.environment_id
        and record['application_uid'] == base.application_uid
        and record['maintenance_uid'] == base.maintenance_uid
        and record['shared_gid'] == base.group
        and record['ingress_gid'] == base.ingress_group
        and record['lock_identity'] == base.lock_identity
        and all(
            record['root_identities'][key] == base.roots[key]
            for key in DIRECTORIES
            if key != 'frontend' and (key != 'data' or not restored)
        )
        and all(
            config[key] == base.description[key]
            for key in (
                'purpose',
                'required_capabilities',
                'enabled_capabilities',
                'database_relative_path',
                'access_policy_ref',
            )
        ),
        code,
    )
    return environment_root


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
