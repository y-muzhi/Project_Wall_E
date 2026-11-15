"""Actual original NTFS config read lease; no repository or provider use."""

import ctypes
from ctypes import wintypes
from dataclasses import replace
import hashlib
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.app.infrastructure import windows_config_source as source
from backend.app.infrastructure.git_local_config import GitConfigError
from backend.app.infrastructure.windows_local_paths import LocalPathGuard, PathBoundaryError
from backend.tests.requirements.test_v15_foundation import tmp_path


@pytest.fixture
def config(tmp_path):
    directory = tmp_path / '配置目录'
    directory.mkdir()
    path = directory / 'original.config'
    raw = b'[core]\n bare=false\n' + b'# opaque original text\n' * 7001
    with path.open('xb') as stream:
        stream.write(raw)
    return path, raw


def acquire(config, **extra):
    path, raw = config
    return source.LockedConfigSource(
        path, max_file_bytes=extra.pop('max_file_bytes', len(raw)), **extra
    )


@pytest.mark.parametrize('limit', [None, False, 0, -1, 1.5, 2**53])
def test_limits_fail_before_native_io(limit):
    with patch.object(source, 'read_api', side_effect=AssertionError('No native IO')):
        with pytest.raises(source.ConfigReadError, match='LIMIT_INVALID'):
            source.LockedConfigSource(r'C:\safe.config', max_file_bytes=limit)


def test_identity_type_and_long_path_fail_before_io():
    with patch.object(source, 'read_api', side_effect=AssertionError('No native IO')):
        with pytest.raises(source.ConfigReadError, match='IDENTITY_INVALID'):
            source.LockedConfigSource(r'C:\safe.config', max_file_bytes=1, expected_file={})
        with pytest.raises(source.ConfigReadError, match='PATH_TOO_LONG'):
            source.LockedConfigSource('C:\\' + 'a' * 239, max_file_bytes=1)


def test_actual_original_raw_bytes_hash_identity_and_noninheritance(config):
    path, raw = config
    with acquire(config) as held:
        value = held.snapshot
        assert value.raw == raw and value.byte_count == len(raw)
        assert value.sha256 == hashlib.sha256(raw).hexdigest()
        assert held.verify() == value
        assert raw[:20].decode() not in repr(value)
        assert str(path) not in repr(value)
        with pytest.raises(AttributeError):
            held.snapshot = None
        flags = wintypes.DWORD()
        assert held._kernel.GetHandleInformation(held._handle, ctypes.byref(flags))
        assert flags.value & 1 == 0
        assert value.file == held._guard.verify()
    with pytest.raises(source.ConfigReadError, match='LEASE_CLOSED'):
        held.verify()
    assert held._handle is None and held._guard is None
    assert path.read_bytes() == raw
    held.close()


def test_real_sharing_denies_writers_replacement_and_parent_rename(config, tmp_path):
    path, raw = config
    with acquire(config) as held:
        kernel = held._kernel
        handle = kernel.CreateFileW(str(path), 0x40000000, 3, None, 3, 0, None)
        assert handle == ctypes.c_void_p(-1).value
        assert ctypes.get_last_error() in (32, 33)
        with pytest.raises(OSError):
            os.replace(path, tmp_path / 'replaced.config')
        with pytest.raises(OSError):
            os.rename(path.parent, tmp_path / 'moved-parent')
        assert held.verify().raw == raw
    assert path.exists()


def test_preexisting_writer_is_busy_and_remains_owned_by_its_original_caller(config):
    path, _ = config
    kernel = source.read_api()
    writer = kernel.CreateFileW(str(path), 0x40000000, 3, None, 3, 0, None)
    assert writer and writer != ctypes.c_void_p(-1).value
    try:
        with pytest.raises(source.ConfigReadError) as caught:
            acquire(config)
        assert caught.value.code == 'SOURCE_BUSY'
        assert caught.value.native_error in (32, 33)
    finally:
        assert kernel.CloseHandle(writer)
    with acquire(config):
        pass


def test_expected_original_object_must_match(config):
    path, _ = config
    with LocalPathGuard(path, directory=False) as metadata:
        identity = metadata.identity
    with acquire(config, expected_file=identity) as held:
        assert held.snapshot.file == identity
    wrong = replace(identity, file_id='0' * 32 if identity.file_id != '0' * 32 else '1' * 32)
    with pytest.raises(source.ConfigReadError, match='ORIGINAL_FILE_DIFFERS'):
        acquire(config, expected_file=wrong)


