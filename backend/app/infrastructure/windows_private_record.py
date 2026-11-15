"""Append one private receipt by its original NTFS handle, never path replacement.

Caller owns the active PrivatePackageGuard. Publication is no-replace; an
uncertain rename is never retried or deleted. Unpublished cleanup addresses only
the actual CREATE_NEW handle. This does not claim power-loss testing.
"""

import ctypes
import hashlib
import re
from ctypes import wintypes
from dataclasses import dataclass, field
from threading import RLock
from uuid import uuid4

from backend.app.shared.validation import MAX_SAFE_INTEGER

from .windows_config_copy import _api as record_api
from .windows_config_copy import _Disposition
from .windows_executable_pin import READ_CHUNK
from .windows_local_paths import FileIdentity, _identity
from .windows_private_package import PrivatePackageGuard, _verify_acl


class PrivateRecordError(RuntimeError):
    def __init__(self, reason, native_error=None):
        self.reason, self.native_error = reason, native_error
        super().__init__(reason)


class _RenameInfo(ctypes.Structure):
    # BOOLEAN followed by native alignment gives HANDLE@8, DWORD@16, WCHAR@20.
    _fields_ = [
        ('replace', ctypes.c_ubyte),
        ('root', wintypes.HANDLE),
        ('name_bytes', wintypes.DWORD),
        ('name', wintypes.WCHAR * 1),
    ]


def rename_private_handle_no_replace(kernel, handle, target):
    if (_RenameInfo.root.offset, _RenameInfo.name_bytes.offset, _RenameInfo.name.offset) != (
        8,
        16,
        20,
    ):
        raise PrivateRecordError('PRIVATE_RECORD_NATIVE_LAYOUT_UNSUPPORTED')
    encoded = str(target).encode('utf-16-le', errors='strict')
    size = _RenameInfo.name.offset + len(encoded) + 2
    buffer = ctypes.create_string_buffer(size)
    info = ctypes.cast(buffer, ctypes.POINTER(_RenameInfo)).contents
    info.replace, info.root, info.name_bytes = 0, None, len(encoded)
    ctypes.memmove(ctypes.addressof(buffer) + _RenameInfo.name.offset, encoded, len(encoded))
    if not kernel.SetFileInformationByHandle(handle, 3, buffer, size):
        raise _failure('PRIVATE_RECORD_RENAME_UNVERIFIED')


@dataclass(frozen=True)
class PrivateRecordReference:
    filename: str
    sha256: str
    byte_count: int
    file: FileIdentity = field(repr=False)


def _failure(reason):
    return PrivateRecordError(reason, ctypes.get_last_error())


