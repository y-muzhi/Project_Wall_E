"""Immutable count-audit byte copies and disk prerequisites for DB20 planning.

Only the registered CountingJournal root is read. No arbitrary external directory
is recursively copied; missing and empty roots remain distinct observations.
"""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path

from .counting_journal import CountingJournal
from .windows_local_paths import FileIdentity, LocalPathGuard
from .schema_inspection import require_snapshot
from backend.app.shared.validation import MAX_SAFE_INTEGER


class MaintenancePreparationError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class AuditFile:
    name: str
    byte_count: int
    sha256: str
    identity: FileIdentity

    def __post_init__(self):
        if (
            type(self.name) is not str
            or not self.name
            or self.name in ('.', '..')
            or any(char in self.name for char in '/\\:')
        ):
            raise ValueError('A single original audit filename is required')
        if type(self.byte_count) is not int or not 0 <= self.byte_count <= MAX_SAFE_INTEGER:
            raise ValueError('Audit byte count exceeds the exact range')


@dataclass(frozen=True)
class AuditSnapshot:
    root_path: str
    state: str
    root_identity: FileIdentity | None
    files: tuple[AuditFile, ...]

    def __post_init__(self):
        if self.state not in ('ABSENT', 'EMPTY', 'FILES'):
            raise ValueError('Unknown audit root state')
        if (self.state == 'ABSENT') != (self.root_identity is None) or (
            self.state == 'FILES'
        ) != bool(self.files):
            raise ValueError('Audit root state and actual entries differ')
        if self.root_identity is not None and not self.root_identity.is_directory:
            raise ValueError('The actual audit directory identity is required')
        if len({file.name for file in self.files}) != len(self.files):
            raise ValueError('Original audit filenames must be distinct')

    @property
    def byte_count(self):
        return sum(file.byte_count for file in self.files)


def _root(session):
    return CountingJournal(session.database, session.process_lock).root


def _names(root):
    with os.scandir(root) as entries:
        return tuple(
            sorted((entry.name for entry in entries), key=lambda name: name.encode('utf-8'))
        )


def _hash_file(path, guard, output=None):
    digest = hashlib.sha256()
    count = 0
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            count += len(chunk)
            if count > MAX_SAFE_INTEGER:
                raise MaintenancePreparationError('AUDIT_SIZE_UNSUPPORTED')
            if output is not None:
                output.write(chunk)
        after = os.fstat(stream.fileno())
    guard.verify()
    if count != before.st_size or count != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise MaintenancePreparationError('AUDIT_SOURCE_CHANGED')
    return count, digest.hexdigest()


def capture_audit(session) -> AuditSnapshot:
    session.verify()
    root = _root(session)
    try:
        root.lstat()
    except FileNotFoundError:
        session.verify()
        return AuditSnapshot(str(root), 'ABSENT', None, ())
    files = []
    with LocalPathGuard(root, directory=True) as directory:
        names = _names(root)
        for name in names:
            # Each entry must be one real normal file, not a link or nested tree.
            path = root / name
            with LocalPathGuard(path, directory=False) as source:
                size, sha256 = _hash_file(path, source)
                files.append(AuditFile(name, size, sha256, source.identity))
        if _names(root) != names:
            raise MaintenancePreparationError('AUDIT_SOURCE_CHANGED')
        identity = directory.verify()
    session.verify()
    return AuditSnapshot(str(root), 'FILES' if files else 'EMPTY', identity, tuple(files))


def verify_audit_backup(session, expected: AuditSnapshot) -> None:
    session.verify()
    destination = session.package_path / 'count-audit-copy'
    if expected.state == 'ABSENT':
        try:
            destination.lstat()
        except FileNotFoundError:
            return
        raise MaintenancePreparationError('ABSENT_AUDIT_MUST_NOT_HAVE_FAKE_COPY')
    session.package_guard.verify_member('count-audit-copy', directory=True)
    with LocalPathGuard(destination, directory=True):
        if _names(destination) != tuple(file.name for file in expected.files):
            raise MaintenancePreparationError('AUDIT_BACKUP_ENTRIES_DIFFER')
        for file in expected.files:
            path = destination / file.name
            with LocalPathGuard(path, directory=False) as guard:
                session.package_guard.verify_member(
                    'count-audit-copy/' + file.name, directory=False
                )
                size, sha256 = _hash_file(path, guard)
                if (size, sha256) != (file.byte_count, file.sha256):
                    raise MaintenancePreparationError('AUDIT_BACKUP_BYTES_DIFFER')
    session.verify()


