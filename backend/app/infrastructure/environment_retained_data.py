"""Keep retained restore data outside the ordinary application's filesystem view."""

import os
import stat

from .environment_files import EnvironmentFailure, protected_directory, require
from .environment_installation import GENERATIONS, uuid_value

UNVERIFIED = 'RESTORE_RETIRED_DATA_ACCESS_UNVERIFIED'


def retained_data_paths(installation):
    if installation.restore_generation_sha256 is None:
        return ()
    stable = installation.environment_root
    generations = stable / GENERATIONS
    active = generations / installation.data_generation / 'data'
    require(installation.path('data') == active, UNVERIFIED)
    with protected_directory(generations) as directory:
        others = tuple(
            name
            for name in sorted(os.listdir(directory))
            if uuid_value(name) and name != installation.data_generation
        )
    roots = []
    for parent in (stable, *(generations / name for name in others)):
        with protected_directory(parent) as directory:
            try:
                measured = os.stat('data', dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                continue
            require(stat.S_ISDIR(measured.st_mode) and measured.st_uid == 0, UNVERIFIED)
            roots.append(parent / 'data')
    return tuple(roots)


def retained_data_unit_properties(installation):
    roots = retained_data_paths(installation)
    if not roots:
        return {}
    # systemd-run decodes quoted words from the string-array property.
    quoted = ['"' + os.fspath(path).replace('"', r'\"') + '"' for path in roots]
    return {
        'InaccessiblePaths': ' '.join(quoted),
        'CapabilityBoundingSet': '~CAP_SYS_ADMIN',
    }


def require_retained_data_inaccessible(installation):
    for path in retained_data_paths(installation):
        require(not os.access(path, os.X_OK, effective_ids=True), UNVERIFIED)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
        except PermissionError:
            continue
        os.close(fd)
        raise EnvironmentFailure(UNVERIFIED)
