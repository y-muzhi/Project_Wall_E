"""Retain a changed original task file before restoring sealed candidate bytes."""

import ctypes
import re
from dataclasses import asdict

from backend.app.shared.validation import strict_json_object

from .content_paths import materialized_path, relative_content_path
from .guard_task_files import _publish_original, _read_original
from .runtime_launch_journal import _bytes
from .windows_config_copy import _api as archive_api
from .windows_config_source import ConfigReadError, LockedFileSource
from .windows_local_paths import FileIdentity, LocalPathGuard, _identity, local_absolute_path
from .windows_private_record import rename_private_handle_no_replace
from .windows_task_workspace_tree import CandidateWorkspaceError, _verify_streams


class _MovableSource(LockedFileSource):
    def __init__(self, expected, size, checkpoint):
        self._initialize(expected.canonical_path, max(1, size), expected)
        self._kernel = archive_api()
        self._capture_raw, self._checkpoint = False, checkpoint
        try:
            self._handle = self._kernel.CreateFileW(
                '\\\\?\\' + str(self._path),
                0x80000000 | 0x10000,
                1,
                None,
                3,
                0x00200000 | 0x00100000 | 0x08000000,
                None,
            )
            if not self._handle or self._handle == ctypes.c_void_p(-1).value:
                self._handle = None
                raise CandidateWorkspaceError('SOURCE_BUSY')
            self._snapshot = self._read()
            _verify_streams(self._kernel, self._handle, directory=False)
        except BaseException:
            self.close()
            raise


def archive_changed_candidate_file(
    package, workspace, scratch, original, entry, key, checkpoint, publish
):
    root = local_absolute_path(workspace.canonical_path)
    scratch_path = local_absolute_path(scratch.canonical_path)
    path = local_absolute_path(original.canonical_path)
    target = local_absolute_path(materialized_path(scratch_path, '.walle-repair-' + key + '.saved'))
    if (
        scratch_path != root.with_name('scratch')
        or scratch.volume_serial != workspace.volume_serial
        or scratch.file_id == workspace.file_id
        or path != root.joinpath(*entry.path.split('/'))
    ):
        raise CandidateWorkspaceError('SOURCE_CHANGED')
    if re.fullmatch('[a-f0-9]{64}', key) is None:
        raise CandidateWorkspaceError('SOURCE_CHANGED')
    intent_name = key + '.task-repair-source-intent.json'
    ack_name = key + '.task-repair-source-ack.json'
    intent = _bytes(
        {
            'workspace': asdict(workspace),
            'scratch': asdict(scratch),
            'original': asdict(original),
            'entry': asdict(entry),
            'archive': str(target),
        }
    )
    with (
        LocalPathGuard(root, directory=True) as work_pin,
        LocalPathGuard(scratch_path, directory=True) as scratch_pin,
        LocalPathGuard(path.parent, directory=True),
    ):
        if work_pin.verify() != workspace or scratch_pin.verify() != scratch:
            raise CandidateWorkspaceError('SOURCE_CHANGED')
        # Once an original move might have happened, this file's action is
        # observation-only. A later repair is a different explicit operation.
        if _read_original(package, intent_name, 16384) is not None:
            raise CandidateWorkspaceError('SOURCE_CHANGED')
        try:
            with _MovableSource(original, entry.byte_count, checkpoint) as source:
                snapshot = source.snapshot
                if (snapshot.byte_count, snapshot.sha256) != (entry.byte_count, entry.sha256):
                    raise CandidateWorkspaceError('SOURCE_CHANGED')
                checkpoint()
                _publish_original(package, intent_name, intent, 16384)

                def move():
                    rename_private_handle_no_replace(source._kernel, source._handle, target)

                publish(move)
                archived = _identity(source._kernel, source._handle, target)
                if (archived.volume_serial, archived.file_id) != (
                    original.volume_serial,
                    original.file_id,
                ):
                    raise CandidateWorkspaceError('SOURCE_CHANGED')
                _verify_streams(source._kernel, source._handle, directory=False)
                _publish_original(
                    package,
                    ack_name,
                    _bytes(
                        {
                            'intent': intent.decode('utf-8'),
                            'archived': asdict(archived),
                        }
                    ),
                    32768,
                )
        except ConfigReadError as error:
            raise CandidateWorkspaceError(error.code) from error
    return archived


def observe_changed_candidate_archive(
    package, workspace, scratch, relative, key, checkpoint, *, expected_source=None
):
    """Recover only the original move receipt from its retained file identity."""
    relative_content_path(relative)
    if re.fullmatch('[a-f0-9]{64}', key) is None:
        raise CandidateWorkspaceError('SOURCE_CHANGED')
    intent_name = key + '.task-repair-source-intent.json'
    raw = _read_original(package, intent_name, 16384)
    if raw is None:
        return None
    value = strict_json_object(raw)
    if set(value) != {'workspace', 'scratch', 'original', 'entry', 'archive'}:
        raise CandidateWorkspaceError('SOURCE_CHANGED')
    try:
        original = FileIdentity(**value['original'])
    except (TypeError, ValueError) as error:
        raise CandidateWorkspaceError('SOURCE_CHANGED') from error
    if expected_source is not None and (
        value['original'] != expected_source['original']
        or value['entry'] != expected_source['entry']
    ):
        raise CandidateWorkspaceError('SOURCE_CHANGED')
    entry = value['entry']
    if (
        type(entry) is not dict
        or original.is_directory is not False
        or original.filesystem != 'NTFS'
    ):
        raise CandidateWorkspaceError('SOURCE_CHANGED')
    root = local_absolute_path(workspace.canonical_path)
    target = local_absolute_path(
        materialized_path(scratch.canonical_path, '.walle-repair-' + key + '.saved')
    )
    if (
        value['workspace'] != asdict(workspace)
        or value['scratch'] != asdict(scratch)
        or value['archive'] != str(target)
        or local_absolute_path(original.canonical_path) != root.joinpath(*relative.split('/'))
        or set(entry) != {'path', 'mode', 'byte_count', 'sha256'}
        or entry['path'] != relative
        or type(entry['byte_count']) is not int
        or entry['byte_count'] < 0
    ):
        raise CandidateWorkspaceError('SOURCE_CHANGED')
    checkpoint()
    try:
        with (
            LocalPathGuard(root, directory=True) as root_pin,
            LocalPathGuard(scratch.canonical_path, directory=True) as scratch_pin,
            LockedFileSource(
                target, max_file_bytes=max(1, entry['byte_count']), checkpoint=checkpoint
            ) as saved,
        ):
            if root_pin.verify() != workspace or scratch_pin.verify() != scratch:
                raise CandidateWorkspaceError('SOURCE_CHANGED')
            archived = saved.snapshot.file
            if (archived.volume_serial, archived.file_id) != (
                original.volume_serial,
                original.file_id,
            ) or (saved.snapshot.byte_count, saved.snapshot.sha256) != (
                entry['byte_count'],
                entry['sha256'],
            ):
                raise CandidateWorkspaceError('SOURCE_CHANGED')
            _verify_streams(saved._kernel, saved._handle, directory=False)
            ack = _bytes({'intent': raw.decode('utf-8'), 'archived': asdict(archived)})
            prior = _read_original(package, key + '.task-repair-source-ack.json', 32768)
            if prior is None:
                checkpoint()
                _publish_original(package, key + '.task-repair-source-ack.json', ack, 32768)
            elif prior != ack:
                raise CandidateWorkspaceError('SOURCE_CHANGED')
    except (ConfigReadError, OSError) as error:
        raise CandidateWorkspaceError('SOURCE_CHANGED') from error
    return archived
