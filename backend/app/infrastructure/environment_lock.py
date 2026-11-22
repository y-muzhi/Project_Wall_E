"""Process lock shared by Linux application and maintenance operations."""

from contextlib import ExitStack
import ctypes
import errno
import os
from pathlib import Path
import stat
from threading import Lock
from uuid import uuid4

from .environment_files import (
    EnvironmentFailure,
    check_ext4,
    identity,
    no_acl,
    protected_directory,
    require,
)

PROTOCOL = 'OC201-ENV-LOCK-1'
LOCK_NAME = 'environment.lock'
LIBRARY_REF = 'lib/walle_environment_lock.so'
_OWNER_MUTEX = Lock()
_LOCAL_OWNERS = set()


class NativeEnvironmentFiles:
    def __init__(self, verified_runtime_root):
        library = ctypes.CDLL(str(Path(verified_runtime_root) / LIBRARY_REF))
        library.walle_env_open_beneath.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        library.walle_env_open_beneath.restype = ctypes.c_int
        library.walle_env_lock_open.argtypes = [ctypes.c_int, ctypes.c_int]
        library.walle_env_lock_open.restype = ctypes.c_int
        library.walle_env_lock_acquire.argtypes = [ctypes.c_int]
        library.walle_env_lock_acquire.restype = ctypes.c_int
        library.walle_env_lock_release.argtypes = [ctypes.c_int]
        library.walle_env_lock_release.restype = ctypes.c_int
        library.walle_env_lock_observe.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int64)]
        library.walle_env_lock_observe.restype = ctypes.c_int
        self.library = library

    def open_beneath(self, root, path, flags, mode=0):
        number = self.library.walle_env_open_beneath(root, os.fsencode(path), flags, mode)
        if number < 0:
            raise OSError(-number, os.strerror(-number), os.fspath(path))
        return number

    def open_lock(self, root, *, writable):
        number = self.library.walle_env_lock_open(root, int(writable))
        require(number >= 0, 'ENVIRONMENT_LOCK_UNAVAILABLE')
        return number


class EnvironmentLock:
    """Own exactly one descriptor for the registered lock inode in this process."""

    def __init__(self, native, root, root_identity, lock_identity, group):
        self.path = root / LOCK_NAME
        self._root = root
        self._native = native
        self._root_identity = root_identity
        self._lock_identity = lock_identity
        self._group = group
        self._reservation = (lock_identity['device'], lock_identity['inode'])
        self._resources = None
        self._fd = None
        self._root_fd = None
        self._pid = None
        self._poisoned = False
        self.owner_epoch = None

    def _check_inode(self, metadata):
        require(
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_nlink == 1
            and metadata.st_uid == 0
            and metadata.st_gid == self._group
            and stat.S_IMODE(metadata.st_mode) == 0o660
            and identity(metadata) == self._lock_identity,
            'ENVIRONMENT_LOCK_IDENTITY_MISMATCH',
        )

    def _root_dir(self, resources):
        root_fd = resources.enter_context(protected_directory(self._root))
        metadata = os.fstat(root_fd)
        require(
            metadata.st_gid == self._group
            and stat.S_IMODE(metadata.st_mode) == 0o550
            and identity(metadata) == self._root_identity,
            'ENVIRONMENT_LOCK_IDENTITY_MISMATCH',
        )
        check_ext4(root_fd)
        self._check_inode(os.stat(LOCK_NAME, dir_fd=root_fd, follow_symlinks=False))
        return root_fd

    def acquire(self):
        with _OWNER_MUTEX:
            require(
                not self._poisoned and self._fd is None and self._reservation not in _LOCAL_OWNERS,
                'ENVIRONMENT_LOCK_ALREADY_OWNED',
            )
            _LOCAL_OWNERS.add(self._reservation)
        resources = ExitStack()
        try:
            root_fd = self._root_dir(resources)
            fd = self._native.open_lock(root_fd, writable=True)
            resources.callback(os.close, fd)
            self._check_inode(os.fstat(fd))
            no_acl(fd)
            result = self._native.library.walle_env_lock_acquire(fd)
            require(result not in (-errno.EACCES, -errno.EAGAIN), 'ENVIRONMENT_ALREADY_RUNNING')
            require(result == 0, 'ENVIRONMENT_LOCK_UNAVAILABLE')
        except BaseException:
            try:
                resources.close()
            finally:
                with _OWNER_MUTEX:
                    _LOCAL_OWNERS.remove(self._reservation)
            raise
        self._fd, self._root_fd = fd, root_fd
        self._resources = resources
        self._pid = os.getpid()
        self.owner_epoch = str(uuid4())
        return self

    def assert_owned(self):
        require(
            self._fd is not None and self._pid == os.getpid() and not self._poisoned,
            'ENVIRONMENT_LOCK_NOT_OWNED',
        )
        try:
            require(
                identity(self._root.stat(follow_symlinks=False)) == self._root_identity,
                'ENVIRONMENT_LOCK_IDENTITY_MISMATCH',
            )
            self._check_inode(os.fstat(self._fd))
            self._check_inode(os.stat(LOCK_NAME, dir_fd=self._root_fd, follow_symlinks=False))
        except (OSError, EnvironmentFailure):
            self._poisoned = True
            raise

    def observer_pid(self):
        """Query an independent process' whole-file writer; never open our owned inode."""
        with _OWNER_MUTEX:
            require(self._reservation not in _LOCAL_OWNERS, 'ENVIRONMENT_LOCK_ALREADY_OWNED')
            with ExitStack() as resources:
                root_fd = self._root_dir(resources)
                fd = self._native.open_lock(root_fd, writable=False)
                resources.callback(os.close, fd)
                self._check_inode(os.fstat(fd))
                no_acl(fd)
                pid = ctypes.c_int64()
                status = self._native.library.walle_env_lock_observe(fd, ctypes.byref(pid))
                require(status in (0, 1), 'ENVIRONMENT_LOCK_UNVERIFIED')
                return pid.value if status == 1 else None

    def release(self):
        require(self._fd is not None and self._pid == os.getpid(), 'ENVIRONMENT_LOCK_NOT_OWNED')
        resources = self._resources
        try:
            result = self._native.library.walle_env_lock_release(self._fd)
            if result != 0:
                self._poisoned = True
                raise EnvironmentFailure('ENVIRONMENT_LOCK_RELEASE_UNVERIFIED', uncertain=True)
        finally:
            self._fd = self._root_fd = self._pid = self._resources = self.owner_epoch = None
            try:
                resources.close()
            finally:
                with _OWNER_MUTEX:
                    _LOCAL_OWNERS.remove(self._reservation)

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_exception):
        self.release()
