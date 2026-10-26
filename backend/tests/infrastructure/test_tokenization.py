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

from backend.app.infrastructure.model_profile import ModelProfile, MODEL_ID, DEEPSEEK_MODEL_ID, DEFAULT_PROFILE
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.infrastructure.tokenization import TokenizationGateway, ENDPOINT, ExactCountUnavailable

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
        for key,value in getattr(self.server,'response_headers',{}).items():self.send_header(key,value)
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
            self.assertIsInstance(failure.exception, ExactCountUnavailable)
            self.assertEqual(failure.exception.reason, 'HTTP_STATUS' if status != 200 else 'INVALID_RESPONSE')
            self.assertEqual(failure.exception.http_status, status if status != 200 else None)
        self.server.body = b'{"model":null,"model":null}'
        with self.assertRaises(ConfigInvalid): await self.gateway.count(self.profile, TEXTS)
        self.server.body = b' ' * 500
        with patch('backend.app.infrastructure.tokenization.COUNT_RESPONSE_BYTES', 256):
            with self.assertRaises(ExactCountUnavailable) as failure: await self.gateway.count(self.profile, TEXTS)
            self.assertEqual(failure.exception.reason, 'RESPONSE_CAPACITY')

    async def test_provider_text_capacity_uses_aggregate_utf8_bytes_before_transport(self):
        profile = ModelProfile(KEY, DEFAULT_PROFILE)
        # Exact cap passes even though escaped JSON is larger; repeated texts
        # count independently. Multibyte and empty diagnostics keep their bytes.
        texts = ('汉'*100000, 'a'*499996, '😀', '')
        value = envelope();value['model'] = DEEPSEEK_MODEL_ID
        value['data'].append({**value['data'][0], 'index': 3})
        self.server.body = json.dumps(value).encode()
        await self.gateway.count(profile, texts)
        self.assertEqual(len(self.server.receipts), 1)
        with self.assertRaises(ExactCountUnavailable) as failure:
            await self.gateway.count(profile, (*texts, 'x'))
        self.assertEqual(failure.exception.reason, 'PROVIDER_INPUT_LIMIT')
        self.assertIsNone(failure.exception.http_status)
        self.assertEqual(len(self.server.receipts), 1)
        self.assertEqual(len(self.transports), 1)
        # No provider evidence for this limit on the legacy model.
        value['model'] = MODEL_ID;self.server.body = json.dumps(value).encode()
        await self.gateway.count(self.profile, (texts[0], texts[1]+'x', texts[2], texts[3]))
        self.assertEqual(len(self.server.receipts), 2)

    async def test_large_validated_response_retains_summary_without_relaxing_audit_capacity(self):
        from backend.app.infrastructure.tokenization import restore_measurement
        value = envelope();value['extra'] = 'not retained '*80
        self.server.body = json.dumps(value).encode()
        with patch('backend.app.infrastructure.tokenization.MAX_AUDIT_BYTES', 256), \
                patch('backend.app.infrastructure.audit_data.MAX_AUDIT_BYTES', 700):
            receipt = await self.gateway.count(self.profile, TEXTS)
        self.assertIsNotNone(receipt.response_digest)
        self.assertNotIn('response', receipt.evidence)
        self.assertNotIn('not retained', json.dumps(receipt.evidence))
        self.assertEqual(restore_measurement(receipt.evidence, TEXTS, expected_model=MODEL_ID,
            raw_required=False).evidence, receipt.evidence)
        with self.assertRaises(ConfigInvalid):
            restore_measurement(receipt.evidence, TEXTS, expected_model=MODEL_ID)
        self.assertEqual(len(self.server.receipts), 1)

    async def test_real_capacity_large_arrays_are_fully_validated_before_summary(self):
        from backend.app.infrastructure.tokenization import restore_measurement
        from backend.app.infrastructure.audit_data import MAX_AUDIT_BYTES
        profile = ModelProfile(KEY, DEFAULT_PROFILE);texts = ('x',)*8
        counts = [1000, 140000, 1, 0, 140000, 0, 1, 1]
        value = {'object': 'list', 'model': profile.model_name, 'id': 'large-loopback-only', 'created': 1,
            'data': [{'object': 'tokenization', 'index': index, 'total_tokens': count,
                'token_ids': [12345]*count, 'offset_mapping': [[100000, 100001]]*count}
                for index, count in enumerate(counts)]}
        self.server.body = json.dumps(value, separators=(',', ':')).encode()
        self.assertGreater(len(self.server.body), MAX_AUDIT_BYTES)
        self.assertLess(len(self.server.body), 8*1024*1024)
        receipt = await self.gateway.count(profile, texts)
        self.assertEqual(list(receipt.counts), counts)
        self.assertIsNotNone(receipt.response_digest)
        self.assertEqual(restore_measurement(receipt.evidence, texts, raw_required=False,
            expected_model=profile.model_name).evidence, receipt.evidence)
        # Even the final array is checked; a large response is never accepted
        # merely because an early count field looks sufficient for rejection.
        value['data'][-1]['offset_mapping'] = [[True, 100001]]
        self.server.body = json.dumps(value, separators=(',', ':')).encode()
        with self.assertRaises(ExactCountUnavailable) as failure:await self.gateway.count(profile, texts)
        self.assertEqual(failure.exception.reason, 'INVALID_RESPONSE')
        self.assertEqual(len(self.server.receipts), 2)

    async def test_failed_http_preserves_bounded_private_parameter_details_after_redaction(self):
        self.server.status=400;self.server.response_headers={'x-request-id':'local-error-trace'}
        message='x'*2040+KEY+' input length exceeds the provider limit'
        self.server.body=json.dumps({'error':{'code':'InvalidParameter','param':'text','message':message,
            'authorization':KEY,'reasoning_content':'MUST_NOT_KEEP'},'irrelevant':'MUST_NOT_KEEP'}).encode()
        with self.assertRaises(ExactCountUnavailable) as failure:await self.gateway.count(self.profile,TEXTS)
        error=failure.exception;detail=error.provider_error
        self.assertEqual((error.reason,error.http_status,detail['category'],detail['code'],detail['parameter']),
            ('HTTP_STATUS',400,'PARAMETER','InvalidParameter','text'))
        self.assertEqual(detail['body_state'],'JSON_ERROR');self.assertEqual(detail['request_id'],'local-error-trace')
        self.assertEqual(len(detail['message']),2048);self.assertTrue(detail['message_truncated'])
        self.assertNotIn(KEY[:12],detail['message']);self.assertNotIn('MUST_NOT_KEEP',json.dumps(detail))
        self.assertNotIn(message,str(error));self.assertNotIn(message,repr(error))
        detail['message']='changed';self.assertNotEqual(error.provider_error['message'],'changed')
        self.assertEqual(len(self.server.receipts),1)

    async def test_http_error_details_never_repair_partial_json_or_echo_credentials_in_identities(self):
        self.server.status=400
        for body,state in ((b'{"error":{"code":"InvalidParameter","code":"other"}}','INVALID_JSON'),
                (b'<html>private failure</html>','INVALID_JSON'),(b' '*16385,'OVERSIZED'),(b'{}','NO_ERROR_OBJECT')):
            self.server.body=body;before=len(self.server.receipts)
            with self.assertRaises(ExactCountUnavailable) as failure:await self.gateway.count(self.profile,TEXTS)
            self.assertEqual(failure.exception.provider_error['body_state'],state)
            self.assertIsNone(failure.exception.provider_error['message']);self.assertEqual(len(self.server.receipts),before+1)
        self.server.response_headers={'x-request-id':KEY}
        self.server.body=json.dumps({'error':{'code':KEY,'param':KEY,'message':KEY}}).encode()
        with self.assertRaises(ExactCountUnavailable) as failure:await self.gateway.count(self.profile,TEXTS)
        detail=failure.exception.provider_error
        self.assertIsNone(detail['code']);self.assertIsNone(detail['parameter']);self.assertIsNone(detail['request_id'])
        self.assertNotIn(KEY,json.dumps(detail))

    async def test_failed_http_status_survives_optional_error_body_read_timeout(self):
        class Broken(httpx.AsyncByteStream):
            closed=False
            async def __aiter__(self):
                yield b'{'
                raise httpx.ReadTimeout('not retained '+KEY)
            async def aclose(self):self.closed=True
        stream=Broken();requests=[]
        def respond(request):requests.append(request);return httpx.Response(400,stream=stream)
        gateway=TokenizationGateway(transport_factory=lambda:httpx.MockTransport(respond))
        with self.assertRaises(ExactCountUnavailable) as failure:await gateway.count(self.profile,TEXTS)
        self.assertEqual(failure.exception.reason,'HTTP_STATUS');self.assertEqual(failure.exception.http_status,400)
        self.assertEqual(failure.exception.provider_error['body_state'],'READ_UNAVAILABLE')
        self.assertTrue(stream.closed);self.assertEqual(len(requests),1)

    async def test_root_detail_and_metadata_error_shapes_retain_only_explanation_fields(self):
        self.server.status=400
        examples=[({'code':'InvalidParameter','message':'text length limit','param':'text'},'text length limit','text'),
            ({'detail':'text length limit'},'text length limit',None),
            ({'detail':[{'type':'string_too_long','loc':['body','text',0],
                'msg':'String should have at most 100 characters','input':'DO_NOT_RETAIN',
                'ctx':{'max_length':100}}]},'String should have at most 100 characters','body.text.0'),
            ({'ResponseMetadata':{'Error':{'Code':'InvalidParameter','Message':'text length limit'}}},'text length limit',None),
            ({'error':'text length limit'},'text length limit',None)]
        for body,message,parameter in examples:
            body['input']='DO_NOT_RETAIN';self.server.body=json.dumps(body).encode();before=len(self.server.receipts)
            with self.assertRaises(ExactCountUnavailable) as failure:await self.gateway.count(self.profile,TEXTS)
            detail=failure.exception.provider_error
            self.assertEqual(detail['body_state'],'JSON_ERROR');self.assertEqual(detail['message'],message)
            self.assertEqual(detail['parameter'],parameter);self.assertNotIn('DO_NOT_RETAIN',json.dumps(detail))
            self.assertEqual(len(self.server.receipts),before+1)
        self.server.body=json.dumps({'unexpected':'DO_NOT_RETAIN','input':'DO_NOT_RETAIN'}).encode()
        with self.assertRaises(ExactCountUnavailable) as failure:await self.gateway.count(self.profile,TEXTS)
        detail=failure.exception.provider_error
        self.assertEqual(detail['body_state'],'NO_ERROR_OBJECT');self.assertIsNone(detail['message'])
        self.assertEqual(detail['body_keys'],['input','unexpected'])

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
