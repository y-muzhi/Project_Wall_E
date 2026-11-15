"""Frame vectors and real independent sender/receiver over a protected endpoint."""

import pytest

from backend.app.infrastructure import guard_pipe_frames as module
from backend.app.infrastructure.windows_guard_pipe_io import CHUNK_LIMIT, PipeIOError
from backend.tests.infrastructure.test_v20_windows_guard_pipe_io import channel
from backend.tests.requirements.test_v15_foundation import tmp_path


def test_canonical_utf8_object_length_and_dictionary_order_are_exact():
    value = {'z': [True, None, -7, 1.5], 'a': '中文'}
    raw = module.encode_guard_frame(value)
    assert int.from_bytes(raw[:4], 'big') == len(raw[4:])
    assert raw[4:] == '{"a":"中文","z":[true,null,-7,1.5]}'.encode('utf-8')
    assert module.decode_guard_payload(raw[4:]) == value
    assert module.encode_guard_frame({'a': '中文', 'z': value['z']}) == raw


def test_exact_payload_limit_is_accepted_and_next_byte_is_not():
    raw = module.encode_guard_frame({'x': 'a' * (module.PAYLOAD_LIMIT - 8)})
    assert len(raw) == CHUNK_LIMIT
    assert module.decode_guard_payload(raw[4:])['x'].endswith('a')
    with pytest.raises(module.GuardFrameError):
        module.encode_guard_frame({'x': 'a' * (module.PAYLOAD_LIMIT - 7)})


@pytest.mark.parametrize(
    'value',
    [
        None,
        [],
        b'{}',
        {1: 'key'},
        {'x': float('nan')},
        {'x': float('inf')},
        {'x': 9007199254740992},
        {'x': -9007199254740992},
        {'x': '\ud800'},
        {'x': (1, 2)},
        {'x': [0] * module.MAX_NODES},
    ],
)
def test_outgoing_values_are_json_facts_not_coerced_claims(value):
    with pytest.raises(module.GuardFrameError):
        module.encode_guard_frame(value)


@pytest.mark.parametrize(
    'raw',
    [
        b'',
        b'[]',
        b'null',
        b'{"x":1,"x":2}',
        b'{"x":{"a":1,"a":2}}',
        b'{"x":NaN}',
        b'{"x":1e400}',
        b'{"x":9007199254740992}',
        b'{"x":"\xff"}',
        b'\xef\xbb\xbf{}',
        b'{}{}',
        b'{"x":"\\ud800"}',
    ],
)
def test_invalid_incoming_payload_is_not_repaired_or_truncated(raw):
    with pytest.raises(module.GuardFrameError):
        module.decode_guard_payload(raw)


def test_structure_depth_is_explicit_and_count_checked_before_child_stack_allocation():
    value = None
    for _ in range(module.MAX_DEPTH - 1):
        value = {'x': value}
    assert module.decode_guard_payload(module.encode_guard_frame(value)[4:]) == value
    with pytest.raises(module.GuardFrameError):
        module.encode_guard_frame({'x': value})


def connected(channel, mode):
    io, client, _ = channel
    peer = client(mode)
    peer.start()
    io.connect(timeout_ms=3000, cancelled=lambda: False)
    peer.ready()
    return io, module.GuardPipeFrames(io)


def test_actual_fragmented_header_and_multibyte_body_use_one_original_reader(channel):
    io, frames = connected(channel, 'FRAME_GOOD')
    assert frames.read(timeout_ms=3000, cancelled=lambda: False) == {'hello': '世界'}
    with pytest.raises(module.GuardFrameError, match='ALREADY_HAS_FRAME_OWNER'):
        module.GuardPipeFrames(io)


def test_actual_unicode_write_and_independent_manual_reply(channel):
    _, frames = connected(channel, 'FRAME_EXCHANGE')
    frames.write({'msg': '你好'}, timeout_ms=3000, cancelled=lambda: False)
    assert frames.read(timeout_ms=3000, cancelled=lambda: False) == {'reply': 'ok'}


@pytest.mark.parametrize('mode', ['FRAME_BAD_SIZE', 'FRAME_BAD_JSON', 'FRAME_PARTIAL'])
def test_bad_length_duplicate_json_or_partial_eof_poison_original_stream(channel, mode):
    io, frames = connected(channel, mode)
    with pytest.raises((module.GuardFrameError, PipeIOError)):
        frames.read(timeout_ms=3000, cancelled=lambda: False)
    assert io._failed and io._pending is None
    with pytest.raises(module.GuardFrameError, match='UNAVAILABLE'):
        frames.read(timeout_ms=100, cancelled=lambda: False)


def test_actual_header_and_body_share_one_deadline(channel):
    io, frames = connected(channel, 'FRAME_DEADLINE')
    io.write_all(b'g', timeout_ms=3000, cancelled=lambda: False)
    with pytest.raises((module.GuardFrameError, PipeIOError)):
        frames.read(timeout_ms=60, cancelled=lambda: False)
    assert io._failed and io._pending is None


@pytest.mark.parametrize('value', [None, {}, 1])
def test_serialized_handle_or_mock_cannot_replace_original_guard_io(value):
    with pytest.raises(TypeError):
        module.GuardPipeFrames(value)
