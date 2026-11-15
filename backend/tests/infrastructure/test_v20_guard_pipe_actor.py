"""Foreign-thread transport calls must fail before locks, preserving the original actor."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from backend.app.infrastructure.guard_pipe_frames import GuardPipeFrames
from backend.app.infrastructure.windows_guard_pipe import GuardPipeError
from backend.app.infrastructure.windows_guard_pipe_io import GuardPipeIO, PipeIOError
from backend.app.infrastructure.windows_pipe_peer import PipePeerError
from backend.tests.infrastructure.test_v20_windows_guard_pipe_io import channel
from backend.tests.infrastructure.test_v20_windows_guard_pipe_client import guard, connect
from backend.tests.infrastructure.test_v20_windows_pipe_peer import connection, peer
from backend.tests.requirements.test_v15_foundation import tmp_path


class ForbiddenGate:
    def __enter__(self):
        raise AssertionError('Foreign thread reached an original actor lock')

    def __exit__(self, *_):
        raise AssertionError('Foreign thread acquired an original actor lock')


def foreign_rejected(owner, action, expected):
    # Fail immediately if the public action touches a foreign lock, rather than
    # making an intentionally broken check hang the fixture cleanup thread.
    with patch.object(owner, '_gate', ForbiddenGate()):
        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(action)
            with pytest.raises(expected, match='OWNER_THREAD_DIFFERS'):
                future.result(timeout=2)


def test_foreign_server_io_and_frame_calls_preserve_the_actual_original_stream(channel):
    io, client, server = channel
    frames = GuardPipeFrames(io)
    foreign_rejected(server, server.verify, GuardPipeError)
    foreign_rejected(server, server.close, GuardPipeError)
    foreign_rejected(io, io.close, PipeIOError)
    foreign_rejected(
        io, lambda: io.read_exact(1, timeout_ms=100, cancelled=lambda: False), PipeIOError
    )
    foreign_rejected(
        frames, lambda: frames.read(timeout_ms=100, cancelled=lambda: False), PipeIOError
    )
    foreign_rejected(frames, frames.close, PipeIOError)
    original = client('FRAME_EXCHANGE')
    original.start()
    io.connect(timeout_ms=3000, cancelled=lambda: False)
    original.ready()
    frames.write({'msg': '你好'}, timeout_ms=3000, cancelled=lambda: False)
    assert frames.read(timeout_ms=3000, cancelled=lambda: False) == {'reply': 'ok'}


def test_foreign_client_and_io_close_cannot_release_original_peer_or_endpoint(guard):
    with connect(guard) as client:
        foreign_rejected(client, client.verify, GuardPipeError)
        foreign_rejected(client, client.close, GuardPipeError)
        with GuardPipeIO(client) as io:
            foreign_rejected(io, io.close, PipeIOError)
            io.write_all(b'ping', timeout_ms=3000, cancelled=lambda: False)
            assert io.read_exact(4, timeout_ms=3000, cancelled=lambda: False) == b'pong'


def test_foreign_peer_close_or_read_does_not_reopen_or_release_the_actual_peer(connection):
    with peer(connection) as lease:
        foreign_rejected(lease, lease.verify, PipePeerError)
        foreign_rejected(lease, lease.close, PipePeerError)
        assert lease.verify() == connection.process.identity
