"""Exact original ref input and bounded ordered ACKs, no ref execution."""

from dataclasses import FrozenInstanceError, replace
import hashlib

import pytest

from backend.app.infrastructure import git_ref_protocol as protocol


def delivery(format='sha1', **changes):
    count = 40 if format == 'sha1' else 64
    args = dict(
        delivery_id=9,
        full_ref='refs/heads/交付/topic',
        planned_oid='1' * count,
        expected_oid='2' * count,
        format=format,
    )
    args.update(changes)
    return protocol.delivery_update(**args)


@pytest.mark.parametrize('format', ['sha1', 'sha256'])
def test_exact_prepare_separates_commit_and_original_ids(format):
    value = delivery(format)
    new, old = value.new_oid.encode(), value.expected_oid.encode()
    assert (
        value.prepare_bytes()
        == b'start\0update ' + value.full_ref.encode() + b'\0' + new + b'\0' + old + b'\0prepare\0'
    )
    assert b'commit\0' not in value.prepare_bytes()
    assert value.arguments() == (
        'update-ref',
        '--no-deref',
        '--create-reflog',
        '-m',
        'WALLE:9',
        '--stdin',
        '-z',
    )
    assert protocol.commit_bytes() == b'commit\0' and protocol.abort_bytes() == b'abort\0'
    assert value.input_sha256 == delivery(format).input_sha256
    assert value.input_sha256 != delivery(format, delivery_id=10).input_sha256
    with pytest.raises(FrozenInstanceError):
        value.new_oid = '3' * len(value.new_oid)


@pytest.mark.parametrize('format', ['sha1', 'sha256'])
def test_baseline_is_only_generated_create_namespace_and_never_zero(format):
    value = protocol.baseline_create(12, 'a' * (40 if format == 'sha1' else 64), format=format)
    assert value.full_ref == 'refs/walle/baselines/12'
    assert value.expected_oid is None
    assert (
        value.prepare_bytes()
        == b'start\0create refs/walle/baselines/12\0' + value.new_oid.encode() + b'\0prepare\0'
    )
    assert value.arguments() == ('update-ref', '--no-deref', '--stdin', '-z')
    for fields in (
        {'expected_oid': 'a' * len(value.new_oid)},
        {'full_ref': 'refs/heads/12'},
        {'full_ref': 'refs/walle/baselines/13'},
    ):
        with pytest.raises(protocol.RefProtocolError):
            replace(value, **fields)


@pytest.mark.parametrize(
    'ref',
    [
        '',
        None,
        'HEAD',
        'main',
        'refs/tags/v1',
        'refs/heads/',
        'refs/heads//a',
        '/refs/heads/a',
        'refs/heads/a/',
        'refs/heads/a.',
        'refs/heads/.a',
        'refs/heads/a.lock',
        'refs/heads/a.lock/b',
        'refs/heads/a..b',
        'refs/heads/a b',
        'refs/heads/a\tb',
        'refs/heads/a\0b',
        'refs/heads/a\nb',
        'refs/heads/a\x7fb',
        'refs/heads/a~',
        'refs/heads/a^',
        'refs/heads/a:b',
        'refs/heads/a?',
        'refs/heads/a*',
        'refs/heads/a[0]',
        'refs/heads/a\\b',
        'refs/heads/a@{1}',
        'refs/heads/\ud800',
    ],
)
def test_branch_is_full_and_never_normalized_or_expression(ref):
    with pytest.raises(protocol.RefProtocolError):
        delivery(full_ref=ref)


@pytest.mark.parametrize(
    'ref',
    [
        'refs/heads/main',
        'refs/heads/子目录/版本',
        'refs/heads/-literal',
        'refs/heads/a@b',
        'refs/heads/topic./child',
        'refs/heads/at@',
        'refs/heads/close]',
    ],
)
def test_valid_full_refs_preserve_literal_spelling(ref):
    assert protocol.branch_ref(ref) == ref


@pytest.mark.parametrize('value', [None, False, 0, -1, 1.0, 2**53, '1'])
def test_original_resource_id_is_not_coerced(value):
    with pytest.raises(protocol.RefProtocolError):
        delivery(delivery_id=value)
    with pytest.raises(protocol.RefProtocolError):
        protocol.baseline_create(value, 'a' * 40, format='sha1')


@pytest.mark.parametrize(
    'value', [None, '', 'HEAD', 'a' * 39, 'A' * 40, '0' * 40, 'a' * 64, 'a' * 40 + '\n']
)
def test_oid_is_exact_full_nonzero_current_format(value):
    for field in ('planned_oid', 'expected_oid'):
        with pytest.raises(protocol.RefProtocolError):
            delivery(**{field: value})
    with pytest.raises(protocol.RefProtocolError):
        protocol.baseline_create(1, value, format='sha1')


@pytest.mark.parametrize(
    'terminal,wire',
    [
        ('COMMIT', b'start: ok\nprepare: ok\ncommit: ok\n'),
        ('ABORT', b'start: ok\nprepare: ok\nabort: ok\n'),
        ('ABORT', b'start: ok\nabort: ok\n'),
    ],
)
def test_ack_fragment_boundaries_and_explicit_terminal(terminal, wire):
    for width in range(1, len(wire) + 1):
        reader = protocol.RefAckDecoder(max_output_bytes=len(wire))
        for start in range(0, len(wire), width):
            reader.feed(wire[start : start + width])
        assert reader.phases[0] == 'START'
        assert reader.finish(expected_terminal=terminal)[-1] == terminal
        with pytest.raises(protocol.RefProtocolError):
            reader.feed(b'')


