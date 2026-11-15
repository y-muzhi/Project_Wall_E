"""Fix all retained source files before the first repair workspace mutation."""

import hashlib
import re
from dataclasses import asdict

from backend.app.infrastructure.content_paths import ContentPathIndex
from backend.app.infrastructure.guard_task_files import _publish_original, _read_original
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.windows_local_paths import local_absolute_path
from backend.app.infrastructure.windows_task_workspace_tree import CandidateWorkspaceError
from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_json_object


class RepairSourcePlan:
    def __init__(self, parent, operation_id, binding, manifest_sha256, limit):
        self.parent = parent
        self.binding = {
            'operation_id': operation_id,
            'candidate_id': binding.candidate_id,
            'manifest_sha256': manifest_sha256,
        }
        self.limit = limit
        digest = hashlib.sha256(canonical_input(self.binding).encode('utf-8')).hexdigest()
        self.name = digest + '.task-repair-plan.json'

    def archive_key(self, path):
        return hashlib.sha256(
            canonical_input(
                {
                    'operation_id': self.binding['operation_id'],
                    'candidate_id': self.binding['candidate_id'],
                    'path': path,
                }
            ).encode('utf-8')
        ).hexdigest()

    def read(self):
        raw = _read_original(self.parent, self.name, self.limit)
        if raw is None:
            return None
        value = strict_json_object(raw)
        if (
            set(value) != {'binding', 'files'}
            or canonical_input(value['binding']) != canonical_input(self.binding)
            or type(value['files']) is not list
            or not value['files']
            or canonical_input(value).encode('utf-8') != raw
        ):
            raise CandidateWorkspaceError('SOURCE_CHANGED')
        namespace = ContentPathIndex()
        paths = []
        for row in value['files']:
            if type(row) is not dict or set(row) != {'entry', 'original'}:
                raise CandidateWorkspaceError('SOURCE_CHANGED')
            entry = row['entry']
            if type(entry) is not dict or set(entry) != {'path', 'mode', 'byte_count', 'sha256'}:
                raise CandidateWorkspaceError('SOURCE_CHANGED')
            original = row['original']
            if (
                type(entry['byte_count']) is not int
                or not 0 <= entry['byte_count'] <= MAX_SAFE_INTEGER
                or type(entry['sha256']) is not str
                or re.fullmatch('[a-f0-9]{64}', entry['sha256']) is None
                or type(original) is not dict
                or set(original)
                != {'canonical_path', 'volume_serial', 'file_id', 'is_directory', 'filesystem'}
                or original['is_directory'] is not False
                or original['filesystem'] != 'NTFS'
            ):
                raise CandidateWorkspaceError('SOURCE_CHANGED')
            for field, size in (('volume_serial', 16), ('file_id', 32)):
                if (
                    type(original[field]) is not str
                    or re.fullmatch('[a-f0-9]{' + str(size) + '}', original[field]) is None
                ):
                    raise CandidateWorkspaceError('SOURCE_CHANGED')
            local_absolute_path(original['canonical_path'])
            namespace.add_file(entry['path'], entry['mode'])
            paths.append(entry['path'])
        if paths != sorted(paths, key=lambda path: path.encode('utf-8')):
            raise CandidateWorkspaceError('SOURCE_CHANGED')
        return value

    def fix(self, files, previous):
        value = {
            'binding': self.binding,
            'files': [
                {'entry': asdict(entry), 'original': asdict(original)} for entry, original in files
            ],
        }
        if previous is not None:
            return previous
        if not files:
            return None
        _publish_original(
            self.parent, self.name, canonical_input(value).encode('utf-8'), self.limit
        )
        return self.read()

    def pending(self, value, observed, current):
        if value is None:
            return current
        pending = {
            row['entry']['path']: row
            for row in value['files']
            if row['entry']['path'] not in observed
        }
        actual = {
            entry.path: {'entry': asdict(entry), 'original': asdict(original)}
            for entry, original in current
        }
        if pending != actual:
            raise CandidateWorkspaceError('SOURCE_CHANGED')
        return current
