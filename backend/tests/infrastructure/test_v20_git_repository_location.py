"""Original NTFS location discovery only, before full Git admission/commands."""

import ctypes
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.app.infrastructure.git_repository_location import (
    RepositoryLocationLease,
    RepositoryLocationError,
)
from backend.app.infrastructure.windows_config_source import ConfigReadError
from backend.app.infrastructure.windows_local_paths import PathBoundaryError
from backend.app.infrastructure.windows_private_package import (
    create_private_package,
    PrivatePackageGuard,
)
from backend.app.infrastructure.windows_config_copy import PrivateConfigCopy
from backend.app.infrastructure.git_config_command import ConfigParseCommand
from backend.app.infrastructure.windows_config_source import LockedConfigSource
from backend.tests.infrastructure.test_v20_windows_worktree_heads import (
    cohort,
    write_new,
    KernelProxy,
)
from backend.tests.requirements.test_v15_foundation import tmp_path


@pytest.fixture
def layout(cohort):
    root, common, linked, admin, private, _ = cohort
    (common / 'objects' / 'pack').mkdir(parents=True)
    (common / 'refs').mkdir()
    write_new(
        common / 'config',
        b'[core]\n repositoryformatversion=0\n bare=false\n[user]\n name=PRIVATE_LOCATION_VALUE\n',
    )
    return SimpleNamespace(root=root, common=common, linked=linked, admin=admin, private=private)


def acquire(layout, root=None, **changes):
    return RepositoryLocationLease(
        root or layout.root,
        private_roots=changes.pop('private_roots', (layout.private,)),
        max_file_bytes=changes.pop('max_file_bytes', 4096),
        max_open_handles=changes.pop('max_open_handles', 4096),
        max_metadata_entries=changes.pop('max_metadata_entries', 4096),
        **changes,
    )


@pytest.mark.parametrize('kind', ['main', 'linked'])
def test_original_main_linked_location_and_private_config_are_stable(layout, kind):
    selected = layout.linked if kind == 'linked' else layout.root
    with acquire(layout, selected) as held:
        facts = held.verify()
        assert Path(facts.root.canonical_path) == selected
        assert Path(facts.common_directory.canonical_path) == layout.common
        assert Path(facts.git_directory.canonical_path) == (
            layout.admin if kind == 'linked' else layout.common
        )
        assert facts.linked == (kind == 'linked') and not facts.expected_bare
        assert held.config_source.snapshot.sha256 == facts.config_sha256
        assert b'PRIVATE_LOCATION_VALUE' in held.config_source.snapshot.raw
        assert 'PRIVATE_LOCATION_VALUE' not in repr(facts)
        original = facts.fingerprint_sha256
        assert len(original) == 64
        with held.hold() as borrowed:
            assert borrowed == facts
            with pytest.raises(RepositoryLocationError, match='IN_USE'):
                held.close()
            assert held.verify() == facts
    with acquire(layout, selected) as fresh:
        assert fresh.verify().fingerprint_sha256 == original


def test_real_bare_candidate_does_not_claim_a_complete_git_history(tmp_path):
    root = tmp_path / 'bare.git'
    private = tmp_path / 'private'
    private.mkdir()
    write_new(root / 'config', b'[core]\n repositoryformatversion=0\n bare=true\n')
    write_new(root / 'HEAD', b'ref: refs/heads/main\n')
    (root / 'objects').mkdir()
    (root / 'refs').mkdir()
    with RepositoryLocationLease(
        root,
        private_roots=(private,),
        max_file_bytes=4096,
        max_open_handles=4096,
        max_metadata_entries=4096,
    ) as held:
        facts = held.verify()
        assert facts.expected_bare and not facts.linked
        assert facts.root == facts.git_directory == facts.common_directory
        assert not hasattr(facts, 'admitted')


def test_separate_main_gitdir_has_no_linked_backlink_requirement(layout, tmp_path):
    source = tmp_path / 'separate-main'
    write_new(source / '.git', ('gitdir: ' + str(layout.common) + '\n').encode())
    with acquire(layout, source) as held:
        facts = held.verify()
        assert not facts.linked and Path(facts.common_directory.canonical_path) == layout.common


