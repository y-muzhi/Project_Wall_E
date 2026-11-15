"""Closure limits, ancestry, typed original reads and interruption boundaries."""

from collections import Counter
from dataclasses import replace
import hashlib
import pytest

from backend.app.infrastructure.git_commit_closure import (
    ClosureLimits,
    GitClosureError,
    inspect_commit_closure,
)
from backend.app.infrastructure.git_object_graph import decode_tree_edges
from backend.app.infrastructure.git_object_read import verify_git_object

SOURCE = 'a' * 64


class Store:
    def __init__(self, format='sha1'):
        self.format, self.values, self.calls = format, {}, []
        self.now = 0
        self.after = lambda request: None
        self.source = SOURCE

    def put(self, kind, raw):
        oid = hashlib.new(
            self.format, kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw
        ).hexdigest()
        value = verify_git_object(
            raw, format=self.format, object_type=kind, oid=oid, max_output_bytes=100000
        )
        self.values[oid] = value
        return oid

    def tree(self, name, oid, mode=b'100644'):
        return self.put('tree', mode + b' ' + name + b'\0' + bytes.fromhex(oid))

    def commit(self, tree, parents=(), message=b'fixture'):
        raw = (
            b'tree '
            + tree.encode()
            + b'\n'
            + b''.join(b'parent ' + p.encode() + b'\n' for p in parents)
            + b'author fixture <a@b> 1 +0000\ncommitter fixture <a@b> 1 +0000\n\n'
            + message
        )
        return self.put('commit', raw)

    def read(self, request):
        self.calls.append(request)
        value = self.values[request.object_oid]
        original = verify_git_object(
            value.raw,
            format=value.format,
            object_type=value.object_type,
            oid=value.object_oid,
            max_output_bytes=request.max_output_bytes,
        )
        self.after(request)
        return original

    def inspect(self, roots, **overrides):
        kwargs = dict(
            format=self.format,
            read_object=self.read,
            source_fingerprint=SOURCE,
            verify_source=lambda: self.source,
            check_active=lambda: None,
            limits=ClosureLimits(100, 100, 100000, 1000000, 100),
            started_at=0,
            clock=lambda: self.now,
        )
        kwargs.update(overrides)
        return inspect_commit_closure(roots, **kwargs)


def graph(format='sha1'):
    data = Store(format)
    empty = data.put('tree', b'')
    blob = data.put('blob', b'private body\0\xff')
    tree = data.tree(b'file', blob)
    parent = data.commit(empty)
    left = data.commit(tree, (parent,), b'left')
    right = data.commit(tree, (parent,), b'right')
    merge = data.commit(tree, (left, right), b'merge')
    return data, merge, right, parent


@pytest.mark.parametrize('format', ['sha1', 'sha256'])
def test_complete_shared_merge_history_reads_every_object_once(format):
    data, merge, right, _ = graph(format)
    result = data.inspect((merge, right, merge))
    assert result.roots == (merge, right, merge) and result.edge_count == 12
    assert len(result.objects) == len(data.values) == len(data.calls) == 7
    assert Counter(value.object_type for value in result.objects) == {
        'commit': 4,
        'tree': 2,
        'blob': 1,
    }
    assert result.byte_count == sum(value.byte_count for value in data.values.values())
    assert all(count == 1 for count in Counter(value.object_oid for value in data.calls).values())
    assert 'private body' not in repr(result)
    assert data.inspect((merge, right, merge)) == result


@pytest.mark.parametrize(
    'field,value',
    [('max_objects', 6), ('max_edges', 11), ('max_object_bytes', 1), ('max_total_bytes', 1)],
)
def test_global_limits_do_not_return_partial_closure(field, value):
    data, merge, right, _ = graph()
    limits = replace(ClosureLimits(100, 100, 100000, 1000000, 100), **{field: value})
    with pytest.raises(ValueError):
        data.inspect((merge, right, merge), limits=limits)


@pytest.mark.parametrize(
    'field', ['max_objects', 'max_edges', 'max_object_bytes', 'max_total_bytes', 'max_seconds']
)
@pytest.mark.parametrize('value', [True, 0, 9007199254740992])
def test_limit_values_are_strict(field, value):
    with pytest.raises(GitClosureError):
        replace(ClosureLimits(100, 100, 100000, 1000000, 100), **{field: value})


def test_missing_parent_is_not_skipped_or_retried():
    data, merge, _, parent = graph()
    del data.values[parent]
    with pytest.raises(KeyError):
        data.inspect((merge,))
    assert sum(request.object_oid == parent for request in data.calls) == 1


