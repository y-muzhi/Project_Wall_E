"""One original config's private parse copy; source/copy stay bound until cleanup.

Only an already verified operator-private package is used. No Git executes here.
Creation/cleanup uses original file handles; unknown ownership never authorizes
path deletion. Callers must keep a path borrow until their original Git exits.
"""

import ctypes
from contextlib import contextmanager
from ctypes import wintypes
from threading import RLock
from uuid import uuid4

from .windows_config_source import LockedConfigSource
from .windows_executable_pin import READ_CHUNK
from .windows_executable_pin import _api as read_api
from .windows_local_paths import _identity
from .windows_private_package import PrivatePackageGuard


class ConfigCopyError(RuntimeError):
    def __init__(self, reason, native_error=None):
        self.reason = reason
        self.native_error = native_error
        super().__init__(reason)


class _Disposition(ctypes.Structure):
    _fields_ = [('delete', ctypes.c_ubyte)]  # Win32 BOOLEAN, not the four-byte BOOL.


def _failure(reason):
    return ConfigCopyError(reason, ctypes.get_last_error())


def _api():
    kernel = read_api()
    kernel.WriteFile.argtypes = kernel.ReadFile.argtypes
    kernel.WriteFile.restype = wintypes.BOOL
    kernel.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    kernel.FlushFileBuffers.restype = wintypes.BOOL
    kernel.SetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    if ctypes.sizeof(_Disposition) != 1:
        raise ConfigCopyError('CONFIG_COPY_NATIVE_LAYOUT_UNSUPPORTED')
    return kernel


