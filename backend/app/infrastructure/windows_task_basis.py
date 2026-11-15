"""One original task-basis file, handed to the ordinary backend by a write-only data handle."""

import ctypes
import hashlib
import os
import re
from ctypes import wintypes
from dataclasses import dataclass, field

from backend.app.shared.validation import MAX_SAFE_INTEGER

from .runtime_launch_journal import LaunchOutcomeUnknown, LaunchScope
from .windows_config_copy import _api as file_io
from .windows_empty_directory import OWNER_RIGHTS
from .windows_executable_pin import READ_CHUNK
from .windows_local_paths import FileIdentity, HandleInfo, _identity, local_absolute_path
from .windows_private_package import OPERATOR_ACCESS, _sid_text
from .windows_process import NativeProcessIdentity, ObservedProcess
from .windows_process import _identity as process_identity
from .windows_stdio import ObjectBasicInformation, _handle, _handle_text
from .windows_stdio import _api as duplicate_api
from .windows_task_directories import (
    _FILE_READ,
    _LABEL_TYPE,
    _MEDIUM,
    TaskLpacDirectories,
    _read_aces,
)

_WRITE_ACCESS = 0x00100082  # FILE_WRITE_DATA | FILE_READ_ATTRIBUTES | SYNCHRONIZE


class TaskBasisTransferError(LaunchOutcomeUnknown):
    def __init__(self, code, native_error=None):
        self.native_error = native_error
        super().__init__(code)


@dataclass(frozen=True)
class BasisCopySpec:
    number: int
    byte_count: int
    sha256: str
    source_sha256: str

    def __post_init__(self):
        if (
            type(self.number) is not int
            or not 1 <= self.number <= MAX_SAFE_INTEGER
            or type(self.byte_count) is not int
            or not 0 <= self.byte_count <= MAX_SAFE_INTEGER
            or any(
                type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None
                for value in (self.sha256, self.source_sha256)
            )
        ):
            raise TaskBasisTransferError('ORIGINAL_BASIS_COPY_SPEC_REQUIRED')

    @property
    def filename(self):
        return f'b{self.number}.md'


@dataclass(frozen=True)
class BasisCopyReceipt:
    scope: LaunchScope
    binding_ref: str
    spec: BasisCopySpec
    file: FileIdentity = field(repr=False)


@dataclass(frozen=True)
class BasisWriteOffer:
    owner: NativeProcessIdentity = field(repr=False)
    expected: BasisCopyReceipt
    writer: str = field(repr=False)


def _failure(code):
    return TaskBasisTransferError(code, ctypes.get_last_error())


def _length(kernel, handle):
    info = HandleInfo()
    if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
        raise _failure('ORIGINAL_BASIS_COPY_LENGTH_UNAVAILABLE')
    return (info.size_high << 32) | info.size_low


