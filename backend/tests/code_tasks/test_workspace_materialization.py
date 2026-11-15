import hashlib

import pytest

from backend.app.code_tasks.repository_baseline_query import BaselineQueryResult
from backend.app.code_tasks.workspace_materialization import (
    FixedWorkspaceStage,
    WorkspaceMaterializationError,
)
from backend.app.infrastructure.content_manifest import ContentEntry
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)

NONCE = 'a' * 32
BINARY = b'\xef\xbb\xbfraw\r\n\x00\xff'


@pytest.fixture
def parent(tmp_path):
    with PrivatePackageGuard(create_private_package(tmp_path / 'owned')) as package:
        yield package


def entry(path, raw, mode='100644'):
    return ContentEntry(path, mode, '1' * 40, len(raw), hashlib.sha256(raw).hexdigest())


def test_original_binary_and_empty_copy_with_modes_and_stable_identity(parent):
    stage = FixedWorkspaceStage(parent, NONCE, lambda: None)
    binary = entry('nested/run.bin', BINARY, '100755')
    empty = entry('empty', b'')
    stage.consume(binary, BINARY)
    stage.consume(empty, b'')
    original = stage._stage_identity
    verified = stage.publish(BaselineQueryResult({'id': 17}, (empty, binary)), lambda: None)
    assert verified.snapshot_id == 17
    assert verified.directory.file_id == original.file_id
    assert verified.entries == (empty, binary)
    assert (stage.target / binary.path).read_bytes() == BINARY
    assert (stage.target / empty.path).read_bytes() == b''
    assert not stage._stage.exists()
    (stage.target / binary.path).write_bytes(b'later edit')
    with pytest.raises(WorkspaceMaterializationError, match='TARGET_ALREADY_EXISTS'):
        FixedWorkspaceStage(parent, NONCE, lambda: None)
    assert (stage.target / binary.path).read_bytes() == b'later edit'


@pytest.mark.parametrize(
    'failure', ['bytes', 'extra', 'missing', 'cancelled', 'proof', 'collision']
)
def test_changed_or_unproved_stage_never_replaces_target(parent, failure):
    cancelled = False

    def check_active():
        if cancelled:
            raise WorkspaceMaterializationError('CANCELLED')

    stage = FixedWorkspaceStage(parent, NONCE, check_active)
    content = entry('binary', BINARY)
    stage.consume(content, BINARY)
    result = BaselineQueryResult({'id': 17}, (content,))
    original_target = stage.target

    def check_source():
        if failure == 'collision':
            original_target.mkdir()
            (original_target / 'outside.txt').write_bytes(b'preserve existing target')

    if failure == 'bytes':
        (stage._stage / content.path).write_bytes(b'x' * len(BINARY))
    elif failure == 'extra':
        (stage._stage / 'extra').touch()
    elif failure == 'missing':
        (stage._stage / content.path).unlink()
    elif failure == 'cancelled':
        cancelled = True
    elif failure == 'proof':
        result = BaselineQueryResult({'id': 17}, ())

    error = FileExistsError if failure == 'collision' else WorkspaceMaterializationError
    with pytest.raises(error):
        stage.publish(result, check_source)
    assert stage._stage.exists()
    if failure == 'collision':
        assert (original_target / 'outside.txt').read_bytes() == b'preserve existing target'
    else:
        assert not original_target.exists()
