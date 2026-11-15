"""Real original NTFS worktree cohort; no user repository or Git execution."""

import ctypes
from dataclasses import replace
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.app.infrastructure import git_worktrees as metadata
from backend.app.infrastructure import windows_worktree_heads as heads
from backend.app.infrastructure.windows_config_source import ConfigReadError
from backend.app.infrastructure.windows_local_paths import PathBoundaryError
from backend.tests.requirements.test_v15_foundation import tmp_path

OID = 'a' * 40
OTHER = 'b' * 40
REF = 'refs/heads/main'


def write_new(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)


def listing_record(root, *, bare=False, detached=False, head=OID, ref=REF):
    fields = [b'worktree ' + str(root).replace('\\', '/').encode('utf-8')]
    if bare:
        fields.append(b'bare')
    else:
        fields.append(b'HEAD ' + head.encode('ascii'))
        fields.append(b'detached' if detached else b'branch ' + ref.encode('utf-8'))
    return b'\0'.join(fields) + b'\0\0'


def decoded(raw):
    return metadata.decode_worktrees(raw, format='sha1', query_exit_code=0, max_output_bytes=65536)


BRANCHES = metadata.decode_local_branches(
    REF.encode() + b'\0' + OID.encode() + b'\0commit\0\0\n',
    format='sha1',
    query_exit_code=0,
    max_output_bytes=65536,
)


@pytest.fixture
def cohort(tmp_path):
    root = tmp_path / 'main 工作区'
    common = root / '.git'
    linked = tmp_path / 'linked 工作区'
    admin = common / 'worktrees' / 'linked'
    private = tmp_path / 'private'
    private.mkdir()
    write_new(common / 'HEAD', b'ref: refs/heads/main\n')
    write_new(linked / '.git', ('gitdir: ' + str(admin) + '\n').encode('utf-8'))
    write_new(admin / 'commondir', b'../..\n')
    write_new(admin / 'gitdir', (str(linked / '.git') + '\n').encode('utf-8'))
    write_new(admin / 'HEAD', OID.encode() + b'\n')
    raw = listing_record(root) + listing_record(linked, detached=True)
    return root, common, linked, admin, private, decoded(raw)


def acquire(cohort, **changes):
    _, common, _, _, private, listing = cohort
    return heads.WorktreeHeadLease(
        changes.pop('listing', listing),
        changes.pop('branches', BRANCHES),
        common_directory=changes.pop('common_directory', common),
        private_roots=changes.pop('private_roots', (private,)),
        max_file_bytes=changes.pop('max_file_bytes', 4096),
        max_open_handles=changes.pop('max_open_handles', 4096),
        **changes,
    )


@pytest.mark.parametrize('format,length', [('sha1', 40), ('sha256', 64)])
def test_exact_head_grammar(format, length):
    assert heads.metadata_head(b'ref: refs/heads/topic\n', format=format) == (
        'BRANCH',
        'refs/heads/topic',
    )
    assert heads.metadata_head(b'a' * length + b'\r\n', format=format) == ('DETACHED', 'a' * length)
    assert heads.metadata_head(b'a' * length, format=format) == ('DETACHED', 'a' * length)


@pytest.mark.parametrize(
    'raw',
    [
        b'',
        b'0' * 40,
        b'A' * 40,
        b'a' * 39,
        b'a' * 64,
        b'a' * 40 + b' ',
        b'ref: HEAD\n',
        b'ref: refs/remotes/origin/main\n',
        b'ref: refs/heads/main\n\n',
        b'ref: refs/heads/main\0',
        b'ref: refs/heads/main\r',
        b'ref: refs/heads/.bad\n',
        b'\xff',
    ],
)
def test_unsupported_head_rejected(raw):
    with pytest.raises((heads.WorktreeHeadError, PathBoundaryError)):
        heads.metadata_head(raw, format='sha1')


