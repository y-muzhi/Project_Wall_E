"""Bounded original Windows file read leases, including GIT20-LOCAL-1.

Metadata ancestors use LocalPathGuard; data IO reuses the executable pin's native
file API and unsupported-attribute policy, without applying PE/image semantics.
This is not repository/layout admission, a private copy or complete capture.
"""

import ctypes
import hashlib
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass, field
from threading import RLock

from backend.app.shared.validation import MAX_SAFE_INTEGER

from .git_local_config import config_source_sha256
from .windows_executable_pin import READ_CHUNK, UNSUPPORTED_ATTRIBUTES
from .windows_executable_pin import _api as read_api
from .windows_local_paths import (
    FileIdentity,
    HandleInfo,
    LocalPathGuard,
    PathBoundaryError,
    _identity,
    local_absolute_path,
)


class ConfigReadError(RuntimeError):
    def __init__(self, reason, native_error=None):
        self.reason = reason
        self.native_error = native_error
        if reason in ('CONFIG_READ_ORIGINAL_FILE_DIFFERS', 'CONFIG_READ_SOURCE_CHANGED'):
            self.code = 'SOURCE_CHANGED'
        elif native_error in (32, 33):
            self.code = 'SOURCE_BUSY'
        else:
            self.code = 'SOURCE_UNSUPPORTED'
        super().__init__(reason)


def _failure(reason):
    return ConfigReadError(reason, ctypes.get_last_error())


@dataclass(frozen=True)
class ConfigSourceSnapshot:
    file: FileIdentity = field(repr=False)
    byte_count: int
    sha256: str
    raw: bytes = field(repr=False)


