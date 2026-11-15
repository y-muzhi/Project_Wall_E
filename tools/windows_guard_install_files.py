"""Create-only protected installer resources; never repair existing ACLs or remove trees."""

import ctypes
import hashlib
from ctypes import wintypes

from backend.app.infrastructure.program_package import ProgramPackageLease
from backend.app.infrastructure.windows_access_check import (
    ControllerAccessQuery,
    require_controller_read_only,
)
from backend.app.infrastructure.windows_config_source import LockedFileSource
from backend.app.infrastructure.windows_local_paths import LocalPathGuard, local_absolute_path
from backend.app.infrastructure.windows_private_package import (
    AclHeader,
    AllowedAce,
    SecurityAttributes,
    _api,
    _sid_text,
)
from tools.windows_guard_install_contract import (
    ADMINISTRATORS,
    FULL_FILE_ACCESS,
    SYSTEM,
    GuardInstallationError,
    permission_sddl,
    program_rights,
)
from tools.windows_guard_install_identity import InstallationOperator, RestorePrivilege


class NativeDescriptor:
    def __init__(self, owner, rights, *, directory):
        self.owner, self.rights, self.directory = owner, dict(rights), directory
        self._kernel, self._security = _api()
        self._descriptor = wintypes.LPVOID()
        self._failed = False
        self._reads = []
        if not self._security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            permission_sddl(owner, rights, directory=directory),
            1,
            ctypes.byref(self._descriptor),
            None,
        ):
            raise GuardInstallationError('INSTALLATION_SECURITY_DESCRIPTOR_UNAVAILABLE')
        security = self._security
        security.GetSecurityInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.DWORD,
            *[ctypes.POINTER(wintypes.LPVOID)] * 5,
        ]
        security.GetSecurityInfo.restype = wintypes.DWORD
        security.GetSecurityDescriptorControl.argtypes = [
            wintypes.LPVOID,
            ctypes.POINTER(wintypes.WORD),
            ctypes.POINTER(wintypes.DWORD),
        ]
        security.GetSecurityDescriptorControl.restype = wintypes.BOOL
        security.IsValidSecurityDescriptor.argtypes = [wintypes.LPVOID]
        security.IsValidSecurityDescriptor.restype = wintypes.BOOL
        security.GetSecurityDescriptorDacl.argtypes = [
            wintypes.LPVOID,
            ctypes.POINTER(wintypes.BOOL),
            ctypes.POINTER(wintypes.LPVOID),
            ctypes.POINTER(wintypes.BOOL),
        ]
        security.GetSecurityDescriptorDacl.restype = wintypes.BOOL
        security.SetSecurityInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.DWORD,
            *[wintypes.LPVOID] * 4,
        ]
        security.SetSecurityInfo.restype = wintypes.DWORD

    def attributes(self):
        if not self._descriptor.value or self._failed or self._reads:
            raise GuardInstallationError('INSTALLATION_DESCRIPTOR_OWNER_CLOSED')
        return SecurityAttributes(ctypes.sizeof(SecurityAttributes), self._descriptor, False)

    def verify_handle(self, handle, *, object_type=1):
        if self._failed or self._reads:
            raise GuardInstallationError('INSTALLATION_DESCRIPTOR_OWNER_UNVERIFIED')
        owner, group, dacl, descriptor = (wintypes.LPVOID() for _ in range(4))
        code = self._security.GetSecurityInfo(
            handle,
            object_type,
            7,
            ctypes.byref(owner),
            ctypes.byref(group),
            ctypes.byref(dacl),
            None,
            ctypes.byref(descriptor),
        )
        if code or not descriptor.value:
            raise GuardInstallationError('INSTALLATION_ORIGINAL_SECURITY_UNAVAILABLE')
        self._reads.append(descriptor.value)
        try:
            if (
                not self._security.IsValidSecurityDescriptor(descriptor)
                or _sid_text(self._kernel, self._security, owner) != self.owner
                or _sid_text(self._kernel, self._security, group) != ADMINISTRATORS
                or not dacl.value
            ):
                raise GuardInstallationError('INSTALLATION_OWNER_GROUP_OR_DACL_DIFFERS')
            control, revision = wintypes.WORD(), wintypes.DWORD()
            if (
                not self._security.GetSecurityDescriptorControl(
                    descriptor, ctypes.byref(control), ctypes.byref(revision)
                )
                or not control.value & 0x1000
            ):
                raise GuardInstallationError('INSTALLATION_PROTECTED_DACL_REQUIRED')
            header = ctypes.cast(dacl, ctypes.POINTER(AclHeader)).contents
            if header.count != len(self.rights):
                raise GuardInstallationError('INSTALLATION_EXACT_ACL_REQUIRED')
            observed = {}
            for index in range(header.count):
                pointer = wintypes.LPVOID()
                if not self._security.GetAce(dacl, index, ctypes.byref(pointer)):
                    raise GuardInstallationError('INSTALLATION_ACE_UNAVAILABLE')
                ace = ctypes.cast(pointer, ctypes.POINTER(AllowedAce)).contents
                if ace.kind != 0 or ace.flags != (3 if self.directory else 0):
                    raise GuardInstallationError('INSTALLATION_EXACT_ALLOW_ACE_REQUIRED')
                sid = _sid_text(
                    self._kernel,
                    self._security,
                    wintypes.LPVOID(pointer.value + ctypes.sizeof(AllowedAce)),
                )
                if sid in observed:
                    raise GuardInstallationError('INSTALLATION_DUPLICATE_ACE')
                observed[sid] = ace.mask
            if observed != self.rights:
                raise GuardInstallationError('INSTALLATION_ACCESS_RIGHTS_DIFFER')
        finally:
            if self._kernel.LocalFree(descriptor):
                error = GuardInstallationError('INSTALLATION_SECURITY_READ_CLOSE_UNVERIFIED')
                error.retained_owner = self
                raise error
            self._reads.remove(descriptor.value)

    def apply(self, handle, *, object_type=1):
        present, defaulted = wintypes.BOOL(), wintypes.BOOL()
        dacl = wintypes.LPVOID()
        if (
            not self._security.GetSecurityDescriptorDacl(
                self._descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)
            )
            or not present.value
            or not dacl.value
        ):
            raise GuardInstallationError('INSTALLATION_FIXED_DACL_UNAVAILABLE')
        code = self._security.SetSecurityInfo(
            handle, object_type, 0x80000004, None, None, dacl, None
        )
        if code:
            raise GuardInstallationError('INSTALLATION_NEW_OBJECT_DACL_SEAL_FAILED')
        self.verify_handle(handle, object_type=object_type)

    def close(self):
        if self._failed:
            error = GuardInstallationError('INSTALLATION_DESCRIPTOR_CLOSE_PREVIOUSLY_UNVERIFIED')
            error.retained_owner = self
            raise error
        if self._descriptor.value:
            if self._kernel.LocalFree(self._descriptor):
                self._failed = True
                error = GuardInstallationError('INSTALLATION_DESCRIPTOR_CLOSE_UNVERIFIED')
                error.retained_owner = self
                raise error
            self._descriptor = wintypes.LPVOID()
        if self._reads:
            self._failed = True
            error = GuardInstallationError('INSTALLATION_SECURITY_READ_CLOSE_UNVERIFIED')
            error.retained_owner = self
            raise error