def test_capacity_checked_before_read_and_empty_file_is_a_real_success(config, tmp_path):
    path, raw = config
    with pytest.raises(source.ConfigReadError, match='BYTES_EXCEEDED'):
        acquire(config, max_file_bytes=len(raw) - 1)
    empty = tmp_path / 'empty.config'
    empty.open('xb').close()
    with source.LockedConfigSource(empty, max_file_bytes=1) as held:
        assert held.snapshot.raw == b'' and held.snapshot.byte_count == 0
    with pytest.raises(PathBoundaryError):
        source.LockedConfigSource(tmp_path / 'absent', max_file_bytes=1)


def test_embedded_nul_is_not_returned_and_failure_releases_only_own_handles(tmp_path):
    path = tmp_path / 'embedded-zero.config'
    with path.open('xb') as stream:
        stream.write(b'[user]\nname=x\0core.bare=true')
    with pytest.raises(GitConfigError, match='SOURCE_BYTES_UNSUPPORTED'):
        source.LockedConfigSource(path, max_file_bytes=100)
    os.rename(path, tmp_path / 'embedded-zero-after-close.config')


def test_hardlink_is_rejected_without_altering_either_file(config, tmp_path):
    path, raw = config
    link = tmp_path / 'hardlink.config'
    os.link(path, link)
    with pytest.raises(PathBoundaryError, match='MULTIPLE_HARD_LINKS'):
        acquire(config)
    assert path.read_bytes() == link.read_bytes() == raw


class KernelProxy:
    def __init__(self, kernel, **overrides):
        self.kernel = kernel
        self.overrides = overrides

    def __getattr__(self, name):
        return self.overrides.get(name, getattr(self.kernel, name))


@pytest.mark.parametrize('operation', ['ReadFile', 'SetFilePointerEx'])
def test_native_read_seek_failure_is_not_empty(config, operation):
    kernel = source.read_api()
    wrapped = KernelProxy(kernel, **{operation: lambda *args: False})
    with patch.object(source, 'read_api', return_value=wrapped):
        with pytest.raises(source.ConfigReadError):
            acquire(config)
    with acquire(config):
        pass


@pytest.mark.parametrize('flag', [0x40, 0x1000, 0x4000, 0x40000, 0x400000])
def test_unsupported_special_attributes_fail_even_for_valid_default_stream(config, flag):
    kernel = source.read_api()

    def attributes(handle, pointer):
        result = kernel.GetFileInformationByHandle(handle, pointer)
        ctypes.cast(pointer, ctypes.POINTER(source.HandleInfo)).contents.attributes |= flag
        return result

    with patch.object(
        source, 'read_api', return_value=KernelProxy(kernel, GetFileInformationByHandle=attributes)
    ):
        with pytest.raises(source.ConfigReadError, match='ATTRIBUTES_UNSUPPORTED'):
            acquire(config)


def test_close_failure_keeps_original_data_and_ancestors_and_blocks_reuse(config):
    held = acquire(config)
    kernel, handle, guard = held._kernel, held._handle, held._guard
    held._kernel = SimpleNamespace(CloseHandle=lambda handle: False)
    try:
        with pytest.raises(source.ConfigReadError) as caught:
            held.close()
        assert caught.value.retained_owner is held
        assert held._handle == handle and held._guard is guard
        with pytest.raises(source.ConfigReadError, match='LEASE_CLOSED'):
            held.verify()
    finally:
        held._kernel = kernel
        held.close()


def test_failed_constructor_cleanup_retains_original_owner_for_retry(config):
    kernel = source.read_api()
    wrapped = KernelProxy(kernel, ReadFile=lambda *args: False, CloseHandle=lambda handle: False)
    held = None
    try:
        with patch.object(source, 'read_api', return_value=wrapped):
            with pytest.raises(source.ConfigReadError) as caught:
                acquire(config)
        held = caught.value.retained_owner
        assert held._handle is not None and held._guard is not None
    finally:
        if held is not None:
            held._kernel = kernel
            held.close()