class PrivateConfigCopy:
    def __init__(self, source, package):
        if type(source) is not LockedConfigSource or type(package) is not PrivatePackageGuard:
            raise ConfigCopyError('ORIGINAL_CONFIG_AND_PRIVATE_PACKAGE_REQUIRED')
        self._initialize(source, package)

    @classmethod
    def create_empty_global(cls, package):
        if type(package) is not PrivatePackageGuard or not package.is_control_git_read_package:
            raise ConfigCopyError('ORIGINAL_CONTROL_GIT_READ_PACKAGE_REQUIRED')
        copy = cls.__new__(cls)
        copy._initialize(None, package)
        return copy

    def _initialize(self, source, package):
        self._gate = RLock()
        self._source, self._package = source, package
        self._source_context = None
        self._original = None
        self._writer = None
        self._reader = None
        self._delete_handle = None
        self._delete_marked = False
        self._created = False
        self._creation_unknown = False
        self._deleted = False
        self._closing = False
        self._uses = 0
        self._copy_identity = None
        self._name = 'git-config-' + uuid4().hex
        self._path = package.path / self._name
        self._kernel = None
        try:
            self._package_identity = package.verify()
            if len(str(self._path).encode('utf-16-le', errors='strict')) // 2 > 240:
                raise ConfigCopyError('CONFIG_COPY_PATH_TOO_LONG')
            if source is not None:
                context = source.hold()
                self._original = context.__enter__()
                self._source_context = context
            self._kernel = _api()
            self._create()
            self.verify()
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    def _create(self):
        with self._package.file_creation_attributes() as attributes:
            self._creation_unknown = True
            handle = self._kernel.CreateFileW(
                '\\\\?\\' + str(self._path),
                0x40000000 | 0x80 | 0x10000,  # WRITE / READ_ATTRIBUTES / DELETE.
                0x1,
                ctypes.byref(attributes),
                1,
                0x00200000 | 0x00100000,
                None,  # CREATE_NEW only.
            )
            if handle == ctypes.c_void_p(-1).value or not handle:
                self._creation_unknown = False
                raise _failure('CONFIG_COPY_CREATE_FAILED')
            self._writer = handle
            self._created = True
            self._creation_unknown = False
        self._copy_identity = _identity(self._kernel, handle, self._path)
        raw = b'' if self._original is None else self._original.raw
        offset = 0
        while offset < len(raw):
            data = ctypes.create_string_buffer(raw[offset : offset + READ_CHUNK])
            count = min(READ_CHUNK, len(raw) - offset)
            written = wintypes.DWORD()
            if not self._kernel.WriteFile(handle, data, count, ctypes.byref(written), None):
                raise _failure('CONFIG_COPY_WRITE_FAILED')
            if not 1 <= written.value <= count:
                raise ConfigCopyError('CONFIG_COPY_WRITE_SIZE_INVALID')
            offset += written.value
        if not self._kernel.FlushFileBuffers(handle):
            raise _failure('CONFIG_COPY_FLUSH_FAILED')
        if _identity(self._kernel, handle, self._path) != self._copy_identity:
            raise ConfigCopyError('CONFIG_COPY_CREATED_FILE_DIFFERS')
        if not self._kernel.CloseHandle(handle):
            raise _failure('CONFIG_COPY_WRITER_CLOSE_UNVERIFIED')
        self._writer = None
        if self._package.verify_member(self._name, directory=False) != self._copy_identity:
            raise ConfigCopyError('CONFIG_COPY_PRIVATE_FILE_DIFFERS')
        try:
            self._reader = LockedConfigSource(
                self._path,
                max_file_bytes=1 if self._source is None else self._source._limit,
                expected_file=self._copy_identity,
            )
        except BaseException as error:
            retained = getattr(error, 'retained_owner', None)
            if type(retained) is LockedConfigSource:
                self._reader = retained
            raise

    def verify(self):
        with self._gate:
            if self._closing or self._reader is None:
                raise ConfigCopyError('CONFIG_COPY_CLOSED')
            if self._package.verify() != self._package_identity:
                raise ConfigCopyError('CONFIG_COPY_PACKAGE_DIFFERS')
            copied = self._reader.verify()
            if (
                copied.file != self._copy_identity
                or self._package.verify_member(self._name, directory=False) != copied.file
            ):
                raise ConfigCopyError('CONFIG_COPY_BYTES_OR_IDENTITY_DIFFERS')
            if self._source is None:
                if copied.raw != b'':
                    raise ConfigCopyError('ORIGINAL_EMPTY_GLOBAL_CONFIG_DIFFERS')
            else:
                original = self._source.verify()
                if original != self._original or copied.raw != original.raw:
                    raise ConfigCopyError('CONFIG_COPY_BYTES_OR_IDENTITY_DIFFERS')
            return copied

    @property
    def empty_global_reader(self):
        if self._source is not None:
            raise ConfigCopyError('ORIGINAL_EMPTY_GLOBAL_CONFIG_REQUIRED')
        self.verify()
        return self._reader

    @contextmanager
    def parse_path(self):
        with self._gate:
            self.verify()
            self._uses += 1
        try:
            yield str(self._path)
        finally:
            with self._gate:
                self._uses -= 1
                self.verify()

    def _mark_and_close(self, attribute):
        handle = getattr(self, attribute)
        if not self._delete_marked:
            value = _Disposition(1)
            if not self._kernel.SetFileInformationByHandle(
                handle,
                4,
                ctypes.byref(value),
                ctypes.sizeof(value),
            ):
                raise _failure('CONFIG_COPY_DELETE_UNVERIFIED')
            self._delete_marked = True
        if not self._kernel.CloseHandle(handle):
            raise _failure('CONFIG_COPY_DELETE_CLOSE_UNVERIFIED')
        setattr(self, attribute, None)
        self._deleted = True

    def _cleanup_file(self):
        if self._creation_unknown:
            raise ConfigCopyError('CONFIG_COPY_CREATION_UNKNOWN')
        if self._writer is not None:
            # This is the actual CREATE_NEW result, including partial writes.
            self._mark_and_close('_writer')
        if self._reader is not None:
            self._reader.close()
            self._reader = None
        if not self._created or self._deleted:
            return
        if self._delete_handle is None:
            if self._package.verify() != self._package_identity:
                raise ConfigCopyError('CONFIG_COPY_PACKAGE_DIFFERS')
            if self._package.verify_member(self._name, directory=False) != self._copy_identity:
                raise ConfigCopyError('CONFIG_COPY_CLEANUP_IDENTITY_DIFFERS')
            handle = self._kernel.CreateFileW(
                '\\\\?\\' + str(self._path),
                0x10000 | 0x80,
                0x1,
                None,
                3,
                0x00200000 | 0x00100000,
                None,
            )
            if handle == ctypes.c_void_p(-1).value or not handle:
                raise _failure('CONFIG_COPY_DELETE_OPEN_UNVERIFIED')
            self._delete_handle = handle
        if not self._delete_marked:
            try:
                actual = _identity(self._kernel, self._delete_handle, self._path)
                if actual != self._copy_identity:
                    raise ConfigCopyError('CONFIG_COPY_CLEANUP_IDENTITY_DIFFERS')
            except BaseException:
                # Never mark a path replacement for deletion.
                if self._kernel.CloseHandle(self._delete_handle):
                    self._delete_handle = None
                raise
        self._mark_and_close('_delete_handle')

    def close(self):
        with self._gate:
            if self._uses:
                raise ConfigCopyError('CONFIG_COPY_IN_USE')
            self._closing = True
            try:
                self._cleanup_file()
                if self._source_context is not None:
                    context = self._source_context
                    self._source_context = None  # Exit the original borrow exactly once.
                    context.__exit__(None, None, None)
            except BaseException as error:
                error.retained_owner = self
                raise

    def __enter__(self):
        self.verify()
        return self

    def __exit__(self, kind, error, traceback):
        self.close()
