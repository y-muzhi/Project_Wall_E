"""Actual original Control Git directory release on NTFS."""

from uuid import uuid4

import pytest

from backend.app.infrastructure.guard_action_journal import GuardActionJournal
from backend.app.infrastructure.guard_control_git_actions import _run_control_git_action
from backend.app.infrastructure.guard_controller_binding import GuardControllerBinding
from backend.app.infrastructure.guard_request_header import _parse
from backend.app.infrastructure.runtime_control_git import ControlGitRegistry
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal
from backend.app.infrastructure.windows_config_copy import PrivateConfigCopy
from backend.app.infrastructure.windows_config_source import LockedConfigSource
from backend.app.infrastructure.windows_control_git_directory_release import (
    ControlGitDirectoryRelease,
    ControlGitDirectoryReleaseError,
)
from backend.app.infrastructure.windows_empty_directory import (
    ReadOnlyEmptyDirectory,
    create_readonly_empty_directory,
)
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_control_git_read_package,
    create_private_package,
)
from backend.tests.infrastructure.test_v20_control_git_read_package import (
    controller,
    ordinary_controller,
    reader,
)
from backend.tests.infrastructure.test_v20_guard_control_git_version import wire
from backend.tests.requirements.test_v15_foundation import tmp_path


def create_package(parent, nonce, token):
    path = create_control_git_read_package(parent, nonce, token)
    return PrivatePackageGuard(path, control_git_reader=token).__enter__()


def test_original_release_removes_only_its_copy_hooks_and_private_package(tmp_path, reader):
    token, source, _ = reader
    binding = GuardControllerBinding('a' * 64, str(uuid4()), source.identity)
    parent_path = create_private_package(tmp_path / 'original-journal')
    source_path = tmp_path / 'source.config'
    raw = b'[core]\n bare=false\n'
    with source_path.open('xb') as stream:
        stream.write(raw)
    with (
        LaunchJournal(parent_path) as journal,
        LockedConfigSource(source_path, max_file_bytes=4096) as config,
    ):
        request = _parse(wire(binding, 'PREPARE', {'fixture': 'PRIVATE_READ_ONLY'}), binding)
        actions = GuardActionJournal(journal)
        start = actions.begin(request)
        registry = ControlGitRegistry(journal, token, controller_ref=binding.controller_ref)
        owner = registry.begin_preparation(actions, start)
        try:
            package = owner.allocate(
                'READ_PACKAGE',
                lambda: create_package(journal._package, start.record.directory_nonce, token),
            )
            hooks = owner.allocate(
                'HOOKS',
                lambda: ReadOnlyEmptyDirectory(
                    create_readonly_empty_directory(package, 'hooks'), control_git_reader=token
                ),
            )
            copied = owner.allocate('CONFIG_COPY', lambda: PrivateConfigCopy(config, package))
            stop = _parse(wire(binding, 'STOP', {}, owner.binding_ref), binding)
            stopped = _run_control_git_action(stop, binding, registry)
            assert stopped.result['native']['stop_requested']
            release = _parse(wire(binding, 'RELEASE', {}, owner.binding_ref), binding)
            released = _run_control_git_action(release, binding, registry)
            assert released.result['native']['cleanup_verified']
            assert _run_control_git_action(release, binding, registry) == released
            assert (
                not package.path.exists() and not hooks.path.exists() and not copied._path.exists()
            )
            assert journal._package.verify().is_directory
            assert config.verify().raw == raw
        finally:
            if not owner.handles_released:
                registry.stop(owner.scope)
                owner.close_stopped_handles()
            registry.close_watch()


@pytest.fixture
def prepared_directory(tmp_path, reader):
    token, _, _ = reader
    nonce = uuid4().hex
    root = create_private_package(tmp_path / 'original-parent')
    with PrivatePackageGuard(root) as parent:
        child = create_package(parent, nonce, token)
        try:
            release = ControlGitDirectoryRelease(parent, child, package_nonce=nonce)
            yield parent, child, nonce, token, release
        finally:
            child.close()


def test_nonempty_directory_stays_intact_until_exact_original_is_empty(prepared_directory):
    parent, child, _, _, release = prepared_directory
    unexpected = child.path / 'original-unexpected.bin'
    with unexpected.open('xb') as stream:
        stream.write(b'fixture child')
    with pytest.raises(ControlGitDirectoryReleaseError, match='DELETE_UNVERIFIED') as failed:
        release.close()
    assert failed.value.retained_owner is release
    assert unexpected.read_bytes() == b'fixture child'
    assert release._handle is None
    unexpected.unlink()
    release.close()
    release.close()
    assert not child.path.exists() and parent.path.is_dir()


def test_substitute_at_original_name_is_never_marked_for_deletion(prepared_directory, monkeypatch):
    parent, child, nonce, token, release = prepared_directory
    moved = parent.path / 'moved-original'
    original_close = child.close

    def replace_after_original_lease_closes():
        original_close()
        child.path.rename(moved)
        create_control_git_read_package(parent, nonce, token)

    with monkeypatch.context() as isolated:
        isolated.setattr(child, 'close', replace_after_original_lease_closes)
        with pytest.raises(ControlGitDirectoryReleaseError, match='FILE_ID_DIFFERS'):
            release.close()
    assert moved.is_dir() and child.path.is_dir()
    assert not release._marked and release._handle is None


def test_delete_mark_close_failure_retains_original_handle_for_observation(
    prepared_directory, monkeypatch
):
    parent, child, _, _, release = prepared_directory
    close = release._kernel.CloseHandle

    def fail_marked_close(handle):
        if release._marked and handle == release._handle:
            return False
        return close(handle)

    with monkeypatch.context() as isolated:
        isolated.setattr(release._kernel, 'CloseHandle', fail_marked_close)
        with pytest.raises(
            ControlGitDirectoryReleaseError, match='DELETE_CLOSE_UNVERIFIED'
        ) as failed:
            release.close()
        assert failed.value.retained_owner is release
        assert release._marked and release._handle is not None
    release.close()
    assert release._released and release._handle is None
    assert not child.path.exists() and parent.path.is_dir()