@pytest.mark.parametrize(
    'relative',
    [
        'shallow',
        'info/grafts',
        'refs/replace',
        'reftable',
        'objects/info/alternates',
        'objects/info/http-alternates',
        'config.worktree',
    ],
)
def test_initial_unsupported_metadata_is_rejected_without_repair(layout, relative):
    target = layout.common / relative
    write_new(target, b'original unsupported marker\n')
    before = target.read_bytes()
    with pytest.raises(RepositoryLocationError, match='UNSUPPORTED_METADATA_PRESENT'):
        acquire(layout)
    assert target.read_bytes() == before


def test_linked_worktree_private_config_is_not_silently_ignored(layout):
    write_new(layout.admin / 'config.worktree', b'[core]\n bare=false\n')
    with pytest.raises(RepositoryLocationError, match='UNSUPPORTED_METADATA_PRESENT'):
        acquire(layout, layout.linked)


@pytest.mark.parametrize('name', ['pack-a.promisor', 'pack-b.PROMISOR'])
def test_promisor_marker_rejected_even_when_config_itself_is_inert(layout, name):
    write_new(layout.common / 'objects/pack' / name, b'')
    with pytest.raises(RepositoryLocationError, match='PROMISOR_PACK'):
        acquire(layout)


@pytest.mark.parametrize('part', ['commondir', 'gitdir'])
def test_wrong_linked_pointer_or_backlink_cannot_change_original_repo_identity(
    layout, tmp_path, part
):
    target = layout.admin / part
    target.unlink()
    if part == 'commondir':
        write_new(target, b'.\n')
    else:
        other = tmp_path / 'different-worktree' / '.git'
        write_new(other, ('gitdir: ' + str(layout.admin) + '\n').encode())
        write_new(target, (str(other) + '\n').encode())
    with pytest.raises(RepositoryLocationError):
        acquire(layout, layout.linked)


def test_absence_and_pack_cohort_changes_are_source_changes(layout):
    with acquire(layout) as held:
        write_new(layout.common / 'shallow', b'')
        with pytest.raises(RepositoryLocationError) as error:
            held.verify()
        assert error.value.code == 'SOURCE_CHANGED'
        (layout.common / 'shallow').unlink()
        assert held.verify()
        write_new(layout.common / 'objects/pack/pack-new.idx', b'fixture')
        with pytest.raises(RepositoryLocationError, match='PACK_LIST_CHANGED') as error:
            held.verify()
        assert error.value.code == 'SOURCE_CHANGED'


@pytest.mark.parametrize(
    'name,value',
    [
        ('max_file_bytes', 0),
        ('max_file_bytes', True),
        ('max_open_handles', -1),
        ('max_metadata_entries', True),
        ('private_roots', ()),
        ('private_roots', []),
    ],
)
def test_bad_limits_and_missing_private_scopes_precede_native_acquisition(layout, name, value):
    with patch(
        'backend.app.infrastructure.git_repository_location.read_api',
        side_effect=AssertionError('No native acquisition'),
    ):
        with pytest.raises(RepositoryLocationError):
            acquire(layout, **{name: value})


def test_handle_budget_is_checked_before_original_directory_open(layout):
    with patch(
        'backend.app.infrastructure.git_repository_location.LocalPathGuard',
        side_effect=AssertionError('No over-budget open'),
    ):
        with pytest.raises(RepositoryLocationError, match='HANDLE_LIMIT_EXCEEDED'):
            acquire(layout, max_open_handles=1)


def test_private_source_overlap_and_small_file_bound_reject(layout):
    with pytest.raises(RepositoryLocationError, match='PRIVATE_SCOPE_OVERLAP'):
        acquire(layout, private_roots=(layout.root,))
    with pytest.raises(ConfigReadError, match='BYTES_EXCEEDED'):
        acquire(layout, max_file_bytes=4)


def test_shared_writer_is_busy_and_is_not_closed_or_modified(layout):
    original = (layout.common / 'config').read_bytes()
    with (layout.common / 'config').open('rb+') as writer:
        with pytest.raises(ConfigReadError) as error:
            acquire(layout)
        assert error.value.code == 'SOURCE_BUSY' and not writer.closed
    assert (layout.common / 'config').read_bytes() == original


def test_failed_data_close_keeps_all_original_ancestor_owners_for_retry(layout):
    held = acquire(layout)
    original = held.config_source
    try:
        with patch.object(
            original, 'close', side_effect=ConfigReadError('FIXTURE_CLOSE_UNVERIFIED')
        ):
            with pytest.raises(ConfigReadError) as error:
                held.close()
            assert error.value.retained_owner is held
            assert held._paths and held._sources
            with pytest.raises(RepositoryLocationError, match='CLOSED'):
                held.verify()
    finally:
        held.close()
    assert not held._paths and not held._sources


