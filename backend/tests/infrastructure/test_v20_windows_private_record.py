"""Real original-handle no-replace private publication, no normal data."""

import ctypes
from dataclasses import replace
import hashlib
from unittest.mock import patch

import pytest

from backend.app.infrastructure import windows_private_record as records
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.tests.requirements.test_v15_foundation import tmp_path

NAME = 'a' * 32 + '.git.json'
RAW = b'{"safe":"fact"}\n'


@pytest.fixture
def package(tmp_path):
    path = create_private_package(tmp_path / 'records')
    with PrivatePackageGuard(path) as held:
        yield held


class Proxy:
    def __init__(self, kernel, **overrides):
        self.kernel, self.overrides = kernel, overrides

    def __getattr__(self, name):
        return self.overrides.get(name, getattr(self.kernel, name))


def acquire(package, name=NAME, raw=RAW):
    return records.PrivateRecordAppend(package, name, raw, max_record_bytes=100000)


def test_real_original_handle_same_directory_rename_no_replace_and_raw_identity(package):
    with acquire(package) as owner:
        original = owner._identity
        stage = owner._stage
        assert stage.exists() and not owner._target.exists()
        reference = owner.publish()
        assert not stage.exists() and owner._verify_bytes(owner._target).file_id == original.file_id
        assert reference.filename == NAME and reference.sha256 == hashlib.sha256(RAW).hexdigest()
        assert reference.byte_count == len(RAW)
        assert reference.file.file_id == original.file_id
        assert reference.file.canonical_path == str(package.path / NAME)
        assert owner.publish() == reference
        assert str(package.path) not in repr(reference)
    assert owner._handle is None and (package.path / NAME).read_bytes() == RAW
    assert package.verify_member(NAME, directory=False) == reference.file


def test_unpublished_cleanup_marks_only_original_handle_for_deletion(package):
    owner = acquire(package)
    original = owner._stage
    owner.close()
    assert not original.exists() and list(package.path.iterdir()) == []
    owner.close()


def test_existing_target_never_replaced_and_uncertain_stage_retained(package):
    with (package.path / NAME).open('xb') as stream:
        stream.write(b'ORIGINAL')
    with acquire(package) as owner:
        stage = owner._stage
        with pytest.raises(records.PrivateRecordError, match='RENAME_UNVERIFIED'):
            owner.publish()
        assert (package.path / NAME).read_bytes() == b'ORIGINAL'
        assert owner._verify_bytes(stage).file_id == owner._identity.file_id
        with pytest.raises(records.PrivateRecordError, match='REQUIRES_OBSERVATION'):
            owner.publish()
    assert stage.read_bytes() == RAW and (package.path / NAME).read_bytes() == b'ORIGINAL'


@pytest.mark.parametrize(
    'name',
    [
        '../x',
        'a.git.json',
        'A' * 32 + '.git.json',
        'a' * 32 + '.json',
        'a' * 32 + '.git.json:stream',
    ],
)
def test_program_name_only_before_io(name):
    with patch.object(records, 'record_api', side_effect=AssertionError('No IO')):
        with pytest.raises(records.PrivateRecordError, match='NAME_INVALID'):
            records.PrivateRecordAppend(
                PrivatePackageGuard(r'C:\unused-record-syntax-check'),
                name,
                RAW,
                max_record_bytes=100,
            )


def test_unknown_rename_keeps_original_and_does_not_retry_or_delete(package):
    owner = acquire(package)
    kernel = owner._kernel
    calls = []

    def rename(handle, kind, buffer, size):
        calls.append(kind)
        if kind == 3:
            ctypes.set_last_error(5)
            return False
        return kernel.SetFileInformationByHandle(handle, kind, buffer, size)

    owner._kernel = Proxy(kernel, SetFileInformationByHandle=rename)
    stage = owner._stage
    try:
        with pytest.raises(records.PrivateRecordError, match='RENAME_UNVERIFIED'):
            owner.publish()
        with pytest.raises(records.PrivateRecordError, match='REQUIRES_OBSERVATION'):
            owner.publish()
    finally:
        owner.close()
    assert calls == [3] and stage.read_bytes() == RAW


def test_published_flush_failure_keeps_final_original_file_and_unknown(package):
    owner = acquire(package)
    kernel = owner._kernel
    owner._kernel = Proxy(kernel, FlushFileBuffers=lambda handle: False)
    try:
        with pytest.raises(records.PrivateRecordError, match='PUBLISHED_FLUSH'):
            owner.publish()
        with pytest.raises(records.PrivateRecordError, match='NOT_PUBLISHED'):
            _ = owner.reference
    finally:
        owner._kernel = kernel
        owner.close()
    assert not owner._stage.exists() and owner._target.read_bytes() == RAW


def test_partial_write_and_actual_full_readback(package):
    kernel = records.record_api()

    def short(handle, data, count, written, overlap):
        return kernel.WriteFile(handle, data, min(count, 3), written, overlap)

    with patch.object(records, 'record_api', return_value=Proxy(kernel, WriteFile=short)):
        with acquire(package, raw=RAW * 5000) as owner:
            reference = owner.publish()
    assert reference.byte_count == len(RAW) * 5000
    assert owner._target.read_bytes() == RAW * 5000


def test_close_failure_keeps_original_handle_for_retry(package):
    owner = acquire(package)
    owner.publish()
    kernel, original = owner._kernel, owner._handle
    owner._kernel = Proxy(kernel, CloseHandle=lambda handle: False)
    try:
        with pytest.raises(records.PrivateRecordError) as error:
            owner.close()
        assert error.value.retained_owner is owner and owner._handle == original
    finally:
        owner._kernel = kernel
        owner.close()
    assert owner._target.read_bytes() == RAW


def test_failed_constructor_cleanup_retains_created_original_for_retry(package):
    kernel = records.record_api()
    wrapped = Proxy(
        kernel, WriteFile=lambda *args: False, SetFileInformationByHandle=lambda *args: False
    )
    owner = None
    try:
        with patch.object(records, 'record_api', return_value=wrapped):
            with pytest.raises(records.PrivateRecordError) as error:
                acquire(package)
        owner = error.value.retained_owner
        assert owner._handle and not owner._rename_may and owner._stage.exists()
    finally:
        if owner is not None:
            owner._kernel = kernel
            owner.close()
    assert list(package.path.iterdir()) == []


def test_original_stage_cannot_be_replaced_while_writer_holds_it(package):
    with acquire(package) as owner:
        other = package.path / 'other'
        with other.open('xb') as stream:
            stream.write(b'OTHER')
        with pytest.raises(OSError):
            other.replace(owner._stage)
        assert owner.publish().sha256 == hashlib.sha256(RAW).hexdigest()
