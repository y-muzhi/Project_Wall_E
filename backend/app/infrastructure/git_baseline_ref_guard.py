"""A narrow NTFS metadata lease for one original create-only baseline ref."""

from dataclasses import replace

from .git_ref_metadata import decode_packed_refs
from .git_ref_protocol import RefPrepareInput
from .git_repository_metadata import MetadataTreeError, RepositoryMetadataLease
from .windows_config_source import LockedConfigSource
from .windows_local_paths import FileIdentity, LocalPathGuard


class BaselineRefConflict(RuntimeError):
    code = 'RESOURCE_CONFLICT'


class BaselineRefGuard:
    """Only the original namespaced lock and its final ref may differ."""

    def __init__(self, metadata, intent):
        if (
            type(metadata) is not RepositoryMetadataLease
            or type(intent) is not RefPrepareInput
            or intent.kind != 'BASELINE_CREATE'
            or intent.object_format != metadata._format
        ):
            raise TypeError('Original create-only baseline reference required')
        self._metadata, self._intent = metadata, intent
        self._target = metadata._common.joinpath(*intent.full_ref.split('/'))
        self._lock = self._target.with_suffix('.lock')
        self._parents = (self._target.parent.parent, self._target.parent)
        self._closed = False
        with metadata._gate:
            self.snapshot = metadata.verify()
            if self.snapshot.lock_paths:
                raise BaselineRefConflict('Original repository has an existing Git lock')
            self._require_absent(self._target)
            self._require_absent(metadata._common / 'logs' / intent.full_ref)
            self._check_packed()
            metadata._users += 1

    def _require_absent(self, path):
        directory = self._metadata._common
        parts = path.relative_to(directory).parts
        for index, part in enumerate(parts):
            names = self._metadata._listings.get(directory, ())
            aliases = tuple(name for name in names if name.casefold() == part.casefold())
            if not aliases:
                return
            if aliases != (part,) or index == len(parts) - 1:
                raise BaselineRefConflict('Original baseline ref or reflog exists')
            directory /= part
            if directory not in self._metadata._listings:
                raise BaselineRefConflict('Original baseline reference namespace is occupied')

    def _check_packed(self):
        metadata = self._metadata
        source = metadata._sources.get(str(metadata._common / 'packed-refs'))
        if source is None:
            return
        original = source.verify()
        target = self._intent.full_ref.split('/')
        for row in decode_packed_refs(
            original.raw,
            format=self._intent.object_format,
            max_output_bytes=metadata._file_limit,
            max_refs=metadata._entry_limit,
        ):
            parts = row.name.split('/')
            length = min(len(parts), len(target))
            shared = parts[:length]
            expected = target[:length]
            if [value.casefold() for value in shared] != [value.casefold() for value in expected]:
                # A packed sibling can also occupy a parent via a case alias.
                for actual, wanted in zip(parts, target):
                    if actual.casefold() != wanted.casefold():
                        break
                    if actual != wanted:
                        raise BaselineRefConflict('Original baseline packed namespace has an alias')
                continue
            raise BaselineRefConflict('Original baseline packed reference is occupied')

    def _verify_delta(self, expected_file):
        metadata = self._metadata
        if self._closed:
            raise MetadataTreeError('ORIGINAL_BASELINE_REF_LEASE_CLOSED')
        metadata._verify_pins()
        additions = {parent.parent: {parent.name} for parent in self._parents}
        additions[self._target.parent] = set() if expected_file is None else {expected_file.name}
        for directory in metadata._listings.keys() | additions.keys():
            original = metadata._listings.get(directory)
            if original is None:
                try:
                    directory.lstat()
                except FileNotFoundError:
                    if expected_file is not None:
                        raise MetadataTreeError(
                            'ORIGINAL_BASELINE_REF_PATH_MISSING', changed=True
                        ) from None
                    continue
                with LocalPathGuard(directory, directory=True) as guard:
                    guard.verify()
                    names = set(metadata._listing(directory))
            else:
                names = set(metadata._listing(directory))
            if (
                expected_file is not None
                and directory == expected_file.parent
                and expected_file.name not in names
            ):
                raise MetadataTreeError('ORIGINAL_BASELINE_REF_PATH_MISSING', changed=True)
            before = set(original or ())
            if not before <= names or names - before - additions.get(directory, set()):
                raise MetadataTreeError('ORIGINAL_BASELINE_REF_METADATA_CHANGED', changed=True)

    def _read_ref(self, path):
        expected = self._intent.new_oid.encode('ascii') + b'\n'
        with LockedConfigSource(path, max_file_bytes=len(expected)) as source:
            observed = source.verify()
            if observed.raw != expected:
                raise MetadataTreeError('ORIGINAL_BASELINE_REF_BYTES_DIFFER', changed=True)
            self._verify_delta(path)
            return observed.file

    def verify_prepared(self):
        metadata = self._metadata
        with metadata._gate:
            self._verify_delta(self._lock)
            return self._read_ref(self._lock)

    def verify_committed(self, original_lock):
        if type(original_lock) is not FileIdentity or original_lock.canonical_path != str(
            self._lock
        ):
            raise TypeError('Original baseline lock identity required')
        metadata = self._metadata
        with metadata._gate:
            self._verify_delta(self._target)
            actual = self._read_ref(self._target)
            if actual != replace(original_lock, canonical_path=str(self._target)):
                raise MetadataTreeError('ORIGINAL_BASELINE_REF_IDENTITY_DIFFERS', changed=True)
            return actual

    def verify_aborted(self):
        with self._metadata._gate:
            self._verify_delta(None)

    def close(self):
        with self._metadata._gate:
            if not self._closed:
                self._metadata._users -= 1
                self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        self.close()
