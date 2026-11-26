"""Verify retained database claims through the current restore's protected receipt chain."""

import os
from collections import defaultdict

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    check_ext4,
    identity,
    no_acl,
    protected_directory,
    require,
)
from backend.app.infrastructure.environment_installation import (
    database_identity,
    read_restore_generation,
)
from backend.app.infrastructure.environment_retained_data import retained_data_paths

from .attachment_observation import path_resource

UNVERIFIED = 'MANAGEMENT_REGISTRY_RECOVERY_RETAINED_DATA_UNVERIFIED'
PRESERVED = 'RETAINED_RESTORE_DATA_VERIFIED'


def identity_key(measured):
    return measured['device'], measured['inode']


def retained_sample(native, environment, data):
    with protected_directory(data.parent) as parent:
        fd = native.open_beneath(parent, 'data', os.O_RDONLY | os.O_DIRECTORY)
        try:
            meta = os.fstat(fd)
            root = identity(meta)
            require(
                (meta.st_uid, meta.st_gid, meta.st_mode & 0o7777)
                == environment.expected_directory('data')
                and root != environment.roots['data']
                and root == identity(os.stat('data', dir_fd=parent, follow_symlinks=False)),
                UNVERIFIED,
            )
            check_ext4(fd)
            no_acl(fd)
            database = database_identity(environment, fd)
            require(
                database is not None
                and database_identity(environment, fd) == database
                and root == identity(os.stat('data', dir_fd=parent, follow_symlinks=False)),
                UNVERIFIED,
            )
            return root, database
        finally:
            os.close(fd)


def retained_data_observation(native, environment, active_database):
    if environment.restore_generation_sha256 is None:
        return []
    stable = environment.environment_root
    current, _ = read_restore_generation(
        stable,
        environment.environment_id,
        environment.data_generation,
        expected=environment.restore_generation_sha256,
    )
    require(
        current['data_identity'] == environment.roots['data']
        and current['database_identity'] == active_database,
        UNVERIFIED,
    )
    by_database = defaultdict(list)
    for data in retained_data_paths(environment):
        try:
            root, database = retained_sample(native, environment, data)
            older = None
            if data.parent != stable:
                older, _ = read_restore_generation(
                    stable, environment.environment_id, data.parent.name
                )
                require(
                    older['data_identity'] == root and older['database_identity'] == database,
                    UNVERIFIED,
                )
            by_database[identity_key(database)].append((data, root, database, older))
        except (EnvironmentFailure, OSError):
            # A missing or changed ancestor cannot satisfy its original claims.
            continue

    seen = {identity_key(active_database)}
    retained = []
    while current is not None:
        previous = identity_key(current['source_database_identity'])
        matches = by_database.get(previous, ())
        if previous in seen or len(matches) != 1:
            break
        seen.add(previous)
        data, root, database, current = matches[0]
        retained.extend(
            (
                path_resource('DATA_ROOT', data, root),
                path_resource('BUSINESS_DATABASE', data / environment.database_relative, database),
            )
        )
    return retained