class LockedFileSource:
    """Hold a real original NTFS file with read sharing only, until explicit close."""

    def __init__(
        self, path, *, max_file_bytes, expected_file=None, capture_raw=True, checkpoint=None
    ):
        self._initialize(path, max_file_bytes, expected_file)
        self._capture_raw, self._checkpoint = capture_raw, checkpoint
        path = self._path
        try:
            self._guard = LocalPathGuard(path, directory=False)
            self._guard.__enter__()
            if expected_file is not None and self._guard.identity != expected_file:
                raise ConfigReadError('CONFIG_READ_ORIGINAL_FILE_DIFFERS')
            handle = self._kernel.CreateFileW(
                '\\\\?\\' + str(path),
                0x80000000,
                0x1,
                None,
                3,
                0x00200000 | 0x00100000 | 0x08000000,
                None,
            )
            if handle == ctypes.c_void_p(-1).value or not handle:
                raise _failure('CONFIG_READ_LOCK_UNAVAILABLE')
            self._handle = handle
            self._snapshot = self._read()
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    def _initialize(self, path, max_file_bytes, expected_file):
        if type(max_file_bytes) is not int or not 1 <= max_file_bytes <= MAX_SAFE_INTEGER:
            raise ConfigReadError('CONFIG_READ_LIMIT_INVALID')
        if expected_file is not None and type(expected_file) is not FileIdentity:
            raise ConfigReadError('CONFIG_READ_IDENTITY_INVALID')
        path = local_absolute_path(path)
        try:
            units = len(str(path).encode('utf-16-le', errors='strict')) // 2
        except UnicodeError:
            raise ConfigReadError('CONFIG_READ_PATH_UNICODE_INVALID') from None
        if units > 240:
            raise ConfigReadError('CONFIG_READ_PATH_TOO_LONG')
        self._path, self._limit = path, max_file_bytes
        self._gate = RLock()
        self._kernel = read_api()
        self._guard = None
        self._handle = None
        self._closing = False
        self._borrows = 0
        self._snapshot = None
        self._expected_file = expected_file
        self._source_process = None
        self._capture_raw, self._checkpoint = True, None

    @property
    def snapshot(self):
        return self._snapshot

    def _attributes(self):
        flags = wintypes.DWORD()
        if (
            not self._kernel.GetHandleInformation(self._handle, ctypes.byref(flags))
            or flags.value & 1
            or self._kernel.GetFileType(self._handle) != 1
        ):
            raise _failure('CONFIG_READ_HANDLE_UNVERIFIED')
        actual = _identity(self._kernel, self._handle, self._path)
        expected = self._expected_file if self._guard is None else self._guard.verify()
        if actual != expected:
            raise ConfigReadError('CONFIG_READ_ORIGINAL_FILE_DIFFERS')
        basic = HandleInfo()
        if not self._kernel.GetFileInformationByHandle(self._handle, ctypes.byref(basic)):
            raise _failure('CONFIG_READ_ATTRIBUTES_UNAVAILABLE')
        if basic.attributes & UNSUPPORTED_ATTRIBUTES:
            raise ConfigReadError('CONFIG_READ_ATTRIBUTES_UNSUPPORTED')
        count = (basic.size_high << 32) | basic.size_low
        if count > self._limit:
            raise ConfigReadError('CONFIG_READ_BYTES_EXCEEDED')
        return actual, count

    def _read(self, *, capture_raw=None, consume=None):
        original, count = self._attributes()
        if capture_raw is None:
            capture_raw = self._capture_raw
        position = ctypes.c_int64()
        if not self._kernel.SetFilePointerEx(self._handle, 0, ctypes.byref(position), 0):
            raise _failure('CONFIG_READ_SEEK_UNAVAILABLE')
        if position.value != 0:
            raise ConfigReadError('CONFIG_READ_SEEK_DIFFERS')
        buffer = ctypes.create_string_buffer(READ_CHUNK)
        raw = bytearray() if capture_raw else None
        digest = hashlib.sha256() if raw is None else None
        total = 0
        while True:
            if self._checkpoint is not None:
                self._checkpoint()
            read = wintypes.DWORD()
            if not self._kernel.ReadFile(
                self._handle, buffer, len(buffer), ctypes.byref(read), None
            ):
                raise _failure('CONFIG_READ_UNAVAILABLE')
            if read.value > len(buffer):
                raise ConfigReadError('CONFIG_READ_SIZE_INVALID')
            if not read.value:
                break
            total += read.value
            if total > count:
                raise ConfigReadError('CONFIG_READ_SOURCE_CHANGED')
            chunk = buffer.raw[: read.value]
            if raw is None:
                digest.update(chunk)
            else:
                raw.extend(chunk)
            if consume is not None:
                consume(chunk)
        if total != count or self._attributes() != (original, count):
            raise ConfigReadError('CONFIG_READ_SOURCE_CHANGED')
        data = b'' if raw is None else bytes(raw)
        sha = digest.hexdigest() if raw is None else self._digest(data)
        return ConfigSourceSnapshot(original, count, sha, data)

    def _digest(self, data):
        return hashlib.sha256(data).hexdigest()

    def verify(self):
        with self._gate:
            if self._closing or self._handle is None:
                raise ConfigReadError('CONFIG_READ_LEASE_CLOSED')
            if self._read() != self.snapshot:
                raise ConfigReadError('CONFIG_READ_SOURCE_CHANGED')
            return self.snapshot

    def verified_raw(self):
        with self._gate:
            if self._closing or self._handle is None:
                raise ConfigReadError('CONFIG_READ_LEASE_CLOSED')
            observed = self._read(capture_raw=True)
            original = self.snapshot
            if (
                observed.file != original.file
                or observed.byte_count != original.byte_count
                or observed.sha256 != original.sha256
            ):
                raise ConfigReadError('CONFIG_READ_SOURCE_CHANGED')
            return observed.raw

    def consume_verified(self, consume):
        """Stream original bytes through the read-only handle, then compare its digest."""
        if not callable(consume):
            raise TypeError('Original file consumer required')
        with self._gate:
            if self._closing or self._handle is None:
                raise ConfigReadError('CONFIG_READ_LEASE_CLOSED')
            observed = self._read(capture_raw=False, consume=consume)
            original = self.snapshot
            if (
                observed.file != original.file
                or observed.byte_count != original.byte_count
                or observed.sha256 != original.sha256
            ):
                raise ConfigReadError('CONFIG_READ_SOURCE_CHANGED')

    @contextmanager
    def hold(self):
        with self._gate:
            original = self.verify()
            self._borrows += 1
        try:
            yield original
        finally:
            with self._gate:
                self._borrows -= 1
                self.verify()

    def close(self):
        with self._gate:
            if self._borrows:
                raise ConfigReadError('CONFIG_READ_IN_USE')
            self._closing = True
            failure = None
            if self._handle is not None:
                if self._kernel.CloseHandle(self._handle):
                    self._handle = None
                else:
                    failure = _failure('CONFIG_READ_CLOSE_UNVERIFIED')
            if self._source_process is not None:
                if self._kernel.CloseHandle(self._source_process):
                    self._source_process = None
                elif failure is None:
                    failure = _failure('CONFIG_READ_SOURCE_PROCESS_CLOSE_UNVERIFIED')
            if self._handle is None and self._guard is not None:
                try:
                    self._guard.close()
                    self._guard = None
                except PathBoundaryError as error:
                    failure = error
            if failure is not None:
                failure.retained_owner = self
                raise failure

    def __enter__(self):
        self.verify()
        return self

    def __exit__(self, kind, error, traceback):
        self.close()


class LockedConfigSource(LockedFileSource):
    """Retain the registered Git config-byte policy on the same native lease."""

    def _digest(self, data):
        return config_source_sha256(data, max_file_bytes=self._limit)