@pytest.mark.parametrize(
    'raw', [None, '', bytearray(b'abc'), b'\n', b'\r\n', b'a\nb', b'a\rb', b'\xff', b'x\0']
)
def test_metadata_line_rejects_missing_multiline_and_invalid_bytes(raw):
    with pytest.raises(heads.WorktreeHeadError):
        heads.metadata_line(raw)


def test_pointers_are_exact_and_dot_segments_only_in_metadata():
    assert (
        str(heads.metadata_pointer(b'../..\n', base_directory=r'C:\repo\.git\worktrees\linked'))
        == r'C:\repo\.git'
    )
    assert (
        str(
            heads.metadata_pointer(
                'gitdir: ../原仓库/.git\r\n'.encode(), base_directory=r'C:\linked', gitfile=True
            )
        )
        == r'C:\原仓库\.git'
    )
    assert (
        str(heads.metadata_pointer(b'D:/repo/.git', base_directory=r'C:\linked')) == r'D:\repo\.git'
    )


@pytest.mark.parametrize(
    'text',
    [
        '',
        'gitdir:',
        'gitdir: ',
        'gitdir: \\\\host\\share',
        'gitdir: \\\\?\\C:\\repo',
        'gitdir: C:repo',
        'gitdir: \\root',
        'gitdir: bad./../repo',
        'gitdir: a:stream',
        'gitdir: NUL',
        'gitdir: foo\\\\bar',
        'gitdir: foo\\',
        'gitdir: foo\nsecond',
    ],
)
def test_unsafe_metadata_pointers_rejected_before_native_io(text):
    with patch.object(heads, 'read_api', side_effect=AssertionError('No IO')):
        with pytest.raises((heads.WorktreeHeadError, PathBoundaryError)):
            heads.metadata_pointer(text.encode(), base_directory=r'C:\base', gitfile=True)


@pytest.mark.parametrize(
    'name,value',
    [
        ('max_file_bytes', 0),
        ('max_file_bytes', False),
        ('max_file_bytes', 2**53),
        ('max_open_handles', 0),
        ('max_open_handles', None),
        ('max_open_handles', -1),
        ('private_roots', ()),
        ('private_roots', []),
    ],
)
def test_invalid_limits_and_private_scopes_fail_before_io(cohort, name, value):
    with patch.object(heads, 'read_api', side_effect=AssertionError('No IO')):
        with pytest.raises(heads.WorktreeHeadError):
            acquire(cohort, **{name: value})


def test_actual_main_linked_bidirectional_originals_and_stable_fingerprint(cohort):
    root, common, linked, admin, _, listing = cohort
    with acquire(cohort) as held:
        bindings = held.verify()
        assert len(bindings) == 2
        assert len(held.fingerprint_sha256) == 64
        assert held.verify_observation(listing, BRANCHES) == held.fingerprint_sha256
        assert {b.root.canonical_path for b in bindings} == {str(root), str(linked)}
        assert {b.git_directory.canonical_path for b in bindings} == {str(common), str(admin)}
        assert 'C:' not in repr(bindings) and str(root) not in repr(bindings)
        count = held._reserved
        for _ in range(3):
            assert held.verify() == bindings
        assert held._reserved == count, 'Absent metadata probes must not leak reservations'
        kernel = held._kernel
        writer = kernel.CreateFileW(str(admin / 'HEAD'), 0x40000000, 3, None, 3, 0, None)
        assert writer == ctypes.c_void_p(-1).value
        assert ctypes.get_last_error() in (32, 33)
        with pytest.raises(OSError):
            os.rename(linked, linked.with_name('moved'))
        fingerprint = held.fingerprint_sha256
    assert not held._directories and not held._sources and not held._probes
    with pytest.raises(heads.WorktreeHeadError, match='LEASE_CLOSED'):
        held.verify()
    with acquire(cohort) as reopened:
        assert reopened.fingerprint_sha256 == fingerprint


