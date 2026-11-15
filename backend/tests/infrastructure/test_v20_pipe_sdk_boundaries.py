"""SDK transport boundaries: no old-context request may reach the application relay."""

from types import SimpleNamespace
import pytest
from backend.app.infrastructure.check_case_evidence import CheckEvidenceUnknown
from backend.app.infrastructure.check_driver_pipe_sdk import PipeChromium, MAX_FRAME_BYTES


@pytest.mark.parametrize('epoch', [0, 1, True, '2', None])
@pytest.mark.parametrize('kind', ['ROUTE', 'BROWSER_START', 'BROWSER_WRITE'])
def test_stale_or_untyped_sdk_epoch_never_calls_relay(tmp_path, epoch, kind):
    pipe = PipeChromium(tmp_path)
    called = []
    pipe._context = SimpleNamespace(_generation=2, _route=lambda value: called.append(value))
    with pytest.raises(CheckEvidenceUnknown, match='CONTEXT_REQUIRED'):
        pipe._event({'event': kind, 'epoch': epoch, 'route': 1, 'request': {}})
    assert called == []


def test_unknown_sdk_event_does_not_call_relay(tmp_path):
    pipe = PipeChromium(tmp_path)
    called = []
    pipe._context = SimpleNamespace(_generation=2, _route=lambda value: called.append(value))
    with pytest.raises(CheckEvidenceUnknown, match='EVENT_UNVERIFIED'):
        pipe._event({'event': 'EVALUATE', 'epoch': 2, 'source': 'invalid user source'})
    assert called == []


def fake_connected(tmp_path):
    from threading import Thread

    pipe = PipeChromium(tmp_path)
    pipe._process = object()

    def acknowledge():
        raw, completed, errors = pipe._outgoing.get(timeout=2)
        completed.set()

    worker = Thread(target=acknowledge)
    worker.start()
    return pipe, worker


@pytest.mark.parametrize(
    'response',
    [
        {'id': True, 'result': True},
        {'id': 0, 'result': True},
        {'id': 2, 'result': True},
        {'id': 1, 'result': True, 'ready': True},
    ],
)
def test_unbound_or_ambiguous_sdk_reply_cannot_become_an_observation(tmp_path, response):
    pipe, worker = fake_connected(tmp_path)
    try:
        pipe._incoming.put(response)
        with pytest.raises(CheckEvidenceUnknown, match='RESPONSE_UNVERIFIED'):
            pipe.rpc('LOCATOR', {}, timeout=1000)
    finally:
        worker.join(timeout=2)


def test_private_sdk_error_stays_typed_and_bounded(tmp_path):
    pipe, worker = fake_connected(tmp_path)
    try:
        pipe._incoming.put({'id': 1, 'error': {'code': 'FAILED', 'message': 'x' * 5000}})
        with pytest.raises(CheckEvidenceUnknown, match='^ORIGINAL_SDK_OPERATION_FAILED$'):
            pipe.rpc('LOCATOR', {}, timeout=1000)
        assert len(pipe._last_error['message']) == 1000
    finally:
        worker.join(timeout=2)


def test_full_sdk_write_queue_obeys_deadline(tmp_path):
    import queue

    pipe = PipeChromium(tmp_path)
    pipe._process = object()
    pipe._outgoing = queue.Queue(maxsize=1)
    pipe._outgoing.put(None)
    with pytest.raises(CheckEvidenceUnknown, match='DEADLINE_EXPIRED'):
        pipe.rpc('LOCATOR', {}, timeout=10)


def test_oversized_sdk_request_is_rejected_before_any_write(tmp_path):
    pipe = PipeChromium(tmp_path)
    pipe._process = object()
    with pytest.raises(CheckEvidenceUnknown, match='FRAME_LIMIT'):
        pipe.rpc('LOCATOR', {'value': 'x' * MAX_FRAME_BYTES})
    assert pipe._outgoing.empty()


def test_profile_creation_denial_returns_immediately_without_retry(tmp_path, monkeypatch):
    from backend.app.infrastructure import check_driver_browser

    attempted = []

    def denied(path, mode):
        attempted.append((path, mode))
        raise PermissionError('Original directory refused creation')

    monkeypatch.setattr(check_driver_browser.os, 'mkdir', denied)
    with pytest.raises(CheckEvidenceUnknown, match='PROFILE_CREATE_FAILED'):
        with check_driver_browser.fresh_browser_profile(tmp_path):
            pytest.fail('Denied profile was used')
    assert len(attempted) == 1


