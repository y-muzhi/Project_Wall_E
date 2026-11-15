"""Write an independent private check copy of the exact candidate package."""

from dataclasses import dataclass, field
from time import monotonic

from backend.app.infrastructure.content_package import (
    SealedCandidate,
    verify_candidate_package,
)
from backend.app.infrastructure.content_package_publish import PublishedCandidate
from backend.app.infrastructure.git_commit_closure import ClosureLimits
from backend.app.infrastructure.windows_config_source import ConfigReadError
from backend.app.infrastructure.windows_local_paths import FileIdentity, local_absolute_path
from backend.app.infrastructure.windows_private_package import PrivatePackageGuard

from .workspace_materialization import (
    FixedWorkspaceStage,
    WorkspaceMaterializationError,
    verify_workspace_tree,
)


@dataclass(frozen=True)
class MaterializedCandidate:
    seal: SealedCandidate
    directory: FileIdentity = field(repr=False)


def materialize_candidate(
    parent, nonce, original, *, active, limits, git_limits, started_at, record_stage
):
    """Reuse the fixed-tree materializer without opening any writable source."""
    if (
        type(parent) is not PrivatePackageGuard
        or parent.is_control_git_read_package
        or type(git_limits) is not ClosureLimits
        or type(original) is not PublishedCandidate
        or type(original.seal) is not SealedCandidate
        or type(original.directory) is not FileIdentity
        or not original.directory.is_directory
        or not callable(active)
        or not callable(record_stage)
        or type(started_at) not in (int, float)
        or not 0 <= started_at <= monotonic()
    ):
        raise WorkspaceMaterializationError('ORIGINAL_CANDIDATE_MATERIALIZATION_REQUIRED')
    binding = original.seal.binding
    with PrivatePackageGuard(original.directory.canonical_path) as source:
        if (
            source.verify() != original.directory
            or source.path.name != binding.package_name(staged=False)
            or parent.path.is_relative_to(source.path)
            or source.path.is_relative_to(parent.path)
        ):
            raise WorkspaceMaterializationError('ORIGINAL_CANDIDATE_DIRECTORY_DIFFERS')

        def checkpoint():
            if active() is not None or source.verify() != original.directory:
                raise WorkspaceMaterializationError('ORIGINAL_CANDIDATE_DIRECTORY_DIFFERS')
            if monotonic() - started_at >= git_limits.max_seconds:
                raise WorkspaceMaterializationError('CANDIDATE_MATERIALIZATION_DEADLINE_EXCEEDED')

        stage = FixedWorkspaceStage(parent, nonce, checkpoint, record_stage=record_stage)
        seal = verify_candidate_package(
            source,
            binding,
            limits=limits,
            git_limits=git_limits,
            started_at=started_at,
            active=checkpoint,
            materialization_root=stage.target,
            expected=original.seal,
            consume_file=stage.consume,
        )
        directory = stage.publish_entries(seal.manifest.entries, checkpoint)
        return MaterializedCandidate(seal, directory)


@dataclass(frozen=True)
class CandidateInputIntegrity:
    candidate_id: int
    manifest_sha256: str
    content_tree_oid: str
    file_count: int
    byte_count: int
    private_copy: FileIdentity = field(repr=False)


def verify_candidate_check_input(materialized, *, active):
    """Verify the current check copy against the exact fixed entries.

    This is the CONTENT_INTEGRITY fact. The check runner still has to prove
    source read-only permissions while untrusted processes can execute.
    """
    if (
        type(materialized) is not MaterializedCandidate
        or type(materialized.seal) is not SealedCandidate
        or type(materialized.directory) is not FileIdentity
        or not materialized.directory.is_directory
        or not callable(active)
    ):
        raise WorkspaceMaterializationError('ORIGINAL_CANDIDATE_CHECK_INPUT_REQUIRED')
    seal = materialized.seal
    manifest = seal.manifest

    def checkpoint():
        if active() is not None:
            raise WorkspaceMaterializationError('ORIGINAL_CANDIDATE_CHECK_INPUT_FENCED')

    try:
        directory = verify_workspace_tree(
            local_absolute_path(materialized.directory.canonical_path),
            materialized.directory,
            manifest.entries,
            checkpoint,
        )
    except ConfigReadError as error:
        if error.code == 'SOURCE_CHANGED' or error.reason == 'CONFIG_READ_BYTES_EXCEEDED':
            raise WorkspaceMaterializationError('INPUT_CHANGED') from error
        raise
    except WorkspaceMaterializationError as error:
        if str(error).endswith(('_DIFFER', '_DIFFERS')):
            raise WorkspaceMaterializationError('INPUT_CHANGED') from error
        raise
    if directory != materialized.directory:
        raise WorkspaceMaterializationError('ORIGINAL_CANDIDATE_CHECK_INPUT_CHANGED')
    return CandidateInputIntegrity(
        seal.binding.candidate_id,
        seal.manifest_sha256,
        manifest.content_tree_oid,
        manifest.file_count,
        manifest.byte_count,
        directory,
    )
