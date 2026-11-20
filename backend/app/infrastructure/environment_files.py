"""Linux installation records and descriptor-relative durable file operations."""

from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from uuid import uuid4

MAX_RECORD_SIZE = 128 * 1024
SHA256 = re.compile(r'[0-9a-f]{64}')
MAX_REVISION = 9007199254740991


class EnvironmentFailure(RuntimeError):
    def __init__(self, code, *, uncertain=False):
        super().__init__(code)
        self.code = code
        self.uncertain = uncertain


def require(condition, code):
    if not condition:
        raise EnvironmentFailure(code)


def exact(record, fields, code):
    require(type(record) is dict and set(record) == set(fields), code)
    return record


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(record):
    return (
        json.dumps(
            record, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False
        )
        + '\n'
    ).encode('utf-8')


def decode(raw, code):
    def pairs(items):
        result = dict(items)
        require(len(result) == len(items), code)
        return result

    def invalid_number(_value):
        raise EnvironmentFailure(code)

    try:
        record = json.loads(
            raw, object_pairs_hook=pairs, parse_constant=invalid_number, parse_float=invalid_number
        )
        require(type(record) is dict and canonical(record) == raw, code)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise EnvironmentFailure(code) from error
    return record


def identity(metadata):
    return {'device': str(metadata.st_dev), 'inode': str(metadata.st_ino)}


def relative(value, code):
    require(
        type(value) is str
        and value
        and '\\' not in value
        and '\x00' not in value
        and all(piece not in ('', '.', '..') for piece in value.split('/')),
        code,
    )
    return PurePosixPath(value)


def absolute(value, code):
    require(type(value) is str and value.startswith('/'), code)
    return Path('/') / relative(value[1:], code)


def no_acl(fd):
    for key in ('system.posix_acl_access', 'system.posix_acl_default'):
        try:
            os.getxattr(fd, key)
        except OSError as error:
            if error.errno in (errno.ENODATA, errno.ENOTSUP):
                continue
            raise
        raise EnvironmentFailure('INSTALLATION_PERMISSIONS_MISMATCH')


@contextmanager
def protected_directory(path):
    """Open absolute directory components without following links, checking root control."""
    code = 'INSTALLATION_PERMISSIONS_MISMATCH'
    require(absolute(os.fspath(path), code) == path, code)
    flags = os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open('/', flags)
    try:
        for component in path.parts[1:]:
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            metadata = os.fstat(fd)
            require(metadata.st_uid == 0 and not stat.S_IMODE(metadata.st_mode) & 0o022, code)
            no_acl(fd)
        yield fd
    finally:
        os.close(fd)


def read_entry(directory, name, *, owner, group=None, reject_writers=0o022):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    fd = os.open(name, flags, dir_fd=directory)
    with os.fdopen(fd, 'rb') as source:
        metadata = os.fstat(fd)
        require(
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_nlink == 1
            and metadata.st_uid == owner
            and (group is None or metadata.st_gid == group)
            and not stat.S_IMODE(metadata.st_mode) & reject_writers,
            'INSTALLATION_PERMISSIONS_MISMATCH',
        )
        no_acl(fd)
        raw = source.read(MAX_RECORD_SIZE + 1)
        require(len(raw) <= MAX_RECORD_SIZE, 'INSTALLATION_RECORD_TOO_LARGE')
        return raw


def read_protected(path):
    with protected_directory(path.parent) as parent:
        return read_entry(parent, path.name, owner=0)


def persisted_write(directory, name, raw, *, mode=0o600, replace=False):
    """The caller owns a stable directory and serializes any replacements."""
    temporary = f'.walle-{uuid4().hex}.tmp'
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(temporary, flags, mode, dir_fd=directory)
    published = False
    try:
        with os.fdopen(fd, 'wb') as sink:
            sink.write(raw)
            sink.flush()
            os.fchmod(sink.fileno(), mode)
            os.fsync(sink.fileno())
        if replace:
            os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
            published = True
        else:
            os.link(
                temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False
            )
            published = True
            os.unlink(temporary, dir_fd=directory)
        os.fsync(directory)
    except OSError as error:
        if published:
            raise EnvironmentFailure('PUBLICATION_UNVERIFIED', uncertain=True) from error
        raise
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


def check_ext4(fd):
    with open(f'/proc/self/fdinfo/{fd}', encoding='ascii') as info:
        fields = dict(line.rstrip('\n').split(':', 1) for line in info if ':' in line)
    mount_id = fields['mnt_id'].strip()
    with open('/proc/self/mountinfo', encoding='utf-8') as mounts:
        for row in mounts:
            before, after = row.split(' - ', 1)
            if before.split(' ', 1)[0] == mount_id:
                require(after.split(' ', 1)[0] == 'ext4', 'INSTALLATION_FILESYSTEM_UNSUPPORTED')
                return
    raise EnvironmentFailure('INSTALLATION_FILESYSTEM_UNSUPPORTED')