class ProtectedInstallationWriter:
    def __init__(self, request, operator, checkpoint):
        if type(operator) is not InstallationOperator or not callable(checkpoint):
            raise GuardInstallationError('ACTUAL_INSTALLATION_OPERATOR_REQUIRED')
        self.operator = operator.verify()
        self.root = local_absolute_path(request['installation_root'])
        self._checkpoint = checkpoint
        self._kernel, self._security = _api()
        self._kernel.WriteFile.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        self._kernel.WriteFile.restype = wintypes.BOOL
        self._kernel.FlushFileBuffers.argtypes = [wintypes.HANDLE]
        self._kernel.FlushFileBuffers.restype = wintypes.BOOL
        self._owners = []
        self._guards = {}
        self._retained = []
        self._closed = False
        self._failed = False
        self._close_failed = False
        try:
            self._program_directory = self._descriptor(
                ADMINISTRATORS, program_rights(request['backend_sid']), directory=True
            )
            self._program_file = self._descriptor(
                ADMINISTRATORS, program_rights(request['backend_sid']), directory=False
            )
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    def _descriptor(self, owner, rights, *, directory):
        result = NativeDescriptor(owner, rights, directory=directory)
        self._owners.append(result)
        return result

    def create_directory(self, path, descriptor=None):
        self.operator.verify()
        self._checkpoint()
        path = local_absolute_path(path)
        if path != self.root and not path.is_relative_to(self.root):
            raise GuardInstallationError('NEW_INSTALLATION_PATH_REQUIRED')
        descriptor = descriptor or self._program_directory
        attributes = descriptor.attributes()
        if not self._kernel.CreateDirectoryW('\\\\?\\' + str(path), ctypes.byref(attributes)):
            raise GuardInstallationError('CREATE_ONLY_INSTALLATION_DIRECTORY_FAILED')
        guard = LocalPathGuard(path, directory=True)
        self._owners.append(guard)
        try:
            guard.__enter__()
        except BaseException as error:
            if getattr(error, 'retained_owner', None) is guard:
                self._owners.remove(guard)
                self._retained.append(guard)
            raise
        self._guards[path] = guard
        handle = self._open(path, 0x60080, directory=True)
        try:
            descriptor.verify_handle(handle)
        finally:
            self._close_handle(handle)
        return guard.verify()

    def _open(self, path, access, *, directory=False, descriptor=None):
        attributes = descriptor.attributes() if descriptor is not None else None
        handle = self._kernel.CreateFileW(
            '\\\\?\\' + str(path),
            access,
            0x3 if descriptor is None else 0,
            ctypes.byref(attributes) if attributes is not None else None,
            1 if descriptor is not None else 3,
            0x00200000 | (0x02000000 if directory else 0x80000000),
            None,
        )
        if not handle or handle == ctypes.c_void_p(-1).value:
            raise GuardInstallationError('INSTALLATION_ORIGINAL_FILE_HANDLE_UNAVAILABLE')
        return handle

    def _close_handle(self, handle):
        if not self._kernel.CloseHandle(handle):
            self._retained.append(handle)
            self._failed = True
            error = GuardInstallationError('INSTALLATION_FILE_CLOSE_UNVERIFIED')
            error.retained_owner = self
            raise error

    def write_file(self, path, source):
        self.operator.verify()
        self._checkpoint()
        path = local_absolute_path(path)
        if not path.is_relative_to(self.root) or path.parent not in self._guards:
            raise GuardInstallationError('NEW_INSTALLATION_FILE_PARENT_REQUIRED')
        handle = self._open(path, 0xC0020080, descriptor=self._program_file)
        expected = source.snapshot

        def write_chunk(raw):
            self._checkpoint()
            data = ctypes.create_string_buffer(raw)
            written = wintypes.DWORD()
            if not self._kernel.WriteFile(
                handle, data, len(raw), ctypes.byref(written), None
            ) or written.value != len(raw):
                raise GuardInstallationError('INSTALLATION_NEW_FILE_WRITE_INCOMPLETE')

        try:
            source.consume_verified(write_chunk)
            if not self._kernel.FlushFileBuffers(handle):
                raise GuardInstallationError('INSTALLATION_NEW_FILE_FLUSH_UNVERIFIED')
            self._program_file.verify_handle(handle)
        finally:
            self._close_handle(handle)
        with LockedFileSource(path, max_file_bytes=max(1, expected.byte_count)) as copied:
            if (copied.snapshot.byte_count, copied.snapshot.sha256) != (
                expected.byte_count,
                expected.sha256,
            ):
                raise GuardInstallationError('INSTALLATION_COPIED_BYTES_DIFFER')
            return copied.snapshot.file

    def write_bytes(self, path, raw):
        class MemorySource:
            def __init__(self):
                from types import SimpleNamespace

                self.snapshot = SimpleNamespace(
                    byte_count=len(raw), sha256=hashlib.sha256(raw).hexdigest()
                )

            def consume_verified(self, consume):
                consume(raw)

        return self.write_file(path, MemorySource())

    def copy_program(self, name, original, policy):
        if name not in ('guard', 'backend'):
            raise GuardInstallationError('FIXED_INSTALLATION_PROGRAM_ROLE_REQUIRED')
        destination = self.root / name
        self.create_directory(destination)
        for relative in sorted(
            original.spec.directories, key=lambda value: (value.count('/'), value)
        ):
            self.create_directory(destination / relative)
        for member in original.spec.files:
            self.write_file(destination / member.path, original._sources[member.path])
        self.write_file(destination / policy.manifest_name, original._sources[policy.manifest_name])
        with ProgramPackageLease(
            destination, expected_sha256=original.spec.manifest_sha256, policy=policy
        ) as copied:
            copied.verify()

    def create_system_journal(self):
        initial = self._descriptor(
            SYSTEM, {SYSTEM: FULL_FILE_ACCESS, ADMINISTRATORS: FULL_FILE_ACCESS}, directory=True
        )
        final = self._descriptor(SYSTEM, {SYSTEM: FULL_FILE_ACCESS}, directory=True)
        target = self.root / 'journal'
        with RestorePrivilege(self.operator):
            self.create_directory(target, initial)
            handle = self._open(target, 0x60080, directory=True)
            try:
                final.apply(handle)
            finally:
                self._close_handle(handle)
        return self._guards[target].verify()

    def verify_program_access(self, token, originals, *, include_receipt=False):
        with ControllerAccessQuery(token) as access:
            for path in (*reversed(self.root.parents), self.root):
                role = 'PACKAGE_DIRECTORY' if path == self.root else 'ANCESTOR'
                with LocalPathGuard(path, directory=True) as guard:
                    require_controller_read_only(access.query(guard), role=role)
                    if path == self.root:
                        handle = self._open(path, 0x20080, directory=True)
                        try:
                            self._program_directory.verify_handle(handle)
                        finally:
                            self._close_handle(handle)
            names = ['guard-deployment.json', 'installation-intent.v1.json']
            if include_receipt:
                names.append('installation-receipt.v1.json')
            for name in names:
                path = self.root / name
                with LocalPathGuard(path, directory=False) as guard:
                    handle = self._open(path, 0x20080)
                    try:
                        self._program_file.verify_handle(handle)
                    finally:
                        self._close_handle(handle)
                    fact = require_controller_read_only(access.query(guard), role='FILE')
                    if not fact.granted_access & 1:
                        raise GuardInstallationError('INSTALLATION_INPUT_READER_ACCESS_MISSING')
            for name, original in originals.items():
                paths = [(self.root / name, 'PACKAGE_DIRECTORY')]
                paths.extend(
                    (self.root / name / value, 'PACKAGE_DIRECTORY')
                    for value in original.spec.directories
                )
                paths.extend((self.root / name / value, 'FILE') for value in original._sources)
                for path, role in paths:
                    self._checkpoint()
                    with LocalPathGuard(path, directory=role != 'FILE') as guard:
                        descriptor = (
                            self._program_file if role == 'FILE' else self._program_directory
                        )
                        handle = self._open(path, 0x20080, directory=role != 'FILE')
                        try:
                            descriptor.verify_handle(handle)
                        finally:
                            self._close_handle(handle)
                        fact = require_controller_read_only(access.query(guard), role=role)
                        minimum = 1
                        if role != 'FILE' or path.suffix.casefold() in ('.exe', '.dll', '.pyd'):
                            minimum |= 0x20
                        if fact.granted_access & minimum != minimum:
                            raise GuardInstallationError('INSTALLED_PROGRAM_READER_ACCESS_MISSING')

    def close(self):
        if self._close_failed:
            error = GuardInstallationError('INSTALLATION_WRITER_CLOSURE_UNVERIFIED')
            error.retained_owner = self
            raise error
        if self._closed:
            return
        failures = []
        for owner in reversed(self._owners):
            try:
                owner.close()
            except BaseException as error:  # noqa: BLE001 -- Retain unknown original owners.
                failures.append(error)
        if failures or self._retained:
            self._close_failed = True
            error = GuardInstallationError('INSTALLATION_WRITER_CLOSURE_UNVERIFIED')
            error.retained_owner = self
            raise error from (failures[0] if failures else None)
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        self.close()