def test_bare_unborn_head_is_not_a_checked_out_branch(tmp_path):
    bare = tmp_path / 'bare.git'
    private = tmp_path / 'private'
    private.mkdir()
    write_new(bare / 'HEAD', b'ref: refs/heads/unborn\n')
    listing = decoded(listing_record(bare, bare=True))
    with heads.WorktreeHeadLease(
        listing,
        (),
        common_directory=bare,
        private_roots=(private,),
        max_file_bytes=4096,
        max_open_handles=512,
    ) as held:
        assert len(held.verify()) == 1


def test_main_gitfile_separate_git_dir_has_no_linked_backlink_requirement(tmp_path):
    root, common, private = (tmp_path / name for name in ('work', 'common.git', 'private'))
    private.mkdir()
    write_new(common / 'HEAD', b'ref: refs/heads/main\n')
    write_new(root / '.git', b'gitdir: ../common.git\n')
    listing = decoded(listing_record(root))
    with heads.WorktreeHeadLease(
        listing,
        BRANCHES,
        common_directory=common,
        private_roots=(private,),
        max_file_bytes=4096,
        max_open_handles=512,
    ) as held:
        assert len(held.verify()) == 1


@pytest.mark.parametrize(
    'part,raw',
    [
        ('HEAD', OTHER.encode() + b'\n'),
        ('commondir', b'../../other-common\n'),
        ('gitdir', b'C:/missing/.git\n'),
    ],
)
def test_linked_head_or_bidirectional_pointer_mismatch_rejects(cohort, part, raw):
    _, _, _, admin, _, _ = cohort
    path = admin / part
    path.unlink()  # Owned, inactive test fixture only.
    write_new(path, raw)
    with pytest.raises((heads.WorktreeHeadError, PathBoundaryError)):
        acquire(cohort)


def test_backlink_to_another_real_gitfile_rejected(cohort, tmp_path):
    _, _, _, admin, _, _ = cohort
    other = tmp_path / 'other' / '.git'
    write_new(other, ('gitdir: ' + str(admin) + '\n').encode())
    path = admin / 'gitdir'
    path.unlink()
    write_new(path, (str(other) + '\n').encode())
    with pytest.raises(heads.WorktreeHeadError, match='BACKLINK_DIFFERS'):
        acquire(cohort)


@pytest.mark.parametrize('location', ['common', 'linked'])
def test_config_worktree_is_not_silently_ignored(cohort, location):
    _, common, _, admin, _, _ = cohort
    write_new((common if location == 'common' else admin) / 'config.worktree', b'')
    with pytest.raises(heads.WorktreeHeadError, match='UNSUPPORTED_METADATA_PRESENT'):
        acquire(cohort)


def test_new_worktree_admin_or_optional_config_detected_while_held(cohort):
    _, common, _, admin, _, _ = cohort
    with acquire(cohort) as held:
        extra = common / 'worktrees' / 'unexpected'
        extra.mkdir()
        try:
            with pytest.raises(heads.WorktreeHeadError, match='COHORT_CHANGED'):
                held.verify()
        finally:
            extra.rmdir()
        write_new(admin / 'config.worktree', b'')
        with pytest.raises(heads.WorktreeHeadError, match='ABSENCE_CHANGED'):
            held.verify()
    with pytest.raises(heads.WorktreeHeadError, match='UNSUPPORTED_METADATA_PRESENT'):
        acquire(cohort)


def test_unlisted_admin_directory_blocks_even_when_listing_is_unchanged(cohort):
    _, common, _, _, _, _ = cohort
    (common / 'worktrees' / 'unlisted').mkdir()
    with pytest.raises(heads.WorktreeHeadError, match='COHORT_DIFFERS'):
        acquire(cohort)


