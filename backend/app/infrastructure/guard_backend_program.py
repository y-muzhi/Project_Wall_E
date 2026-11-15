"""Read-only admission of Guard's fixed protected backend executable package.

The root and expected manifest digest are trusted installation configuration,
never packet input. A plain Python interpreter pin is not a backend program.
No ACL, installation, process or service is created/changed by this verifier.
"""

import hashlib
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import get_ident
from time import monotonic

from .content_paths import materialized_path, relative_content_path
from .program_manifest import (
    BACKEND_PROGRAM_POLICY,
    MAX_MANIFEST_BYTES,
    MAX_MEMBERS,
    decode_program_manifest,
)
from .runtime_launch_journal import _bytes, _hex
from .windows_access_check import ControllerAccessQuery, require_controller_read_only
from .windows_config_source import LockedConfigSource
from .windows_controller_token import ControllerPrimaryToken
from .windows_executable_pin import ExecutablePin
from .windows_local_paths import LocalPathGuard, local_absolute_path
from .windows_pipe_peer import NamedPipePeerLease

POLICY_VERSION = BACKEND_PROGRAM_POLICY.version
MANIFEST_NAME = BACKEND_PROGRAM_POLICY.manifest_name


class BackendProgramError(RuntimeError):
    pass


def decode_backend_program_manifest(raw, *, expected_sha256):
    return decode_program_manifest(
        raw,
        expected_sha256=expected_sha256,
        policy=BACKEND_PROGRAM_POLICY,
        error_type=BackendProgramError,
    )


def open_registered_backend_image(root, *, manifest_sha256):
    """Pin the fixed installed entry before reading any backend frame."""
    _hex(manifest_sha256)
    package = local_absolute_path(root)
    with LockedConfigSource(package / MANIFEST_NAME, max_file_bytes=MAX_MANIFEST_BYTES) as manifest:
        spec = decode_backend_program_manifest(
            manifest.verify().raw, expected_sha256=manifest_sha256
        )
    entry = next(item for item in spec.files if item.path == spec.entry)
    return ExecutablePin(
        materialized_path(package, entry.path),
        expected_byte_count=entry.byte_count,
        expected_sha256=entry.sha256,
    )


@dataclass(frozen=True)
class BackendProgramAdmission:
    policy_version: str
    program_ref: str
    manifest_sha256: str
    evidence_sha256: str