def copy_audit(session, expected: AuditSnapshot) -> None:
    session.verify()
    if capture_audit(session) != expected:
        raise MaintenancePreparationError('AUDIT_SOURCE_CHANGED')
    destination = session.package_path / 'count-audit-copy'
    if expected.state == 'ABSENT':
        verify_audit_backup(session, expected)
        return
    # No overwrite, merge, synthesized evidence or cleanup of older recovery assets.
    destination.mkdir()
    session.package_guard.verify_member('count-audit-copy', directory=True)
    root = _root(session)
    with LocalPathGuard(root, directory=True) as source_root:
        if source_root.identity != expected.root_identity:
            raise MaintenancePreparationError('AUDIT_SOURCE_CHANGED')
        for file in expected.files:
            with LocalPathGuard(root / file.name, directory=False) as source:
                if source.identity != file.identity:
                    raise MaintenancePreparationError('AUDIT_SOURCE_CHANGED')
                with (destination / file.name).open('xb') as output:
                    # Verify privacy before writing any original business bytes.
                    session.package_guard.verify_member(
                        'count-audit-copy/' + file.name, directory=False
                    )
                    size, sha256 = _hash_file(root / file.name, source, output)
                    output.flush()
                    os.fsync(output.fileno())
                if (size, sha256) != (file.byte_count, file.sha256):
                    raise MaintenancePreparationError('AUDIT_SOURCE_CHANGED')
        source_root.verify()
    if capture_audit(session) != expected:
        raise MaintenancePreparationError('AUDIT_SOURCE_CHANGED')
    verify_audit_backup(session, expected)


@dataclass(frozen=True)
class SpaceObservation:
    database_bytes: int
    audit_bytes: int
    source_required_bytes: int
    package_required_bytes: int
    shared_volume: bool
    source_available_bytes: int
    package_available_bytes: int


def _available_bytes(path):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetDiskFreeSpaceExW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.c_uint64),
    ]
    kernel.GetDiskFreeSpaceExW.restype = wintypes.BOOL
    available, total, free = ctypes.c_uint64(), ctypes.c_uint64(), ctypes.c_uint64()
    if not kernel.GetDiskFreeSpaceExW(
        '\\\\?\\' + str(path), ctypes.byref(available), ctypes.byref(total), ctypes.byref(free)
    ):
        raise MaintenancePreparationError('DISK_SPACE_UNVERIFIED')
    return available.value


def require_disk_space(session, connection, audit: AuditSnapshot) -> SpaceObservation:
    session.verify()
    require_snapshot(connection)
    databases = connection.execute('PRAGMA database_list').fetchall()
    main = [row for row in databases if row[1] == 'main']
    if (
        len(main) != 1
        or not main[0][2]
        or Path(main[0][2]) != session.database.path
        or any(row[1] not in ('main', 'temp') for row in databases)
    ):
        raise MaintenancePreparationError('DATABASE_CONNECTION_DIFFERS')
    if audit.root_path != str(_root(session)):
        raise MaintenancePreparationError('AUDIT_ROOT_DIFFERS')
    pages = connection.execute('PRAGMA page_count').fetchone()[0]
    page_size = connection.execute('PRAGMA page_size').fetchone()[0]
    if (
        type(pages) is not int
        or pages < 1
        or page_size not in (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536)
    ):
        raise MaintenancePreparationError('DATABASE_SIZE_UNVERIFIED')
    logical = pages * page_size
    if logical > MAX_SAFE_INTEGER or audit.byte_count > MAX_SAFE_INTEGER:
        raise MaintenancePreparationError('MAINTENANCE_SIZE_UNSUPPORTED')
    # Conservative peak allowance: original + rebuild/WAL growth, two database
    # copies/rehearsal growth, audit bytes/temporary publication and 64MiB per side.
    margin = 64 * 1024 * 1024
    ddl = len(session.release.upgrade.encode('utf-8')) * 8
    source_required = logical * 2 + ddl + margin
    package_required = logical * 4 + audit.byte_count * 2 + ddl + margin
    shared = (
        session.source_guard.identity.volume_serial == session.package_guard.verify().volume_serial
    )
    source_available = _available_bytes(session.database.path.parent)
    package_available = _available_bytes(session.package_path)
    required = source_required + package_required
    if source_available < (required if shared else source_required) or package_available < (
        required if shared else package_required
    ):
        raise MaintenancePreparationError('DISK_SPACE_INSUFFICIENT')
    session.verify()
    return SpaceObservation(
        logical,
        audit.byte_count,
        source_required,
        package_required,
        shared,
        source_available,
        package_available,
    )
