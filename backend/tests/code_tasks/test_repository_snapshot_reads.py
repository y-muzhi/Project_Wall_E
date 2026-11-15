"""Snapshot request lifetime tests without opening a Guard connection."""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from starlette.requests import Request

from backend.app.code_tasks import repository_snapshot_reads as reads


def test_disconnect_signals_the_original_read_after_request_parsing():
    async def exercise():
        async def receive():
            return {'type': 'http.disconnect'}

        request = Request(
            {
                'type': 'http',
                'method': 'GET',
                'path': '/api/v1/code-snapshots/1',
                'headers': [],
                'app': SimpleNamespace(state=SimpleNamespace()),
            },
            receive=receive,
        )

        async def boundary(original, request_type, response_type, invoke):
            assert original is request and not request._is_disconnected
            return await asyncio.to_thread(invoke, object(), reads.SnapshotRequest(1))

        def snapshot(_runtime, parsed, _worker, cancelled):
            assert parsed.snapshot_id == 1
            assert cancelled.wait(2)
            return 'cancelled read'

        with (
            patch.object(reads, 'handle_http', boundary),
            patch.object(reads, '_snapshot', snapshot),
        ):
            result = await reads.snapshot_http(request)
        assert result == 'cancelled read'

    asyncio.run(exercise())
