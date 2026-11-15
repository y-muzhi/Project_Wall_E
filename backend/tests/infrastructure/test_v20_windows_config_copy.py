"""Actual private config copy ownership; only fresh operator-private test assets."""

import ctypes
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.app.infrastructure import windows_config_copy as copying
from backend.app.infrastructure import windows_config_source as reading
from backend.app.infrastructure.windows_private_package import (
    PackageSecurityError,
    PrivatePackageGuard,
    create_private_package,
)
from backend.tests.infrastructure.test_v20_windows_private_package import test_only_set_dacl
from backend.tests.requirements.test_v15_foundation import tmp_path


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / 'source.config'
    raw = b'[core]\n repositoryformatversion=0\n bare=false\n[user]\n name=PRIVATE_COPY_ONLY\n'
    with path.open('xb') as stream:
        stream.write(raw)
    package = create_private_package(tmp_path / 'private')
    with (
        PrivatePackageGuard(package) as guard,
        reading.LockedConfigSource(path, max_file_bytes=4096) as source,
    ):
        yield source, guard, path, raw


class Proxy:
    def __init__(self, kernel, **overrides):
        self.kernel, self.overrides = kernel, overrides

    def __getattr__(self, name):
        return self.overrides.get(name, getattr(self.kernel, name))


def test_real_copy_exact_private_identity_and_source_held_through_cleanup(setup):
    source, package, path, raw = setup
    with copying.PrivateConfigCopy(source, package) as copy:
        actual = copy.verify()
        assert actual.raw == raw and actual.file != source.snapshot.file
        assert actual.sha256 == source.snapshot.sha256
        assert package.verify_member(copy._name, directory=False) == actual.file
        assert source._borrows == 1
        with pytest.raises(reading.ConfigReadError, match='IN_USE'):
            source.close()
        assert not source._closing
        with copy.parse_path() as private:
            assert Path(private).read_bytes() == raw
            with pytest.raises(copying.ConfigCopyError, match='IN_USE'):
                copy.close()
            assert not copy._closing
        assert copy.verify() == actual
    assert copy._deleted and not copy._path.exists()
    assert source._borrows == 0 and source.verify().raw == raw
    assert path.read_bytes() == raw
    assert list(package.path.iterdir()) == []
    copy.close()
    with pytest.raises(copying.ConfigCopyError, match='CLOSED'):
        copy.verify()


def test_empty_source_is_copied_and_flushed_as_real_empty_file(tmp_path):
    path = tmp_path / 'empty.config'
    path.open('xb').close()
    package = create_private_package(tmp_path / 'private-empty')
    with (
        PrivatePackageGuard(package) as guard,
        reading.LockedConfigSource(path, max_file_bytes=1) as original,
    ):
        with copying.PrivateConfigCopy(original, guard) as copy:
            assert copy.verify().byte_count == 0
            with copy.parse_path() as private:
                assert Path(private).read_bytes() == b''
        assert list(package.iterdir()) == []


def test_multiple_copies_and_nested_borrows_do_not_release_each_other(setup):
    source, package, _, raw = setup
    first = copying.PrivateConfigCopy(source, package)
    second = copying.PrivateConfigCopy(source, package)
    try:
        assert source._borrows == 2 and first._path != second._path
        with first.parse_path(), first.parse_path():
            assert first._uses == 2
        first.close()
        assert source._borrows == 1 and second.verify().raw == raw
        assert len(list(package.path.iterdir())) == 1
    finally:
        first.close()
        second.close()
    assert source._borrows == 0


def test_input_types_and_inactive_source_fail_without_copying(setup):
    source, package, _, _ = setup
    with patch.object(copying, '_api', side_effect=AssertionError('No native copy')):
        for original, guard in (({}, package), (source, {})):
            with pytest.raises(copying.ConfigCopyError, match='ORIGINAL_CONFIG'):
                copying.PrivateConfigCopy(original, guard)
        source.close()
        with pytest.raises(reading.ConfigReadError, match='LEASE_CLOSED'):
            copying.PrivateConfigCopy(source, package)
    assert list(package.path.iterdir()) == []
    assert source._borrows == 0


def test_create_new_collision_never_alters_or_deletes_existing_file(setup):
    source, package, _, _ = setup
    name = 'git-config-' + 'a' * 32
    existing = package.path / name
    with existing.open('xb') as stream:
        stream.write(b'keep existing file')
    with patch.object(copying, 'uuid4', return_value=SimpleNamespace(hex='a' * 32)):
        with pytest.raises(copying.ConfigCopyError, match='CREATE_FAILED'):
            copying.PrivateConfigCopy(source, package)
    assert existing.read_bytes() == b'keep existing file'
    assert source._borrows == 0


@pytest.mark.parametrize('operation', ['WriteFile', 'FlushFileBuffers'])
def test_failed_write_or_flush_deletes_only_original_partial_copy(setup, operation):
    source, package, _, raw = setup
    kernel = copying._api()
    wrapped = Proxy(kernel, **{operation: lambda *args: False})
    with patch.object(copying, '_api', return_value=wrapped):
        with pytest.raises(copying.ConfigCopyError):
            copying.PrivateConfigCopy(source, package)
    assert list(package.path.iterdir()) == []
    assert source._borrows == 0 and source.verify().raw == raw


def test_short_successful_writes_preserve_every_original_byte(setup):
    source, package, _, raw = setup
    kernel = copying._api()

    def short(handle, buffer, count, written, overlapped):
        return kernel.WriteFile(handle, buffer, min(3, count), written, overlapped)

    with patch.object(copying, '_api', return_value=Proxy(kernel, WriteFile=short)):
        with copying.PrivateConfigCopy(source, package) as copy:
            assert copy.verify().raw == raw


