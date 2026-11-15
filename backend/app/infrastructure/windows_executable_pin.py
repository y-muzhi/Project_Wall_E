"""Retain one registered x64 image's original NTFS object during native creation.

The caller supplies trusted catalog bytes/identity, never an RPC path or digest.
This is a file lease, not a signature, package ACL or runtime-admission proof.
No process executes here. Writable mapped sections and hostile administrators
remain outside this sharing check; protected runtime admission is independent.
"""

import ctypes
import hashlib
import re
import struct
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from threading import RLock

from .windows_local_paths import (
    FileIdentity,
    HandleInfo,
    LocalPathGuard,
    PathBoundaryError,
    _identity,
    local_absolute_path,
)
from .windows_local_paths import (
    _api as path_api,
)

READ_CHUNK = 64 * 1024
PE_HEADER_LIMIT = 1024 * 1024
# DIRECTORY / DEVICE / REPARSE / OFFLINE / ENCRYPTED / recall on open or data.
UNSUPPORTED_ATTRIBUTES = 0x10 | 0x40 | 0x400 | 0x1000 | 0x4000 | 0x40000 | 0x400000


class ExecutablePinError(RuntimeError):
    def __init__(self, code, native_error=None):
        self.code = code
        self.native_error = native_error
        super().__init__(code)


@dataclass(frozen=True)
class ExecutableIdentity:
    file: FileIdentity
    byte_count: int
    sha256: str
    architecture: str


def _failure(code):
    return ExecutablePinError(code, ctypes.get_last_error())


def _api():
    kernel = path_api()
    kernel.GetFileType.argtypes = [wintypes.HANDLE]
    kernel.GetFileType.restype = wintypes.DWORD
    kernel.GetHandleInformation.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetHandleInformation.restype = wintypes.BOOL
    kernel.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel.ReadFile.restype = wintypes.BOOL
    kernel.SetFilePointerEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int64,
        ctypes.POINTER(ctypes.c_int64),
        wintypes.DWORD,
    ]
    kernel.SetFilePointerEx.restype = wintypes.BOOL
    return kernel


def _pe_x64(header, count):
    if len(header) < 64 or header[:2] != b'MZ':
        raise ExecutablePinError('REGISTERED_IMAGE_NOT_PE')
    offset = struct.unpack_from('<I', header, 0x3C)[0]
    if not 64 <= offset <= PE_HEADER_LIMIT or offset + 26 > len(header):
        raise ExecutablePinError('REGISTERED_IMAGE_HEADER_INVALID')
    if header[offset : offset + 6] != b'PE\0\0\x64\x86':
        raise ExecutablePinError('REGISTERED_IMAGE_NOT_AMD64')
    optional_size, characteristics = struct.unpack_from('<HH', header, offset + 20)
    if (
        optional_size < 112
        or offset + 24 + optional_size > count
        or not characteristics & 0x2
        or characteristics & 0x2000
        or struct.unpack_from('<H', header, offset + 24)[0] != 0x20B
    ):
        raise ExecutablePinError('REGISTERED_IMAGE_NOT_X64_EXECUTABLE')


