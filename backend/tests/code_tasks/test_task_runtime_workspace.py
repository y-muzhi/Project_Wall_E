"""Real source receipts and Guard workspace role, with one-shot runtime publication."""

import hashlib
from dataclasses import asdict
from uuid import uuid4

import pytest

from backend.app.code_tasks.repository_baseline_query import BaselineQueryResult
from backend.app.code_tasks.task_runtime_workspace import publish_runtime_workspace
from backend.app.code_tasks.task_start_workspace import WorkspaceAllocation
from backend.app.code_tasks.workspace_materialization import (
    FixedWorkspaceStage,
    WorkspaceMaterializationError,
)
from backend.app.infrastructure.content_manifest import ContentEntry
from backend.app.infrastructure.guard_action_journal import GuardActionJournal
from backend.app.infrastructure.guard_controller_binding import GuardControllerBinding
from backend.app.infrastructure.guard_request_header import _parse
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal
from backend.app.infrastructure.windows_controller_token import ControllerPrimaryToken
from backend.app.infrastructure.windows_local_paths import LocalDirectoryPin
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.infrastructure.windows_private_record import PrivateRecordAppend
from backend.app.infrastructure.windows_task_directories import TaskLpacDirectories, TaskRuntimeRoot
from backend.tests.infrastructure.test_v20_guard_action_journal import packet
from backend.tests.infrastructure.test_v20_windows_controller_token import (
    controller,
    ordinary_controller,
)
from backend.tests.requirements.test_v15_foundation import tmp_path


LIMITS = {'max_snapshot_files': 8, 'max_file_bytes': 512, 'max_snapshot_bytes': 1024}
PAYLOADS = {'src/first.py': b'print(1)\r\n', 'src/empty.txt': b'', 'README.md': b'\xff'}


def _original_workspace(parent):
    allocation = WorkspaceAllocation(17, 3, 4, 5, 6, uuid4().hex, parent.verify())
    stage = FixedWorkspaceStage(parent, allocation.nonce, lambda: None)
    entries = []
    for path, raw in sorted(PAYLOADS.items()):
        entry = ContentEntry(path, '100644', 'a' * 40, len(raw), hashlib.sha256(raw).hexdigest())
        stage.consume(entry, raw)
        entries.append(entry)
    source = stage.publish(
        BaselineQueryResult({'id': allocation.snapshot_id}, tuple(entries)), lambda: None
    )
    tree = canonical_input({'entries': [asdict(entry) for entry in source.entries]}).encode('utf-8')
    name = allocation.nonce + '.workspace-tree.json'
    with PrivateRecordAppend(parent, name, tree, max_record_bytes=16384) as manifest:
        record = asdict(manifest.publish())
    receipt = canonical_input(
        {
            'workspace_id': allocation.workspace_id,
            'directory': asdict(source.directory),
            'content_sha256': record['sha256'],
            'tree_record': record,
        }
    )
    return allocation, receipt


@pytest.fixture
def allocated_runtime(tmp_path, ordinary_controller):
    process, _ = ordinary_controller
    binding = GuardControllerBinding(uuid4().hex + uuid4().hex, str(uuid4()), process.identity)
    with (
        ControllerPrimaryToken(process, expected=binding.controller) as token,
        PrivatePackageGuard(create_private_package(tmp_path / 'source')) as parent,
        LaunchJournal(create_private_package(tmp_path / 'guard')) as journal,
        LocalDirectoryPin(tmp_path) as base,
        TaskRuntimeRoot.create(base, binding.controller.user_sid) as runtime_root,
    ):
        allocation, receipt = _original_workspace(parent)
        actions = GuardActionJournal(journal)
        prepare = packet(binding, number=allocation.operation_id, action_input={'run_kind': 'TASK'})
        prepare = _parse({**prepare.wire, 'step_no': 4}, binding)
        owner = TaskLpacDirectories(
            runtime_root, actions, actions.begin(prepare), prepare, binding, token
        )
        try:
            owner.allocate(cancelled=lambda: False)
            yield (
                parent,
                allocation,
                receipt,
                owner.workspace_destination(),
                owner.root / 'workspace',
            )
        finally:
            owner.close()