class TaskBasisSlot:
    """Guard retains the original file without reading the document body."""

    def __init__(self, directories, spec, *, cancelled):
        if (
            type(directories) is not TaskLpacDirectories
            or type(spec) is not BasisCopySpec
            or not callable(cancelled)
        ):
            raise TaskBasisTransferError('ORIGINAL_BASIS_DIRECTORY_AND_SPEC_REQUIRED')
        self._dirs, self.spec, self._cancelled = directories, spec, cancelled
        self._role = directories._directories.get('basis')
        if self._role is None:
            raise TaskBasisTransferError('ORIGINAL_BASIS_DIRECTORY_REQUIRED')
        self._path = self._role.path / spec.filename
        self._kernel = file_io()
        self._dup, self._security, _ = duplicate_api()
        self._original = None
        self._writer = self._process = self._reader = None
        self._may_issue = False
        self._descriptor = None
        self._closed = False

    @property
    def _native_path(self):
        return '\\\\?\\' + str(self._path)

    def _checkpoint(self):
        if self._closed:
            raise TaskBasisTransferError('ORIGINAL_BASIS_SLOT_CLOSED')
        self._dirs._require_open(self._cancelled)
        self._role.verify()

    def _verify_file_policy(self):
        if self._descriptor is not None:
            raise TaskBasisTransferError('ORIGINAL_BASIS_SECURITY_FREE_UNVERIFIED')
        owner, dacl, sacl, descriptor = (wintypes.LPVOID() for _ in range(4))
        security = self._role._security
        code = security.GetNamedSecurityInfoW(
            self._native_path,
            1,
            0x15,
            ctypes.byref(owner),
            None,
            ctypes.byref(dacl),
            ctypes.byref(sacl),
            ctypes.byref(descriptor),
        )
        if code or not descriptor:
            raise TaskBasisTransferError('ORIGINAL_BASIS_COPY_SECURITY_UNAVAILABLE', code)
        self._descriptor = descriptor
        try:
            operator = self._dirs._operator
            # Inherited file ACEs may have the inherited marker, with the same access.
            expected = {operator: OPERATOR_ACCESS}
            for reader in {self._dirs._user, self._dirs.package_sid, OWNER_RIGHTS} - {operator}:
                expected[reader] = _FILE_READ
            aces = _read_aces(self._kernel, security, dacl)
            labels = _read_aces(self._kernel, security, sacl)
            if (
                _sid_text(self._kernel, security, owner) != operator
                or len(aces) != len(expected)
                or any(kind != 0 or flags not in (0, 16) for kind, flags, _, _ in aces)
                or {sid: mask for _, _, mask, sid in aces} != expected
                or len(labels) != 1
                or labels[0][1] not in (0, 16)
                or (labels[0][0], *labels[0][2:]) != (_LABEL_TYPE, 1, _MEDIUM)
            ):
                raise TaskBasisTransferError('ORIGINAL_BASIS_COPY_SECURITY_DIFFERS')
        finally:
            self._free_descriptor()

    def _free_descriptor(self):
        if self._descriptor and self._kernel.LocalFree(self._descriptor):
            raise _failure('ORIGINAL_BASIS_SECURITY_FREE_UNVERIFIED')
        self._descriptor = None

    def _close_handle(self, name, kernel):
        handle = getattr(self, name)
        if handle:
            if not kernel.CloseHandle(handle):
                raise _failure('ORIGINAL_BASIS_HANDLE_CLOSE_UNVERIFIED')
            setattr(self, name, None)

    def _offer_once(self):
        self._checkpoint()
        self._writer = self._kernel.CreateFileW(
            self._native_path, _WRITE_ACCESS, 1, None, 1, 0x00300000, None
        )
        if not self._writer or self._writer == ctypes.c_void_p(-1).value:
            self._writer = None
            raise _failure('ORIGINAL_BASIS_COPY_CREATE_REQUIRED')
        self._original = _identity(self._kernel, self._writer, self._path)
        if self._original.is_directory or _length(self._kernel, self._writer) != 0:
            raise TaskBasisTransferError('ORIGINAL_BASIS_COPY_NOT_NEW')
        self._verify_file_policy()
        controller = self._dirs._controller
        recipient = controller._expected
        self._process = self._dup.OpenProcess(0x40 | 0x1000 | 0x100000, False, recipient.pid)
        if (
            not self._process
            or process_identity(self._dup, self._security, self._process, recipient.pid)
            != recipient
        ):
            raise TaskBasisTransferError('ORIGINAL_BASIS_RECIPIENT_DIFFERS')
        remote = wintypes.HANDLE()
        self._checkpoint()
        self._may_issue = True
        if (
            not self._dup.DuplicateHandle(
                self._dup.GetCurrentProcess(),
                self._writer,
                self._process,
                ctypes.byref(remote),
                _WRITE_ACCESS,
                False,
                0,
            )
            or not remote
        ):
            raise _failure('ORIGINAL_BASIS_WRITER_HANDOFF_UNVERIFIED')
        self._close_handle('_process', self._dup)
        self._close_handle('_writer', self._kernel)
        self._checkpoint()
        return BasisWriteOffer(
            recipient,
            BasisCopyReceipt(self._dirs.scope, self._dirs.binding_ref, self.spec, self._original),
            _handle_text(remote.value),
        )

    def _open_read_pin(self):
        if self._reader is None:
            handle = self._kernel.CreateFileW(
                self._native_path, 0x80000000, 1, None, 3, 0x00300000, None
            )
            if not handle or handle == ctypes.c_void_p(-1).value:
                raise _failure('ORIGINAL_BASIS_WRITER_STILL_UNVERIFIED')
            self._reader = handle
        if _identity(self._kernel, self._reader, self._path) != self._original:
            raise TaskBasisTransferError('ORIGINAL_BASIS_COPY_IDENTITY_DIFFERS')
        self._verify_file_policy()

    def pin_written(self):
        with self._dirs._actions._journal._scope(self._dirs.scope):
            self._checkpoint()
            if not self._may_issue or self._writer is not None or self._original is None:
                raise TaskBasisTransferError('ORIGINAL_BASIS_WRITER_STILL_UNVERIFIED')
            self._open_read_pin()
            if _length(self._kernel, self._reader) != self.spec.byte_count:
                raise TaskBasisTransferError('ORIGINAL_BASIS_COPY_LENGTH_DIFFERS')
            self._checkpoint()

    def confirm(self, receipt):
        with self._dirs._actions._journal._scope(self._dirs.scope):
            if self._reader is None or receipt != BasisCopyReceipt(
                self._dirs.scope, self._dirs.binding_ref, self.spec, self._original
            ):
                raise TaskBasisTransferError('ORIGINAL_BASIS_COPY_RECEIPT_DIFFERS')
            self.pin_written()
            return receipt

    def close(self):
        if self._closed:
            return
        try:
            self._free_descriptor()
            self._close_handle('_process', self._dup)
            self._close_handle('_writer', self._kernel)
            if self._may_issue:
                self._open_read_pin()  # Closure is proved by sharing, never a remote handle number.
            self._close_handle('_reader', self._kernel)
            self._closed = True
        except BaseException as error:
            error.retained_owner = self
            raise


