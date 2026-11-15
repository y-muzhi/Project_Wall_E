"""Fixed BUILD input and original-byte recovery, no repository writes."""

from dataclasses import FrozenInstanceError
import hashlib
from unittest.mock import patch

import pytest

from backend.app.infrastructure import git_commit_input as commit


def make(**changes):
    fields = {
        'format': 'sha1',
        'tree_oid': 'a' * 40,
        'parent_oid': 'b' * 40,
        'delivery_id': 31,
        'fixed_unix_seconds': 1700000000,
        'author': commit.CommitIdentity('作者', 'author@example.invalid'),
        'committer': commit.CommitIdentity('控制方', 'committer@example.invalid'),
        'message_template': '任务{task_id}\r\n候选{candidate_id}\r结束',
        'task_id': 11,
        'candidate_id': 22,
        'max_payload_bytes': 16384,
    }
    fields.update(changes)
    return commit.build_delivery_commit(**fields)


def restore(value, raw=None, **changes):
    raw = value.payload if raw is None else raw
    fields = {
        'format': value.format,
        'tree_oid': value.tree_oid,
        'parent_oid': value.parent_oid,
        'delivery_id': value.delivery_id,
        'expected_payload_sha256': value.payload_sha256,
        'expected_commit_oid': value.commit_oid,
        'max_payload_bytes': 16384,
    }
    fields.update(changes)
    return commit.verify_stored_delivery_commit(raw, **fields)


@pytest.mark.parametrize('format,length', [('sha1', 40), ('sha256', 64)])
def test_exact_headers_utf8_lf_template_and_unique_original_delivery(format, length):
    value = make(format=format, tree_oid='a' * length, parent_oid='b' * length)
    expected = (
        'tree ' + 'a' * length + '\nparent ' + 'b' * length + '\n'
        'author 作者 <author@example.invalid> 1700000000 +0000\n'
        'committer 控制方 <committer@example.invalid> 1700000000 +0000\n\n'
        '任务11\n候选22\n结束\nWALL-E-Delivery: 31\n'
    ).encode('utf-8')
    assert value.payload == expected and len(value.commit_oid) == length
    assert value.payload_sha256 == hashlib.sha256(expected).hexdigest()
    assert restore(value) == value
    assert '任务11' not in repr(value)
    with pytest.raises(FrozenInstanceError):
        value.delivery_id = 99


def test_recovery_reads_original_bytes_without_current_template_or_clock():
    original = make()
    with patch.object(
        commit, 'render_delivery_message', side_effect=AssertionError('No rendering')
    ):
        assert restore(original).payload is original.payload
    assert restore(original).fixed_unix_seconds == 1700000000


@pytest.mark.parametrize(
    'template',
    [
        '{unknown}',
        '{}',
        '{0}',
        '{task_id.__class__}',
        '{task_id[0]}',
        '{task_id!r}',
        '{candidate_id:04d}',
        '{task_id:{candidate_id}}',
        '{unclosed',
    ],
)
def test_templates_cannot_read_anything_except_the_two_literal_ids(template):
    with pytest.raises(commit.DeliveryCommitError, match='TEMPLATE_INVALID'):
        make(message_template=template)


def test_literal_braces_and_trailing_blank_lines_are_not_silently_removed():
    value = make(message_template='{{固定}} {task_id}\n\n')
    assert value.payload.endswith('{\u56fa定} 11\n\nWALL-E-Delivery: 31\n'.encode('utf-8'))
    assert restore(value) == value


@pytest.mark.parametrize(
    'message',
    [
        'WALL-E-Delivery: 3',
        'prefix\nwall-e-delivery: 31',
        ' \tWALL-E-Delivery \t: 31',
        'WALL-E-Delivery: 31\nWALL-E-Delivery: 31',
    ],
)
def test_template_cannot_supply_a_second_delivery_claim(message):
    with pytest.raises(commit.DeliveryCommitError, match='TRAILER_ALREADY_PRESENT'):
        make(message_template=message)


