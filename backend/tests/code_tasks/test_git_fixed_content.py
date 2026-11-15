from dataclasses import replace
import pytest

from backend.app.infrastructure.content_manifest import ContentLimits
from backend.app.infrastructure.git_commit_closure import ClosureLimits
from backend.app.infrastructure.git_fixed_content import inspect_fixed_tree
from backend.tests.code_tasks.test_git_commit_closure import Store, SOURCE


def fixture(format='sha1'):
    data = Store(format)
    blob = data.put('blob', b'\xef\xbb\xbfbytes\r\n\0\xff')
    child = data.tree(b'file', blob)
    empty = data.put('tree', b'')
    root = data.put(
        'tree',
        b'40000 x\0'
        + bytes.fromhex(child)
        + b'40000 y\0'
        + bytes.fromhex(child)
        + b'40000 z\0'
        + bytes.fromhex(empty),
    )
    commit = data.commit(root)
    return data, commit


def inspect(data, commit, **changes):
    params = dict(
        format=data.format,
        read_object=data.read,
        source_fingerprint=SOURCE,
        verify_source=lambda: data.source,
        check_active=lambda: None,
        read_limits=ClosureLimits(100, 100, 100000, 1000000, 100),
        content_limits=ContentLimits(100000, 1000000, 100, 1),
        materialization_root=r'C:\owned',
        check_file=lambda path, blob: None,
        started_at=0,
        clock=lambda: data.now,
    )
    params.update(changes)
    return inspect_fixed_tree(commit, **params)


@pytest.mark.parametrize('format', ['sha1', 'sha256'])
def test_all_paths_shared_objects_empty_directories_and_original_bytes(format):
    data, commit = fixture(format)
    bodies = []
    result = inspect(data, commit, check_file=lambda path, blob: bodies.append((path, blob.raw)))
    assert [entry.path for entry in result.entries] == ['x/file', 'y/file']
    assert result.enumerated_entries == 6 and result.byte_count == 2 * len(bodies[0][1])
    assert bodies[0][1] == bodies[1][1] == b'\xef\xbb\xbfbytes\r\n\0\xff'
    assert result.entries[0].blob_oid == result.entries[1].blob_oid


@pytest.mark.parametrize(
    'limits',
    [
        ContentLimits(1, 10000, 10, 1),
        ContentLimits(10000, 12, 10, 1),
        ContentLimits(10000, 10000, 1, 1),
    ],
)
def test_file_budgets_count_each_path_and_fail_whole_result(limits):
    data, commit = fixture()
    with pytest.raises(ValueError):
        inspect(data, commit, content_limits=limits)


def test_enumeration_and_full_target_path_are_bounded():
    data, commit = fixture()
    with pytest.raises(ValueError):
        inspect(data, commit, read_limits=ClosureLimits(100, 4, 100000, 1000000, 100))
    with pytest.raises(ValueError):
        inspect(data, commit, materialization_root='C:\\' + 'a' * 235)


@pytest.mark.parametrize(
    'prefix',
    [
        b'version https://git-lfs.github.com/spec/v1\n',
        b'version https://hawser.github.com/spec/v1\n',
    ],
)
def test_lfs_pointer_is_rejected_before_file_policy(prefix):
    data = Store()
    blob = data.put('blob', prefix + b'oid sha256:' + b'a' * 64 + b'\nsize 1\n')
    commit = data.commit(data.tree(b'large', blob))
    called = []
    with pytest.raises(ValueError, match='LFS'):
        inspect(data, commit, check_file=lambda path, blob: called.append(path))
    assert not called


def test_empty_tree_is_actual_success_not_missing_tree():
    data = Store()
    root = data.put('tree', b'')
    commit = data.commit(root)
    assert inspect(data, commit).entries == ()
    del data.values[root]
    with pytest.raises(KeyError):
        inspect(data, commit)


def test_policy_absence_failure_and_unconfirmed_return_never_succeed():
    data, commit = fixture()
    with pytest.raises(ValueError):
        inspect(data, commit, check_file=None)
    assert not data.calls
    with pytest.raises(ValueError, match='POLICY_UNVERIFIED'):
        inspect(data, commit, check_file=lambda path, blob: True)

    def reject(path, blob):
        raise PermissionError('test policy denial')

    with pytest.raises(PermissionError):
        inspect(data, commit, check_file=reject)


def test_source_or_time_change_in_file_policy_is_checked():
    for change in ('source', 'now'):
        data, commit = fixture()

        def mutate(path, blob):
            setattr(data, change, 'b' * 64 if change == 'source' else 100)

        with pytest.raises(ValueError):
            inspect(data, commit, check_file=mutate)


def test_pointer_header_in_normal_source_is_not_a_pointer():
    from backend.app.infrastructure.git_fixed_content import reject_lfs_pointer

    for raw in (
        b'version https://git-lfs.github.com/spec/v1\nexample documentation\n',
        b'version https://git-lfs.github.com/spec/v1\n',
        b'version https://git-lfs.github.com/spec/v1\n' + b'x' * 1024,
    ):
        assert reject_lfs_pointer(raw) is None


def test_lfs_extensions_are_not_silently_materialized_as_source():
    from backend.app.infrastructure.git_fixed_content import reject_lfs_pointer

    raw = (
        b'version https://git-lfs.github.com/spec/v1\next-0-test sha256:example\noid sha256:'
        + b'a' * 64
        + b'\nsize 0\n'
    )
    with pytest.raises(ValueError, match='LFS'):
        reject_lfs_pointer(raw)


def test_empty_root_budget_is_not_confused_with_commit_header_count():
    data = Store()
    commit = data.commit(data.put('tree', b''))
    result = inspect(data, commit, read_limits=ClosureLimits(2, 1, 10000, 10000, 100))
    assert result.entries == () and result.enumerated_entries == 1