class ProtectedBackendProgram:
    """One original CLIENT, primary-token copy, package and descriptor snapshot."""

    def __init__(self, peer, root, *, expected_manifest_sha256, timeout_ms, cancelled):
        if type(peer) is not NamedPipePeerLease or peer._peer_kind != 'CLIENT':
            raise BackendProgramError('ACTUAL_ORIGINAL_BACKEND_PEER_REQUIRED')
        _hex(expected_manifest_sha256)
        self._owner_thread = get_ident()
        self._peer = peer
        self._root = local_absolute_path(root)
        self._expected_manifest_sha256 = expected_manifest_sha256
        self._peer_lease = None
        self._token = None
        self._access = None
        self._guards = {}
        self._roles = {}
        self._sources = {}
        self._orphans = []
        self._facts = {}
        self._closing = False
        self._users = 0
        self._spec = None
        self._admission = None
        deadline = self._deadline(timeout_ms, cancelled)
        try:
            self._peer_lease = peer.original_process()
            process = self._peer_lease.__enter__()
            self._token = self._create(ControllerPrimaryToken, process, expected=process.identity)
            self._access = self._create(ControllerAccessQuery, self._token)
            for path in reversed(self._root.parents):
                self._hold_path(path, 'ANCESTOR', deadline, cancelled)
            self._hold_path(self._root, 'PACKAGE_DIRECTORY', deadline, cancelled)
            manifest_path = self._root / MANIFEST_NAME
            manifest = self._hold_file(manifest_path, MAX_MANIFEST_BYTES, deadline, cancelled)
            self._spec = decode_backend_program_manifest(
                manifest.raw, expected_sha256=expected_manifest_sha256
            )
            for item in self._spec.files:
                materialized_path(self._root, item.path)
            expected = {MANIFEST_NAME, *(item.path for item in self._spec.files)}
            actual = self._inventory(deadline, cancelled)
            if actual != expected:
                raise BackendProgramError('BACKEND_PROGRAM_PACKAGE_MEMBERS_DIFFER')
            for item in self._spec.files:
                snapshot = self._hold_file(
                    Path(materialized_path(self._root, item.path)),
                    max(1, item.byte_count),
                    deadline,
                    cancelled,
                )
                if snapshot.byte_count != item.byte_count or snapshot.sha256 != item.sha256:
                    raise BackendProgramError('BACKEND_PROGRAM_MEMBER_BYTES_DIFFER')
            image = peer._program.verify()
            entry = self._sources[self._root / self._spec.entry].snapshot
            if (
                entry.file != image.file
                or entry.sha256 != image.sha256
                or entry.byte_count != image.byte_count
            ):
                raise BackendProgramError('BACKEND_PEER_NOT_REGISTERED_PACKAGE_ENTRY')
            self._admission = self._verify_until(deadline, cancelled)
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    def _check_thread(self):
        if get_ident() != self._owner_thread:
            raise BackendProgramError('ORIGINAL_BACKEND_PROGRAM_OWNER_THREAD_DIFFERS')

    def _deadline(self, timeout_ms, cancelled):
        if type(timeout_ms) is not int or not 1 <= timeout_ms <= 300000 or not callable(cancelled):
            raise BackendProgramError('BACKEND_PROGRAM_QUERY_BOUNDARY_REQUIRED')
        deadline = monotonic() + timeout_ms / 1000
        self._check_deadline(deadline, cancelled)
        return deadline

    def _check_deadline(self, deadline, cancelled):
        if cancelled() or monotonic() >= deadline:
            raise BackendProgramError('BACKEND_PROGRAM_QUERY_CANCELLED_OR_EXPIRED')

    def _create(self, kind, *args, **kwargs):
        try:
            return kind(*args, **kwargs)
        except BaseException as error:
            retained = getattr(error, 'retained_owner', None)
            if retained is not None:
                self._orphans.append(retained)
                error.retained_owner = self
            raise

    def _hold_path(self, path, role, deadline, cancelled):
        self._check_deadline(deadline, cancelled)
        guard = self._guards.get(path)
        if guard is None:
            guard = LocalPathGuard(path, directory=role != 'FILE')
            self._guards[path] = guard
            self._roles[path] = role
            guard.__enter__()
        facts = require_controller_read_only(self._access.query(guard), role=role)
        minimum = 0x20 if role == 'ANCESTOR' else 0x1 | 0x20
        if role == 'FILE':
            minimum = 0x1 | (0x20 if path.suffix.casefold() in ('.exe', '.dll', '.pyd') else 0)
        if facts.granted_access & minimum != minimum:
            raise BackendProgramError('BACKEND_PROGRAM_READ_OR_EXECUTE_ACCESS_MISSING')
        previous = self._facts.get(path)
        if previous is not None and previous != facts:
            raise BackendProgramError('BACKEND_PROGRAM_ORIGINAL_DESCRIPTOR_DIFFERS')
        self._facts[path] = facts
        return guard

    def _hold_file(self, path, maximum, deadline, cancelled):
        guard = self._hold_path(path, 'FILE', deadline, cancelled)
        source = self._create(
            LockedConfigSource, path, max_file_bytes=maximum, expected_file=guard.identity
        )
        self._sources[path] = source
        return source.verify()

    def _inventory(self, deadline, cancelled):
        found = set()
        pending = ['']
        expected_files = frozenset(item.path for item in self._spec.files)
        directories = self._spec.directories
        while pending:
            relative = pending.pop()
            path = self._root if not relative else self._root.joinpath(*relative.split('/'))
            self._hold_path(path, 'PACKAGE_DIRECTORY', deadline, cancelled)
            with os.scandir(path) as rows:
                for row in rows:
                    self._check_deadline(deadline, cancelled)
                    name = row.name if not relative else relative + '/' + row.name
                    relative_content_path(name)
                    if row.is_dir(follow_symlinks=False):
                        if name not in directories:
                            raise BackendProgramError('BACKEND_PROGRAM_PACKAGE_MEMBERS_DIFFER')
                        pending.append(name)
                    elif row.is_file(follow_symlinks=False):
                        if name != MANIFEST_NAME and name not in expected_files:
                            raise BackendProgramError('BACKEND_PROGRAM_PACKAGE_MEMBERS_DIFFER')
                        found.add(name)
                    else:
                        raise BackendProgramError('BACKEND_PROGRAM_PACKAGE_TYPE_UNSUPPORTED')
                    if len(found) + len(pending) > MAX_MEMBERS * 2 + 1:
                        raise BackendProgramError('BACKEND_PROGRAM_MEMBER_LIMIT')
        return found

    @property
    def peer(self):
        return self._peer

    @property
    def spec(self):
        return self._spec

    def verify(self, *, timeout_ms, cancelled):
        self._check_thread()
        if self._closing or self._spec is None:
            raise BackendProgramError('ORIGINAL_BACKEND_PROGRAM_UNAVAILABLE')
        return self._verify_until(self._deadline(timeout_ms, cancelled), cancelled)

    def _verify_until(self, deadline, cancelled):
        self._peer.verify()
        observations = []
        for path, guard in sorted(
            self._guards.items(), key=lambda item: str(item[0]).encode('utf-8')
        ):
            self._check_deadline(deadline, cancelled)
            facts = require_controller_read_only(self._access.query(guard), role=self._roles[path])
            if facts != self._facts[path]:
                raise BackendProgramError('BACKEND_PROGRAM_ORIGINAL_DESCRIPTOR_DIFFERS')
            observations.append(asdict(facts))
        for source in self._sources.values():
            self._check_deadline(deadline, cancelled)
            if source.verify() != source.snapshot:
                raise BackendProgramError('BACKEND_PROGRAM_ORIGINAL_BYTES_DIFFER')
        actual = self._inventory(deadline, cancelled)
        expected = {MANIFEST_NAME, *(item.path for item in self._spec.files)}
        if actual != expected:
            raise BackendProgramError('BACKEND_PROGRAM_PACKAGE_MEMBERS_DIFFER')
        self._peer.verify()
        evidence = hashlib.sha256(
            _bytes(
                {
                    'policy_version': POLICY_VERSION,
                    'manifest_sha256': self._spec.manifest_sha256,
                    'controller': asdict(self._peer._expected),
                    'image': asdict(self._peer._program.verify()),
                    'access': observations,
                }
            )
        ).hexdigest()
        result = BackendProgramAdmission(
            POLICY_VERSION, self._spec.program_ref, self._spec.manifest_sha256, evidence
        )
        if self._admission is not None and result != self._admission:
            raise BackendProgramError('BACKEND_PROGRAM_ORIGINAL_ADMISSION_DIFFERS')
        return result

    @contextmanager
    def admission(self, *, timeout_ms, cancelled):
        self._check_thread()
        if self._closing:
            raise BackendProgramError('ORIGINAL_BACKEND_PROGRAM_UNAVAILABLE')
        deadline = self._deadline(timeout_ms, cancelled)
        result = self._verify_until(deadline, cancelled)
        self._users += 1
        try:
            yield result
        finally:
            self._users -= 1
            self._verify_until(deadline, cancelled)

    def close(self):
        self._check_thread()
        if self._users:
            raise BackendProgramError('ORIGINAL_BACKEND_PROGRAM_IN_USE')
        self._closing = True
        try:
            for source in tuple(self._sources.values()):
                source.close()
                self._sources.pop(source._path)
            for path, guard in tuple(reversed(tuple(self._guards.items()))):
                guard.close()
                del self._guards[path]
            if self._access is not None:
                self._access.close()
                self._access = None
            if self._token is not None:
                self._token.close()
                self._token = None
            for orphan in tuple(self._orphans):
                orphan.close()
                self._orphans.remove(orphan)
            if self._peer_lease is not None:
                lease, self._peer_lease = self._peer_lease, None
                lease.__exit__(None, None, None)
        except BaseException as error:
            error.retained_owner = self
            raise

    def __enter__(self):
        self._check_thread()
        if self._closing:
            raise BackendProgramError('ORIGINAL_BACKEND_PROGRAM_UNAVAILABLE')
        return self

    def __exit__(self, kind, error, traceback):
        self.close()
