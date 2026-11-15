"""Real private source plan across an interrupted multi-file repair."""

import hashlib
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.app.code_tasks.task_repair_source_plan import RepairSourcePlan
from backend.app.infrastructure.windows_local_paths import LocalPathGuard
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.infrastructure.windows_task_repair_archive import (
    archive_changed_candidate_file,
    observe_changed_candidate_archive,
)
from backend.app.infrastructure.windows_task_workspace_tree import (
    CandidateWorkspaceEntry,
    CandidateWorkspaceError,
)
from backend.tests.requirements.test_v15_foundation import tmp_path  # noqa: F401


def test_interrupted_plan_keeps_extra_file_and_only_allows_original_remaining_sources(tmp_path):  # noqa: F811
    workspace = tmp_path / 'workspace'
    scratch = tmp_path / 'scratch'
    workspace.mkdir()
    scratch.mkdir()
    sources = []
    for name, raw in [('a-extra.txt', b'extra bytes'), ('b-changed.txt', b'changed bytes')]:
        path = workspace / name
        with path.open('xb') as stream:
            stream.write(raw)
        with LocalPathGuard(path, directory=False) as pin:
            original = pin.verify()
        sources.append(
            (
                CandidateWorkspaceEntry(name, '100644', len(raw), hashlib.sha256(raw).hexdigest()),
                original,
            )
        )
    with (
        LocalPathGuard(workspace, directory=True) as work,
        LocalPathGuard(scratch, directory=True) as temporary,
        PrivatePackageGuard(create_private_package(tmp_path / 'private')) as package,
    ):
        work_id, scratch_id = work.verify(), temporary.verify()
        plan = RepairSourcePlan(package, 81, SimpleNamespace(candidate_id=27), 'c' * 64, 32768)
        saved = plan.fix(sources, None)
        first, first_id = sources[0]

        class Interrupted(Exception):
            pass

        def uncertain_move(move):
            move()
            raise Interrupted

        with pytest.raises(Interrupted):
            archive_changed_candidate_file(
                package,
                work_id,
                scratch_id,
                first_id,
                first,
                plan.archive_key(first.path),
                lambda: None,
                uncertain_move,
            )
        assert not (workspace / first.path).exists()
        resumed = RepairSourcePlan(package, 81, SimpleNamespace(candidate_id=27), 'c' * 64, 32768)
        assert resumed.read() == saved
        recovered = observe_changed_candidate_archive(
            package,
            work_id,
            scratch_id,
            first.path,
            resumed.archive_key(first.path),
            lambda: None,
            expected_source=saved['files'][0],
        )
        assert recovered.file_id == first_id.file_id
        pending = sources[1:]
        assert resumed.pending(saved, {first.path}, pending) == pending
        changed, original = pending[0]
        with pytest.raises(CandidateWorkspaceError):
            resumed.pending(saved, {first.path}, [(replace(changed, sha256='0' * 64), original)])
        with pytest.raises(CandidateWorkspaceError):
            resumed.pending(saved, {first.path}, [])
        with pytest.raises(CandidateWorkspaceError):
            resumed.pending(saved, {first.path}, [(changed, replace(original, file_id='0' * 32))])
        with pytest.raises(CandidateWorkspaceError, match='SOURCE_CHANGED'):
            observe_changed_candidate_archive(
                package,
                work_id,
                scratch_id,
                first.path,
                resumed.archive_key(first.path),
                lambda: None,
                expected_source=saved['files'][1],
            )
        # A different original operation cannot acquire this restoration plan.
        other = RepairSourcePlan(package, 82, SimpleNamespace(candidate_id=27), 'c' * 64, 32768)
        assert other.read() is None and other.archive_key(first.path) != plan.archive_key(
            first.path
        )


@pytest.mark.parametrize(
    'invalid',
    [
        'boolean-size',
        'negative-size',
        'bad-digest',
        'missing-identity',
        'directory',
        'bad-file-id',
        'numeric-binding',
    ],
)
def test_malformed_private_source_plan_cannot_authorize_a_move(monkeypatch, invalid):
    from backend.app.code_tasks import task_repair_source_plan
    from backend.app.infrastructure.idempotency import canonical_input

    plan = RepairSourcePlan(None, 81, SimpleNamespace(candidate_id=27), 'c' * 64, 32768)
    value = {
        'binding': plan.binding,
        'files': [
            {
                'entry': {'path': 'src.txt', 'mode': '100644', 'byte_count': 1, 'sha256': 'a' * 64},
                'original': {
                    'canonical_path': 'C:\\fixed\\workspace\\src.txt',
                    'volume_serial': '1' * 16,
                    'file_id': '2' * 32,
                    'is_directory': False,
                    'filesystem': 'NTFS',
                },
            }
        ],
    }
    raw = canonical_input(value).encode('utf-8')
    monkeypatch.setattr(task_repair_source_plan, '_read_original', lambda *args: raw)
    assert plan.read() == value
    damaged = deepcopy(value)
    row = damaged['files'][0]
    if invalid == 'boolean-size':
        row['entry']['byte_count'] = True
    elif invalid == 'negative-size':
        row['entry']['byte_count'] = -1
    elif invalid == 'bad-digest':
        row['entry']['sha256'] = 'unverified'
    elif invalid == 'missing-identity':
        row['original'] = None
    elif invalid == 'directory':
        row['original']['is_directory'] = True
    elif invalid == 'numeric-binding':
        damaged['binding']['operation_id'] = 81.0
    else:
        row['original']['file_id'] = 'unverified'
    raw = canonical_input(damaged).encode('utf-8')
    with pytest.raises(CandidateWorkspaceError, match='SOURCE_CHANGED'):
        plan.read()
