"""Run a pre-bound Uvicorn server with a confirmed ASGI shutdown result."""

from socket import socket

from uvicorn import Server


def run_owned_server(server: Server, listener: socket) -> int:
    server.run(sockets=[listener])
    lifecycle = server.lifespan
    if (
        not server.started
        or not lifecycle.shutdown_event.is_set()
        or lifecycle.shutdown_failed
        or lifecycle.error_occurred
    ):
        return 2
    return 0
