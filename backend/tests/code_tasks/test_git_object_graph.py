"""Malformed object structure and content namespace boundaries, no IO."""

from dataclasses import replace
import hashlib
import pytest

from backend.app.infrastructure.git_object_read import verify_git_object
from backend.app.infrastructure.git_object_graph import decode_commit_edges, decode_tree_edges
from backend.app.infrastructure.git_object_graph import GitObjectGraphError


def obj(kind, raw, format='sha1'):
    oid = hashlib.new(
        format, kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw
    ).hexdigest()
    return verify_git_object(raw, format=format, object_type=kind, oid=oid, max_output_bytes=65536)


def commit(tree, parents=(), extra=b'', message=b'raw\xff\0\r\n'):
    return (
        b'tree '
        + tree
        + b'\n'
        + b''.join(b'parent ' + p + b'\n' for p in parents)
        + b'author fixture <a@b> 1 +0000\ncommitter fixture <a@b> 2 +0000\n'
        + extra
        + b'\n'
        + message
    )


def record(name, *, mode=b'100644', oid=b'a' * 20):
    return mode + b' ' + name + b'\0' + oid


@pytest.mark.parametrize('format, length', [('sha1', 40), ('sha256', 64)])
def test_root_merge_signed_headers_and_binary_message_keep_only_real_edges(format, length):
    raw = commit(
        b'a' * length,
        [b'b' * length, b'c' * length],
        b'gpgsig first\n continuation\nencoding ISO-8859-1\n',
    )
    value = obj('commit', raw, format)
    edges = decode_commit_edges(value, max_object_bytes=65536, max_headers=20)
    assert edges.tree_oid == 'a' * length and edges.parent_oids == ('b' * length, 'c' * length)
    assert value.raw == raw
    root = decode_commit_edges(
        obj('commit', commit(b'a' * length), format), max_object_bytes=65536, max_headers=3
    )
    assert root.parent_oids == ()


@pytest.mark.parametrize(
    'raw',
    [
        b'',
        b'tree ' + b'a' * 40 + b'\n',
        commit(b'HEAD'),
        commit(b'0' * 40),
        commit(b'A' * 40),
        commit(b'a' * 40, [b'b' * 7]),
        commit(b'a' * 40).replace(b'author ', b'writer ', 1),
        commit(b'a' * 40).replace(b'committer ', b'writer ', 1),
        commit(b'a' * 40, b'', b' parent ' + b'b' * 40 + b'\n'),
        commit(b'a' * 40, b'', b'parent ' + b'b' * 40 + b'\n'),
        commit(b'a' * 40, b'', b'tree ' + b'b' * 40 + b'\n'),
        commit(b'a' * 40, b'', b'author extra\n'),
        commit(b'a' * 40, b'', b'no-space\n'),
        commit(b'a' * 40).replace(b'author fixture', b'author \0fixture'),
        commit(b'a' * 40).replace(b'tree ', b'parent ', 1),
    ],
)
def test_bad_commit_structure_never_yields_partial_edges(raw):
    with pytest.raises(ValueError):
        decode_commit_edges(obj('commit', raw), max_object_bytes=65536, max_headers=100)


@pytest.mark.parametrize('format,length', [('sha1', 20), ('sha256', 32)])
def test_empty_tree_and_git_directory_sort_order(format, length):
    assert decode_tree_edges(obj('tree', b'', format), max_object_bytes=100, max_entries=1) == ()
    raw = (
        record(b'foo.bar', oid=b'a' * length)
        + record(b'foo', mode=b'40000', oid=b'b' * length)
        + record('中文'.encode(), mode=b'100755', oid=b'c' * length)
    )
    rows = decode_tree_edges(obj('tree', raw, format), max_object_bytes=65536, max_entries=3)
    assert [(row.name, row.mode, row.object_type) for row in rows] == [
        ('foo.bar', '100644', 'blob'),
        ('foo', '40000', 'tree'),
        ('中文', '100755', 'blob'),
    ]
    assert rows[1].object_oid == (b'b' * length).hex()


@pytest.mark.parametrize(
    'raw',
    [
        b'100644 name',
        record(b'name')[:-1],
        b'x',
        record(b'name', mode=b'120000'),
        record(b'name', mode=b'160000'),
        record(b'name', mode=b'040000'),
        record(b'../secret'),
        record(b'a/b'),
        record(b'.git'),
        record(b'NUL.txt'),
        record(b'name.'),
        record(b'\xff'),
        record('e\u0301'.encode()),
        record(b'bad:name'),
        record(b''),
        record(b'b') + record(b'a'),
        record(b'a') + record(b'a'),
        record(b'A') + record(b'a'),
        record(b'a') + record(b'a', mode=b'40000'),
        record(b'a', oid=b'\0' * 20),
    ],
)
def test_bad_tree_cannot_hide_or_normalize_entries(raw):
    with pytest.raises(ValueError):
        decode_tree_edges(obj('tree', raw), max_object_bytes=65536, max_entries=100)


def test_limits_and_forged_original_facts_are_checked():
    value = obj('tree', record(b'a') + record(b'b'))
    for maximum in (True, 0, 1):
        with pytest.raises(ValueError):
            decode_tree_edges(value, max_object_bytes=65536, max_entries=maximum)
    for changed in (
        replace(value, byte_count=0),
        replace(value, sha256='a' * 64),
        replace(value, raw=b''),
    ):
        with pytest.raises(ValueError):
            decode_tree_edges(changed, max_object_bytes=65536, max_entries=10)
    with pytest.raises(GitObjectGraphError):
        decode_commit_edges(value, max_object_bytes=65536, max_headers=10)
    with pytest.raises(ValueError):
        decode_commit_edges(obj('commit', commit(b'a' * 40)), max_object_bytes=65536, max_headers=2)