def test_profile_is_new_per_case_and_removed_after_failure(tmp_path):
    from backend.app.infrastructure.check_driver_browser import fresh_browser_profile

    with fresh_browser_profile(tmp_path) as first:
        from pathlib import Path

        original = Path(first)
        (original / 'prior-case').write_bytes(b'private test state')
    assert not original.exists()
    with pytest.raises(RuntimeError, match='case failed'):
        with fresh_browser_profile(tmp_path) as second:
            assert second != first and list(Path(second).iterdir()) == []
            raise RuntimeError('case failed')
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('identity', [True, 0, 2, '1'])
def test_browser_transport_never_writes_or_stops_another_original_process(tmp_path, identity):
    pipe = PipeChromium(tmp_path)
    calls = []
    pipe._context = SimpleNamespace(_generation=3)
    pipe._browser_id = 1
    pipe._browser = SimpleNamespace(write=lambda value: calls.append(value))
    with pytest.raises(CheckEvidenceUnknown, match='PROCESS_REQUIRED'):
        pipe._event({'event': 'BROWSER_WRITE', 'epoch': 3, 'browser': identity, 'data': 'YQ=='})
    assert calls == []


def test_sdk_pipe_handles_partial_os_writes_without_truncation(tmp_path):
    import io, json, struct
    from threading import Thread

    class PartialPipe:
        def __init__(self):
            self.raw = io.BytesIO()

        def write(self, data):
            return self.raw.write(data[:7])

        def flush(self):
            pass

    sink = PartialPipe()
    pipe = PipeChromium(tmp_path)
    pipe._process = SimpleNamespace(stdin=sink)
    worker = Thread(target=pipe._write_frames)
    worker.start()
    try:
        pipe._incoming.put({'id': 1, 'result': None})
        pipe.rpc('LOCATOR', {'value': '中文' * 100}, timeout=2000)
        value = sink.raw.getvalue()
        assert struct.unpack('<I', value[:4])[0] == len(value) - 4
        assert json.loads(value[4:]) == {'id': 1, 'op': 'LOCATOR', 'value': {'value': '中文' * 100}}
    finally:
        pipe._closed = True
        worker.join(timeout=2)
        assert not worker.is_alive()


def test_running_browser_profile_is_retained_for_original_guard_stop(tmp_path):
    from pathlib import Path
    from backend.app.infrastructure.check_driver_browser import fresh_browser_profile

    with pytest.raises(CheckEvidenceUnknown, match='PROFILE_STOP_REQUIRED'):
        with fresh_browser_profile(tmp_path, can_remove=lambda: False) as profile:
            held = Path(profile)
            (held / 'owned-browser').write_bytes(b'original active process')
    assert (held / 'owned-browser').read_bytes() == b'original active process'


def test_failed_launch_stops_original_browser_before_profile_cleanup(tmp_path, monkeypatch):
    calls = []
    pipe = PipeChromium(tmp_path)
    browser = SimpleNamespace(stderr=b'bounded error', close=lambda: calls.append('stopped'))

    def failed(*args, **kwargs):
        pipe._browser = browser
        raise CheckEvidenceUnknown('ORIGINAL_SDK_OPERATION_FAILED')

    monkeypatch.setattr(pipe, 'rpc', failed)
    with pytest.raises(CheckEvidenceUnknown, match='SDK_OPERATION_FAILED'):
        pipe.launch_persistent_context(
            str(tmp_path / 'profile'),
            executable_path='fixed',
            chromium_sandbox=True,
            headless=True,
            service_workers='block',
            accept_downloads=False,
            args=[],
            timeout=100,
        )
    assert calls == ['stopped']
    assert pipe.profile_can_remove() and pipe._context is None
    assert pipe._last_browser_stderr == b'bounded error'


def test_browser_write_ack_follows_complete_physical_short_writes(tmp_path, monkeypatch):
    import base64, os, queue
    from threading import Thread
    from types import SimpleNamespace
    from backend.app.infrastructure.check_driver_browser_process import BrowserPipeProcess

    sent, writes = [], []
    source = BrowserPipeProcess(tmp_path, tmp_path, {}, lambda op, value: sent.append((op, value)))
    source.process = SimpleNamespace(poll=lambda: None)
    source._write_fd = 123456

    def partial(fd, data):
        assert fd == 123456
        writes.append(bytes(data))
        return min(2, len(data))

    monkeypatch.setattr(os, 'write', partial)
    source.write(base64.b64encode(b'abcdef').decode('ascii'), sequence=1)
    assert source._acks.empty() and sent == []
    worker = Thread(target=source._write)
    worker.start()
    try:
        assert source._acks.get(timeout=2) == 1
        assert writes == [b'abcdef', b'cdef', b'ef'] and sent == []
        source._acks.put_nowait(1)
        source.poll()
        assert sent == [('BROWSER_WRITTEN', {'write': 1})]
        for invalid in (True, 0, 1, 3):
            with pytest.raises(CheckEvidenceUnknown, match='WRITE_SEQUENCE_REQUIRED'):
                source.write(base64.b64encode(b'x').decode('ascii'), sequence=invalid)
    finally:
        source._closed = True
        worker.join(timeout=2)
        assert not worker.is_alive()
