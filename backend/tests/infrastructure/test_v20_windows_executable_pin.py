"""Actual retained file objects, no program execution or normal data writes."""

from dataclasses import replace
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import struct
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.app.infrastructure import windows_executable_pin as pin
from backend.app.infrastructure.windows_local_paths import LocalPathGuard
from backend.tests.requirements.test_v15_foundation import tmp_path


def image_bytes():
    data = bytearray(2 * pin.READ_CHUNK + 317)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3C, 128)
    data[128:134] = b'PE\0\0\x64\x86'
    struct.pack_into('<HHH', data, 148, 240, 0x22, 0x20B)
    data[4096:] = bytes((index * 13 % 256 for index in range(len(data) - 4096)))
    return bytes(data)


@pytest.fixture
def source(tmp_path):
    directory = tmp_path / 'image-parent'
    directory.mkdir()
    path = directory / '固定 程序.exe'
    data = image_bytes()
    with path.open('xb') as output:
        output.write(data)
    return path, data


def acquire(source, **changes):
    path, data = source
    options = {
        'expected_byte_count': len(data),
        'expected_sha256': hashlib.sha256(data).hexdigest(),
    }
    options.update(changes)
    return pin.ExecutablePin(path, **options)


@pytest.mark.parametrize('count', [None, False, 0, -1, 1.0, 2**53])
def test_catalog_size_is_required_before_any_native_io(count):
    with patch.object(pin, '_api', side_effect=AssertionError('No file open')):
        with pytest.raises(pin.ExecutablePinError, match='SIZE_INVALID'):
            pin.ExecutablePin(r'C:\fixed.exe', expected_byte_count=count, expected_sha256='a' * 64)


@pytest.mark.parametrize('digest', [None, '', 'A' * 64, 'a' * 63, 'g' * 64])
def test_catalog_digest_is_exact_lowercase_sha256_before_native_io(digest):
    with patch.object(pin, '_api', side_effect=AssertionError('No file open')):
        with pytest.raises(pin.ExecutablePinError, match='DIGEST_INVALID'):
            pin.ExecutablePin(r'C:\fixed.exe', expected_byte_count=1, expected_sha256=digest)


@pytest.mark.parametrize('path', ['C:\\' + 'a' * 238 + '.exe', 'C:\\bad\ud800.exe'])
def test_long_or_unpaired_unicode_path_is_not_admitted(path):
    with patch.object(pin, '_api', side_effect=AssertionError('No file open')):
        with pytest.raises(pin.ExecutablePinError, match='PATH_'):
            pin.ExecutablePin(path, expected_byte_count=1, expected_sha256='a' * 64)


def test_real_file_identity_streamed_bytes_noninherit_and_creation_lease(source):
    path, data = source
    with acquire(source) as held:
        actual = held.verify()
        assert actual.file.canonical_path == str(path)
        assert len(actual.file.file_id) == 32
        assert actual.sha256 == hashlib.sha256(data).hexdigest()
        assert actual.byte_count == len(data) and actual.architecture == 'win-x64'
        flags = wintypes.DWORD()
        assert held._kernel.GetHandleInformation(held._handle, ctypes.byref(flags))
        assert flags.value & 1 == 0
        # Other readers still work; Guard never exposes the raw data handle.
        assert path.read_bytes() == data
        with held.creation_path() as application:
            assert application == str(path)
            with pytest.raises(pin.ExecutablePinError, match='IN_USE'):
                held.close()
        assert held.verify() == actual
    with pytest.raises(pin.ExecutablePinError, match='PIN_CLOSED'):
        held.verify()


def test_image_and_parent_cannot_be_written_deleted_or_replaced_during_pin(source):
    path, data = source
    with acquire(source):
        for mode in ('r+b', 'wb'):
            with pytest.raises(OSError):
                with path.open(mode):
                    pytest.fail('No writable file open')
        with pytest.raises(OSError):
            path.unlink()
        with pytest.raises(OSError):
            path.parent.rename(path.parent.with_name('moved'))
        replacement = path.with_name('replacement.exe')
        with replacement.open('xb') as output:
            output.write(b'replacement')
        with pytest.raises(OSError):
            os.replace(replacement, path)
        assert path.read_bytes() == data
    os.replace(replacement, path)
    assert path.read_bytes() == b'replacement'


def test_preexisting_writer_is_rejected_and_failed_pin_releases_ancestors(source):
    path, _ = source
    kernel = pin._api()
    writer = kernel.CreateFileW(str(path), 0x40000000, 0x1 | 0x2 | 0x4, None, 3, 0, None)
    assert writer and writer != ctypes.c_void_p(-1).value
    try:
        with pytest.raises(pin.ExecutablePinError, match='READ_LOCK_UNAVAILABLE'):
            acquire(source)
    finally:
        assert kernel.CloseHandle(writer)
    moved = path.parent.with_name('unlocked')
    path.parent.rename(moved)
    moved.rename(path.parent)


def test_prior_file_identity_rejects_replaced_object_with_identical_bytes(source):
    path, data = source
    with LocalPathGuard(path, directory=False) as old:
        identity = old.verify()
    replacement = path.with_name('new.exe')
    with replacement.open('xb') as output:
        output.write(data)
    os.replace(replacement, path)
    with pytest.raises(pin.ExecutablePinError, match='FILE_IDENTITY_DIFFERS'):
        acquire(source, expected_file=identity)
    with acquire(source) as current:
        assert current.identity.file.file_id != identity.file_id


