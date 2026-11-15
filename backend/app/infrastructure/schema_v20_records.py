"""Bounded immutable metadata publication inside a verified maintenance package."""

import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile

from .schema_v20_release import canonical_bytes
from .windows_local_paths import LocalPathGuard, local_absolute_path
from .schema_v20_assets import MaintenancePreparationError
from backend.app.shared.validation import strict_json_object

MAX_RECORD_BYTES = 64 * 1024 * 1024


def _record_path(session, name):
    if type(name) is not str or not name or '\\' in name or ':' in name:
        raise MaintenancePreparationError('MAINTENANCE_RECORD_NAME_INVALID')
    parts = name.split('/')
    if (
        PurePosixPath(name).is_absolute()
        or len(parts) > 2
        or any(part in ('', '.', '..') for part in parts)
    ):
        raise MaintenancePreparationError('MAINTENANCE_RECORD_NAME_INVALID')
    if len(parts) == 2:
        if parts[0] != 'receipts':
            raise MaintenancePreparationError('MAINTENANCE_RECORD_NAME_INVALID')
        session.package_guard.verify_member('receipts', directory=True)
    return local_absolute_path(session.package_path.joinpath(*parts))


def _publish_new(temporary, target):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.MoveFileExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    kernel.MoveFileExW.restype = wintypes.BOOL
    # Same-directory rename, WRITE_THROUGH, without REPLACE_EXISTING/COPY_ALLOWED.
    if not kernel.MoveFileExW('\\\\?\\' + str(temporary), '\\\\?\\' + str(target), 0x8):
        raise MaintenancePreparationError('NEW_MAINTENANCE_RECORD_REQUIRED')


def write_record(session, name, value):
    """Publish a new name atomically; an existing plan/receipt is never replaced."""
    session.verify()
    target = _record_path(session, name)
    try:
        target.lstat()
    except FileNotFoundError:
        pass
    else:
        raise MaintenancePreparationError('NEW_MAINTENANCE_RECORD_REQUIRED')
    encoded = canonical_bytes(value)
    if len(encoded) > MAX_RECORD_BYTES:
        raise MaintenancePreparationError('MAINTENANCE_RECORD_TOO_LARGE')
    # Validate the precise type/range/Unicode JSON representation before IO.
    strict_json_object(encoded)
    temporary = None
    try:
        with NamedTemporaryFile(
            dir=target.parent, prefix='.maintenance-', suffix='.tmp', delete=False
        ) as stream:
            temporary = Path(stream.name)
            relative = temporary.relative_to(session.package_path).as_posix()
            session.package_guard.verify_member(relative, directory=False)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        session.verify()
        _publish_new(temporary, target)
        digest = hashlib.sha256(encoded).hexdigest()
        read_record(session, name, expected_sha256=digest)
        return digest
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def read_record(session, name, *, expected_sha256=None):
    session.verify()
    path = _record_path(session, name)
    session.package_guard.verify_member(name, directory=False)
    with LocalPathGuard(path, directory=False) as guard:
        with path.open('rb') as stream:
            encoded = stream.read(MAX_RECORD_BYTES + 1)
        guard.verify()
    if len(encoded) > MAX_RECORD_BYTES:
        raise MaintenancePreparationError('MAINTENANCE_RECORD_TOO_LARGE')
    digest = hashlib.sha256(encoded).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise MaintenancePreparationError('MAINTENANCE_RECORD_DIGEST_DIFFERS')
    result = strict_json_object(encoded)
    if canonical_bytes(result) != encoded:
        raise MaintenancePreparationError('MAINTENANCE_RECORD_NOT_CANONICAL')
    session.verify()
    return result, digest
