"""Original backend config-file handles for a fixed Guard read command."""

import ctypes
import os
import re
from ctypes import wintypes
from dataclasses import dataclass, field

from .git_repository_location import RepositoryLocationLease
from .runtime_launch_journal import LaunchScope
from .windows_config_source import ConfigReadError, LockedConfigSource, LockedFileSource
from .windows_controller_token import ControllerPrimaryToken
from .windows_local_paths import FileIdentity, local_absolute_path
from .windows_process import NativeProcessIdentity, ObservedProcess
from .windows_process import _identity as process_identity
from .windows_stdio import ObjectBasicInformation, _handle, _handle_text
from .windows_stdio import _api as duplicate_api

MAX_GUARD_CONFIG_BYTES = 1024 * 1024
FILE_GENERIC_READ = 0x00120089


@dataclass(frozen=True)
class ConfigReadDescriptor:
    owner: NativeProcessIdentity = field(repr=False)
    scope: LaunchScope
    file: FileIdentity = field(repr=False)
    sha256: str
    byte_count: int
    handle: str = field(repr=False)


def open_config_export(location, scope):
    """Give Guard a separate file position, held by the caller through handoff."""
    if type(location) is not RepositoryLocationLease or type(scope) is not LaunchScope:
        raise TypeError('Original repository location and launch scope required')
    original = location.verify()
    source = LockedConfigSource(
        original.config.canonical_path,
        max_file_bytes=location._file_limit,
        expected_file=original.config,
    )
    try:
        copied = source.verify()
        if copied.sha256 != original.config_sha256 or location.verify() != original:
            raise ConfigReadError('CONFIG_READ_SOURCE_CHANGED')
        with ObservedProcess(os.getpid()) as current:
            descriptor = ConfigReadDescriptor(
                current.identity,
                scope,
                copied.file,
                copied.sha256,
                copied.byte_count,
                _handle_text(source._handle),
            )
        return source, descriptor
    except BaseException as error:
        try:
            source.close()
        except BaseException as cleanup:
            cleanup.retained_owner = source
            raise cleanup from error
        raise


def verify_config_export_descriptor(descriptor, *, max_file_bytes):
    if (
        type(descriptor) is not ConfigReadDescriptor
        or type(descriptor.scope) is not LaunchScope
        or type(descriptor.owner) is not NativeProcessIdentity
        or type(descriptor.file) is not FileIdentity
        or descriptor.file.is_directory is not False
        or descriptor.file.filesystem != 'NTFS'
        or type(descriptor.file.canonical_path) is not str
        or type(descriptor.file.volume_serial) is not str
        or re.fullmatch('[0-9a-f]{16}', descriptor.file.volume_serial) is None
        or type(descriptor.file.file_id) is not str
        or re.fullmatch('[0-9a-f]{32}', descriptor.file.file_id) is None
        or type(descriptor.sha256) is not str
        or re.fullmatch('[0-9a-f]{64}', descriptor.sha256) is None
        or type(descriptor.byte_count) is not int
        or not 0 <= descriptor.byte_count <= max_file_bytes
    ):
        raise ConfigReadError('ORIGINAL_CONFIG_EXPORT_INVALID')
    path = local_absolute_path(descriptor.file.canonical_path)
    if path.name.casefold() != 'config' or len(str(path).encode('utf-16-le')) > 480:
        raise ConfigReadError('ORIGINAL_CONFIG_EXPORT_PATH_INVALID')
    return _handle(descriptor.handle)


def copy_original_config_source(controller, descriptor, *, scope, max_file_bytes):
    """Duplicate the actual read handle. Never open a supplied path for data."""
    handle = verify_config_export_descriptor(descriptor, max_file_bytes=max_file_bytes)
    return _copy_original_read_source(
        controller,
        descriptor,
        handle,
        scope=scope,
        max_file_bytes=max_file_bytes,
        source_type=LockedConfigSource,
    )


def _copy_original_read_source(
    controller,
    descriptor,
    handle,
    *,
    scope,
    max_file_bytes,
    source_type,
    checkpoint=None,
):
    if (
        type(controller) is not ControllerPrimaryToken
        or not isinstance(scope, LaunchScope)
        or descriptor.scope != scope
        or descriptor.owner != controller._expected
    ):
        raise ConfigReadError('ORIGINAL_CONFIG_EXPORT_REQUIRED')
    if source_type not in (LockedConfigSource, LockedFileSource):
        raise TypeError('Original file reader type required')
    source = source_type.__new__(source_type)
    source._initialize(descriptor.file.canonical_path, max_file_bytes, descriptor.file)
    source._capture_raw = source_type is LockedConfigSource
    source._checkpoint = checkpoint
    kernel, security, native = duplicate_api()
    try:
        with controller.creation_handle():
            process = kernel.OpenProcess(0x40 | 0x1000 | 0x100000, False, descriptor.owner.pid)
            if not process:
                raise ConfigReadError(
                    'ORIGINAL_CONFIG_EXPORT_PROCESS_UNAVAILABLE', ctypes.get_last_error()
                )
            source._source_process = process
            if (
                process_identity(kernel, security, process, descriptor.owner.pid)
                != descriptor.owner
            ):
                raise ConfigReadError('ORIGINAL_CONFIG_EXPORT_PROCESS_DIFFERS')
            duplicate = wintypes.HANDLE()
            if not kernel.DuplicateHandle(
                process, handle, kernel.GetCurrentProcess(), ctypes.byref(duplicate), 0, False, 2
            ):
                raise ConfigReadError(
                    'ORIGINAL_CONFIG_EXPORT_DUPLICATE_UNVERIFIED', ctypes.get_last_error()
                )
            source._handle = duplicate.value
            access = ObjectBasicInformation()
            returned = wintypes.ULONG()
            status = native.NtQueryObject(
                source._handle,
                0,
                ctypes.byref(access),
                ctypes.sizeof(access),
                ctypes.byref(returned),
            )
            if (
                status != 0
                or returned.value != ctypes.sizeof(access)
                or access.granted_access != FILE_GENERIC_READ
            ):
                raise ConfigReadError('ORIGINAL_CONFIG_EXPORT_READ_ACCESS_REQUIRED')
            if not kernel.CloseHandle(process):
                raise ConfigReadError(
                    'ORIGINAL_CONFIG_EXPORT_PROCESS_CLOSE_UNVERIFIED', ctypes.get_last_error()
                )
            source._source_process = None
            snapshot = source._read()
            if snapshot.sha256 != descriptor.sha256 or snapshot.byte_count != descriptor.byte_count:
                raise ConfigReadError('CONFIG_READ_SOURCE_CHANGED')
            source._snapshot = snapshot
    except BaseException as error:
        try:
            source.close()
        except BaseException as cleanup:
            cleanup.retained_owner = source
            raise cleanup from error
        raise
    return source