@pytest.mark.parametrize(
    'kind', ['digest', 'size', 'mz', 'offset', 'machine', 'dll', 'optional', 'truncated']
)
def test_wrong_bytes_size_or_pe_never_get_a_live_pin(source, kind):
    path, original = source
    data = bytearray(original)
    options = {}
    expected = 'BYTES_DIFFER'
    if kind == 'digest':
        options['expected_sha256'] = '0' * 64
    elif kind == 'size':
        options['expected_byte_count'] = len(data) + 1
        expected = 'SIZE_DIFFERS'
    elif kind == 'mz':
        data[0] = 0
        expected = 'NOT_PE'
    elif kind == 'offset':
        struct.pack_into('<I', data, 0x3C, pin.PE_HEADER_LIMIT + 1)
        expected = 'HEADER_INVALID'
    elif kind == 'machine':
        data[132] = 0
        expected = 'NOT_AMD64'
    elif kind == 'dll':
        struct.pack_into('<H', data, 150, 0x2002)
        expected = 'NOT_X64_EXECUTABLE'
    elif kind == 'optional':
        struct.pack_into('<H', data, 152, 0x10B)
        expected = 'NOT_X64_EXECUTABLE'
    else:
        data = data[:156]
        expected = 'NOT_X64_EXECUTABLE'
    # All new fixture writes are to NEW temporary paths.
    altered = path.with_name(kind + '.exe')
    with altered.open('xb') as output:
        output.write(data)
    with pytest.raises(pin.ExecutablePinError, match=expected):
        acquire((altered, data), **options)
    altered.unlink()


@pytest.mark.parametrize('attribute', [0x40, 0x1000, 0x4000, 0x40000, 0x400000])
def test_unadmitted_file_attributes_fail_closed_even_with_matching_digest(source, attribute):
    kernel = pin._api()

    def info(handle, pointer):
        result = kernel.GetFileInformationByHandle(handle, pointer)
        if result:
            ctypes.cast(pointer, ctypes.POINTER(pin.HandleInfo)).contents.attributes |= attribute
        return result

    wrapped = SimpleNamespace(
        **{
            name: getattr(kernel, name)
            for name in (
                'GetFileType',
                'GetHandleInformation',
                'CreateFileW',
                'CloseHandle',
                'ReadFile',
                'SetFilePointerEx',
                'GetFileInformationByHandleEx',
                'GetFinalPathNameByHandleW',
                'GetVolumeInformationByHandleW',
            )
        },
        GetFileInformationByHandle=info,
    )
    with patch.object(pin, '_api', return_value=wrapped):
        with pytest.raises(pin.ExecutablePinError, match='ATTRIBUTES_UNSUPPORTED'):
            acquire(source)


def test_read_failure_cleans_own_file_and_ancestors(source):
    kernel = pin._api()
    wrapped = SimpleNamespace(
        **{
            name: getattr(kernel, name)
            for name in (
                'GetFileType',
                'GetHandleInformation',
                'CreateFileW',
                'CloseHandle',
                'SetFilePointerEx',
                'GetFileInformationByHandle',
                'GetFileInformationByHandleEx',
                'GetFinalPathNameByHandleW',
                'GetVolumeInformationByHandleW',
            )
        },
        ReadFile=lambda *args: False,
    )
    with patch.object(pin, '_api', return_value=wrapped):
        with pytest.raises(pin.ExecutablePinError, match='READ_UNAVAILABLE'):
            acquire(source)
    source[0].unlink()


def test_partial_close_retains_original_object_and_cannot_be_used_for_creation(source):
    held = acquire(source)
    kernel = held._kernel
    original = held._handle
    held._kernel = SimpleNamespace(CloseHandle=lambda handle: False)
    try:
        with pytest.raises(pin.ExecutablePinError, match='CLOSE_UNVERIFIED') as caught:
            held.close()
        assert caught.value.retained_owner is held
        assert held._handle == original and held._guard is not None
        with pytest.raises(pin.ExecutablePinError, match='PIN_CLOSED'):
            held.verify()
    finally:
        held._kernel = kernel
        held.close()
    assert held._handle is None and held._guard is None


def test_failed_ancestor_close_retains_guard_for_actual_retry(source):
    held = acquire(source)
    guard = held._guard
    kernel = guard._kernel
    guard._kernel = SimpleNamespace(CloseHandle=lambda handle: False)
    try:
        with pytest.raises(pin.ExecutablePinError, match='CLOSE_UNVERIFIED') as caught:
            held.close()
        assert caught.value.retained_owner is held
        assert held._handle is None and held._guard is guard and guard._held
    finally:
        guard._kernel = kernel
        held.close()
    assert not guard._held and held._guard is None


def test_actual_fixed_mingit_entry_matches_published_inventory():
    import json
    from backend.app.infrastructure.git_bundle import BUNDLE_PARENT

    root = BUNDLE_PARENT / 'win-x64'
    manifest = json.loads((root / 'manifest.json').read_bytes())
    entry = next(member for member in manifest['members'] if member['path'] == 'cmd/git.exe')
    with pin.ExecutablePin(
        root / 'cmd/git.exe',
        expected_byte_count=entry['byte_count'],
        expected_sha256=entry['sha256'],
    ) as held:
        assert held.identity.sha256 == entry['sha256']
        assert held.verify() == held.identity
    # Still no subprocess, repository, version/Guard/ACL admission or real API.
