"""Root-owned installation and independently verified manager data identity."""

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import stat
from uuid import uuid4

from backend.app.infrastructure.environment_files import (
    canonical,
    check_ext4,
    decode,
    digest,
    exact,
    identity,
    no_acl,
    persisted_write,
    protected_directory,
    read_entry,
    require,
)
from backend.app.infrastructure.environment_installation import (
    identity_record,
    sha_value,
    uuid_value,
)
from backend.app.infrastructure.environment_lock import EnvironmentLock, LOCK_NAME

ANCHOR_NAME = 'manager-installation.v1.json'
DATABASE_NAME = 'registry.sqlite3'
GENERATIONS = 'registry-generations'
SOURCE_ANCHOR = 'registry-source-installation.v1.json'
INSTALLATION_ERROR = 'MANAGEMENT_INSTALLATION_INVALID'
IDENTITY_ERROR = 'MANAGEMENT_REGISTRY_IDENTITY_MISMATCH'
ROOT_NAMES = ('data', 'proof', 'lock')
FIELDS = (
    'format_version',
    'manager_id',
    'host_id',
    'registry_generation',
    'manager_uid',
    'manager_gid',
    'runtime_manifest_sha256',
    'root',
    'root_identity',
    'directories',
    'lock_identity',
    'database_identity',
)
GENERATION_FIELDS = (
    'generation_root_identity',
    'source_registry_generation',
    'source_registry_anchor_sha256',
    'recovery_preparation_sha256',
)


def managed_id(value):
    return type(value) is int and 1 <= value < 2**31


@dataclass(frozen=True)
class RegistryInstallation:
    anchor: Path
    sha256: str
    manager_id: str
    host_id: str
    registry_generation: str
    uid: int
    gid: int
    root_facts: dict
    directories: dict
    lock_facts: dict
    database_facts: dict
    generation_root_facts: dict | None = None
    historical: bool = False

    @property
    def directory_root(self):
        root = self.anchor.parent
        if self.generation_root_facts is None:
            return root
        return root / GENERATIONS / self.registry_generation

    def lock(self, native):
        require(not self.historical, INSTALLATION_ERROR)
        return EnvironmentLock(
            native,
            self.anchor.parent / 'lock',
            self.directories['lock'],
            self.lock_facts,
            self.gid,
        )

    @contextmanager
    def private_directory(self, native, name):
        require(name in ('data', 'proof'), INSTALLATION_ERROR)
        with ExitStack() as resources:
            root = resources.enter_context(protected_directory(self.anchor.parent))
            require_registry_root(os.fstat(root), self.root_facts, self.gid)
            if self.generation_root_facts is not None:
                root = resources.enter_context(protected_directory(self.directory_root))
                require_registry_root(os.fstat(root), self.generation_root_facts, self.gid)
            fd = native.open_beneath(root, name, os.O_DIRECTORY | os.O_RDONLY)
            try:
                metadata = os.fstat(fd)
                require(
                    identity(metadata) == self.directories[name]
                    and metadata.st_uid == self.uid
                    and metadata.st_gid == self.gid
                    and stat.S_IMODE(metadata.st_mode) == 0o700,
                    IDENTITY_ERROR,
                )
                no_acl(fd)
                check_ext4(fd)
                yield fd
            finally:
                os.close(fd)


def read_registry_anchor(parent, name):
    metadata = os.fstat(parent)
    raw = read_entry(parent, name, owner=0, group=metadata.st_gid, reject_writers=0o237)
    return metadata, raw


def require_registry_root(metadata, expected, group):
    require(
        identity(metadata) == expected
        and metadata.st_gid == group
        and stat.S_IMODE(metadata.st_mode) == 0o2750,
        IDENTITY_ERROR,
    )


