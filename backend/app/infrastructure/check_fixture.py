"""Verify a registered private fixture and its complete file closure."""

from contextlib import contextmanager
from dataclasses import dataclass, field

from backend.app.shared.validation import strict_integer, strict_json_object

from .check_runner_bundle import CheckResourceError, exact_record, reference, valid_sha256
from .content_paths import ContentPathIndex
from .windows_config_source import LockedFileSource
from .windows_local_paths import FileIdentity
from .windows_private_package import PrivatePackageGuard
from .windows_task_workspace_tree import _scan_task_workspace_tree

FIXTURE_MANIFEST = 'manifest.json'
MAX_FIXTURE_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024


@dataclass(frozen=True)
class RegisteredCheckFixture:
    reference: str
    sha256: str
    directory: FileIdentity = field(repr=False)

    def __post_init__(self):
        reference(self.reference)
        if (
            not valid_sha256(self.sha256)
            or type(self.directory) is not FileIdentity
            or not self.directory.is_directory
            or self.directory.filesystem != 'NTFS'
        ):
            raise CheckResourceError('ORIGINAL_TESTING_FIXTURE_REQUIRED')


def _manifest_files(raw, fixture_ref, expected_target):
    value = exact_record(strict_json_object(raw), ('schema_version', 'target', 'file_entries'))
    rows = value['file_entries']
    if (
        type(value['schema_version']) is not int
        or value['schema_version'] != 1
        or type(value['target']) is not dict
        or value['target'].get('fixture_ref') != fixture_ref
        or expected_target is not None
        and value['target'] != expected_target
        or type(rows) is not list
        or len(rows) > 256
    ):
        raise CheckResourceError('TESTING_FIXTURE_MANIFEST_DIFFERS')
    paths = ContentPathIndex()
    paths.add_file(FIXTURE_MANIFEST, '100644')
    total = len(raw)
    result = {}
    for row in rows:
        row = exact_record(row, ('path', 'byte_count', 'sha256'))
        path = paths.add_file(row['path'], '100644').path
        count = strict_integer(row['byte_count'], 'byte_count', 0, MAX_FIXTURE_BYTES)
        total += count
        if total > MAX_FIXTURE_BYTES or not valid_sha256(row['sha256']):
            raise CheckResourceError('TESTING_FIXTURE_FILE_INVALID')
        result[path] = (count, row['sha256'])
    return result


def verify_fixed_members(package, directory, expected, checkpoint):
    if package.verify() != directory:
        raise CheckResourceError('TESTING_RESOURCE_DIRECTORY_DIFFERS')
    files, directories, _, _ = _scan_task_workspace_tree(package.path, directory, checkpoint)
    parents = {
        path[:position]
        for path in expected
        for position, character in enumerate(path)
        if character == '/'
    }
    if {name: (count, digest) for name, (_, count, digest) in files.items()} != expected or set(
        directories
    ) != parents:
        raise CheckResourceError('TESTING_RESOURCE_CLOSURE_DIFFERS')
    for name, identity in directories.items():
        checkpoint()
        if package.verify_member(name, directory=True) != identity:
            raise CheckResourceError('TESTING_RESOURCE_MEMBER_DIFFERS')
    for name, (identity, _, _) in files.items():
        checkpoint()
        if package.verify_member(name, directory=False) != identity:
            raise CheckResourceError('TESTING_RESOURCE_MEMBER_DIFFERS')
    return files


@contextmanager
def hold_check_fixture(fixture, checkpoint, *, expected_target=None):
    if type(fixture) is not RegisteredCheckFixture:
        raise CheckResourceError('ORIGINAL_TESTING_FIXTURE_REQUIRED')
    directory = fixture.directory
    with PrivatePackageGuard(directory.canonical_path) as package:
        manifest = package.verify_member(FIXTURE_MANIFEST, directory=False)
        with LockedFileSource(
            package.path / FIXTURE_MANIFEST,
            max_file_bytes=MAX_MANIFEST_BYTES,
            expected_file=manifest,
            checkpoint=checkpoint,
        ) as source:
            if source.snapshot.sha256 != fixture.sha256:
                raise CheckResourceError('TESTING_FIXTURE_DIGEST_DIFFERS')
            expected = _manifest_files(source.snapshot.raw, fixture.reference, expected_target)
            expected[FIXTURE_MANIFEST] = (source.snapshot.byte_count, source.snapshot.sha256)
            original = verify_fixed_members(package, directory, expected, checkpoint)
            yield (
                package,
                {name: facts for name, facts in original.items() if name != FIXTURE_MANIFEST},
            )
            if original != verify_fixed_members(package, directory, expected, checkpoint):
                raise CheckResourceError('TESTING_FIXTURE_CLOSURE_CHANGED')