def test_source_change_after_original_read_stops_before_another():
    data, merge, _, _ = graph()
    data.after = lambda request: setattr(data, 'source', 'b' * 64)
    with pytest.raises(GitClosureError, match='SOURCE_CHANGED'):
        data.inspect((merge,))
    assert len(data.calls) == 1


@pytest.mark.parametrize('now', [100, float('nan'), -1, True])
def test_deadline_and_clock_fault_after_read_stop_before_another(now):
    data, merge, _, _ = graph()
    data.after = lambda request: setattr(data, 'now', now)
    with pytest.raises(GitClosureError):
        data.inspect((merge,))
    assert len(data.calls) == 1


def test_cancel_exception_and_unconfirmed_active_check_do_not_read():
    data, merge, _, _ = graph()

    def cancel():
        raise InterruptedError('owned cancellation')

    with pytest.raises(InterruptedError):
        data.inspect((merge,), check_active=cancel)
    with pytest.raises(GitClosureError, match='ACTIVE_CHECK'):
        data.inspect((merge,), check_active=lambda: False)
    assert data.calls == []


def test_cancellation_after_read_propagates_without_result():
    data, merge, _, _ = graph()

    def cancel():
        if data.calls:
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        data.inspect((merge,), check_active=cancel)
    assert len(data.calls) == 1


def test_wrong_object_or_format_cannot_supply_requested_edge():
    data, merge, _, _ = graph()
    other = Store('sha256')
    oid = other.put('commit', data.values[merge].raw)
    with pytest.raises(GitClosureError, match='ORIGINAL_OBJECT'):
        data.inspect((merge,), read_object=lambda request: other.values[oid])


def test_kind_conflict_and_external_gitlink_are_not_hidden():
    data = Store()
    blob = data.put('blob', b'body')
    bad = data.put('tree', b'100644 a\0' + bytes.fromhex(blob) + b'40000 b\0' + bytes.fromhex(blob))
    commit = data.commit(bad)
    with pytest.raises(GitClosureError, match='KIND_CONFLICT'):
        data.inspect((commit,))
    external = data.tree(b'submodule', 'b' * 40, b'160000')
    commit = data.commit(external)
    before = len(data.calls)
    with pytest.raises(GitClosureError, match='GITLINK'):
        data.inspect((commit,))
    assert len(data.calls) == before + 2


def test_history_readability_never_authorizes_unsupported_current_tree():
    data = Store()
    blob = data.put('blob', b'link target')
    tree = data.tree(b'\xff', blob, b'120000')
    commit = data.commit(tree)
    assert len(data.inspect((commit,)).objects) == 3
    with pytest.raises(ValueError):
        decode_tree_edges(data.values[tree], max_object_bytes=100000, max_entries=100)


def test_zero_remaining_budget_can_still_verify_actual_empty_tree():
    data = Store()
    empty = data.put('tree', b'')
    commit = data.commit(empty)
    limits = ClosureLimits(2, 2, 10000, data.values[commit].byte_count, 10)
    result = data.inspect((commit,), limits=limits)
    assert result.byte_count == limits.max_total_bytes
    assert data.calls[-1].max_output_bytes == 1


@pytest.mark.parametrize('roots', [(), [], ('HEAD',), ('0' * 40,), ('a' * 7,)])
def test_invalid_roots_are_not_interpreted_as_revisions(roots):
    data = Store()
    with pytest.raises(ValueError):
        data.inspect(roots)
    assert not data.calls


def test_final_serialization_time_and_source_change_cannot_publish_success(monkeypatch):
    from backend.app.infrastructure import git_commit_closure as module

    data, merge, _, _ = graph()
    original = module.canonical_input

    def serialize(payload):
        result = original(payload)
        data.now = 100
        return result

    monkeypatch.setattr(module, 'canonical_input', serialize)
    with pytest.raises(GitClosureError, match='TIME_LIMIT'):
        data.inspect((merge,))
    data.now = 0

    def serialize_changed_source(payload):
        result = original(payload)
        data.source = 'b' * 64
        return result

    monkeypatch.setattr(module, 'canonical_input', serialize_changed_source)
    with pytest.raises(GitClosureError, match='SOURCE_CHANGED') as error:
        data.inspect((merge,))
    assert error.value.code == 'SOURCE_CHANGED'


def test_false_declared_empty_object_length_is_not_original_fact():
    data = Store()
    empty = data.put('tree', b'')
    from backend.app.infrastructure.git_object_graph import require_original_object

    with pytest.raises(ValueError):
        require_original_object(replace(data.values[empty], byte_count=False), 'tree', 1000)
