"""Real NTFS candidate source custody and fixed path selection."""

import hashlib
from time import monotonic

import pytest

from backend.app.infrastructure.content_manifest import ContentLimits
from backend.app.infrastructure.content_paths import ContentPathEntry
from backend.app.infrastructure.content_secret_policy import (
    REFERENCE,
    SecretRestricted,
    load_secret_policy,
)
from backend.app.infrastructure.content_selection import ContentSelection
from backend.app.infrastructure.git_commit_closure import GitClosureError
from backend.app.infrastructure.windows_local_paths import LocalPathGuard
from backend.app.infrastructure.windows_task_workspace_tree import (
    CandidateWorkspaceError,
    CandidateWorkspaceLimits,
    hold_candidate_workspace,
)
from backend.tests.requirements.test_v15_foundation import tmp_path


def write(path, value):
    with path.open('xb') as file:
        file.write(value)


@pytest.fixture
def source(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'src').mkdir()
    (workspace / 'generated').mkdir()
    write(workspace / 'entry.sh', b'#!/bin/sh\n')
    write(workspace / 'src' / 'new.txt', b'new\r\nbytes\x00')
    write(workspace / 'generated' / '.env', b'not selected')
    write(workspace / 'omitted.txt', b'outside new file include')
    selection = ContentSelection(
        product_include_paths=['src/'],
        nonproduct_exclude_paths=['generated/'],
        new_file_mode='100644',
        baseline_entries=[
            ContentPathEntry('entry.sh', '100755'),
            ContentPathEntry('deleted.txt', '100644'),
        ],
    )
    with LocalPathGuard(workspace, directory=True) as guard:
        original = guard.verify()
    return workspace, original, selection


def candidate(source, *, quiescent=lambda: None, files=4):
    workspace, original, selection = source
    return hold_candidate_workspace(
        workspace,
        original,
        selection=selection,
        secret_policy=load_secret_policy(REFERENCE),
        limits=CandidateWorkspaceLimits(ContentLimits(64, 128, files, 4096), 32, 256, 8),
        quiescent=quiescent,
        started_at=monotonic(),
    )


def test_source_holds_selected_file_and_excludes_untracked_outputs(source):
    workspace, _, _ = source
    with candidate(source) as locked:
        assert [(item.path, item.mode) for item in locked.entries] == [
            ('entry.sh', '100755'),
            ('src/new.txt', '100644'),
        ]
        for item in locked.entries:
            raw = locked.read(item)
            assert hashlib.sha256(raw).hexdigest() == item.sha256
            assert item.byte_count == len(raw)
        assert locked.read(locked.entries[1]) == b'new\r\nbytes\x00'
        with pytest.raises(OSError), (workspace / 'entry.sh').open('ab'):
            raise AssertionError('A selected candidate file still allows a writer')
        locked.verify()
    with pytest.raises(CandidateWorkspaceError, match='SOURCE_CHANGED'):
        locked.read(locked.entries[0])
    with (workspace / 'entry.sh').open('ab') as file:
        file.write(b'after closing the original read lease')


@pytest.mark.parametrize(
    'mode', ['changed', 'secret', 'write-lease', 'limit', 'fenced', 'omitted-read']
)
def test_source_fails_without_complete_locked_evidence(source, mode):
    workspace, _, _ = source
    quiescent = (lambda: True) if mode == 'fenced' else (lambda: None)
    if mode == 'secret':
        write(workspace / 'src' / 'secret.txt', b'-----BEGIN PRIVATE KEY-----')
    if mode == 'write-lease':
        with (
            (workspace / 'entry.sh').open('ab'),
            pytest.raises(CandidateWorkspaceError, match='SOURCE_BUSY'),
        ):
            with candidate(source):
                raise AssertionError('Source captured while writable')
        return
    errors = {
        'changed': 'SOURCE_CHANGED',
        'secret': 'SECRET_RESTRICTED',
        'limit': 'SOURCE_UNSUPPORTED',
        'fenced': 'WRITER_ACTIVE',
        'omitted-read': 'CONTENT_NOT_READY',
    }
    with pytest.raises((CandidateWorkspaceError, SecretRestricted), match=errors[mode]):
        with candidate(source, quiescent=quiescent, files=1 if mode == 'limit' else 4) as locked:
            for item in locked.entries:
                if mode != 'omitted-read':
                    locked.read(item)
            if mode == 'changed':
                write(workspace / 'src' / 'newer.txt', b'new after the original scan')


def test_source_rejects_lfs_pointer(source):
    workspace, _, _ = source
    write(
        workspace / 'src' / 'pointer.txt',
        b'version https://git-lfs.github.com/spec/v1\noid sha256:' + b'a' * 64 + b'\nsize 12\n',
    )
    with pytest.raises(GitClosureError, match='CONTENT_LFS_POINTER_UNSUPPORTED'):
        with hold_candidate_workspace(
            workspace,
            source[1],
            selection=source[2],
            secret_policy=load_secret_policy(REFERENCE),
            limits=CandidateWorkspaceLimits(ContentLimits(256, 512, 4, 4096), 32, 256, 8),
            quiescent=lambda: None,
            started_at=monotonic(),
        ) as locked:
            for item in locked.entries:
                locked.read(item)