@pytest.mark.parametrize('scope', ['ancestor', 'inside-main', 'inside-linked', 'same-main'])
def test_native_private_scope_overlap_rejects(cohort, scope):
    root, _, linked, _, _, _ = cohort
    paths = {
        'ancestor': root.parent,
        'inside-main': root / 'private',
        'inside-linked': linked / 'private',
        'same-main': root,
    }
    selected = paths[scope]
    selected.mkdir(exist_ok=True)
    with pytest.raises(heads.WorktreeHeadError, match='PRIVATE_SCOPE_OVERLAP'):
        acquire(cohort, private_roots=(selected,))


def test_handle_budget_precedes_any_directory_or_metadata_open(cohort):
    with patch.object(heads.LocalPathGuard, '__enter__', side_effect=AssertionError('No open')):
        with pytest.raises(heads.WorktreeHeadError, match='HANDLE_LIMIT_EXCEEDED'):
            acquire(cohort, max_open_handles=1)


def test_source_busy_does_not_close_original_caller_writer(cohort):
    _, _, _, admin, _, _ = cohort
    kernel = heads.read_api()
    writer = kernel.CreateFileW(str(admin / 'HEAD'), 0x40000000, 3, None, 3, 0, None)
    assert writer and writer != ctypes.c_void_p(-1).value
    try:
        with pytest.raises(ConfigReadError) as error:
            acquire(cohort)
        assert error.value.code == 'SOURCE_BUSY'
    finally:
        assert kernel.CloseHandle(writer)
    with acquire(cohort):
        pass


def test_fresh_git_snapshot_change_rejected_without_adopting_it(cohort):
    _, _, _, _, _, listing = cohort
    with acquire(cohort) as held:
        changed = replace(listing, listing_sha256='0' * 64)
        with pytest.raises(heads.WorktreeHeadError, match='GIT_OBSERVATION_CHANGED'):
            held.verify_observation(changed, BRANCHES)
        assert held.verify_observation(listing, BRANCHES) == held.fingerprint_sha256


def test_failed_data_close_keeps_all_original_ancestors_and_retries_same_owner(cohort):
    held = acquire(cohort)
    original = next(iter(held._sources.values()))
    try:
        with patch.object(original, 'close', side_effect=ConfigReadError('TEST_CLOSE_UNKNOWN')):
            with pytest.raises(ConfigReadError) as caught:
                held.close()
            assert caught.value.retained_owner is held
            assert held._directories and held._probes and held._sources
            with pytest.raises(heads.WorktreeHeadError, match='LEASE_CLOSED'):
                held.verify()
    finally:
        held.close()
    assert not held._directories and not held._probes and not held._sources


class KernelProxy:
    def __init__(self, kernel, **overrides):
        self.kernel, self.overrides = kernel, overrides

    def __getattr__(self, name):
        return self.overrides.get(name, getattr(self.kernel, name))


@pytest.mark.parametrize('flag', [0x40, 0x1000, 0x4000, 0x40000, 0x400000])
def test_metadata_attributes_rechecked_on_originals_after_acquisition(cohort, flag):
    held = acquire(cohort)
    kernel = held._kernel

    def attributes(handle, pointer):
        result = kernel.GetFileInformationByHandle(handle, pointer)
        ctypes.cast(pointer, ctypes.POINTER(heads.HandleInfo)).contents.attributes |= flag
        return result

    try:
        held._kernel = KernelProxy(kernel, GetFileInformationByHandle=attributes)
        with pytest.raises(heads.WorktreeHeadError, match='ATTRIBUTES_UNSUPPORTED'):
            held.verify()
    finally:
        held._kernel = kernel
        held.close()


@pytest.mark.parametrize('part', ['.git', 'HEAD', 'commondir', 'gitdir'])
def test_metadata_hardlinks_rejected_without_changing_any_original(cohort, tmp_path, part):
    _, _, linked, admin, _, _ = cohort
    original = linked / '.git' if part == '.git' else admin / part
    body = original.read_bytes()
    alias = tmp_path / ('extra-link-' + part.lstrip('.'))
    os.link(original, alias)
    with pytest.raises(PathBoundaryError, match='MULTIPLE_HARD_LINKS_REJECTED'):
        acquire(cohort)
    assert original.read_bytes() == alias.read_bytes() == body


