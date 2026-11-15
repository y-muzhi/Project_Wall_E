"""Original-controller read role on NEW private preparation packages only."""

import ctypes
from ctypes import wintypes
from uuid import uuid4

import pytest

from backend.app.infrastructure import windows_private_package as packages
from backend.app.infrastructure.windows_config_source import LockedConfigSource
from backend.app.infrastructure.windows_config_copy import PrivateConfigCopy
from backend.app.infrastructure.windows_controller_token import (
    ControllerPrimaryToken,
    ControllerTokenError,
)
from backend.app.infrastructure.windows_empty_directory import (
    ReadOnlyEmptyDirectory,
    create_readonly_empty_directory,
    _verify_security,
)
from backend.app.infrastructure.windows_private_record import (
    PrivateRecordAppend,
    PrivateRecordError,
)
from backend.tests.infrastructure.test_v20_windows_controller_token import (
    ordinary_controller,
    controller,
)
from backend.tests.infrastructure.test_v20_windows_private_package import test_only_set_dacl
from backend.tests.requirements.test_v15_foundation import tmp_path

UNASSIGNED_SID = 'S-1-5-21-42424242-42424242-42424242-42424242'


@pytest.fixture
def reader(ordinary_controller):
    process, job = ordinary_controller
    with ControllerPrimaryToken(process, expected=process.identity) as token:
        yield token, process, job


def test_new_read_role_reuses_actual_config_copy_hooks_and_blocks_private_records(tmp_path, reader):
    token, _, _ = reader
    source_path = tmp_path / 'source.config'
    raw = b'[core]\n bare=false\n'
    with source_path.open('xb') as stream:
        stream.write(raw)
    parent_path = packages.create_private_package(tmp_path / 'operator-root')
    with packages.PrivatePackageGuard(parent_path) as parent:
        nonce = uuid4().hex
        child = packages.create_control_git_read_package(parent, nonce, token)
        assert child == parent_path / ('control-git-' + nonce)
        with packages.PrivatePackageGuard(child, control_git_reader=token) as package:
            assert package.is_control_git_read_package
            assert package.reader_sid == token.identity.user_sid
            with LockedConfigSource(source_path, max_file_bytes=4096) as source:
                with PrivateConfigCopy(source, package) as copy:
                    assert copy.verify().raw == raw
                    assert package.verify_member(copy._name, directory=False) == copy.verify().file
            assert list(child.iterdir()) == []
            hooks = create_readonly_empty_directory(package, 'hooks')
            with ReadOnlyEmptyDirectory(hooks, control_git_reader=token) as empty:
                assert empty.verify().file.is_directory
                assert list(hooks.iterdir()) == []
            with pytest.raises(PrivateRecordError, match='OPERATOR_ONLY'):
                PrivateRecordAppend(
                    package, uuid4().hex + '.git.json', b'{}', max_record_bytes=1024
                )
            with pytest.raises(packages.PackageSecurityError, match='OPERATOR_ONLY_PARENT'):
                packages.create_control_git_read_package(package, uuid4().hex, token)
            with pytest.raises(packages.PackageSecurityError, match='NEW_PRIVATE_PACKAGE_REQUIRED'):
                packages.create_control_git_read_package(parent, nonce, token)
        # Operator-only defaults still publish their real private record.
        with PrivateRecordAppend(
            parent, uuid4().hex + '.git.json', b'{}', max_record_bytes=1024
        ) as record:
            result = record.publish()
            assert result.byte_count == 2


def test_original_reader_exit_allows_static_verification_and_owned_copy_cleanup_but_no_new_grant(
    tmp_path, reader
):
    token, process, job = reader
    path = tmp_path / 'original.config'
    with path.open('xb') as stream:
        stream.write(b'[core]\n bare=false\n')
    parent_path = packages.create_private_package(tmp_path / 'operator-root')
    with packages.PrivatePackageGuard(parent_path) as parent:
        child = packages.create_control_git_read_package(parent, uuid4().hex, token)
        with packages.PrivatePackageGuard(child, control_git_reader=token) as package:
            with LockedConfigSource(path, max_file_bytes=4096) as source:
                copy = PrivateConfigCopy(source, package)
                hooks = create_readonly_empty_directory(package, 'hooks')
                with ReadOnlyEmptyDirectory(hooks, control_git_reader=token) as empty:
                    job.terminate_owned(1)
                    assert process._kernel.WaitForSingleObject(process._handle, 8000) == 0
                    assert empty.verify().file.is_directory
                    assert copy.verify().raw == b'[core]\n bare=false\n'
                    copy.close()
                    assert not copy._path.exists()
                    package.verify()
                    nonce = uuid4().hex
                    with pytest.raises(ControllerTokenError):
                        packages.create_control_git_read_package(parent, nonce, token)
                    assert not (parent_path / ('control-git-' + nonce)).exists()
                    with pytest.raises(ControllerTokenError):
                        create_readonly_empty_directory(package, 'late-hooks')
                    assert not (child / 'late-hooks').exists()