def bind_basis_offer(offer, scope, binding_ref):
    if type(offer) is not BasisWriteOffer or type(offer.expected) is not BasisCopyReceipt:
        raise TaskBasisTransferError('ORIGINAL_BASIS_WRITER_OFFER_REQUIRED')
    expected = offer.expected
    if (
        type(scope) is not LaunchScope
        or type(binding_ref) is not str
        or re.fullmatch('[0-9a-f]{32}', binding_ref) is None
        or expected.scope != scope
        or expected.binding_ref != binding_ref
        or type(expected.spec) is not BasisCopySpec
    ):
        raise TaskBasisTransferError('ORIGINAL_BASIS_WRITER_SCOPE_DIFFERS')
    with ObservedProcess(os.getpid()) as current:
        if current.identity != offer.owner:
            raise TaskBasisTransferError('ORIGINAL_BASIS_WRITER_RECIPIENT_DIFFERS')
    if type(expected.file) is not FileIdentity or expected.file.is_directory is not False:
        raise TaskBasisTransferError('ORIGINAL_BASIS_WRITER_IDENTITY_DIFFERS')
    path = local_absolute_path(expected.file.canonical_path)
    if path.name != expected.spec.filename or path.parent.name != 'basis':
        raise TaskBasisTransferError('ORIGINAL_BASIS_WRITER_IDENTITY_DIFFERS')
    return expected, path


def _verified_writer(offer, scope, binding_ref):
    expected, path = bind_basis_offer(offer, scope, binding_ref)
    handle = _handle(offer.writer)
    kernel = file_io()
    query, _, native = duplicate_api()
    info, size, flags = ObjectBasicInformation(), wintypes.ULONG(), wintypes.DWORD()
    if (
        native.NtQueryObject(handle, 0, ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(size))
        != 0
        or size.value != ctypes.sizeof(info)
        or info.granted_access != _WRITE_ACCESS
        or not query.GetHandleInformation(handle, ctypes.byref(flags))
        or flags.value & 1
        or query.GetFileType(handle) != 1
    ):
        raise TaskBasisTransferError('ORIGINAL_BASIS_WRITER_ACCESS_DIFFERS')
    if _identity(kernel, handle, path) != expected.file:
        raise TaskBasisTransferError('ORIGINAL_BASIS_WRITER_IDENTITY_DIFFERS')
    return kernel, handle


class BackendBasisWriter:
    """Own only the checked handle in the original backend process."""

    def __init__(self, offer, scope, binding_ref):
        self._kernel, self._handle = _verified_writer(offer, scope, binding_ref)
        self._spec = offer.expected.spec
        self._started = False

    def write(self, raw, checkpoint):
        if self._handle is None or self._started:
            raise TaskBasisTransferError('ORIGINAL_BASIS_WRITER_ALREADY_USED')
        self._started = True
        kernel, handle, spec = self._kernel, self._handle, self._spec
        checkpoint()
        if (
            type(raw) is not bytes
            or len(raw) != spec.byte_count
            or hashlib.sha256(raw).hexdigest() != spec.sha256
        ):
            raise TaskBasisTransferError('ORIGINAL_BASIS_COPY_SOURCE_DIFFERS')
        if _length(kernel, handle) != 0:
            raise TaskBasisTransferError('ORIGINAL_BASIS_COPY_NOT_NEW')
        offset = 0
        while offset < len(raw):
            checkpoint()
            part = raw[offset : offset + READ_CHUNK]
            data, written = ctypes.create_string_buffer(part), wintypes.DWORD()
            if not kernel.WriteFile(handle, data, len(part), ctypes.byref(written), None):
                raise _failure('ORIGINAL_BASIS_COPY_WRITE_UNVERIFIED')
            if not 1 <= written.value <= len(part):
                raise TaskBasisTransferError('ORIGINAL_BASIS_COPY_WRITE_UNVERIFIED')
            offset += written.value
        if not kernel.FlushFileBuffers(handle) or _length(kernel, handle) != len(raw):
            raise _failure('ORIGINAL_BASIS_COPY_FLUSH_UNVERIFIED')
        checkpoint()

    def close(self):
        if self._handle is not None:
            if not self._kernel.CloseHandle(self._handle):
                error = _failure('ORIGINAL_BASIS_WRITER_CLOSE_UNVERIFIED')
                error.retained_owner = self
                raise error
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        self.close()
