"""Read-only original program bytes; this lease is not an ACL or OS admission."""

import os
from time import monotonic

from .content_paths import ContentPathIndex
from .program_manifest import MAX_MANIFEST_BYTES, ProgramManifestError, decode_program_manifest
from .windows_config_source import LockedFileSource
from .windows_executable_pin import ExecutablePin
from .windows_file_streams import require_default_data_stream
from .windows_local_paths import LocalPathGuard, local_absolute_path


class ProgramPackageLease:
    """Pin a complete fixed inventory and retain its original native owners."""

    def __init__(
        self, root, *, expected_sha256, policy, timeout_ms=120000, cancelled=lambda: False
    ):
        self.root = local_absolute_path(root)
        self.policy = policy
        self.spec = None
        self._owners = []
        self._orphans = []
        self._directories = {}
        self._sources = {}
        self._closed = False
        self._close_failed = False
        self._entry = None
        deadline = self._deadline(timeout_ms, cancelled)
        try:
            self._directory(self.root)
            manifest = self._source(policy.manifest_name, MAX_MANIFEST_BYTES, capture_raw=True)
            self.spec = decode_program_manifest(
                manifest.snapshot.raw, expected_sha256=expected_sha256, policy=policy
            )
            namespace = ContentPathIndex(materialization_root=self.root)
            namespace.add_file(policy.manifest_name, '100644')
            for member in self.spec.files:
                namespace.add_file(member.path, '100644')
            self._inventory(deadline, cancelled)
            for member in self.spec.files:
                self._checkpoint(deadline, cancelled)
                source = self._source(member.path, max(1, member.byte_count))
                if (source.snapshot.byte_count, source.snapshot.sha256) != (
                    member.byte_count,
                    member.sha256,
                ):
                    raise ProgramManifestError('PROGRAM_PACKAGE_MEMBER_BYTES_DIFFER')
            member = next(item for item in self.spec.files if item.path == self.spec.entry)
            self._entry = self._create(
                ExecutablePin,
                self.root / self.spec.entry,
                expected_byte_count=member.byte_count,
                expected_sha256=member.sha256,
            )
            if self._entry.verify().file != self._sources[self.spec.entry].snapshot.file:
                raise ProgramManifestError('PROGRAM_PACKAGE_ORIGINAL_ENTRY_DIFFERS')
            self._inventory(deadline, cancelled)
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    def _deadline(self, timeout_ms, cancelled):
        if type(timeout_ms) is not int or not 1 <= timeout_ms <= 300000 or not callable(cancelled):
            raise ProgramManifestError('PROGRAM_PACKAGE_QUERY_BOUNDARY_REQUIRED')
        deadline = monotonic() + timeout_ms / 1000
        self._checkpoint(deadline, cancelled)
        return deadline

    def _checkpoint(self, deadline, cancelled):
        if self._closed or self._close_failed:
            raise ProgramManifestError('PROGRAM_PACKAGE_LEASE_CLOSED')
        if cancelled() or monotonic() >= deadline:
            raise ProgramManifestError('PROGRAM_PACKAGE_QUERY_CANCELLED_OR_EXPIRED')

    def _create(self, factory, *args, **kwargs):
        try:
            owner = factory(*args, **kwargs)
        except BaseException as error:
            retained = getattr(error, 'retained_owner', None)
            if retained is not None:
                self._orphans.append(retained)
            raise
        self._owners.append(owner)
        return owner

    def _directory(self, path):
        if path in self._directories:
            return self._directories[path]
        owner = self._create(LocalPathGuard, path, directory=True)
        try:
            owner.__enter__()
        except BaseException as error:
            if getattr(error, 'retained_owner', None) is owner:
                self._owners.remove(owner)
                self._orphans.append(owner)
            raise
        require_default_data_stream(owner._kernel, owner._held[-1][0], directory=True)
        self._directories[path] = owner
        return owner

    def _source(self, relative, maximum, *, capture_raw=False):
        owner = self._create(
            LockedFileSource, self.root / relative, max_file_bytes=maximum, capture_raw=capture_raw
        )
        require_default_data_stream(owner._kernel, owner._handle, directory=False)
        self._sources[relative] = owner
        return owner

    def _inventory(self, deadline, cancelled):
        expected_files = {self.policy.manifest_name, *(item.path for item in self.spec.files)}
        expected_directories = self.spec.directories
        found_files, found_directories = set(), set()
        pending = ['']
        while pending:
            self._checkpoint(deadline, cancelled)
            relative = pending.pop()
            path = self.root / relative
            directory = self._directory(path)
            directory.verify()
            require_default_data_stream(directory._kernel, directory._held[-1][0], directory=True)
            with os.scandir(path) as entries:
                for entry in entries:
                    self._checkpoint(deadline, cancelled)
                    name = relative + '/' + entry.name if relative else entry.name
                    if name in expected_directories:
                        found_directories.add(name)
                        pending.append(name)
                    elif name in expected_files:
                        found_files.add(name)
                    else:
                        raise ProgramManifestError('PROGRAM_PACKAGE_MEMBERS_DIFFER')
        if found_files != expected_files or found_directories != expected_directories:
            raise ProgramManifestError('PROGRAM_PACKAGE_MEMBERS_DIFFER')

    def verify(self, *, timeout_ms=120000, cancelled=lambda: False):
        deadline = self._deadline(timeout_ms, cancelled)
        self._inventory(deadline, cancelled)
        for source in self._sources.values():
            self._checkpoint(deadline, cancelled)
            source.verify()
            require_default_data_stream(source._kernel, source._handle, directory=False)
        self._entry.verify()
        self._inventory(deadline, cancelled)
        return self.spec

    def verify_running_entry(self, executable):
        path = local_absolute_path(executable)
        if path != self.root / self.spec.entry:
            raise ProgramManifestError('PROGRAM_PACKAGE_RUNNING_ENTRY_DIFFERS')
        with ExecutablePin(
            path,
            expected_byte_count=self._entry.identity.byte_count,
            expected_sha256=self._entry.identity.sha256,
        ) as current:
            if current.verify().file != self._entry.verify().file:
                raise ProgramManifestError('PROGRAM_PACKAGE_RUNNING_ENTRY_DIFFERS')

    def close(self):
        if self._close_failed:
            error = ProgramManifestError('PROGRAM_PACKAGE_CLOSE_PREVIOUSLY_UNVERIFIED')
            error.retained_owner = self
            raise error
        if self._closed:
            return
        failures = []
        for owner in reversed(self._owners):
            try:
                owner.close()
            except BaseException as error:  # noqa: BLE001 -- Close every owner and retain failures.
                failures.append(error)
        if failures or self._orphans:
            self._close_failed = True
            error = ProgramManifestError('PROGRAM_PACKAGE_CLOSE_UNVERIFIED')
            error.retained_owner = self
            raise error from (failures[0] if failures else None)
        self._owners.clear()
        self._closed = True

    def __enter__(self):
        if self._closed or self._close_failed:
            raise ProgramManifestError('PROGRAM_PACKAGE_LEASE_CLOSED')
        return self

    def __exit__(self, kind, error, traceback):
        self.close()
