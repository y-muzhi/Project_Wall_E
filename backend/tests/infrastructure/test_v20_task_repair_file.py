from dataclasses import replace

import pytest

from backend.app.infrastructure.windows_local_paths import LocalPathGuard
from backend.app.infrastructure.windows_task_repair_file import publish_missing_candidate_file
from backend.app.infrastructure.windows_task_workspace_tree import CandidateWorkspaceError


@pytest.mark.parametrize('case', ['publish', 'race', 'fenced', 'parent-replaced'])
def test_restore_file_publishes_only_by_original_ntfs_handle(tmp_path, case):
    workspace = tmp_path / 'workspace'
    parent = workspace / 'nested'
    parent.mkdir(parents=True)
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    with (
        LocalPathGuard(workspace, directory=True) as work_pin,
        LocalPathGuard(parent, directory=True) as parent_pin,
        LocalPathGuard(scratch, directory=True) as scratch_pin,
    ):
        work_id, parent_id, scratch_id = (
            work_pin.verify(),
            parent_pin.verify(),
            scratch_pin.verify(),
        )
    if case == 'parent-replaced':
        parent_id = replace(parent_id, file_id='0' * 32)
    target = parent / 'source.txt'

    class Stopped(Exception):
        pass

    def fenced_rename(rename):
        assert len(list(scratch.iterdir())) == 1
        if case == 'fenced':
            raise Stopped
        if case == 'race':
            with target.open('xb') as file:
                file.write(b'concurrent contents')
        rename()

    def restore():
        publish_missing_candidate_file(
            work_id,
            scratch_id,
            parent_id,
            'nested/source.txt',
            b'from seal',
            lambda: None,
            fenced_rename,
        )

    if case == 'publish':
        restore()
        assert target.read_bytes() == b'from seal'
    elif case == 'race':
        with pytest.raises(CandidateWorkspaceError, match='SOURCE_CHANGED'):
            restore()
        assert target.read_bytes() == b'concurrent contents'
    else:
        expected = Stopped if case == 'fenced' else CandidateWorkspaceError
        with pytest.raises(expected):
            restore()
        assert not target.exists()
    assert not list(scratch.iterdir())


@pytest.mark.parametrize('case', ['archive', 'changed', 'fenced', 'busy', 'move-unknown'])
def test_changed_file_archive_retains_original_bytes_and_obeys_fence(tmp_path, case):
    import hashlib

    from backend.app.infrastructure.windows_config_source import LockedFileSource
    from backend.app.infrastructure.windows_private_package import (
        PrivatePackageGuard,
        create_private_package,
    )
    from backend.app.infrastructure.windows_task_repair_archive import (
        archive_changed_candidate_file,
        observe_changed_candidate_archive,
    )
    from backend.app.infrastructure.windows_task_workspace_tree import CandidateWorkspaceEntry

    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    path = workspace / 'source.txt'
    raw = b'original changed bytes'
    with path.open('xb') as file:
        file.write(raw)
    with (
        LocalPathGuard(workspace, directory=True) as root,
        LocalPathGuard(scratch, directory=True) as temporary,
        LocalPathGuard(path, directory=False) as file,
    ):
        identities = root.verify(), temporary.verify(), file.verify()
    entry = CandidateWorkspaceEntry(
        'source.txt', '100644', len(raw), hashlib.sha256(raw).hexdigest()
    )
    if case == 'changed':
        with path.open('ab') as file:
            file.write(b'later')

    class Fenced(Exception):
        pass

    def publish(move):
        if case == 'fenced':
            raise Fenced
        move()
        if case == 'move-unknown':
            raise Fenced

    package_path = create_private_package(tmp_path / 'records')
    with PrivatePackageGuard(package_path) as records:

        def archive():
            return archive_changed_candidate_file(
                records, *identities, entry, 'a' * 64, lambda: None, publish
            )

        if case == 'archive':
            result = archive()
            retained = scratch / ('.walle-repair-' + 'a' * 64 + '.saved')
            assert not path.exists() and retained.read_bytes() == raw
            assert result.file_id == identities[2].file_id
            assert (package_path / ('a' * 64 + '.task-repair-source-ack.json')).is_file()
        elif case == 'move-unknown':
            with pytest.raises(Fenced):
                archive()
            retained = scratch / ('.walle-repair-' + 'a' * 64 + '.saved')
            assert not path.exists() and retained.read_bytes() == raw
            with pytest.raises(CandidateWorkspaceError):
                archive()
            assert retained.read_bytes() == raw
            assert not (package_path / ('a' * 64 + '.task-repair-source-ack.json')).exists()
            recovered = observe_changed_candidate_archive(
                records,
                identities[0],
                identities[1],
                'source.txt',
                'a' * 64,
                lambda: None,
            )
            assert recovered.file_id == identities[2].file_id
            assert (
                observe_changed_candidate_archive(
                    records,
                    identities[0],
                    identities[1],
                    'source.txt',
                    'a' * 64,
                    lambda: None,
                )
                == recovered
            )
            with retained.open('ab') as tamper:
                tamper.write(b'changed archive')
            with pytest.raises(CandidateWorkspaceError):
                observe_changed_candidate_archive(
                    records,
                    identities[0],
                    identities[1],
                    'source.txt',
                    'a' * 64,
                    lambda: None,
                )

        elif case == 'busy':
            with LockedFileSource(path, max_file_bytes=100):
                with pytest.raises(CandidateWorkspaceError):
                    archive()
            assert path.read_bytes() == raw
        else:
            with pytest.raises(Fenced if case == 'fenced' else CandidateWorkspaceError):
                archive()
            assert path.read_bytes() == raw + (b'later' if case == 'changed' else b'')
            assert not list(scratch.iterdir())
