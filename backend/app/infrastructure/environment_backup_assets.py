"""Preserve the registered ordinary count-audit bytes within a stopped backup."""

from contextlib import contextmanager, nullcontext
from hashlib import sha256
import os
import stat

from .audit_data import MAX_AUDIT_BYTES
from .count_audit_paths import COUNT_AUDIT_ENTRY, count_audit_root
from .environment_files import (
    EnvironmentFailure,
    canonical,
    check_ext4,
    decode,
    digest,
    exact,
    identity,
    no_acl,
    persisted_write,
    read_entry,
    require,
)

AUDIT_COPY = 'count-audit'
AUDIT_INDEX = 'count-audit-index.v1.json'
AUDIT_UNSUPPORTED = 'BACKUP_ASSET_UNSUPPORTED'
AUDIT_UNVERIFIED = 'BACKUP_ASSET_UNVERIFIED'
AUDIT_LIMIT = 'BACKUP_ASSET_LIMIT'
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
SOURCE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
TARGET_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
SCOPE_FIELDS = (
    'operation_id',
    'environment_id',
    'data_generation',
    'deployment_id',
    'control_revision',
)


def audit_source_name(installation):
    return count_audit_root(installation.database).name


@contextmanager
def audit_directory(parent, name, owner, group, *, source):
    code = AUDIT_UNSUPPORTED if source else AUDIT_UNVERIFIED
    allowed = (0o700, 0o750, 0o770) if source else (0o700,)
    try:
        fd = os.open(name, DIRECTORY_FLAGS, dir_fd=parent)
    except FileNotFoundError:
        if not source:
            raise
        yield None
        return
    except OSError as error:
        raise EnvironmentFailure(code) from error
    try:
        actual = os.fstat(fd)
        require(
            actual.st_uid == owner
            and actual.st_gid == group
            and stat.S_IMODE(actual.st_mode) in allowed,
            code,
        )
        check_ext4(fd)
        no_acl(fd)
        yield fd
        if source:
            require(
                identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) == identity(actual),
                code,
            )
    finally:
        os.close(fd)


def audit_file_facts(fd, owner, group, *, source):
    metadata = os.fstat(fd)
    modes = (0o600, 0o640, 0o660) if source else (0o400,)
    require(
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == owner
        and metadata.st_gid == group
        and metadata.st_nlink == 1
        and stat.S_IMODE(metadata.st_mode) in modes
        and 0 < metadata.st_size <= MAX_AUDIT_BYTES,
        AUDIT_UNSUPPORTED if source else AUDIT_UNVERIFIED,
    )
    no_acl(fd)
    return metadata


def audit_names(fd, maximum):
    names = []
    with os.scandir(fd) as entries:
        for entry in entries:
            require(len(names) < maximum, AUDIT_LIMIT)
            require(COUNT_AUDIT_ENTRY.fullmatch(entry.name) is not None, AUDIT_UNSUPPORTED)
            names.append(entry.name)
    return sorted(names)


def file_signature(metadata):
    return identity(metadata), metadata.st_size, metadata.st_ctime_ns, metadata.st_mtime_ns


def scan_audit(parent, name, owner, group, maximum, *, source, output=None):
    code = AUDIT_UNSUPPORTED if source else AUDIT_UNVERIFIED
    try:
        fd = os.open(name, SOURCE_FLAGS, dir_fd=parent)
    except OSError as error:
        raise EnvironmentFailure(code) from error
    with os.fdopen(fd, 'rb') as handle:
        initial = audit_file_facts(handle.fileno(), owner, group, source=source)
        limit = initial.st_size
        require(limit <= maximum, AUDIT_LIMIT)
        if output is None:
            target = nullcontext(None)
        else:
            target = os.fdopen(os.open(name, TARGET_FLAGS, 0o600, dir_fd=output), 'wb')
        measured = 0
        checksum = sha256()
        with target as sink:
            while block := handle.read(128 * 1024):
                measured += len(block)
                require(measured <= limit, code)
                checksum.update(block)
                if sink is not None:
                    sink.write(block)
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            require(
                measured == limit
                and file_signature(current)
                == file_signature(initial)
                == file_signature(os.fstat(handle.fileno())),
                code,
            )
            if sink is not None:
                sink.flush()
                os.fchmod(sink.fileno(), 0o400)
                os.fsync(sink.fileno())
    return {'name': name, 'bytes': measured, 'sha256': checksum.hexdigest()}, file_signature(
        initial
    )