def test_failed_reader_cleanup_is_retained_by_original_copy_owner(setup):
    source, package, _, _ = setup
    kernel = reading.read_api()
    wrapped = Proxy(kernel, ReadFile=lambda *args: False, CloseHandle=lambda handle: False)
    owner = None
    try:
        with patch.object(reading, 'read_api', return_value=wrapped):
            with pytest.raises(reading.ConfigReadError) as caught:
                copying.PrivateConfigCopy(source, package)
        owner = caught.value.retained_owner
        assert type(owner) is copying.PrivateConfigCopy
        assert owner._reader is not None and owner._reader._handle is not None
        assert source._borrows == 1
    finally:
        if owner is not None:
            owner._reader._kernel = kernel
            owner.close()
    assert source._borrows == 0 and list(package.path.iterdir()) == []


@pytest.mark.parametrize('phase', ['reader_close', 'mark_delete', 'delete_close'])
def test_cleanup_failure_retains_specific_original_resources_and_blocks_reuse(setup, phase):
    source, package, _, raw = setup
    copy = copying.PrivateConfigCopy(source, package)
    kernel = copy._kernel
    reader_kernel = copy._reader._kernel
    original_handle = None
    try:
        if phase == 'reader_close':
            copy._reader._kernel = SimpleNamespace(CloseHandle=lambda handle: False)
        elif phase == 'mark_delete':
            copy._kernel = Proxy(kernel, SetFileInformationByHandle=lambda *args: False)
        else:

            def close(handle):
                return False if handle == copy._delete_handle else kernel.CloseHandle(handle)

            copy._kernel = Proxy(kernel, CloseHandle=close)
        with pytest.raises(Exception) as caught:
            copy.close()
        assert caught.value.retained_owner is copy
        assert source._borrows == 1 and not copy._deleted
        if phase == 'reader_close':
            original_handle = copy._reader._handle
            assert original_handle is not None
        else:
            original_handle = copy._delete_handle
            assert original_handle is not None
            assert copy._delete_marked == (phase == 'delete_close')
        with pytest.raises(copying.ConfigCopyError, match='CLOSED'):
            copy.verify()
        with pytest.raises(reading.ConfigReadError, match='IN_USE'):
            source.close()
    finally:
        copy._kernel = kernel
        if copy._reader is not None:
            copy._reader._kernel = reader_kernel
        copy.close()
    assert original_handle is not None
    assert source._borrows == 0 and source.verify().raw == raw
    assert list(package.path.iterdir()) == []


def test_replacement_is_not_deleted_when_its_path_matches_owned_copy(setup):
    source, package, _, raw = setup
    copy = copying.PrivateConfigCopy(source, package)
    original = copy._path
    moved = package.path / 'original-moved.config'
    assert original.parent.resolve() == moved.parent.resolve() == package.path.resolve()
    copy._reader.close()  # Inject loss of the original read barrier, then external replacement.
    os.rename(original, moved)
    with original.open('xb') as stream:
        stream.write(b'OTHER_PRIVATE_FILE')
    try:
        with pytest.raises(copying.ConfigCopyError, match='CLEANUP_IDENTITY_DIFFERS') as caught:
            copy.close()
        assert caught.value.retained_owner is copy
        assert original.read_bytes() == b'OTHER_PRIVATE_FILE'
        assert moved.read_bytes() == raw
        assert source._borrows == 1
    finally:
        original.unlink()
        os.rename(moved, original)
        copy.close()
    assert list(package.path.iterdir()) == []


def test_changed_private_dacl_is_rejected_without_repairs_or_deleting_copy(setup):
    source, package, _, _ = setup
    sid = package.operator_sid
    copy = copying.PrivateConfigCopy(source, package)
    exact = 'D:P(A;OICI;FA;;;' + sid + ')'
    broad = exact + '(A;OICI;FR;;;WD)'
    try:
        test_only_set_dacl(package.path, broad)
        with pytest.raises(PackageSecurityError):
            copy.verify()
        with pytest.raises(PackageSecurityError) as caught:
            copy.close()
        assert caught.value.retained_owner is copy
        assert copy._path.exists() and source._borrows == 1
    finally:
        test_only_set_dacl(package.path, exact)
        copy.close()
    assert list(package.path.iterdir()) == []


def test_cancelled_parse_borrow_is_released_without_discarding_source(setup):
    source, package, _, raw = setup
    with copying.PrivateConfigCopy(source, package) as copy:
        with pytest.raises(RuntimeError, match='cancelled'):
            with copy.parse_path():
                raise RuntimeError('cancelled')
        assert copy._uses == 0 and copy.verify().raw == raw
    assert source._borrows == 0


def test_unknown_create_never_guesses_from_path_or_repeats_creation(setup):
    source, package, _, _ = setup
    kernel = copying._api()
    calls = 0

    def unknown(*args):
        nonlocal calls
        calls += 1
        raise RuntimeError('Injected dispatch uncertainty before actual call')

    owner = None
    try:
        with patch.object(copying, '_api', return_value=Proxy(kernel, CreateFileW=unknown)):
            with pytest.raises(copying.ConfigCopyError, match='CREATION_UNKNOWN') as caught:
                copying.PrivateConfigCopy(source, package)
        owner = caught.value.retained_owner
        assert owner._creation_unknown and owner._writer is None
        assert source._borrows == 1 and calls == 1
        with pytest.raises(copying.ConfigCopyError, match='CREATION_UNKNOWN'):
            owner.close()
        assert calls == 1
    finally:
        if owner is not None:
            # Test has direct proof its injected call never reached the OS.
            owner._creation_unknown = False
            owner.close()
    assert list(package.path.iterdir()) == []
