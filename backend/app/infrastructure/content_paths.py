"""CONTENT20-STORE-1 logical paths, before any filesystem or Git object IO.

These checks do not replace native path/file identity guards. Inputs are never
normalized into a different path; aliases and file/directory conflicts fail.
"""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import PureWindowsPath

from .windows_local_paths import local_absolute_path

MAX_FULL_PATH_UTF16 = 240
_MODES = frozenset(('100644', '100755'))
_RESERVED = re.compile(r'CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³]', re.IGNORECASE)


class ContentPathError(ValueError):
    code = 'SOURCE_UNSUPPORTED'

    def __init__(self, reason):
        self.reason = reason
        # A source filename can contain sensitive text; never include it here.
        super().__init__(reason)


def relative_content_path(value):
    if type(value) is not str or not value:
        raise ContentPathError('RELATIVE_CONTENT_PATH_REQUIRED')
    try:
        value.encode('utf-8', errors='strict')
    except UnicodeError:
        raise ContentPathError('CONTENT_PATH_UNICODE_INVALID') from None
    if unicodedata.normalize('NFC', value) != value:
        raise ContentPathError('CONTENT_PATH_NOT_NFC')
    if (
        value.startswith('/')
        or '\\' in value
        or any(character in value for character in ':*?"<>|')
        or any(unicodedata.category(character) == 'Cc' for character in value)
    ):
        raise ContentPathError('CONTENT_PATH_COMPONENT_INVALID')
    parts = value.split('/')
    for part in parts:
        if (
            part in ('', '.', '..')
            or part.endswith(('.', ' '))
            or _RESERVED.fullmatch(part.split('.')[0].rstrip(' ')) is not None
            or part.casefold() == '.git'
        ):
            raise ContentPathError('CONTENT_PATH_COMPONENT_INVALID')
    return value


def content_file_mode(value):
    if type(value) is not str or value not in _MODES:
        raise ContentPathError('CONTENT_FILE_MODE_UNSUPPORTED')
    return value


def materialized_path(root, relative):
    relative_content_path(relative)
    absolute = local_absolute_path(root)
    final = PureWindowsPath(absolute).joinpath(*relative.split('/'))
    if len(str(final).encode('utf-16-le', errors='strict')) // 2 > MAX_FULL_PATH_UTF16:
        raise ContentPathError('CONTENT_FULL_PATH_TOO_LONG')
    return str(final)


@dataclass(frozen=True)
class ContentPathEntry:
    path: str
    mode: str


class ContentPathIndex:
    """One complete code tree, with implied parent directories and no dedup."""

    def __init__(self, *, materialization_root=None):
        self._root = (
            None if materialization_root is None else local_absolute_path(materialization_root)
        )
        self._names = {}
        self._files = {}

    def _register(self, path, final_kind):
        path = relative_content_path(path)
        if self._root is not None:
            materialized_path(self._root, path)
        parts = path.split('/')
        proposed = []
        for count in range(1, len(parts) + 1):
            spelling = '/'.join(parts[:count])
            kind = final_kind if count == len(parts) else 'DIRECTORY'
            key = spelling.casefold()
            existing = self._names.get(key)
            if existing is not None:
                old_spelling, old_kind = existing
                if old_spelling != spelling:
                    raise ContentPathError('CONTENT_PATH_CASE_ALIAS')
                if old_kind != kind:
                    raise ContentPathError('CONTENT_FILE_DIRECTORY_CONFLICT')
                if kind == 'FILE':
                    raise ContentPathError('CONTENT_PATH_DUPLICATE')
            proposed.append((key, spelling, kind))
        for key, spelling, kind in proposed:
            self._names[key] = (spelling, kind)
        return path

    def add_directory(self, path):
        # Namespace validation only; empty directories are not content entries.
        self._register(path, 'DIRECTORY')

    def add_file(self, path, mode):
        mode = content_file_mode(mode)
        path = self._register(path, 'FILE')
        entry = ContentPathEntry(path, mode)
        self._files[path] = entry
        return entry

    def without_files(self, entries):
        """Project verified file removals while retaining every other name."""
        result = ContentPathIndex(materialization_root=self._root)
        result._names = self._names.copy()
        result._files = self._files.copy()
        for entry in entries:
            if type(entry) is not ContentPathEntry or result._files.get(entry.path) != entry:
                raise ContentPathError('CONTENT_PATH_REMOVAL_DIFFERS')
            del result._files[entry.path]
            del result._names[entry.path.casefold()]
        return result

    def entries(self):
        return tuple(
            self._files[path] for path in sorted(self._files, key=lambda path: path.encode('utf-8'))
        )