class PrivateRecordAppend:
    def __init__(self, package, filename, raw, *, max_record_bytes):
        if type(package) is not PrivatePackageGuard:
            raise PrivateRecordError('ORIGINAL_PRIVATE_RECORD_PACKAGE_REQUIRED')
        if package.is_control_git_read_package:
            raise PrivateRecordError('PRIVATE_RECORD_OPERATOR_ONLY_PACKAGE_REQUIRED')
        basis_document = (
            type(filename) is str
            and re.fullmatch(r'[a-f0-9]{32}\.b[1-9][0-9]{0,15}\.md', filename) is not None
        )
        delivery_commit = (
            type(filename) is str
            and re.fullmatch(r'[a-f0-9]{32}\.delivery-commit\.bin', filename) is not None
        )
        journal_file = type(filename) is str and (
            filename == 'runtime-guard.lock'
            or re.fullmatch(r'\.(?:launch|guard-action)-[a-f0-9]{32}\.tmp', filename) is not None
        )
        if not (basis_document or delivery_commit or journal_file) and (
            type(filename) is not str
            or re.fullmatch(
                r'[a-f0-9]{32}\.(?:git|delivery-stop|snapshot-query|snapshot-query-closed|workspace-stage|workspace-tree|workspace-release-(?:intent|ack)|runtime-workspace(?:-intent)?|basis-seal|task-guard-owner|task-guard-binding)\.json|[a-f0-9]{64}\.[a-f0-9]{32}\.native\.json|[a-f0-9]{64}\.(?:controller(?:-seal)?|project-check(?:-completion|-export|-(?:prepare|create-suspended|resume|stop|release)-(?:intent|ack))?|testing-http-(?:outcome|request-[1-9][0-9]{0,2})|browser-(?:case-result|request-[1-9][0-9]{0,2})|task-network(?:-install)?|task-basis-complete|task-files(?:-held)?|task-workspace-(?:write|published)|task-runtime-(?:intent|files)|task-execution-prepared|task-control-credential|task-launch-confirm-intent|task-native-output|task-repair-source-(?:intent|ack)|task-repair-plan|task-directory-release-(?:intent|ack)|task-opencode-(?:(?:session|initial|permission)-(?:intent|ack)|initial-planned)|task-backend-(?:prepare|create-suspended|resume|stop|release)-(?:intent|ack)|task-native-(?:suspended|stopped)|task-lpac-profile-(?:intent|created|release|released))\.json',
                filename,
            )
            is None
        ):
            raise PrivateRecordError('PRIVATE_RECORD_NAME_INVALID')
        if type(max_record_bytes) is not int or not 1 <= max_record_bytes <= MAX_SAFE_INTEGER:
            raise PrivateRecordError('PRIVATE_RECORD_LIMIT_INVALID')
        if (
            type(raw) is not bytes
            or (not raw and not basis_document)
            or len(raw) > max_record_bytes
        ):
            raise PrivateRecordError('PRIVATE_RECORD_BYTES_INVALID')
        if (_RenameInfo.root.offset, _RenameInfo.name_bytes.offset, _RenameInfo.name.offset) != (
            8,
            16,
            20,
        ):
            raise PrivateRecordError('PRIVATE_RECORD_NATIVE_LAYOUT_UNSUPPORTED')
        self._gate = RLock()
        self._package, self._filename = package, filename
        self._stage = package.path / ('.record-' + uuid4().hex + '.tmp')
        self._target = package.path / filename
        self._raw_size = len(raw)
        self._sha256 = hashlib.sha256(raw).hexdigest()
        self._handle = None
        self._identity = None
        self._rename_may = False
        self._published = False
        self._closing = False
        self._delete_marked = False
        self._reference = None
        self._kernel = record_api()
        try:
            self._package_identity = package.verify()
            self._create(raw)
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    @property
    def reference(self):
        if not self._published:
            raise PrivateRecordError('PRIVATE_RECORD_NOT_PUBLISHED')
        return self._reference

    def _create(self, raw):
        with self._package.file_creation_attributes() as attributes:
            handle = self._kernel.CreateFileW(
                '\\\\?\\' + str(self._stage),
                0x80000000 | 0x40000000 | 0x10000 | 0x80,
                0x1,
                ctypes.byref(attributes),
                1,
                0x00200000 | 0x00100000,
                None,
            )
            if not handle or handle == ctypes.c_void_p(-1).value:
                raise _failure('PRIVATE_RECORD_CREATE_FAILED')
            self._handle = handle
        self._identity = _identity(self._kernel, handle, self._stage)
        _verify_acl(self._stage, self._package.operator_sid, protected=False)
        offset = 0
        while offset < len(raw):
            part = raw[offset : offset + READ_CHUNK]
            data = ctypes.create_string_buffer(part)
            written = wintypes.DWORD()
            if not self._kernel.WriteFile(handle, data, len(part), ctypes.byref(written), None):
                raise _failure('PRIVATE_RECORD_WRITE_UNVERIFIED')
            if not 1 <= written.value <= len(part):
                raise PrivateRecordError('PRIVATE_RECORD_WRITE_SIZE_INVALID')
            offset += written.value
        if not self._kernel.FlushFileBuffers(handle):
            raise _failure('PRIVATE_RECORD_FLUSH_UNVERIFIED')
        self._verify_bytes(self._stage)

    def _verify_bytes(self, path):
        actual = _identity(self._kernel, self._handle, path)
        if (
            actual.volume_serial != self._identity.volume_serial
            or actual.file_id != self._identity.file_id
            or actual.is_directory
        ):
            raise PrivateRecordError('PRIVATE_RECORD_ORIGINAL_FILE_DIFFERS')
        position = ctypes.c_int64()
        if (
            not self._kernel.SetFilePointerEx(self._handle, 0, ctypes.byref(position), 0)
            or position.value != 0
        ):
            raise _failure('PRIVATE_RECORD_SEEK_UNVERIFIED')
        digest, count = hashlib.sha256(), 0
        buffer = ctypes.create_string_buffer(READ_CHUNK)
        while True:
            read = wintypes.DWORD()
            if not self._kernel.ReadFile(
                self._handle, buffer, len(buffer), ctypes.byref(read), None
            ):
                raise _failure('PRIVATE_RECORD_READ_UNVERIFIED')
            if read.value > len(buffer) or count + read.value > self._raw_size:
                raise PrivateRecordError('PRIVATE_RECORD_BYTES_DIFFER')
            if not read.value:
                break
            digest.update(buffer.raw[: read.value])
            count += read.value
        if count != self._raw_size or digest.hexdigest() != self._sha256:
            raise PrivateRecordError('PRIVATE_RECORD_BYTES_DIFFER')
        return actual

    def publish(self):
        with self._gate:
            if self._closing or self._handle is None:
                raise PrivateRecordError('PRIVATE_RECORD_CLOSED')
            if self._published:
                self._verify_bytes(self._target)
                return self.reference
            if self._rename_may:
                raise PrivateRecordError('PRIVATE_RECORD_RENAME_REQUIRES_OBSERVATION')
            if self._package.verify() != self._package_identity:
                raise PrivateRecordError('PRIVATE_RECORD_PACKAGE_DIFFERS')
            self._verify_bytes(self._stage)
            # Fully qualified same-directory destination. No replace flag,
            # relative-root, path-based rename, copy or deletion fallback.
            self._rename_may = True
            rename_private_handle_no_replace(self._kernel, self._handle, self._target)
            if not self._kernel.FlushFileBuffers(self._handle):
                raise _failure('PRIVATE_RECORD_PUBLISHED_FLUSH_UNVERIFIED')
            actual = self._verify_bytes(self._target)
            _verify_acl(self._target, self._package.operator_sid, protected=False)
            if self._package.verify() != self._package_identity:
                raise PrivateRecordError('PRIVATE_RECORD_PACKAGE_DIFFERS')
            self._reference = PrivateRecordReference(
                self._filename, self._sha256, self._raw_size, actual
            )
            self._published = True
            return self.reference

    def close(self):
        with self._gate:
            self._closing = True
            if self._handle is None:
                return
            try:
                if not self._rename_may and not self._delete_marked:
                    disposition = _Disposition(1)
                    if not self._kernel.SetFileInformationByHandle(
                        self._handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)
                    ):
                        raise _failure('PRIVATE_RECORD_STAGE_DELETE_UNVERIFIED')
                    self._delete_marked = True
                # Published or uncertain publication is retained, never unlinked.
                if not self._kernel.CloseHandle(self._handle):
                    raise _failure('PRIVATE_RECORD_CLOSE_UNVERIFIED')
                self._handle = None
            except BaseException as error:
                error.retained_owner = self
                raise

    def __enter__(self):
        if self._closing or self._handle is None:
            raise PrivateRecordError('PRIVATE_RECORD_CLOSED')
        return self

    def __exit__(self, kind, error, traceback):
        self.close()
