"""Verify the isolated runtime launcher's result against the actual ASGI lifecycle."""

import runpy
import signal
import socket
import sys
from contextlib import asynccontextmanager, nullcontext
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from starlette.applications import Starlette
from uvicorn import Server

ENTRY = Path(__file__).resolve().parents[3] / 'tools/linux_runtime/serve_environment.py'


@pytest.mark.parametrize(
    ('failure', 'expected_exit', 'phases'),
    (
        (None, 0, ['startup', 'shutdown']),
        ('startup', 3, ['startup']),
        ('shutdown', 2, ['startup', 'shutdown']),
    ),
)
def test_owned_launcher_exit_reflects_actual_lifespan(monkeypatch, failure, expected_exit, phases):
    entry = runpy.run_path(str(ENTRY))
    observed = []

    @asynccontextmanager
    async def lifespan(_app):
        observed.append('startup')
        if failure == 'startup':
            raise RuntimeError('Isolated startup failure')
        yield
        observed.append('shutdown')
        if failure == 'shutdown':
            raise RuntimeError('Isolated shutdown failure')

    async def finish_without_requests(_server):
        pass

    monkeypatch.setattr(Server, 'main_loop', finish_without_requests)
    app = FastAPI(lifespan=lifespan)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0))
        if failure == 'startup':
            with pytest.raises(SystemExit) as stopped:
                entry['serve_application'](app, listener)
            assert stopped.value.code == expected_exit
        else:
            assert entry['serve_application'](app, listener) == expected_exit
    assert observed == phases


@pytest.mark.skipif(sys.platform != 'linux', reason='Management uses the Linux registry')
@pytest.mark.parametrize(
    ('failure', 'expected_exit', 'phases'),
    (
        (None, 0, ['startup', 'shutdown']),
        ('startup', 3, ['startup']),
        ('shutdown', 2, ['startup', 'shutdown']),
        ('forced', 2, ['startup']),
    ),
)
def test_management_launcher_exit_reflects_actual_lifespan(
    monkeypatch, failure, expected_exit, phases
):
    from backend.app.management import management_web

    observed = []

    @asynccontextmanager
    async def lifespan(_app):
        observed.append('startup')
        if failure == 'startup':
            raise RuntimeError('Isolated management startup failure')
        yield
        observed.append('shutdown')
        if failure == 'shutdown':
            raise RuntimeError('Isolated management shutdown failure')

    async def finish_without_requests(server):
        if failure == 'forced':
            server.handle_exit(signal.SIGINT, None)
            server.handle_exit(signal.SIGINT, None)

    monkeypatch.setattr(Server, 'main_loop', finish_without_requests)
    monkeypatch.setattr(management_web, 'Starlette', partial(Starlette, lifespan=lifespan))
    monkeypatch.setattr(management_web, 'read_registry', lambda *_args, **_options: nullcontext())
    monkeypatch.setattr(
        management_web, 'ManagementScope', lambda *_args: SimpleNamespace(respond=lambda *_: None)
    )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0))
        monkeypatch.setattr(
            management_web, 'listening_socket', lambda *_args: nullcontext(listener)
        )

        def serve_manager():
            return management_web.serve(None, None, None, None, None)

        if failure == 'startup':
            with pytest.raises(SystemExit) as stopped:
                serve_manager()
            assert stopped.value.code == expected_exit
        else:
            assert serve_manager() == expected_exit
    assert observed == phases