def load_installation(
    path, expected, runtime_sha, *, installer=False, prepared=False, archived=False
):
    require(
        path.is_absolute()
        and path.name == (SOURCE_ANCHOR if archived else ANCHOR_NAME)
        and not (prepared and archived)
        and sha_value(expected)
        and sha_value(runtime_sha),
        INSTALLATION_ERROR,
    )
    with protected_directory(path.parent) as parent:
        anchor_parent, raw = read_registry_anchor(parent, path.name)
    value = decode(raw, INSTALLATION_ERROR)
    version = value.get('format_version')
    require(type(version) is int and version in (1, 2), INSTALLATION_ERROR)
    root = path.parent.parent.parent if prepared or archived else path.parent
    record = exact(
        value, FIELDS if version == 1 else (*FIELDS, *GENERATION_FIELDS), INSTALLATION_ERROR
    )
    require(
        digest(raw) == expected
        and record['root'] == str(root)
        and record['runtime_manifest_sha256'] == runtime_sha
        and managed_id(record['manager_uid'])
        and managed_id(record['manager_gid'])
        and all(uuid_value(record[key]) for key in ('manager_id', 'host_id', 'registry_generation'))
        and (not prepared or version == 2),
        INSTALLATION_ERROR,
    )
    children = exact(record['directories'], ROOT_NAMES, INSTALLATION_ERROR)
    for item in (
        *children.values(),
        record['root_identity'],
        record['lock_identity'],
        record['database_identity'],
    ):
        identity_record(item, INSTALLATION_ERROR)
    require(
        len({(item['device'], item['inode']) for item in children.values()}) == len(ROOT_NAMES),
        INSTALLATION_ERROR,
    )
    # The writer's configured identity is distinct from every environment and development login.
    require(
        (
            os.geteuid() == 0
            if installer
            else os.geteuid() == record['manager_uid']
            and os.getegid() == record['manager_gid']
            and set(os.getgroups()) <= {record['manager_gid']}
        ),
        INSTALLATION_ERROR,
    )
    group = record['manager_gid']
    if archived:
        require(
            path.parent.parent == root / GENERATIONS
            and uuid_value(path.parent.name)
            and path.parent.name != record['registry_generation'],
            INSTALLATION_ERROR,
        )
        require_registry_root(anchor_parent, identity(anchor_parent), group)
        with protected_directory(root) as stable:
            anchor_parent = os.fstat(stable)
    generation_root = None
    if version == 2:
        generation_root = record['generation_root_identity']
        identity_record(generation_root, INSTALLATION_ERROR)
        require(
            uuid_value(record['source_registry_generation'])
            and record['source_registry_generation'] != record['registry_generation']
            and sha_value(record['source_registry_anchor_sha256'])
            and sha_value(record['recovery_preparation_sha256']),
            INSTALLATION_ERROR,
        )
        slot = root / GENERATIONS / record['registry_generation']
        if prepared:
            require(path.parent == slot, INSTALLATION_ERROR)
            require_registry_root(anchor_parent, generation_root, group)
            with protected_directory(root) as stable:
                anchor_parent = os.fstat(stable)
        else:
            with protected_directory(slot) as directory:
                require_registry_root(os.fstat(directory), generation_root, group)
    require_registry_root(anchor_parent, record['root_identity'], group)
    return RegistryInstallation(
        root / ANCHOR_NAME,
        expected,
        record['manager_id'],
        record['host_id'],
        record['registry_generation'],
        record['manager_uid'],
        group,
        record['root_identity'],
        children,
        record['lock_identity'],
        record['database_identity'],
        generation_root,
        archived,
    )


def prepare_installation(root, uid, gid, runtime_sha, host_id):
    require(
        os.geteuid() == 0
        and root.is_absolute()
        and managed_id(uid)
        and managed_id(gid)
        and sha_value(runtime_sha)
        and uuid_value(host_id),
        INSTALLATION_ERROR,
    )
    fd_flags = os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_RDONLY
    entry_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    with protected_directory(root.parent) as parent:
        check_ext4(parent)
        os.mkdir(root.name, mode=0o700, dir_fd=parent)
        os.fsync(parent)
        root_fd = os.open(root.name, fd_flags, dir_fd=parent)
        try:
            os.fchown(root_fd, 0, gid)
            os.fchmod(root_fd, 0o2750)
            facts = {}
            for name in ROOT_NAMES:
                os.mkdir(name, mode=0o700, dir_fd=root_fd)
                descriptor = os.open(name, fd_flags, dir_fd=root_fd)
                try:
                    lock = name == 'lock'
                    if lock or name == 'data':
                        filename = LOCK_NAME if lock else DATABASE_NAME
                        file_fd = os.open(filename, entry_flags, 0o600, dir_fd=descriptor)
                        try:
                            os.fchown(file_fd, 0 if lock else uid, gid)
                            os.fchmod(file_fd, 0o660 if lock else 0o600)
                            file_facts = identity(os.fstat(file_fd))
                            if lock:
                                lock_identity = file_facts
                            else:
                                database_identity = file_facts
                            os.fsync(file_fd)
                        finally:
                            os.close(file_fd)
                    os.fchown(descriptor, 0 if lock else uid, gid)
                    os.fchmod(descriptor, 0o550 if lock else 0o700)
                    facts[name] = identity(os.fstat(descriptor))
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            record = {
                'format_version': 1,
                'manager_id': str(uuid4()),
                'host_id': host_id,
                'registry_generation': str(uuid4()),
                'manager_uid': uid,
                'manager_gid': gid,
                'runtime_manifest_sha256': runtime_sha,
                'root': str(root),
                'root_identity': identity(os.fstat(root_fd)),
                'directories': facts,
                'lock_identity': lock_identity,
                'database_identity': database_identity,
            }
            raw = canonical(record)
            # Publishing the immutable anchor last leaves any incomplete root unregistered.
            persisted_write(root_fd, ANCHOR_NAME, raw, mode=0o440)
            return {
                'manager_id': record['manager_id'],
                'registry_generation': record['registry_generation'],
                'anchor_sha256': digest(raw),
            }
        finally:
            os.close(root_fd)
