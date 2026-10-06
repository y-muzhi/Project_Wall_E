"""Real loopback TCP counts protocol, isolation and cancellation; no Ark calls."""
import asyncio
from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Event, Thread
import unittest
from unittest.mock import patch

import httpx

from backend.app.infrastructure.model_profile import ModelProfile, MODEL_ID
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.infrastructure.tokenization import TokenizationGateway, ENDPOINT

KEY = 'local-count-test-credential-only'
TEXTS = ('中文😀', '{"text":"原文\\n😀"}', '完整系统文本')


def envelope():
    return {'object': 'list', 'id': 'local-count-wire-id', 'model': MODEL_ID, 'created': 1791289200,
            'data': [{'object': 'tokenization', 'index': index, 'total_tokens': 2,
                      'token_ids': [10, 11], 'offset_mapping': [[0, 1], [1, 2]]} for index in range(len(TEXTS))]}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *args): pass
    def do_POST(self):
        self.server.receipts.append({'path': self.path, 'body': self.rfile.read(int(self.headers['Content-Length'])),
                                     'authorization': self.headers.get('Authorization')})
        self.server.entered.set()
        if self.server.hold:
            self.connection.settimeout(3)
            try:
                if self.connection.recv(1) == b'': self.server.peer_closed.set()
            except OSError: pass
            self.close_connection = True
            return
        body = self.server.body
        self.send_response(self.server.status)
        self.send_header('Content-Length', str(len(body))); self.send_header('Content-Type', 'application/json')
        self.end_headers()
        try: self.wfile.write(body)
        except OSError: pass


class Forward(httpx.AsyncBaseTransport):
    def __init__(self, owner):
        self.owner = owner; self.inner = httpx.AsyncHTTPTransport(retries=0, trust_env=False); self.closed = False
    async def handle_async_request(self, request):
        body = await request.aread()
        self.owner.observed.append({'url': str(request.url), 'body': body, 'extensions': deepcopy(request.extensions)})
        return await self.inner.handle_async_request(httpx.Request(request.method,
            f'http://127.0.0.1:{self.owner.server.server_port}/controlled-count', headers=request.headers,
            content=body, extensions=deepcopy(request.extensions)))
    async def aclose(self):
        await self.inner.aclose(); self.closed = True


class TokenizationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); self.server.daemon_threads = True
        self.server.receipts = []; self.server.body = json.dumps(envelope(), ensure_ascii=False).encode()
        self.server.status = 200; self.server.hold = False; self.server.entered = Event(); self.server.peer_closed = Event()
        self.thread = Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.observed = []; self.transports = []
        def factory():
            transport = Forward(self); self.transports.append(transport); return transport
        self.gateway = TokenizationGateway(transport_factory=factory); self.profile = ModelProfile(KEY)

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(3)

    async def test_exact_unicode_batch_fixed_endpoint_version_and_audit_hashes(self):
        original = json.dumps({'model': MODEL_ID, 'text': list(TEXTS)}, ensure_ascii=False, separators=(',', ':')).encode()
        receipt = await self.gateway.count(self.profile, TEXTS)
        self.assertEqual(receipt.counts, (2, 2, 2))  # Controlled fixture, not actual tokenizer accuracy.
        self.assertEqual(receipt.text_sha256, tuple(hashlib.sha256(text.encode()).hexdigest() for text in TEXTS))
        self.assertEqual(receipt.request_sha256, hashlib.sha256(original).hexdigest())
        self.assertEqual(self.server.receipts[0]['body'], original)
        self.assertEqual(self.server.receipts[0]['authorization'], 'Bearer '+KEY)
        self.assertEqual(self.observed[0]['url'], ENDPOINT)
        self.assertEqual(self.observed[0]['extensions']['timeout'], {'connect': 10, 'read': 180, 'write': 10, 'pool': 10})
        self.assertEqual(receipt.evidence['response'], envelope())
        self.assertNotIn(KEY, repr(receipt)); self.assertNotIn(KEY, json.dumps(receipt.evidence))
        self.assertTrue(all(transport.closed for transport in self.transports))

    async def test_missing_wrong_model_and_unknown_counts_fail_without_retry_or_chat(self):
        bad = []
        value = envelope(); value['model'] = 'doubao-seed-2-1-pro'; bad.append(value)
        value = envelope(); del value['model']; bad.append(value)
        for count in (None, True, -1, '2', 2.0, 9007199254740992):
            value = envelope(); value['data'][0]['total_tokens'] = count; bad.append(value)
        value = envelope(); value['data'][0]['index'] = True; bad.append(value)
        value = envelope(); value['data'].reverse(); bad.append(value)
        value = envelope(); value['data'].pop(); bad.append(value)
        value = envelope(); value['data'][0]['token_ids'] = [10]; bad.append(value)
        value = envelope(); value['data'][0]['offset_mapping'][0] = [2, 1]; bad.append(value)
        for body in bad:
            with self.subTest(body=body):
                self.server.body = json.dumps(body).encode(); before = len(self.server.receipts)
                with self.assertRaises(ConfigInvalid): await self.gateway.count(self.profile, TEXTS)
                self.assertEqual(len(self.server.receipts), before+1)
        self.assertTrue(all(row['url'] == ENDPOINT for row in self.observed))
        self.assertTrue(all(transport.closed for transport in self.transports))

    async def test_http_failures_redirect_malformed_and_capacity_never_retry(self):
        for status, body in ((429, envelope()), (503, envelope()), (307, envelope()), (200, []), (200, {'error': {'message': KEY}})):
            self.server.status = status; self.server.body = json.dumps(body).encode(); before = len(self.server.receipts)
            with self.assertRaises(ConfigInvalid) as failure: await self.gateway.count(self.profile, TEXTS)
            self.assertNotIn(KEY, str(failure.exception)); self.assertEqual(len(self.server.receipts), before+1)
        self.server.body = b'{"model":null,"model":null}'
        with self.assertRaises(ConfigInvalid): await self.gateway.count(self.profile, TEXTS)
        self.server.body = b' ' * 500
        with patch('backend.app.infrastructure.tokenization.MAX_AUDIT_BYTES', 256):
            with self.assertRaises(ConfigInvalid): await self.gateway.count(self.profile, TEXTS)

    async def test_audit_redacts_secrets_and_rejects_credential_trace(self):
        value = envelope(); value['authorization'] = KEY; value['extra'] = KEY
        self.server.body = json.dumps(value).encode(); receipt = await self.gateway.count(self.profile, TEXTS)
        self.assertNotIn(KEY, receipt.response_json); self.assertNotIn('authorization', receipt.evidence['response'])
        value['id'] = KEY; self.server.body = json.dumps(value).encode()
        with self.assertRaises(ConfigInvalid): await self.gateway.count(self.profile, TEXTS)

    async def test_invalid_input_never_opens_a_connection(self):
        for texts in ((), [*TEXTS], (True,), ('\ud800',)):
            with self.assertRaises(ConfigInvalid): await self.gateway.count(self.profile, texts)
        self.assertEqual(self.observed, []); self.assertEqual(self.transports, [])

    async def test_cancel_closes_actual_connection_and_does_not_retry(self):
        self.server.hold = True
        task = asyncio.create_task(self.gateway.count(self.profile, TEXTS))
        self.assertTrue(await asyncio.to_thread(self.server.entered.wait, 3))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(await asyncio.to_thread(self.server.peer_closed.wait, 3))
        self.assertEqual(len(self.server.receipts), 1)
        self.assertTrue(all(transport.closed for transport in self.transports))
