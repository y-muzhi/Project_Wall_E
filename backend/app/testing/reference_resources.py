"""Immutable, operator-prepared Testing reference sets, independent of candidates."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from time import monotonic

from backend.app.code_tasks.repository_baseline_validation import read_registered_baseline
from backend.app.infrastructure.check_runner_bundle import (
    CheckResourceError,
    exact_record,
    reference,
    references,
    valid_sha256,
)
from backend.app.infrastructure.content_paths import ContentPathError
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.windows_config_source import ConfigReadError, LockedFileSource
from backend.app.infrastructure.windows_local_paths import FileIdentity, PathBoundaryError
from backend.app.infrastructure.windows_private_package import (
    PackageSecurityError,
    PrivatePackageGuard,
)
from backend.app.shared.validation import strict_integer, strict_json_object

REFERENCE_MANIFEST = 'reference-set.json'
MAX_REFERENCE_BYTES = 1024 * 1024
MAX_SAMPLES = 20
MAX_REFERENCE_SETS = 256
SOURCE_ERRORS = (
    CheckResourceError,
    ConfigReadError,
    ContentPathError,
    OSError,
    PackageSecurityError,
    PathBoundaryError,
    ValueError,
)


@dataclass(frozen=True)
class NegativeReference:
    snapshot_id: int
    expected_failed_case_ids: tuple[str, ...]


@dataclass(frozen=True)
class ReferenceSet:
    reference_set_ref: str
    basis_fingerprint: str
    positive_snapshot_ids: tuple[int, ...]
    negative_controls: tuple[NegativeReference, ...]
    repeat_count: int

    def value(self):
        return {
            'reference_set_ref': self.reference_set_ref,
            'basis_fingerprint': self.basis_fingerprint,
            'positive_snapshot_ids': list(self.positive_snapshot_ids),
            'negative_controls': [
                {
                    'snapshot_id': row.snapshot_id,
                    'expected_failed_case_ids': list(row.expected_failed_case_ids),
                }
                for row in self.negative_controls
            ],
            'repeat_count': self.repeat_count,
        }

    @property
    def snapshot_ids(self):
        return (*self.positive_snapshot_ids, *(row.snapshot_id for row in self.negative_controls))


def decode_reference_set(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_REFERENCE_BYTES:
        raise CheckResourceError('TESTING_REFERENCE_BYTES_INVALID')
    source = exact_record(strict_json_object(raw), ReferenceSet.__dataclass_fields__)
    positives, controls = source['positive_snapshot_ids'], source['negative_controls']
    if (
        not valid_sha256(source['basis_fingerprint'])
        or type(positives) is not list
        or not positives
        or type(controls) is not list
        or not controls
        or len(positives) + len(controls) > MAX_SAMPLES
    ):
        raise CheckResourceError('TESTING_REFERENCE_SAMPLES_INVALID')
    negative = []
    for row in controls:
        row = exact_record(row, NegativeReference.__dataclass_fields__)
        negative.append(
            NegativeReference(
                strict_integer(row['snapshot_id'], 'snapshot_id'),
                references(row['expected_failed_case_ids'], nonempty=True),
            )
        )
    fixed = ReferenceSet(
        reference(source['reference_set_ref']),
        source['basis_fingerprint'],
        tuple(strict_integer(identity, 'snapshot_id') for identity in positives),
        tuple(negative),
        strict_integer(source['repeat_count'], 'repeat_count', 2, 10),
    )
    if len(set(fixed.snapshot_ids)) != len(fixed.snapshot_ids):
        raise CheckResourceError('TESTING_REFERENCE_SAMPLES_OVERLAP')
    return fixed


@dataclass(frozen=True)
class RegisteredReferenceSet:
    reference: ReferenceSet = field(repr=False)
    directory: FileIdentity = field(repr=False)
    sha256: str

    def __post_init__(self):
        if (
            type(self.reference) is not ReferenceSet
            or type(self.directory) is not FileIdentity
            or not self.directory.is_directory
            or self.directory.filesystem != 'NTFS'
            or not valid_sha256(self.sha256)
        ):
            raise CheckResourceError('ORIGINAL_TESTING_REFERENCE_REGISTRATION_REQUIRED')
        # Constructors use the same grammar as the file reader.
        original = canonical_input(self.reference.value()).encode('utf-8')
        if decode_reference_set(original) != self.reference:
            raise CheckResourceError('ORIGINAL_TESTING_REFERENCE_REGISTRATION_DIFFERS')


@contextmanager
def hold_reference_set(registration, *, deadline, cancelled=lambda: False):
    if type(registration) is not RegisteredReferenceSet:
        raise CheckResourceError('ORIGINAL_TESTING_REFERENCE_REGISTRATION_REQUIRED')

    def checkpoint():
        if cancelled() or monotonic() >= deadline:
            raise CheckResourceError('TESTING_REFERENCE_INSPECTION_INTERRUPTED')

    checkpoint()
    with PrivatePackageGuard(registration.directory.canonical_path) as guard:
        if guard.verify() != registration.directory:
            raise CheckResourceError('ORIGINAL_TESTING_REFERENCE_DIRECTORY_DIFFERS')
        identity = guard.verify_member(REFERENCE_MANIFEST, directory=False)
        with LockedFileSource(
            guard.path / REFERENCE_MANIFEST,
            max_file_bytes=MAX_REFERENCE_BYTES,
            expected_file=identity,
            checkpoint=checkpoint,
        ) as source:
            fixed = decode_reference_set(source.snapshot.raw)
            if source.snapshot.sha256 != registration.sha256 or fixed != registration.reference:
                raise CheckResourceError('ORIGINAL_TESTING_REFERENCE_BYTES_DIFFER')
            checkpoint()
            yield fixed
            if (
                source.verify() != source.snapshot
                or guard.verify_member(REFERENCE_MANIFEST, directory=False) != identity
            ):
                raise CheckResourceError('ORIGINAL_TESTING_REFERENCE_CHANGED')


def original_baselines(connection, reference_set):
    """Read only committed GIT20 registration evidence, without probing a repository."""
    result = []
    source_commits = set()
    for identity in reference_set.snapshot_ids:
        row = read_registered_baseline(connection, identity)
        if row is None:
            return None
        commit = row['repository_id'], row['commit_oid']
        if commit in source_commits:
            return None
        source_commits.add(commit)
        result.append(dict(row))
    return tuple(result)


def registration_reason(database, registration):
    try:
        with (
            hold_reference_set(registration, deadline=monotonic() + 3) as fixed,
            database.transaction() as connection,
        ):
            try:
                snapshots = original_baselines(connection, fixed)
            except StorageUnavailable:
                snapshots = None
            if snapshots is None:
                return 'CONTENT_NOT_READY'
    except SOURCE_ERRORS:
        return 'CONTENT_NOT_READY'
    return None