@pytest.mark.parametrize(
    'wire',
    [
        b'prepare: ok\n',
        b'commit: ok\n',
        b'start: ok\ncommit: ok\n',
        b'start: ok\nstart: ok\n',
        b'start: ok\r\n',
        b'start: OK\n',
        b'start: ok\nprepare: ok\nprepare: ok\n',
        b'start: ok\nprepare: ok\ncommit: ok\ncommit: ok\n',
        b'start: ok\nabort: ok\nprepare: ok\n',
        b'start: ok\nprepare: ok\ncommit: ok\nPRIVATE_GARBAGE',
        b'git version 2.56.0.windows.4\n',
        b'\xff',
        b'start: ok\0',
    ],
)
def test_bad_ack_cannot_be_reset_or_reinterpreted_as_success(wire):
    reader = protocol.RefAckDecoder(max_output_bytes=4096)
    with pytest.raises(protocol.RefProtocolError) as caught:
        reader.feed(wire)
    assert 'PRIVATE' not in str(caught.value)
    with pytest.raises(protocol.RefProtocolError):
        reader.feed(b'start: ok\nprepare: ok\ncommit: ok\n')
    with pytest.raises(protocol.RefProtocolError):
        _ = reader.phases


@pytest.mark.parametrize(
    'wire', [b'', b'start: ok\n', b'start: ok\nprepare: ok\n', b'start: ok\nprepare: ok\ncomm']
)
def test_eof_or_exit_is_not_commit_ack(wire):
    reader = protocol.RefAckDecoder(max_output_bytes=100)
    reader.feed(wire)
    with pytest.raises(protocol.RefProtocolError):
        reader.finish(expected_terminal='COMMIT')


def test_wrong_terminal_or_capacity_type_is_not_accepted():
    reader = protocol.RefAckDecoder(max_output_bytes=100)
    reader.feed(b'start: ok\nabort: ok\n')
    with pytest.raises(protocol.RefProtocolError):
        reader.finish(expected_terminal='COMMIT')
    reader = protocol.RefAckDecoder(max_output_bytes=1)
    with pytest.raises(protocol.RefProtocolError):
        reader.feed(b'st')
    for maximum in (None, False, 0, -1, 1.5, 2**53):
        with pytest.raises(protocol.RefProtocolError):
            protocol.RefAckDecoder(max_output_bytes=maximum)
    for raw in ('start: ok\n', bytearray(b'start: ok\n'), None):
        with pytest.raises(protocol.RefProtocolError):
            protocol.RefAckDecoder(max_output_bytes=100).feed(raw)


def test_unsupported_kind_format_and_intent_digest_never_echo_inputs():
    value = delivery()
    for fields in ({'kind': 'ARBITRARY'}, {'object_format': 'sha512'}):
        with pytest.raises(protocol.RefProtocolError):
            replace(value, **fields)
    assert len(value.input_sha256) == len(hashlib.sha256(b'').hexdigest())


def test_prepared_query_exact_direct_old_ref_and_create_absence():
    intent = delivery()
    raw = intent.full_ref.encode() + b'\0' + intent.expected_oid.encode() + b'\0\0\n'
    assert protocol.prepared_ref_observation(
        raw, intent, query_exit_code=0, max_output_bytes=len(raw)
    ) == {
        'full_ref': intent.full_ref,
        'oid': intent.expected_oid,
        'symref': None,
    }
    baseline = protocol.baseline_create(12, 'a' * 40, format='sha1')
    assert (
        protocol.prepared_ref_observation(b'', baseline, query_exit_code=0, max_output_bytes=1)[
            'oid'
        ]
        is None
    )
    with pytest.raises(protocol.RefProtocolError):
        protocol.prepared_ref_observation(raw, baseline, query_exit_code=0, max_output_bytes=4096)


@pytest.mark.parametrize(
    'raw',
    [
        b'',
        b'refs/heads/other\0' + b'2' * 40 + b'\0\0\n',
        'refs/heads/交付/topic'.encode() + b'\0' + b'1' * 40 + b'\0\0\n',
        'refs/heads/交付/topic'.encode() + b'\0' + b'2' * 40 + b'\0refs/heads/elsewhere\0\n',
        'refs/heads/交付/topic'.encode() + b'\0' + b'2' * 40 + b'\0\0\r\n',
        'refs/heads/交付/topic'.encode() + b'\0' + b'\xff' * 40 + b'\0\0\n',
        'refs/heads/交付/topic'.encode() + b'\0' + b'2' * 40 + b'\0\0\n' + b'EXTRA\0',
    ],
)
def test_prepared_query_failure_or_symbolic_ref_never_authorizes_commit(raw):
    with pytest.raises(protocol.RefProtocolError):
        protocol.prepared_ref_observation(raw, delivery(), query_exit_code=0, max_output_bytes=4096)


@pytest.mark.parametrize('exit_code', [None, False, True, 1, 128, -1])
def test_empty_failed_query_does_not_claim_missing_baseline(exit_code):
    with pytest.raises(protocol.RefProtocolError):
        protocol.prepared_ref_observation(
            b'',
            protocol.baseline_create(1, 'a' * 40, format='sha1'),
            query_exit_code=exit_code,
            max_output_bytes=10,
        )