@pytest.mark.parametrize('value', [None, '..', 'A' * 32, 'a' * 31, str(uuid4())])
def test_pre_recorded_nonce_is_required_without_creating_or_repairing_any_child(
    tmp_path, reader, value
):
    token, _, _ = reader
    path = packages.create_private_package(tmp_path / 'operator-root')
    with packages.PrivatePackageGuard(path) as parent:
        with pytest.raises(packages.PackageSecurityError, match='NONCE_REQUIRED'):
            packages.create_control_git_read_package(parent, value, token)
        assert list(path.iterdir()) == []


@pytest.mark.parametrize('value', [None, {}, 'S-1-5-18', 1])
def test_reader_cannot_be_a_sid_handle_or_serialized_claim(tmp_path, value):
    path = packages.create_private_package(tmp_path / 'operator-root')
    with packages.PrivatePackageGuard(path) as parent:
        with pytest.raises(packages.PackageSecurityError, match='READER_REQUIRED'):
            packages.create_control_git_read_package(parent, uuid4().hex, value)
        assert list(path.iterdir()) == []


def test_replaced_parent_path_cannot_redirect_creation_away_from_original_file_identity(
    tmp_path, reader
):
    token, _, _ = reader
    first = packages.create_private_package(tmp_path / 'first')
    second = packages.create_private_package(tmp_path / 'second')
    with packages.PrivatePackageGuard(first) as parent:
        nonce = uuid4().hex
        parent.path = second
        try:
            with pytest.raises(packages.PackageSecurityError, match='PARENT_CHANGED'):
                packages.create_control_git_read_package(parent, nonce, token)
        finally:
            parent.path = first
        assert list(first.iterdir()) == list(second.iterdir()) == []
        parent.verify()


def test_actual_two_ace_descriptor_and_child_inheritance_reject_extra_write_or_default_open(
    tmp_path,
):
    path = packages.create_private_package(tmp_path / 'synthetic-read-role')
    sid = packages.current_operator_sid()
    test_only_set_dacl(path, packages._package_sddl(sid, UNASSIGNED_SID))
    directory = path / 'child'
    directory.mkdir()
    file = directory / 'sample'
    with file.open('xb') as stream:
        stream.write(b'fixed')
    packages._verify_acl(path, sid, protected=True, reader_sid=UNASSIGNED_SID)
    packages._verify_acl(directory, sid, protected=False, reader_sid=UNASSIGNED_SID)
    packages._verify_acl(file, sid, protected=False, reader_sid=UNASSIGNED_SID)
    with pytest.raises(packages.PackageSecurityError, match='ONLY_ALLOW_OPERATOR'):
        with packages.PrivatePackageGuard(path):
            pass
    wrong = packages._package_sddl(sid, UNASSIGNED_SID).replace('0x001200a9', '0x001200ab')
    test_only_set_dacl(path, wrong)
    with pytest.raises(packages.PackageSecurityError, match='READER_ACCESS_DIFFERS'):
        packages._verify_acl(path, sid, protected=True, reader_sid=UNASSIGNED_SID)


def test_actual_three_read_only_hook_aces_preserve_owner_rights_and_reject_a_missing_reader(
    tmp_path,
):
    parent = packages.create_private_package(tmp_path / 'hook-parent')
    target = parent / 'hooks'
    sid = packages.current_operator_sid()
    sddl = (
        'O:'
        + sid
        + 'D:P'
        + ''.join(
            '(A;;0x1200a9;;;' + principal + ')' for principal in (sid, 'S-1-3-4', UNASSIGNED_SID)
        )
    )
    kernel, security = packages._api()
    descriptor = wintypes.LPVOID()
    assert security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, 1, ctypes.byref(descriptor), None
    )
    try:
        attributes = packages.SecurityAttributes(
            ctypes.sizeof(packages.SecurityAttributes), descriptor, False
        )
        assert kernel.CreateDirectoryW('\\\\?\\' + str(target), ctypes.byref(attributes))
    finally:
        kernel.LocalFree(descriptor)
    _verify_security(target, sid, UNASSIGNED_SID)
    with pytest.raises(packages.PackageSecurityError, match='PROTECTED_DACL_REQUIRED'):
        _verify_security(target, sid)
