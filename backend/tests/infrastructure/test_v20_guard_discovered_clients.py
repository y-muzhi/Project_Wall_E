"""Actual connected-client discovery and pre-frame rejection, with owned pipe clients."""

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.infrastructure import guard_control_git_host as host_module
from backend.app.infrastructure.guard_controller_records import GuardControllerRecords
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal, LaunchOutcomeUnknown
from backend.app.infrastructure.windows_executable_pin import ExecutablePin
from backend.app.infrastructure.windows_pipe_peer import PipePeerError
from backend.app.infrastructure.windows_private_package import (
    create_private_package,
    current_operator_sid,
)
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.tests.infrastructure import test_v20_guard_control_git_transport as transport
from backend.tests.infrastructure.test_v20_windows_guard_pipe_io import client_owner

tmp_path = transport.tmp_path
program_port = transport.program_port


@pytest.mark.parametrize('failure', ['wrong-image', 'cancel-after-connect', 'retained-owner'])
def test_unadmitted_connected_client_cannot_consume_a_frame_or_replace_the_endpoint(
    tmp_path, monkeypatch, program_port, failure
):
    with ObservedProcess(os.getpid()) as process:
        image = Path(process.identity.image_path)
    raw = image.read_bytes()
    if failure == 'wrong-image':
        image = tmp_path / 'registered-backend.exe'
        with image.open('xb') as stream:
            stream.write(raw)
    monkeypatch.setattr(
        host_module,
        'open_registered_backend_image',
        lambda *args, **kwargs: ExecutablePin(
            image, expected_byte_count=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest()
        ),
    )
    cancelled = False
    closed = []

    class Retained:
        def close(self):
            closed.append(True)

    retained = Retained()
    discover = host_module.discover_registered_pipe_client

    @contextmanager
    def interrupted(*args, **kwargs):
        nonlocal cancelled
        if failure == 'retained-owner':
            error = PipePeerError('INJECTED_DISCOVERY_CLOSE_UNVERIFIED')
            error.retained_owner = retained
            raise error
        with discover(*args, **kwargs) as backend:
            cancelled = True
            yield backend

    if failure != 'wrong-image':
        monkeypatch.setattr(host_module, 'discover_registered_pipe_client', interrupted)
    reference = uuid4().hex + uuid4().hex
    journal_path = create_private_package(tmp_path / 'guard-journal')
    with LaunchJournal(journal_path) as journal, GuardControllerRecords(journal) as records:
        host = host_module.GuardControlGitHost(
            records,
            reference,
            backend_sid=current_operator_sid(),
            package_root=tmp_path,
            manifest_sha256='a' * 64,
        )
        original = host._endpoint._handle
        directory = tmp_path / 'unadmitted-client'
        directory.mkdir()
        try:
            with client_owner(directory, host, 'SILENT') as client:
                client.start()
                error_type = (
                    LaunchOutcomeUnknown if failure == 'cancel-after-connect' else PipePeerError
                )
                with pytest.raises(error_type) as failed:
                    host.accept_registered(timeout_ms=10000, cancelled=lambda: cancelled)
                assert failed.value.retained_owner is host
                assert host._session == 'UNADMITTED'
                assert host._frames is None and host._backend is None
                assert host._server._owners == {}
                assert client.ready().observe().state == 'RUNNING'
                if failure == 'retained-owner':
                    assert host._orphans == [retained]
                    host.close()
                    assert closed == [True]
                else:
                    host.retire_session()
                    assert host._endpoint._handle == original
                    assert host._session is None
                    assert client.ready().observe().state == 'RUNNING'
        finally:
            host.close()


@pytest.mark.parametrize('mode', ['FRAME_BAD_JSON', 'FRAME_BAD_SIZE', 'SILENT', 'EXITED_BACKEND'])
def test_poisoned_original_stream_can_retire_without_replaying_any_request(
    tmp_path, monkeypatch, program_port, mode
):
    with ObservedProcess(os.getpid()) as process:
        image = Path(process.identity.image_path)
    raw = image.read_bytes()
    monkeypatch.setattr(
        host_module,
        'open_registered_backend_image',
        lambda *args, **kwargs: ExecutablePin(
            image, expected_byte_count=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest()
        ),
    )
    reference = uuid4().hex + uuid4().hex
    journal_path = create_private_package(tmp_path / 'failed-stream-journal')
    with LaunchJournal(journal_path) as journal, GuardControllerRecords(journal) as records:
        host = host_module.GuardControlGitHost(
            records,
            reference,
            backend_sid=current_operator_sid(),
            package_root=tmp_path,
            manifest_sha256='a' * 64,
        )
        original = host._endpoint._handle
        directory = tmp_path / 'poisoned-client'
        directory.mkdir()
        try:
            with client_owner(
                directory, host, 'SILENT' if mode == 'EXITED_BACKEND' else mode
            ) as client:
                client.start()
                host.accept_registered(timeout_ms=10000, cancelled=lambda: False)
                if mode == 'EXITED_BACKEND':
                    backend = client.ready()
                    client.job.terminate_owned(1)
                    assert backend._kernel.WaitForSingleObject(backend._handle, 8000) == 0
                with pytest.raises(RuntimeError):
                    host.serve(timeout_ms=300, cancelled=lambda: False)
                assert host._session == 'FAILED'
                assert host._frames._failed
                assert host._server._owners == {}
                assert client.ready().observe().state == (
                    'EXITED' if mode == 'EXITED_BACKEND' else 'RUNNING'
                )
                host.retire_failed_session()
                assert host._session is None and host._frames is None
                assert host._server._retained == []
                assert host._endpoint._handle == original
                assert client.ready().observe().state == (
                    'EXITED' if mode == 'EXITED_BACKEND' else 'RUNNING'
                )
        finally:
            host.close()
