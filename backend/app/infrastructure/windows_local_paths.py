"""DB20 local NTFS path identities held open without delete/rename sharing.

This is a maintenance prerequisite, not an LPAC/Guard or maintenance-window
proof. It never reads business file contents, changes ACLs or repairs a path.
"""

import ctypes
import ntpath
import os
import re
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath


class PathBoundaryError(RuntimeError):
    def __init__(self, code: str, native_error: int | None = None):
        self.code = code
        self.native_error = native_error
        super().__init__(code)


@dataclass(frozen=True)
class FileIdentity:
    canonical_path: str
    volume_serial: str
    file_id: str
    is_directory: bool
    filesystem: str


class FileIdInfo(ctypes.Structure):
    _fields_ = [
        ('volume_serial', ctypes.c_uint64),
        ('file_id', ctypes.c_ubyte * 16),
    ]


class HandleInfo(ctypes.Structure):
    _fields_ = [
        ('attributes', wintypes.DWORD),
        ('creation', wintypes.FILETIME),
        ('access', wintypes.FILETIME),
        ('write', wintypes.FILETIME),
        ('volume_serial', wintypes.DWORD),
        ('size_high', wintypes.DWORD),
        ('size_low', wintypes.DWORD),
        ('links', wintypes.DWORD),
        ('index_high', wintypes.DWORD),
        ('index_low', wintypes.DWORD),
    ]


def local_absolute_path(value: Path | str) -> Path:
    """Reject namespace/stream/device aliases before any native or network IO."""
    text = os.fspath(value)
    if type(text) is not str or not text or len(text) > 32000 or '\0' in text:
        raise PathBoundaryError('PATH_INVALID')
    text = text.replace('/', '\\')
    if re.match(r'^[A-Za-z]:\\', text) is None:
        raise PathBoundaryError('LOCAL_ABSOLUTE_PATH_REQUIRED')
    parts = text[3:].split('\\')
    if parts and parts[-1] == '':
        parts.pop()
    for part in parts:
        if (
            not part
            or part in ('.', '..')
            or part.endswith(('.', ' '))
            or any(char in part for char in ':*?"<>|')
            or any(ord(char) < 32 for char in part)
            or re.fullmatch(
                r'CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³]',
                part.split('.')[0].rstrip(' '),
                re.IGNORECASE,
            )
        ):
            raise PathBoundaryError('AMBIGUOUS_PATH_COMPONENT')
    return Path(str(PureWindowsPath(text)))


def _api():
    if os.name != 'nt':
        raise PathBoundaryError('WINDOWS_PATH_API_REQUIRED')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(HandleInfo)]
    kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel.GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    kernel.GetDriveTypeW.restype = wintypes.UINT
    kernel.GetVolumeInformationByHandleW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
        wintypes.DWORD,
    ]
    kernel.GetVolumeInformationByHandleW.restype = wintypes.BOOL
    return kernel


def _failure(code):
    return PathBoundaryError(code, ctypes.get_last_error())


def _final_path(kernel, handle):
    buffer = ctypes.create_unicode_buffer(32768)
    size = kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
    if size == 0 or size >= len(buffer):
        raise _failure('FINAL_PATH_UNAVAILABLE')
    result = buffer.value
    if not result.startswith('\\\\?\\') or result.startswith('\\\\?\\UNC\\'):
        raise PathBoundaryError('LOCAL_FINAL_PATH_REQUIRED')
    return result[4:]


def _identity(kernel, handle, expected_path):
    basic = HandleInfo()
    if not kernel.GetFileInformationByHandle(handle, ctypes.byref(basic)):
        raise _failure('FILE_ATTRIBUTES_UNAVAILABLE')
    if basic.attributes & 0x400:
        raise PathBoundaryError('REPARSE_POINT_REJECTED')
    directory = bool(basic.attributes & 0x10)
    if not directory and basic.links != 1:
        raise PathBoundaryError('MULTIPLE_HARD_LINKS_REJECTED')
    identity = FileIdInfo()
    if not kernel.GetFileInformationByHandleEx(
        handle, 18, ctypes.byref(identity), ctypes.sizeof(identity)
    ):
        raise _failure('FILE_ID_UNAVAILABLE')
    final = _final_path(kernel, handle)
    if ntpath.normcase(ntpath.normpath(final)) != ntpath.normcase(str(expected_path)):
        raise PathBoundaryError('CANONICAL_PATH_DIFFERS')
    filesystem = ctypes.create_unicode_buffer(64)
    flags = wintypes.DWORD()
    if not kernel.GetVolumeInformationByHandleW(
        handle, None, 0, None, None, ctypes.byref(flags), filesystem, len(filesystem)
    ):
        raise _failure('VOLUME_INFORMATION_UNAVAILABLE')
    if filesystem.value.upper() != 'NTFS' or not flags.value & 0x8:
        raise PathBoundaryError('NTFS_WITH_PERSISTENT_ACL_REQUIRED')
    return FileIdentity(
        str(Path(final)),
        f'{identity.volume_serial:016x}',
        bytes(identity.file_id).hex(),
        directory,
        filesystem.value.upper(),
    )


