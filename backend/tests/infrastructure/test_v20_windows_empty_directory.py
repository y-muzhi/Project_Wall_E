"""Actual new private read-only directory; never modifies an existing ACL."""

from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import ctypes

import pytest

from backend.app.infrastructure import windows_empty_directory as empty
from backend.app.infrastructure.windows_private_package import (
    create_private_package,
    PrivatePackageGuard,
    PackageSecurityError,
)
from backend.app.infrastructure.windows_local_paths import PathBoundaryError
from backend.app.infrastructure.windows_access_check import require_controller_read_only
from backend.tests.infrastructure.test_v20_windows_access_check import (
    query,
    ordinary_controller,
    controller,
)
from backend.tests.requirements.test_v15_foundation import tmp_path


@pytest.fixture
def package(tmp_path):
    root = create_private_package(tmp_path / 'private')
    with PrivatePackageGuard(root) as package:
        yield package


def test_actual_operator_can_read_but_cannot_add_or_rewrite_acl(package, query):
    path = empty.create_readonly_empty_directory(package, 'hooks')
    with empty.ReadOnlyEmptyDirectory(path) as held:
        original = held.verify()
        access = query.query(held._guard)
        assert access.granted_access == empty.READ_EXECUTE
        require_controller_read_only(access, role='PACKAGE_DIRECTORY')
        assert list(path.iterdir()) == []
        with pytest.raises(PermissionError):
            (path / 'cannot-write').open('xb')
        with pytest.raises(PermissionError):
            (path / 'cannot-create-directory').mkdir()
        with held.hold():
            with pytest.raises(PackageSecurityError, match='IN_USE'):
                held.close()
            assert held.verify() == original
        with pytest.raises(PermissionError):
            path.rename(path.with_name('cannot-rename-original'))
    # Parent DELETE_CHILD cleanup is allowed only after original handles close.
    path.rmdir()
    assert not path.exists()


@pytest.mark.parametrize('name', ['.', '..', 'nested/hooks', r'nested\hooks', r'C:\outside'])
def test_child_name_cannot_escape_original_private_parent(package, name):
    with pytest.raises((PackageSecurityError, PathBoundaryError)):
        empty.create_readonly_empty_directory(package, name)


def test_existing_directory_is_never_repaired_or_changed(package, query):
    path = package.path / 'existing'
    path.mkdir()
    with empty.LocalPathGuard(path, directory=True) as guard:
        before = query.query(guard)
        with pytest.raises(PackageSecurityError, match='NEW_EMPTY_DIRECTORY_REQUIRED'):
            empty.create_readonly_empty_directory(package, 'existing')
        assert query.query(guard) == before
        with pytest.raises(PackageSecurityError):
            empty.ReadOnlyEmptyDirectory(path)


def test_content_is_not_cleared_to_manufacture_an_empty_resource(package):
    path = package.path / 'content'
    path.mkdir()
    with (path / 'original.txt').open('xb') as stream:
        stream.write(b'original owned content')
    with pytest.raises(PackageSecurityError):
        empty.ReadOnlyEmptyDirectory(path)
    assert (path / 'original.txt').read_bytes() == b'original owned content'


def test_failed_path_close_retains_original_owner(package):
    path = empty.create_readonly_empty_directory(package, 'hooks')
    held = empty.ReadOnlyEmptyDirectory(path)
    try:
        with patch.object(
            held._guard, 'close', side_effect=PackageSecurityError('FIXTURE_CLOSE_UNKNOWN')
        ):
            with pytest.raises(PackageSecurityError) as error:
                held.close()
            assert error.value.retained_owner is held
            with pytest.raises(PackageSecurityError, match='CLOSED'):
                held.verify()
    finally:
        held.close()


def test_descriptor_free_failure_keeps_original_pointer_and_retries_exact_allocation():
    calls = []
    kernel = SimpleNamespace(LocalFree=lambda pointer: calls.append(pointer) or 1)
    allocation = empty._Descriptor(kernel, 123)
    with pytest.raises(PackageSecurityError) as error:
        allocation.close()
    assert error.value.retained_owner is allocation and allocation.pointer == 123
    kernel.LocalFree = lambda pointer: calls.append(pointer) or None
    allocation.close()
    allocation.close()
    assert calls == [123, 123] and allocation.pointer is None
