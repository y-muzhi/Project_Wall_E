"""Actual effective controller rights, with no changes to system ACLs or owners."""

import ctypes
from ctypes import wintypes
from pathlib import Path
import stat
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.app.infrastructure import windows_access_check as access
from backend.app.infrastructure.windows_controller_token import ControllerPrimaryToken
from backend.app.infrastructure.windows_local_paths import LocalPathGuard, FileIdentity
from backend.tests.infrastructure.test_v20_windows_controller_token import (
    ordinary_controller,
    controller,
)
from backend.tests.requirements.test_v15_foundation import tmp_path


class ApiProxy:
    def __init__(self, original, **changes):
        self.original, self.changes = original, changes

    def __getattr__(self, key):
        return self.changes[key] if key in self.changes else getattr(self.original, key)


@pytest.fixture
def query(ordinary_controller):
    source, _ = ordinary_controller
    with ControllerPrimaryToken(source, expected=source.identity) as original:
        with access.ControllerAccessQuery(original) as evaluator:
            yield evaluator


@pytest.fixture
def owned_file(tmp_path):
    path = tmp_path / 'owned-access.txt'
    with path.open('xb') as stream:
        stream.write(b'owned read-only access fixture')
    return path


@pytest.mark.parametrize('value', [None, 1, {}, False, 'token'])
def test_raw_pid_token_claim_or_serialized_value_is_not_an_access_token(value):
    with patch.object(access, '_api', side_effect=AssertionError('No native token')):
        with pytest.raises(access.NativeAccessError, match='ORIGINAL_CONTROLLER'):
            access.ControllerAccessQuery(value)


@pytest.mark.parametrize(
    'role,mask,directory',
    [
        ('FILE', 0x2, False),
        ('FILE', 0x4, False),
        ('FILE', 0x10000, False),
        ('FILE', 0x40000, False),
        ('FILE', 0x80000, False),
        ('PACKAGE_DIRECTORY', 0x40, True),
        ('PACKAGE_DIRECTORY', 0x2, True),
        ('ANCESTOR', 0x40, True),
        ('ANCESTOR', 0x40000, True),
    ],
)
def test_write_delete_parent_delete_acl_and_owner_rights_are_independent_rejections(
    role, mask, directory
):
    facts = access.ControllerAccess(
        FileIdentity(r'C:\fixed', '1' * 16, 'a' * 32, directory, 'NTFS'),
        'S-1-5-21-1',
        'S-1-5-18',
        'a' * 64,
        mask,
    )
    with pytest.raises(access.NativeAccessError, match='CAN_MUTATE'):
        access.require_controller_read_only(facts, role=role)


def test_directory_role_and_unknown_fact_types_do_not_become_approval():
    facts = access.ControllerAccess(
        FileIdentity(r'C:\fixed', '1' * 16, 'a' * 32, True, 'NTFS'),
        'S-1-5-21-1',
        'S-1-5-18',
        'a' * 64,
        0x1200A9,
    )
    with pytest.raises(access.NativeAccessError, match='ROLE_DIFFERS'):
        access.require_controller_read_only(facts, role='FILE')
    with pytest.raises(access.NativeAccessError):
        access.require_controller_read_only(None, role='FILE')


def test_real_query_binds_original_owner_file_descriptor_and_does_not_impersonate(
    query, owned_file
):
    with LocalPathGuard(owned_file, directory=False) as guard:
        facts = query.query(guard)
        assert facts.file == guard.identity
        assert facts.controller_user_sid == query._controller.identity.user_sid
        assert facts.owner_sid == facts.controller_user_sid
        assert len(facts.descriptor_sha256) == 64
        assert facts.granted_access & 0x40000  # owner may rewrite the DACL
        assert query._files == [] and query._descriptors == []
        with pytest.raises(access.NativeAccessError, match='CAN_MUTATE'):
            access.require_controller_read_only(facts, role='FILE')
    # Existing production helper rejects an actually impersonating thread; query
    # successfully returning here also used the original controller lease.
    with query._controller.creation_handle():
        assert query._token is not None


