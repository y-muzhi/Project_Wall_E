"""Offline checks for the one-shot diagnostic; no real credentials or requests."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import httpx

spec = importlib.util.spec_from_file_location('model_smoke', Path(__file__).with_name('model-smoke.py'))
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
KEY = 'synthetic-offline-test-key'


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def observe(self, status, envelope):
        requests = []
        def handler(request):
            requests.append(request)
            self.assertEqual(str(request.url), smoke.ENDPOINT)
            self.assertEqual(json.loads(request.content), smoke.BODY)
            return httpx.Response(status, json=envelope)
        result = await smoke.invoke(KEY, transport=httpx.MockTransport(handler))
        self.assertEqual(len(requests), 1)
        self.assertNotIn(KEY, json.dumps(result))
        return result

    async def test_success_and_fixed_caps(self):
        result = await self.observe(200, {'model': smoke.MODEL, 'choices': [
            {'message': {'role': 'assistant', 'content': 'OK'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 30, 'completion_tokens': 1, 'total_tokens': 31}})
        self.assertTrue(result['passed'])
        self.assertEqual(result['usage']['completion_tokens'], 1)
        self.assertEqual(smoke.BODY['max_tokens'], 128)
        self.assertEqual(smoke.BODY['thinking'], {'type': 'disabled'})
        self.assertLessEqual(sum(len(m['content'].encode('utf-8')) for m in smoke.BODY['messages']), 200)

    async def test_error_and_redirect_stop_without_retry(self):
        for status in (401, 429, 302, 503):
            result = await self.observe(status, {'error': {'code': KEY}})
            self.assertEqual(result['outcome'], 'HTTP_ERROR')
            self.assertEqual(result['error_code'], '[REDACTED]')

    async def test_wrong_model_and_credential_echo_are_not_accepted(self):
        result = await self.observe(200, {'model': 'wrong', 'choices': [
            {'message': {'role': 'assistant', 'content': KEY}, 'finish_reason': 'stop'}]})
        self.assertFalse(result['passed'])
        self.assertEqual(result['reply'], '[REDACTED]')

    async def test_non_object_response_rejected(self):
        result = await self.observe(200, [])
        self.assertEqual(result['outcome'], 'RESPONSE_PROTOCOL')

    async def test_timeout_is_unknown_one_request(self):
        requests = []
        def handler(request):
            requests.append(request)
            raise httpx.ReadTimeout('synthetic', request=request)
        result = await smoke.invoke(KEY, transport=httpx.MockTransport(handler))
        self.assertEqual(len(requests), 1)
        self.assertEqual(result['outcome'], 'TRANSPORT_UNKNOWN')

    async def test_response_capacity_stops(self):
        result = await smoke.invoke(KEY, transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b'x' * 65537)))
        self.assertEqual(result['outcome'], 'RESPONSE_CAPACITY')


class LocalFileTests(unittest.TestCase):
    def test_credential_parsing_and_exclusive_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env.local'
            path.write_text('WALLE_MODEL_API_KEY="' + KEY + '"\n', encoding='utf-8')
            self.assertEqual(smoke.credential(path), KEY)
            path.write_text('WALLE_MODEL_API_KEY=x\nWALLE_MODEL_API_KEY=y\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                smoke.credential(path)
            record = Path(directory) / 'prepared.json'
            smoke.save(record, {'prepared': True})
            with self.assertRaises(FileExistsError):
                smoke.save(record, {'prepared': False})
            self.assertEqual(json.loads(record.read_text(encoding='utf-8')), {'prepared': True})


if __name__ == '__main__':
    unittest.main(verbosity=2)