def test_publishes_fixed_bytes_once_and_checks_original_receipt(allocated_runtime):
    parent, allocation, receipt, destination, target = allocated_runtime
    result = publish_runtime_workspace(
        parent, allocation, receipt, destination, lambda: None, LIMITS
    )
    assert result == publish_runtime_workspace(
        parent, allocation, receipt, destination, lambda: None, LIMITS
    )
    assert all((target / path).read_bytes() == raw for path, raw in PAYLOADS.items())
    assert all(
        (parent.path / allocation.key / path).read_bytes() == raw for path, raw in PAYLOADS.items()
    )
    assert set(path.name for path in parent.path.glob('*.runtime-workspace*.json')) == {
        allocation.nonce + '.runtime-workspace-intent.json',
        allocation.nonce + '.runtime-workspace.json',
    }
    file = target / 'README.md'
    displaced = target / 'original'
    file.rename(displaced)
    file.write_bytes(PAYLOADS['README.md'])
    displaced.unlink()
    with pytest.raises(WorkspaceMaterializationError, match='RECEIPT_DIFFERS'):
        publish_runtime_workspace(parent, allocation, receipt, destination, lambda: None, LIMITS)
    assert file.read_bytes() == PAYLOADS['README.md']


def test_interrupted_publication_does_not_resume_writing(allocated_runtime):
    parent, allocation, receipt, destination, target = allocated_runtime

    def check_stop():
        if any(path.is_file() for path in target.rglob('*')):
            raise WorkspaceMaterializationError('fixture stop')

    with pytest.raises(WorkspaceMaterializationError, match='fixture stop'):
        publish_runtime_workspace(parent, allocation, receipt, destination, check_stop, LIMITS)
    partial = {
        path.relative_to(target): path.read_bytes() for path in target.rglob('*') if path.is_file()
    }
    assert len(partial) == 1
    with pytest.raises(WorkspaceMaterializationError, match='OUTCOME_UNVERIFIED'):
        publish_runtime_workspace(parent, allocation, receipt, destination, lambda: None, LIMITS)
    assert {
        path.relative_to(target): path.read_bytes() for path in target.rglob('*') if path.is_file()
    } == partial
    assert not list(parent.path.glob('*.runtime-workspace.json'))


def test_nonempty_target_cannot_be_adopted(allocated_runtime):
    parent, allocation, receipt, destination, target = allocated_runtime
    existing = target / 'README.md'
    existing.write_bytes(b'already present')
    with pytest.raises(WorkspaceMaterializationError, match='TARGET_NOT_EMPTY'):
        publish_runtime_workspace(parent, allocation, receipt, destination, lambda: None, LIMITS)
    assert existing.read_bytes() == b'already present'
    assert not list(parent.path.glob('*.runtime-workspace*.json'))


def test_guard_observes_default_stream_and_rejects_named_ntfs_stream(tmp_path):
    from backend.app.infrastructure.windows_local_paths import LocalPathGuard
    from backend.app.infrastructure.windows_task_workspace_lease import WorkspaceWriteError
    from backend.app.infrastructure.windows_task_workspace_tree import observe_task_workspace_tree

    path = tmp_path / 'owned-task-workspace'
    path.mkdir()
    file = path / 'sample.txt'
    file.write_bytes(b'original')
    with LocalPathGuard(path, directory=True) as guard:
        identity = guard.verify()
    checkpoint = lambda: None
    original = observe_task_workspace_tree(path, identity, checkpoint)
    stream = file.with_name(file.name + ':fixture')
    stream.write_bytes(b'temporary named stream')
    try:
        with pytest.raises(WorkspaceWriteError, match='ALTERNATE_STREAM_UNSUPPORTED'):
            observe_task_workspace_tree(path, identity, checkpoint)
    finally:
        stream.unlink()
    assert observe_task_workspace_tree(path, identity, checkpoint) == original


def test_launch_tree_retains_original_ntfs_reads_and_rechecks_directory_inventory(tmp_path):
    from backend.app.infrastructure.windows_local_paths import LocalPathGuard
    from backend.app.infrastructure.windows_task_workspace_lease import WorkspaceWriteError
    from backend.app.infrastructure.windows_task_workspace_tree import (
        hold_task_workspace_tree,
        observe_task_workspace_tree,
    )

    path = tmp_path / 'owned-launch-workspace'
    path.mkdir()
    file = path / 'existing.txt'
    file.write_bytes(b'original')
    with LocalPathGuard(path, directory=True) as guard:
        identity = guard.verify()

    def checkpoint():
        pass

    original = observe_task_workspace_tree(path, identity, checkpoint)
    with hold_task_workspace_tree(path, identity, original, checkpoint) as held:
        assert held == original
        with pytest.raises(OSError):
            file.open('wb').close()
        with pytest.raises(OSError):
            file.rename(path / 'renamed.txt')
    extra = path / 'late.txt'
    with pytest.raises(WorkspaceWriteError, match='LAUNCH_TREE_DIFFERS'):
        with hold_task_workspace_tree(path, identity, original, checkpoint):
            extra.write_bytes(b'late fixture')
    extra.unlink()
    with file.open('r+b') as stream:
        assert stream.read() == b'original'