@pytest.mark.parametrize(
    'value', ['', ' ', 'a\nb', 'a\rb', 'a\tb', 'a<b', 'a>b', 'a\x85b', '\ud800']
)
def test_author_and_committer_cannot_inject_headers_or_invalid_utf8(value):
    for field in ('author', 'committer'):
        with pytest.raises(commit.DeliveryCommitError):
            make(**{field: commit.CommitIdentity(value, 'a@example.invalid')})
        with pytest.raises(commit.DeliveryCommitError):
            make(**{field: commit.CommitIdentity('name', value)})


@pytest.mark.parametrize(
    'field,value',
    [
        ('delivery_id', True),
        ('task_id', 0),
        ('candidate_id', -1),
        ('fixed_unix_seconds', -1),
        ('fixed_unix_seconds', 1.0),
        ('fixed_unix_seconds', 2**53),
        ('max_payload_bytes', False),
        ('tree_oid', '0' * 40),
        ('parent_oid', 'B' * 40),
        ('parent_oid', 'b' * 64),
        ('format', 'md5'),
    ],
)
def test_original_ids_time_limits_and_object_format_are_strict(field, value):
    with pytest.raises(commit.DeliveryCommitError):
        make(**{field: value})


def test_payload_limit_uses_utf8_bytes_and_does_not_shrink_or_omit_the_message():
    value = make()
    assert make(max_payload_bytes=len(value.payload)) == value
    with pytest.raises(commit.DeliveryCommitError, match='PAYLOAD_TOO_LARGE'):
        make(max_payload_bytes=len(value.payload) - 1)


@pytest.mark.parametrize(
    'field,value',
    [
        ('delivery_id', 32),
        ('tree_oid', 'c' * 40),
        ('parent_oid', 'd' * 40),
        ('expected_payload_sha256', '0' * 64),
        ('expected_commit_oid', '0' * 40),
    ],
)
def test_stored_bytes_cannot_be_rebound_to_new_original_metadata(field, value):
    with pytest.raises(commit.DeliveryCommitError):
        restore(make(), **{field: value})


@pytest.mark.parametrize(
    'kind',
    [
        'crlf',
        'no_final_lf',
        'second_parent',
        'tree',
        'extra_header',
        'invalid_utf8',
        'missing_trailer',
        'extra_trailer',
        'changed_time',
        'huge_time',
        'empty_body',
    ],
)
def test_self_consistent_hashes_do_not_admit_malformed_or_reassociated_payloads(kind):
    original = make()
    raw = original.payload
    if kind == 'crlf':
        raw = raw.replace(b'\n', b'\r\n')
    elif kind == 'no_final_lf':
        raw = raw[:-1]
    elif kind == 'second_parent':
        raw = raw.replace(b'author ', b'parent ' + b'c' * 40 + b'\nauthor ', 1)
    elif kind == 'tree':
        raw = raw.replace(b'a' * 40, b'c' * 40, 1)
    elif kind == 'extra_header':
        raw = raw.replace(b'\n\n', b'\ngpgsig external\n\n', 1)
    elif kind == 'invalid_utf8':
        raw = raw.replace('任务11'.encode('utf-8'), b'\xff')
    elif kind == 'missing_trailer':
        raw = raw.replace(b'WALL-E-Delivery: 31\n', b'other message\n')
    elif kind == 'extra_trailer':
        raw += b'wall-e-delivery: 31\n'
    elif kind == 'changed_time':
        raw = raw.replace(b'> 1700000000 ', b'> 1700000001 ', 1)
    elif kind == 'huge_time':
        raw = raw.replace(b'> 1700000000 ', b'> ' + b'9' * 5000 + b' ', 1)
    else:
        raw = raw.split(b'\n\n', 1)[0] + b'\n\n'
    oid = hashlib.new(
        original.format,
        b'commit ' + str(len(raw)).encode('ascii') + b'\0' + raw,
    ).hexdigest()
    with pytest.raises(commit.DeliveryCommitError):
        restore(
            original,
            raw,
            expected_payload_sha256=hashlib.sha256(raw).hexdigest(),
            expected_commit_oid=oid,
        )
