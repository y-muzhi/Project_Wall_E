"""Publish the original private candidate directory without replacing a target."""

import ctypes
from dataclasses import dataclass
from time import monotonic

from .content_package import (
    CandidatePackageBinding,
    ContentPackageError,
    SealedCandidate,
    TargetPackageBinding,
    _check_package_paths,
    verify_candidate_package,
)
from .git_commit_closure import ClosureLimits
from .windows_local_paths import FileIdentity, _identity
from .windows_private_package import PrivatePackageGuard, create_private_package
from .windows_private_record import record_api, rename_private_handle_no_replace


@dataclass(frozen=True)
class PublishedCandidate:
    seal: SealedCandidate
    directory: FileIdentity


def _store_identity(store, binding):
    if (
        type(store) is not PrivatePackageGuard
        or store.is_control_git_read_package
        or type(binding) not in (CandidatePackageBinding, TargetPackageBinding)
    ):
        raise ContentPackageError('ORIGINAL_CANDIDATE_STORE_REQUIRED')
    return store.verify()


def create_candidate_stage(store, binding):
    original = _store_identity(store, binding)
    stage = store.path / binding.package_name(staged=True)
    final = store.path / binding.package_name(staged=False)
    for location in (stage, final):
        _check_package_paths(location, binding.object_format)
        if _present(location):
            raise ContentPackageError('CANDIDATE_PACKAGE_KEY_ALREADY_USED')
    created = create_private_package(stage)
    if store.verify() != original:
        raise ContentPackageError('CANDIDATE_STORE_CHANGED')
    return created


def _present(path):
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _physical_identity(file):
    return file.volume_serial, file.file_id


def _rename_original(stage, final, identity, checkpoint):
    kernel = record_api()
    checkpoint()
    handle = kernel.CreateFileW(
        '\\\\?\\' + str(stage),
        0x00010000 | 0x80,  # DELETE | FILE_READ_ATTRIBUTES
        0x1,  # share read; prohibit another writer, deleter or renamer
        None,
        3,  # OPEN_EXISTING
        0x00200000 | 0x02000000,  # no reparse traversal; directory handle
        None,
    )
    if not handle or handle == ctypes.c_void_p(-1).value:
        raise ContentPackageError('CANDIDATE_PUBLICATION_ORIGINAL_OPEN_UNVERIFIED')
    try:
        if _identity(kernel, handle, stage) != identity:
            raise ContentPackageError('CANDIDATE_PUBLICATION_STAGE_CHANGED')
        checkpoint()
        rename_private_handle_no_replace(kernel, handle, final)
        if _physical_identity(_identity(kernel, handle, final)) != _physical_identity(identity):
            raise ContentPackageError('CANDIDATE_PUBLICATION_FILE_ID_DIFFERS')
        checkpoint()
    finally:
        if not kernel.CloseHandle(handle):
            raise ContentPackageError('CANDIDATE_PUBLICATION_CLOSE_UNVERIFIED')


def publish_candidate_package(
    store,
    binding,
    *,
    limits,
    git_limits,
    started_at,
    active,
    materialization_root,
    expected=None,
):
    """Reconcile the recorded key, optionally moving its one exact sealed stage.

    The active callback proves original publish/recovery ownership. The controller
    decides whether a published historical fact can become current. An ambiguous
    outcome leaves both locations untouched for reconciliation.
    """
    original = _store_identity(store, binding)
    if (
        type(git_limits) is not ClosureLimits
        or type(started_at) not in (int, float)
        or not 0 <= started_at <= monotonic()
        or not callable(active)
    ):
        raise ContentPackageError('CANDIDATE_PUBLICATION_CONTROL_REQUIRED')
    deadline = started_at + git_limits.max_seconds

    def checkpoint():
        if monotonic() >= deadline or active() is not None or store.verify() != original:
            raise ContentPackageError('CANDIDATE_PUBLICATION_CONTROL_CHANGED')

    stage = store.path / binding.package_name(staged=True)
    final = store.path / binding.package_name(staged=False)
    _check_package_paths(final, binding.object_format)
    checkpoint()
    staged, published = _present(stage), _present(final)
    if staged and published:
        raise ContentPackageError('CANDIDATE_PUBLICATION_LOCATIONS_CONFLICT')
    if not staged and not published:
        raise ContentPackageError('CANDIDATE_PUBLICATION_PACKAGE_MISSING')
    common = {
        'limits': limits,
        'git_limits': git_limits,
        'started_at': started_at,
        'active': checkpoint,
        'materialization_root': materialization_root,
    }
    identity = None
    if staged:
        with PrivatePackageGuard(stage) as package:
            identity = package.verify()
            if identity.volume_serial != original.volume_serial:
                raise ContentPackageError('CANDIDATE_PUBLICATION_VOLUME_DIFFERS')
            expected = verify_candidate_package(package, binding, expected=expected, **common)
        _rename_original(stage, final, identity, checkpoint)

    with PrivatePackageGuard(final) as package:
        destination = package.verify()
        if destination.volume_serial != original.volume_serial or (
            identity is not None and _physical_identity(destination) != _physical_identity(identity)
        ):
            raise ContentPackageError('CANDIDATE_PUBLICATION_DESTINATION_DIFFERS')
        sealed = verify_candidate_package(package, binding, expected=expected, **common)
        if _present(stage) or package.verify() != destination:
            raise ContentPackageError('CANDIDATE_PUBLICATION_DESTINATION_UNVERIFIED')
        checkpoint()
    return PublishedCandidate(sealed, destination)
