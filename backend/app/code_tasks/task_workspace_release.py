"""Release the backend copy of the original stopped workspace, by original file IDs."""

import hashlib
import re
from dataclasses import asdict

from backend.app.infrastructure.guard_task_files import _publish_original, _read_original
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.app.infrastructure.windows_local_paths import FileIdentity
from backend.app.infrastructure.windows_private_package import PrivatePackageGuard
from backend.app.infrastructure.windows_task_directory_release import (
    OwnedTreeDeletion,
    OwnedTreeEntry,
)
from backend.app.shared.validation import strict_json_object

_PLAN_LIMIT = 64 * 1024 * 1024
_ACK_LIMIT = 4096


def _absent(path):
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    return False


class OriginalWorkspaceRelease:
    def __init__(self, package, original, operation_id, guard_ref):
        key = original.workspace_key
        if (
            type(package) is not PrivatePackageGuard
            or package.is_control_git_read_package
            or re.fullmatch('working-[a-f0-9]{32}', key) is None
            or package.verify() != original.workspace_parent
            or package.path / key != OwnedTreeDeletion.path(original.workspace_root)
        ):
            raise TaskExecutionError('ORIGINAL_TASK_WORKSPACE_RELEASE_SCOPE_DIFFERS')
        self._package, self._original = package, original
        self._root = package.path / key
        self._stage = package.path / ('staging-' + key[8:])
        self._prefix = key[8:] + '.workspace-release-'
        self._deletion = OwnedTreeDeletion(original.workspace_parent)
        self._scope = {
            'schema_version': 1,
            'operation_id': operation_id,
            'original': original.scope(),
            'guard_cleanup_sha256': guard_ref,
            'workspace_key': key,
        }

    def _read(self, kind, limit):
        return _read_original(self._package, self._prefix + kind + '.json', limit)

    def _append(self, kind, raw, limit):
        _publish_original(self._package, self._prefix + kind + '.json', raw, limit)
        if self._read(kind, limit) != raw:
            raise TaskExecutionError('ORIGINAL_TASK_WORKSPACE_RELEASE_RECEIPT_DIFFERS')

    def _checkpoint(self, checkpoint):
        checkpoint()
        if self._package.verify() != self._original.workspace_parent or not _absent(self._stage):
            raise TaskExecutionError('ORIGINAL_TASK_WORKSPACE_RELEASE_SCOPE_CHANGED')

    def _load_plan(self, intent):
        record = strict_json_object(intent)
        raw_entries = record.pop('entries', None)
        if record != self._scope or type(raw_entries) is not list or not raw_entries:
            raise TaskExecutionError('ORIGINAL_TASK_WORKSPACE_RELEASE_PLAN_DIFFERS')
        entries = tuple(
            OwnedTreeEntry(FileIdentity(**row['file']), FileIdentity(**row['parent']))
            for row in raw_entries
        )
        if entries[-1] != OwnedTreeEntry(
            self._original.workspace_root, self._original.workspace_parent
        ):
            raise TaskExecutionError('ORIGINAL_TASK_WORKSPACE_RELEASE_ROOT_DIFFERS')
        known = {self._root: entries[-1].file}
        for entry in reversed(entries[:-1]):
            path, parent = self._deletion.path(entry.file), self._deletion.path(entry.parent)
            if (
                path in known
                or not path.is_relative_to(self._root)
                or parent != path.parent
                or known.get(parent) != entry.parent
                or not entry.parent.is_directory
            ):
                raise TaskExecutionError('ORIGINAL_TASK_WORKSPACE_RELEASE_PLAN_DIFFERS')
            known[path] = entry.file
        if intent != _bytes({**self._scope, 'entries': [asdict(entry) for entry in entries]}):
            raise TaskExecutionError('ORIGINAL_TASK_WORKSPACE_RELEASE_PLAN_DIFFERS')
        return entries

    def close(self):
        self._deletion.close()

    def release(self, checkpoint):
        def checked():
            self._checkpoint(checkpoint)

        checked()
        intent = self._read('intent', _PLAN_LIMIT)
        ack = self._read('ack', _ACK_LIMIT)
        if intent is None:
            if ack is not None or _absent(self._root):
                raise TaskExecutionError('ORIGINAL_TASK_WORKSPACE_RELEASE_PROOF_REQUIRED')
            entries = self._deletion.inventory(self._original.workspace_root, checked)
            intent = _bytes({**self._scope, 'entries': [asdict(entry) for entry in entries]})
            checked()
            self._append('intent', intent, _PLAN_LIMIT)
        else:
            entries = self._load_plan(intent)
        result = _bytes(
            {
                **self._scope,
                'intent_sha256': hashlib.sha256(intent).hexdigest(),
                'released_entry_count': len(entries),
            }
        )
        if ack is not None and (ack != result or not _absent(self._root)):
            raise TaskExecutionError('ORIGINAL_TASK_WORKSPACE_RELEASE_RECEIPT_DIFFERS')
        if ack is None:
            for entry in entries:
                checked()
                if self._deletion.is_pending(entry) or not _absent(self._deletion.path(entry.file)):
                    self._deletion.delete(entry, checked)
            checked()
            if not _absent(self._root):
                raise TaskExecutionError('ORIGINAL_TASK_WORKSPACE_RELEASE_UNVERIFIED')
            self._append('ack', result, _ACK_LIMIT)
        checked()
        if not _absent(self._root):
            raise TaskExecutionError('ORIGINAL_TASK_WORKSPACE_RELEASE_UNVERIFIED')
        return hashlib.sha256(result).hexdigest()