def test_probe_close_failure_retains_original_handle_and_all_ancestors(cohort):
    held = acquire(cohort)
    kernel = held._kernel
    try:
        held._kernel = KernelProxy(kernel, CloseHandle=lambda handle: False)
        with pytest.raises(heads.WorktreeHeadError, match='CLOSE_UNVERIFIED') as caught:
            held.close()
        assert caught.value.retained_owner is held
        assert not held._sources and held._probes and held._directories
    finally:
        held._kernel = kernel
        held.close()


def test_directory_close_failure_retains_that_original_owner_for_retry(cohort):
    held = acquire(cohort)
    guard = list(held._directories.values())[-1]
    try:
        with patch.object(guard, 'close', side_effect=PathBoundaryError('TEST_CLOSE_UNKNOWN')):
            with pytest.raises(PathBoundaryError) as caught:
                held.close()
            assert caught.value.retained_owner is held
            assert not held._sources and not held._probes and held._directories
            assert guard in held._directories.values()
    finally:
        held.close()


def test_failed_probe_identity_and_cleanup_keep_original_owner(cohort):
    _, _, linked, _, _, _ = cohort
    kernel = heads.read_api()
    original_identity = heads._identity

    def identity(api, handle, path):
        if path == linked / '.git':
            raise heads.WorktreeHeadError('TEST_IDENTITY_UNKNOWN')
        return original_identity(api, handle, path)

    owner = None
    try:
        with (
            patch.object(heads, '_identity', side_effect=identity),
            patch.object(
                heads,
                'read_api',
                return_value=KernelProxy(kernel, CloseHandle=lambda handle: False),
            ),
        ):
            with pytest.raises(heads.WorktreeHeadError) as caught:
                acquire(cohort)
        owner = caught.value.retained_owner
        assert type(owner) is heads.WorktreeHeadLease
        assert any(value[1] is None for value in owner._probes.values())
        assert owner._directories
    finally:
        if owner is not None:
            owner._kernel = kernel
            owner.close()


def test_failed_inner_data_cleanup_remains_transitively_owned(cohort):
    from backend.app.infrastructure import windows_config_source as sources

    kernel = sources.read_api()
    wrapped = KernelProxy(kernel, ReadFile=lambda *args: False, CloseHandle=lambda handle: False)
    owner = None
    try:
        with patch.object(sources, 'read_api', return_value=wrapped):
            with pytest.raises(ConfigReadError) as caught:
                acquire(cohort)
        owner = caught.value.retained_owner
        assert type(owner) is heads.WorktreeHeadLease
        assert owner._sources and owner._directories and owner._probes
        assert all(source._handle is not None for source in owner._sources.values())
    finally:
        if owner is not None:
            for source in owner._sources.values():
                source._kernel = kernel
            owner.close()


def test_absent_admin_directory_becomes_present_is_a_change(tmp_path):
    bare, private = tmp_path / 'bare.git', tmp_path / 'private'
    private.mkdir()
    write_new(bare / 'HEAD', b'ref: refs/heads/unborn\n')
    with heads.WorktreeHeadLease(
        decoded(listing_record(bare, bare=True)),
        (),
        common_directory=bare,
        private_roots=(private,),
        max_file_bytes=4096,
        max_open_handles=512,
    ) as held:
        (bare / 'worktrees').mkdir()
        with pytest.raises(heads.WorktreeHeadError, match='ABSENCE_CHANGED'):
            held.verify()


def test_missing_listed_worktree_is_not_ignored(cohort):
    root, _, _, _, _, listing = cohort
    missing = decoded(listing_record(root) + listing_record(root.parent / 'missing', detached=True))
    with pytest.raises(PathBoundaryError):
        acquire(cohort, listing=missing)
    # Rejection released all our originals, so a new valid acquisition works.
    with acquire(cohort):
        pass
