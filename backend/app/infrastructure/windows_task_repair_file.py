"""Publish one missing candidate file by its original NTFS staging handle."""

import ctypes
import os
from ctypes import wintypes
from uuid import uuid4

from .content_paths import materialized_path
from .windows_config_copy import _api, _Disposition
from .windows_executable_pin import READ_CHUNK
from .windows_local_paths import LocalPathGuard, PathBoundaryError, _identity, local_absolute_path
from .windows_private_record import PrivateRecordError, rename_private_handle_no_replace
from .windows_task_workspace_tree import CandidateWorkspaceError, _verify_streams


def _native_failure(reason):
    return PathBoundaryError(reason, ctypes.get_last_error())


def _absent(target):
    # Match the workspace's case-folding rules even in a case-sensitive NTFS
    # directory. The actual native publication separately forbids replacement.
    with os.scandir(target.parent) as children:
        if any(child.name.casefold() == target.name.casefold() for child in children):
            raise CandidateWorkspaceError('SOURCE_CHANGED')


def _write_stage(kernel, handle, raw, checkpoint):
    offset = 0
    while offset < len(raw):
        checkpoint()
        part = raw[offset : offset + READ_CHUNK]
        buffer = ctypes.create_string_buffer(part)
        written = wintypes.DWORD()
        if not kernel.WriteFile(handle, buffer, len(part), ctypes.byref(written), None):
            raise _native_failure('REPAIR_STAGE_WRITE_UNVERIFIED')
        if not 1 <= written.value <= len(part):
            raise PathBoundaryError('REPAIR_STAGE_WRITE_SIZE_INVALID')
        offset += written.value
    if not kernel.FlushFileBuffers(handle):
        raise _native_failure('REPAIR_STAGE_FLUSH_UNVERIFIED')
    _verify_streams(kernel, handle, directory=False)


def create_missing_candidate_directory(workspace, parent, relative, checkpoint, publish):
    root = local_absolute_path(workspace.canonical_path)
    target = local_absolute_path(materialized_path(root, relative))
    with (
        LocalPathGuard(root, directory=True) as workspace_pin,
        LocalPathGuard(target.parent, directory=True) as parent_pin,
    ):
        if workspace_pin.verify() != workspace or parent_pin.verify() != parent:
            raise CandidateWorkspaceError('SOURCE_CHANGED')
        _absent(target)
        checkpoint()
        created = False

        def mkdir():
            nonlocal created
            try:
                target.mkdir()
            except FileExistsError as error:
                raise CandidateWorkspaceError('SOURCE_CHANGED') from error
            created = True

        publish(mkdir)
        if not created:
            raise PathBoundaryError('REPAIR_DIRECTORY_CREATION_NOT_ATTEMPTED')
        with LocalPathGuard(target, directory=True) as directory:
            _verify_streams(directory._kernel, directory._held[-1][0], directory=True)
            return directory.verify()


def publish_missing_candidate_file(workspace, scratch, parent, relative, raw, checkpoint, publish):
    root = local_absolute_path(workspace.canonical_path)
    target = local_absolute_path(materialized_path(root, relative))
    scratch_path = local_absolute_path(scratch.canonical_path)
    if (
        scratch_path != root.with_name('scratch')
        or scratch.volume_serial != workspace.volume_serial
        or scratch.file_id == workspace.file_id
    ):
        raise CandidateWorkspaceError('SOURCE_CHANGED')
    kernel = _api()
    with (
        LocalPathGuard(root, directory=True) as workspace_pin,
        LocalPathGuard(scratch_path, directory=True) as scratch_pin,
        LocalPathGuard(target.parent, directory=True) as parent_pin,
    ):
        if (
            workspace_pin.verify() != workspace
            or scratch_pin.verify() != scratch
            or parent_pin.verify() != parent
        ):
            raise CandidateWorkspaceError('SOURCE_CHANGED')
        _absent(target)
        checkpoint()
        stage = scratch_path / ('.walle-repair-' + uuid4().hex + '.tmp')
        handle = kernel.CreateFileW(
            '\\\\?\\' + str(stage),
            0x80000000 | 0x40000000 | 0x10000 | 0x80,
            0x1,
            None,
            1,  # CREATE_NEW
            0x00200000 | 0x00100000,
            None,
        )
        if not handle or handle == ctypes.c_void_p(-1).value:
            raise _native_failure('REPAIR_STAGE_CREATE_UNVERIFIED')
        rename_attempted = False
        renamed = False

        def rename():
            nonlocal rename_attempted, renamed
            rename_attempted = True
            try:
                rename_private_handle_no_replace(kernel, handle, target)
            except PrivateRecordError as error:
                if error.native_error in (80, 183):
                    raise CandidateWorkspaceError('SOURCE_CHANGED') from error
                raise
            renamed = True

        try:
            original = _identity(kernel, handle, stage)
            _write_stage(kernel, handle, raw, checkpoint)
            if _identity(kernel, handle, stage) != original:
                raise CandidateWorkspaceError('SOURCE_CHANGED')
            _absent(target)
            checkpoint()
            publish(rename)
            if not renamed:
                raise PathBoundaryError('REPAIR_PUBLICATION_NOT_ATTEMPTED')
            actual = _identity(kernel, handle, target)
            if (actual.volume_serial, actual.file_id) != (original.volume_serial, original.file_id):
                raise CandidateWorkspaceError('SOURCE_CHANGED')
            _verify_streams(kernel, handle, directory=False)
            if not kernel.FlushFileBuffers(handle):
                raise _native_failure('REPAIR_PUBLICATION_FLUSH_UNVERIFIED')
        finally:
            try:
                if not renamed:
                    # An uncertain rename can only be cleaned if the original
                    # handle still proves that it belongs to scratch.
                    if rename_attempted:
                        try:
                            _identity(kernel, handle, stage)
                        except PathBoundaryError:
                            raise PathBoundaryError('REPAIR_STAGE_LOCATION_UNVERIFIED') from None
                    disposition = _Disposition(1)
                    if not kernel.SetFileInformationByHandle(
                        handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)
                    ):
                        raise _native_failure('REPAIR_STAGE_DELETE_UNVERIFIED')
            finally:
                if not kernel.CloseHandle(handle):
                    raise _native_failure('REPAIR_STAGE_CLOSE_UNVERIFIED')