class ExecutablePin:
    """Keep metadata ancestors and a read-only, no-WRITE/no-DELETE data handle."""

    def __init__(self, path, *, expected_byte_count, expected_sha256, expected_file=None):
        if type(expected_byte_count) is not int or not 1 <= expected_byte_count <= 2**53 - 1:
            raise ExecutablePinError('REGISTERED_IMAGE_SIZE_INVALID')
        if (
            type(expected_sha256) is not str
            or re.fullmatch('[0-9a-f]{64}', expected_sha256) is None
        ):
            raise ExecutablePinError('REGISTERED_IMAGE_DIGEST_INVALID')
        if expected_file is not None and type(expected_file) is not FileIdentity:
            raise ExecutablePinError('REGISTERED_FILE_IDENTITY_INVALID')
        path = local_absolute_path(path)
        try:
            units = len(str(path).encode('utf-16-le', errors='strict')) // 2
        except UnicodeError:
            raise ExecutablePinError('REGISTERED_IMAGE_PATH_UNICODE_INVALID') from None
        if units > 240:
            raise ExecutablePinError('REGISTERED_IMAGE_PATH_TOO_LONG')
        self._path = path
        self._expected_count = expected_byte_count
        self._expected_digest = expected_sha256
        self._expected_file = expected_file
        self._gate = RLock()
        self._kernel = _api()
        self._guard = None
        self._handle = None
        self._identity = None
        self._closing = False
        self._borrows = 0
        try:
            self._guard = LocalPathGuard(path, directory=False)
            self._guard.__enter__()
            if expected_file is not None and self._guard.identity != expected_file:
                raise ExecutablePinError('REGISTERED_FILE_IDENTITY_DIFFERS')
            # OPEN_EXISTING, OPEN_REPARSE_POINT, OPEN_NO_RECALL, sequential scan.
            # FILE_SHARE_READ denies both pre-existing and future write/delete opens.
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
                raise _failure('REGISTERED_IMAGE_READ_LOCK_UNAVAILABLE')
            self._handle = handle
            self._identity = self._verify_bytes()
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    @property
    def identity(self):
        return self._identity

    @property
    def path(self):
        return self._path

    def _attributes(self):
        flags = wintypes.DWORD()
        if (
            not self._kernel.GetHandleInformation(self._handle, ctypes.byref(flags))
            or flags.value & 1
            or self._kernel.GetFileType(self._handle) != 1
        ):
            raise _failure('REGISTERED_IMAGE_HANDLE_UNVERIFIED')
        actual = _identity(self._kernel, self._handle, self._path)
        if actual != self._guard.verify():
            raise ExecutablePinError('REGISTERED_IMAGE_OBJECT_DIFFERS')
        basic = HandleInfo()
        if not self._kernel.GetFileInformationByHandle(self._handle, ctypes.byref(basic)):
            raise _failure('REGISTERED_IMAGE_ATTRIBUTES_UNAVAILABLE')
        if basic.attributes & UNSUPPORTED_ATTRIBUTES:
            raise ExecutablePinError('REGISTERED_IMAGE_ATTRIBUTES_UNSUPPORTED')
        count = (basic.size_high << 32) | basic.size_low
        if count != self._expected_count:
            raise ExecutablePinError('REGISTERED_IMAGE_SIZE_DIFFERS')
        return actual

    def _verify_bytes(self):
        actual = self._attributes()
        position = ctypes.c_int64()
        if not self._kernel.SetFilePointerEx(self._handle, 0, ctypes.byref(position), 0):
            raise _failure('REGISTERED_IMAGE_SEEK_UNAVAILABLE')
        if position.value != 0:
            raise ExecutablePinError('REGISTERED_IMAGE_SEEK_DIFFERS')
        buffer = ctypes.create_string_buffer(READ_CHUNK)
        digest = hashlib.sha256()
        header = bytearray()
        total = 0
        while True:
            read = wintypes.DWORD()
            if not self._kernel.ReadFile(
                self._handle,
                buffer,
                len(buffer),
                ctypes.byref(read),
                None,
            ):
                raise _failure('REGISTERED_IMAGE_READ_UNAVAILABLE')
            if read.value > len(buffer):
                raise ExecutablePinError('REGISTERED_IMAGE_READ_SIZE_INVALID')
            if not read.value:
                break
            total += read.value
            if total > self._expected_count:
                raise ExecutablePinError('REGISTERED_IMAGE_SIZE_DIFFERS')
            data = buffer.raw[: read.value]
            digest.update(data)
            if len(header) < PE_HEADER_LIMIT + 26:
                header.extend(data[: PE_HEADER_LIMIT + 26 - len(header)])
        if total != self._expected_count or digest.hexdigest() != self._expected_digest:
            raise ExecutablePinError('REGISTERED_IMAGE_BYTES_DIFFER')
        _pe_x64(header, total)
        if self._attributes() != actual:
            raise ExecutablePinError('REGISTERED_IMAGE_OBJECT_DIFFERS')
        return ExecutableIdentity(actual, total, digest.hexdigest(), 'win-x64')

    def verify(self):
        with self._gate:
            if self._closing or self._handle is None:
                raise ExecutablePinError('REGISTERED_IMAGE_PIN_CLOSED')
            if self._verify_bytes() != self.identity:
                raise ExecutablePinError('REGISTERED_IMAGE_IDENTITY_DIFFERS')
            return self.identity

    @contextmanager
    def creation_path(self):
        with self._gate:
            self.verify()
            self._borrows += 1
            try:
                yield str(self._path)
            finally:
                self._borrows -= 1
                # Creation may already have succeeded: caller must retain its
                # original native result if this postcondition cannot be proved.
                self.verify()

    def close(self):
        with self._gate:
            if self._borrows:
                raise ExecutablePinError('REGISTERED_IMAGE_IN_USE')
            self._closing = True
            errors = []
            if self._handle is not None:
                if self._kernel.CloseHandle(self._handle):
                    self._handle = None
                else:
                    errors.append(_failure('REGISTERED_IMAGE_CLOSE_UNVERIFIED'))
            # Keep ancestors until the final data handle is actually closed.
            if self._handle is None and self._guard is not None:
                try:
                    self._guard.close()
                    self._guard = None
                except PathBoundaryError as error:
                    errors.append(error)
            if errors:
                error = ExecutablePinError(
                    'REGISTERED_IMAGE_CLOSE_UNVERIFIED',
                    getattr(errors[0], 'native_error', None),
                )
                error.retained_owner = self
                raise error from errors[0]

    def __enter__(self):
        self.verify()
        return self

    def __exit__(self, kind, error, traceback):
        self.close()
