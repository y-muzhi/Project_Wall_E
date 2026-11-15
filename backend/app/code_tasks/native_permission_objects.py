"""Private checks for concrete files in the original Coding workspace."""

from contextlib import contextmanager
import ntpath

from backend.app.infrastructure.content_paths import (
    ContentPathError,
    materialized_path,
    relative_content_path,
)
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.windows_local_paths import (
    LocalPathGuard,
    PathBoundaryError,
    local_absolute_path,
)


def workspace_relative_path(value):
    if type(value) is not str or not value or len(value) > 4096:
        return None
    try:
        return relative_content_path(value.replace('\\', '/'))
    except ContentPathError:
        return None


def permission_object_refs(original):
    name, patterns, metadata = original['permission'], original['patterns'], original['metadata']
    if len(patterns) != 1 or (
        (name == 'read' and metadata)
        or (name == 'edit' and type(metadata.get('filepath')) is not str)
        or name not in ('read', 'edit')
    ):
        return []
    path = workspace_relative_path(patterns[0])
    return [] if path is None else [{'kind': 'WORKSPACE_PATH', 'path': path}]


def usable_workspace_refs(value):
    return (
        type(value) is list
        and len(value) == 1
        and type(value[0]) is dict
        and set(value[0]) == {'kind', 'path'}
        and value[0]['kind'] == 'WORKSPACE_PATH'
        and type(value[0]['path']) is str
        and workspace_relative_path(value[0]['path']) == value[0]['path']
    )


@contextmanager
def pin_permission_object(control, workspace, original, checkpoint, *, timeout_ms):
    refs = permission_object_refs(original)
    if not refs:
        raise TaskExecutionError('ORIGINAL_PERMISSION_OBJECT_UNVERIFIED')
    try:
        expected = materialized_path(workspace.canonical_path, refs[0]['path'])
        if original['permission'] == 'edit':
            actual = str(local_absolute_path(original['metadata']['filepath']))
            if ntpath.normcase(actual) != ntpath.normcase(expected):
                raise TaskExecutionError('ORIGINAL_PERMISSION_OBJECT_DIFFERS')
        control.verify_workspace_paths(checkpoint, timeout_ms=timeout_ms)
        with (
            LocalPathGuard(workspace.canonical_path, directory=True) as root,
            LocalPathGuard(expected, directory=False) as item,
        ):
            identity = item.verify()

            def verify():
                checkpoint()
                if root.verify() != workspace or item.verify() != identity:
                    raise TaskExecutionError('ORIGINAL_PERMISSION_OBJECT_DIFFERS')

            verify()
            yield verify
    except (PathBoundaryError, ContentPathError) as error:
        raise TaskExecutionError('ORIGINAL_PERMISSION_OBJECT_UNVERIFIED') from error