class LocalPathGuard:
    def __init__(self, path: Path | str, *, directory: bool):
        if type(directory) is not bool:
            raise ValueError('Specify the actual expected path type')
        self.path = local_absolute_path(path)
        self.directory = directory
        self._kernel = None
        self._held = []
        self._closing = False
        self.identity: FileIdentity | None = None

    def __enter__(self):
        if self._held:
            raise RuntimeError('The path guard is already active')
        kernel = _api()
        self._closing = False
        self._kernel = kernel
        if kernel.GetDriveTypeW(self.path.anchor) not in (2, 3):
            raise PathBoundaryError('LOCAL_VOLUME_REQUIRED')
        current = Path(self.path.anchor)
        components = [current]
        for part in self.path.parts[1:]:
            current = current / part
            components.append(current)
        try:
            for index, path in enumerate(components):
                # OPEN_EXISTING, OPEN_REPARSE_POINT and BACKUP_SEMANTICS.
                # READ/WRITE sharing permits SQLite IO; absence of DELETE sharing
                # keeps this object and each ancestor from being renamed/replaced.
                handle = kernel.CreateFileW(
                    '\\\\?\\' + str(path),
                    0x80,
                    0x1 | 0x2,
                    None,
                    3,
                    0x00200000 | 0x02000000,
                    None,
                )
                if handle == ctypes.c_void_p(-1).value:
                    raise _failure('PATH_HANDLE_UNAVAILABLE')
                self._held.append((handle, path, None))
                actual = _identity(kernel, handle, path)
                expected_directory = index < len(components) - 1 or self.directory
                if actual.is_directory != expected_directory:
                    raise PathBoundaryError('PATH_TYPE_DIFFERS')
                self._held[-1] = (handle, path, actual)
            self.identity = self._held[-1][2]
            self.verify()
            return self
        except BaseException:
            self.close()
            raise

    def verify(self) -> FileIdentity:
        if not self._held or self._kernel is None or self._closing:
            raise RuntimeError('An active native path guard is required')
        for handle, path, expected in self._held:
            if _identity(self._kernel, handle, path) != expected:
                raise PathBoundaryError('FILE_IDENTITY_CHANGED')
        return self._held[-1][2]

    def close(self):
        self._closing = True
        if self._kernel is None:
            return
        remaining = []
        failures = []
        for item in reversed(self._held):
            handle, _, _ = item
            if self._kernel.CloseHandle(handle):
                continue
            remaining.append(item)
            failures.append(ctypes.get_last_error())
        self._held = list(reversed(remaining))
        if not self._held:
            self._kernel = None
        if failures:
            error = PathBoundaryError('PATH_HANDLE_CLOSE_UNVERIFIED', failures[0])
            error.retained_owner = self
            raise error

    def __exit__(self, error_type, error, traceback):
        self.close()


class LocalDirectoryPin:
    """Hold a native data handle as well as the original directory path guards."""

    def __init__(self, path, *, expected=None):
        self._path = LocalPathGuard(path, directory=True)
        self._expected = expected
        self._handle = None

    def __enter__(self):
        try:
            self._path.__enter__()
            identity = self._path.verify()
            if self._expected is not None and identity != self._expected:
                raise PathBoundaryError('ORIGINAL_DIRECTORY_PIN_DIFFERS')
            self._expected = identity
            kernel = self._path._kernel
            handle = kernel.CreateFileW(
                '\\\\?\\' + str(self._path.path), 0x81, 0x3, None, 3, 0x02200000, None
            )
            if not handle or handle == ctypes.c_void_p(-1).value:
                raise _failure('ORIGINAL_DIRECTORY_PIN_UNAVAILABLE')
            self._handle = handle
            self.verify()
            return self
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                raise cleanup from original
            raise

    def verify(self):
        if (
            self._handle is None
            or self._path.verify() != self._expected
            or _identity(self._path._kernel, self._handle, self._path.path) != self._expected
        ):
            raise PathBoundaryError('ORIGINAL_DIRECTORY_PIN_DIFFERS')
        return self._expected

    def close(self):
        try:
            if self._handle is not None:
                if not self._path._kernel.CloseHandle(self._handle):
                    raise _failure('ORIGINAL_DIRECTORY_PIN_CLOSE_UNVERIFIED')
                self._handle = None
            self._path.close()
        except BaseException as error:
            error.retained_owner = self
            raise

    def __exit__(self, kind, error, traceback):
        self.close()
