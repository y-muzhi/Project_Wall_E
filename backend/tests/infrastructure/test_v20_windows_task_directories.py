"""Original LPAC directory ACLs and integrity labels on temporary NTFS objects."""

import ctypes
from ctypes import wintypes
from uuid import uuid4

import pytest

from backend.app.infrastructure.guard_action_journal import GuardActionJournal
from backend.app.infrastructure.guard_controller_binding import GuardControllerBinding
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal
from backend.app.infrastructure.windows_controller_token import ControllerPrimaryToken
from backend.app.infrastructure.windows_local_paths import LocalDirectoryPin
from backend.app.infrastructure.windows_private_package import (
    PackageSecurityError,
    create_private_package,
    _api,
)
from backend.app.infrastructure.windows_task_directories import (
    MUTABLE_ROLES,
    TASK_ROLES,
    TaskLpacDirectories,
    TaskRuntimeRoot,
    _read_aces,
)
from backend.tests.infrastructure.test_v20_guard_action_journal import packet
from backend.tests.infrastructure.test_v20_windows_controller_token import (
    controller,
    ordinary_controller,
)
from backend.tests.requirements.test_v15_foundation import tmp_path


@pytest.fixture
def original_paths(tmp_path, ordinary_controller):
    process, _ = ordinary_controller
    binding = GuardControllerBinding(uuid4().hex + uuid4().hex, str(uuid4()), process.identity)
    with (
        ControllerPrimaryToken(process, expected=binding.controller) as token,
        LaunchJournal(create_private_package(tmp_path / 'guard')) as journal,
        LocalDirectoryPin(tmp_path) as base,
        TaskRuntimeRoot.create(base, binding.controller.user_sid) as runtime_root,
    ):
        actions = GuardActionJournal(journal)
        prepare = packet(binding, action_input={'run_kind': 'TASK'})
        accepted = actions.begin(prepare)
        with pytest.raises(PackageSecurityError, match='FIRST_ACCEPTANCE_REQUIRED'):
            TaskLpacDirectories(
                runtime_root, actions, actions.begin(prepare), prepare, binding, token
            )
        owner = TaskLpacDirectories(runtime_root, actions, accepted, prepare, binding, token)
        try:
            yield owner, journal
        finally:
            owner.close()


def test_real_original_lpac_directory_layout_keeps_distinct_protected_roles(original_paths):
    owner, journal = original_paths
    expected_parent = journal._package.verify()
    results = owner.allocate(cancelled=lambda: False)
    assert results == owner.verify()
    assert tuple(fact.role for fact in results) == TASK_ROLES
    assert len({fact.file.file_id for fact in results}) == len(TASK_ROLES)
    assert all(fact.file.volume_serial == expected_parent.volume_serial for fact in results)
    assert all(
        fact.integrity_sid == ('S-1-16-4096' if fact.role in MUTABLE_ROLES else 'S-1-16-8192')
        for fact in results
    )
    assert owner.package_sid.startswith('S-1-15-2-')
    assert set(path.name for path in owner.root.iterdir()) == set(TASK_ROLES) - {'root'}
    assert all(not list((owner.root / role).iterdir()) for role in TASK_ROLES[1:])
    assert journal._package.verify() == expected_parent
    with pytest.raises(PackageSecurityError, match='ALLOCATION_NOT_NEW'):
        owner.allocate(cancelled=lambda: False)


def test_cancelled_lpac_directory_allocation_keeps_original_partial_owner(original_paths):
    owner, _ = original_paths
    with pytest.raises(PackageSecurityError, match='ALLOCATION_INTERRUPTED') as failure:
        owner.allocate(cancelled=lambda: (owner.root / 'workspace').exists())
    assert failure.value.retained_owner is owner
    assert [path.name for path in owner.root.iterdir()] == ['workspace']
    assert owner._directories['workspace'].original is not None
    with pytest.raises(PackageSecurityError, match='DIRECTORIES_UNVERIFIED'):
        owner.verify()
    with pytest.raises(PackageSecurityError, match='ALLOCATION_NOT_NEW'):
        owner.allocate(cancelled=lambda: False)


def test_lpac_directory_never_adopts_existing_scope_path(original_paths):
    owner, _ = original_paths
    owner.root.mkdir()
    sentinel = owner.root / 'existing'
    sentinel.write_bytes(b'existing')
    with pytest.raises(PackageSecurityError, match='NEW_DIRECTORY_REQUIRED') as failure:
        owner.allocate(cancelled=lambda: False)
    assert failure.value.retained_owner is owner
    assert not owner._directories['root'].created
    assert list(owner.root.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b'existing'


def test_closed_original_scope_blocks_any_directory_creation(original_paths):
    owner, journal = original_paths
    journal.close_nonce(owner.scope)
    with pytest.raises(PackageSecurityError, match='ALLOCATION_INTERRUPTED'):
        owner.allocate(cancelled=lambda: False)
    assert not owner.root.exists()


def test_original_task_files_inherit_only_their_role_permissions(original_paths):
    owner, _ = original_paths
    owner.allocate(cancelled=lambda: False)
    kernel, security = _api()
    expected = {
        'workspace': (0x001301FF, 'S-1-16-4096'),
        'scratch': (0x001301FF, 'S-1-16-4096'),
        'basis': (0x00120089, 'S-1-16-8192'),
        'config': (0x00120089, 'S-1-16-8192'),
        'runtime': (0x001200A9, 'S-1-16-8192'),
    }
    for role, (rights, label) in expected.items():
        child = owner.root / role / 'owned-test-input'
        child.write_bytes(b'fixture')
        dacl, sacl, descriptor = (wintypes.LPVOID() for _ in range(3))
        assert (
            security.GetNamedSecurityInfoW(
                str(child),
                1,
                0x14,
                None,
                None,
                ctypes.byref(dacl),
                ctypes.byref(sacl),
                ctypes.byref(descriptor),
            )
            == 0
        )
        try:
            aces = _read_aces(kernel, security, dacl)
            # NTFS can materialize inherited file ACEs without INHERITED_ACE.
            assert all(flags in (0, 0x10) for _, flags, _, _ in aces)
            grants = [(kind, mask, sid) for kind, _, mask, sid in aces]
            assert [ace for ace in grants if ace[2] == owner.package_sid] == [
                (0, rights, owner.package_sid)
            ]
            assert (0, rights, 'S-1-3-4') in grants
            ((kind, flags, mask, sid),) = _read_aces(kernel, security, sacl)
            assert flags in (0, 0x10)
            assert (kind, mask, sid) == (0x11, 1, label)
        finally:
            assert not kernel.LocalFree(descriptor)
    owner.verify()