@pytest.mark.parametrize('flag', [0x40, 0x1000, 0x4000, 0x40000])
def test_metadata_attributes_are_rechecked_on_held_originals(layout, flag):
    from backend.app.infrastructure.windows_local_paths import HandleInfo

    held = acquire(layout)
    kernel = held._kernel

    def attributes(handle, pointer):
        result = kernel.GetFileInformationByHandle(handle, pointer)
        ctypes.cast(pointer, ctypes.POINTER(HandleInfo)).contents.attributes |= flag
        return result

    try:
        held._kernel = KernelProxy(kernel, GetFileInformationByHandle=attributes)
        with pytest.raises(RepositoryLocationError, match='ATTRIBUTES_UNSUPPORTED'):
            held.verify()
    finally:
        held._kernel = kernel
        held.close()


def test_location_source_is_reused_by_existing_private_config_command(layout, tmp_path):
    package = create_private_package(tmp_path / 'parse-private')
    empty = package / 'empty'
    empty.open('xb').close()
    with (
        acquire(layout) as held,
        held.hold(),
        PrivatePackageGuard(package) as private,
        LockedConfigSource(empty, max_file_bytes=4096) as global_config,
    ):
        with PrivateConfigCopy(held.config_source, private) as copied:
            command = ConfigParseCommand(copied, global_config)
            try:
                assert command.facts()['source']['sha256'] == held.verify().config_sha256
                assert command.arguments()[0] == 'config'
            finally:
                command.close()


def test_actual_fixed_git_sha1_sha256_main_linked_bare_and_separate_locations(tmp_path):
    import json
    from time import monotonic, sleep
    from uuid import uuid4
    from backend.app.infrastructure.git_bundle import verify_bundle_bytes
    from backend.app.infrastructure.windows_job import OwnedJob
    from backend.app.infrastructure.windows_process import ObservedProcess
    from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot

    assert verify_bundle_bytes()[0] == 375
    root = Path(__file__).resolve().parents[3]
    nonce = uuid4().hex
    with (tmp_path / '.location-owner').open('x', encoding='ascii') as stream:
        stream.write(nonce)
    worker = root / 'backend/tests/infrastructure/v20_repository_location_worker.py'
    code = '\n'.join(
        [
            'import runpy,sys',
            'sys.path.insert(0,' + repr(str(root)) + ')',
            'sys.argv=' + repr([str(worker), str(tmp_path), nonce]),
            'runpy.run_path(' + repr(str(worker)) + ',run_name="__main__")',
        ]
    )
    job = OwnedJob(active_process_limit=16, job_memory_limit_bytes=512 * 1024 * 1024)
    process = None
    try:
        process = TestSuspendedRoot(job, tmp_path, code)
        process.resume()
        with ObservedProcess(process.pid) as observed:
            deadline = monotonic() + 45
            while observed.observe().state == 'RUNNING' and monotonic() < deadline:
                sleep(0.01)
            final = observed.observe()
            assert final.state == 'EXITED'
        raw = (tmp_path / 'location-result.json').read_bytes()
        assert len(raw) <= 8192
        result = json.loads(raw)
        assert result['run_nonce'] == nonce
        assert result['completed'], (result.get('failed_step'), result.get('failure_kind'))
        assert final.exit_code == 0
        assert result['layouts'] == [
            {'format': format, 'kind': kind, 'config_verified': True}
            for format in ('sha1', 'sha256')
            for kind in ('MAIN', 'LINKED', 'BARE', 'SEPARATE')
        ]
    finally:
        job.terminate_owned(1)
        if process is not None:
            assert job._kernel.WaitForSingleObject(process.info.process, 8000) == 0
        deadline = monotonic() + 8
        while job.observe_members().process_ids and monotonic() < deadline:
            sleep(0.01)
        assert job.observe_members().complete and not job.observe_members().process_ids
        if process is not None:
            process.close()
        job.close()


def test_pack_listing_has_its_own_entry_budget(layout):
    write_new(layout.common / 'objects/pack/one.idx', b'')
    write_new(layout.common / 'objects/pack/two.idx', b'')
    with pytest.raises(RepositoryLocationError, match='PACK_LIST_LIMIT'):
        acquire(layout, max_metadata_entries=1)
