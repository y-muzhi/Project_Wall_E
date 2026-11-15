"""CONTENT20-STORE-1 new-file selection; tracked paths can never be hidden.

Pure namespace decisions only. A capture caller must supply the COMPLETE fixed
baseline and enumerate the actual quiet workspace; this does not prove either.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .content_paths import (
    ContentPathEntry,
    ContentPathError,
    ContentPathIndex,
    content_file_mode,
    relative_content_path,
)


@dataclass(frozen=True)
class _Rule:
    path: str
    directory: bool

    def matches(self, path, *, directory=False):
        if self.path == '.':
            return True
        candidate = path.split('/')
        original = self.path.split('/')
        for left, right in zip(candidate, original):
            if left.casefold() != right.casefold():
                return False
            if left != right:
                raise ContentPathError('CONTENT_SELECTION_CASE_ALIAS')
        if self.directory:
            return len(candidate) > len(original) or (directory and len(candidate) == len(original))
        return not directory and len(candidate) == len(original)


def _rules(values, *, include, namespace, seen):
    if type(values) is not list:
        raise ContentPathError('CONTENT_SELECTION_RULE_ARRAY_REQUIRED')
    result = []
    for value in values:
        if type(value) is not str:
            raise ContentPathError('CONTENT_SELECTION_RULE_REQUIRED')
        if value == '.' and include:
            rule = _Rule('.', True)
        else:
            directory = value.endswith('/')
            path = relative_content_path(value[:-1] if directory else value)
            rule = _Rule(path, directory)
        identity = (rule.path, rule.directory)
        if identity in seen:
            raise ContentPathError('CONTENT_SELECTION_RULE_DUPLICATE_OR_CONFLICT')
        if rule.path != '.':
            if rule.directory:
                namespace.add_directory(rule.path)
            else:
                namespace.add_file(rule.path, '100644')  # Namespace type, not a captured mode.
        seen.add(identity)
        result.append(rule)
    return tuple(result)


@dataclass(frozen=True, init=False)
class ContentSelection:
    _includes: tuple[_Rule, ...] = field(repr=False)
    _excludes: tuple[_Rule, ...] = field(repr=False)
    _tracked_modes: Mapping[str, str] = field(repr=False)
    new_file_mode: str

    def __init__(
        self,
        *,
        product_include_paths,
        nonproduct_exclude_paths,
        new_file_mode,
        baseline_entries,
    ):
        mode = content_file_mode(new_file_mode)
        namespace = ContentPathIndex()
        seen = set()
        includes = _rules(product_include_paths, include=True, namespace=namespace, seen=seen)
        excludes = _rules(nonproduct_exclude_paths, include=False, namespace=namespace, seen=seen)
        # A directory include may have deliberate nonproduct children. An exclude
        # ancestor may not silently erase an explicit child include.
        for included in includes:
            if included.path == '.':
                continue
            if any(
                excluded.directory
                and (
                    included.path == excluded.path or included.path.startswith(excluded.path + '/')
                )
                for excluded in excludes
            ):
                raise ContentPathError('CONTENT_SELECTION_INCLUDE_SHADOWED')

        if type(baseline_entries) not in (list, tuple):
            raise ContentPathError('CONTENT_SELECTION_COMPLETE_BASELINE_REQUIRED')
        baseline = ContentPathIndex()
        modes = {}
        for entry in baseline_entries:
            if type(entry) is not ContentPathEntry:
                raise ContentPathError('CONTENT_SELECTION_BASELINE_ENTRY_REQUIRED')
            baseline.add_file(entry.path, entry.mode)
            # Visit every rule: an earlier match cannot hide an alias/conflict.
            for rule in includes:
                rule.matches(entry.path)
            excluded = [rule.matches(entry.path) for rule in excludes]
            if any(excluded):
                raise ContentPathError('CONTENT_SELECTION_EXCLUDES_TRACKED_PATH')
            modes[entry.path] = entry.mode
        object.__setattr__(self, '_includes', includes)
        object.__setattr__(self, '_excludes', excludes)
        object.__setattr__(self, '_tracked_modes', MappingProxyType(modes))
        object.__setattr__(self, 'new_file_mode', mode)

    def _matches(self, path, *, directory):
        path = relative_content_path(path)
        included = [rule.matches(path, directory=directory) for rule in self._includes]
        excluded = [rule.matches(path, directory=directory) for rule in self._excludes]
        return path, any(included), any(excluded)

    def file(self, path):
        """Actual enumerated ordinary file -> original mode entry or excluded.

        Callers still validate the final selected tree using ContentPathIndex;
        no body is opened and no absence/deletion is inferred here.
        """
        path, included, excluded = self._matches(path, directory=False)
        if path in self._tracked_modes:
            if excluded:
                raise ContentPathError('CONTENT_SELECTION_EXCLUDES_TRACKED_PATH')
            return ContentPathEntry(path, self._tracked_modes[path])
        if included and not excluded:
            return ContentPathEntry(path, self.new_file_mode)
        return None

    def prune_directory(self, path):
        """Only an explicit excluded directory prunes traversal, never include gaps."""
        _, _, excluded = self._matches(path, directory=True)
        return excluded