def test_read_only_file_attribute_cannot_hide_owner_dacl_rewrite_right(query, owned_file):
    owned_file.chmod(stat.S_IREAD)
    try:
        with LocalPathGuard(owned_file, directory=False) as guard:
            facts = query.query(guard)
            assert facts.granted_access & 0x40000
            with pytest.raises(access.NativeAccessError, match='CAN_MUTATE'):
                access.require_controller_read_only(facts, role='FILE')
    finally:
        owned_file.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_existing_program_files_directory_has_real_effective_read_only_rights(query):
    # Read-only observation of the existing OS directory, no ownership/ACL change.
    target = Path(r'C:\Program Files')
    with LocalPathGuard(target, directory=True) as guard:
        facts = query.query(guard)
        assert access.require_controller_read_only(facts, role='PACKAGE_DIRECTORY') == facts
        assert access.require_controller_read_only(facts, role='ANCESTOR') == facts
        assert facts.granted_access & 0x1  # list/read permission exists


def test_existing_chrome_image_is_only_a_read_only_acl_vector_not_a_runtime_dependency(query):
    target = Path(r'C:\Program Files\Google\Chrome\Application\chrome.exe')
    with LocalPathGuard(target, directory=False) as guard:
        facts = query.query(guard)
        assert access.require_controller_read_only(facts, role='FILE') == facts
        assert facts.owner_sid != facts.controller_user_sid
    # No Chrome execution, package adoption or backend program authentication.


def test_unknown_access_check_cleans_original_file_and_descriptor_without_a_fact(query, owned_file):
    security = query._security
    query._security = ApiProxy(security, AccessCheck=lambda *args: False)
    try:
        with LocalPathGuard(owned_file, directory=False) as guard:
            with pytest.raises(access.NativeAccessError, match='EFFECTIVE_ACCESS_UNAVAILABLE'):
                query.query(guard)
    finally:
        query._security = security
    assert query._files == [] and query._descriptors == []


@pytest.mark.parametrize('mask,status,size', [(0x10000000, 1, 8), (1, 0, 8), (0, 1, 0)])
def test_invalid_native_grant_or_output_shape_fails_closed(query, owned_file, mask, status, size):
    security = query._security

    def invalid(*args):
        ctypes.cast(args[5], ctypes.POINTER(wintypes.DWORD)).contents.value = size
        ctypes.cast(args[6], ctypes.POINTER(wintypes.DWORD)).contents.value = mask
        ctypes.cast(args[7], ctypes.POINTER(wintypes.BOOL)).contents.value = status
        return True

    query._security = ApiProxy(security, AccessCheck=invalid)
    try:
        with LocalPathGuard(owned_file, directory=False) as guard:
            with pytest.raises(access.NativeAccessError, match='EFFECTIVE_ACCESS_INVALID'):
                query.query(guard)
    finally:
        query._security = security
    assert not query._files and not query._descriptors


def test_failed_query_token_close_retains_the_exact_token_until_cleanup(query, owned_file):
    kernel = query._kernel
    token = query._token
    query._kernel = ApiProxy(kernel, CloseHandle=lambda handle: False)
    try:
        with pytest.raises(access.NativeAccessError, match='CLOSE_UNVERIFIED') as caught:
            query.close()
        assert caught.value.retained_owner is query and query._token == token
        with LocalPathGuard(owned_file, directory=False) as guard:
            with pytest.raises(access.NativeAccessError, match='QUERY_CLOSED'):
                query.query(guard)
    finally:
        query._kernel = kernel
        query.close()


def test_failed_security_descriptor_free_is_retained_not_dropped(query, owned_file):
    kernel = query._kernel

    def free(pointer):
        value = getattr(pointer, 'value', pointer)
        if value in query._descriptors:
            return value
        return kernel.LocalFree(pointer)

    query._kernel = ApiProxy(kernel, LocalFree=free)
    try:
        with LocalPathGuard(owned_file, directory=False) as guard:
            with pytest.raises(access.NativeAccessError, match='FREE_UNVERIFIED') as caught:
                query.query(guard)
        assert caught.value.retained_owner is query
        assert len(query._descriptors) == 1 and not query._files
    finally:
        query._kernel = kernel
        query.close()
    assert query._descriptors == [] and query._token is None
