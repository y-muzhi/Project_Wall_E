"""Trusted local Testing resource registration and protected compilation sources."""

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic

from backend.app.infrastructure.check_fixture import RegisteredCheckFixture, hold_check_fixture
from backend.app.infrastructure.check_runner_bundle import (
    CheckResourceError,
    RegisteredCheckRunner,
    hold_check_runner_bundle,
)
from backend.app.infrastructure.windows_local_paths import FileIdentity

from .pack_compile import CompilerTarget
from .reference_resources import MAX_REFERENCE_SETS, RegisteredReferenceSet


def require_directory(value):
    if type(value) is not FileIdentity or not value.is_directory or value.filesystem != 'NTFS':
        raise CheckResourceError('TESTING_ORIGINAL_PRIVATE_DIRECTORY_REQUIRED')


@dataclass(frozen=True)
class InstalledTarget:
    target: CompilerTarget
    runner: RegisteredCheckRunner
    fixture_directory: FileIdentity = field(repr=False)

    def __post_init__(self):
        require_directory(self.fixture_directory)
        if (
            type(self.target) is not CompilerTarget
            or type(self.runner) is not RegisteredCheckRunner
            or self.target.runner_sha256 != self.runner.manifest_sha256
        ):
            raise CheckResourceError('TESTING_ORIGINAL_TARGET_REGISTRATION_REQUIRED')


@dataclass(frozen=True)
class TestingAssetInstallation:
    pack_directory: FileIdentity = field(repr=False)
    registered_targets: tuple[InstalledTarget, ...]
    reference_sets: tuple[RegisteredReferenceSet, ...] = field(default=(), repr=False)

    def __post_init__(self):
        require_directory(self.pack_directory)
        entries = self.registered_targets
        if (
            type(entries) is not tuple
            or len(entries) > 64
            or any(type(item) is not InstalledTarget for item in entries)
            or len({item.target.target_ref for item in entries}) != len(entries)
        ):
            raise CheckResourceError('TESTING_ORIGINAL_TARGET_REGISTRATION_REQUIRED')
        references = self.reference_sets
        if (
            type(references) is not tuple
            or len(references) > MAX_REFERENCE_SETS
            or any(type(item) is not RegisteredReferenceSet for item in references)
            or len({item.reference.reference_set_ref for item in references}) != len(references)
        ):
            raise CheckResourceError('TESTING_ORIGINAL_REFERENCE_REGISTRATION_REQUIRED')
        pack_root = Path(self.pack_directory.canonical_path)
        source_directories = [
            source for item in entries for source in (item.fixture_directory, item.runner.directory)
        ]
        source_directories.extend(item.directory for item in references)
        for source in source_directories:
            path = Path(source.canonical_path)
            if pack_root.is_relative_to(path) or path.is_relative_to(pack_root):
                raise CheckResourceError('TESTING_PACK_ROOT_OVERLAPS_FIXED_SOURCE')

    @property
    def targets(self):
        return tuple(item.target for item in self.registered_targets)


@contextmanager
def hold_compiler_sources(installation, targets, *, deadline, cancelled):
    """Verify original bytes and resource identities without invoking a runner."""
    if type(installation) is not TestingAssetInstallation:
        raise CheckResourceError('TESTING_COMPILER_INSTALLATION_UNAVAILABLE')

    def checkpoint():
        if cancelled() or monotonic() >= deadline:
            raise CheckResourceError('TESTING_COMPILER_SOURCE_INSPECTION_INTERRUPTED')

    entries = {item.target.target_ref: item for item in installation.registered_targets}
    with ExitStack() as guards:
        for target in targets:
            checkpoint()
            entry = entries.get(target.target_ref)
            if entry is None or entry.target != target:
                raise CheckResourceError('TESTING_ORIGINAL_TARGET_CHANGED')
            runner = guards.enter_context(
                hold_check_runner_bundle(entry.runner, deadline=deadline, cancelled=cancelled)
            )
            if not {'CONTENT_INTEGRITY', target.driver_kind}.issubset(runner.manifest.capabilities):
                raise CheckResourceError('TESTING_RUNNER_CAPABILITY_UNAVAILABLE')
            fixture = RegisteredCheckFixture(
                target.fixture_ref, target.fixture_sha256, entry.fixture_directory
            )
            original = {
                key: value for key, value in target.wire().items() if key != 'fixture_sha256'
            }
            guards.enter_context(hold_check_fixture(fixture, checkpoint, expected_target=original))
        checkpoint()
        yield
        checkpoint()