def capture_count_audit(installation, data_fd, output_fd, plan, receipt):
    source_name = audit_source_name(installation)
    env_group = installation.group
    results = []
    with audit_directory(
        data_fd, source_name, installation.application_uid, env_group, source=True
    ) as source:
        if source is None:
            state = 'ABSENT'
        else:
            names = audit_names(source, plan['max_audit_files'])
            state = 'FILES' if names else 'EMPTY'
            total = plan['max_audit_bytes']
            signatures = {}
            os.mkdir(AUDIT_COPY, 0o700, dir_fd=output_fd)
            with audit_directory(
                output_fd, AUDIT_COPY, installation.maintenance_uid, env_group, source=False
            ) as copy:
                for name in names:
                    fact, before = scan_audit(
                        source,
                        name,
                        installation.application_uid,
                        env_group,
                        total,
                        source=True,
                        output=copy,
                    )
                    total -= fact['bytes']
                    results.append(fact)
                    signatures[name] = before
                require(audit_names(source, plan['max_audit_files']) == names, AUDIT_UNSUPPORTED)
                require(
                    all(
                        file_signature(os.stat(name, dir_fd=source, follow_symlinks=False))
                        == signatures[name]
                        for name in names
                    ),
                    AUDIT_UNSUPPORTED,
                )
                os.fsync(copy)
                os.fsync(output_fd)
    if state == 'ABSENT':
        try:
            os.stat(source_name, dir_fd=data_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise EnvironmentFailure(AUDIT_UNSUPPORTED)
    index = canonical(
        {
            'format_version': 1,
            'asset_kind': 'COUNTING_AUDIT',
            'intent_sha256': receipt['intent_sha256'],
            **{name: receipt[name] for name in SCOPE_FIELDS},
            'database_sha256': receipt['database_artifact']['sha256'],
            'state': state,
            'entries': results,
        }
    )
    persisted_write(output_fd, AUDIT_INDEX, index, mode=0o400)
    return {'name': AUDIT_INDEX, 'bytes': len(index), 'sha256': digest(index)}


def source_index(installation, fd, receipt):
    owner, group = installation.maintenance_uid, installation.group
    observed_index = os.stat(AUDIT_INDEX, dir_fd=fd, follow_symlinks=False)
    require(
        stat.S_ISREG(observed_index.st_mode) and stat.S_IMODE(observed_index.st_mode) == 0o400,
        AUDIT_UNVERIFIED,
    )
    raw = read_entry(fd, AUDIT_INDEX, owner=owner, group=group, reject_writers=0o222)
    require(
        receipt['asset_index'] == {'name': AUDIT_INDEX, 'bytes': len(raw), 'sha256': digest(raw)}
        and file_signature(observed_index)
        == file_signature(os.stat(AUDIT_INDEX, dir_fd=fd, follow_symlinks=False)),
        AUDIT_UNVERIFIED,
    )
    observed = exact(
        decode(raw, AUDIT_UNVERIFIED),
        (
            'format_version',
            'asset_kind',
            'intent_sha256',
            *SCOPE_FIELDS,
            'database_sha256',
            'state',
            'entries',
        ),
        AUDIT_UNVERIFIED,
    )
    files = observed['entries']
    state = observed['state']
    require(
        type(observed['format_version']) is int
        and observed['format_version'] == 1
        and observed['asset_kind'] == 'COUNTING_AUDIT'
        and observed['intent_sha256'] == receipt['intent_sha256']
        and observed['database_sha256'] == receipt['database_artifact']['sha256']
        and all(observed[name] == receipt[name] for name in SCOPE_FIELDS)
        and state in ('ABSENT', 'EMPTY', 'FILES')
        and type(files) is list
        and (state == 'FILES') == bool(files),
        AUDIT_UNVERIFIED,
    )
    return raw, observed


def verify_count_audit(installation, fd, plan, receipt):
    _, index = source_index(installation, fd, receipt)
    owner, group = installation.maintenance_uid, installation.group
    files = index['entries']
    members = {AUDIT_INDEX}
    if index['state'] == 'ABSENT':
        require(AUDIT_COPY not in os.listdir(fd), AUDIT_UNVERIFIED)
        return members
    with audit_directory(fd, AUDIT_COPY, owner, group, source=False) as copy:
        names = audit_names(copy, plan['max_audit_files'])
        require(len(files) == len(names), AUDIT_UNVERIFIED)
        total = plan['max_audit_bytes']
        for name, expected in zip(names, files, strict=True):
            observed, _ = scan_audit(copy, name, owner, group, total, source=False)
            require(expected == observed, AUDIT_UNVERIFIED)
            total -= observed['bytes']
        require(audit_names(copy, plan['max_audit_files']) == names, AUDIT_UNVERIFIED)
    return members | {AUDIT_COPY}


def restore_audit_file(source, target, expected, owner, group):
    name = expected['name']
    try:
        os.stat(name, dir_fd=target, follow_symlinks=False)
    except FileNotFoundError:
        with os.fdopen(os.open(name, SOURCE_FLAGS, dir_fd=source), 'rb') as handle:
            initial = audit_file_facts(handle.fileno(), owner, group, source=False)
            require(initial.st_size == expected['bytes'], AUDIT_UNVERIFIED)
            raw = handle.read(initial.st_size + 1)
            current = os.stat(name, dir_fd=source, follow_symlinks=False)
            require(
                file_signature(initial)
                == file_signature(current)
                == file_signature(os.fstat(handle.fileno()))
                and len(raw) == expected['bytes']
                and digest(raw) == expected['sha256'],
                AUDIT_UNVERIFIED,
            )
        persisted_write(target, name, raw, mode=0o400)
    else:
        actual, _ = scan_audit(target, name, owner, group, expected['bytes'], source=False)
        require(actual == expected, AUDIT_UNVERIFIED)


def restore_count_audit(installation, source, target, capture, receipt):
    owner, group = installation.maintenance_uid, installation.group
    try:
        os.stat(AUDIT_INDEX, dir_fd=target, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        verify_count_audit(installation, target, capture, receipt)
        return receipt['asset_index']
    raw, index = source_index(installation, source, receipt)
    if index['state'] == 'ABSENT':
        require(AUDIT_COPY not in os.listdir(target), AUDIT_UNVERIFIED)
    else:
        try:
            os.mkdir(AUDIT_COPY, 0o700, dir_fd=target)
            os.fsync(target)
        except FileExistsError:
            pass
        with (
            audit_directory(source, AUDIT_COPY, owner, group, source=False) as original,
            audit_directory(target, AUDIT_COPY, owner, group, source=False) as copy,
        ):
            names = {entry['name'] for entry in index['entries']}
            require(
                set(audit_names(copy, capture['max_audit_files'])) <= names,
                AUDIT_UNVERIFIED,
            )
            for expected in index['entries']:
                restore_audit_file(original, copy, expected, owner, group)
            require(set(audit_names(copy, capture['max_audit_files'])) == names, AUDIT_UNVERIFIED)
            os.fsync(copy)
    persisted_write(target, AUDIT_INDEX, raw, mode=0o400)
    verify_count_audit(installation, target, capture, receipt)
    return receipt['asset_index']
